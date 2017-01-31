# -*- coding: utf-8 -*-
import json
from datetime import datetime
from datetime import timedelta
from time import sleep

from django.conf import settings
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.utils import override_settings
from django.utils.unittest import TestCase
from django.test.client import Client

# Override BILLING_SUBSCRIPTION_MODEL before ikwen.billing.models is loaded
setattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.billing.models import Subscription, Invoice, PaymentMean

__author__ = "Kom Sihon"


def wipe_test_data():
    """
    This test was originally built with django-nonrel 1.6 which had an error when flushing the database after
    each test. So the flush is performed manually with this custom tearDown()
    """
    import ikwen.core.models
    import ikwen.billing.models
    import ikwen.accesscontrol.models
    for alias in getattr(settings, 'DATABASES').keys():
        if alias == 'wallets':
            continue
        for name in ('Member',):
            model = getattr(ikwen.accesscontrol.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Config', 'Service', 'ConsoleEvent', ):
            model = getattr(ikwen.core.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Product', 'Payment', 'Invoice', 'Subscription',
                     'InvoicingConfig', 'PaymentMean', 'MoMoTransaction'):
            model = getattr(ikwen.billing.models, name)
            model.objects.using(alias).all().delete()


class BillingViewsTest(TestCase):
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
    def test_InvoiceList(self):
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('billing:invoice_list', args=('56eb6d04b37b3379c531e012', )))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['invoices']), 2)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_InvoiceDetail(self):
        invoice = Invoice.objects.all()[0]
        invoice.subscription.expiry = datetime.now() + timedelta(days=20)
        invoice.subscription.save()
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('billing:invoice_detail', args=(invoice.id, )))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['invoice'])

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_PaymentMeanList(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:payment_mean_list'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_PaymentMeanList(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:payment_mean_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['payment_mean_list']), 2)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_set_credentials(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:set_credentials'),
                                   {'mean_id': '5880870e4fc0c229da8da3d1',
                                    'credentials': '{"username": "PPUser", "password": "PPPass",'
                                                   '"signature": "PPSignature", "merchant_id": "PPMerchantID"}'})
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertTrue(resp['success'])
        payment_mean = PaymentMean.objects.get(pk='5880870e4fc0c229da8da3d1')
        credentials = json.loads(payment_mean.credentials)
        self.assertEqual(credentials['username'], 'PPUser')
        self.assertEqual(credentials['password'], 'PPPass')
        self.assertEqual(credentials['signature'], 'PPSignature')
        self.assertEqual(credentials['merchant_id'], 'PPMerchantID')

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_toggle_payment_mean(self):
        self.client.login(username='arch', password='admin')
        PaymentMean.objects.filter(pk='5880870e4fc0c229da8da3d2').update(is_active=True)
        response = self.client.get(reverse('billing:toggle_payment_mean'), {'mean_id': '5880870e4fc0c229da8da3d2'})
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertTrue(resp['success'])
        payment_mean = PaymentMean.objects.get(pk='5880870e4fc0c229da8da3d2')
        self.assertFalse(payment_mean.is_active)
