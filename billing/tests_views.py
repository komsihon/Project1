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

from echo.models import Balance
from ikwen.core.models import OperatorWallet

# Override BILLING_SUBSCRIPTION_MODEL before ikwen.billing.models is loaded
setattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')
setattr(settings, 'BILLING_INVOICE_ITEM_MODEL', 'billing.InvoiceItem')

BASE_DIR = getattr(settings, 'BASE_DIR')
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.core.models import XEmailObject
from ikwen.billing.models import Product, Subscription, Invoice, PaymentMean, Payment
from ikwen.billing.utils import get_invoicing_config_instance

__author__ = "Kom Sihon"


def wipe_test_data():
    """
    This test was originally built with django-nonrel 1.6 which had an error when flushing the database after
    each test. So the flush is performed manually with this custom tearDown()
    """
    import ikwen.core.models
    import ikwen.billing.models
    import ikwen.accesscontrol.models
    OperatorWallet.objects.using('wallets').all().delete()
    Balance.objects.using('wallets').all().delete()
    for alias in getattr(settings, 'DATABASES').keys():
        if alias == 'wallets':
            continue
        for name in ('Member',):
            model = getattr(ikwen.accesscontrol.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Config', 'Service', 'ConsoleEvent', 'XEmailObject'):
            model = getattr(ikwen.core.models, name)
            model.objects.using(alias).all().delete()
        for name in ('Product', 'Subscription', 'Payment', 'Invoice', 'InvoicingConfig',
                     'PaymentMean', 'MoMoTransaction', 'SupportBundle', 'SupportCode'):
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
    def test_ProductList(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['product_list']), 3)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_ProductList_delete_with_product_having_subscriptions(self):
        """
        Trying to delete a Product with actual subscriptions bound to it
        returns an error message asking to delete subscriptions first.
        """
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:product_list'), data={'action': 'delete',
                                                                          'selection': '55eb63379c531e012d04b37a'})
        resp = json.loads(response.content)
        self.assertEqual(resp['message'], "Cannot delete product with actual subscriptions. Deactivate instead")

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_ProductList_delete_with_product_having_no_subscription(self):
        """
        Deleting a product without subscription actually removes it.
        """
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:product_list'), data={'action': 'delete',
                                                                          'selection': '55eb63379c531e012d04b37b'})
        resp = json.loads(response.content)
        self.assertEqual(resp['message'], "1 item(s) deleted.")
        self.assertEqual(resp['deleted'], ['55eb63379c531e012d04b37b'])
        self.assertRaises(Product.DoesNotExist, Product.objects.get, pk='55eb63379c531e012d04b37b')

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_SubscriptionList(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:subscription_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['subscription_list']), 3)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_ChangeSubscription(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:change_subscription', args=('56eb6d04b37b3379c531e012',)))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_SubscriptionList_delete_with_subscription_having_invoices(self):
        """
        Deleting a subscription cascades and deletes invoices and payments all together.
        """
        self.client.login(username='arch', password='admin')
        self.assertGreaterEqual(Payment.objects.filter(invoice='56eb6d04b379d531e01237d1').count(), 1)
        Invoice.objects.exclude(pk='56eb6d04b379d531e01237d1').delete()
        self.assertEqual(Invoice.objects.filter(subscription='56eb6d04b37b3379c531e012').count(), 1)
        response = self.client.get(reverse('billing:subscription_list'),
                                   data={'action': 'delete', 'selection': '56eb6d04b37b3379c531e012'})
        resp = json.loads(response.content)
        self.assertEqual(resp['message'], "1 item(s) deleted.")
        self.assertEqual(resp['deleted'], ['56eb6d04b37b3379c531e012'])
        self.assertRaises(Payment.DoesNotExist, Payment.objects.get, invoice='56eb6d04b379d531e01237d1')
        self.assertRaises(Invoice.DoesNotExist, Invoice.objects.get, subscription='56eb6d04b37b3379c531e012')
        self.assertRaises(Subscription.DoesNotExist, Subscription.objects.get, pk='56eb6d04b37b3379c531e012')

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       MEDIA_ROOT=BASE_DIR + '/billing/fixtures/')
    def test_SubscriptionList_import_with_CSV_having_errors(self):
        """
        Importing and incorrect CSV file generates an error with a precise message.
        """
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:subscription_list'),
                                   data={'action': 'import', 'filename': 'ikwen_Billing_import_clients_with_errors.csv'})
        resp = json.loads(response.content)
        self.assertEqual(resp['error'], "Invalid email wrong_email on line 2")

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       MEDIA_ROOT=BASE_DIR + '/billing/fixtures/')
    def test_SubscriptionList_import_with_correct_CSV(self):
        """
        Importing a correct CSV creates the subscriptions in the database.
        """
        product_id = '55eb63379c531e012d04b37c'
        Product.objects.filter(pk=product_id).update(is_active=True)
        Subscription.objects.filter(product=product_id).delete()
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:subscription_list'),
                                   data={'action': 'import', 'filename': 'ikwen_Billing_import_clients.csv'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Subscription.objects.filter(product=product_id).count(), 5)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/', UNIT_TESTING=True)
    def test_ChangeSubscription_with_new_subscription(self):
        """
        Creating a new subscription generates and sends an invoice to designated customer email
        """
        Balance.objects.using('wallets').create(service_id='54ad2bd9b37b335a18fe5801', mail_count=100)
        self.client.login(username='arch', password='admin')
        email = 'client1@ikwen.com'
        data = {'email': email, 'product': '55eb63379c531e012d04b37b', 'monthly_cost': 5000, 'expiry': '2035-01-01',
                'billing_cycle': 'Quarterly', 'invoice_tolerance': 10, 'status': Subscription.PENDING}
        response = self.client.post(reverse('billing:change_subscription'), data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Member.objects.filter(email=email, is_ghost=True).count(), 1)
        self.assertEqual(XEmailObject.objects.filter(to=email).count(), 1)
        self.assertEqual(Balance.objects.using('wallets').get(service_id='54ad2bd9b37b335a18fe5801').mail_count, 99)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_InvoiceAdmin(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:admin_invoice_list'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_InvoiceList(self):
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('billing:invoice_list'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_InvoiceDetail(self):
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('billing:invoice_detail', args=('56eb6d04b379d531e01237d1', )))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_api_pull_invoice_with_invoicing_config_pull_invoice_false(self):
        """
        pull_invoice with invoicing_config.pull_invoice = False returns an error message
        """
        data = {'api_signature': 'wrong_signature', 'invoice_number': 'INV001'}
        response = self.client.post(reverse('billing:pull_invoice'), data=data)
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertEqual(resp['error'], "Cannot import when not explicitly configured to do so. You must set activate " \
                 "pull_invoice in your platform configuration for import to work.")

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_api_pull_invoice_with_invalid_signature(self):
        invoicing_config = get_invoicing_config_instance()
        invoicing_config.pull_invoice = True
        invoicing_config.save(using=UMBRELLA)
        data = {'api_signature': 'wrong_signature', 'invoice_number': 'INV001'}
        response = self.client.post(reverse('billing:pull_invoice'), data=data)
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertEqual(resp['error'], "Invalide API Signature.")

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/billing/', UNIT_TESTING=True)
    def test_api_pull_invoice_with_correct_data(self):
        """
        pull_invoice() called with correct data generates and sends the invoice to customer
        """
        invoicing_config = get_invoicing_config_instance()
        invoicing_config.pull_invoice = True
        invoicing_config.save(using=UMBRELLA)
        Balance.objects.using('wallets').create(service_id='54ad2bd9b37b335a18fe5801', mail_count=100)
        number = 'INV001'
        data = {'api_signature': 'top_secret_token', 'invoice_number': number, 'reference_id': 'Ext_ID_1',
                'amount': 5000, 'due_date': '2035-01-01', 'quantity': 1}
        response = self.client.post(reverse('billing:pull_invoice'), data=data)
        self.assertEqual(response.status_code, 200)
        resp = json.loads(response.content)
        self.assertTrue(resp['success'])
        self.assertEqual(Invoice.objects.filter(number=number).count(), 1)
        self.assertEqual(XEmailObject.objects.filter(to='member2@ikwen.com').count(), 1)
        self.assertEqual(Balance.objects.using('wallets').get(service_id='54ad2bd9b37b335a18fe5801').mail_count, 99)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_PaymentMeanList(self):
        self.client.login(username='arch', password='admin')
        response = self.client.get(reverse('billing:payment_mean_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['payment_mean_list_all']), 3)

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

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801', IS_IKWEN=False, DEBUG=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       IKWEN_CONFIG_MODEL='billing.OperatorProfile',
                       EMAIL_FILE_PATH='test_emails/billing/', UNIT_TESTING=True,
                       PAYMENTS={'subscription': {
                           'before': 'ikwen.billing.collect.product_set_checkout',
                           'after': 'ikwen.billing.collect.product_do_checkout'}})
    def test_subscribe_to_plan(self):
        Subscription.objects.all().delete()
        self.client.login(username='member3', password='admin')
        response = self.client.post(reverse('billing:momo_set_checkout'),
                                   {'product_id': '55eb63379c531e012d04b37a', 'payment_conf': 'subscription'})
        self.assertEqual(response.status_code, 200)
        # Init payment from Checkout page
        response = self.client.get(reverse('billing:init_momo_transaction'), data={'phone': '677003321'})
        json_resp = json.loads(response.content)
        tx_id = json_resp['tx_id']
        response = self.client.get(reverse('billing:check_momo_transaction_status'), data={'tx_id': tx_id})
        self.assertEqual(response.status_code, 200)
        json_resp = json.loads(response.content)
        self.assertTrue(json_resp['success'])
        subscription = Subscription.objects.get(member='56eb6d04b37b3379b531e013', status=Subscription.ACTIVE)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801', IS_IKWEN=False, DEBUG=True,
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       IKWEN_CONFIG_MODEL='billing.OperatorProfile',
                       EMAIL_FILE_PATH='test_emails/billing/', UNIT_TESTING=True)
    def test_pay_invoice_with_invoicing_config_return_url(self):
        """
        If InvoicingConfig has a return_url, then successful payment hits that
        return_url with the following parameters:
            reference_id: Reference ID of the subscription
            invoice_number:
            amount_paid
            extra_months: Extra months the customer decided to in addition of those of the current invoice
        """
        invoice_id = '56eb6d04b379d531e01237d3'
        sub_id = '56eb6d04b37b3379c531e013'
        Subscription.objects.filter(pk=sub_id).update(expiry=datetime.now().date())
        invoicing_config = get_invoicing_config_instance()
        invoicing_config.return_url = 'http://localhost/notify/'
        invoicing_config.save(using=UMBRELLA)
        self.client.login(username='member3', password='admin')
        response = self.client.post(reverse('billing:momo_set_checkout'), {'invoice_id': invoice_id})
        self.assertEqual(response.status_code, 200)
        # Init payment from Checkout page
        response = self.client.get(reverse('billing:init_momo_transaction'), data={'phone': '677003321'})
        json_resp = json.loads(response.content)
        tx_id = json_resp['tx_id']
        response = self.client.get(reverse('billing:check_momo_transaction_status'), data={'tx_id': tx_id})
        self.assertEqual(response.status_code, 200)
        json_resp = json.loads(response.content)
        self.assertTrue(json_resp['success'])
        self.assertEqual(Invoice.objects.get(pk=invoice_id).status, Invoice.PAID)
        expiry = (datetime.now() + timedelta(days=30)).date()
        self.assertEqual(Subscription.objects.get(pk=sub_id).expiry, expiry)

    @override_settings(IKWEN_SERVICE_ID='54ad2bd9b37b335a18fe5801')
    def test_PricingPage(self):
        """
        The pricing page shows all active billing Product
        """
        response = self.client.get(reverse('billing:pricing'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['product_list']), 2)
