# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from django.core.management import call_command
from django.test.utils import override_settings
from django.utils.unittest import TestCase
from django.test.client import Client

from ikwen.core.models import OperatorWallet
from ikwen.billing.utils import get_subscription_model

from ikwen.billing.crons import send_invoices, send_invoice_reminders, send_invoice_overdue_notices, \
    suspend_customers_services


from ikwen.billing.models import Invoice, InvoicingConfig
from ikwen.accesscontrol.tests_auth import wipe_test_data
Subscription = get_subscription_model()

__author__ = "Kom Sihon"


def shutdown_service(subscription):
    print 'Service %s shut down' % subscription.id


class BillingUtilsTest(TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml', 'billing_invoices.yaml']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/')
    def test_send_invoices(self):
        Invoice.objects.all().delete()
        invoicing_config = InvoicingConfig.objects.all()[0]
        expiry = datetime.now() + timedelta(days=invoicing_config.gap)
        Subscription.objects.all().update(expiry=expiry)
        send_invoices()
        sent = Invoice.objects.filter(reminders_sent=1).count()
        self.assertEqual(sent, 2)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/')
    def test_send_invoices_with_one_iao_having_enough_money_on_wallets(self):
        """
        Sends invoice to IAO. If IAO has enough money on his wallets,
        the payment is made directly through wallet debit and a
        confirmation email is sent.
        :return: 
        """
        Invoice.objects.all().delete()
        invoicing_config = InvoicingConfig.objects.all()[0]
        expiry = datetime.now() + timedelta(days=invoicing_config.gap)
        new_expiry = expiry + timedelta(days=30)
        Subscription.objects.all().update(expiry=expiry)
        OperatorWallet.objects.using('wallets').create(nonrel_id='56eb6d04b37b3379b531b102', provider='mtn-momo', balance=4000)
        OperatorWallet.objects.using('wallets').create(nonrel_id='56eb6d04b37b3379b531b102', provider='orange-money', balance=3000)
        send_invoices()
        sent = Invoice.objects.filter(reminders_sent=1).count()
        self.assertEqual(sent, 1)
        momo_wallet = OperatorWallet.objects.using('wallets').get(nonrel_id='56eb6d04b37b3379b531b102', provider='mtn-momo')
        om_wallet = OperatorWallet.objects.using('wallets').get(nonrel_id='56eb6d04b37b3379b531b102', provider='orange-money')
        self.assertEqual(momo_wallet.balance, 0)
        self.assertEqual(om_wallet.balance, 1000)
        service = Subscription.objects.get(pk='56eb6d04b37b3379b531b102')
        self.assertEqual(service.expiry, new_expiry.date())

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/')
    def test_send_invoices_reminders(self):
        invoicing_config = InvoicingConfig.objects.all()[0]
        due_date = datetime.now() + timedelta(days=10)
        last_reminder = datetime.now() - timedelta(days=invoicing_config.reminder_delay)
        Invoice.objects.all().update(due_date=due_date, last_reminder=last_reminder)
        send_invoice_reminders()
        sent = Invoice.objects.filter(reminders_sent=2).count()
        self.assertEqual(sent, 3)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/')
    def test_send_invoice_overdue_notices(self):
        invoicing_config = InvoicingConfig.objects.all()[0]
        due_date = datetime.now() - timedelta(days=1)
        last_reminder = datetime.now() - timedelta(days=invoicing_config.reminder_delay)
        Invoice.objects.all().update(due_date=due_date, last_reminder=last_reminder)
        send_invoice_overdue_notices()
        sent = Invoice.objects.filter(overdue_notices_sent=1).count()
        self.assertEqual(sent, 3)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       SERVICE_SUSPENSION_ACTION='ikwen.core.tests_billing_crons.shutdown_service',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/')
    def test_shutdown_customers_services(self):
        invoicing_config = InvoicingConfig.objects.all()[0]
        due_date = datetime.now() - timedelta(days=invoicing_config.tolerance + 3)
        Invoice.objects.all().update(due_date=due_date, status=Invoice.OVERDUE)
        suspend_customers_services()
        sent = Invoice.objects.filter(status=Invoice.EXCEEDED).count()
        self.assertEqual(sent, 4)
