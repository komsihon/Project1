# -*- coding: utf-8 -*-
import json
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.utils import override_settings
from django.utils.unittest import TestCase
from django.test.client import Client
from ikwen.core.utils import add_database_to_settings

from ikwen.core.models import OperatorWallet, Service

from ikwen.accesscontrol.tests_auth import wipe_test_data
from ikwen.accesscontrol.backends import UMBRELLA

__author__ = "Kom Sihon"


class CashoutViewsTest(TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml']

    def setUp(self):
        self.client = Client()
        add_database_to_settings('test_ikwen_service_2')
        for fixture in self.fixtures:
            call_command('loaddata', fixture)
            call_command('loaddata', fixture, database='test_ikwen_service_2')

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102',
                       CACHES={'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}})
    def test_Payments(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('cashout:home'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', DEBUG=True, IKWEN_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/cashout/', TESTING=True)
    def test_request_cash_out_without_cashout_address_for_payment_method(self):
        self.client.login(username='arch', password='admin')
        OperatorWallet.objects.using('wallets').create(nonrel_id='56eb6d04b37b3379b531b102',
                                                       provider='mtn-momo', balance=20000)
        response = self.client.get(reverse('cashout:request_cash_out'), {'provider': 'uba'})
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertTrue(resp['error'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', DEBUG=True, IKWEN_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/cashout/', TESTING=True)
    def test_request_cash_out(self):
        self.client.login(username='arch', password='admin')
        OperatorWallet.objects.using('wallets').create(nonrel_id='56eb6d04b37b3379b531b102',
                                                       provider='mtn-momo', balance=20000)

        # Everything should go well here
        response = self.client.get(reverse('cashout:request_cash_out'), {'provider': 'mtn-momo'})
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertTrue(resp['success'])

        # Request must be denied because an pending request for mtn-momo already exists
        response = self.client.get(reverse('cashout:request_cash_out'), {'provider': 'mtn-momo'})
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertTrue(resp['error'])
