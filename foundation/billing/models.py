# -*- coding: utf-8 -*-
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from ikwen.foundation.core.fields import MultiImageField

from ikwen.foundation.accesscontrol.models import Member
from ikwen.foundation.core.models import Model, Service
from ikwen.foundation.core.utils import add_database_to_settings

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


class InvoicingConfig(models.Model):
    name = models.CharField(max_length=100, default=_('Default'),
                            help_text=_("Name of this configuration."))
    currency = models.CharField(max_length=15,
                                help_text=_("Abbreviation of currency in use for the billing system. Eg: "
                                            "<strong>USD Dollar, XAF, Euro, etc.</strong>"))
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
    # This is the default number of days preceding expiry on which invoice must be sent to client.
    # this number can later be overriden per subscription of clients
    gap = models.IntegerField(default=15, verbose_name=_("Gap"),
                              help_text=_("Number of days preceding expiry on which invoice must be sent to client."))
    tolerance = models.IntegerField(default=1, verbose_name=_("Tolerance"),
                                    help_text=_("Number of overdue days allowed. "
                                                "After that, severe action must be undertaken."))
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
                                                    help_text=_("Model of mail to send to client as receipt of payment. "
                                                                "HTML is allowed."))
    payment_confirmation_sms = models.TextField(blank=True, verbose_name=_("Payment confirmation SMS"),
                                                help_text=_("Model of SMS to send to client as receipt of payment."))
    service_suspension_subject = models.CharField(max_length=60, blank=True, verbose_name=_("Service suspension subject"),
                                                  help_text=_("Subject of mail of notice of service suspension."))
    service_suspension_message = models.TextField(blank=True, verbose_name=_("Service suspension message"),
                                                  help_text=_("Model of mail to send to client to notiy service suspension. "
                                                              "HTML is allowed."))
    service_suspension_sms = models.TextField(blank=True, verbose_name=_("Service suspension SMS"),
                                              help_text=_("Model of SMS to send to client to notiy service suspension."))

    class Meta:
        verbose_name_plural = _("Configurations of the invoicing system")

    def __unicode__(self):
        return u'%s' % self.name

    @staticmethod
    def get_default_tolerance():
        try:
            from ikwen.foundation.billing.utils import get_invoicing_config_instance
            invoicing_config = get_invoicing_config_instance()
            return invoicing_config.tolerance
        except:
            return 1


class Product(Model):
    """
    Any product a customer may subscribe to
    """
    IMAGE_UPLOAD_TO = 'ikwen/billing/product_images'
    name = models.CharField(max_length=100, unique=True, db_index=True,
                            help_text="Name of the product as advertised to the customer.")
    short_description = models.CharField(max_length=45, blank=True,
                                         help_text=_("Short description understandable by the customer."))
    monthly_cost = models.FloatField(help_text=_("How much the client must pay per month for this product. "
                                                 "You may override it when subscribing a customer.<br>"
                                                 "<strong>WARNING:</strong> Modifying this will not affect previously "
                                                 "created subscriptions. You must change that individually if you want "
                                                 "your update to take effect on already created subscriptions."))
    image = MultiImageField(upload_to=IMAGE_UPLOAD_TO, blank=True, null=True)
    details = models.TextField(blank=True,
                               help_text=_("Detailed description of the product."))

    def __unicode__(self):
        from ikwen.foundation.billing.utils import get_invoicing_config_instance
        invoicing_config = get_invoicing_config_instance()
        return u'%s: %s %.2f/month' % (self.name, invoicing_config.currency, self.monthly_cost)

    def get_details(self):
        if not self.details:
            return 'N/A'
        return self.details


class AbstractSubscription(Model):
    """
    Abstraction of a client subscription to a service
    """
    PENDING = 'Pending'
    SUSPENDED = 'Suspended'
    CANCELED = 'Canceled'
    ACTIVE = 'Active'
    STATUS_CHOICES = (
        (PENDING, _('Pending')),
        (SUSPENDED, _('Suspended')),
        (CANCELED, _('Canceled')),
        (ACTIVE, _('Active'))
    )
    member = models.ForeignKey(Member, related_name='+',
                               help_text=_("Client who subscribes to the service."))
    product = models.ForeignKey(getattr(settings, 'BILLING_PRODUCT_MODEL', 'billing.Product'))
    monthly_cost = models.FloatField(help_text=_("How much the client must pay per month for the service."))
    billing_cycle = models.CharField(max_length=30, choices=Service.BILLING_CYCLES_CHOICES, blank=True,
                                     help_text=_("The interval after which invoice are sent to client."))
    details = models.TextField(blank=True,
                               help_text=_("More details about this subscription."))
    # Date of expiry of the service. The billing system automatically sets it to
    # Invoice.due_date + invoice_tolerance
    # Invoice in this case is the invoice addressed to client for this Service
    expiry = models.DateTimeField(blank=True, null=True,
                                  help_text=_("Date of expiry of the service."))
    invoice_tolerance = models.IntegerField(default=InvoicingConfig.get_default_tolerance,
                                            help_text=_("Number of overdue days allowed. "
                                                        "After that, severe action must be undertaken."))
    status = models.CharField(max_length=15, default=PENDING, choices=STATUS_CHOICES)
    since = models.DateTimeField(verbose_name=_('Subscribed on'),
                                 help_text=_("Date when the user subscribed"))

    class Meta:
        abstract = True


class Subscription(AbstractSubscription):
    """
    A client subscription to a service
    """

    def __unicode__(self):
        from ikwen.foundation.billing.utils import get_invoicing_config_instance
        invoicing_config = get_invoicing_config_instance()
        return u'%s: %s %.2f/month' % (self.member.full_name, invoicing_config.currency, self.monthly_cost)


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
    number = models.CharField(max_length=10)
    amount = models.PositiveIntegerField()
    date_issued = models.DateTimeField(default=timezone.now)
    due_date = models.DateField()
    reminders_sent = models.IntegerField(default=0,
                                         help_text="Number of reminders sent to the client.")
    last_reminder = models.DateTimeField(blank=True, null=True,
                                         help_text=_("Last time the invoice reminder was sent to client"))
    overdue_notices_sent = models.IntegerField(default=0,
                                               help_text="Number of invoice overdue notice sent to the client.")
    last_overdue_notice = models.DateTimeField(blank=True, null=True,
                                               help_text=_("Last time the overdue notice was sent to client"))
    status = models.CharField(choices=INVOICE_STATUS_CHOICES, max_length=30, default=PENDING)

    class Meta:
        abstract = True

    def __unicode__(self):
        return _("Invoice No. ") + self.number


class Invoice(AbstractInvoice):
    subscription = models.ForeignKey(getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', Subscription), related_name='+')

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
        using = 'default'
        if kwargs.get('using'):
            using = kwargs['using']
            del(kwargs['using'])
        if getattr(settings, 'IS_IKWEN', False):
            # If we are on Ikwen itself, replicate the update on the current Service database
            if self.subscription.__dict__.get('database'):
                add_database_to_settings(self.subscription.database)
                super(Invoice, self).save(using=self.subscription.database, *args, **kwargs)
        super(Invoice, self).save(using=using, *args, **kwargs)


class SendingReport(Model):
    """
    Report information about a sending performed
    by a billing cron task.
    """
    count = models.IntegerField()
    total_amount = models.FloatField()


class AbstractPayment(Model):
    CASH = "Cash"
    WENCASH = "WenCash"
    PAYPAL = "Paypal"
    CHECK = "Check"
    BANK_CARD = "BankCard"
    BANK_TRANSFER = "BankTransfer"
    MONEY_TRANSFER = "MoneyTransfer"
    METHODS_CHOICES = (
        (CASH, _("Cash")),
        (WENCASH, "WenCash"),
        (PAYPAL, "Paypal"),
        (CHECK, _("Check")),
        (BANK_CARD, _("Bank card")),
        (BANK_TRANSFER, _("Bank transfer")),
        (MONEY_TRANSFER, _("Money transfer")),
    )
    method = models.CharField(max_length=60, choices=METHODS_CHOICES)
    amount = models.PositiveIntegerField()
    cashier = models.ForeignKey(Member, blank=True, null=True, related_name='+',
                                help_text=_("If the payment was in cash, this is who collected the money"))

    class Meta:
        abstract = True


class Payment(AbstractPayment):
    invoice = models.ForeignKey(Invoice)

    def get_member(self):
        return str(self.invoice.subscription.member)
    get_member.short_description = _('Member')

    def save(self, *args, **kwargs):
        """
        In real world, this object is replicated in the sub_database for consistency purposes and so will hardly
        be modified from that database since Payment object is never exposed in the admin interface of the IAO.
        So said the save() method on this object will generally be called when the object is being manipulated
        from the upper Ikwen website itself. The changes made from there must then be replicated to the sub database.

        The replication is made by adding the actual Payment database to DATABASES in settings and calling
        save(using=database).

        Let's recall that we determine if we are on Ikwen website by testing that there is no DATABASE connection
        named 'foundation', since 'foundation' is the 'default' database there.
        """
        from ikwen.foundation.accesscontrol.backends import UMBRELLA
        using = 'default'
        if kwargs.get('using'):
            using = kwargs['using']
            del(kwargs['using'])
        databases = getattr(settings, 'DATABASES')
        if not databases.get(UMBRELLA):
            # If we are on Ikwen itself, replicate the update on the current Service database
            if self.invoice.subscription.__dict__.get('database'):
                add_database_to_settings(self.invoice.subscription.database)
                super(Payment, self).save(using=self.invoice.subscription.database, *args, **kwargs)
        super(Payment, self).save(using=using, *args, **kwargs)
