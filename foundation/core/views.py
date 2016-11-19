# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta

import requests
from ajaxuploader.views import AjaxFileUploader
from django.conf import settings
from django.contrib.admin import helpers
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files import File
from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import reverse
from django.db.models import get_model
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.template.defaultfilters import slugify
from django.utils import translation
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_by_path
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic.base import TemplateView
from django.views.generic.list import ListView

from ikwen.foundation.accesscontrol.templatetags.auth_tokens import append_auth_tokens

from ikwen.foundation.billing.utils import get_invoicing_config_instance, get_billing_cycle_days_count, \
    get_billing_cycle_months_count

from ikwen.foundation.billing.models import Invoice

from ikwen.foundation.accesscontrol.backends import UMBRELLA
from ikwen.foundation.accesscontrol.models import Member, ACCESS_REQUEST_EVENT
from ikwen.foundation.core.models import Service, QueuedSMS, ConsoleEventType, ConsoleEvent, AbstractConfig, Country
from ikwen.foundation.core.utils import get_service_instance, DefaultUploadBackend, generate_favicons
import ikwen.conf.settings

IKWEN_BASE_URL = getattr(settings, 'IKWEN_BASE_URL') if getattr(settings, 'DEBUG', False) else ikwen.conf.settings.PROJECT_URL


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
            response = [order.to_dict() for order in queryset]
            return HttpResponse(
                json.dumps(response),
                'content-type: text/json',
                **response_kwargs
            )
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
            for word in search_term.split(' '):
                word = slugify(word)[:4]
                if word:
                    kwargs = {self.search_field + '__icontains': word}
                    queryset = queryset.filter(**kwargs)
                    if queryset.count() > 0:
                        break
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
        path = self.UPLOAD_DIR + "/" + filename
        self._dest.close()
        img_upload_context = request.GET['img_upload_context']
        media_root = getattr(settings, 'MEDIA_ROOT')
        usage = request.GET['usage']
        try:
            with open(media_root + path, 'r') as f:
                content = File(f)
                if img_upload_context == Configuration.UPLOAD_CONTEXT:
                    service = get_service_instance()
                    config = get_service_instance().config
                    if usage == 'profile':
                        current_image_path = config.logo.path if config.logo.name else None
                        destination = media_root + AbstractConfig.LOGO_UPLOAD_TO + "/" + filename
                        config.logo.save(destination, content)
                        url = config.logo.url
                        src = config.logo.path
                        generate_favicons(src)
                    else:
                        current_image_path = config.cover_image.path if config.cover_image.name else None
                        destination = media_root + AbstractConfig.COVER_UPLOAD_TO + "/" + filename
                        config.cover_image.save(destination, content)
                        url = config.cover_image.url
                        src = config.cover_image.path
                    cache.delete(service.id + ':config:')
                    cache.delete(service.id + ':config:default')
                    cache.delete(service.id + ':config:' + UMBRELLA)
                    config.save(using=UMBRELLA)
                    from ikwen.conf import settings as ikwen_settings
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
                        url = member.photo.small_url
                    else:
                        current_image_path = member.cover_image.path if member.cover_image.name else None
                        destination = media_root + Member.COVER_UPLOAD_TO + "/" + filename
                        member.cover_image.save(destination, content)
                        url = member.cover_image.url
            try:
                os.unlink(media_root + path)
            except Exception as e:
                if getattr(settings, 'DEBUG', False):
                    raise e
            if current_image_path:
                try:
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
            if service.expiry < now:
                service.expired = True
            if now > service.next_invoice_on:
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
        model_admin_name = getattr(settings, 'IKWEN_CONFIG_MODEL_ADMIN', 'ikwen.foundation.core.admin.ConfigAdmin')
        config_model_admin = import_by_path(model_admin_name)
        config_admin = config_model_admin(config_model, default_site)
        return config_admin

    def get_context_data(self, **kwargs):
        from django.contrib.admin import helpers
        context = super(Configuration, self).get_context_data(**kwargs)
        config_admin = self.get_config_admin()
        ModelForm = config_admin.get_form(self.request)
        form = ModelForm(instance=context['config'])
        admin_form = helpers.AdminForm(form, list(config_admin.get_fieldsets(self.request)),
                                       config_admin.get_prepopulated_fields(self.request),
                                       config_admin.get_readonly_fields(self.request))
        context['model_admin_form'] = admin_form
        context['img_upload_context'] = self.UPLOAD_CONTEXT
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        service = get_service_instance()
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
            next_url = reverse('ikwen:configuration') + '?success=yes'
            next_url = append_auth_tokens(next_url, request)
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            return render(request, self.template_name, context)


def pay_invoice(request, *args, **kwargs):
    member = request.user


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
        target = ConsoleEventType.PERSONAL if len(self.request.user.collaborates_on) == 0\
            else self.request.GET.get('target', ConsoleEventType.BUSINESS)

        access_request_events = {}
        for service in list(set(member.collaborates_on) | set(member.customer_on)):
            type_access_request = ConsoleEventType.objects.get(codename=ACCESS_REQUEST_EVENT)
            if target == ConsoleEventType.BUSINESS:
                request_event_list = list(ConsoleEvent.objects
                                          .filter(event_type=type_access_request, member=member, service=service)
                                          .order_by('-id'))
                if len(request_event_list) > 0:
                    access_request_events[service] = request_event_list

        targeted_type = list(ConsoleEventType.objects.filter(target=target).exclude(codename=ACCESS_REQUEST_EVENT))
        event_list = ConsoleEvent.objects.filter(event_type__in=targeted_type, member=member).order_by('-id')[:length]
        context['access_request_events'] = access_request_events
        context['event_list'] = event_list
        context['is_console'] = True  # console.html extends profile.html, so this helps differentiates in templates
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('format') == 'json':
            target = ConsoleEventType.PERSONAL if len(self.request.user.collaborates_on) == 0\
                else self.request.GET.get('target', ConsoleEventType.BUSINESS)
            start = int(self.request.GET['start'])
            if self.request.user_agent.is_mobile:
                length = 10
            elif self.request.user_agent.is_tablet:
                length = 20
            else:
                length = 30
            limit = start + length
            targeted_type = list(ConsoleEventType.objects.filter(target=target).exclude(codename=ACCESS_REQUEST_EVENT))
            queryset = ConsoleEvent.objects \
                           .filter(event_type__in=targeted_type, member=self.request.user).order_by('-id')[start:limit]
            response = [event.to_dict() for event in queryset]
            return HttpResponse(
                json.dumps(response),
                'content-type: text/json',
                **response_kwargs
            )
        else:
            return super(Console, self).render_to_response(context, **response_kwargs)


@login_required
def reset_notices_counter(request, *args, **kwargs):
    target = ConsoleEventType.PERSONAL if len(request.user.collaborates_on) == 0 else request.GET['target']
    if target == '':
        target = ConsoleEventType.BUSINESS
    if target == ConsoleEventType.BUSINESS:
        request.user.business_notices = 0
    else:
        request.user.personal_notices = 0

    request.user.save()
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
    for word in q.split(' '):
        word = slugify(word)[:4]
        if word:
            queryset = queryset.filter(project_name__icontains=word)
            if queryset.count() > 0:
                break

    projects = []
    for s in queryset.order_by('project_name')[:6]:
        p = s.to_dict()
        p['url'] = IKWEN_BASE_URL + reverse('ikwen:company_profile', args=(s.app.slug, s.project_name_slug))
        projects.append(p)

    response = {'object_list': projects}
    callback = request.GET['callback']
    jsonp = callback + '(' + json.dumps(response) + ')'
    return HttpResponse(jsonp, content_type='application/json')


@login_required
def load_event_content(request, *args, **kwargs):
    event_id = request.GET['event_id']
    try:
        event = ConsoleEvent.objects.using(UMBRELLA).get(pk=event_id)
        response = {'html': event.render()}
        callback = request.GET['callback']
        response = callback + '(' + json.dumps(response) + ')'
        return HttpResponse(response, content_type='application/json')
    except ConsoleEvent.DoesNotExist:
        return None


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


class Contact(BaseView):
    template_name = 'core/contact.html'


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
