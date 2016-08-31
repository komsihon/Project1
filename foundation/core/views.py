# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta

from ajaxuploader.views import AjaxFileUploader
from django.conf import settings
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

from ikwen.foundation.billing.utils import get_invoicing_config_instance, get_billing_cycle_days_count, \
    get_billing_cycle_months_count

from ikwen.foundation.billing.models import Invoice

from ikwen.foundation.accesscontrol.backends import UMBRELLA
from ikwen.foundation.accesscontrol.models import Member
from ikwen.foundation.core.models import Service, QueuedSMS, ConsoleEventType, ConsoleEvent, AbstractConfig
from ikwen.foundation.core.utils import get_service_instance, DefaultUploadBackend, strip_datetime_fields
import ikwen.conf.settings

IKWEN_BASE_URL = getattr(settings, 'PROJECT_URL') if getattr(settings, 'DEBUG', False) else ikwen.conf.settings.PROJECT_URL


class BaseView(TemplateView):
    def get_context_data(self, **kwargs):
        context = super(BaseView, self).get_context_data(**kwargs)
        context['lang'] = translation.get_language()[:2]
        context['year'] = datetime.now().year
        service = get_service_instance()
        context['service'] = service
        context['config'] = service.config
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
    object_count = int(getattr(settings, 'HYBRID_LIST_OBJECT_COUNT', '24'))
    search_field = 'name'
    ordering = ('-created_on', )
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
        context[self.context_object_name] = context[self.context_object_name].order_by(*self.ordering)[:self.object_count]
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('format') == 'json':
            queryset = self.get_queryset()
            start_date = self.request.GET.get('start_date')
            end_date = self.request.GET.get('end_date')
            if start_date and end_date:
                queryset = queryset.filter(created_on__range=(start_date, end_date))
            elif start_date:
                queryset = queryset.filter(created_on__gte=start_date)
            elif end_date:
                queryset = queryset.filter(created_on__lte=end_date)
            start = int(self.request.GET.get('start'))
            length = int(self.request.GET.get('length'))
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
            for word in search_term.split(' '):
                word = slugify(word)[:4]
                if word:
                    kwargs = {self.search_field + '__icontains': word}
                    queryset = queryset.filter(**kwargs)
                    if queryset.count() > 0:
                        break
        return queryset


class CustomizationImageUploadBackend(DefaultUploadBackend):
    """
    Ajax upload handler for ikwen cover and profile images
    """
    def upload_complete(self, request, filename, *args, **kwargs):
        import os
        path = self.UPLOAD_DIR + "/" + filename
        self._dest.close()
        media_root = getattr(settings, 'MEDIA_ROOT')
        img_upload_context = request.GET['img_upload_context']
        usage = request.GET['usage']
        try:
            with open(media_root + path, 'r') as f:
                content = File(f)
                if img_upload_context == Configuration.UPLOAD_CONTEXT:
                    config = get_service_instance().config
                    if usage == 'profile':
                        destination = media_root + AbstractConfig.LOGO_UPLOAD_TO + "/" + filename
                        config.logo.save(destination, content)
                        url = config.logo.url
                    else:
                        destination = media_root + AbstractConfig.COVER_UPLOAD_TO + "/" + filename
                        config.cover_image.save(destination, content)
                        url = config.cover_image.url
                else:
                    member_id = request.GET['member_id']
                    member = Member.objects.get(pk=member_id)
                    if usage == 'profile':
                        destination = media_root + Member.PROFILE_UPLOAD_TO + "/" + filename
                        member.photo.save(destination, content)
                        url = member.photo.small_url
                    else:
                        destination = media_root + Member.COVER_UPLOAD_TO + "/" + filename
                        member.cover_image.save(destination, content)
                        url = member.cover_image.url
            os.unlink(media_root + path)
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
        if service.version == Service.FREE:
            service.expiry = None
        else:
            now = datetime.now()
            service.next_invoice_on = service.expiry - timedelta(days=invoicing_config.gap)
            if now > service.next_invoice_on:
                days = get_billing_cycle_days_count(service.billing_cycle)
                service.next_invoice_on = service.next_invoice_on + timedelta(days=days)
            service.next_invoice_amount = service.monthly_cost * get_billing_cycle_months_count(service.billing_cycle)
            service.pending_invoice_count = Invoice.objects.filter(subscription=service, status=Invoice.PENDING).count()

        context['service'] = service
        context['currency'] = invoicing_config.currency
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
                                       config_admin.get_prepopulated_fields(self.request))
        context['config_admin_form'] = admin_form
        context['img_upload_context'] = self.UPLOAD_CONTEXT
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context

    # def get(self, request, *args, **kwargs):
    #     if request.user.is_authenticated():
    #         next_url = request.REQUEST.get('next')
    #         if next_url:
    #             return HttpResponseRedirect(next_url)
    #         next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', 'ikwen:console')
    #         return HttpResponseRedirect(reverse(next_url_view))
    #     return render(request, self.template_name, {'service': get_service_instance()})

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        service = get_service_instance()
        config_admin = self.get_config_admin()
        ModelForm = config_admin.get_form(request)
        form = ModelForm(request.POST, instance=service.config)
        if form.is_valid():
            form.save()
            service.config.save(using=UMBRELLA)
            cache.delete(service.config.id + ':')
            cache.delete(service.config.id + ':default')
            cache.delete(service.config.id + ':' + UMBRELLA)
            next_url = reverse('ikwen:configuration') + '?success=yes'
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            return render(request, self.template_name, context)


def before_paypal_set_checkout(request, *args, **kwargs):
    config = get_service_instance().config
    setattr(settings, 'PAYPAL_WPP_USER', config.paypal_user)
    setattr(settings, 'PAYPAL_WPP_PASSWORD', config.paypal_password)
    setattr(settings, 'PAYPAL_WPP_SIGNATURE', config.paypal_api_signature)
    # return set_ch


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
        member = Member.objects.using(UMBRELLA).get(pk=self.request.user.id)
        context['member'] = member
        context['profile_name'] = member.full_name
        context['profile_photo_url'] = member.photo.small_url if member.photo.name else ''
        context['profile_cover_url'] = member.cover_image.url if member.cover_image.name else ''
        target = self.request.GET.get('target', ConsoleEvent.BUSINESS)
        events = {}
        for service in member.collaborates_on:
            service_events = {}
            for type in ConsoleEventType.objects.using(UMBRELLA).filter(app=service.app):
                pending = list(ConsoleEvent.objects.using(UMBRELLA)
                               .filter(target=target, event_type=type, member=member, service=service, status=ConsoleEvent.PENDING)
                               .order_by('-id')[:4])
                event_types = {}
                if len(pending) > 0:
                    event_types['pending'] = pending
                if len(pending) < 4:
                    c = 4 - len(pending)
                    others = list(ConsoleEvent.objects.using(UMBRELLA)
                                  .filter(target=target, event_type=type, member=member, service=service)
                                  .exclude(status=ConsoleEvent.PENDING).order_by('-id')[:c])
                    if len(others) > 0:
                        event_types['others'] = others
                if event_types:
                    service_events[type] = event_types
            if service_events:
                events[service] = service_events
        context['events'] = events
        context['is_console'] = True
        return context


@login_required
def reset_notices_counter(request, *args, **kwargs):
    target = request.GET['target']
    if target == ConsoleEvent.BUSINESS:
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
    q = request.GET['q']
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
    return HttpResponse(json.dumps(projects), content_type='application/json')


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
