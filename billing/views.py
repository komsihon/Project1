# -*- coding: utf-8 -*-
import json
import logging
import random
import string
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.core.urlresolvers import reverse
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.http import HttpResponseForbidden
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_by_path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView

from ikwen.billing.mtnmomo.open_api import MTN_MOMO, init_momo_payment
from ikwen.billing.orangemoney.wso2_api import init_om_payment

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.billing.cloud_setup import DeploymentForm, deploy
from ikwen.billing.models import PaymentMean, CloudBillingPlan, IkwenInvoiceItem, InvoiceEntry, MoMoTransaction
from ikwen.billing.orangemoney.views import init_web_payment, ORANGE_MONEY
from ikwen.billing.yup.views import YUP, init_yup_web_payment
from ikwen.billing.uba.views import UBA, init_uba_web_payment
from ikwen.billing.utils import get_subscription_model, get_product_model
from ikwen.core.models import Service, Application
from ikwen.core.utils import get_service_instance
from ikwen.core.views import HybridListView
from ikwen.partnership.models import ApplicationRetailConfig

logger = logging.getLogger('ikwen')

Product = get_product_model()
Subscription = get_subscription_model()


class PaymentMeanList(HybridListView):
    model = PaymentMean
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
    search_field = 'processor_tx_id'

    def get_filter_criteria(self):
        criteria = {}
        if getattr(settings, 'IS_UMBRELLA', False):
            criteria['service_id'] = self.request.GET.get('service_id')
        else:
            criteria['service_id'] = getattr(settings, 'IKWEN_SERVICE_ID')
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
            b = now - timedelta(days=7)
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
            # Using rather 'starting_on' and 'ending_on' to avoid collisions with the
            # default expected GET parameters used in core.HybridListView.get_context_data()
            start_date = self.request.GET.get('starting_on') + " 00:00:00"
            end_date = self.request.GET.get('ending_on') + " 23:59:59"
        criteria['start_date'] = start_date
        criteria['end_date'] = end_date
        return criteria

    def get_queryset(self):
        criteria = self.get_filter_criteria()
        queryset = MoMoTransaction.objects.using('wallets').filter(type=MoMoTransaction.CASH_OUT)
        return self.grab_transactions(queryset, **criteria)

    def grab_transactions(self, queryset, **criteria):
        start_date = criteria.pop('start_date')
        end_date = criteria.pop('end_date')
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
        if criteria.get('status') is None and criteria.get('is_running') is None:
            count_successful = queryset.filter(status=MoMoTransaction.SUCCESS).count()
            aggr = queryset.filter(status=MoMoTransaction.SUCCESS).aggregate(Sum('amount'))
            aggr_fees = queryset.filter(status=MoMoTransaction.SUCCESS).aggregate(Sum('fees'))
            aggr_dara_fees = queryset.filter(status=MoMoTransaction.SUCCESS).aggregate(Sum('dara_fees'))
            if aggr['amount__sum']:
                amount_successful = aggr['amount__sum'] - aggr_fees['fees__sum'] - aggr_dara_fees['dara_fees__sum']
            count_running = queryset.filter(is_running=True).count()
            aggr = queryset.filter(is_running=True).aggregate(Sum('amount'))
            if aggr['amount__sum']:
                amount_running = aggr['amount__sum']
            count_failed = queryset.exclude(Q(status=MoMoTransaction.SUCCESS) |
                                             Q(status=MoMoTransaction.DROPPED) |
                                             Q(is_running=True)).count()
            aggr = queryset.exclude(Q(status=MoMoTransaction.SUCCESS) |
                                    Q(status=MoMoTransaction.DROPPED) |
                                    Q(is_running=True)).aggregate(Sum('amount'))
            if aggr['amount__sum']:
                amount_failed = aggr['amount__sum']
            count_dropped = queryset.filter(status=MoMoTransaction.DROPPED).count()
            aggr = queryset.filter(status=MoMoTransaction.DROPPED).aggregate(Sum('amount'))
            if aggr['amount__sum']:
                amount_dropped = aggr['amount__sum']
        aggr = queryset.aggregate(Sum('amount'))
        if aggr['amount__sum']:
            amount_total += aggr['amount__sum']
        count_total = queryset.count()
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
            if diff.total_seconds() > 660:
                tx.is_running = False
                tx.status = MoMoTransaction.DROPPED
                tx.save()

    def get_context_data(self, **kwargs):
        context = super(TransactionLog, self).get_context_data(**kwargs)
        queryset = context['queryset']
        criteria = self.get_filter_criteria()
        context['status'] = self.request.GET.get('status')
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

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        mean = request.GET.get('mean')
        if action == 'init':
            if mean == MTN_MOMO:
                return init_momo_payment(request)
            elif mean == ORANGE_MONEY:
                return init_om_payment(request)
        elif action == 'check_tx_status':
            return self.check_tx_status(request)
        return super(MoMoSetCheckout, self).get(request, *args, **kwargs)

    def check_tx_status(self, request, *args, **kwargs):
        tx_id = request.GET['tx_id']
        tx = MoMoTransaction.objects.using('wallets').get(pk=tx_id)

        # When a MoMoTransaction is created, its status is None or empty string
        # So perform a check first to make sure a status has been set
        if tx.status:
            if tx.status == MoMoTransaction.SUCCESS:
                resp_dict = {'success': True, 'return_url': request.session['return_url']}
                return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
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
        if payment_mean.slug == YUP:
            return init_yup_web_payment(request, *args, **kwargs)
        if payment_mean.slug == UBA:
            return init_uba_web_payment(request, *args, **kwargs)
        context['amount'] = request.session['amount']
        return render(request, self.template_name, context)
