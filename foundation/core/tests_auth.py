# # -*- coding: utf-8 -*-
# import json
# import ikwen.models
# from urllib import unquote
# from urlparse import urlparse
# from django.conf import settings
# from django.core.urlresolvers import reverse
# from django.template.defaultfilters import urlencode
# from django.test.client import Client
# from django.test.utils import override_settings
# from django.utils import unittest, timezone
# from ikwen.backends import UMBRELLA
# from ikwen.models import Member, Service, Application, Country, Payment, Company, Invoice
# from django.utils.translation import gettext as _
#
#
# class IkwenLoginTestCase(unittest.TestCase):
#     IKWEN_SERVICE_ID = '56eb6d04b37b3379b531b101'
#
#     def setUp(self):
#         self.client = Client()
#         app = Application.objects.create(base_monthly_cost=2500, name='Ikwen App', url='')
#         Service.objects.create(id=self.IKWEN_SERVICE_ID, app=app, project_name='My Project',
#                                monthly_cost=app.base_monthly_cost, billing_cycle=Service.MONTHLY)
#
#     def tearDown(self):
#         for name in ('Application', 'Config', 'Service', 'Member'):
#             model = getattr(ikwen.models, name)
#             model.objects.all().delete()
#
#     def test_login_with_wrong_credentials_and_no_prior_get_parameters(self):
#         """
#         Wrong parameters set the login_form in context
#         """
#         response = self.client.get(reverse('ikwen:sign_in'))
#         self.assertEqual(response.status_code, 200)
#         response = self.client.post(reverse('ikwen:sign_in'), {'username': 'arch@ikwen.com', 'password': 'wrong'}, follow=True)
#         self.assertIsNotNone(response.context['login_form'])
#
#     @override_settings(LOGIN_REDIRECT_URL=None)
#     def test_login_with_correct_credentials_and_no_prior_get_parameters(self):
#         """
#         Login in with no prior GET parameters should redirect to accountSetup page
#         """
#         Member.objects.create_user(email='arch@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:sign_in'))
#         self.assertEqual(response.status_code, 200)
#         response = self.client.post(reverse('ikwen:sign_in'), {'username': 'arch@ikwen.com', 'password': 'admin'}, follow=True)
#         final = response.redirect_chain[-1]
#         location = final[0].strip('/').split('/')[-1]
#         self.assertEqual(location, 'accountSetup')
#
#     @override_settings(LOGIN_REDIRECT_URL=None)
#     def test_login_with_correct_credentials_and_member_is_iao_and_no_next_url(self):
#         """
#         Login in with no prior GET parameters and member that is IAO takes to service_list page
#         """
#         Member.objects.create_user(email='arch@ikwen.com', password='admin', is_iao=True)
#         response = self.client.post(reverse('ikwen:sign_in'), {'username': 'arch@ikwen.com', 'password': 'admin'}, follow=True)
#         final = response.redirect_chain[-1]
#         location = final[0].strip('/').split('/')[-1]
#         self.assertEqual(location, 'services')
#
#     @override_settings(LOGIN_REDIRECT_URL='ikwen:contact')
#     def test_sign_in_with_user_already_logged_in_and_no_next_url(self):
#         """
#         If user is already logged in, he is taken back to site homepage
#         """
#         Member.objects.create_user(email='arch@ikwen.com', password='admin')
#         self.client.login(email='arch@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:sign_in'), follow=True)
#         final = response.redirect_chain[-1]
#         location = final[0].strip('/').split('/')[-1]
#         self.assertEqual(location, 'contact')
#
#     def test_sign_in_with_user_already_logged_in_and_next_url(self):
#         """
#         If user is already logged in, he is taken to the next_url parameter
#         """
#         Member.objects.create_user(email='arch@ikwen.com', password='admin')
#         self.client.login(email='arch@ikwen.com', password='admin')
#         next_url = reverse('ikwen:contact')
#         response = self.client.get(reverse('ikwen:sign_in') + '?next=' + urlencode(next_url), follow=True)
#         final = response.redirect_chain[-1]
#         location = final[0]
#         self.assertEqual(location, 'http://testserver' + next_url)
#
#     def test_login_with_correct_credentials_and_next_url_having_other_get_parameters(self):
#         """
#         Login in with next_url GET parameter should redirect to next_url with its GET parameters kept
#         """
#         Member.objects.create_user(email='arch@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:sign_in'))
#         self.assertEqual(response.status_code, 200)
#         contact_url = reverse('ikwen:contact')
#         next_url = contact_url + '?p1=v1&p2=v2'
#         origin = reverse('ikwen:sign_in') + '?next=' + urlencode(next_url)
#         response = self.client.post(origin, {'username': 'arch@ikwen.com', 'password': 'admin'}, follow=True)
#         final = response.redirect_chain[-1]
#         self.assertEqual(final[0], 'http://testserver' + next_url)
#
#     def test_login_with_wrong_credentials_get_parameters_and_next_url_having_other_get_parameters(self):
#         """
#         Wrong login credentials stays on the same page and keeps previous GET parameters that were
#         available when landing on the login page
#         """
#         response = self.client.get(reverse('ikwen:sign_in'))
#         self.assertEqual(response.status_code, 200)
#         contact_url = reverse('ikwen:contact')
#         next_url = contact_url + '?p1=v1&p2=v2'
#         query_string = 'next=' + urlencode(next_url) + '&par1=val1&par2=val2'
#         origin = reverse('ikwen:sign_in') + '?' + query_string
#         response = self.client.post(origin, {'username': 'arch@ikwen.com', 'password': 'wrong'}, follow=True)
#         self.assertGreaterEqual(response.request['PATH_INFO'].find('/signIn/'), 0)
#         self.assertEqual(response.request['QUERY_STRING'], query_string)
#         self.assertIsNotNone(response.context['login_form'])
#
#     def test_register_with_password_mismatch(self):
#         """
#         Different password and confirmation set the passwordMismatch=yes GET parameter and prior GET parameters remain
#         """
#         origin = reverse('ikwen:register') + '?next=http://localhost/hotspot/config&p1=v1&p2=v2'
#         response = self.client.post(origin, {'email': 'good@email.com', 'password': 'secret', 'password2': 'sec',
#                                              'phone': '655045781', 'name': 'Sah Fogaing'}, follow=True)
#         self.assertEqual(response.status_code, 200)
#         self.assertGreaterEqual(response.request['PATH_INFO'].find('/signIn/'), 0)
#         params = unquote(response.request['QUERY_STRING']).split('&')
#         self.assertGreaterEqual(params.index('passwordMismatch=yes'), 0)
#         self.assertGreaterEqual(params.index('next=http://localhost/hotspot/config'), 0)
#         self.assertGreaterEqual(params.index('p1=v1'), 0)
#         self.assertGreaterEqual(params.index('p2=v2'), 0)
#
#     def test_register_with_wrong_email_password_phone_name(self):
#         """
#         Wrong parameters set the register_form in context with correct error and prior GET parameters remain
#         """
#         origin = reverse('ikwen:register') + '?next=http://localhost/hotspot/config&p1=v1&p2=v2'
#         response = self.client.post(origin, {'email': 'wrong@email', 'password': '',
#                                              'phone': '(+237)655045781', 'name': ''}, follow=True)
#         self.assertEqual(response.status_code, 200)
#         self.assertIsNotNone(response.context['register_form'].errors['email'])
#         self.assertIsNotNone(response.context['register_form'].errors['password'])
#         self.assertIsNotNone(response.context['register_form'].errors['password2'])
#         self.assertIsNotNone(response.context['register_form'].errors['phone'])
#         self.assertIsNotNone(response.context['register_form'].errors['name'])
#         self.assertEqual(response.request['QUERY_STRING'], 'next=http://localhost/hotspot/config&p1=v1&p2=v2')
#
#     @override_settings(LOGIN_REDIRECT_URL=None)
#     def test_register_with_correct_values_next_url_and_other_get_parameters(self):
#         """
#         Correct parameters save user in default and foundation databases. Prior GET parameters remain
#         """
#         contact_url = reverse('ikwen:contact')
#         origin = reverse('ikwen:register') + '?next=' + urlencode(contact_url) + '&p1=v1&p2=v2'
#         response = self.client.post(origin, {'email': 'testuser1@email.com', 'password': 'secret', 'password2': 'secret',
#                                              'phone': '655000001', 'name': 'Sah Fogaing'}, follow=True)
#         m1 = Member.objects.using(UMBRELLA).get(email='testuser1@email.com')
#         m2 = Member.objects.get(email='testuser1@email.com')
#         self.assertEqual(self.client.session['_auth_user_id'], m1.id)  # Test whether user is actually logged in
#         self.assertEqual(m1.id, m2.id)
#         final = urlparse(response.redirect_chain[-1][0])
#         location = final.path.strip('/').split('/')[-1]
#         self.assertEqual(location, 'contact')
#         params = unquote(final.query).split('&')
#         self.assertGreaterEqual(params.index('p1=v1'), 0)
#         self.assertGreaterEqual(params.index('p2=v2'), 0)
#         response = self.client.post(reverse('ikwen:sign_in'), {'username': 'testuser1@email.com', 'password': 'secret'}, follow=True)
#         final = response.redirect_chain[-1]
#         location = final[0].strip('/').split('/')[-1]
#         self.assertEqual(location, 'accountSetup')
#
#     def test_update_info_with_existing_email(self):
#         """
#         User should be informed if changing e-mail to an existing one
#         """
#         Member.objects.create_user(email='info_updater1@ikwen.com', password='admin', phone='655000010')
#         Member.objects.create_user(email='info_updater2@ikwen.com', password='admin', phone='655000011')
#         self.client.login(email='info_updater1@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:update_info'), {'email': 'info_updater2@ikwen.com'})
#         self.assertEqual(response.status_code, 200)
#         self.assertEqual(response.content, json.dumps({'error': _('This e-mail already exists.')}))
#
#     def test_update_info_with_existing_phone(self):
#         """
#         User should be informed if changing phone to an existing one
#         """
#         Member.objects.create_user(email='info_updater1@ikwen.com', password='admin', phone='655000010')
#         Member.objects.create_user(email='info_updater2@ikwen.com', password='admin', phone='655000011')
#         self.client.login(email='info_updater1@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:update_info'), {'phone': '655000011'})
#         self.assertEqual(response.status_code, 200)
#         self.assertEqual(response.content, json.dumps({'error': _('This phone already exists.')}))
#
#     def test_update_gender_with_gender_previously_set(self):
#         """
#         User should not update gender when set
#         """
#         Member.objects.create_user(email='gender@ikwen.com', password='admin', gender=Member.MALE, phone='655000012')
#         self.client.login(email='gender@ikwen.com', password='admin')
#         self.client.get(reverse('ikwen:update_info'), {'gender': Member.FEMALE})
#         m = Member.objects.get(email='gender@ikwen.com')
#         self.assertEqual(m.gender, Member.MALE)
#
#     def test_update_correct_parameters_and_gender_not_set(self):
#         """
#         All user information should be updated and correct information message returned
#         """
#         Member.objects.create_user(email='info_updater3@ikwen.com', password='admin', phone='655000013')
#         self.client.login(email='info_updater3@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:update_info'), {'email': 'u4@ikwen.com', 'phone': '655000014',
#                                                                   'gender': Member.MALE, 'name': 'Sah Fogaing'})
#         self.assertEqual(response.content, json.dumps({'message': _('Your information were successfully updated.')}))
#         m = Member.objects.get(email='u4@ikwen.com')
#         m1 = Member.objects.using(UMBRELLA).get(email='u4@ikwen.com')
#         self.assertEqual(m.phone, '655000014')
#         self.assertEqual(m.gender, Member.MALE)
#         self.assertEqual(m.first_name, 'Sah')
#         self.assertEqual(m.last_name, 'Fogaing')
#         self.assertEqual(m1.phone, '655000014')
#         self.assertEqual(m1.gender, Member.MALE)
#         self.assertEqual(m1.first_name, 'Sah')
#         self.assertEqual(m1.last_name, 'Fogaing')
#
#     def test_update_password_with_incorrect_current_password(self):
#         """
#         User must be informed when current password is incorrect
#         """
#         Member.objects.create_user(email='pwd@ikwen.com', password='admin', phone='655000020')
#         self.client.login(email='pwd@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:update_password'), {'password': 'wrong'})
#         self.assertEqual(response.content, json.dumps({'error': _('The current password is incorrect!')}))
#
#     def test_update_password_with_password_mismatch(self):
#         """
#         User should be informed when password and confirmation mismatch
#         """
#         Member.objects.create_user(email='pwd1@ikwen.com', password='admin', phone='655000021')
#         self.client.login(email='pwd1@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:update_password'), {'password': 'admin', 'password1': 'value1', 'password2': 'value2'})
#         self.assertEqual(response.content, json.dumps({'error': _("Passwords don't match.")}))
#
#     def test_update_password_with_correct_values(self):
#         Member.objects.create_user(email='pwd2@ikwen.com', password='admin', phone='655000022')
#         self.assertTrue(self.client.login(email='pwd2@ikwen.com', password='admin'))
#         response = self.client.get(reverse('ikwen:update_password'), {'password': 'admin', 'password1': 'value', 'password2': 'value'})
#         self.assertEqual(response.content, json.dumps({'message': _('Your password was successfully updated.')}))
#         self.assertTrue(self.client.login(email='pwd2@ikwen.com', password='value'))
#         m2 = Member.objects.using(UMBRELLA).get(email='pwd2@ikwen.com')
#         self.assertTrue(m2.check_password('value'))
#
#     def test_login_with_phone(self):
#         """
#         User can login using phone number and e-mail as well
#         """
#         Member.objects.create_user(email='phone_user@ikwen.com', password='admin', phone='655000030')
#         self.assertTrue(self.client.login(email='phone_user@ikwen.com', password='admin'))
#         self.assertTrue(self.client.login(phone='655000030', password='admin'))
#
#     @override_settings(DEBUG=True)
#     def test_account_setup_page(self):
#         """
#         Make sure the url is reachable
#         """
#         Member.objects.create_user(email='pwd1@ikwen.com', password='admin', phone='655000021')
#         self.client.login(email='pwd1@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:account_setup'))
#         self.assertEqual(response.status_code, 200)
#
#     def test_contact(self):
#         """
#         Contact should render ikwen/contact.html template
#         """
#         response = self.client.get(reverse('ikwen:contact'))
#         self.assertEqual(response.status_code, 200)
#
#     @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101')
#     def test_service_list_page(self):
#         """
#         Make sure the url is reachable
#         """
#         Member.objects.create_user(email='member1@ikwen.com', password='admin', phone='655000021')
#         self.client.login(email='member1@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:service_list'))
#         self.assertEqual(response.status_code, 200)
#         self.assertEqual(response.context['services'].count(), 2)
#
#     @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', DEBUG=True)
#     def test_service_detail_page(self):
#         """
#         Make sure the url is reachable
#         """
#         Member.objects.create_user(email='member1@ikwen.com', password='admin', phone='655000021')
#         self.client.login(email='member1@ikwen.com', password='admin')
#         response = self.client.get(reverse('ikwen:service_detail', args=('56eb6d04b37b3379b531b101', )))
#         self.assertEqual(response.status_code, 200)
#         self.assertIsNotNone(response.context['service'])
