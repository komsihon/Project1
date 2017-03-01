# -*- coding: utf-8 -*-
from datetime import datetime
from datetime import timedelta
from django.conf import settings
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.utils import override_settings
from django.utils.unittest import TestCase
from django.test import Client

# Override BILLING_SUBSCRIPTION_MODEL before ikwen.billing.models is loaded
setattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')

from ikwen.billing.admin import Product

from ikwen.core.models import ConsoleEvent

from ikwen.accesscontrol.models import Member

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.billing.tests_views import wipe_test_data


from ikwen.billing.models import Invoice

__author__ = "Kom Sihon"


class BillingAdminTest(TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ik_billing_setup_data.yaml', 'configs.yaml', 'billing_members.yaml', 'subscriptions.yaml', 'invoices.yaml']

    def setUp(self):
        self.client = Client()
        call_command('loaddata', 'ik_billing_setup_data.yaml', database=UMBRELLA)
        call_command('loaddata', 'billing_members.yaml', database=UMBRELLA)
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_InvoicingConfigChange(self):
        self.client.login(username='member1', password='admin')
        response = self.client.get(reverse('admin:billing_invoicingconfig_change', args=('56cc6b423350d09453e3b37b', )))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_ProductChangeList(self):
        self.client.login(username='member1', password='admin')
        response = self.client.get(reverse('admin:billing_product_changelist'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_ProductAdd(self):
        self.client.login(username='member1', password='admin')
        print Product.objects.all().count()
        response = self.client.post(reverse('admin:billing_product_add'),
                                    {'name': 'New product', 'short_description': 'A new cool product',
                                     'monthly_cost': 5000, 'details': 'sfg', '_save': 'Save'})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse('admin:billing_product_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Product.objects.all().count(), 2)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_ProductChange(self):
        self.client.login(username='member1', password='admin')
        response = self.client.get(reverse('admin:billing_product_change', args=('55eb63379c531e012d04b37a', )))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_SubscriptionChangeList(self):
        self.client.login(username='member1', password='admin')
        response = self.client.get(reverse('admin:billing_subscription_changelist'), {'q': 'tch'})
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing_admin/')
    def test_SubscriptionAdd(self):
        self.client.login(username='member1', password='admin')
        response = self.client.post(reverse('admin:billing_subscription_add'),
                                    {'member': '56eb6d04b37b3379b531e013', 'product': '55eb63379c531e012d04b37a',
                                     'monthly_cost': 5000, 'since': datetime.now()})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse('admin:billing_subscription_changelist'))
        self.assertEqual(len(response.context['results']), 4)
        member3 = Member.objects.using(UMBRELLA).get(username='member3')
        self.assertEqual(member3.personal_notices, 1)
        self.assertEqual(ConsoleEvent.objects.using(UMBRELLA).filter(member=member3).count(), 1)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_SubscriptionChange(self):
        self.client.login(username='member1', password='admin')
        response = self.client.get(reverse('admin:billing_subscription_change', args=('56eb6d04b37b3379c531e012', )))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_InvoiceChangeList(self):
        self.client.login(username='member1', password='admin')
        response = self.client.get(reverse('admin:billing_invoice_changelist'), {'q': 'tch'})
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing_admin/')
    def test_InvoiceAdd(self):
        self.client.login(username='member1', password='admin')
        response = self.client.post(reverse('admin:billing_invoice_add'),
                                    {'subscription': '56eb6d04b37b3379c531e013', 'amount': 5000,
                                     'due_date': datetime.now() + timedelta(days=10)})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse('admin:billing_subscription_changelist'))
        self.assertEqual(len(response.context['results']), 5)
        member3 = Member.objects.using(UMBRELLA).get(username='member3')
        self.assertEqual(member3.personal_notices, 1)
        self.assertEqual(ConsoleEvent.objects.using(UMBRELLA).filter(member=member3).count(), 1)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing_admin/')
    def test_InvoiceChange(self):
        self.client.login(username='member1', password='admin')
        response = self.client.post(reverse('admin:billing_invoice_change', args=('56eb6d04b37b3379d531e013', )),
                                    {'subscription': '56eb6d04b37b3379c531e012', 'amount': 5000,
                                     'due_date': datetime.now() + timedelta(days=10),
                                     'payment_set-0-method': 'Cash', 'payment_set-0-amount': 3000,
                                     'payment_set-1-method': 'Cash', 'payment_set-1-amount': 2000})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse('admin:billing_subscription_changelist'))
        self.assertEqual(len(response.context['results']), 4)
        invoice = Invoice.objects.get(pk='56eb6d04b37b3379d531e013')
        self.assertEqual(invoice.status, Invoice.PAID)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_PaymentChangeList(self):
        self.client.login(username='member1', password='admin')
        response = self.client.get(reverse('admin:billing_payment_changelist'), {'q': 'pok'})
        self.assertEqual(response.status_code, 200)
