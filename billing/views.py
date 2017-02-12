# -*- coding: utf-8 -*-
import json
from datetime import date, datetime, timedelta
from threading import Thread

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.db.models.loading import get_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template import Context
from django.template.loader import get_template
from django.template.response import TemplateResponse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from ikwen.core.models import Service

from ikwen.core.utils import add_database_to_settings, get_service_instance, add_event, get_mail_content

from ikwen.accesscontrol.models import Member

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.views import BaseView
from ikwen.billing.models import Invoice, SendingReport, SERVICE_SUSPENDED_EVENT, PaymentMean, Payment, \
    PAYMENT_CONFIRMATION
from ikwen.billing.utils import get_invoicing_config_instance, get_subscription_model, get_days_count, \
    get_payment_confirmation_message, share_payment_and_set_stats

subscription_model_name = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')
app_label = subscription_model_name.split('.')[0]
model = subscription_model_name.split('.')[1]
Subscription = get_model(app_label, model)


class BillingBaseView(BaseView):
    def get_context_data(self, **kwargs):
        context = super(BillingBaseView, self).get_context_data(**kwargs)
        context['invoicing_config'] = get_invoicing_config_instance()
        return context


class IframeAdmin(BillingBaseView):
    template_name = 'core/iframe_admin.html'

    def get_context_data(self, **kwargs):
        context = super(IframeAdmin, self).get_context_data(**kwargs)
        model_name = kwargs['model_name']
        app_name = kwargs.get('app_name', 'billing')
        iframe_url = reverse('admin:%s_%s_changelist' % (app_name, model_name))
        context['model_name'] = model_name
        context['iframe_url'] = iframe_url
        return context


class InvoiceList(BillingBaseView):

    def get_context_data(self, **kwargs):
        context = super(InvoiceList, self).get_context_data(**kwargs)
        subscription_id = kwargs['subscription_id']
        subscription_model = get_subscription_model()
        subscriptions = list(subscription_model.objects.filter(pk=subscription_id))
        context['unpaid_invoices_count'] = Invoice.objects.filter(
            Q(status=Invoice.PENDING) | Q(status=Invoice.OVERDUE),
            subscription__in=subscriptions
        ).count()
        invoices = Invoice.objects.filter(subscription__in=subscriptions).order_by('-id')
        for invoice in invoices:
            if invoice.status == Invoice.PAID:
                payments = list(invoice.payment_set.all().order_by('-id'))
                invoice.paid_on = payments[-1].created_on.strftime('%B %d, %Y %H:%M')
                invoice.method = payments[-1].method
        context['invoices'] = invoices
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        app_label = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'ikwen.billing.Subscription').split('.')[0]
        return TemplateResponse(request, [
            'billing/%s/invoice_list.html' % app_label,
            'billing/invoice_list.html'
        ], context)


class InvoiceDetail(BillingBaseView):
    template_name = 'billing/invoice_detail.html'

    def get_context_data(self, **kwargs):
        context = super(InvoiceDetail, self).get_context_data(**kwargs)
        invoice_id = self.kwargs['invoice_id']
        invoice = get_object_or_404(Invoice, pk=invoice_id)
        context['invoice'] = invoice
        context['payment_mean_list'] = list(PaymentMean.objects.filter(is_active=True).order_by('-is_main'))
        if getattr(settings, 'IS_IKWEN', False):
            try:
                context['customer_config'] = invoice.service.config
            except:
                pass

        # User may want to extend the payment above the default duration
        # Below are a list of possible extension dates on a year
        # TODO: Manage extensions for case where Product is bound to a duration (billing cycle)
        if getattr(settings, 'SEPARATE_BILLING_CYCLE', True):
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


def render_subscription_event(event):
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


def render_billing_event(event):
    service = event.service
    database = service.database
    add_database_to_settings(database)
    currency_symbol = service.config.currency_symbol
    try:
        invoice = Invoice.objects.using(database).get(pk=event.object_id)
        c = Context({'title': _(event.event_type.title),
                     'danger': event.event_type.codename == SERVICE_SUSPENDED_EVENT,
                     'currency_symbol': currency_symbol,
                     'amount': invoice.amount,
                     'obj': invoice,
                     'details_url': service.url + reverse('billing:invoice_list', args=(invoice.id,)),
                     'pay_now_url': service.url + reverse('billing:invoice_detail', args=(invoice.id,)),
                     'show_pay_now': invoice.status != Invoice.PAID})
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


class PaymentMeanList(BaseView):
    template_name = 'billing/payment_mean_list.html'

    def get_context_data(self, **kwargs):
        context = super(PaymentMeanList, self).get_context_data(**kwargs)
        payment_mean_list = []
        for mean in PaymentMean.objects.all().order_by('-is_main'):
            # Ordering by -is_main causes the main to appear first
            if mean.credentials:
                try:
                    mean.credentials = json.loads(mean.credentials.strip())
                except:
                    mean.is_active = False
                    mean.save()
            payment_mean_list.append(mean)
        context['payment_mean_list'] = payment_mean_list
        return context


@permission_required('accesscontrol.sudo')
def set_credentials(request, *args, **kwargs):
    """
    Set credentials of a payment mean on an IAO Website
    """
    mean_id = request.GET['mean_id']
    credentials = request.GET['credentials']
    payment_mean = PaymentMean.objects.get(pk=mean_id)
    try:
        json.loads(credentials.strip())
    except:
        return HttpResponse(
            json.dumps({'error': "Invalid credentials. Could not be parsed successfully"}),
            'content-type: text/json'
        )
    payment_mean.credentials = credentials
    payment_mean.save()
    return HttpResponse(json.dumps({'success': True}), 'content-type: text/json')


@permission_required('accesscontrol.sudo')
def toggle_payment_mean(request, *args, **kwargs):
    """
    Turn Active/Inactive a payment mean on an IAO Website
    """
    mean_id = request.GET['mean_id']
    payment_mean = PaymentMean.objects.get(pk=mean_id)
    if payment_mean.is_active:
        if payment_mean.is_main:
            return HttpResponse(json.dumps({'error': "Cannot cancel main payment mean"}), 'content-type: text/json')
        payment_mean.is_active = False
    else:
        payment_mean.is_active = True
    payment_mean.save()
    return HttpResponse(json.dumps({'success': True}), 'content-type: text/json')


def set_invoice_checkout(request, *args, **kwargs):
    """
    This function has no URL associated with it.
     It serves as ikwen setting "MOMO_BEFORE_CHECKOUT"
    """
    invoice_id = request.POST['invoice_id']
    try:
        extra_months = int(request.POST.get('extra_months', ''))
    except ValueError:
        extra_months = 0
    invoice = Invoice.objects.get(pk=invoice_id)
    request.session['amount'] = invoice.amount + invoice.service.monthly_cost * extra_months
    request.session['model_name'] = 'billing.Invoice'
    request.session['object_id'] = invoice_id
    request.session['extra_months'] = extra_months


def confirm_invoice_payment(request):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_AFTER_CHECKOUT"
    """
    invoice_id = request.session['object_id']
    invoice = Invoice.objects.get(pk=invoice_id)
    invoice.status = Invoice.PAID
    invoice.save()
    service = get_service_instance()
    config = service.config
    amount = request.session['amount']
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY, amount=amount)
    s = invoice.service
    extra_months = request.session['extra_months']
    total_months = invoice.months_count + extra_months
    days = get_days_count(total_months)
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
    share_payment_and_set_stats(invoice, total_months)
    member = request.user
    add_event(service, member, PAYMENT_CONFIRMATION, invoice.id)
    if member.email:
        subject, message, sms_text = get_payment_confirmation_message(payment, member)
        html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
        sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
        msg = EmailMessage(subject, html_content, sender, [member.email])
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()
    next_url = service.url + reverse('billing:invoice_detail', args=(invoice.id, ))
    return {'success': True, 'next_url': next_url}


class NoticeMail(BillingBaseView):
    """
    Preview of invoing system notice mails
    """
    template_name = 'billing/mails/notice.html'

    def get_context_data(self, **kwargs):
        context = super(NoticeMail, self).get_context_data(**kwargs)
        context['invoice_url'] = 'some_url'
        return context
