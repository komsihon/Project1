# -*- coding: utf-8 -*-
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from djongo import models

from ikwen.core.constants import PENDING
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.core.constants import PENDING_FOR_PAYMENT
from ikwen.core.fields import ImageField, MultiImageField
from ikwen.core.models import Model, Service, Application, AbstractConfig
from ikwen.core.utils import add_database_to_settings

# Business events aimed and the Billing IAO
INVOICES_SENT_EVENT = 'InvoicesSentEvent'
REMINDERS_SENT_EVENT = 'RemindersSentEvent'
OVERDUE_NOTICES_SENT_EVENT = 'OverdueNoticesSentEvent'
SUSPENSION_NOTICES_SENT_EVENT = 'SuspensionNoticesSentEvent'

# Personal events aimed at the Billing IAO Customer
SUBSCRIPTION_EVENT = 'SubscriptionEvent'  # Member newly subscribed to a Service. Rendered by accesscontrol.views.render_access_granted_event
NEW_INVOICE_EVENT = 'NewInvoiceEvent'
INVOICE_REMINDER_EVENT = 'InvoiceReminderEvent'
OVERDUE_NOTICE_EVENT = 'OverdueNoticeEvent'
SERVICE_SUSPENDED_EVENT = 'ServiceSuspendedEvent'
PAYMENT_CONFIRMATION = 'PaymentConfirmation'

JUMBOPAY_MOMO = 'jumbopay-momo'

MTN_MOMO = 'mtn-momo'
ORANGE_MONEY = 'orange-money'
YUP = 'yup'
UBA = 'uba'


class AbstractInvoiceItem(Model):
    label = models.CharField(max_length=100, unique=True)
    amount = models.FloatField(default=0)

    class Meta:
        abstract = True


class InvoiceItem(AbstractInvoiceItem):
    pass


class IkwenInvoiceItem(AbstractInvoiceItem):
    """
    Represents an InvoiceItem that can be retailed by
    a partner. In this case, price is the amount expected
    by ikwen, while amount is what end user actually pays
    """
    price = models.FloatField(default=0)


class InvoiceEntry(Model):
    item = models.EmbeddedField(model_container=getattr(settings, 'BILLING_INVOICE_ITEM_MODEL', 'InvoiceItem'))
    short_description = models.CharField(max_length=100, blank=True)
    quantity = models.FloatField(default=1)
    quantity_unit = models.CharField(max_length=30, blank=True, null=True, default=_("Month(s)"))
    total = models.FloatField(default=0)


class OperatorProfile(AbstractConfig):
    max_customers = models.IntegerField(default=300)

    def save(self, *args, **kwargs):
        using = kwargs.pop('using', 'default')
        if getattr(settings, 'IS_IKWEN', False):
            db = self.service.database
            add_database_to_settings(db)
            try:
                obj_mirror = OperatorProfile.objects.using(db).get(pk=self.id)
                obj_mirror.ikwen_share_rate = self.ikwen_share_rate
                obj_mirror.ikwen_share_fixed = self.ikwen_share_fixed
                obj_mirror.max_customers = self.max_customers
                obj_mirror.cash_out_min = self.cash_out_min
                obj_mirror.cash_out_rate = self.cash_out_rate
                super(OperatorProfile, obj_mirror).save(using=db)
            except OperatorProfile.DoesNotExist:
                pass
        super(OperatorProfile, self).save(using=using, *args, **kwargs)


class InvoicingConfig(models.Model):
    service = models.ForeignKey(Service, blank=True, null=True, related_name='+', on_delete=models.CASCADE)
    separate_billing_cycle = models.BooleanField(default=True)
    processing_fees_on_customer = models.BooleanField(default=False)
    # This is the default number of days preceding expiry on which invoice must be sent to client.
    # this number can later be overriden per subscription of clients
    logo = ImageField(_("Logo"), upload_to='invoicing_config/logos', allowed_extensions=['jpg', 'jpeg'],
                      help_text=_("Logo to display on PDF Invoices. Landscape version is better."))
    gap = models.IntegerField(default=14, verbose_name=_("Gap"),
                              help_text=_("Number of days preceding expiry on which invoice must be sent to client."))
    tolerance = models.IntegerField(default=7, verbose_name=_("Tolerance"),
                                    help_text=_("Number of overdue days allowed. "
                                                "After that, severe action must be undertaken."))
    return_url = models.URLField(blank=True,
                                 help_text="Payment details are routed to this URL upon checkout confirmation. See "
                                           "<a href='http://support.ikwen.com/billing/configuration-return-url'>"
                                           "support.ikwen.com/billing/configuration-return-url</a> for more details.")
    suspension_return_url = models.URLField(blank=True,
                                            help_text="Payment details are routed to this URL upon service suspension. "
                                                      "See <a href='http://support.ikwen.com/billing/configuration-suspension-return-url'>"
                                                      "support.ikwen.com/billing/configuration-suspension-return-url</a> for more details.")
    pull_invoice = models.BooleanField(_("Activate Pull API"), default=False,
                                       help_text="Check if you want your invoices to be pulled from an external system. "
                                                 "You will have to send data to https://api.ikwen.com/billing/pull_invoice "
                                                 "when an invoice is issued. See <a href='http://support.ikwen.com/billing/pulling-invoice-from-external-system'>"
                                                 "http://support.ikwen.com/billing/pulling-invoice-from-external-system</a> for more details.")

    new_invoice_subject = models.CharField(max_length=100, blank=True, verbose_name=_("New invoice subject"),
                                           help_text=_("Subject of the mail of notice of invoice generation."))
    new_invoice_message = models.TextField(blank=True, verbose_name=_("New invoice mail message"),
                                           help_text=_("Model of mail to send for notice of invoice generation."))
    new_invoice_sms = models.TextField(blank=True, verbose_name=_("New invoice SMS"),
                                       help_text=_("Model of SMS to send for notice of invoice generation."))
    reminder_subject = models.CharField(max_length=60, blank=True, verbose_name=_("Reminder subject"),
                                        help_text=_("Subject of the mail that reminds invoice payment."))
    reminder_message = models.TextField(blank=True, verbose_name=_("Reminder message"),
                                        help_text=_("Model of mail to send to remind invoice payment."))
    reminder_sms = models.TextField(blank=True, verbose_name=_("Reminder SMS"),
                                    help_text=_("Model of SMS to send to remind invoice payment."))
    reminder_delay = models.IntegerField(default=5, verbose_name=_("Reminder delay"),
                                         help_text=_("Number of days after which a reminder must be re-sent to client."))
    overdue_subject = models.CharField(max_length=60, blank=True, verbose_name=_("Overdue subject"),
                                       help_text=_("Subject of the mail that informs of invoice overdue."))
    overdue_message = models.TextField(blank=True, verbose_name=_("Overdue message"),
                                       help_text=_("Model of mail to send to inform of invoice overdue"))
    overdue_sms = models.TextField(blank=True, verbose_name=_("Overdue SMS"),
                                   help_text=_("Model of SMS to send to inform of invoice overdue"))
    overdue_delay = models.IntegerField(default=2, verbose_name=_("Overdue delay"),
                                        help_text=_("Number of days after which a reminder must be re-sent to client."))
    payment_confirmation_subject = models.CharField(max_length=60, blank=True, verbose_name=_("Payment confirmation subject"),
                                                    help_text=_("Subject of mail of receipt of payment."))
    payment_confirmation_message = models.TextField(blank=True, verbose_name=_("Payment confirmation message"),
                                                    help_text=_("Model of mail to send to client as receipt of"
                                                                "payment. HTML is allowed."))
    payment_confirmation_sms = models.TextField(blank=True, verbose_name=_("Payment confirmation SMS"),
                                                help_text=_("Model of SMS to send to client as receipt of payment."))
    service_suspension_subject = models.CharField(max_length=60, blank=True, verbose_name=_("Service suspension subject"),
                                                  help_text=_("Subject of mail of notice of service suspension."))
    service_suspension_message = models.TextField(blank=True, verbose_name=_("Service suspension message"),
                                                  help_text=_("Model of mail to send to client to notiy service "
                                                              "suspension. HTML is allowed."))
    service_suspension_sms = models.TextField(blank=True, verbose_name=_("Service suspension SMS"),
                                              help_text=_("Model of SMS to send to client to notify service suspension."))

    class Meta:
        verbose_name_plural = _("Configurations of the invoicing system")

    def __str__(self):
        return u'%s' % self.service

    @staticmethod
    def get_default_tolerance():
        try:
            from ikwen.billing.utils import get_invoicing_config_instance
            invoicing_config = get_invoicing_config_instance()
            return invoicing_config.tolerance
        except:
            return 1


class AbstractProduct(Model):
    """
    Abstract definition of product a customer may subscribe to
    """
    IMAGE_UPLOAD_TO = 'billing/product_images'
    name = models.CharField(max_length=100, unique=True, db_index=True,
                            help_text="Name of the product as advertised to the customer.")
    slug = models.SlugField(unique=True, db_index=True)
    short_description = models.TextField(blank=True,
                                         help_text=_("Short description understandable by the customer."))
    duration = models.IntegerField(default=30,
                                   help_text="Number of days covered by the cost this product.")
    duration_text = models.CharField(max_length=30, blank=True, null=True,
                                     help_text=_("How you want the customer to see the duration.<br>"
                                                 "Eg:<strong>1 month</strong>, <strong>3 months</strong>, etc."))
    cost = models.FloatField(help_text=_("Cost of the product on the duration set previously."))
    image = MultiImageField(upload_to=IMAGE_UPLOAD_TO, blank=True, null=True, max_size=800)
    details = models.TextField(blank=True,
                               help_text=_("Detailed description of the product."))
    is_active = models.BooleanField(default=True,
                                    help_text=_("Check to make the product active."))
    is_main = models.BooleanField(default=False,
                                  help_text=_("Check to make the product active."))
    is_one_off = models.BooleanField(default=False,
                                     help_text=_("One off product generates a one off subscription."))
    order_of_appearance = models.IntegerField(default=1)

    class Meta:
        abstract = True

    def __str__(self):
        from ikwen.core.utils import get_service_instance
        config = get_service_instance().config
        return u'%s: %s %.2f/%d days' % (self.name, config.currency_symbol, self.cost, self.duration)

    def get_details(self):
        if not self.details:
            return 'N/A'
        return self.details


class Product(AbstractProduct):
    """
    Any product a customer may subscribe to
    """


class AbstractSubscription(Model):
    """
    Abstraction of a client subscription to a service
    """
    PENDING = 'Pending'
    SUSPENDED = 'Suspended'
    CANCELED = 'Canceled'
    EXPIRED = 'Expired'
    ACTIVE = 'Active'
    STATUS_CHOICES = (
        (PENDING, _('Pending')),
        (SUSPENDED, _('Suspended')),
        (CANCELED, _('Canceled')),
        (ACTIVE, _('Active'))
    )
    member = models.ForeignKey(Member, blank=True, null=True, related_name='+', on_delete=models.SET_NULL,
                               help_text=_("Client who subscribes to the service."))
    reference_id = models.CharField(_("Reference ID"), max_length=60, blank=True, null=True, db_index=True,
                                    help_text=_("Unique ID of the client subscription in your external system."))
    product = models.ForeignKey(getattr(settings, 'BILLING_PRODUCT_MODEL', 'billing.Product'), on_delete=models.SET_NULL,
                                blank=True, null=True, related_name='+', limit_choices_to={'is_active': True})
    monthly_cost = models.FloatField(blank=True, null=True,
                                     help_text=_("How much the client must pay per month for the service."))
    billing_cycle = models.CharField(max_length=30, choices=Service.BILLING_CYCLES_CHOICES, blank=True,
                                     help_text=_("The interval after which invoice are sent to client."))
    details = models.TextField(blank=True,
                               help_text=_("More details about this subscription."))
    # Date of expiry of the service. The billing system automatically sets it to
    # Invoice.due_date + invoice_tolerance
    # Invoice in this case is the invoice addressed to client for this Service
    expiry = models.DateField(blank=True, null=True,
                              help_text=_("Date of expiry of the service."))
    invoice_tolerance = models.IntegerField(default=InvoicingConfig.get_default_tolerance,
                                            help_text=_("Number of overdue days allowed. "
                                                        "After that, severe action must be undertaken."))
    status = models.CharField(max_length=15, default=PENDING_FOR_PAYMENT, choices=STATUS_CHOICES)
    since = models.DateTimeField(_('Subscribed on'), default=timezone.now, db_index=True,
                                 help_text=_("Date when the user subscribed"))

    class Meta:
        abstract = True

    def get_status(self):
        if self.status != self.EXPIRED and datetime.now().date() < self.expiry:
            self.status = self.EXPIRED
            self.save()
        return self.status


class Subscription(AbstractSubscription):
    """
    A client subscription to a service
    """

    def __str__(self):
        # from ikwen.core.utils import get_service_instance
        # config = get_service_instance().config
        # return u'%s: %s %.2f/month' % (self.member.full_name, config.currency_symbol, self.monthly_cost)
        return u'%s: %s' % (self.member.full_name, self.product.name)


class AbstractInvoice(Model):
    """
    Base class for Invoice in Ikwen apps.
    """
    PENDING = "Pending"
    OVERDUE = "Overdue"
    EXCEEDED = "Exceeded"
    PAID = "Paid"
    INVOICE_STATUS_CHOICES = (
        (PENDING, _("Pending")),
        (OVERDUE, _("Overdue")),
        (EXCEEDED, _("Exceeded")),
        (PAID, _("Paid")),
    )
    member = models.ForeignKey(Member, blank=True, null=True, related_name='+', on_delete=models.SET_NULL,
                               help_text=_("Member to whom invoice is addressed."))
    number = models.CharField(max_length=10)
    amount = models.PositiveIntegerField()
    paid = models.PositiveIntegerField(default=0)
    processing_fees = models.PositiveIntegerField(default=0)
    months_count = models.IntegerField(blank=True, null=True,
                                       help_text="Number of months covered by the payment of this invoice.")
    date_issued = models.DateTimeField(default=timezone.now)
    due_date = models.DateField()
    reminders_sent = models.IntegerField(default=0,
                                         help_text="Number of reminders sent to the client.")
    last_reminder = models.DateTimeField(blank=True, null=True,
                                         help_text=_("Last time the invoice reminder was sent to client."))
    overdue_notices_sent = models.IntegerField(default=0,
                                               help_text="Number of invoice overdue notice sent to the client.")
    last_overdue_notice = models.DateTimeField(blank=True, null=True,
                                               help_text=_("Last time the overdue notice was sent to client."))
    status = models.CharField(choices=INVOICE_STATUS_CHOICES, max_length=30, default=PENDING)
    is_one_off = models.BooleanField(default=not getattr(settings, 'SEPARATE_BILLING_CYCLE', True))
    entries = models.ArrayField(model_container=InvoiceEntry)

    class Meta:
        abstract = True

    def __str__(self):
        return _("Invoice No. ") + self.number

    def get_to_be_paid(self):
        return self.amount - self.paid

    def get_invoiced_to(self):
        return ''


class Invoice(AbstractInvoice):
    subscription = models.ForeignKey(getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', Subscription),
                                     blank=True, null=True, related_name='+', on_delete=models.SET_NULL)

    def _get_service(self):
        return self.subscription
    service = property(_get_service)  # Alias for subscription

    @staticmethod
    def get_last(obj):
        queryset = Invoice.objects.filter(subscription=obj).order_by('-id')
        if queryset.count() > 0:
            return queryset[0]

    def save(self, *args, **kwargs):
        """
        In real world, this object is replicated in the sub_database for consistency purposes and so will hardly
        be modified from that database since Invoice object is never exposed in the admin interface of the IAO.
        So said the save() method on this object will generally be called when the object is being manipulated
        from the upper Ikwen website itself. The changes made from there must then be replicated to the sub database.

        The replication is made by adding the actual Invoice database to DATABASES in settings and calling
        save(using=database).

        Let's recall that we determine if we are on Ikwen website by testing that there is no DATABASE connection
        named 'foundation', since 'foundation' is the 'default' database there.
        """
        using = kwargs.get('using')
        if using:
            del(kwargs['using'])
        else:
            using = 'default'
        if getattr(settings, 'IS_IKWEN', False):
            # If we are on Ikwen itself, replicate the update on the current Service database
            db = self.subscription.__dict__.get('database')
            if db:
                add_database_to_settings(db)
                super(Invoice, self).save(using=db, *args, **kwargs)
        super(Invoice, self).save(using=using, *args, **kwargs)


class SupportBundle(Model):
    """
    A customer support bundle
    """
    TECHNICAL = 'Technical'
    INFOGRAPHICS = 'Infographics'
    MARKETING = 'Marketing'
    TYPE_CHOICES = (
        (TECHNICAL, _("Technical")),
        (INFOGRAPHICS, _("Infographics")),
        (MARKETING, _("Marketing")),
    )

    EMAIL = 'Email'
    PHONE = 'Phone'
    ONSITE = 'Onsite'
    CHANNEL_CHOICES = (
        (EMAIL, _("Email")),
        (PHONE, _("Phone")),
        (ONSITE, _("Onsite")),
    )
    type = models.CharField(max_length=30, choices=TYPE_CHOICES, blank=True, null=True)
    channel = models.CharField(max_length=30, default=EMAIL, choices=CHANNEL_CHOICES)
    description = models.TextField(blank=True, null=True)
    quantity = models.IntegerField(default=0)
    duration = models.IntegerField()
    cost = models.IntegerField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return '%s (%d): %d days' % (self.type, self.quantity, self.duration)


class SupportCode(Model):
    """
    A customer support code. Actually an instance of a
    SupportBundle purchased by a customer
    """
    service = models.OneToOneField(Service, related_name='+', on_delete=models.CASCADE)
    token = models.CharField(max_length=60)
    bundle = models.ForeignKey(SupportBundle, blank=True, null=True, on_delete=models.SET_NULL)
    balance = models.IntegerField(default=0)
    expiry = models.DateTimeField(db_index=True)


class Donation(Model):
    """
    A donation offered by a website visitor
    """
    member = models.ForeignKey(Member, blank=True, null=True, on_delete=models.SET_NULL,
                               help_text="Member who gives if authenticated user.")
    amount = models.FloatField()
    message = models.TextField(blank=True, null=True,
                               help_text="Message from the person.")
    status = models.CharField(max_length=15, default=PENDING)


class SendingReport(Model):
    """
    Report information about a sending performed
    by a billing cron task.
    """
    count = models.IntegerField()
    total_amount = models.FloatField()


class AbstractPayment(Model):
    CASH = "Cash"
    MOBILE_MONEY = "MobileMoney"
    PAYPAL = "Paypal"
    CHECK = "Check"
    BANK_CARD = "BankCard"
    BANK_TRANSFER = "BankTransfer"
    MONEY_TRANSFER = "MoneyTransfer"
    WALLET_DEBIT = "WalletDebit"
    METHODS_CHOICES = (
        (CASH, _("Cash")),
        (MOBILE_MONEY, "WenCash"),
        (PAYPAL, "Paypal"),
        (CHECK, _("Check")),
        (BANK_CARD, _("Bank card")),
        (BANK_TRANSFER, _("Bank transfer")),
        (MONEY_TRANSFER, _("Money transfer")),
        (WALLET_DEBIT, _("Wallet debit")),
    )
    method = models.CharField(max_length=60, choices=METHODS_CHOICES)
    processor_tx_id = models.CharField(max_length=60, blank=True, null=True, default=None, db_index=True)
    amount = models.PositiveIntegerField()
    cashier = models.ForeignKey(Member, blank=True, null=True, related_name='+', on_delete=models.SET_NULL,
                                help_text=_("If the payment was in cash, this is who collected the money"))

    class Meta:
        abstract = True


class Payment(AbstractPayment):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)

    def __str__(self):
        return self.invoice.member.full_name

    def get_member(self):
        return self.invoice.member.full_name
    get_member.short_description = _('Member')

    def save(self, *args, **kwargs):
        """
        In real world, this object is replicated in the sub_database for consistency purposes and so will hardly
        be modified from that database since Payment object is never exposed in the admin interface of the IAO.
        So said the save() method on this object will generally be called when the object is being manipulated
        from the upper ikwen website itself. The changes made from there must then be replicated to the sub database.

        The replication is made by adding the actual Service database to DATABASES in settings and calling
        save(using=database).
        """
        using = kwargs.pop('using', 'default')
        if getattr(settings, 'IS_IKWEN', False):
            # If we are on ikwen itself, replicate the update on the current Service database
            db = self.invoice.subscription.__dict__.get('database')
            if db:
                add_database_to_settings(db)
                super(Payment, self).save(using=db)
        super(Payment, self).save(using=using, *args, **kwargs)

    def _get_transaction(self):
        try:
            return MoMoTransaction.objects.using('wallets').get(processor_tx_id=self.processor_tx_id)
        except:
            pass
    transaction = property(_get_transaction)


class PaymentMean(Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    logo = models.ImageField(upload_to='payment_means', blank=True, null=True)
    watermark = models.ImageField(upload_to='payment_watermarks/', blank=True, null=True)
    button_img_url = models.URLField(blank=True, null=True,
                                     help_text="URL of the button image. That is the image that serves as the "
                                               "button on which the user will click to checkout.")
    action_url_name = models.CharField(max_length=100, blank=True, null=True,
                                       help_text="Name of the action URL of the form that will submit this payment.")
    credentials = models.TextField(blank=True, null=True,
                                   help_text="Credentials of this mean as a JSON string.")
    is_main = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    is_cashflex = models.BooleanField(default=False)

    class Meta:
        db_table = 'ikwen_payment_mean'

    def __str__(self):
        return self.name

    def _get_provider_logo(self):
        if self.is_cashflex:
            try:
                bank = Service.objects.using(UMBRELLA).get(project_name_slug=self.slug)
                return bank.config.logo
            except:
                pass
        else:
            return self.logo
    provider_logo = property(_get_provider_logo)


class MoMoTransaction(Model):
    SUCCESS = 'Success'
    FAILURE = 'Failure'
    DROPPED = 'Dropped'
    REQUEST_EXCEPTION = 'RequestException'
    TIMEOUT = 'Timeout'
    API_ERROR = 'APIError'
    SSL_ERROR = 'SSLError'
    SERVER_ERROR = 'ServerError'

    CASH_IN = 'CashIn'
    CASH_OUT = 'CashOut'

    service_id = models.CharField(max_length=24, db_index=True)
    type = models.CharField(max_length=24, db_index=True)
    wallet = models.CharField(max_length=60, blank=True, null=True, db_index=True,
                              help_text="Wallet Provider Solution. Eg: MTN MoMo, Orange Money, etc.")
    username = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    phone = models.CharField(max_length=24, db_index=True)
    amount = models.FloatField(default=0)
    fees = models.FloatField(default=0)  # Transaction fees
    dara_fees = models.FloatField(default=0)  # Dara fees
    dara_id = models.CharField(max_length=24, blank=True, null=True, db_index=True)
    model = models.CharField(max_length=150, blank=True, null=True, db_index=True)
    object_id = models.CharField(max_length=60, blank=True, null=True)
    processor_tx_id = models.CharField(max_length=100, blank=True, db_index=True,
                                       help_text="ID of the transaction in the Payment Processor system")
    task_id = models.CharField(max_length=60, blank=True, null=True, db_index=True,
                               help_text="Task ID (Payment Processor API)")
    callback = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    is_running = models.BooleanField(default=True, db_index=True)
    status = models.CharField(max_length=30, blank=True, null=True, db_index=True)

    class Meta:
        db_table = 'ikwen_momo_transaction'
        verbose_name = 'MoMo Transaction'
        verbose_name_plural = 'MoMo Transactions'

    def _get_service(self):
        return Service.objects.using(UMBRELLA).get(pk=self.service_id)
    service = property(_get_service)

    def _get_member(self):
        return Member.objects.using('default').get(username=self.username)
    member = property(_get_member)

    def _get_wallet_name(self):
        if self.wallet == MTN_MOMO:
            return 'MoMo'
        elif self.wallet == ORANGE_MONEY:
            return 'OM'
        elif self.wallet == YUP:
            return 'Yup'
        elif self.wallet == UBA:
            return 'UBA'
        else:
            return self.wallet.capitalize()
    wallet_name = property(_get_wallet_name)


class CloudBillingPlan(Model):
    app = models.ForeignKey(Application, on_delete=models.CASCADE)
    partner = models.ForeignKey(Service, related_name='+', blank=True, null=True, on_delete=models.CASCADE,
                                help_text="Retailer this billing plan applies to.")
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    is_pro_version = models.BooleanField(default=False)
    max_objects = models.IntegerField(default=100)
    tx_share_fixed = models.FloatField(help_text="Fixed amount ikwen collects per transaction "
                                                 "on websites with this billing plan.")
    tx_share_rate = models.FloatField(help_text="Rate ikwen collects per transaction "
                                                "on websites with this billing plan.")
    setup_cost = models.IntegerField(help_text="Setup cost at which ikwen sells the service. "
                                               "Retailer may charge additional fees.")
    setup_months_count = models.IntegerField(help_text="Number of months covered by the payment "
                                                       "of the cloud_setup Invoice.")
    monthly_cost = models.IntegerField(help_text="Monthly cost at which ikwen sells the service. "
                                                 "Retailer may charge additional fees.")

    def __str__(self):
        return '%s: %s (%d)' % (self.app.name, self.name, self.setup_cost)


class BankAccount(Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    bank = models.ForeignKey(Service, related_name='+', on_delete=models.CASCADE)
    number = models.CharField(max_length=60)
    slug = models.CharField(max_length=60)

    class Meta:
        db_table = 'ikwen_bank_account'
