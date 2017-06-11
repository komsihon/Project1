
from django.conf import settings
from django.core.management import call_command
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest

from ikwen.partnership.models import PartnerProfile

# Override BILLING_SUBSCRIPTION_MODEL before ikwen.billing.models is loaded
setattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'core.Service')
setattr(settings, 'BILLING_INVOICE_ITEM_MODEL', 'billing.IkwenInvoiceItem')


from ikwen.core.tests_views import wipe_test_data
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.core.models import Service, Application
from ikwen.billing.models import CloudBillingPlan, InvoicingConfig, InvoiceEntry, IkwenInvoiceItem


class AppRetailSetupTestCase(unittest.TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml', 'billing_plans.yaml']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', LOCAL_DEV=True,
                       BILLING_SUBSCRIPTION_MODEL='core.Service',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/cloud_setup/')
    def test_setup(self):
        app = Application.objects.using(UMBRELLA).get(pk='56eb6d04b37b3379b531a001')
        billing_cycle = 'Quarterly'
        billing_plan = CloudBillingPlan.objects.using(UMBRELLA).get(pk='57e7b9b5371b6d0cb131a001')
        member = Member.objects.using(UMBRELLA).get(pk='56eb6d04b37b3379b531e014')
        project_name = 'IT Pro'
        setup_cost = 45000
        monthly_cost = 13500
        item1 = IkwenInvoiceItem(label='Website Cloud Setup', price=billing_plan.setup_cost, amount=setup_cost)
        entries = [
            InvoiceEntry(item=item1),
        ]
        from ikwen.partnership.cloud_setup import deploy
        deploy(app, member, project_name, billing_plan, monthly_cost, billing_cycle, entries)
        service_umbrella = Service.objects.get(domain='itpro.ikwen.com')
        service_original = Service.objects.using('itpro').get(domain='itpro.ikwen.com')
        self.assertIsNotNone(PartnerProfile.objects.get(service=service_umbrella))
        self.assertIsNotNone(PartnerProfile.objects.using('itpro').get(service=service_original))
        self.assertIsNotNone(InvoicingConfig.objects.using('itpro').all()[0])
