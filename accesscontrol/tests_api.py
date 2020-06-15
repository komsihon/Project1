# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest

from ikwen.accesscontrol.tests_auth import wipe_test_data
from ikwen.accesscontrol.models import Member


class APIAccessControlTestCase(unittest.TestCase):
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
            call_command('loaddata', fixture, database='umbrella')

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', UNIT_TESTING=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/ikwen/', IS_IKWEN=False)
    def test_check_user(self):
        """
        Checks if user with given username exists. Username is tested
        against 'username', 'email' and 'phone'.
        """
        origin = reverse('ikwen:api_check_user')
        response = self.client.get(origin, {'username': '680102030', 'api_signature': 'api-signature-1'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertFalse(json_response['existing'])
        response = self.client.get(origin, {'username': '677000003', 'api_signature': 'api-signature-1'})
        json_response = json.loads(response.content)
        self.assertTrue(json_response['existing'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', UNIT_TESTING=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/ikwen/', IS_IKWEN=False)
    def test_register_with_correct_values(self):
        """
        Register through API creates Member and return JSON response {'success': true}
        """
        origin = reverse('ikwen:api_register')
        response = self.client.post(origin, {'username': 'Test.User1@domain.com', 'password': 'secret', 'password2': 'secret',
                                             'phone': '655000001', 'first_name': 'Sah', 'last_name': 'Fogaing',
                                             'api_signature': 'api-signature-1'}, follow=True)
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])
        m1 = Member.objects.get(username='test.user1@domain.com')
        self.assertEqual(m1.full_name, 'Sah Fogaing')  # Member correctly created and saved

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', UNIT_TESTING=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/ikwen/', IS_IKWEN=False)
    def test_login_with_correct_values(self):
        """
        Login through API with correct values logs in Member and return JSON response {'success': true}
        """
        origin = reverse('ikwen:api_sign_in')
        response = self.client.post(origin, {'username': 'member3@ikwen.com', 'password': 'admin',
                                             'api_signature': 'api-signature-1'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', UNIT_TESTING=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/ikwen/', IS_IKWEN=False)
    def test_request_email_password_reset_with_correct_values(self):
        """
        Initiates the password reset flow and sends the email with instructions
        """
        origin = reverse('ikwen:api_request_email_password_reset')
        response = self.client.post(origin, {'email': 'member3@ikwen.com', 'api_signature': 'api-signature-1'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', UNIT_TESTING=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/ikwen/', IS_IKWEN=False)
    def test_request_phone_password_reset_with_correct_values(self):
        """
        Initiates the SMS password reset flow by sending a secret code to the phone
        """
        origin = reverse('ikwen:api_request_sms_reset_code')
        response = self.client.get(origin, {'phone': '677000003', 'api_signature': 'api-signature-1'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', UNIT_TESTING=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/ikwen/', IS_IKWEN=False)
    def test_sms_reset_password(self):
        """
        Resets the password if all data correct
        """
        origin = reverse('ikwen:api_request_sms_reset_code')
        self.client.get(origin, {'phone': '677000003', 'api_signature': 'api-signature-1'})
        origin = reverse('ikwen:api_sms_reset_password')
        response = self.client.post(origin, {'reset_code': self.client.session['reset_code'], 'new_password1': 'enigma', 'new_password2': 'enigma',
                                             'api_signature': 'api-signature-1'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])
