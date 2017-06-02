# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta
from time import strptime

import requests
from ajaxuploader.views import AjaxFileUploader
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files import File
from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.db.models import get_model
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.utils import translation
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_by_path
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic.base import TemplateView
from django.views.generic.list import ListView
from django.contrib.admin import helpers
from django.utils.translation import gettext as _
from ikwen.cashout.models import CashOutRequest

from ikwen.accesscontrol.templatetags.auth_tokens import append_auth_tokens

from ikwen.billing.utils import get_invoicing_config_instance, get_billing_cycle_days_count, \
    get_billing_cycle_months_count, get_subscription_model

from ikwen.billing.models import Invoice

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member, ACCESS_REQUEST_EVENT
from ikwen.core.models import Service, QueuedSMS, ConsoleEventType, ConsoleEvent, AbstractConfig, Country, \
    OperatorWallet
from ikwen.core.utils import get_service_instance, DefaultUploadBackend, generate_favicons, add_database_to_settings, \
    add_database, calculate_watch_info, set_counters
import ikwen.conf.settings

try:
    ikwen_service = Service.objects.using(UMBRELLA).get(pk=ikwen.conf.settings.IKWEN_SERVICE_ID)
    IKWEN_BASE_URL = ikwen_service.url
except Service.DoesNotExist:
    IKWEN_BASE_URL = getattr(settings, 'IKWEN_BASE_URL') if getattr(settings, 'DEBUG',
                                                                    False) else ikwen.conf.settings.PROJECT_URL


class BaseView(TemplateView):
    def get_context_data(self, **kwargs):
        context = super(BaseView, self).get_context_data(**kwargs)
        context['lang'] = translation.get_language()[:2]
        context['year'] = datetime.now().year
        service = get_service_instance()
        context['service'] = service
        config = service.config
        context['config'] = config
        context['currency_code'] = config.currency_code
        context['currency_symbol'] = config.currency_symbol
        return context


class HybridListView(ListView):
    """
    Extension of the django builtin :class:`django.views.generic.ListView`. This view is Hybrid because it can
    render HTML or JSON results for Ajax calls.

    :attr:search_field: Name of the default field it uses to filter Ajax requests. Defaults to *name*
    :attr:ordering: Tuple of model fields used to order object list when page is rendered in HTML
    :attr:ajax_ordering: Tuple of model fields used to order results of Ajax requests. It is similar to ordering of
    django admin
    """
    page_size = int(getattr(settings, 'HYBRID_LIST_PAGE_SIZE', '25'))
    search_field = 'name'
    ordering = ('-created_on', )
    list_filter = ()
    ajax_ordering = ('-created_on', )

    def get_queryset(self):
        if self.queryset is not None:
            queryset = self.queryset
            if hasattr(queryset, '_clone'):
                queryset = queryset._clone()
        elif self.model is not None:
            queryset = self.model._default_manager.all()
        else:
            raise ImproperlyConfigured("'%s' must define 'queryset' or 'model'"
                                       % self.__class__.__name__)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(HybridListView, self).get_context_data(**kwargs)
        context.update(BaseView().get_context_data(**kwargs))
        context[self.context_object_name] = context[self.context_object_name].order_by(*self.ordering)[:self.page_size]
        context['page_size'] = self.page_size
        context['total_objects'] = self.get_queryset().count()
        context['filter'] = self.get_filter()
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('format') == 'json':
            queryset = self.get_queryset()
            queryset = self.filter_queryset(queryset)
            start_date = self.request.GET.get('start_date')
            end_date = self.request.GET.get('end_date')
            if start_date and end_date:
                queryset = queryset.filter(created_on__range=(start_date, end_date))
            elif start_date:
                queryset = queryset.filter(created_on__gte=start_date)
            elif end_date:
                queryset = queryset.filter(created_on__lte=end_date)
            start = int(self.request.GET.get('start'))
            length = int(self.request.GET.get('length', self.page_size))
            limit = start + length
            queryset = self.get_search_results(queryset)
            queryset = queryset.order_by(*self.ajax_ordering)[start:limit]
            response = []
            for item in queryset:
                try:
                    response.append(item.to_dict())
                except:
                    continue
            callback = self.request.GET.get('callback')
            if callback:
                response = {'object_list': response}
                jsonp = callback + '(' + json.dumps(response) + ')'
                return HttpResponse(jsonp, content_type='application/json', **response_kwargs)
            return HttpResponse(json.dumps(response), 'content-type: text/json', **response_kwargs)
        else:
            return super(HybridListView, self).render_to_response(context, **response_kwargs)

    def get_search_results(self, queryset):
        """
        Default search function that filters the queryset based on the value of GET parameter q and the search_field
        :param queryset:
        :return:
        """
        # TODO: Implement MongoDB native indexed text search instead of Django ORM one for better performance
        search_term = self.request.GET.get('q')
        if search_term and len(search_term) >= 2:
            search_term = search_term.lower()
            word = slugify(search_term)[:4]
            if word:
                kwargs = {self.search_field + '__icontains': word}
                queryset = queryset.filter(**kwargs)
        return queryset

    def get_filter(self):
        options = []
        for item in self.list_filter:
            if callable(item):
                filter = item()
                choices = filter.lookups()
                if choices:
                    options.append({
                        'title': filter.title,
                        'parameter_name': filter.parameter_name,
                        'choices': filter.lookups()
                    })
        return options

    def filter_queryset(self, queryset):
        for item in self.list_filter:
            if callable(item):
                filter = item()
                queryset = filter.queryset(self.request, queryset)
        return queryset


upload_image = AjaxFileUploader(DefaultUploadBackend)


class CustomizationImageUploadBackend(DefaultUploadBackend):
    """
    Ajax upload handler for ikwen cover and profile images
    """
    def upload_complete(self, request, filename, *args, **kwargs):
        import os
        from ikwen.conf import settings as ikwen_settings
        path = self.UPLOAD_DIR + "/" + filename
        self._dest.close()
        img_upload_context = request.GET['img_upload_context']
        media_root = getattr(settings, 'MEDIA_ROOT')
        usage = request.GET['usage']
        try:
            with open(media_root + path, 'r') as f:
                content = File(f)
                if img_upload_context == Configuration.UPLOAD_CONTEXT:
                    service_id = request.GET['service_id']
                    service = Service.objects.get(pk=service_id)
                    # service = get_service_instance()
                    config = service.config
                    if usage == 'profile':
                        current_image_path = config.logo.path if config.logo.name else None
                        destination = media_root + AbstractConfig.LOGO_UPLOAD_TO + "/" + filename
                        config.logo.save(destination, content)
                        url = ikwen_settings.MEDIA_URL + config.logo.name
                        src = config.logo.path
                        generate_favicons(src)
                    else:
                        current_image_path = config.cover_image.path if config.cover_image.name else None
                        destination = media_root + AbstractConfig.COVER_UPLOAD_TO + "/" + filename
                        config.cover_image.save(destination, content)
                        url = ikwen_settings.MEDIA_URL + config.cover_image.name
                        src = config.cover_image.path
                    cache.delete(service.id + ':config:')
                    cache.delete(service.id + ':config:default')
                    cache.delete(service.id + ':config:' + UMBRELLA)
                    config.save(using=UMBRELLA)
                    dst = src.replace(media_root, ikwen_settings.MEDIA_ROOT)
                    dst_folder = '/'.join(dst.split('/')[:-1])
                    if not os.path.exists(dst_folder):
                        os.makedirs(dst_folder)
                    try:
                        os.rename(src, dst)
                    except Exception as e:
                        if getattr(settings, 'DEBUG', False):
                            raise e
                else:
                    member_id = request.GET['member_id']
                    member = Member.objects.get(pk=member_id)
                    if usage == 'profile':
                        current_image_path = member.photo.path if member.photo.name else None
                        destination = media_root + Member.PROFILE_UPLOAD_TO + "/" + filename
                        member.photo.save(destination, content)
                        url = ikwen_settings.MEDIA_URL + member.photo.small_name
                    else:
                        current_image_path = member.cover_image.path if member.cover_image.name else None
                        destination = media_root + Member.COVER_UPLOAD_TO + "/" + filename
                        member.cover_image.save(destination, content)
                        url = ikwen_settings.MEDIA_URL + member.cover_image.name
            try:
                if os.path.exists(media_root + path):
                    os.unlink(media_root + path)
            except Exception as e:
                if getattr(settings, 'DEBUG', False):
                    raise e
            if current_image_path:
                try:
                    if os.path.exists(current_image_path):
                        os.unlink(current_image_path)
                except OSError as e:
                    if getattr(settings, 'DEBUG', False):
                        raise e
            return {
                'url': url
            }
        except IOError as e:
            if settings.DEBUG:
                raise e
            return {'error': 'File failed to upload. May be invalid or corrupted image file'}


upload_customization_image = AjaxFileUploader(CustomizationImageUploadBackend)


class DefaultHome(BaseView):
    """
    Can be used to set at default Home page for applications that do
    not have a public part. This merely shows the company name, logo
    and slogan. This view can be used to create the url with the
    name 'home' that MUST ABSOLUTELY EXIST in all Ikwen applications.
    """
    template_name = 'core/default_home.html'


class ServiceDetail(BaseView):
    template_name = 'core/service_detail.html'

    def get_context_data(self, **kwargs):
        context = super(ServiceDetail, self).get_context_data(**kwargs)
        invoicing_config = get_invoicing_config_instance(UMBRELLA)
        service_id = kwargs['service_id']
        service = Service.objects.using(UMBRELLA).get(pk=service_id)
        invoice = Invoice.get_last(service)
        if invoice:
            service.last_payment = invoice.created_on
        if not service.version or service.version == Service.FREE:
            service.expiry = None
        else:
            now = datetime.now()
            service.next_invoice_on = service.expiry - timedelta(days=invoicing_config.gap)
            if service.expiry < now.date():
                service.expired = True
            if now.date() > service.next_invoice_on:
                days = get_billing_cycle_days_count(service.billing_cycle)
                service.next_invoice_on = service.next_invoice_on + timedelta(days=days)
            service.next_invoice_amount = service.monthly_cost * get_billing_cycle_months_count(service.billing_cycle)
            service.pending_invoice_count = Invoice.objects.filter(subscription=service, status=Invoice.PENDING).count()

        context['service'] = service
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context


class Configuration(BaseView):
    template_name = 'core/configuration.html'

    UPLOAD_CONTEXT = 'config'

    def get_config_admin(self):
        from django.contrib.admin import AdminSite
        config_model_name = getattr(settings, 'IKWEN_CONFIG_MODEL', 'core.Config')
        app_label = config_model_name.split('.')[0]
        model = config_model_name.split('.')[1]
        config_model = get_model(app_label, model)
        default_site = AdminSite()
        model_admin_name = getattr(settings, 'IKWEN_CONFIG_MODEL_ADMIN', 'ikwen.core.admin.ConfigAdmin')
        config_model_admin = import_by_path(model_admin_name)
        config_admin = config_model_admin(config_model, default_site)
        return config_admin

    def get_context_data(self, **kwargs):
        context = super(Configuration, self).get_context_data(**kwargs)
        config_admin = self.get_config_admin()
        ModelForm = config_admin.get_form(self.request)
        if getattr(settings, 'IS_IKWEN', False):
            service_id = kwargs.get('service_id')
            if service_id:
                service = get_object_or_404(Service, pk=service_id)
                context['service'] = service
                context['config'] = service.config
        form = ModelForm(instance=context['config'])
        admin_form = helpers.AdminForm(form, list(config_admin.get_fieldsets(self.request)),
                                       config_admin.get_prepopulated_fields(self.request),
                                       config_admin.get_readonly_fields(self.request))
        context['model_admin_form'] = admin_form
        context['is_company'] = True
        context['img_upload_context'] = self.UPLOAD_CONTEXT
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        if getattr(settings, 'IS_IKWEN', False):
            service_id = kwargs.get('service_id')
            if service_id:
                service = get_object_or_404(Service, pk=service_id)
                next_url = reverse('ikwen:configuration', args=(service_id,))
            else:
                service = get_service_instance()
                next_url = reverse('ikwen:configuration')
        else:
            service = get_service_instance()
            next_url = reverse('ikwen:configuration')
        config_admin = self.get_config_admin()
        ModelForm = config_admin.get_form(request)
        form = ModelForm(request.POST, instance=service.config)
        if form.is_valid():
            form.cleaned_data['company_name_slug'] = slugify(form.cleaned_data['company_name'])
            form.save()
            cache.delete(service.id + ':config:')
            cache.delete(service.id + ':config:default')
            cache.delete(service.id + ':config:' + UMBRELLA)
            service.config.save(using=UMBRELLA)
            next_url = append_auth_tokens(next_url + '?success=yes', request)
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            admin_form = helpers.AdminForm(form, list(config_admin.get_fieldsets(self.request)),
                                           config_admin.get_prepopulated_fields(self.request),
                                           config_admin.get_readonly_fields(self.request))
            context['model_admin_form'] = admin_form
            return render(request, self.template_name, context)


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


class Console(BaseView):
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
        context['member'] = member
        context['profile_name'] = member.full_name
        context['profile_photo_url'] = member.photo.small_url if member.photo.name else ''
        context['profile_cover_url'] = member.cover_image.url if member.cover_image.name else ''

        type_access_request = ConsoleEventType.objects.get(codename=ACCESS_REQUEST_EVENT)
        access_request_events = {}
        for service in member.get_services():
            request_event_list = list(ConsoleEvent.objects
                                      .filter(event_type=type_access_request, member=member, service=service)
                                      .order_by('-id'))
            if len(request_event_list) > 0:
                access_request_events[service] = request_event_list

        event_list = ConsoleEvent.objects.exclude(event_type=type_access_request) \
                         .filter(Q(member=member) | Q(group_id__in=member.group_fk_list) | Q(group_id__isnull=True, member__isnull=True),
                                 service__in=member.get_services()).order_by('-id')[:length]
        context['access_request_events'] = access_request_events
        context['event_list'] = event_list
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
            queryset = ConsoleEvent.objects.exclude(event_type=type_access_request)\
                           .filter(Q(member=member) | Q(group_id__in=member.group_fk_list) | Q(group_id__isnull=True, member__isnull=True),
                                   service__in=member.get_services()).order_by('-id')[start:limit]
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


class DefaultDashboard(BaseView):
    """
    Can be used to set at default Dashboard page for applications.
    This view can be used to create the url with the name 'admin_home'
    that MUST ABSOLUTELY EXIST in all ikwen applications.
    """
    template_name = 'core/dashboard.html'


def list_projects(request, *args, **kwargs):
    q = request.GET['q'].lower()
    if len(q) < 2:
        return

    queryset = Service.objects.using(UMBRELLA)
    word = slugify(q)[:4]
    if word:
        queryset = queryset.filter(project_name__icontains=word)

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
        event = ConsoleEvent.objects.using(UMBRELLA).get(pk=event_id)
        response = {'html': event.render(request)}
    except ConsoleEvent.DoesNotExist:
        response = {'html': ''}
    response = callback + '(' + json.dumps(response) + ')'
    return HttpResponse(response, content_type='application/json')


def render_service_deployed_event(event, request):
    service = event.service
    database = service.database
    add_database_to_settings(database)
    currency_symbol = service.config.currency_symbol
    invoice = Invoice.objects.using(database).get(pk=event.object_id)
    service_deployed = invoice.service
    member = service_deployed.member
    if request.user != member:
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
                'due_date': invoice.due_date,
                'show_pay_now': invoice.status != Invoice.PAID}
    from ikwen.conf import settings as ikwen_settings
    data.update({'currency_symbol': currency_symbol,
                 'details_url': service.url + reverse('billing:invoice_detail', args=(invoice.id,)),
                 'amount': invoice.amount,
                 'MEMBER_AVATAR': ikwen_settings.MEMBER_AVATAR, 'IKWEN_MEDIA_URL': ikwen_settings.MEDIA_URL})
    c = Context(data)
    html_template = get_template(template_name)
    return html_template.render(c)


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


class DashboardBase(BaseView):

    def get_context_data(self, **kwargs):
        context = super(DashboardBase, self).get_context_data(**kwargs)
        service = get_service_instance()
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

        qs = CashOutRequest.objects.using('wallets').filter(service_id=service.id, status=CashOutRequest.PAID).order_by('-id')
        last_cash_out = qs[0] if qs.count() >= 1 else None
        if last_cash_out:
            # Re-transform created_on into a datetime object
            last_cash_out.created_on = datetime(*strptime(last_cash_out.created_on[:19], '%Y-%m-%d %H:%M:%S')[:6])
        service = get_service_instance()
        try:
            wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=service.id)
            context['wallet'] = wallet
        except:
            pass
        context['earnings_report'] = earnings_report
        context['last_cash_out'] = last_cash_out
        return context


class LegalMentions(BaseView):
    template_name = 'core/contact.html'


class TermsAndConditions(BaseView):
    template_name = 'core/contact.html'


class WelcomeMail(BaseView):
    template_name = 'accesscontrol/mails/welcome.html'


class BaseExtMail(BaseView):
    template_name = 'core/mails/base.html'


class ServiceExpired(BaseView):
    template_name = 'core/service_expired.html'
