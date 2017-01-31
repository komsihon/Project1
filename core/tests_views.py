# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from datetime import datetime, timedelta
from time import sleep

from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest
from ikwen.core.models import Service

from ikwen.core.utils import get_service_instance

from ikwen.accesscontrol.tests_auth import wipe_test_data


class IkwenCoreViewsTestCase(unittest.TestCase):
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

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', CACHES=None)
    def test_list_projects(self):
        """
        Lists projects with name contains the query 'q' and return a JSON Array of objects
        """
        self.client.login(username='member3', password='admin')
        callback = 'jsonp'
        response = self.client.get(reverse('ikwen:list_projects'), {'q': 'ik', 'callback': callback})
        self.assertEqual(response.status_code, 200)
        json_string = response.content[:-1].replace(callback + '(', '')
        json_response = json.loads(json_string)
        self.assertEqual(len(json_response['object_list']), 2)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', CACHES=None)
    def test_Console(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:console'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', CACHES=None)
    def test_Configuration(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:configuration'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', CACHES=None)
    def test_service_detail_page(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:service_detail', args=('56eb6d04b37b3379b531b101', )))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['service'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', IS_IKWEN=False,
                       MIDDLEWARE_CLASSES=('ikwen.core.middleware.ServiceStatusCheckMiddleware',
                                           'django.contrib.sessions.middleware.SessionMiddleware',
                                           'django.contrib.auth.middleware.AuthenticationMiddleware',))
    def test_ServiceExpiredMiddleware(self):
        """
        Whenever service is expired, an error 909 page is displayed if accessing
        a public URL. Admin URLs are redirected to service detail where user
        can then access his invoices and do the payment.
        """
        service = get_service_instance()
        service.expiry = datetime.now() - timedelta(days=10)
        service.save()
        response = self.client.get(reverse('ikwen:register'), follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-1]
        self.assertEqual(location, 'error909')
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:configuration'), follow=True)
        final = response.redirect_chain[-1]
        location = final[0].strip('/').split('/')[-2]
        self.assertEqual(location, 'serviceDetail')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', TESTING=True, DEBUG=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/core/', )
    def test_pay_invoice(self):
        """
        Walks all through the payment from choosing the payment mean,
        setting checkout, confirm payment and having its Service expiry extended
        """
        call_command('loaddata', 'billing_invoices.yaml')
        now = datetime.now()
        Service.objects.filter(pk='56eb6d04b37b3379b531b102').update(expiry=now.date())
        self.client.login(username='arch', password='admin')
        response = self.client.post(reverse('billing:momo_set_checkout'), {'invoice_id': '56eb6d04b37b3379d531e012',
                                                                           'extra_months': 0})
        self.assertEqual(response.status_code, 200)
        # Init payment from Checkout page
        response = self.client.get(reverse('billing:init_momo_cashout'), data={'phone': '655003321'})
        json_resp = json.loads(response.content)
        tx_id = json_resp['tx_id']
        sleep(1)
        response = self.client.get(reverse('billing:check_momo_transaction_status'), data={'tx_id': tx_id})
        self.assertEqual(response.status_code, 200)
        json_resp = json.loads(response.content)
        self.assertTrue(json_resp['success'])
        s = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        new_expiry = now + timedelta(days=30)
        s.expiry = new_expiry.date()
