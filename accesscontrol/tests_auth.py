# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from urllib import unquote
from urlparse import urlparse

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.template.defaultfilters import urlencode
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest
from django.utils.translation import gettext as _
from permission_backend_nonrel.models import UserPermissionList

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member, COMMUNITY
from ikwen.core.models import Service, Config, OperatorWallet, ConsoleEventType
from ikwen.core.utils import add_database, get_service_instance
from ikwen.billing.models import MoMoTransaction
from ikwen.rewarding.models import ReferralRewardPack, Reward, CumulatedCoupon, CouponSummary
from ikwen.revival.models import MemberProfile

from echo.models import Balance


def wipe_test_data(db=None):
    """
    This test was originally built with django-nonrel 1.6 which had an error when flushing the database after
    each test. So the flush is performed manually with this custom tearDown()
    """
    import ikwen.core.models
    import ikwen.billing.models
    import ikwen.accesscontrol.models
    import ikwen.partnership.models
    import ikwen.revival.models
    import ikwen.rewarding.models
    import ikwen_kakocase.kakocase.models
    import permission_backend_nonrel.models
    import daraja.models
    OperatorWallet.objects.using('wallets').all().delete()
    MoMoTransaction.objects.using('wallets').all().delete()
    Balance.objects.using('wallets').all().delete()
    if db:
        aliases = [db]
    else:
        aliases = getattr(settings, 'DATABASES').keys()
    databases = getattr(settings, 'DATABASES')
    for alias in aliases:
        if alias == 'wallets':
            continue
        if not databases[alias]['NAME'].startswith('test_'):
            continue
        Group.objects.using(alias).all().delete()
        for name in ('Application', 'Service', 'Config', 'ConsoleEventType',
                     'ConsoleEvent', 'Country', ):
            model = getattr(ikwen.core.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Member', 'AccessRequest', 'OwnershipTransfer', ):
            model = getattr(ikwen.accesscontrol.models, name)
            model.objects.using(alias).all().delete()
        for name in ('UserPermissionList', 'GroupPermissionList',):
            model = getattr(permission_backend_nonrel.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Product', 'Payment', 'Invoice', 'Subscription',
                     'InvoicingConfig', 'PaymentMean', 'MoMoTransaction'):
            model = getattr(ikwen.billing.models, name)
            model.objects.using(alias).all().delete()
        for name in ('PartnerProfile', 'ApplicationRetailConfig'):
            model = getattr(ikwen.partnership.models, name)
            model.objects.using(alias).all().delete()
        for name in ('ProfileTag', 'ObjectProfile', 'MemberProfile', 'Revival', 'CyclicRevival',
                     'Target', 'CyclicTarget', ):
            model = getattr(ikwen.revival.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Coupon', 'CRBillingPlan', 'Reward', 'CumulatedCoupon', 'CouponSummary',
                     'CouponUse', 'CouponWinner', 'CRProfile', 'CROperatorProfile',
                     'JoinRewardPack', 'ReferralRewardPack', 'PaymentRewardPack', ):
            model = getattr(ikwen.rewarding.models, name)
            model.objects.using(alias).all().delete()
        for name in ('TsunamiBundle', 'OperatorProfile', ):
            model = getattr(ikwen_kakocase.kakocase.models, name)
            model.objects.using(alias).all().delete()
        for name in ('DarajaConfig', 'DaraRequest', 'Dara', 'Invitation', ):
            model = getattr(daraja.models, name)
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
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml', 'member_profiles.yaml']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_Register_page(self):
        """
        Register page must return http 200
        """
        response = self.client.get(reverse('ikwen:register'))
        self.assertEqual(response.status_code, 200)

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_login_with_wrong_credentials_and_no_prior_get_parameters(self):
        """
        Wrong parameters set the login_form in context
        """
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('ikwen:do_sign_in'), {'username': 'arch', 'password': 'wrong'}, follow=True)
        self.assertIsNotNone(response.context['login_form'])

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', LOGIN_REDIRECT_URL=None)
    def test_login_with_correct_uname_and_password_and_no_prior_get_parameters(self):
        """
        Login in with no prior GET parameters should redirect to console page
        """
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('ikwen:do_sign_in'), {'username': 'member3', 'password': 'admin'}, follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-1]
        self.assertEqual(location, 'console')

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', LOGIN_REDIRECT_URL=None)
    def test_login_with_correct_email_and_password_and_no_prior_get_parameters(self):
        """
        Login in with no prior GET parameters should redirect to console page
        """
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('ikwen:do_sign_in'), {'username': 'member3@ikwen.com', 'password': 'admin'},
                                    follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-1]
        self.assertEqual(location, 'console')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', LOGIN_REDIRECT_URL='ikwen:forgotten_password')
    def test_sign_in_with_user_already_logged_in_and_no_next_url(self):
        """
        If user is already logged in and LOGIN_REDIRECT_URL is set,
        he is redirected to that url rather than to his console
        """
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('ikwen:sign_in'), follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-1]
        self.assertEqual(location, 'forgottenPassword')

    @override_settings(DATABASES=DATABASES, IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_sign_in_with_user_already_logged_in_and_next_url(self):
        """
        If user is already logged in, he is taken to the next_url parameter
        """
        self.client.login(username='arch', password='admin')
        next_url = reverse('ikwen:forgotten_password')
        response = self.client.get(reverse('ikwen:sign_in') + '?next=' + urlencode(next_url), follow=True)
        final = response.redirect_chain[-1]
        location = final[0]
        self.assertEqual(location, 'http://testserver' + next_url)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_login_with_correct_credentials_and_next_url_having_other_get_parameters(self):
        """
        Login in with next_url GET parameter should redirect to next_url with its GET parameters kept
        """
        response = self.client.get(reverse('ikwen:sign_in'))
        self.assertEqual(response.status_code, 200)
        contact_url = reverse('ikwen:forgotten_password')
        next_url = contact_url + '?p1=v1&p2=v2'
        origin = reverse('ikwen:do_sign_in') + '?next=' + urlencode(next_url)
        response = self.client.post(origin, {'username': 'arch', 'password': 'admin'}, follow=True)
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
        contact_url = reverse('ikwen:forgotten_password')
        next_url = contact_url + '?p1=v1&p2=v2'
        query_string = 'next=' + urlencode(next_url) + '&par1=val1&par2=val2'
        origin = reverse('ikwen:do_sign_in') + '?' + query_string
        response = self.client.post(origin, {'username': 'arch', 'password': 'wrong'}, follow=True)
        self.assertEqual(response.request['QUERY_STRING'], query_string)
        self.assertIsNotNone(response.context['login_form'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_login_with_api_signature(self):
        """
        Authenticating with API Signature works as well and returns the member who created the service
        """
        service = get_service_instance()
        member = authenticate(api_signature=service.api_signature)
        self.assertEqual(service.member, member)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', AUTH_WITHOUT_PASSWORD=True)
    def test_login_with_correct_username_and_without_password(self):
        """
        Authenticating without password works only for non staff Users
        and setting AUTH_WITHOUT_PASSWORD set to True
        """
        Member.objects.filter(username='member3').update(is_staff=False)
        response = self.client.post(reverse('ikwen:do_sign_in'), {'username': 'member3', 'password': '**'}, follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-1]
        self.assertEqual(location, 'console')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', AUTH_WITHOUT_PASSWORD=True)
    def test_login_with_correct_username_only_and_user_is_staff(self):
        """
        Authenticating without username works only for non staff Users
        and setting AUTH_WITHOUT_PASSWORD set to True
        """
        Member.objects.filter(username='member3').update(is_staff=True)
        response = self.client.post(reverse('ikwen:do_sign_in'), {'username': 'member3', 'password': '**'})
        self.assertIsNotNone(response.context['error_message'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_register_with_password_mismatch(self):
        """
        Different password and confirmation brings back to the register page and prior GET parameters remain
        """
        origin = reverse('ikwen:register') + '?next=http://localhost/hotspot/config&p1=v1&p2=v2'
        response = self.client.post(origin, {'username': 'good', 'password': 'secret', 'password2': 'sec',
                                             'phone': '655045781', 'first_name': 'Sah', 'last_name': 'Fogaing'}, follow=True)
        self.assertEqual(response.status_code, 200)
        final = response.redirect_chain[-1][0]
        self.assertGreaterEqual(final.find('/register'), 0)
        params = unquote(response.request['QUERY_STRING']).split('&')
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
                       EMAIL_FILE_PATH='test_emails/ikwen/', IS_IKWEN=False)
    def test_register_with_correct_values_next_url_and_other_get_parameters(self):
        """
        Correct parameters save user in default and foundation databases. Prior GET parameters remain
        """
        import ikwen.conf.settings as ikwen_settings
        ikwen_settings.IKWEN_SERVICE_ID = getattr(settings, 'IKWEN_SERVICE_ID')
        service = Service.objects.get(pk=getattr(settings, 'IKWEN_SERVICE_ID'))
        Config.objects.create(service=service, company_name='Project', contact_email='arch@ikwen.com',  signature='')
        contact_url = reverse('ikwen:forgotten_password')
        origin = reverse('ikwen:register') + '?next=' + urlencode(contact_url + '?p1=v1&p2=v2')
        response = self.client.post(origin, {'username': 'Test.User1@domain.com', 'password': 'secret', 'password2': 'secret',
                                             'phone': '655000001', 'first_name': 'Sah', 'last_name': 'Fogaing'}, follow=True)
        m1 = Member.objects.using(UMBRELLA).get(username='test.user1@domain.com')
        m2 = Member.objects.get(email='test.user1@domain.com')
        self.assertEqual(self.client.session['_auth_user_id'], m1.id)  # Test whether user is actually logged in
        self.assertEqual(m1.id, m2.id)
        self.assertEqual(m1.full_name, 'Sah Fogaing')
        final = urlparse(response.redirect_chain[-1][0])
        location = final.path.strip('/').split('/')[-1]
        self.assertEqual(location, 'forgottenPassword')
        params = unquote(final.query).split('&')
        self.assertGreaterEqual(params.index('p1=v1'), 0)
        self.assertGreaterEqual(params.index('p2=v2'), 0)
        response = self.client.post(reverse('ikwen:do_sign_in'), {'username': 'test.user1@domain.com', 'password': 'secret'}, follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('?').strip('/').split('/')[-1]
        self.assertEqual(location, 'console')
        perm_list = UserPermissionList.objects.get(user=m2)
        group = Group.objects.get(name=COMMUNITY)
        self.assertIn(group.id, perm_list.group_fk_list)
        self.assertIn(group.id, m1.group_fk_list)
        self.assertIn(group.id, m2.group_fk_list)
        from pymongo import Connection
        cnx = Connection()
        cnx.drop_database('test_registered_member')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_register_with_existing_ghost_as_phone(self):
        """
        If a 'ghost' Member exists with the same email or phone, it is
        replaced with the one registering and profile information of
        the ghost are shift to the actual Member.
        Ghost is Member with is_ghost=True. Those member are created manually
        from the admin or when user leaves his mail on a website.        .
        """
        UserPermissionList.objects.all().delete()
        ghost = Member.objects.create_user(username='666000006', gender='Male', phone='666000006', is_ghost=True,
                                           first_name='Ngnieng', last_name='Makambou', password='secret')
        ghost_profile, update = MemberProfile.objects.get_or_create(member=ghost)
        ghost_profile.tag_fk_list.extend(['58088fc0c253e5ddf0563956', '58088fc0c253e5ddf0563957'])
        ghost_profile.save()
        origin = reverse('ikwen:register')
        response = self.client.post(origin, {'username': 'ngnieng@ikwen.com', 'password': 'secret', 'password2': 'secret',
                                             'phone': '237666000006', 'first_name': 'Ngnieng', 'last_name': 'Kom', 'gender': 'Female'}, follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('?').strip('/').split('/')[-1]
        self.assertEqual(location, 'console')
        member = Member.objects.get(username='ngnieng@ikwen.com', phone='237666000006', is_ghost=False)
        member_profile = MemberProfile.objects.get(member=member)
        self.assertEqual(set(member_profile.tag_fk_list), {'58088fc0c253e5ddf0563952', '58088fc0c253e5ddf0563955',
                                                           '58088fc0c253e5ddf0563956', '58088fc0c253e5ddf0563957'})
        self.assertRaises(Member.DoesNotExist, Member.objects.get, phone='666000006', is_ghost=True)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
    def test_register_with_existing_ghost_as_email(self):
        """
        If a 'ghost' Member exists with the same email or phone, it is
        replaced with the one registering and profile information of
        the ghost are shift to the actual Member.
        Ghost is Member with is_ghost=True. Those member are created manually
        from the admin or when user leaves his mail on a website.        .
        """
        ghost = Member.objects.create_user(username='ngnieng@ikwen.com', email='ngnieng@ikwen.com', gender='Male',
                                           phone='666000006', password='secret', is_ghost=True)
        ghost_profile, update = MemberProfile.objects.get_or_create(member=ghost)
        ghost_profile.tag_fk_list.extend(['58088fc0c253e5ddf0563956', '58088fc0c253e5ddf0563957'])
        ghost_profile.save()
        origin = reverse('ikwen:register')
        response = self.client.post(origin, {'username': 'ngnieng@ikwen.com', 'password': 'secret', 'password2': 'secret',
                                             'phone': '237666000006', 'first_name': 'Ngnieng', 'last_name': 'Kom', 'gender': 'Female'}, follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('?').strip('/').split('/')[-1]
        self.assertEqual(location, 'console')
        member = Member.objects.get(username='ngnieng@ikwen.com', phone='237666000006', is_ghost=False)
        member_profile = MemberProfile.objects.get(member=member)
        self.assertEqual(set(member_profile.tag_fk_list), {'58088fc0c253e5ddf0563952', '58088fc0c253e5ddf0563955',
                                                           '58088fc0c253e5ddf0563956', '58088fc0c253e5ddf0563957'})
        self.assertRaises(Member.DoesNotExist, Member.objects.get, phone='666000006', is_ghost=True)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/accesscontrol/referral')
    def test_register_with_referrer_and_referral_reward(self):
        """
        Member registering through a referrer receives the
        join reward pack and his referrer receives the referral
        reward pack.
        """
        call_command('loaddata', 'rewarding.yaml')
        service = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        group_id = '5804b37b3379b531e01eb6d2'
        add_database(service.database)
        Group.objects.using(service.database).create(pk=group_id, name=COMMUNITY)
        UserPermissionList.objects.using(service.database).all().delete()
        origin = reverse('ikwen:register') + '?join=ikwen-service-2&referrer=56eb6d04b37b3379b531e014'
        response = self.client.post(origin, {'username': 'referred.user1@domain.com', 'password': 'secret', 'password2': 'secret',
                                             'phone': '655000001', 'first_name': 'Phil', 'last_name': 'Mia'}, follow=True)
        final = response.redirect_chain[-1]
        params = unquote(final[0]).split('?')[1]
        self.assertGreaterEqual(params.index('joined='), 0)
        total_count = 0
        member = Member.objects.get(pk='56eb6d04b37b3379b531e014')
        for ref in ReferralRewardPack.objects.using(UMBRELLA).filter(service='56eb6d04b37b3379b531b102'):
            coupon = ref.coupon
            total_count += ref.count
            Reward.objects.using(UMBRELLA).get(member=member, coupon=coupon, count=ref.count,
                                               type=Reward.REFERRAL, status=Reward.SENT)
            cumul = CumulatedCoupon.objects.using(UMBRELLA).get(member=member, coupon=coupon)
            self.assertEqual(cumul.count, ref.count)
        scs = CouponSummary.objects.using(UMBRELLA).get(service='56eb6d04b37b3379b531b102', member=member)
        self.assertEqual(scs.count, total_count)

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
    def test_update_info_with_correct_parameters_and_gender_previously_unset(self):
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
