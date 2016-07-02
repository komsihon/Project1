# -*- coding: utf-8 -*-
from datetime import datetime
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models import Q, get_model
from django.http import HttpResponseForbidden
from django.utils import timezone
from django.utils.module_loading import import_by_path

from ikwen.foundation.core.models import QueuedSMS, Config
from ikwen.foundation.accesscontrol.models import Member
from ikwen.foundation.core.utils import get_service_instance, get_mail_content, send_sms
from import_export.admin import ImportExportMixin, ExportMixin
from django.utils.translation import gettext_lazy as _

from ikwen.foundation.billing.models import Payment, AbstractInvoice, InvoicingConfig, Invoice
from ikwen.foundation.billing.utils import get_payment_confirmation_message, get_invoice_generated_message, \
    get_next_invoice_number

subscription_model_name = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')
app_label = subscription_model_name.split('.')[0]
model = subscription_model_name.split('.')[1]
Subscription = get_model(app_label, model)


class InvoicingConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'gap', 'reminder_delay', 'overdue_delay', 'tolerance', 'currency', )
    fieldsets = (
        (None, {'fields': ('currency', )}),
        (_('Invoice generation'), {'fields': ('gap', 'new_invoice_subject', 'new_invoice_message', 'new_invoice_sms', )}),
        (_('Reminders'), {'fields': ('reminder_delay', 'reminder_subject', 'reminder_message', 'reminder_sms', )}),
        (_('Overdue'), {'fields': ('overdue_delay', 'tolerance', 'overdue_subject', 'overdue_message', 'overdue_sms')}),
        (_('Service suspension'), {'fields': ('service_suspension_subject', 'service_suspension_message', 'service_suspension_sms')}),
    )
    save_on_top = True


class SubscriptionAdmin(admin.ModelAdmin, ImportExportMixin):
    list_display = ('member', 'monthly_cost', 'billing_cycle', 'expiry', 'status', )
    list_filter = ('status', 'billing_cycle', )
    search_fields = ('member_email', 'member_phone', )
    fieldsets = (
        (None, {'fields': ('member', 'monthly_cost', 'billing_cycle', 'details', 'since', )}),
        (_('Billing'), {'fields': ('status', 'expiry', 'invoice_tolerance', )}),
        (_('Important dates'), {'fields': ('created_on', 'updated_on', )}),
    )
    readonly_fields = ('created_on', 'updated_on', )
    raw_id_fields = ('member', )
    save_on_top = True

    def get_search_results(self, request, queryset, search_term):
        try:
            int(search_term)
            members = list(Member.objects.filter(
                Q(phone__contains=search_term) | Q(email__icontains=search_term.lower())
            ))
            queryset = self.model.objects.filter(member__in=members)
            use_distinct = False
        except ValueError:
            members = list(Member.objects.filter(email__icontains=search_term.lower()))
            queryset = self.model.objects.filter(member__in=members)
            use_distinct = False
        return queryset, use_distinct


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 1
    list_display = ('amount', 'method', 'when', 'cashier', )
    readonly_fields = ('when', 'cashier')


class InvoiceAdmin(admin.ModelAdmin, ImportExportMixin):
    list_display = ('subscription', 'number', 'amount', 'date_issued', 'due_date',
                    'reminders_sent', 'overdue_notices_sent', 'status', )
    list_filter = ('status', 'reminders_sent', 'overdue_notices_sent', )
    search_fields = ('member_email', 'member_phone', )
    fieldsets = (
        (None, {'fields': ('number', 'subscription', 'amount', 'due_date', 'date_issued', 'status', )}),
        (_('Notices'), {'fields': ('reminders_sent', 'overdue_notices_sent', )}),
    )
    readonly_fields = ('number', 'date_issued', 'status',  'reminders_sent', 'overdue_notices_sent', )
    raw_id_fields = ('subscription', )
    inlines = (PaymentInline, )
    save_on_top = True

    def save_model(self, request, obj, form, change):
        # Send e-mail for manually generated Invoice upon creation
        if not change:
            # Send e-mail only if e-mail is a valid one. It will be agreed that if a client
            # does not have an e-mail. we create a fake e-mail that contains his phone number.
            # So e-mail containing phone number are invalid.
            obj.number = get_next_invoice_number(auto=False)
            member = obj.subscription.member
            config = get_service_instance().config
            subject, message, sms_text = get_invoice_generated_message(obj)
            if member.email.find(member.phone) < 0:
                invoice_url = getattr(settings, 'PROJECT_URL') + reverse('billing:invoice_detail', args=(obj.id, ))
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                                extra_context={'invoice_url': invoice_url})
                sender = '%s <%s>' % (config.company_name, config.contact_email)
                msg = EmailMessage(subject, html_content, sender, [member.email])
                msg.content_subtype = "html"
                if msg.send():
                    obj.reminders_sent = 1
                    obj.last_reminder = timezone.now()
            if sms_text:
                if member.phone:
                    if config.sms_sending_method == Config.HTTP_API:
                        send_sms(member.phone, sms_text)
                    else:
                        QueuedSMS.objects.create(recipient=member.phone, text=sms_text)
        super(InvoiceAdmin, self).save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        total_amount = 0
        instance = None
        for instance in instances:
            if isinstance(instance, Payment):
                if instance.cashier:
                    instance = None  # Prevents the notification from being sent at the end of this "for" loop
                    continue
                instance.cashier = request.user
                instance.save()
                total_amount += instance.amount
        if instance:
            # TODO: Check if the last payment is newly added
            # Notice email is sent only for the last saved Payment,
            # this is why this code is not run within the "for" loop above
            member = instance.invoice.subscription.member
            config = get_service_instance().config
            subject, message, sms_text = get_payment_confirmation_message(instance)
            if member.email.find(member.phone) < 0:
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
                sender = '%s <%s>' % (config.company_name, config.contact_email)
                msg = EmailMessage(subject, html_content, sender, [member.email])
                msg.content_subtype = "html"
                msg.send()
            if sms_text:
                if member.phone:
                    if config.sms_sending_method == Config.HTTP_API:
                        send_sms(member.phone, sms_text)
                    else:
                        QueuedSMS.objects.create(recipient=member.phone, text=sms_text)
            if total_amount >= instance.invoice.amount:
                instance.invoice.status == AbstractInvoice.PAID
                instance.invoice.save()

    def get_search_results(self, request, queryset, search_term):
        try:
            int(search_term)
            members = list(Member.objects.filter(
                Q(phone__contains=search_term) | Q(email__icontains=search_term.lower()),
            ))
            subscriptions = []
            for member in members:
                subscriptions.extend(list(Subscription.objects.filter(member=member)))
            queryset = self.model.objects.filter(
                Q(subscription__in=subscriptions) | Q(number__icontains=search_term.lower())
            )
            use_distinct = False
        except ValueError:
            members = list(Member.objects.filter(email__icontains=search_term.lower()))
            # Subscriptions should have been fetched this way:
            #
            # subscriptions = list(Subscription.objects.filter(member__in=members))
            #
            # but it causes an error when Subscription is an ikwen.foundation.core.models.Service
            #
            # AttributeError: 'RelatedObject' object has no attribute 'get_internal_type'
            #
            # TODO: Search and fix the issue above
            subscriptions = []
            for member in members:
                subscriptions.extend(list(Subscription.objects.filter(member=member)))
            queryset = self.model.objects.filter(
                Q(subscription__in=subscriptions) | Q(number__icontains=search_term.lower())
            )
            use_distinct = False
        return queryset, use_distinct


class CashierListFilter(admin.SimpleListFilter):
    """
    Implements the filtering of ContentUpdate by member on Content Vendor website
    """

    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = _('cashier')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'member_id'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        choices = []
        for member in Member.objects.filter(is_staff=True):
            choice = (member.id, member.get_full_name())
            choices.append(choice)
        return choices

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value():
            cashier = Member.objects.get(pk=self.value())
            return queryset.filter(cashier=cashier)
        return queryset


class PaymentAdmin(admin.ModelAdmin, ExportMixin):
    list_display = ('get_member', 'amount', 'method', 'when', 'cashier', )
    list_filter = ('when', 'method', CashierListFilter, )
    search_fields = ('member_email', 'member_phone', )
    readonly_fields = ('when', 'cashier')
    raw_id_fields = ('invoice', )

    def save_model(self, request, obj, form, change):
        return HttpResponseForbidden("To add a payment, you must go the Invoice detail form.")

    def get_search_results(self, request, queryset, search_term):
        try:
            int(search_term)
            members = list(Member.objects.filter(
                Q(phone__contains=search_term) | Q(email__icontains=search_term.lower())
            ))
            subscriptions = []
            for member in members:
                subscriptions.extend(list(Subscription.objects.filter(member=member)))
            invoices = list(Invoice.objects.filter(subscription__in=subscriptions))
            queryset = self.model.objects.filter(invoice__in=invoices)
            use_distinct = False
        except ValueError:
            members = list(Member.objects.filter(email__icontains=search_term.lower()))
            subscriptions = []
            for member in members:
                subscriptions.extend(list(Subscription.objects.filter(member=member)))
            invoices = list(Invoice.objects.filter(subscription__in=subscriptions))
            queryset = self.model.objects.filter(invoice__in=invoices)
            use_distinct = False
        return queryset, use_distinct

# Override SubscriptionAdmin class if there's another defined in settings
subscription_model_admin = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL_ADMIN', None)
if subscription_model_admin:
    SubscriptionAdmin = import_by_path(subscription_model_admin)

admin.site.register(InvoicingConfig, InvoicingConfigAdmin)
try:
    admin.site.register(Subscription, SubscriptionAdmin)
except AlreadyRegistered:
    pass
admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Payment, PaymentAdmin)

