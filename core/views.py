# -*- coding: utf-8 -*-
import json
import os
import random
import string
from copy import deepcopy
from datetime import datetime, timedelta
from time import strptime

import requests
from ajaxuploader.views import AjaxFileUploader
from currencies.models import Currency
from django.conf import settings
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files import File
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.db.models import get_model
from django.db.models.fields.files import ImageFieldFile
from django.forms.models import modelform_factory
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic.base import TemplateView
from django.views.generic.list import ListView

import ikwen.conf.settings
from echo.models import Balance
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member, ACCESS_REQUEST_EVENT
from ikwen.billing.models import Invoice, SupportCode
from ikwen.billing.utils import get_invoicing_config_instance, get_billing_cycle_days_count, \
    get_billing_cycle_months_count, refresh_currencies_exchange_rates
from ikwen.cashout.models import CashOutRequest
from ikwen.core.models import Service, QueuedSMS, ConsoleEventType, ConsoleEvent, AbstractConfig, Country, \
    OperatorWallet
from ikwen.core.utils import get_service_instance, DefaultUploadBackend, generate_favicons, add_database_to_settings, \
    add_database, calculate_watch_info, set_counters, get_model_admin_instance
from ikwen.rewarding.models import CROperatorProfile
from ikwen.revival.models import ProfileTag, Revival

try:
    ikwen_service = Service.objects.using(UMBRELLA).get(pk=ikwen.conf.settings.IKWEN_SERVICE_ID)
    IKWEN_BASE_URL = ikwen_service.url
except Service.DoesNotExist:
    IKWEN_BASE_URL = getattr(settings, 'IKWEN_BASE_URL') if getattr(settings, 'DEBUG',
                                                                    False) else ikwen.conf.settings.PROJECT_URL


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
    ordering = ('-id', )
    list_filter = ()
    ajax_ordering = ('-id', )
    template_name = 'core/object_list_base.html'
    html_results_template_name = 'core/snippets/object_list_results.html'
    change_object_url_name = None

    def get_context_data(self, **kwargs):
        context = super(HybridListView, self).get_context_data(**kwargs)
        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        max_chars = self.request.GET.get('max_chars', 4)
        if start_date and end_date:
            queryset = queryset.filter(created_on__range=(start_date, end_date))
        elif start_date:
            queryset = queryset.filter(created_on__gte=start_date)
        elif end_date:
            queryset = queryset.filter(created_on__lte=end_date)
        queryset = self.get_search_results(queryset, max_chars=max_chars)
        context_object_name = self.get_context_object_name(self.object_list)
        context[context_object_name] = context[context_object_name].order_by(*self.ordering)[:self.page_size]
        context['queryset'] = queryset
        context['page_size'] = self.page_size
        context['total_objects'] = self.get_queryset().count()
        context['filter'] = self.get_filter()
        model = self.get_queryset().model
        meta = model._meta
        context['verbose_name'] = meta.verbose_name
        context['verbose_name_plural'] = meta.verbose_name_plural
        try:
            context['has_is_active_field'] = model().is_active
        except AttributeError:
            pass
        if not self.change_object_url_name:
            self.change_object_url_name = '%s:change_%s' % (meta.app_label, meta.model_name)
        context['change_object_url_name'] = self.change_object_url_name
        return context

    def render_to_response(self, context, **response_kwargs):
        fmt = self.request.GET.get('format')
        queryset = context['queryset']
        if fmt == 'json':
            queryset = queryset.order_by(*self.ajax_ordering)
            start = int(self.request.GET.get('start', 0))
            length = int(self.request.GET.get('length', self.page_size))
            limit = start + length
            queryset = queryset[start:limit]
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
            queryset = queryset.order_by(*self.ordering)
            paginator = Paginator(queryset, self.page_size)
            page = self.request.GET.get('page')
            try:
                objects_page = paginator.page(page)
            except PageNotAnInteger:
                objects_page = paginator.page(1)
            except EmptyPage:
                objects_page = paginator.page(paginator.num_pages)
            context['q'] = self.request.GET.get('q')
            context['objects_page'] = objects_page
            if fmt == 'html_results':
                return render(self.request, self.html_results_template_name, context)
            else:
                return super(HybridListView, self).render_to_response(context, **response_kwargs)

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        model_name = request.GET.get('model_name')
        if model_name:
            tokens = model_name.split('.')
            model = get_model(tokens[0], tokens[1])
        else:
            model = self.model
        if action == 'delete':
            selection = request.GET['selection'].split(',')
            deleted = []
            for pk in selection:
                try:
                    obj = model.objects.get(pk=pk)
                    obj.delete()
                    deleted.append(pk)
                except:
                    continue
            response = {
                'message': "%d item(s) deleted." % len(selection),
                'deleted': deleted
            }
            return HttpResponse(json.dumps(response))
        elif action == 'toggle_attribute':
            object_id = request.GET['object_id']
            attr = request.GET['attr']
            val = request.GET['val']
            obj = model._default_manager.get(pk=object_id)
            if val.lower() == 'true':
                obj.__dict__[attr] = True
            else:
                obj.__dict__[attr] = False
            obj.save()
            response = {'success': True}
            return HttpResponse(json.dumps(response), 'content-type: text/json')
        # Sorting stuffs
        sorted_keys = request.GET.get('sorted')
        if sorted_keys:
            for token in sorted_keys.split(','):
                object_id, order_of_appearance = token.split(':')
                try:
                    model.objects.filter(pk=object_id).update(order_of_appearance=order_of_appearance)
                except:
                    continue
        return super(HybridListView, self).get(request, *args, **kwargs)

    def get_search_results(self, queryset, max_chars=None):
        """
        Default search function that filters the queryset based on
        the value of GET parameter q and the search_field.
        Only the first max_chars of the search string will be used
        to search. Setting it to none causes to search with the
        input string exactly as such.
        """
        # TODO: Implement MongoDB native indexed text search instead of Django ORM one for better performance
        search_term = self.request.GET.get('q')
        if search_term and len(search_term) >= 2:
            search_term = search_term.lower()
            word = slugify(search_term).replace('-', ' ')
            try:
                word = word[:int(max_chars)]
            except:
                pass
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
            else:
                item_values = set([obj.__getattribute__(item) for obj in self.get_queryset()])
                item_values = list(sorted(item_values))
                options.append({
                    'title': item.capitalize(),
                    'parameter_name': item,
                    'choices': [(val, val) for val in item_values]
                })
        return options

    def filter_queryset(self, queryset):
        for item in self.list_filter:
            if callable(item):
                filter = item()
                queryset = filter.queryset(self.request, queryset)
            else:
                kwargs = {}
                value = self.request.GET.get(item)
                if value:
                    kwargs[item] = value
                    queryset = queryset.filter(**kwargs)
        return queryset


class ChangeObjectBase(TemplateView):
    model = None
    model_admin = None
    object_list_url = None  # Django url name of the object list page
    change_object_url = None  # Django url name of the change object page
    template_name = 'core/change_object_base.html'
    context_object_name = 'obj'
    profiles_aware = False  # If set to true, object ProfileTag management utilities will be integrated to the object
    auto_profile = False  # If true, this object generates a secret ProfileTag matching the actual object upon save
    revival_mail_renderer = None
    image_field = None
    label_field = None
    image_help_text = None

    def get_object(self, **kwargs):
        object_id = kwargs.get('object_id')  # May be overridden with the one from GET data
        object_id = self.request.GET.get('object_id', object_id)
        if object_id:
            return get_object_or_404(self.model, pk=object_id)

    def get_model_form(self, obj):
        ModelForm = modelform_factory(self.model, fields=self.model_admin.fields)
        if obj:
            form = ModelForm(instance=obj)
        else:
            form = ModelForm(instance=self.model())
        return form

    def get_context_data(self, **kwargs):
        context = super(ChangeObjectBase, self).get_context_data(**kwargs)
        model_admin = get_model_admin_instance(self.model, self.model_admin)
        obj = self.get_object(**kwargs)
        form = self.get_model_form(obj)
        obj_form = helpers.AdminForm(form, list(model_admin.get_fieldsets(self.request, obj)),
                                     model_admin.get_prepopulated_fields(self.request, obj),
                                     model_admin.get_readonly_fields(self.request, obj))

        context[self.context_object_name] = obj
        model_obj = self.model()
        context['obj'] = obj  # Base template recognize the context object only with the name 'obj'
        context['verbose_name'] = model_obj._meta.verbose_name
        context['verbose_name_plural'] = model_obj._meta.verbose_name_plural
        context['object_list_url'] = self.get_object_list_url(self.request, obj, **kwargs)
        context['model_admin_form'] = obj_form
        context['label_field'] = self.label_field if self.label_field else 'name'
        img_field_list = []
        i = 0
        for key in model_obj.__dict__.keys():
            field = model_obj.__getattribute__(key)
            if isinstance(field, ImageFieldFile):
                img_obj = {
                    'image': field,
                    'field': key,
                    'help_text': field.field.help_text,
                    'counter': i
                }
                img_field_list.append(img_obj)
                i += 1
        context['img_field_list'] = img_field_list
        return context

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        if action == 'delete_image':
            object_id = kwargs.get('object_id')
            obj = get_object_or_404(self.model, pk=object_id)
            image_field_name = request.POST.get('image_field_name', 'image')
            image_field = obj.__getattribute__(image_field_name)
            if image_field.name:
                os.unlink(image_field.path)
                try:
                    os.unlink(image_field.small_path)
                    os.unlink(image_field.thumb_path)
                except:
                    pass
                obj.__setattr__(image_field_name, None)
                obj.save()
            return HttpResponse(
                json.dumps({'success': True}),
                content_type='application/json'
            )
        return super(ChangeObjectBase, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        object_admin = get_model_admin_instance(self.model, self.model_admin)
        object_id = kwargs.get('object_id')
        before = None
        if object_id:
            obj = self.get_object(**kwargs)
            before = deepcopy(obj)
        else:
            obj = self.model()
        model_form = object_admin.get_form(request)
        form = model_form(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            slug_field_name = request.POST.get('slug_field_name', 'slug')
            try:
                obj.__getattribute__(slug_field_name)
                name_field_name = request.POST.get('name_field_name', 'name')
                try:
                    name_field = obj.__getattribute__(name_field_name)
                    obj.__setattr__(slug_field_name, slugify(name_field))
                    obj.save()
                except:
                    pass
            except:
                pass

            if self.auto_profile:
                name_field_name = request.POST.get('name_field_name', 'name')
                try:
                    name_field = obj.__getattribute__(name_field_name)
                    slug = '__' + slugify(name_field)
                    if before:
                        before_name = before.__getattribute__(name_field_name)
                        before_slug = '__' + slugify(before_name)
                        if before_name != name_field:
                            ProfileTag.objects.filter(slug=before_slug).update(name=name_field, slug=slug)
                    else:
                        ProfileTag.objects.get_or_create(name=name_field, slug=slug, is_auto=True)
                except:
                    pass

            image_url = request.POST.get('image_url')
            if image_url:
                s = get_service_instance()
                image_field_name = request.POST.get('image_field_name', 'image')
                image_field = obj.__getattribute__(image_field_name)
                if not image_field.name or image_url != image_field.url:
                    filename = image_url.split('/')[-1]
                    media_root = getattr(settings, 'MEDIA_ROOT')
                    media_url = getattr(settings, 'MEDIA_URL')
                    path = image_url.replace(media_url, '')
                    try:
                        with open(media_root + path, 'r') as f:
                            content = File(f)
                            destination = media_root + obj.UPLOAD_TO + "/" + s.project_name_slug + '_' + filename
                            image_field.save(destination, content)
                        os.unlink(media_root + path)
                    except IOError as e:
                        if getattr(settings, 'DEBUG', False):
                            raise e
                        return {'error': 'File failed to upload. May be invalid or corrupted image file'}
            self.save_object_profile_tags(request, obj, *args, **kwargs)
            self.after_save(request, obj, *args, **kwargs)
            if request.POST.get('keep_editing'):
                next_url = self.get_change_object_url(request, obj, *args, **kwargs)
            else:
                next_url = self.get_object_list_url(request, obj, *args, **kwargs)
            if object_id:
                messages.success(request, obj._meta.verbose_name.capitalize() + ' <strong>' + str(obj).decode('utf8') + '</strong> ' + _('successfully updated'))
            else:
                messages.success(request, obj._meta.verbose_name.capitalize() + ' <strong>' + str(obj).decode('utf8') + '</strong> ' + _('successfully created'))
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['errors'] = form.errors
            return render(request, self.template_name, context)

    def get_object_list_url(self, request, obj, *args, **kwargs):
        if self.object_list_url:
            url = reverse(self.object_list_url)
        else:
            try:
                if obj is None:
                    obj = self.model()
                url = reverse('%s:%s_list' % (obj._meta.app_label, obj._meta.model_name))
            except:
                url = request.META['HTTP_REFERER']
        return url

    def get_change_object_url(self, request, obj, *args, **kwargs):
        if self.change_object_url:
            url = reverse(self.change_object_url, args=(obj.id, ))
        else:
            try:
                if obj is None:
                    obj = self.model()
                url = reverse('%s:change_%s' % (obj._meta.app_label, obj._meta.model_name))
            except:
                url = request.META['HTTP_REFERER']
        return url

    def save_object_profile_tags(self, request, obj, *args, **kwargs):
        auto_profiletag_id_list = kwargs.pop('auto_profiletag_id_list', [])
        profiletag_ids = request.GET.get('profiletag_ids', '').strip()
        revival_mail_renderer = kwargs.pop('revival_mail_renderer', self.revival_mail_renderer)
        if not (profiletag_ids or auto_profiletag_id_list):
            return
        do_revive = kwargs.pop('do_revive', None)  # Set a revival if explicitly stated to do so
        if do_revive is None and not kwargs.get('object_id'):
            do_revive = True  # Set a revival in any case for a newly added item
        profiletag_id_list = []
        if profiletag_ids:
            profiletag_id_list = profiletag_ids.split(',')
        profiletag_id_list.extend(auto_profiletag_id_list)
        model_name = obj._meta.app_label + '.' + obj._meta.model_name
        if do_revive and revival_mail_renderer:  # This is a newly created object
            service = get_service_instance()
            srvce = Service.objects.using(UMBRELLA).get(pk=service.id)
            for tag_id in profiletag_id_list:
                revival, update = Revival.objects.get_or_create(service=service, model_name=model_name, object_id=obj.id,
                                                 profile_tag_id=tag_id, mail_renderer=revival_mail_renderer)
                Revival.objects.using(UMBRELLA).get_or_create(id=revival.id, service=srvce, model_name=model_name, object_id=obj.id,
                                                       profile_tag_id=tag_id, mail_renderer=revival_mail_renderer)

    def after_save(self, request, obj, *args, **kwargs):
        """
        Run after the form is successfully saved
        in the post() function
        """


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
                    config = service.config
                    if usage == 'profile':
                        current_image_path = config.logo.path if config.logo.name else None
                        destination = media_root + AbstractConfig.LOGO_UPLOAD_TO + "/" + filename
                        config.logo.save(destination, content)
                        url = ikwen_settings.MEDIA_URL + config.logo.name
                        src = config.logo.path
                        generate_favicons(src)
                        destination2_folder = ikwen_settings.MEDIA_ROOT + AbstractConfig.LOGO_UPLOAD_TO
                        if not os.path.exists(destination2_folder):
                            os.makedirs(destination2_folder)
                        destination2 = config.logo.path.replace(media_root, ikwen_settings.MEDIA_ROOT)
                        os.rename(destination, destination2)
                    else:
                        current_image_path = config.cover_image.path if config.cover_image.name else None
                        destination = media_root + AbstractConfig.COVER_UPLOAD_TO + "/" + filename
                        config.cover_image.save(destination, content)
                        url = ikwen_settings.MEDIA_URL + config.cover_image.name
                        destination2_folder = ikwen_settings.MEDIA_ROOT + AbstractConfig.COVER_UPLOAD_TO
                        if not os.path.exists(destination2_folder):
                            os.makedirs(destination2_folder)
                        destination2 = config.cover_image.path.replace(media_root, ikwen_settings.MEDIA_ROOT)
                        os.rename(destination, destination2)
                    cache.delete(service.id + ':config:')
                    cache.delete(service.id + ':config:default')
                    cache.delete(service.id + ':config:' + UMBRELLA)
                    config.save(using=UMBRELLA)
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
                    member.propagate_changes()
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
        service_id = kwargs['service_id']
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
        echo_balance, update = Balance.objects.using('wallets').get_or_create(service_id=srvce.id)
        context['srvce'] = srvce  # Service named srvce in context to avoid collision with service from template_context_processors
        context['support_code'] = support_code
        context['echo_balance'] = echo_balance
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context


class Configuration(TemplateView):
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
        service = get_service_instance()
        if getattr(settings, 'IS_IKWEN', False):
            service_id = kwargs.get('service_id')
            if service_id:
                service = get_object_or_404(Service, pk=service_id)
                context['service'] = service
                context['config'] = service.config

        form = ModelForm(instance=service.config)
        admin_form = helpers.AdminForm(form, list(config_admin.get_fieldsets(self.request)),
                                       config_admin.get_prepopulated_fields(self.request),
                                       config_admin.get_readonly_fields(self.request))
        context['model_admin_form'] = admin_form
        context['is_company'] = True
        context['img_upload_context'] = self.UPLOAD_CONTEXT
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        context['currency_list'] = Currency.objects.all().order_by('code')
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
        form = ModelForm(request.POST, request.FILES, instance=service.config)
        if form.is_valid():
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
            form.cleaned_data['company_name_slug'] = slugify(form.cleaned_data['company_name'])
            form.save()
            cache.delete(service.id + ':config:')
            cache.delete(service.id + ':config:default')
            cache.delete(service.id + ':config:' + UMBRELLA)
            service.config.save(using=UMBRELLA)
            messages.success(request, _("Configuration successfully updated."))
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
        suggested_operators = CROperatorProfile.objects.exclude(service__in=member_services).filter(is_active=True)
        suggestion_list = [op.service for op in suggested_operators.order_by('-id')[:9]]
        if join_service and join_service not in suggestion_list and join_service not in member_services:
            suggestion_list.insert(0, join_service)
        coupon_summary_list = member.couponsummary_set.filter(service__in=active_cr_services)
        event_list = ConsoleEvent.objects.filter(Q(member=member) | Q(group_id__in=member.group_fk_list) |
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
            queryset = ConsoleEvent.objects.exclude(event_type=type_access_request)\
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
        event = ConsoleEvent.objects.using(UMBRELLA).get(pk=event_id)
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
        invoice = Invoice.objects.using(UMBRELLA).get(pk=event.object_id)
    service_deployed = invoice.service
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
                'due_date': invoice.due_date,
                'show_pay_now': invoice.status != Invoice.PAID}
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
        service = get_service_instance()
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
        context['CRNCY'] = Currency.active.base()
        return context


class AdminHomeBase(TemplateView):

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        if action == 'update_domain':
            service = get_service_instance()
            new_domain = request.GET['new_domain']
            is_naked_domain = True if request.GET.get('is_naked_domain') else False
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
