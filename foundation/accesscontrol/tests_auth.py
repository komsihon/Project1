# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from urllib import unquote
from urlparse import urlparse

from django.conf import settings
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.template.defaultfilters import urlencode
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _
from ikwen.foundation.accesscontrol.middleware import TOKEN_CHUNK

from foundation.accesscontrol.backends import UMBRELLA
from ikwen.foundation.accesscontrol.models import Member
from ikwen.foundation.core.models import Service, Config


def wipe_test_data():
    """
    This test was originally built with django-nonrel 1.6 which had an error when flushing the database after
    each test. So the flush is performed manually with this custom tearDown()
    """
    import ikwen.foundation.core.models
    import ikwen.foundation.accesscontrol.models
    for alias in getattr(settings, 'DATABASES').keys():
        for name in ('Application', 'Service', 'Config', 'ConsoleEventType', 'ConsoleEvent', 'Country', ):
            model = getattr(ikwen.foundation.core.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Member', 'AccessRequest', ):
            model = getattr(ikwen.foundation.accesscontrol.models, name)
            model.objects.using(alias).all().delete()


# DATABASES = {
#    'default': {
#        'ENGINE': 'django_mongodb_engine',
#        'NAME': 'test_registered_member',
#    },
#    'umbrella': {
#        'ENGINE': 'django_mongodb_engine',
#        'NAME': 'test_ikwen_umbrella',
#    }
# }
DATABASES = getattr(settings, 'DATABASES')
DATABASES['default'] = {
   'ENGINE': 'django_mongodb_engine',
   'NAME': 'ikwen',
}
DATABASES['umbrella'] = {
   'ENGINE': 'django_mongodb_engine',
   'NAME': 'ikwen_umbrella',
}
setattr(settings, 'DATABASES', DATABASES)


class IkwenAuthTestCase(unittest.TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_login_with_wrong_credentials_and_no_prior_get_parameters(self):
        """
        Wrong parameters set the login_form in context
        """
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('ikwen:sign_in'), {'username': 'arch', 'password': 'wrong'}, follow=True)
        self.assertIsNotNone(response.context['login_form'])

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', LOGIN_REDIRECT_URL=None)
    def test_login_with_correct_credentials_and_no_prior_get_parameters(self):
        """
        Login in with no prior GET parameters should redirect to console page
        """
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('ikwen:sign_in'), {'username': 'member3', 'password': 'admin'}, follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-2]
        self.assertEqual(location, 'console')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', LOGIN_REDIRECT_URL='ikwen:contact')
    def test_sign_in_with_user_already_logged_in_and_no_next_url(self):
        """
        If user is already logged in and LOGIN_REDIRECT_URL is set,
        he is redirected to that url rather than to his console
        """
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('ikwen:sign_in'), follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-1]
        self.assertEqual(location, 'console')

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_sign_in_with_user_already_logged_in_and_next_url(self):
        """
        If user is already logged in, he is taken to the next_url parameter
        """
        self.client.login(username='arch', password='admin')
        next_url = reverse('ikwen:contact')
        response = self.client.get(reverse('ikwen:sign_in') + '?next=' + urlencode(next_url), follow=True)
        final = response.redirect_chain[-1]
        location = final[0]
        self.assertEqual(location, 'http://testserver' + next_url)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_login_with_correct_credentials_and_next_url_having_other_get_parameters(self):
        """
        Login in with next_url GET parameter should redirect to next_url with its GET parameters kept
        """
        member = Member.objects.get(username='arch')
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = member.password[-TOKEN_CHUNK:-1]
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        contact_url = reverse('ikwen:contact')
        next_url = contact_url + '?p1=v1&p2=v2'
        origin = reverse('ikwen:sign_in') + '?next=' + urlencode(next_url)
        response = self.client.post(origin, {'username': 'arch', 'password': 'admin'}, follow=True)
        final = response.redirect_chain[-1]
        self.assertEqual(final[0], 'http://testserver' + next_url + '&key=' + uid + '&rand=' + token)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_middleware_hit_url_with_invalid_tokens(self):
        """
        Normally authenticated user is logged out redirected to the
        requested URL without key and token when those last two are invalid
        """
        member = Member.objects.get(username='arch')
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = member.password[-TOKEN_CHUNK:-1]
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        contact_url = reverse('ikwen:contact')
        next_url = contact_url + '?p1=v1&p2=v2'
        origin = reverse('ikwen:sign_in') + '?next=' + urlencode(next_url)
        self.client.post(origin, {'username': 'arch', 'password': 'admin'}, follow=True)
        origin_with_invalid_tokens = next_url + '&key=' + uid + '&rand=WrongToken'
        response = self.client.get(origin_with_invalid_tokens, follow=True)
        final = response.redirect_chain[-1]
        self.assertEqual(final[0], 'http://testserver' + next_url)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_login_with_wrong_credentials_get_parameters_and_next_url_having_other_get_parameters(self):
        """
        Wrong login credentials stays on the same page and keeps previous GET parameters that were
        available when landing on the login page
        """
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        contact_url = reverse('ikwen:contact')
        next_url = contact_url + '?p1=v1&p2=v2'
        query_string = 'next=' + urlencode(next_url) + '&par1=val1&par2=val2'
        origin = reverse('ikwen:sign_in') + '?' + query_string
        response = self.client.post(origin, {'username': 'arch', 'password': 'wrong'}, follow=True)
        self.assertGreaterEqual(response.request['PATH_INFO'].find('/signIn/'), 0)
        self.assertEqual(response.request['QUERY_STRING'], query_string)
        self.assertIsNotNone(response.context['login_form'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_register_with_password_mismatch(self):
        """
        Different password and confirmation set the passwordMismatch=yes GET parameter and prior GET parameters remain
        """
        origin = reverse('ikwen:register') + '?next=http://localhost/hotspot/config&p1=v1&p2=v2'
        response = self.client.post(origin, {'username': 'good', 'password': 'secret', 'password2': 'sec',
                                             'phone': '655045781', 'first_name': 'Sah', 'last_name': 'Fogaing'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.request['PATH_INFO'].find('/signIn/'), 0)
        params = unquote(response.request['QUERY_STRING']).split('&')
        self.assertGreaterEqual(params.index('passwordMismatch=yes'), 0)
        self.assertGreaterEqual(params.index('next=http://localhost/hotspot/config'), 0)
        self.assertGreaterEqual(params.index('p1=v1'), 0)
        self.assertGreaterEqual(params.index('p2=v2'), 0)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_register_with_wrong_email_password_phone_name(self):
        """
        Wrong parameters set the register_form in context with correct error and prior GET parameters remain
        """
        origin = reverse('ikwen:register') + '?next=http://localhost/hotspot/config&p1=v1&p2=v2'
        response = self.client.post(origin, {'username': 'wrong', 'email': 'wrong@email', 'password': '',
                                             'phone': '(+237)655045781', 'first_name': ''}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['register_form'].errors['email'])
        self.assertIsNotNone(response.context['register_form'].errors['password'])
        self.assertIsNotNone(response.context['register_form'].errors['password2'])
        self.assertIsNotNone(response.context['register_form'].errors['phone'])
        self.assertIsNotNone(response.context['register_form'].errors['first_name'])
        self.assertIsNotNone(response.context['register_form'].errors['last_name'])
        self.assertEqual(response.request['QUERY_STRING'], 'next=http://localhost/hotspot/config&p1=v1&p2=v2')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', LOGIN_REDIRECT_URL=None,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/ikwen/')
    def test_register_with_correct_values_next_url_and_other_get_parameters(self):
        """
        Correct parameters save user in default and foundation databases. Prior GET parameters remain
        """
        service = Service.objects.get(pk=getattr(settings, 'IKWEN_SERVICE_ID'))
        Config.objects.create(service=service, company_name='Project', contact_email='arch@ikwen.com',  signature='')
        contact_url = reverse('ikwen:contact')
        origin = reverse('ikwen:register') + '?next=' + urlencode(contact_url + '?p1=v1&p2=v2')
        response = self.client.post(origin, {'username': 'testuser1', 'password': 'secret', 'password2': 'secret',
                                             'phone': '655000001', 'first_name': 'Sah', 'last_name': 'Fogaing'}, follow=True)
        m1 = Member.objects.using(UMBRELLA).get(username='testuser1')
        m2 = Member.objects.get(username='testuser1')
        self.assertEqual(self.client.session['_auth_user_id'], m1.id)  # Test whether user is actually logged in
        self.assertEqual(m1.id, m2.id)
        self.assertEqual(m1.full_name, 'Sah Fogaing')
        final = urlparse(response.redirect_chain[-1][0])
        location = final.path.strip('/').split('/')[-1]
        self.assertEqual(location, 'contact')
        params = unquote(final.query).split('&')
        self.assertGreaterEqual(params.index('p1=v1'), 0)
        self.assertGreaterEqual(params.index('p2=v2'), 0)
        response = self.client.post(reverse('ikwen:sign_in'), {'username': 'testuser1', 'password': 'secret'}, follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-2]
        self.assertEqual(location, 'console')
        from pymongo import Connection
        cnx = Connection()
        cnx.drop_database('test_registered_member')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_update_info_with_existing_email(self):
        """
        User should be informed if changing e-mail to an existing one
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:update_info'), {'email': 'member3@ikwen.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps({'error': _('This e-mail already exists.')}))

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_update_info_with_existing_phone(self):
        """
        User should be informed if changing phone to an existing one
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:update_info'), {'phone': '677000003'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, json.dumps({'error': _('This phone already exists.')}))

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_update_gender_with_gender_previously_set(self):
        """
        User should not update gender when set
        """
        self.client.login(username='member2', password='admin')
        self.client.get(reverse('ikwen:update_info'), {'gender': Member.FEMALE})
        m = Member.objects.get(username='member2')
        self.assertEqual(m.gender, Member.MALE)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', DATABASES=DATABASES)
    def test_update_correct_parameters_and_gender_previously_unset(self):
        """
        All user information should be updated and correct information message returned
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:update_info'), {'email': 'u4@email.com', 'phone': '655000014',
                                                                  'gender': Member.MALE, 'name': 'Sah Fogaing'})
        self.assertEqual(response.content, json.dumps({'message': _('Your information were successfully updated.')}))
        m = Member.objects.get(email='u4@email.com')
        m1 = Member.objects.using(UMBRELLA).get(email='u4@email.com')
        self.assertEqual(m.phone, '655000014')
        self.assertEqual(m.gender, Member.MALE)
        self.assertEqual(m.first_name, 'Sah')
        self.assertEqual(m.last_name, 'Fogaing')
        self.assertEqual(m1.phone, '655000014')
        self.assertEqual(m1.gender, Member.MALE)
        self.assertEqual(m1.first_name, 'Sah')
        self.assertEqual(m1.last_name, 'Fogaing')
        from pymongo import Connection
        cnx = Connection()
        cnx.drop_database('test_registered_member')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_update_password_with_incorrect_current_password(self):
        """
        User must be informed when current password is incorrect
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:update_password'), {'password': 'wrong'})
        self.assertEqual(response.content, json.dumps({'error': _('The current password is incorrect!')}))

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_update_password_with_password_mismatch(self):
        """
        User should be informed when password and confirmation mismatch
        """
        Member.objects.create_user(username='member2', password='admin', phone='655000021')
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:update_password'), {'password': 'admin', 'password1': 'value1', 'password2': 'value2'})
        self.assertEqual(response.content, json.dumps({'error': _("Passwords don't match.")}))

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', DATABASES=DATABASES)
    def test_update_password_with_correct_values(self):
        self.assertTrue(self.client.login(username='member2', password='admin'))
        response = self.client.get(reverse('ikwen:update_password'), {'password': 'admin', 'password1': 'value', 'password2': 'value'})
        self.assertEqual(response.content, json.dumps({'message': _('Your password was successfully updated.')}))
        self.assertTrue(self.client.login(username='member2', password='value'))
        m2 = Member.objects.using(UMBRELLA).get(username='member2')
        self.assertTrue(m2.check_password('value'))
        from pymongo import Connection
        cnx = Connection()
        cnx.drop_database('test_registered_member')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_login_with_phone(self):
        """
        User can login using phone number and e-mail as well
        """
        self.assertTrue(self.client.login(username='member2', password='admin'))
        self.assertTrue(self.client.login(phone='677000002', password='admin'))

    @override_settings(DEBUG=True, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_account_setup_page(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:account_setup'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', DEBUG=True)
    def test_forgottenPassword(self):
        """
        Make sure the url is reachable
        """
        response = self.client.get(reverse('ikwen:forgotten_password'))
        self.assertEqual(response.status_code, 200)
