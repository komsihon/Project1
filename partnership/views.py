from datetime import datetime

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponseForbidden
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.utils.http import urlquote
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.generic import TemplateView
from ikwen.theming.models import Theme

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.billing.models import CloudBillingPlan, IkwenInvoiceItem, InvoiceEntry
from ikwen.core.models import Application, Service
from ikwen.core.utils import get_service_instance, set_counters, calculate_watch_info, rank_watch_objects
from ikwen.core.views import HybridListView, DashboardBase
from ikwen.partnership.cloud_setup import deploy, DeploymentForm
from ikwen.partnership.forms import ChangeServiceForm


class ApplicationList(HybridListView):
    template_name = 'partnership/application_list.html'
    model = CloudBillingPlan
    context_object_name = 'plan_list'

    def get_queryset(self):
        apps = list(Application.objects.using('umbrella').exclude(deployment_url_name=''))
        service = get_service_instance()
        if getattr(settings, 'IS_IKWEN', False):
            return CloudBillingPlan.objects.using('umbrella').filter(app__in=apps, partner__isnull=True)
        return CloudBillingPlan.objects.using('umbrella').filter(app__in=apps, partner=service)


class ServiceList(HybridListView):
    template_name = 'partnership/service_list.html'
    model = Service
    context_object_name = 'service_list'
    ordering = ('project_name_slug', )
    ajax_ordering = ('project_name_slug', )

    def get_queryset(self):
        if getattr(settings, 'IS_IKWEN', False):
            return Service.objects.filter(retailer__isnull=True)
        return Service.objects.exclude(pk=get_service_instance().id)


class ChangeService(TemplateView):
    template_name = 'partnership/service_detail.html'

    def get_context_data(self, **kwargs):
        context = super(ChangeService, self).get_context_data(**kwargs)
        service_id = kwargs['service_id']
        website = Service.objects.get(pk=service_id)
        now = datetime.now()
        if website.expiry:
            if website.expiry < now.date():
                website.expired = True
        context['website'] = website
        context['billing_plan'] = Service.objects.using('umbrella').get(pk=service_id).billing_plan
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context

    def post(self, request, *args, **kwargs):
        form = ChangeServiceForm(request.POST)
        if form.is_valid():
            service_id = kwargs['service_id']
            website = Service.objects.using('umbrella').get(pk=service_id)
            billing_cycle = form.cleaned_data['billing_cycle'].strip()
            monthly_cost = form.cleaned_data['monthly_cost']
            website.billing_cycle = billing_cycle
            website.monthly_cost = monthly_cost
            website.save(using='umbrella')
            website.save(using='default')
            next_url = request.META['HTTP_REFERER']
            request.session['notice_message'] = 'Service <strong>' + str(website) + '</strong> ' + _('successfully updated')
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['form'] = form
            return render(request, 'partnership/service_detail.html', context)


class Dashboard(DashboardBase):
    template_name = 'partnership/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super(Dashboard, self).get_context_data(**kwargs)
        service = get_service_instance()
        set_counters(service)
        earnings_today = context['earnings_report']['today']
        earnings_yesterday = context['earnings_report']['yesterday']
        earnings_last_week = context['earnings_report']['last_week']
        earnings_last_28_days = context['earnings_report']['last_28_days']

        transaction_count = calculate_watch_info(service.transaction_count_history)
        transaction_count_yesterday = calculate_watch_info(service.transaction_count_history, 1)
        transaction_count_last_week = calculate_watch_info(service.transaction_count_history, 7)
        transaction_count_last_28_days = calculate_watch_info(service.transaction_count_history, 28)

        # AEPT stands for Average Earning Per Transaction
        aept_today = earnings_today['total'] / transaction_count['total'] if transaction_count['total'] else 0
        aept_yesterday = earnings_yesterday['total'] / transaction_count_yesterday['total']\
            if transaction_count_yesterday and transaction_count_yesterday['total'] else 0
        aept_last_week = earnings_last_week['total'] / transaction_count_last_week['total']\
            if transaction_count_last_week and transaction_count_last_week['total'] else 0
        aept_last_28_days = earnings_last_28_days['total'] / transaction_count_last_28_days['total']\
            if transaction_count_last_28_days and transaction_count_last_28_days['total'] else 0

        transactions_report = {
            'today': {
                'count': transaction_count['total'] if transaction_count else 0,
                'aept': '%.2f' % aept_today,  # AEPT: Avg Earning Per Transaction
            },
            'yesterday': {
                'count': transaction_count_yesterday['total'] if transaction_count_yesterday else 0,
                'aept': '%.2f' % aept_yesterday,
            },
            'last_week': {
                'count': transaction_count_last_week['total'] if transaction_count_last_week else 0,
                'aept': '%.2f' % aept_last_week,
            },
            'last_28_days': {
                'count': transaction_count_last_28_days['total']if transaction_count_last_28_days else 0,
                'aept': '%.2f' % aept_last_28_days,
            }
        }
        customers = list(Service.objects.all())
        for customer in customers:
            set_counters(customer)
        customers_report = {
            'today': rank_watch_objects(customers, 'earnings_history'),
            'yesterday': rank_watch_objects(customers, 'earnings_history', 1),
            'last_week': rank_watch_objects(customers, 'earnings_history', 7),
            'last_28_days': rank_watch_objects(customers, 'earnings_history', 28)
        }
        apps = list(Application.objects.all())
        for app in apps:
            set_counters(app)
        apps_report = {
            'today': rank_watch_objects(apps, 'earnings_history'),
            'yesterday': rank_watch_objects(apps, 'earnings_history', 1),
            'last_week': rank_watch_objects(apps, 'earnings_history', 7),
            'last_28_days': rank_watch_objects(apps, 'earnings_history', 28)
        }

        context['transactions_report'] = transactions_report
        context['customers_report'] = customers_report
        context['apps_report'] = apps_report
        return context


class DeployCloud(TemplateView):
    template_name = 'core/cloud_setup/deploy.html'

    def get_context_data(self, **kwargs):
        context = super(DeployCloud, self).get_context_data(**kwargs)
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        app = Application.objects.using(UMBRELLA).get(slug='ikwen-retail')
        context['app'] = app
        billing_plan_list = CloudBillingPlan.objects.using(UMBRELLA).filter(app=app)
        if billing_plan_list.count() == 0:
            setup_months_count = 12
            context['ikwen_setup_cost'] = app.base_monthly_cost * setup_months_count
            context['ikwen_monthly_cost'] = app.base_monthly_cost
            context['setup_months_count'] = setup_months_count
        if billing_plan_list.count() > 0:
            context['billing_plan_list'] = billing_plan_list
            context['setup_months_count'] = billing_plan_list[0].setup_months_count
        return context

    def get(self, request, *args, **kwargs):
        member = request.user
        uri = request.META['REQUEST_URI']
        next_url = reverse('ikwen:sign_in') + '?next=' + urlquote(uri)
        if member.is_anonymous():
            return HttpResponseRedirect(next_url)
        if not getattr(settings, 'IS_IKWEN', False):
            if not member.has_perm('accesscontrol.sudo'):
                return HttpResponseForbidden("You are not allowed here. Please login as an administrator.")
        return super(DeployCloud, self).get(request, *args, **kwargs)

    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def post(self, request, *args, **kwargs):
        form = DeploymentForm(request.POST)
        if form.is_valid():
            app_id = form.cleaned_data.get('app_id')
            project_name = form.cleaned_data.get('project_name')
            billing_cycle = form.cleaned_data.get('billing_cycle')
            billing_plan_id = form.cleaned_data.get('billing_plan_id')
            app = Application.objects.using(UMBRELLA).get(pk=app_id)
            billing_plan = CloudBillingPlan.objects.using(UMBRELLA).get(pk=billing_plan_id)

            customer_id = form.cleaned_data.get('customer_id')
            customer = Member.objects.using(UMBRELLA).get(pk=customer_id)
            setup_cost = form.cleaned_data.get('setup_cost')
            monthly_cost = form.cleaned_data.get('monthly_cost')
            if setup_cost < billing_plan.setup_cost:
                return HttpResponseForbidden("Attempt to set a Setup cost lower than allowed.")
            if monthly_cost < billing_plan.monthly_cost:
                return HttpResponseForbidden("Attempt to set a monthly cost lower than allowed.")

            invoice_entries = []
            website_setup = IkwenInvoiceItem(label='Platform setup', price=billing_plan.setup_cost, amount=setup_cost)
            short_description = "N/A"
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
            theme = Theme.objects.using(UMBRELLA).get(slug='dreamer')
            theme.display = Theme.COZY
            if getattr(settings, 'DEBUG', False):
                service = deploy(app, customer, project_name, billing_plan,
                                 monthly_cost, theme, billing_cycle, invoice_entries)
            else:
                try:
                    service = deploy(app, customer, project_name, billing_plan,
                                     monthly_cost, theme, billing_cycle, invoice_entries)
                except Exception as e:
                    context = self.get_context_data(**kwargs)
                    context['error'] = e.message
                    return render(request, 'core/cloud_setup/deploy.html', context)
            next_url = reverse('partnership:change_service', args=(service.id, ))
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['form'] = form
            return render(request, 'core/cloud_setup/deploy.html', context)
