# -*- coding: utf-8 -*-
from datetime import datetime
from datetime import timedelta
from django.conf import settings
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.utils import override_settings
from django.utils.unittest import TestCase
from django.test.client import Client

# Override BILLING_SUBSCRIPTION_MODEL before ikwen.foundation.billing.models is loaded
setattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')

from ikwen.foundation.accesscontrol.backends import UMBRELLA

from ikwen.foundation.billing.models import Invoice

__author__ = "Kom Sihon"


def wipe_test_data():
    """
    This test was originally built with django-nonrel 1.6 which had an error when flushing the database after
    each test. So the flush is performed manually with this custom tearDown()
    """
    import ikwen.foundation.core.models
    import ikwen.foundation.billing.models
    import ikwen.foundation.accesscontrol.models
    for alias in getattr(settings, 'DATABASES').keys():
        for name in ('Member',):
            model = getattr(ikwen.foundation.accesscontrol.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Config', 'Service', 'ConsoleEvent', ):
            model = getattr(ikwen.foundation.core.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Product', 'Payment', 'Invoice', 'Subscription', 'InvoicingConfig'):
            model = getattr(ikwen.foundation.billing.models, name)
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

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       IS_IKWEN=True)
    def test_InvoiceDetail(self):
        invoice = Invoice.objects.all()[0]
        invoice.subscription.expiry = datetime.now() + timedelta(days=20)
        invoice.subscription.save()
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('billing:invoice_detail', args=(invoice.id, )))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['invoice'])


