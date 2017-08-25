# -*- coding: utf-8 -*-
import json
import random
import string
from datetime import date, datetime, timedelta
from threading import Thread

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db import transaction
from django.db.models import Q
from django.db.models.loading import get_model
from django.http import HttpResponse
from django.http import HttpResponseForbidden
from django.http import HttpResponseRedirect
from django.template import Context
from django.template.loader import get_template
from django.template.response import TemplateResponse
from django.utils.http import urlquote
from django.utils.module_loading import import_by_path
from django.utils.text import slugify
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from ikwen.billing.orangemoney.views import init_web_payment, ORANGE_MONEY

from ikwen.conf.settings import MOMO_SLUG

from ikwen.billing.jumbopay.views import init_momo_cashout

from ikwen.billing.mtnmomo.views import init_request_payment
from ikwen.billing.cloud_setup import DeploymentForm, deploy

from ikwen.partnership.models import ApplicationRetailConfig

from ikwen.core.models import Service, Application

from ikwen.core.utils import add_database_to_settings, get_service_instance, add_event, get_mail_content

from ikwen.accesscontrol.models import Member, SUDO

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.views import BaseView
from ikwen.billing.models import Invoice, SendingReport, SERVICE_SUSPENDED_EVENT, PaymentMean, Payment, \
    PAYMENT_CONFIRMATION, CloudBillingPlan, IkwenInvoiceItem, InvoiceEntry, MoMoTransaction
from ikwen.billing.utils import get_invoicing_config_instance, get_subscription_model, get_days_count, \
    get_payment_confirmation_message, share_payment_and_set_stats

import logging
logger = logging.getLogger('ikwen')

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
        subscription_model = get_subscription_model()
        subscriptions = list(subscription_model.objects.filter(member=self.request.user))
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
                invoice_service = invoice.service
                context['customer_config'] = invoice_service.config
                context['vendor'] = invoice_service.retailer.config if invoice_service.retailer else context['config']
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
    config = get_service_instance().config
    if not config.is_pro_version:
        return HttpResponse(
            json.dumps({'error': "Operation not allowed"}),
            'content-type: text/json'
        )
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
    if request.user.is_anonymous():
        next_url = reverse('ikwen:sign_in')
        referrer = request.META.get('HTTP_REFERER')
        if referrer:
            next_url += '?' + urlquote(referrer)
        return HttpResponseRedirect(next_url)
    service = get_service_instance()
    config = service.config
    invoice_id = request.POST['invoice_id']
    try:
        extra_months = int(request.POST.get('extra_months', ''))
    except ValueError:
        extra_months = 0
    invoice = Invoice.objects.get(pk=invoice_id)
    amount = invoice.amount + invoice.service.monthly_cost * extra_months
    if config.__dict__.get('processing_fees_on_customer'):
        amount += config.ikwen_share_fixed
    request.session['amount'] = amount
    request.session['model_name'] = 'billing.Invoice'
    request.session['object_id'] = invoice_id
    request.session['extra_months'] = extra_months


def confirm_invoice_payment(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_AFTER_CHECKOUT"
    """
    service = get_service_instance()
    config = service.config
    invoice_id = request.session['object_id']
    invoice = Invoice.objects.get(pk=invoice_id)
    invoice.status = Invoice.PAID
    if config.__dict__.get('processing_fees_on_customer'):
        invoice.processing_fees = config.ikwen_share_fixed
    invoice.save()
    amount = request.session['amount']
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY, amount=amount)
    s = invoice.service
    if config.__dict__.get('separate_billing_cycle', True):
        extra_months = request.session['extra_months']
        total_months = invoice.months_count + extra_months
        days = get_days_count(total_months)
    else:
        days = invoice.subscription.product.duration
        total_months = None
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
    add_event(service, PAYMENT_CONFIRMATION, member=member, object_id=invoice.id)
    partner = s.retailer
    if partner:
        add_database_to_settings(partner.database)
        sudo_group = Group.objects.using(partner.database).get(name=SUDO)
    else:
        sudo_group = Group.objects.using(UMBRELLA).get(name=SUDO)
    add_event(service, PAYMENT_CONFIRMATION, group_id=sudo_group.id, object_id=invoice.id)
    if member.email:
        subject, message, sms_text = get_payment_confirmation_message(payment, member)
        html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
        sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
        msg = EmailMessage(subject, html_content, sender, [member.email])
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()
    next_url = service.url + reverse('billing:invoice_detail', args=(invoice.id, ))
    return {'success': True, 'next_url': next_url}


class DeployCloud(BaseView):
    template_name = 'core/cloud_setup/deploy.html'

    def get_context_data(self, **kwargs):
        context = super(DeployCloud, self).get_context_data(**kwargs)
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        app_slug = kwargs['app_slug']
        app = Application.objects.using(UMBRELLA).get(slug=app_slug)
        context['app'] = app
        if getattr(settings, 'IS_IKWEN', False):
            billing_plan_list = CloudBillingPlan.objects.using(UMBRELLA).filter(app=app, partner__isnull=True)
            if billing_plan_list.count() == 0:
                setup_months_count = 3
                context['ikwen_setup_cost'] = app.base_monthly_cost * setup_months_count
                context['ikwen_monthly_cost'] = app.base_monthly_cost
                context['setup_months_count'] = setup_months_count
        else:
            service = get_service_instance()
            billing_plan_list = CloudBillingPlan.objects.using(UMBRELLA).filter(app=app, partner=service)
            if billing_plan_list.count() == 0:
                retail_config = ApplicationRetailConfig.objects.using(UMBRELLA).get(app=app, partner=service)
                setup_months_count = 3
                context['ikwen_setup_cost'] = retail_config.ikwen_monthly_cost * setup_months_count
                context['ikwen_monthly_cost'] = retail_config.ikwen_monthly_cost
                context['setup_months_count'] = setup_months_count
        if billing_plan_list.count() > 0:
            context['billing_plan_list'] = billing_plan_list
            context['setup_months_count'] = billing_plan_list[0].setup_months_count
        return context

    def post(self, request, *args, **kwargs):
        form = DeploymentForm(request.POST)
        if form.is_valid():
            app_id = form.cleaned_data.get('app_id')
            member_id = form.cleaned_data.get('member_id')
            project_name = form.cleaned_data.get('project_name')
            billing_cycle = form.cleaned_data.get('billing_cycle')
            billing_plan_id = form.cleaned_data.get('billing_plan_id')
            setup_cost = form.cleaned_data.get('setup_cost')
            monthly_cost = form.cleaned_data.get('monthly_cost')
            domain = form.cleaned_data.get('domain')
            partner_id = form.cleaned_data.get('partner_id')
            app = Application.objects.using(UMBRELLA).get(pk=app_id)
            member = Member.objects.using(UMBRELLA).get(pk=member_id)
            billing_plan = CloudBillingPlan.objects.using(UMBRELLA).get(pk=billing_plan_id)
            if setup_cost < billing_plan.setup_cost:
                return HttpResponseForbidden("Attempt to set a Setup cost lower than allowed.")
            if monthly_cost < billing_plan.monthly_cost:
                return HttpResponseForbidden("Attempt to set a monthly cost lower than allowed.")
            partner = Service.objects.using(UMBRELLA).get(pk=partner_id) if partner_id else None
            invoice_entries = []
            domain_name = IkwenInvoiceItem(label='Domain name')
            domain_name_entry = InvoiceEntry(item=domain_name, short_description=domain)
            invoice_entries.append(domain_name_entry)
            website_setup = IkwenInvoiceItem(label='Website setup', price=billing_plan.setup_cost, amount=setup_cost)
            short_description = "%d products" % billing_plan.max_products
            website_setup_entry = InvoiceEntry(item=website_setup, short_description=short_description, total=setup_cost)
            invoice_entries.append(website_setup_entry)
            i = 0
            while True:
                try:
                    label = request.POST['item%d' % i]
                    amount = float(request.POST['amount%d' % i])
                    if not (label and amount):
                        break
                    item = IkwenInvoiceItem(label=label, amount=amount)
                    entry = InvoiceEntry(item=item, total=amount)
                    invoice_entries.append(entry)
                    i += 1
                except:
                    break
            if getattr(settings, 'DEBUG', False):
                service = deploy(app, member, project_name, billing_plan,
                                 setup_cost, monthly_cost, invoice_entries, billing_cycle, domain,
                                 partner_retailer=partner)
            else:
                try:
                    service = deploy(app, member, project_name, billing_plan,
                                     setup_cost, monthly_cost, invoice_entries, billing_cycle, domain,
                                     partner_retailer=partner)
                except Exception as e:
                    context = self.get_context_data(**kwargs)
                    context['error'] = e.message
                    return render(request, 'core/cloud_setup/deploy.html', context)
            if getattr(settings, 'IS_IKWEN', False):
                next_url = reverse('partnership:change_service', args=(service.id, ))
            else:
                next_url = reverse('change_service', args=(service.id, ))
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['form'] = form
            return render(request, 'core/cloud_setup/deploy.html', context)


class NoticeMail(BillingBaseView):
    """
    Preview of invoing system notice mails
    """
    template_name = 'billing/mails/notice.html'

    def get_context_data(self, **kwargs):
        context = super(NoticeMail, self).get_context_data(**kwargs)
        context['invoice_url'] = 'some_url'
        return context


class MoMoSetCheckout(BaseView):
    template_name = 'billing/momo_checkout.html'

    def get_context_data(self, **kwargs):
        context = super(MoMoSetCheckout, self).get_context_data(**kwargs)
        mean = self.request.GET.get('mean')
        if mean:
            try:
                payment_mean = PaymentMean.objects.get(slug=mean)
            except PaymentMean.DoesNotExist:
                payment_mean = get_object_or_404(PaymentMean, slug=MOMO_SLUG)
        else:
            payment_mean = get_object_or_404(PaymentMean, slug=MOMO_SLUG)

        if getattr(settings, 'DEBUG', False):
            json.loads(payment_mean.credentials)
        else:
            try:
                json.loads(payment_mean.credentials)
            except:
                return HttpResponse("Error, Could not parse Payment API parameters for %s." % payment_mean.name)

        context['payment_mean'] = payment_mean
        member = self.request.user
        if member.is_authenticated():
            context['phone'] = member.phone
        return context

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def post(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        payment_mean = context['payment_mean']
        signature = ''.join([random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(16)])
        request.session['signature'] = signature
        path = getattr(settings, 'MOMO_BEFORE_CASH_OUT')
        momo_before_checkout = import_by_path(path)
        http_resp = momo_before_checkout(request, *args, **kwargs)
        if http_resp:
            return http_resp
        if payment_mean.slug == ORANGE_MONEY:
            return init_web_payment(request, *args, **kwargs)
        context['amount'] = request.session['amount']
        return render(request, self.template_name, context)


def init_momo_transaction(request, *args, **kwargs):
    phone = request.GET['phone']
    request.session['phone'] = phone
    if phone.startswith('67') or phone.startswith('68') or (650 <= int(phone[:3]) < 655):
        # MTN is processed by MTN API itself
        return init_request_payment(request, *args, **kwargs)
    elif getattr(settings, 'IS_IKWEN', False):
        return HttpResponse(json.dumps({'error': 'Only MTN Mobile Money payments are accepted'}), 'content-type: text/json')
    else: # Orange is processed by JumboPay
        return init_momo_cashout(request, *args, **kwargs)


@transaction.atomic
def check_momo_transaction_status(request, *args, **kwargs):
    tx_id = request.GET['tx_id']
    tx = MoMoTransaction.objects.using('wallets').get(pk=tx_id)

    # When a MoMoTransaction is created, its status is None or empty string
    # So perform a double check. First, make sure a status has been set
    if tx.is_running and tx.status:
        tx.is_running = False
        tx.save(using='wallets')
        if tx.status == MoMoTransaction.SUCCESS:
            request.session['tx_id'] = tx_id
            path = getattr(settings, 'MOMO_AFTER_CASH_OUT')
            momo_after_checkout = import_by_path(path)
            if getattr(settings, 'DEBUG', False):
                resp_dict = momo_after_checkout(request, signature=request.session['signature'])
                return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
            else:
                try:
                    resp_dict = momo_after_checkout(request, signature=request.session['signature'])
                    return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
                except:
                    logger.error("MTN MoMo: Failure while querying transaction status", exc_info=True)
                    return HttpResponse(json.dumps({'error': 'Unknown server error in AFTER_CASH_OUT'}))
        resp_dict = {'error': tx.status, 'message': ''}
        if getattr(settings, 'DEBUG', False):
            resp_dict['message'] = tx.message
        elif tx.status == MoMoTransaction.FAILURE:
            resp_dict['message'] = 'Ooops! You may have refused authorization. Please try again.'
        elif tx.status == MoMoTransaction.API_ERROR:
            resp_dict['message'] = 'Your balance may be insufficient. Please check and try again.'
        elif tx.status == MoMoTransaction.TIMEOUT:
            resp_dict['message'] = 'MTN Server is taking too long to respond. Please try again later'
        elif tx.status == MoMoTransaction.REQUEST_EXCEPTION:
            resp_dict['message'] = 'Could not init transaction with MTN Server. Please try again later'
        elif tx.status == MoMoTransaction.SERVER_ERROR:
            resp_dict['message'] = 'Unknown server error. Please try again later'
        return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
    return HttpResponse(json.dumps({'running': True}), 'content-type: text/json')
