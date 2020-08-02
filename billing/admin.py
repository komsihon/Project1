# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from threading import Thread

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Group
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ikwen.accesscontrol.backends import UMBRELLA
from import_export.admin import ImportExportMixin

from currencies.models import Currency
from ikwen.accesscontrol.models import Member, SUDO
from ikwen.billing.models import Payment, AbstractInvoice, InvoicingConfig, Invoice, NEW_INVOICE_EVENT, \
    SUBSCRIPTION_EVENT, PaymentMean, MoMoTransaction, CloudBillingPlan, PAYMENT_CONFIRMATION, SupportBundle
from ikwen.billing.utils import get_payment_confirmation_message, get_invoice_generated_message, \
    get_next_invoice_number, get_subscription_registered_message, get_subscription_model, get_product_model, \
    get_invoicing_config_instance, get_days_count, share_payment_and_set_stats
from ikwen.core.admin import CustomBaseAdmin
from ikwen.core.models import QueuedSMS, Config, Application, Service, RETAIL_APP_SLUG
from ikwen.core.utils import get_service_instance, get_mail_content, send_sms, add_event, add_database
from ikwen.partnership.models import ApplicationRetailConfig
from import_export import resources, fields

Product = get_product_model()
subscription_model_name = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')
Subscription = get_subscription_model()


class InvoicingConfigAdmin(CustomBaseAdmin):
    list_display = ('gap', 'reminder_delay', 'overdue_delay', 'tolerance', )
    fieldsets = (
        (_('General'), {'fields': ('gap', 'separate_billing_cycle', 'processing_fees_on_customer', )}),
        (_('Invoice generation'), {'fields': ('new_invoice_subject', 'new_invoice_message', 'new_invoice_sms', )}),
        (_('Reminders'), {'fields': ('reminder_delay', 'reminder_subject', 'reminder_message', 'reminder_sms', )}),
        (_('Overdue'), {'fields': ('overdue_delay', 'tolerance', 'overdue_subject', 'overdue_message', 'overdue_sms')}),
        (_('Service suspension'), {'fields': ('service_suspension_subject', 'service_suspension_message', 'service_suspension_sms')}),
        (_('API'), {'fields': ('pull_invoice', 'suspension_return_url', 'return_url', )}),
    )
    save_on_top = True


class ProductAdmin(CustomBaseAdmin, ImportExportMixin):
    list_display = ('name', 'short_description', 'cost', )
    search_fields = ('name', )
    readonly_fields = ('created_on', 'updated_on', )
    fields = ('name', 'short_description', 'cost', 'duration', 'duration_text', 'is_one_off', )


class SubscriptionAdmin(CustomBaseAdmin, ImportExportMixin):
    if not getattr(settings, 'IS_IKWEN', False):
        add_form_template = 'admin/subscription/change_form.html'
        change_form_template = 'admin/subscription/change_form.html'

    list_display = ('member', 'monthly_cost', 'billing_cycle', 'expiry', 'status', )
    list_filter = ('status', 'billing_cycle', )
    search_fields = ('member_name', 'member_phone', )
    fieldsets = (
        (None, {'fields': ('reference_id', 'product', 'monthly_cost', 'billing_cycle', )}),
        (_('Billing'), {'fields': ('status', 'expiry', 'invoice_tolerance', )}),
        (_('Important dates'), {'fields': ('updated_on', 'since', )}),
    )
    readonly_fields = ('updated_on', 'since', )
    save_on_top = True

    def get_search_results(self, request, queryset, search_term):
        try:
            int(search_term)
            members = list(Member.objects.filter(
                Q(phone__contains=search_term) | Q(full_name__icontains=search_term.lower())
            ))
            queryset = self.model.objects.filter(member__in=members)
            use_distinct = False
        except ValueError:
            members = list(Member.objects.filter(full_name__icontains=search_term.lower()))
            queryset = self.model.objects.filter(member__in=members)
            use_distinct = False
        return queryset, use_distinct

    def save_model(self, request, obj, form, change):
        # Send e-mail for manually generated Invoice upon creation
        super(SubscriptionAdmin, self).save_model(request, obj, form, change)
        if change:
            return

        # Send e-mail only if e-mail is a valid one. It will be agreed that if a client
        # does not have an e-mail. we create a fake e-mail that contains his phone number.
        # So e-mail containing phone number are invalid.
        member = obj.member
        service = get_service_instance()
        config = service.config
        subject, message, sms_text = get_subscription_registered_message(obj)

        # This helps differentiates from fake email accounts created as phone@provider.com
        if member.email.find(member.phone) < 0:
            add_event(service, SUBSCRIPTION_EVENT, member=member, object_id=obj.id, model=subscription_model_name)
            html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
            # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
            # to be delivered to Spams because of origin check.
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            Thread(target=lambda m: m.send(), args=(msg,)).start()
        if sms_text:
            if member.phone:
                if config.sms_sending_method == Config.HTTP_API:
                    send_sms(member.phone, sms_text)
                else:
                    QueuedSMS.objects.create(recipient=member.phone, text=sms_text)


class SubscriptionResource(resources.ModelResource):
    client = fields.Field(column_name=_('Client'))
    reference_id = fields.Field(column_name=_('Reference ID'))
    product = fields.Field(column_name=_('Product'))
    monthly_cost = fields.Field(column_name=_('Monthly cost'))
    billing_cycle = fields.Field(column_name=_('Billing cycle'))
    expiry = fields.Field(column_name=_('Expiry'))
    invoice_tolerance = fields.Field(column_name=_('Tolerance'))
    status = fields.Field(column_name=_('Status'))
    since = fields.Field(column_name=_('Since'))

    class Meta:
        model = Subscription
        fields = ('client', 'reference_id', 'product', 'monthly_cost',
                  'billing_cycle', 'expiry', 'invoice_tolerance', 'status', 'since')
        export_order = ('client', 'reference_id', 'product', 'monthly_cost',
                        'billing_cycle', 'expiry', 'invoice_tolerance', 'status', 'since')

    def dehydrate_client(self, obj):
        try:
            member = obj.member
            if member:
                return member.full_name
        except Member.DoesNotExist:
            pass
        return '<Anonymous>'

    def dehydrate_reference_id(self, obj):
        if obj.reference_id:
            return obj.reference_id
        return ''

    def dehydrate_product(self, obj):
        try:
            product = obj.product
            if product:
                return product.name
        except Product.DoesNotExist:
            pass
        return ''

    def dehydrate_monthly_cost(self, obj):
        return obj.monthly_cost

    def dehydrate_billing_cycle(self, obj):
        return obj.billing_cycle

    def dehydrate_expiry(self, obj):
        if obj.expiry:
            return obj.expiry.strftime('%Y-%m-%d %H:%M')
        return 'N/A'

    def dehydrate_invoice_tolerance(self, obj):
        return obj.invoice_tolerance

    def dehydrate_status(self, obj):
        return obj.status

    def dehydrate_since(self, obj):
        if obj.since:
            return obj.since.strftime('%y-%m-%d %H:%M')
        return 'N/A'


class PaymentResource(resources.ModelResource):
    client = fields.Field(column_name=_('Client'))
    invoice_number = fields.Field(column_name=_('Invoice No'))
    amount = fields.Field(column_name=_('Amount'))
    method = fields.Field(column_name=_('Method'))
    cashier = fields.Field(column_name=_('Cashier'))
    created_on = fields.Field(column_name='Date')

    class Meta:
        model = Payment
        fields = ('client', 'invoice_number', 'amount', 'method', 'cashier', 'created_on', )
        export_order = ('client', 'invoice_number', 'amount', 'method', 'cashier', 'created_on', )

    def dehydrate_client(self, payment):
        try:
            member = payment.invoice.member
            if member:
                return member.full_name
        except:
            pass
        return '<Anonymous>'

    def dehydrate_invoice_number(self, payment):
        try:
            invoice = payment.invoice
            if invoice:
                return invoice.number
        except Invoice.DoesNotExist:
            pass
        return 'N/A'

    def dehydrate_amount(self, payment):
        return payment.amount

    def dehydrate_method(self, payment):
        return payment.method

    def dehydrate_cashier(self, payment):
        try:
            cashier = payment.cashier
            if cashier:
                return cashier.full_name
        except Member.DoesNotExist:
            pass
        return 'N/A'

    def dehydrate_created_on(self, payment):
        return payment.created_on.strftime('%y-%m-%d %H:%M')


class PaymentInline(admin.TabularInline):
    model = Payment
    list_display = ('amount', 'method', 'created_on', 'cashier', )

    def get_extra(self, request, obj=None, **kwargs):
        if obj.status == Invoice.PAID:
            return 0
        return 1

    def get_max_num(self, request, obj=None, **kwargs):
        if obj.status == Invoice.PAID:
            return 1

    def get_readonly_fields(self, request, obj=None):
        if obj.status == Invoice.PAID:
            return 'method', 'amount', 'created_on', 'cashier'
        return 'created_on', 'cashier'

    def has_delete_permission(self, request, obj=None):
        if obj.status == Invoice.PAID:
            return False
        return super(PaymentInline, self).has_delete_permission(request, obj)


class InvoiceAdmin(CustomBaseAdmin, ImportExportMixin):
    if not getattr(settings, 'IS_IKWEN', False):
        add_form_template = 'admin/invoice/change_form.html'
        change_form_template = 'admin/invoice/change_form.html'

    list_display = ('subscription', 'number', 'amount', 'date_issued', 'due_date', 'reminders_sent', 'status', )
    list_filter = ('status', 'reminders_sent', 'overdue_notices_sent', )
    search_fields = ('member_name', 'member_phone', )
    fieldsets = (
        (None, {'fields': ('number', 'subscription', 'amount', 'due_date', 'date_issued', 'status', )}),
        (_('Notices'), {'fields': ('reminders_sent', 'overdue_notices_sent', )}),
    )
    readonly_fields = ('number', 'date_issued', 'status',  'reminders_sent', 'overdue_notices_sent', )
    raw_id_fields = ('subscription', )
    inlines = (PaymentInline, )
    save_on_top = True

    def get_readonly_fields(self, request, obj=None):
        if obj.status == Invoice.PAID:
            return 'number', 'subscription', 'amount', 'due_date', 'date_issued', 'status',  'reminders_sent', 'overdue_notices_sent'
        return 'number', 'subscription', 'date_issued', 'status',  'reminders_sent', 'overdue_notices_sent'

    def save_model(self, request, obj, form, change):
        # Send e-mail for manually generated Invoice upon creation
        if change:
            super(InvoiceAdmin, self).save_model(request, obj, form, change)
            return
        obj.number = get_next_invoice_number(auto=False)
        super(InvoiceAdmin, self).save_model(request, obj, form, change)
        member = obj.subscription.member
        service = get_service_instance()
        config = service.config
        subject, message, sms_text = get_invoice_generated_message(obj)
        if member.email:
            add_event(service, NEW_INVOICE_EVENT, member=member, object_id=obj.id)
            invoice_url = service.url + reverse('billing:invoice_detail', args=(obj.id,))
            html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                            extra_context={'invoice_url': invoice_url})
            # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
            # to be delivered to Spams because of origin check.
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            if msg.send(fail_silently=True):
                obj.reminders_sent = 1
                obj.last_reminder = timezone.now()
        if sms_text:
            if member.phone:
                if config.sms_sending_method == Config.HTTP_API:
                    send_sms(member.phone, sms_text)
                else:
                    QueuedSMS.objects.create(recipient=member.phone, text=sms_text)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        total_amount = 0
        instance = None
        for instance in instances:
            if isinstance(instance, Payment):
                total_amount += instance.amount
                if instance.cashier:
                    # Instances with non null cashier are those that previously existed.
                    # setting them to None allows to ignore them at the end of the loop
                    # since we want to undertake action only for newly added Payment
                    instance = None
                    continue
                instance.cashier = request.user
                instance.save()
        if instance:
            # TODO: Check if the last payment is newly added
            # Notice email is sent only for the last saved Payment,
            # this is why this code is not run within the "for" loop above
            member = instance.invoice.subscription.member
            service = get_service_instance()
            config = service.config
            invoice = instance.invoice
            s = invoice.service
            days = get_days_count(invoice.months_count)
            if s.status == Service.SUSPENDED:
                invoicing_config = get_invoicing_config_instance()
                days -= invoicing_config.tolerance  # Catch-up days that were offered before service suspension
                expiry = datetime.now() + timedelta(days=days)
                expiry = expiry.date()
            elif s.expiry:
                expiry = s.expiry + timedelta(days=days)
            else:
                expiry = datetime.now() + timedelta(days=days)
                expiry = expiry.date()
            s.expiry = expiry
            s.status = Service.ACTIVE
            if invoice.is_one_off:
                s.version = Service.FULL
            s.save()
            share_payment_and_set_stats(invoice, invoice.months_count)

            if s.retailer:
                db = s.retailer.database
                Service.objects.using(db).filter(pk=s.id).update(expiry=s.expiry, status=s.status, version=s.version)

            sudo_group = Group.objects.using(UMBRELLA).get(name=SUDO)
            add_event(service, PAYMENT_CONFIRMATION, group_id=sudo_group.id, object_id=invoice.id)
            add_event(service, PAYMENT_CONFIRMATION, member=member, object_id=invoice.id)
            subject, message, sms_text = get_payment_confirmation_message(instance, member)
            if member.email:
                try:
                    currency = Currency.active.default().symbol
                except:
                    currency = config.currency_code
                invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id,))
                subject, message, sms_text = get_payment_confirmation_message(instance, member)
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                                extra_context={'member_name': member.first_name, 'invoice': invoice,
                                                               'cta': _("View invoice"), 'invoice_url': invoice_url,
                                                               'currency': currency})
                sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
                msg = EmailMessage(subject, html_content, sender, [member.email])
                msg.content_subtype = "html"
                Thread(target=lambda m: m.send(), args=(msg,)).start()
            if sms_text:
                if member.phone:
                    if config.sms_sending_method == Config.HTTP_API:
                        send_sms(member.phone, sms_text)
                    else:
                        QueuedSMS.objects.create(recipient=member.phone, text=sms_text)
            if total_amount >= invoice.amount:
                invoice.status = AbstractInvoice.PAID
                invoice.save()

    def get_search_results(self, request, queryset, search_term):
        try:
            int(search_term)
            members = list(Member.objects.filter(
                Q(phone__contains=search_term) | Q(full_name__icontains=search_term.lower()),
            ))
            subscriptions = []
            for member in members:
                subscriptions.extend(list(Subscription.objects.filter(member=member)))
            queryset = self.get_queryset(request).filter(
                Q(subscription__in=subscriptions) | Q(number__icontains=search_term.lower())
            )
            use_distinct = False
        except ValueError:
            if search_term:
                members = list(Member.objects.filter(full_name__icontains=search_term.lower()))
                # Subscriptions should have been fetched this way:
                #
                # subscriptions = list(Subscription.objects.filter(member__in=members))
                #
                # but it causes an error when Subscription is an ikwen.core.models.Service
                #
                # AttributeError: 'RelatedObject' object has no attribute 'get_internal_type'
                #
                # TODO: Search and fix the issue above
                subscriptions = []
                for member in members:
                    subscriptions.extend(list(Subscription.objects.filter(member=member)))
                queryset = self.get_queryset(request).filter(
                    Q(subscription__in=subscriptions) | Q(number__icontains=search_term.lower())
                )
            use_distinct = False
        return queryset, use_distinct


class PaymentMeanAdmin(admin.ModelAdmin):
    list_display = ('name', 'logo', 'watermark', 'button_img_url', 'is_cashflex')
    search_fields = ('name',)
    prepopulated_fields = {"slug": ("name",)}

    def save_model(self, request, obj, form, change):
        if change:
            obj_before = PaymentMean.objects.get(pk=obj.id)
            for service in Service.objects.all():
                db = service.database
                if not db:
                    continue
                add_database(db)
                try:
                    obj_db = PaymentMean.objects.using(db).get(slug=obj.slug)
                    if obj_db.credentials == obj_before.credentials:
                        obj_db.credentials = obj.credentials
                        obj_db.save(using=db)
                except PaymentMean.DoesNotExist:
                    pass
        else:
            super(PaymentMeanAdmin, self).save_model(request, obj, form, change)


class MoMoTransactionResource(resources.ModelResource):
    operator = fields.Field(column_name='Operator')
    app = fields.Field(column_name='App')
    phone = fields.Field(column_name='Phone')
    amount = fields.Field(column_name='Amount')
    user_id = fields.Field(column_name='User ID')
    created_on = fields.Field(column_name='Date')
    status = fields.Field(column_name='Status')

    class Meta:
        model = MoMoTransaction
        fields = ('created_on', 'operator', 'app', 'phone', 'amount', 'user_id', 'status')
        export_order = ('operator', 'app', 'phone', 'amount', 'user_id', 'created_on', 'status', )

    def dehydrate_created_on(self, tx):
        return tx.created_on.strftime('%Y-%m-%d %H:%M%S')

    def dehydrate_operator(self, tx):
        return tx.wallet

    def dehydrate_app(self, tx):
        try:
            return Service.objects.get(pk=tx.service_id).project_name
        except:
            return 'Kakocase'

    def dehydrate_phone(self, tx):
        return tx.phone

    def dehydrate_amount(self, tx):
        return tx.amount

    def dehydrate_user_id(self, tx):
        return tx.username

    def dehydrate_status(self, tx):
        return tx.status


class MoMoTransactionAdmin(admin.ModelAdmin):
    list_display = ('service', 'phone', 'amount', 'model', 'object_id', 'username', 'created_on', 'status')
    search_fields = ('phone',)
    ordering = ('-id', )
    list_filter = ('wallet', 'created_on', 'status', )
    readonly_fields = ('service_id', 'type', 'wallet', 'username', 'phone', 'amount', 'model',
                       'object_id', 'processor_tx_id', 'task_id', 'message', 'is_running', 'status')

    def get_queryset(self, request):
        if getattr(settings, 'IS_UMBRELLA', False):
            return super(MoMoTransactionAdmin, self).get_queryset(request).using('wallets').filter(is_running=False)
        else:
            service = get_service_instance()
            return super(MoMoTransactionAdmin, self).get_queryset(request).using('wallets').filter(service_id=service.id, is_running=False)


class PartnerListFilter(admin.SimpleListFilter):
    title = _('partner')
    parameter_name = 'partner_id'

    def lookups(self, request, model_admin):
        choices = []
        retail_app = Application.objects.get(slug=RETAIL_APP_SLUG)
        for partner in Service.objects.filter(app=retail_app):
            choice = (partner.id, partner.project_name)
            choices.append(choice)
        return choices

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value():
            partner = Service.objects.get(pk=self.value())
            return queryset.filter(partner=partner)
        return queryset


class CloudBillingPlanAdmin(admin.ModelAdmin):
    list_display = ('app', 'partner', 'name', 'setup_cost', 'setup_months_count', 'monthly_cost',
                    'tx_share_fixed', 'tx_share_rate', 'is_active', 'is_pro_version')
    search_fields = ('app', 'name', )
    list_filter = ('app', PartnerListFilter, )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "partner":
            app = Application.objects.get(slug=RETAIL_APP_SLUG)
            kwargs["queryset"] = Service.objects.filter(app=app)
        return super(CloudBillingPlanAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.partner:
            try:
                ApplicationRetailConfig.objects.get(partner=obj.partner, app=obj.app)
            except ApplicationRetailConfig.DoesNotExist:
                self.message_user(request, "Cannot create a billing plan without a prior retail config for this app")
                return
        super(CloudBillingPlanAdmin, self).save_model(request, obj, form, change)


class SupportBundleAdmin(admin.ModelAdmin):
    list_display = ('type', 'quantity', 'duration', 'cost')


admin.site.register(InvoicingConfig, InvoicingConfigAdmin)
admin.site.register(Invoice, InvoiceAdmin)


if getattr(settings, 'IS_UMBRELLA', False):
    admin.site.register(PaymentMean, PaymentMeanAdmin)
    admin.site.register(MoMoTransaction, MoMoTransactionAdmin)
    admin.site.register(CloudBillingPlan, CloudBillingPlanAdmin)
    admin.site.register(SupportBundle, SupportBundleAdmin)

