# -*- coding: utf-8 -*-
import csv
import json
import logging
from datetime import date, datetime, timedelta
from threading import Thread
from time import strptime

from ajaxuploader.views import AjaxFileUploader
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.loading import get_model
from django.http import HttpResponse, Http404
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from currencies.context_processors import currencies

from echo.models import Balance
from echo.utils import notify_for_low_messaging_credit, LOW_MAIL_LIMIT, notify_for_empty_messaging_credit
from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.constants import PENDING_FOR_PAYMENT
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member, DEFAULT_GHOST_PWD
from ikwen.billing.models import Invoice, SendingReport, SERVICE_SUSPENDED_EVENT, PaymentMean, \
    InvoiceEntry, InvoiceItem, Payment, InvoicingConfig
from ikwen.billing.admin import ProductAdmin, SubscriptionAdmin, InvoicingConfigAdmin, PaymentResource, \
    SubscriptionResource
from ikwen.billing.utils import get_invoicing_config_instance, get_subscription_model, get_product_model, \
    get_next_invoice_number, get_billing_cycle_months_count, get_payment_confirmation_message, get_days_count, \
    get_months_count_billing_cycle
from ikwen.core.utils import add_database_to_settings, get_service_instance, get_mail_content, XEmailMessage, \
    DefaultUploadBackend, set_counters, increment_history_field, get_model_admin_instance
from ikwen.core.views import HybridListView, ChangeObjectBase

logger = logging.getLogger('ikwen')

Product = get_product_model()
Subscription = get_subscription_model()


class ProductList(HybridListView):
    model = Product
    ordering = ('order_of_appearance', 'cost', )
    list_filter = (('is_active', _('Active')), )
    context_object_name = 'product_list'

    def get(self, request, *args, **kwargs):
        action = self.request.GET.get('action')
        if action == 'delete':
            selection = self.request.GET['selection'].split(',')
            deleted = []
            for pk in selection:
                try:
                    obj = Product.objects.get(pk=pk)
                    if Subscription.objects.filter(product=obj).count() > 0:
                        response = {'message': _("Cannot delete product with actual subscriptions. "
                                                 "Deactivate instead")}
                        return HttpResponse(json.dumps(response))
                    obj.delete()
                    deleted.append(pk)
                except:
                    continue
            response = {
                'message': "%d item(s) deleted." % len(selection),
                'deleted': deleted
            }
            return HttpResponse(json.dumps(response))
        return super(ProductList, self).get(request, *args, **kwargs)


class ChangeProduct(ChangeObjectBase):
    model = Product
    model_admin = ProductAdmin
    template_name = 'billing/change_product.html'


class SubscriptionList(HybridListView):
    queryset = Subscription.objects.select_related('member, product').exclude(status=PENDING_FOR_PAYMENT)
    ordering = ('-id', )
    list_filter = ('product', 'status', ('since', _("Subs. Date")), 'expiry')
    context_object_name = 'subscription_list'
    template_name = 'billing/subscription_list.html'
    html_results_template_name = 'billing/snippets/subscription_list_results.html'
    show_import = True
    export_resource = SubscriptionResource

    def get_search_results(self, queryset, max_chars=None):
        search_term = self.request.GET.get('q')
        if search_term and len(search_term) >= 2:
            search_term = search_term.lower()
            word = slugify(search_term)
            if word:
                word = word[:4]
                member_list = list(Member.objects.filter(full_name__icontains=word))
                queryset = queryset.filter(member__in=member_list)
        return queryset

    def get(self, request, *args, **kwargs):
        action = self.request.GET.get('action')
        if action == 'import':
            return self.import_subscription_file(request)
        if action == 'delete':
            selection = request.GET['selection'].split(',')
            deleted = []
            for pk in selection:
                try:
                    obj = Subscription.objects.get(pk=pk)
                    invoice_queryset = Invoice.objects.filter(subscription=obj)
                    Payment.objects.filter(invoice__in=list(invoice_queryset)).delete()
                    invoice_queryset.delete()
                    obj.delete()
                    deleted.append(pk)
                except:
                    continue
            response = {
                'message': "%d item(s) deleted." % len(selection),
                'deleted': deleted
            }
            return HttpResponse(json.dumps(response))
        return super(SubscriptionList, self).get(request, *args, **kwargs)

    def import_subscription_file(self, request, *args, **kwargs):
        media_url = getattr(settings, 'MEDIA_URL')
        filename = request.GET['filename'].replace(media_url, '')
        error = import_subscriptions(filename)
        if error:
            return HttpResponse(json.dumps({'error': error}))
        import_subscriptions(filename, dry_run=False)
        return HttpResponseRedirect(reverse('billing:subscription_list'))


class ChangeSubscription(ChangeObjectBase):
    model = Subscription
    model_admin = SubscriptionAdmin
    template_name = 'billing/change_subscription.html'

    def get_object(self, **kwargs):
        object_id = kwargs.get('object_id')
        if object_id:
            try:
                return Subscription.objects.select_related('member', 'product').get(pk=object_id)
            except Subscription.DoestNotExist:
                raise Http404("Subscription %s does not exist" % object_id)

    def get_context_data(self, **kwargs):
        context = super(ChangeSubscription, self).get_context_data(**kwargs)
        invoicing_config = get_invoicing_config_instance()
        context['default_tolerance'] = invoicing_config.tolerance
        obj = context['obj']
        product_costs = {}
        for product in Product._default_manager.filter(is_active=True):
            product_costs[str(product.id)] = product.cost
        context['product_costs'] = product_costs
        context['invoice_list'] = Invoice.objects.select_related('subscription').filter(subscription=obj)[:10]
        return context

    def after_save(self, request, obj, *args, **kwargs):
        object_id = kwargs.get('object_id')
        if object_id:
            return
        # It's a student under creation, so set a new Invoice for him
        number = get_next_invoice_number()
        months_count = get_billing_cycle_months_count(obj.billing_cycle)
        try:
            amount = float(request.POST.get('amount'))
        except:
            amount = obj.monthly_cost * months_count
        product = obj.product
        if product:
            short_description = product.name
        else:
            short_description = request.POST.get('short_description', '---')
        obj.details = short_description
        obj.save()
        invoice_entries = []
        item = InvoiceItem(label=_('Subscription'), amount=amount)
        entry = InvoiceEntry(item=item, short_description=short_description, quantity=months_count, total=amount)
        invoice_entries.append(entry)
        invoice = Invoice.objects.create(number=number, subscription=obj, amount=amount, months_count=months_count,
                                         due_date=obj.expiry, entries=invoice_entries, is_one_off=True)
        email = request.POST.get('email')
        member_id = request.POST.get('member_id')
        if member_id:
            member = Member.objects.get(pk=member_id) if member_id else None
        elif email:
            try:
                member = Member.objects.filter(email=email)[0]
            except:
                member = Member.objects.create_user(email, DEFAULT_GHOST_PWD, email=email, is_ghost=True)
        else:
            return
        obj.member = member
        obj.save()
        service = get_service_instance()
        config = service.config
        with transaction.atomic(using=WALLETS_DB_ALIAS):
            balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
            if 0 < balance.mail_count < LOW_MAIL_LIMIT:
                try:
                    notify_for_low_messaging_credit(service, balance)
                except:
                    logger.error("Failed to notify %s for low messaging credit." % service, exc_info=True)
            if balance.mail_count == 0 and not getattr(settings, 'UNIT_TESTING', False):
                try:
                    notify_for_empty_messaging_credit(service, balance)
                except:
                    logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
                return
            if product:
                subject = _("Your invoice for subscription to %s" % product.name)
            else:
                if short_description != '---':
                    subject = _("Your invoice for " + short_description)
                else:
                    subject = _("Your invoice for subscription")
            try:
                currency = currencies(request)['CURRENCY'].symbol
            except:
                currency = config.currency_symbol
            invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id, ))
            html_content = get_mail_content(subject, template_name='billing/mails/notice.html',
                                            extra_context={'invoice': invoice, 'member_name': member.first_name,
                                                           'invoice_url': invoice_url, 'cta': _("Pay now"),
                                                           'currency': currency})
            sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
            msg = XEmailMessage(subject, html_content, sender, [email])
            msg.content_subtype = "html"
            balance.mail_count -= 1
            balance.save()
            if getattr(settings, 'UNIT_TESTING', False):
                msg.send()
            else:
                Thread(target=lambda m: m.send(), args=(msg, )).start()


class AdminInvoiceList(HybridListView):
    template_name = 'billing/invoice_list.html'
    html_results_template_name = 'billing/snippets/admin_invoice_list_results.html'
    list_filter = ('status', 'due_date', )

    def get_queryset(self):
        queryset = Invoice.objects.select_related('member').exclude(status=PENDING_FOR_PAYMENT)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(AdminInvoiceList, self).get_context_data(**kwargs)
        context['pending_invoice_count'] = Invoice.objects.exclude(
            Q(status=PENDING_FOR_PAYMENT) & Q(status=Invoice.PAID)
        ).count()
        return context

    def get_search_results(self, queryset, max_chars=None):
        search_term = self.request.GET.get('q')
        if search_term and len(search_term) >= 2:
            search_term = search_term.lower()
            word = slugify(search_term)
            if word:
                word = word[:4]
                member_list = list(Member.objects.filter(full_name__icontains=word))
                if member_list:
                    queryset = queryset.filter(member__in=member_list)
                else:
                    queryset = queryset.filter(number__icontains=word)
        return queryset


class InvoiceList(HybridListView):
    if getattr(settings, 'IS_UMBRELLA', False):
        template_name = 'billing/iao_invoice_list.html'
    else:
        template_name = 'billing/invoice_list.html'
    html_results_template_name = 'billing/snippets/invoice_list_results.html'

    def get_queryset(self):
        member = self.request.user
        queryset = Invoice.objects.filter(member=member, status=Invoice.PAID)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(InvoiceList, self).get_context_data(**kwargs)
        member = self.request.user
        queryset = Invoice.objects.exclude(status=Invoice.PAID).filter(member=member)
        context['pending_invoice_list'] = queryset
        context['pending_invoice_count'] = queryset.count()
        context['is_customer'] = True
        return context


class InvoiceDetail(TemplateView):
    template_name = 'billing/invoice_detail.html'

    def get_context_data(self, **kwargs):
        context = super(InvoiceDetail, self).get_context_data(**kwargs)
        invoice_id = self.kwargs['invoice_id']
        try:
            invoice = Invoice.objects.select_related('subscription').get(pk=invoice_id)
        except Invoice.DoesNotExist:
            raise Http404("Invoice not found")
        try:
            subscription = invoice.subscription
            context['monthly_cost'] = subscription.monthly_cost
        except AttributeError:
            subscription = None
        try:
            product = subscription.product
        except AttributeError:
            product = None
        member = self.request.user
        if member.is_authenticated():
            if not invoice.member and not member.is_staff:
                invoice.member = member
                invoice.save()
            if subscription:
                mbr = subscription.member
                if not mbr or mbr.is_ghost:
                    if not member.is_staff:
                        subscription.member = member
                        subscription.save()
        context['invoice'] = invoice
        if not invoice.entries:
            if product and product.short_description:
                details = product.short_description
            elif subscription.details:
                details = subscription.details
            else:
                details = '------'
            context['details'] = details
        context['payment_mean_list'] = list(PaymentMean.objects.filter(is_active=True).order_by('-is_main'))
        context['invoicing_config'] = get_invoicing_config_instance()
        if getattr(settings, 'IS_IKWEN', False):
            try:
                invoice_service = invoice.service
                retailer = invoice_service.retailer
                context['customer_config'] = invoice_service.config
                context['vendor'] = retailer.config if retailer else get_service_instance().config
            except:
                pass
        else:
            context['vendor'] = get_service_instance().config

        # User may want to extend the payment above the default duration
        # Below are a list of possible extension dates on a year
        # TODO: Manage extensions for case where Product is bound to a duration (billing cycle)
        if not invoice.is_one_off:
            expiry = invoice.subscription.expiry
            exp_year = expiry.year
            exp_month = expiry.month
            exp_day = expiry.day
            extensions = []
            for i in (1, 2, 3, 6, 12):
                year = exp_year
                month = exp_month + i
                day = exp_day
                if month > 12:
                    year += 1
                    month = (exp_month + i) % 12
                    if month == 0:
                        month = 12
                valid_date = False
                while not valid_date:
                    try:
                        next_expiry = date(year, month, day)
                        extensions.append({'expiry': next_expiry, 'months': i})
                        valid_date = True
                    except:
                        day -= 1
            context['extensions'] = extensions
        return context

    def cash_in(self, invoice, request):
        if not request.user.has_perm('billing.ik_cash_in'):
            return HttpResponse(json.dumps({'error': "You're not allowed here"}))
        service = get_service_instance()
        config = service.config
        if invoice.status == Invoice.PAID:
            return HttpResponse(json.dumps({'error': "Invoice already paid"}))
        amount = request.GET.get('amount', invoice.amount)
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError()
        except ValueError:
            return HttpResponse(json.dumps({'error': "Invalid amount"}))
        member = invoice.member
        response = {'success': True}
        payment = Payment.objects.create(invoice=invoice, amount=amount, method=Payment.CASH, cashier=request.user)
        try:
            aggr = Payment.objects.filter(invoice=invoice).aggregate(Sum('amount'))
            amount_paid = aggr['amount__sum']
        except IndexError:
            amount_paid = 0
        total = amount + amount_paid
        if total >= invoice.amount:
            invoice.status = Invoice.PAID
            invoice.save()
            try:
                subscription = invoice.subscription
                subscription.status = Subscription.ACTIVE
                days = get_days_count(invoice.months_count)
                subscription.expiry += timedelta(days=days)
                subscription.save()
            except AttributeError:
                pass
        set_counters(service)
        increment_history_field(service, 'turnover_history', amount)
        increment_history_field(service, 'earnings_history', amount)
        increment_history_field(service, 'transaction_earnings_history', amount)
        increment_history_field(service, 'invoice_earnings_history', amount)
        increment_history_field(service, 'transaction_count_history')
        increment_history_field(service, 'invoice_count_history')
        if member.email:
            balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
            if 0 < balance.mail_count < LOW_MAIL_LIMIT:
                notify_for_low_messaging_credit(service, balance)
            if balance.mail_count <= 0 and not getattr(settings, 'UNIT_TESTING', False):
                notify_for_empty_messaging_credit(service, balance)
                return HttpResponse(json.dumps(response))
            subject, message, sms = get_payment_confirmation_message(payment, member)
            html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
            sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
            msg = XEmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            try:
                with transaction.atomic(using='wallets'):
                    balance.mail_count -= 1
                    balance.save()
                    Thread(target=lambda m: m.send(), args=(msg,)).start()
            except:
                pass
        return HttpResponse(json.dumps(response))

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        invoice_id = kwargs['invoice_id']
        try:
            invoice = Invoice.objects.select_related('member, subscription').get(pk=invoice_id)
        except Invoice.DoesNotExist:
            raise Http404("Invoice not found")
        if action == 'cash_in':
            return self.cash_in(invoice, request)
        member = invoice.member
        if member and not member.is_ghost:
            if request.user.is_authenticated() and not request.user.is_staff:
                if request.user != member:
                    next_url = reverse('ikwen:sign_in')
                    next_url += '?next=' + reverse('billing:invoice_detail', args=(invoice.id, ))
                    return HttpResponseRedirect(next_url)
        return super(InvoiceDetail, self).get(request, *args, **kwargs)


class PaymentList(HybridListView):
    template_name = 'billing/payment_list.html'
    html_results_template_name = 'billing/snippets/payment_list_results.html'
    list_filter = ('cashier', 'method', ('created_on', _('Payment date')), )
    export_resource = PaymentResource

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            queryset = Payment.objects.select_related('invoice').all()
        else:
            queryset = Payment.objects.select_related('invoice').filter(cashier=user)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(PaymentList, self).get_context_data(**kwargs)
        queryset = context['queryset']
        try:
            qs = queryset.filter(method=Payment.CASH)
            aggr = qs.aggregate(Sum('amount'))
            total_cash = {'count': qs.count(), 'amount': aggr['amount__sum']}
        except IndexError:
            total_cash = {'count': 0, 'amount': 0}
        try:
            qs = queryset.filter(method=Payment.MOBILE_MONEY)
            aggr = qs.aggregate(Sum('amount'))
            total_momo = {'count': qs.count(), 'amount': aggr['amount__sum']}
        except IndexError:
            total_momo = {'count': 0, 'amount': 0}
        try:
            qs = queryset.filter(method=Payment.BANK_CARD)
            aggr = qs.aggregate(Sum('amount'))
            total_bank_card = {'count': qs.count(), 'amount': aggr['amount__sum']}
        except IndexError:
            total_bank_card = {'count': 0, 'amount': 0}
        try:
            qs = queryset.exclude(Q(method=Payment.CASH) & Q(method=Payment.MOBILE_MONEY) & Q(method=Payment.BANK_CARD))
            aggr = qs.aggregate(Sum('amount'))
            total_other = {'count': qs.count(), 'amount': aggr['amount__sum']}
        except IndexError:
            total_other = {'count': 0, 'amount': 0}
        context['total_cash'] = total_cash
        context['total_momo'] = total_momo
        context['total_bank_card'] = total_bank_card
        context['total_other'] = total_other
        return context

    def get_search_results(self, queryset, max_chars=None):
        search_term = self.request.GET.get('q')
        if search_term and len(search_term) >= 2:
            search_term = search_term.lower()
            word = slugify(search_term)
            if word:
                word = word[:4]
                member_list = list(Member.objects.filter(full_name__icontains=word))
                invoice_list = list(Invoice.objects.filter(member__in=member_list))
                queryset = queryset.select_relate('invoice').filter(invoice__in=invoice_list)
        return queryset


@login_required
def change_billing_cycle(request, *args, **kwargs):
    subscription_id = request.GET['subscription_id']
    new_cycle = request.GET['new_cycle']
    subscription_model = get_subscription_model()
    if getattr(settings, 'IS_IKWEN', False):
        service = subscription_model.objects.using(UMBRELLA).get(pk=subscription_id)
        service.billing_cycle = new_cycle
        service.save(using=service.database)
    else:
        service = subscription_model.objects.get(pk=subscription_id)
        service.billing_cycle = new_cycle
    service.save()
    callback = request.GET['callback']
    response = callback + '(' + json.dumps({'success': True}) + ')'
    return HttpResponse(response, content_type='application/json')


@login_required
def list_members(request, *args, **kwargs):
    """
    Used for member auto-complete in billing admin upon
    creation of a Subscription.
    """
    q = request.GET['query'].lower()
    if len(q) < 2:
        return

    queryset = Member.objects
    for word in q.split(' '):
        word = slugify(word)[:4]
        if word:
            queryset = queryset.filter(full_name__icontains=word)[:10]
            if queryset.count() > 0:
                break

    suggestions = [{'value': member.full_name, 'data': member.pk} for member in queryset]
    response = {'suggestions': suggestions}
    return HttpResponse(json.dumps(response), content_type='application/json')


@login_required
def list_subscriptions(request, *args, **kwargs):
    """
    Used for member auto-complete in billing admin upon
    creation of a Subscription.
    """
    q = request.GET['query'].lower()
    if len(q) < 2:
        return

    subscriptions = []
    queryset = Member.objects
    for word in q.split(' '):
        word = slugify(word)[:4]
        if word:
            members = list(queryset.filter(full_name__icontains=word)[:10])
            if len(members) > 0:
                subscriptions = list(Subscription.objects.filter(member__in=members))
                break

    suggestions = [{'value': str(s), 'data': s.pk} for s in subscriptions]
    response = {'suggestions': suggestions}
    return HttpResponse(json.dumps(response), content_type='application/json')


def render_subscription_event(event, request):
    service = event.service
    database = service.database
    add_database_to_settings(database)
    tk = event.model.split('.')
    app_label = tk[0]
    model = tk[1]
    subscription_model = get_model(app_label, model)
    try:
        subscription = subscription_model.objects.using(database).get(pk=event.object_id)
        short_description = subscription.__dict__.get('short_description')
        image = subscription.product.image
        try:
            cost = subscription.monthly_cost
            billing_cycle = subscription.billing_cycle
        except AttributeError:
            cost = subscription.product.cost
            billing_cycle = None

        c = Context({'title': _(event.event_type.title),
                     'product_name': subscription.product.name,
                     'short_description': short_description,
                     'currency_symbol': service.config.currency_symbol,
                     'cost': cost,
                     'image_url': image.url if image and image.name else None,
                     'billing_cycle': billing_cycle,
                     'obj': subscription})
    except Subscription.DoesNotExist:
        return None

    html_template = get_template('billing/events/subscription.html')
    return html_template.render(c)


def render_billing_event(event, request):
    service = event.service
    database = service.database
    add_database_to_settings(database)
    currency_symbol = service.config.currency_symbol
    try:
        invoice = Invoice.objects.using(database).get(pk=event.object_id)
        member = invoice.subscription.member
        try:
            details = invoice.subscription.product.get_details()
        except:
            subscription = get_subscription_model().objects.get(pk=invoice.subscription.id)
            details = subscription.details
        from ikwen.conf import settings as ikwen_settings
        data = {'title': _(event.event_type.title),
                'details': details,
                'danger': event.event_type.codename == SERVICE_SUSPENDED_EVENT,
                'currency_symbol': currency_symbol,
                'amount': invoice.amount,
                'obj': invoice,
                'details_url': service.url + reverse('billing:invoice_detail', args=(invoice.id,)),
                'show_pay_now': invoice.status != Invoice.PAID,
                'MEMBER_AVATAR': ikwen_settings.MEMBER_AVATAR, 'IKWEN_MEDIA_URL': ikwen_settings.MEDIA_URL}
        if member.id != request.GET['member_id']:
            data['member'] = member
        c = Context(data)
    except Invoice.DoesNotExist:
        try:
            report = SendingReport.objects.using(database).get(pk=event.object_id)
            c = Context({'title': '<strong>%d</strong> %s' % (report.count, _(event.event_type.title)),
                         'currency_symbol': currency_symbol,
                         'amount': report.total_amount,
                         'details_url': service.url + reverse('billing:iframe_admin', args=('invoice',)),
                         'obj': report})
        except SendingReport.DoesNotExist:
            return None

    html_template = get_template('billing/events/notice.html')
    return html_template.render(c)


class Configuration(ChangeObjectBase):
    model = InvoicingConfig
    model_admin = InvoicingConfigAdmin
    template_name = 'billing/configuration.html'

    def get_object(self, **kwargs):
        return get_invoicing_config_instance()

    def get_object_list_url(self, request, obj, *args, **kwargs):
        return reverse('billing:configuration')

    def post(self, request, *args, **kwargs):
        object_admin = get_model_admin_instance(self.model, self.model_admin)
        obj = self.get_object(**kwargs)
        model_form = object_admin.get_form(request)
        form = model_form(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save(using=UMBRELLA)
            next_url = self.get_object_list_url(request, obj, *args, **kwargs)
            messages.success(request, _('Configuration successfully updated'))
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['errors'] = form.errors
            return render(request, self.template_name, context)


def import_subscriptions(filename, dry_run=True):
    abs_path = getattr(settings, 'MEDIA_ROOT') + filename
    fh = open(abs_path, 'r')
    line = fh.readline()
    fh.close()
    data = line.split(',')
    delimiter = ',' if len(data) > 0 else ';'
    error = None
    row_length = 9
    now = datetime.now()
    with open(abs_path) as csv_file:
        csv_reader = csv.reader(csv_file, delimiter=delimiter)
        i = -1
        for row in csv_reader:
            i += 1
            if i == 0:
                continue
            if len(row) < row_length:
                error = _("Missing information on line %(line)d. %(found)d tokens found, "
                          "but %(expected) expected." % {'line': i + 1, 'found': len(row), 'expected': row_length})
                break
            email = row[0].strip()
            try:
                validate_email(email)
            except ValidationError:
                error = _("Invalid email %(email)s on line %(line)d" % {'email': email, 'line': (i + 1)})
                break
            reference_id = row[1].strip()
            if reference_id:
                try:
                    Subscription.objects.get(reference_id=reference_id)
                    error = _("Reference ID <ins>%(ref)s</ins> on line %(line)d "
                              "already exists." % {'ref': reference_id, 'line': (i + 1)})
                    break
                except Subscription.DoesNotExist:
                    pass
            product_id = row[2].strip().capitalize()
            try:
                product = Product.objects.get(pk=product_id, is_active=True)
            except Product.DoesNotExist:
                pk_list = [obj.id for obj in Product.objects.filter(is_active=True)]
                error = _("Product ID <ins>%(pk)s</ins> not found or inactive. Line %(line)d. \n"
                          "Must be one of <b>%(pk_list)s</b>" % {'pk': product_id, 'line': i + 1, 'pk_list': ', '.join(pk_list)})
                break
            cost = row[3].lower().strip()
            if cost:
                try:
                    cost = float(cost)
                except ValueError:
                    error = _("Invalid cost <ins>%(cost)s</ins> on line %(line)d. "
                              "Expected valid float or int" % {'cost': cost, 'line': i + 1})
                    break
            else:
                cost = product.cost
            months_count = row[4].lower().strip()
            try:
                months_count = int(months_count)
                if months_count not in [1, 3, 6, 12]:
                    raise ValueError()
                billing_cycle = get_months_count_billing_cycle(months_count)
            except ValueError:
                error = _("Invalid billing cycle <ins>%(billing_cycle)s</ins> on line %(line)d. "
                          "Expected one of: 1, 3, 6 or 12" % {'billing_cycle': months_count, 'line': i + 1})
                break
            since = row[5].strip()
            if since:
                try:
                    st = strptime(since.replace(' ', '').replace('/', '-'), '%Y-%m-%d')
                    since = datetime(st.tm_year, st.tm_mon, st.tm_mday)
                except:
                    try:
                        st = strptime(since.replace(' ', '').replace('/', '-'), '%d-%m-%Y')
                        since = datetime(st.tm_year, st.tm_mon, st.tm_mday)
                    except:
                        error = _("Incorrect subscription date <ins>%(since)s</ins> on line %(line)d. "
                                  "Must be in the format Year-Month-Day" % {'since': since, 'line': i + 1})
                        break
            else:
                since = now
            exp = row[6].strip()
            try:
                st = strptime(exp.replace(' ', '').replace('/', '-'), '%Y-%m-%d')
                expiry = date(st.tm_year, st.tm_mon, st.tm_mday)
            except:
                try:
                    st = strptime(exp.replace(' ', '').replace('/', '-'), '%d-%m-%Y')
                    expiry = date(st.tm_year, st.tm_mon, st.tm_mday)
                except:
                    error = _("Incorrect expiry <ins>%(expiry)s</ins> on line %(line)d. "
                              "Must be in the format Year-Month-Day" % {'expiry': exp, 'line': i + 1})
                    break
            tolerance = row[7].lower().strip()
            try:
                tolerance = int(tolerance)
            except ValueError:
                error = _("Invalid tolerance <ins>%(tolerance)s</ins> on line %(line)d. "
                          "Expected integer value" % {'tolerance': tolerance, 'line': i + 1})
                break
            status = row[8].strip()
            if status.lower() not in ['pending', 'active', 'suspended', 'canceled']:
                error = _("Invalid status <ins>%(status)s</ins> on line %(line)d. Must be one of: "
                          "<b>Pending</b>, <b>Active</b>, <b>Suspended</b> or <b>Canceled</b>." % {'status': status, 'line': i + 1})
                break
            if not dry_run:
                try:
                    try:
                        member = Member.objects.filter(email=email)[0]
                    except IndexError:
                        member = Member.objects.create_user(email, DEFAULT_GHOST_PWD, email=email, is_ghost=True)
                    Subscription.objects.create(member=member, product=product, reference_id=reference_id,
                                                monthly_cost=cost, billing_cycle=billing_cycle,
                                                invoice_tolerance=tolerance, since=since, expiry=expiry,
                                                status=status.capitalize())
                except:
                    continue
    return error


class SubscriptionUploadBackend(DefaultUploadBackend):

    def upload_complete(self, request, filename, *args, **kwargs):
        path = self.UPLOAD_DIR + "/" + filename
        self._dest.close()
        try:
            error = import_subscriptions(path)
        except Exception as e:
            error = e.message
        return {
            'path': getattr(settings, 'MEDIA_URL') + path,
            'error_message': error
        }


upload_subscription_file = AjaxFileUploader(SubscriptionUploadBackend)
