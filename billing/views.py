# -*- coding: utf-8 -*-
import json
import logging
import random
import string
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.core.urlresolvers import reverse
from django.db.models import Q, Sum
from django.db.models.loading import get_model
from django.http import HttpResponse
from django.http import HttpResponseForbidden
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView

from ikwen.core.constants import PENDING

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.billing.cloud_setup import DeploymentForm, deploy
from ikwen.billing.models import Invoice, SendingReport, SERVICE_SUSPENDED_EVENT, PaymentMean, \
    CloudBillingPlan, IkwenInvoiceItem, InvoiceEntry, Product, MoMoTransaction
from ikwen.billing.admin import ProductAdmin, SubscriptionAdmin
from ikwen.billing.mtnmomo.views import MTN_MOMO
from ikwen.billing.orangemoney.views import init_web_payment, ORANGE_MONEY
from ikwen.billing.utils import get_invoicing_config_instance, get_subscription_model
from ikwen.core.models import Service, Application
from ikwen.core.utils import add_database_to_settings, get_service_instance
from ikwen.core.views import HybridListView, ChangeObjectBase
from ikwen.partnership.models import ApplicationRetailConfig

logger = logging.getLogger('ikwen')

subscription_model_name = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')
app_label = subscription_model_name.split('.')[0]
model = subscription_model_name.split('.')[1]
Subscription = get_model(app_label, model)


class BillingBaseView(TemplateView):
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


class ProductList(HybridListView):
    model = Product
    ordering = ('order_of_appearance', 'cost', )
    context_object_name = 'product_list'
    template_name = 'billing/product_list.html'

    def get(self, request, *args, **kwargs):
        action = self.request.GET.get('action')
        if action == 'delete':
            selection = self.request.GET['selection'].split(',')
            deleted = []
            for pk in selection:
                try:
                    obj = Product.objects.get(pk=pk)
                    if Subscription.objects.filter(product=obj).count() > 0:
                        response = {'message': "Cannot delete because there are actual subscriptions. "
                                               "Deactivate instead"}
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
    if getattr(settings, 'DEBUG', False):
        model = Subscription
    else:
        queryset = Subscription.objects.exclude(status=PENDING)
    ordering = ('-id', )
    list_filter = ('status', )
    context_object_name = 'subscription_list'
    template_name = 'billing/subscription_list.html'
    html_results_template_name = 'billing/snippets/subscription_list_results.html'

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


class ChangeSubscription(ChangeObjectBase):
    model = Subscription
    model_admin = SubscriptionAdmin
    template_name = 'billing/change_subscription.html'


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
        subscription = invoice.subscription
        if not subscription.member:
            subscription.member = self.request.user
            subscription.save()
        context['invoice'] = invoice
        context['payment_mean_list'] = list(PaymentMean.objects.filter(is_active=True).order_by('-is_main'))
        if getattr(settings, 'IS_IKWEN', False):
            try:
                invoice_service = invoice.service
                context['customer_config'] = invoice_service.config
                context['vendor'] = invoice_service.retailer.config if invoice_service.retailer \
                    else get_service_instance().config
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


class PaymentMeanList(TemplateView):
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
        context['payment_mean_list_all'] = payment_mean_list
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
        credentials = json.loads(credentials.strip())
        cleaned = {}
        for key, val in credentials.items():
            cleaned[key] = val.strip()
    except:
        return HttpResponse(
            json.dumps({'error': "Invalid credentials. Could not be parsed successfully"}),
            'content-type: text/json'
        )
    payment_mean.credentials = json.dumps(cleaned)
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


class TransactionLog(HybridListView):
    context_object_name = 'transaction_list'
    template_name = 'billing/transaction_log.html'
    html_results_template_name = 'billing/snippets/transaction_log_results.html'
    page_size = 200

    def get_filter_criteria(self):
        criteria = {}
        operator = self.request.GET.get('operator')
        if operator:
            criteria['wallet'] = operator
        status = self.request.GET.get('status')
        if status:
            criteria['status'] = status
        is_running = self.request.GET.get('is_running')
        if is_running:
            criteria['is_running'] = True
        period = self.request.GET.get('period', 'today')
        now = datetime.now()
        if period == 'today':
            start_date = datetime(now.year, now.month, now.day, 0, 0, 0)
            end_date = datetime(now.year, now.month, now.day, 23, 59, 59)
        elif period == 'yesterday':
            yst = now - timedelta(days=1)
            start_date = datetime(yst.year, yst.month, yst.day, 0, 0, 0)
            end_date = datetime(yst.year, yst.month, yst.day, 23, 59, 59)
        elif period == 'last_7_days':
            b = now - timedelta(days=1)
            start_date = datetime(b.year, b.month, b.day, 0, 0, 0)
            end_date = now
        elif period == 'last_28_days':
            b = now - timedelta(days=28)
            start_date = datetime(b.year, b.month, b.day, 0, 0, 0)
            end_date = now
        elif period == 'since_the_1st':
            start_date = datetime(now.year, now.month, 1, 0, 0, 0)
            end_date = now
        else:
            start_date = None
            end_date = None
        criteria['start_date'] = start_date
        criteria['end_date'] = end_date
        return criteria

    def get_queryset(self):
        criteria = self.get_filter_criteria()
        queryset = MoMoTransaction.objects.using('wallets').filter(service_id=getattr(settings, 'IKWEN_SERVICE_ID'))
        # queryset = MoMoTransaction.objects.using('wallets').all()
        return self.grab_transactions(queryset, **criteria)

    def grab_transactions(self, queryset, **criteria):
        start_date = criteria.pop('start_date')
        end_date = criteria.pop('end_date')
        if start_date and end_date:
            queryset = queryset.filter(created_on__range=(start_date, end_date))
        self.mark_dropped(queryset)
        if criteria.get('status') == MoMoTransaction.FAILURE:
            criteria.pop('status')
            queryset = queryset.exclude(Q(status=MoMoTransaction.SUCCESS) |
                                        Q(status=MoMoTransaction.DROPPED) |
                                        Q(is_running=True))
        return queryset.filter(**criteria)

    def sum_transactions(self, queryset, **criteria):
        count_successful, count_running, count_failed, count_dropped = 0, 0, 0, 0
        amount_successful, amount_running, amount_failed, amount_dropped, amount_total = 0, 0, 0, 0, 0
        start_date = criteria.pop('start_date')
        end_date = criteria.pop('end_date')
        if start_date and end_date:
            queryset = queryset.filter(created_on__range=(start_date, end_date))
        if criteria.get('status') is None and criteria.get('is_running') is None:
            count_successful = queryset.filter(status=MoMoTransaction.SUCCESS, **criteria).count()
            aggr = queryset.filter(status=MoMoTransaction.SUCCESS, **criteria).aggregate(Sum('amount'))
            if aggr['amount__sum']:
                amount_successful = aggr['amount__sum']
            count_running = queryset.filter(is_running=True, **criteria).count()
            aggr = queryset.filter(is_running=True, **criteria).aggregate(Sum('amount'))
            if aggr['amount__sum']:
                amount_running = aggr['amount__sum']
            count_failed = queryset.exclude(Q(status=MoMoTransaction.SUCCESS) |
                                             Q(status=MoMoTransaction.DROPPED) |
                                             Q(is_running=True)).filter(**criteria).count()
            aggr = queryset.exclude(Q(status=MoMoTransaction.SUCCESS) |
                                    Q(status=MoMoTransaction.DROPPED) |
                                    Q(is_running=True)).filter(**criteria).aggregate(Sum('amount'))
            if aggr['amount__sum']:
                amount_failed = aggr['amount__sum']
            count_dropped = queryset.filter(status=MoMoTransaction.DROPPED, **criteria).count()
            aggr = queryset.filter(status=MoMoTransaction.DROPPED, **criteria).aggregate(Sum('amount'))
            if aggr['amount__sum']:
                amount_dropped = aggr['amount__sum']
        elif criteria.get('status') == MoMoTransaction.FAILURE:
            criteria.pop('status')
            queryset = queryset.exclude(Q(status=MoMoTransaction.SUCCESS) |
                                        Q(status=MoMoTransaction.DROPPED) |
                                        Q(is_running=True))
        aggr = queryset.filter(**criteria).aggregate(Sum('amount'))
        if aggr['amount__sum']:
            amount_total += aggr['amount__sum']
        count_total = queryset.filter(**criteria).count()
        meta = {
            'total': {'count': count_total, 'amount': amount_total},
            'successful': {'count': count_successful, 'amount': amount_successful},
            'running': {'count': count_running, 'amount': amount_running},
            'failed': {'count': count_failed, 'amount': amount_failed},
            'dropped': {'count': count_dropped, 'amount': amount_dropped},
        }
        return meta

    def mark_dropped(self, queryset):
        for tx in queryset.filter(is_running=True):
            diff = datetime.now() - tx.created_on
            if diff.seconds > 660:
                tx.is_running = False
                tx.status = MoMoTransaction.DROPPED
                tx.save()

    def get_context_data(self, **kwargs):
        context = super(TransactionLog, self).get_context_data(**kwargs)
        criteria = self.get_filter_criteria()
        queryset = self.get_queryset()
        context['meta'] = self.sum_transactions(queryset, **criteria)
        return context


class DeployCloud(TemplateView):
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


class MoMoSetCheckout(TemplateView):
    template_name = 'billing/momo_checkout.html'

    def get_context_data(self, **kwargs):
        context = super(MoMoSetCheckout, self).get_context_data(**kwargs)
        mean = self.request.GET.get('mean')
        if mean:
            payment_mean = get_object_or_404(PaymentMean, slug=mean)
        else:
            payment_mean = get_object_or_404(PaymentMean, slug=MTN_MOMO)

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
        if getattr(settings, 'UNIT_TESTING', False):
            signature = 'dumb_signature'
        else:
            signature = ''.join([random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(16)])
        request.session['signature'] = signature
        payments_conf = getattr(settings, 'PAYMENTS', None)
        if payments_conf:
            conf = request.POST.get('payment_conf', 'default').lower().strip()
            request.session['payment_conf'] = conf
            path = payments_conf[conf]['before']
        else:
            path = getattr(settings, 'MOMO_BEFORE_CASH_OUT')
        momo_before_checkout = import_by_path(path)
        http_resp = momo_before_checkout(request, payment_mean, *args, **kwargs)
        if http_resp:
            return http_resp
        if payment_mean.slug == ORANGE_MONEY:
            return init_web_payment(request, *args, **kwargs)
        context['amount'] = request.session['amount']
        return render(request, self.template_name, context)
