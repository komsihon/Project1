# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from django.conf import settings
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.utils import override_settings
from django.utils.unittest import TestCase
from django.test.client import Client

# Override BILLING_SUBSCRIPTION_MODEL before ikwen.billing.models is loaded

setattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')

from ikwen.billing.crons import send_invoices, send_invoice_reminders, send_invoice_overdue_notices, \
    suspend_customers_services
from ikwen.billing.utils import get_invoicing_config_instance
from ikwen.billing.models import Invoice, InvoicingConfig, Subscription
from ikwen.billing.tests_views import wipe_test_data

__author__ = "Kom Sihon"


def shutdown_service(subscription):
    print 'Service %s shut down' % subscription.id


class BillingUtilsTest(TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ik_billing_setup_data.yaml', 'configs.yaml', 'billing_members.yaml', 'subscriptions.yaml', 'invoices.yaml']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/', IS_IKWEN=False)
    def test_send_invoices(self):
        Invoice.objects.all().delete()
        invoicing_config = get_invoicing_config_instance()
        expiry = datetime.now() + timedelta(days=invoicing_config.gap)
        Subscription.objects.all().update(expiry=expiry)
        send_invoices()
        sent = Invoice.objects.all().count()
        self.assertEqual(sent, 3)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/', IS_IKWEN=False)
    def test_send_invoices_reminders(self):
        invoicing_config = get_invoicing_config_instance()
        due_date = datetime.now() + timedelta(days=10)
        last_reminder = datetime.now() - timedelta(days=invoicing_config.reminder_delay)
        Invoice.objects.all().update(due_date=due_date, last_reminder=last_reminder)
        send_invoice_reminders()
        sent = Invoice.objects.filter(reminders_sent=2).count()
        self.assertEqual(sent, 3)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/', IS_IKWEN=False)
    def test_send_invoice_overdue_notices(self):
        invoicing_config = get_invoicing_config_instance()
        due_date = datetime.now() - timedelta(days=1)
        last_reminder = datetime.now() - timedelta(days=invoicing_config.reminder_delay)
        Invoice.objects.all().update(due_date=due_date, last_reminder=last_reminder)
        send_invoice_overdue_notices()
        sent = Invoice.objects.filter(overdue_notices_sent=1).count()
        self.assertEqual(sent, 3)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       SERVICE_SUSPENSION_ACTION='ikwen.billing.tests_crons.shutdown_service',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/', IS_IKWEN=False)
    def test_shutdown_customers_services(self):
        invoicing_config = get_invoicing_config_instance()
        due_date = datetime.now() - timedelta(days=invoicing_config.tolerance + 3)
        Invoice.objects.all().update(due_date=due_date, status=Invoice.OVERDUE)
        suspend_customers_services()
        sent = Invoice.objects.filter(status=Invoice.EXCEEDED).count()
        self.assertEqual(sent, 4)
