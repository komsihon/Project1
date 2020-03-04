# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta
from time import strptime

import requests
from ajaxuploader.views import AjaxFileUploader
from currencies.models import Currency
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_page
from django.views.generic.base import TemplateView

import ikwen.conf.settings
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member, ACCESS_REQUEST_EVENT, OwnershipTransfer
from ikwen.billing.models import Invoice, SupportCode
from ikwen.billing.utils import get_invoicing_config_instance, get_billing_cycle_days_count, \
    get_billing_cycle_months_count, refresh_currencies_exchange_rates
from ikwen.cashout.models import CashOutRequest
from ikwen.core.generic import HybridListView, ChangeObjectBase, CustomizationImageUploadBackend
from ikwen.core.models import Service, QueuedSMS, ConsoleEventType, ConsoleEvent, Country, \
    OperatorWallet, XEmailObject
from ikwen.core.utils import get_service_instance, DefaultUploadBackend, add_database_to_settings, \
    add_database, calculate_watch_info, set_counters
from ikwen.rewarding.models import CROperatorProfile

try:
    ikwen_service = Service.objects.using(UMBRELLA).get(pk=ikwen.conf.settings.IKWEN_SERVICE_ID)
    IKWEN_BASE_URL = ikwen_service.url
except Service.DoesNotExist:
    IKWEN_BASE_URL = getattr(settings, 'IKWEN_BASE_URL') if getattr(settings, 'DEBUG',
                                                                    False) else ikwen.conf.settings.PROJECT_URL

logger = logging.getLogger('ikwen')

HybridListView = HybridListView   # Proxy import to make ikwen.core.views.HybridListView valid
ChangeObjectBase = ChangeObjectBase   # Proxy import to make ikwen.core.views.ChangeObjectBase valid
upload_image = AjaxFileUploader(DefaultUploadBackend)
upload_customization_image = AjaxFileUploader(CustomizationImageUploadBackend)


class DefaultHome(TemplateView):
    """
    Can be used to set at default Home page for applications that do
    not have a public part. This merely shows the company name, logo
    and slogan. This view can be used to create the url with the
    name 'home' that MUST ABSOLUTELY EXIST in all Ikwen applications.
    """
    template_name = 'core/default_home.html'


class ServiceDetail(TemplateView):
    template_name = 'core/service_detail.html'

    def get_context_data(self, **kwargs):
        context = super(ServiceDetail, self).get_context_data(**kwargs)
        invoicing_config = get_invoicing_config_instance(UMBRELLA)
        service_id = kwargs.get('service_id')
        if not service_id:
            service_id = getattr(settings, 'IKWEN_SERVICE_ID')
        srvce = Service.objects.using(UMBRELLA).get(pk=service_id)
        invoice = Invoice.get_last(srvce)
        now = datetime.now()
        if invoice:
            srvce.last_payment = invoice.created_on
        if not srvce.version or srvce.version == Service.FREE:
            srvce.expiry = None
        else:
            srvce.next_invoice_on = srvce.expiry - timedelta(days=invoicing_config.gap)
            if srvce.expiry < now.date():
                srvce.expired = True
            if now.date() > srvce.next_invoice_on:
                days = get_billing_cycle_days_count(srvce.billing_cycle)
                srvce.next_invoice_on = srvce.next_invoice_on + timedelta(days=days)
            srvce.next_invoice_amount = srvce.monthly_cost * get_billing_cycle_months_count(srvce.billing_cycle)
            srvce.pending_invoice_count = Invoice.objects.filter(subscription=srvce, status=Invoice.PENDING).count()
        try:
            support_code = SupportCode.objects.using(UMBRELLA).filter(service=srvce).order_by('-id')[0]
        except IndexError:
            support_code = None
        if support_code and support_code.expiry < now:
            support_code.expired = True
        from echo.models import Balance
        echo_balance, update = Balance.objects.using('wallets').get_or_create(service_id=srvce.id)
        context['srvce'] = srvce  # Service named srvce in context to avoid collision with service from template_context_processors
        context['support_code'] = support_code
        context['echo_balance'] = echo_balance
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        if action == 'update_domain':
            new_domain = request.GET['new_domain']
            is_naked_domain = True if request.GET['type'] == Service.MAIN else False
            try:
                service = get_service_instance(using=UMBRELLA)
                service.update_domain(new_domain, is_naked_domain)
            except:
                logger.error("Failed to update domain to %s" % new_domain)
                response = {'error': _("Unknown error occured.")}
                return HttpResponse(json.dumps(response), 'content-type: text/json')
        elif action == 'transfer_ownership':
            email = request.GET['email']
            try:
                member = Member.objects.using(UMBRELLA).filter(email=email)[0]
                service = get_service_instance(using=UMBRELLA)
                transfer = OwnershipTransfer.objects.create(sender=request.user, target=member, service=service)
                # Send email here
            except IndexError:
                response = {'error': _("%s does not have an account on ikwen." % email)}
        return super(ServiceDetail, self).get(request, *args, **kwargs)


class Configuration(ChangeObjectBase):
    template_name = 'core/configuration.html'
    model = getattr(settings, 'IKWEN_CONFIG_MODEL', 'core.Config')
    model_admin = getattr(settings, 'IKWEN_CONFIG_MODEL_ADMIN', 'ikwen.core.admin.ConfigAdmin')
    context_object_name = 'config'
    object_list_url = 'ikwen:configuration'

    UPLOAD_CONTEXT = 'config'

    def get_object(self, **kwargs):
        if getattr(settings, 'IS_IKWEN', False):
            service_id = kwargs.get('service_id')
        else:
            service_id = getattr(settings, 'IKWEN_SERVICE_ID')
        return get_object_or_404(Service, pk=service_id).config

    def get_context_data(self, **kwargs):
        context = super(Configuration, self).get_context_data(**kwargs)
        context['target_service'] = context['config'].service
        context['is_company'] = True
        context['img_upload_context'] = self.UPLOAD_CONTEXT
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        context['currency_list'] = Currency.objects.all().order_by('code')
        return context

    def after_save(self, request, obj, *args, **kwargs):
        service = obj.service
        try:
            currency_code = request.POST['currency_code']
            if currency_code != Currency.active.base().code:
                refresh_currencies_exchange_rates()
            Currency.objects.all().update(is_base=False, is_default=False, is_active=False)
            Currency.objects.filter(code=currency_code).update(is_base=True, is_default=True, is_active=True)
            for crcy in Currency.objects.all():
                try:
                    request.POST[crcy.code]  # Tests wheter this currency was activated
                    crcy.is_active = True
                    crcy.save()
                except KeyError:
                    continue
        except:
            pass
        cache.delete(service.id + ':config:')
        cache.delete(service.id + ':config:default')
        cache.delete(service.id + ':config:' + UMBRELLA)
        obj.save(using=UMBRELLA)


def get_queued_sms(request, *args, **kwargs):
    email = request.GET['email']
    password = request.GET['password']
    qty = request.GET.get('quantity')
    if not qty:
        qty = 100
    user = Member.objects.using(UMBRELLA).get(email=email)
    if not user.check_password(password):
        response = {'error': 'E-mail or password not found.'}
    else:
        qs = QueuedSMS.objects.all()[:qty]
        response = [sms.to_dict() for sms in qs]
        qs.delete()
    return HttpResponse(json.dumps(response), 'content-type: text/json')


class Console(TemplateView):
    template_name = 'core/console.html'

    def get_context_data(self, **kwargs):
        context = super(Console, self).get_context_data(**kwargs)
        reset_notices_counter(self.request)
        member = self.request.user
        if self.request.user_agent.is_mobile:
            length = 10
        elif self.request.user_agent.is_tablet:
            length = 20
        else:
            length = 30
        join = self.request.GET.get('join')
        context['member'] = member
        context['profile_name'] = member.full_name
        context['profile_photo_url'] = member.photo.small_url if member.photo.name else ''
        context['profile_cover_url'] = member.cover_image.url if member.cover_image.name else ''

        member_services = member.get_services()
        active_operators = CROperatorProfile.objects.filter(service__in=member_services, is_active=True)
        active_cr_services = [op.service for op in active_operators]
        suggestion_list = []
        join_service = None
        if join:
            try:
                join_service = Service.objects.get(project_name_slug=join)
                CROperatorProfile.objects.get(service=join_service, is_active=True)
                suggestion_list.append(join_service)
            except CROperatorProfile.DoesNotExist:
                pass
        suggested_operators = CROperatorProfile.objects.select_related('service').exclude(service__in=member_services).filter(is_active=True)
        suggestion_list = [op.service for op in suggested_operators.order_by('-id')[:9]]
        if join_service and join_service not in suggestion_list and join_service not in member_services:
            suggestion_list.insert(0, join_service)
        coupon_summary_list = member.couponsummary_set.select_related('service').filter(service__in=active_cr_services)
        event_list = ConsoleEvent.objects.select_related('service')\
                         .filter(Q(member=member) | Q(group_id__in=member.group_fk_list) |
                                 Q(group_id__isnull=True, member__isnull=True, service__in=member_services)).order_by('-id')[:length]
        context['event_list'] = event_list
        context['suggestion_list'] = suggestion_list
        context['coupon_summary_list'] = coupon_summary_list
        context['is_console'] = True  # console.html extends profile.html, so this helps differentiates in templates
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('format') == 'json':
            start = int(self.request.GET['start'])
            if self.request.user_agent.is_mobile:
                length = 10
            elif self.request.user_agent.is_tablet:
                length = 20
            else:
                length = 30
            limit = start + length
            type_access_request = ConsoleEventType.objects.get(codename=ACCESS_REQUEST_EVENT)
            member = self.request.user
            queryset = ConsoleEvent.objects.select_related('service, member, event_type').exclude(event_type=type_access_request)\
                           .filter(Q(member=member) | Q(group_id__in=member.group_fk_list) |
                                   Q(group_id__isnull=True, member__isnull=True, service__in=member.get_services())).order_by('-id')[start:limit]
            response = []
            for event in queryset:
                try:
                    response.append(event.to_dict())
                except:
                    continue
            return HttpResponse(json.dumps(response), 'content-type: text/json', **response_kwargs)
        else:
            return super(Console, self).render_to_response(context, **response_kwargs)


@login_required
def reset_notices_counter(request, *args, **kwargs):
    member = request.user
    for s in member.get_services():
        add_database(s.database)
        Member.objects.using(s.database).filter(pk=member.id).update(personal_notices=0)
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


def list_projects(request, *args, **kwargs):
    q = request.GET['q'].lower()
    if len(q) < 2:
        return

    queryset = Service.objects.using(UMBRELLA).filter(is_public=True)
    word = slugify(q)[:4]
    if word:
        queryset = queryset.filter(project_name_slug__icontains=word)

    projects = []
    for s in queryset.order_by('project_name')[:6]:
        try:
            p = s.to_dict()
            p['url'] = IKWEN_BASE_URL + reverse('ikwen:company_profile', args=(s.project_name_slug,))
            projects.append(p)
        except:
            pass

    response = {'object_list': projects}
    callback = request.GET['callback']
    jsonp = callback + '(' + json.dumps(response) + ')'
    return HttpResponse(jsonp, content_type='application/json')


def load_event_content(request, *args, **kwargs):
    event_id = request.GET['event_id']
    callback = request.GET['callback']
    try:
        event = ConsoleEvent.objects.using(UMBRELLA).select_related('service, member, event_type').get(pk=event_id)
        response = {'html': event.render(request)}
    except ConsoleEvent.DoesNotExist:
        response = {'html': ''}
    response = callback + '(' + json.dumps(response) + ')'
    return HttpResponse(response, content_type='application/json')


def render_service_deployed_event(event, request):
    from ikwen.conf import settings as ikwen_settings
    service = event.service
    database = service.database
    add_database_to_settings(database)
    currency_symbol = service.config.currency_symbol
    try:
        invoice = Invoice.objects.using(database).get(pk=event.object_id)
    except Invoice.DoesNotExist:
        try:
            invoice = Invoice.objects.using(UMBRELLA).get(pk=event.object_id)
        except:
            invoice = None
    service_deployed = invoice.service if invoice else Service.objects.get(pk=event.object_id)
    show_pay_now = invoice.status != Invoice.PAID if invoice else False
    due_date = invoice.due_date if invoice else None
    is_daraja = service_deployed.app.slug == 'daraja'
    member = service_deployed.member
    if request.GET['member_id'] != member.id:
        data = {'title': 'New service deployed',
                'details': service_deployed.details,
                'member': member,
                'service_deployed': True}
        template_name = 'billing/events/notice.html'
    else:
        template_name = 'core/events/service_deployed.html'
        data = {'obj': invoice,
                'project_name': service_deployed.project_name,
                'service_url': service_deployed.url,
                'due_date': due_date,
                'is_daraja': is_daraja,
                'show_pay_now': show_pay_now}
    if is_daraja:
        data.update({'details_url': reverse('daraja:registered_company_list')})
    else:
        data.update({'currency_symbol': currency_symbol,
                     'details_url': IKWEN_BASE_URL + reverse('billing:invoice_detail', args=(invoice.id,)),
                     'amount': invoice.amount,
                     'MEMBER_AVATAR': ikwen_settings.MEMBER_AVATAR, 'IKWEN_MEDIA_URL': ikwen_settings.MEDIA_URL})
    c = Context(data)
    html_template = get_template(template_name)
    return html_template.render(c)


@cache_page(60 * 60)
def get_location_by_ip(request, *args, **kwargs):
    try:
        if getattr(settings, 'LOCAL_DEV', False):
            ip = '154.72.166.181'  # My Local IP by the time I was writing this code
        else:
            ip = request.META['REMOTE_ADDR']
        r = requests.get('http://geo.groupkt.com/ip/%s/json' % ip)
        result = json.loads(r.content.decode('utf-8'))
        location = result['RestResponse']['result']
        country = Country.objects.get(iso2=location['countryIso2'])
        city = location['city']
        response = {
            'country': country.to_dict(),
            'city': city
        }
    except:
        response = {'error': True}
    return HttpResponse(json.dumps(response))


class DashboardBase(TemplateView):

    template_name = 'core/dashboard_base.html'

    transactions_count_title = _("Transactions")
    transactions_avg_revenue_title = _('ARPT <i class="text-muted">Avg. Eearning Per Transaction</i>')

    def get_service(self, **kwargs):
        return get_service_instance()

    def get_context_data(self, **kwargs):
        context = super(DashboardBase, self).get_context_data(**kwargs)
        service = self.get_service(**kwargs)
        set_counters(service)
        earnings_today = calculate_watch_info(service.earnings_history)
        earnings_yesterday = calculate_watch_info(service.earnings_history, 1)
        earnings_last_week = calculate_watch_info(service.earnings_history, 7)
        earnings_last_28_days = calculate_watch_info(service.earnings_history, 28)

        earnings_report = {
            'today': earnings_today,
            'yesterday': earnings_yesterday,
            'last_week': earnings_last_week,
            'last_28_days': earnings_last_28_days
        }

        tx_count_today = calculate_watch_info(service.transaction_count_history)
        tx_count_yesterday = calculate_watch_info(service.transaction_count_history, 1)
        tx_count_last_week = calculate_watch_info(service.transaction_count_history, 7)
        tx_count_last_28_days = calculate_watch_info(service.transaction_count_history, 28)

        # AEPT stands for Average Earning Per Transaction
        aept_today = earnings_today['total'] / tx_count_today['total'] if tx_count_today['total'] else 0
        aept_yesterday = earnings_yesterday['total'] / tx_count_yesterday['total']\
            if tx_count_yesterday and tx_count_yesterday['total'] else 0
        aept_last_week = earnings_last_week['total'] / tx_count_last_week['total']\
            if tx_count_last_week and tx_count_last_week['total'] else 0
        aept_last_28_days = earnings_last_28_days['total'] / tx_count_last_28_days['total']\
            if tx_count_last_28_days and tx_count_last_28_days['total'] else 0

        transactions_report = {
            'today': {
                'count': tx_count_today['total'] if tx_count_today else 0,
                'aepo': '%.2f' % aept_today,  # AEPO: Avg Earning Per Order
            },
            'yesterday': {
                'count': tx_count_yesterday['total'] if tx_count_yesterday else 0,
                'aepo': '%.2f' % aept_yesterday,  # AEPO: Avg Earning Per Order
            },
            'last_week': {
                'count': tx_count_last_week['total'] if tx_count_last_week else 0,
                'aepo': '%.2f' % aept_last_week,  # AEPO: Avg Earning Per Order
            },
            'last_28_days': {
                'count': tx_count_last_28_days['total'] if tx_count_last_28_days else 0,
                'aepo': '%.2f' % aept_last_28_days,  # AEPO: Avg Earning Per Order
            }
        }

        qs = CashOutRequest.objects.using('wallets').filter(service_id=service.id, status=CashOutRequest.PAID).order_by('-id')
        last_cash_out = qs[0] if qs.count() >= 1 else None
        if last_cash_out:
            # Re-transform created_on into a datetime object
            try:
                last_cash_out.created_on = datetime(*strptime(last_cash_out.created_on[:19], '%Y-%m-%d %H:%M:%S')[:6])
            except TypeError:
                pass
            if last_cash_out.amount_paid:
                last_cash_out.amount = last_cash_out.amount_paid
        try:
            balance = 0
            for wallet in OperatorWallet.objects.using('wallets').filter(nonrel_id=service.id):
                balance += wallet.balance
            context['balance'] = balance
        except:
            pass
        context['earnings_report'] = earnings_report
        context['transactions_report'] = transactions_report
        context['transactions_count_title'] = self.transactions_count_title
        context['transactions_avg_revenue_title'] = self.transactions_avg_revenue_title
        context['last_cash_out'] = last_cash_out
        context['earnings_history'] = service.earnings_history[-30:]
        context['transaction_count_history'] = service.transaction_count_history[-30:]
        context['CRNCY'] = Currency.active.base()
        return context


class AdminHomeBase(TemplateView):

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        if action == 'update_domain':
            service = get_service_instance(using=UMBRELLA)
            new_domain = request.GET['new_domain'].lower()
            is_naked_domain = True if request.GET['type'] == Service.MAIN else False
            service.update_domain(new_domain, is_naked_domain)
            service.reload_settings(service.settings_template, is_naked_domain=is_naked_domain)
            return HttpResponse(json.dumps({'success': True}))
        return super(AdminHomeBase, self).get(request, *args, **kwargs)


class LegalMentions(TemplateView):
    template_name = 'core/legal_mentions.html'


class TermsAndConditions(TemplateView):
    template_name = 'core/terms_and_conditions.html'


class WelcomeMail(TemplateView):
    template_name = 'accesscontrol/mails/community_welcome.html'


class BaseExtMail(TemplateView):
    template_name = 'core/mails/base.html'


class ServiceExpired(TemplateView):
    template_name = 'core/service_expired.html'

    def get(self, request, *args, **kwargs):
        service = get_service_instance(using=UMBRELLA)
        if service.status == Service.PENDING or service.status == Service.ACTIVE:
            return HttpResponseRedirect(reverse('home'))
        return super(ServiceExpired, self).get(request, *args, **kwargs)


class Offline(TemplateView):
    """
    Offline page for the PWA
    """
    template_name = 'core/offline.html'
    

class SentEmailLog(HybridListView):
    model = XEmailObject
    html_results_template_name = 'core/snippets/sent_email_log_results.html'
    template_name = 'core/sent_email_log.html'
    list_filter = (
        'type',
        ('created_on', _('Date')),
    )


class SentEmailDetail(ChangeObjectBase):
    model = XEmailObject
    model_admin = getattr(settings, 'IKWEN_CONFIG_MODEL_ADMIN', 'ikwen.core.admin.XEmailObjectAdmin')
    template_name = 'core/sent_email_detail.html'
    context_object_name = 'email'
