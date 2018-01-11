# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from datetime import datetime, timedelta

from django.core.cache import cache
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest
from ikwen.partnership.models import PartnerProfile

from ikwen.billing.models import Invoice, IkwenInvoiceItem, InvoiceEntry

from ikwen.core.models import Service, OperatorWallet

from ikwen.core.utils import get_service_instance, add_database_to_settings

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
        add_database_to_settings('test_kc_partner_jumbo')
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
        service.status = Service.SUSPENDED
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

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', DEBUG=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/core/', UNIT_TESTING=True)
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
        response = self.client.get(reverse('billing:init_momo_transaction'), data={'phone': '677003321'})
        json_resp = json.loads(response.content)
        tx_id = json_resp['tx_id']
        response = self.client.get(reverse('billing:check_momo_transaction_status'), data={'tx_id': tx_id})
        self.assertEqual(response.status_code, 200)
        json_resp = json.loads(response.content)
        self.assertTrue(json_resp['success'])
        s = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        new_expiry = now + timedelta(days=30)
        self.assertEqual(s.expiry, new_expiry.date())

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', DEBUG=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/core/', UNIT_TESTING=True)
    def test_pay_invoice_with_service_having_retailer(self):
        """
        Walks all through the payment from choosing the payment mean,
        setting checkout, confirm payment and having its Service expiry extended.
        If the Service is deployed through a partner. Share earnings accordingly
        """
        call_command('loaddata', 'billing_invoices.yaml')
        call_command('loaddata', 'partners.yaml')
        call_command('loaddata', 'ikwen_members.yaml', database='test_kc_partner_jumbo')
        call_command('loaddata', 'setup_data.yaml', database='test_kc_partner_jumbo')
        call_command('loaddata', 'partners.yaml', database='test_kc_partner_jumbo')
        call_command('loaddata', 'partner_app_retail_config.yaml')
        call_command('loaddata', 'partner_app_retail_config.yaml', database='test_kc_partner_jumbo')
        now = datetime.now()
        partner = Service.objects.get(pk='56eb6d04b9b531b10537b331')
        Service.objects.filter(pk='56eb6d04b37b3379b531b102').update(expiry=now.date(), retailer=partner)
        Invoice.objects.filter(pk='56eb6d04b37b3379d531e012').update(amount=18000)
        self.client.login(username='arch', password='admin')
        response = self.client.post(reverse('billing:momo_set_checkout'), {'invoice_id': '56eb6d04b37b3379d531e012',
                                                                           'extra_months': 2})
        self.assertEqual(response.status_code, 200)
        # Init payment from Checkout page
        response = self.client.get(reverse('billing:init_momo_transaction'), data={'phone': '677003321'})
        json_resp = json.loads(response.content)
        tx_id = json_resp['tx_id']
        response = self.client.get(reverse('billing:check_momo_transaction_status'), data={'tx_id': tx_id})
        self.assertEqual(response.status_code, 200)
        json_resp = json.loads(response.content)
        self.assertTrue(json_resp['success'])
        s = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        new_expiry = now + timedelta(days=91)
        self.assertEqual(s.expiry, new_expiry.date())

        cache.clear()
        service = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        self.assertEqual(service.turnover_history, [18000])
        self.assertEqual(service.invoice_earnings_history, [12000])
        self.assertEqual(service.earnings_history, [12000])
        self.assertEqual(service.invoice_count_history, [1])

        app = service.app
        self.assertEqual(app.turnover_history, [18000])
        self.assertEqual(app.invoice_earnings_history, [12000])
        self.assertEqual(app.earnings_history, [12000])
        self.assertEqual(app.invoice_count_history, [1])

        partner = Service.objects.get(pk='56eb6d04b9b531b10537b331')
        self.assertEqual(partner.turnover_history, [18000])
        self.assertEqual(partner.invoice_earnings_history, [12000])
        self.assertEqual(partner.earnings_history, [12000])
        self.assertEqual(partner.invoice_count_history, [1])

        partner_app = partner.app
        self.assertEqual(partner_app.turnover_history, [18000])
        self.assertEqual(partner_app.invoice_earnings_history, [12000])
        self.assertEqual(partner_app.earnings_history, [12000])
        self.assertEqual(partner_app.invoice_count_history, [1])

        partner_original = Service.objects.using('test_kc_partner_jumbo').get(pk='56eb6d04b9b531b10537b331')
        self.assertEqual(partner_original.invoice_earnings_history, [6000])
        self.assertEqual(partner_original.earnings_history, [6000])
        self.assertEqual(partner_original.invoice_count_history, [1])

        service_mirror = Service.objects.using('test_kc_partner_jumbo').get(pk='56eb6d04b37b3379b531b102')
        self.assertEqual(service_mirror.invoice_earnings_history, [6000])
        self.assertEqual(service_mirror.earnings_history, [6000])
        self.assertEqual(service_mirror.invoice_count_history, [1])

        app_mirror = service_mirror.app
        self.assertEqual(app_mirror.invoice_earnings_history, [6000])
        self.assertEqual(app_mirror.earnings_history, [6000])
        self.assertEqual(app_mirror.invoice_count_history, [1])

        partner_wallet = OperatorWallet.objects.using('wallets').get(nonrel_id='56eb6d04b9b531b10537b331')
        self.assertEqual(partner_wallet.balance, 6000)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', DEBUG=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/core/', UNIT_TESTING=True)
    def test_pay_one_off_invoice_with_service_having_retailer(self):
        """
        Walks all through the payment from choosing the payment mean,
        setting checkout, confirm payment and having its Service expiry extended.
        If the Service is deployed through a partner. Share earnings accordingly
        """
        call_command('loaddata', 'billing_invoices.yaml')
        call_command('loaddata', 'partners.yaml')
        call_command('loaddata', 'ikwen_members.yaml', database='test_kc_partner_jumbo')
        call_command('loaddata', 'setup_data.yaml', database='test_kc_partner_jumbo')
        call_command('loaddata', 'partners.yaml', database='test_kc_partner_jumbo')
        call_command('loaddata', 'partner_app_retail_config.yaml')
        call_command('loaddata', 'partner_app_retail_config.yaml', database='test_kc_partner_jumbo')
        now = datetime.now()
        partner = Service.objects.get(pk='56eb6d04b9b531b10537b331')
        Service.objects.filter(pk='56eb6d04b37b3379b531b102').update(expiry=now.date(), retailer=partner)
        item1 = IkwenInvoiceItem(label='item1', amount=10000, price=7000)
        item2 = IkwenInvoiceItem(label='item2', amount=4000, price=0)
        entries = [
            InvoiceEntry(item=item1),
            InvoiceEntry(item=item2, quantity=2)
        ]
        Invoice.objects.filter(pk='56eb6d04b37b3379d531e012').update(is_one_off=True, amount=18000, entries=entries)
        self.client.login(username='arch', password='admin')
        response = self.client.post(reverse('billing:momo_set_checkout'), {'invoice_id': '56eb6d04b37b3379d531e012'})
        self.assertEqual(response.status_code, 200)
        # Init payment from Checkout page
        response = self.client.get(reverse('billing:init_momo_transaction'), data={'phone': '677003321'})
        json_resp = json.loads(response.content)
        tx_id = json_resp['tx_id']
        response = self.client.get(reverse('billing:check_momo_transaction_status'), data={'tx_id': tx_id})
        self.assertEqual(response.status_code, 200)
        json_resp = json.loads(response.content)
        self.assertTrue(json_resp['success'])
        s = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        new_expiry = now + timedelta(days=30)
        self.assertEqual(s.expiry, new_expiry.date())

        cache.clear()
        service = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        self.assertEqual(service.turnover_history, [18000])
        self.assertEqual(service.invoice_earnings_history, [7000])
        self.assertEqual(service.earnings_history, [7000])
        self.assertEqual(service.invoice_count_history, [1])

        app = service.app
        self.assertEqual(app.turnover_history, [18000])
        self.assertEqual(app.invoice_earnings_history, [7000])
        self.assertEqual(app.earnings_history, [7000])
        self.assertEqual(app.invoice_count_history, [1])

        partner = Service.objects.get(pk='56eb6d04b9b531b10537b331')
        self.assertEqual(partner.turnover_history, [18000])
        self.assertEqual(partner.invoice_earnings_history, [7000])
        self.assertEqual(partner.earnings_history, [7000])
        self.assertEqual(partner.invoice_count_history, [1])

        partner_app = partner.app
        self.assertEqual(partner_app.turnover_history, [18000])
        self.assertEqual(partner_app.invoice_earnings_history, [7000])
        self.assertEqual(partner_app.earnings_history, [7000])
        self.assertEqual(partner_app.invoice_count_history, [1])

        service_mirror = Service.objects.using('test_kc_partner_jumbo').get(pk='56eb6d04b37b3379b531b102')
        self.assertEqual(service_mirror.invoice_earnings_history, [11000])
        self.assertEqual(service_mirror.earnings_history, [11000])
        self.assertEqual(service_mirror.invoice_count_history, [1])

        app_mirror = service_mirror.app
        self.assertEqual(app_mirror.invoice_earnings_history, [11000])
        self.assertEqual(app_mirror.earnings_history, [11000])
        self.assertEqual(app_mirror.invoice_count_history, [1])

        partner_wallet = OperatorWallet.objects.using('wallets').get(nonrel_id='56eb6d04b9b531b10537b331')
        self.assertEqual(partner_wallet.balance, 11000)
