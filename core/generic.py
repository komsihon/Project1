# -*- coding: utf-8 -*-
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, date

from django.conf import settings
from django.contrib import messages
from django.contrib.admin import helpers
from django.core.cache import cache
from django.core.files import File
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import get_model
from django.db.models.fields.files import ImageFieldFile
from django.forms.models import modelform_factory
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.generic.base import TemplateView
from django.views.generic.list import ListView
from django.forms.fields import DateField, DateTimeField
from import_export.formats.base_formats import XLS

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.core.models import Service, AbstractConfig
from ikwen.core.utils import get_service_instance, DefaultUploadBackend, generate_icons, get_model_admin_instance
from ikwen.revival.models import ProfileTag, Revival


class HybridListView(ListView):
    """
    Extension of the django builtin :class:`django.views.generic.ListView`. This view is Hybrid because it can
    render HTML or JSON results for Ajax calls.

    :attr:search_field: Name of the default field it uses to filter Ajax requests. Defaults to *name*
    :attr:ordering: Tuple of model fields used to order object list when page is rendered in HTML
    :attr:ajax_ordering: Tuple of model fields used to order results of Ajax requests. It is similar to ordering of
    django admin
    """
    page_size = int(getattr(settings, 'HYBRID_LIST_PAGE_SIZE', '50'))
    max_visible_page_count = 5
    search_field = 'name'
    ordering = ('-id', )
    list_filter = ()
    ajax_ordering = ('-id', )
    template_name = 'core/object_list_base.html'
    html_results_template_name = 'core/snippets/object_list_results.html'
    change_object_url_name = None
    show_import = False
    export_resource = None

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
        context[context_object_name] = queryset.order_by(*self.ordering)[:self.page_size]
        context['queryset'] = queryset
        context['page_size'] = self.page_size
        context['total_objects'] = self.get_queryset().count()
        context['filter'] = self.get_filter()
        model = self.get_queryset().model
        meta = model._meta
        context['verbose_name'] = meta.verbose_name
        context['verbose_name_plural'] = meta.verbose_name_plural
        try:
            context['has_is_active_field'] = True if model().is_active is not None else False
        except AttributeError:
            pass
        try:
            context['is_sortable'] = True if model().order_of_appearance is not None else False
        except AttributeError:
            pass
        if not self.change_object_url_name:
            self.change_object_url_name = '%s:change_%s' % (meta.app_label, meta.model_name)
        context['change_object_url_name'] = self.change_object_url_name
        context['html_results_template_name'] = self.html_results_template_name
        context['show_import'] = self.show_import
        context['show_export'] = self.export_resource is not None
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
            if self.request.GET.get('action') == 'export':
                return self.export(queryset)
            paginator = Paginator(queryset, self.page_size)
            page = self.request.GET.get('page')
            try:
                objects_page = paginator.page(page)
                page = int(page)
            except PageNotAnInteger:
                page = 1
                objects_page = paginator.page(1)
            except EmptyPage:
                page = paginator.num_pages
                objects_page = paginator.page(paginator.num_pages)
            context['q'] = self.request.GET.get('q')
            context['objects_page'] = objects_page
            min_page = page - (page % self.max_visible_page_count) + 1
            max_page = min_page + self.max_visible_page_count
            context['page_range'] = range(min_page, max_page + 1)
            if fmt == 'html_results':
                return render(self.request, self.html_results_template_name, context)
            else:
                return super(HybridListView, self).render_to_response(context, **response_kwargs)

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        model_name = request.GET.get('model_name')
        if model_name:
            model = get_model(*model_name.split('.'))
        elif self.model:
            model = self.model
        else:
            model = self.get_queryset().model
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
                    model._default_manager.filter(pk=object_id).update(order_of_appearance=order_of_appearance)
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
                if type(item) is tuple:
                    item_title = item[1]
                    item = item[0]
                else:
                    item_title = item
                elt = None
                choices = []
                is_date_filter = False
                try:
                    elt = self.get_queryset()[0].__getattribute__(item)
                except IndexError:
                    pass
                if isinstance(elt, datetime) or isinstance(elt, date):
                    now = datetime.now()
                    criterion = {item + '__gt': now}
                    has_future_dates = self.get_queryset().filter(**criterion).count() > 0
                    choices = [
                        ('__period__today', _("Today")),
                        ('__period__yesterday', _("Yesterday")),
                        ('__period__last_7_days', _("Last 7 days")),
                        ('__period__since_the_1st', _("Since the 1st")),
                    ]
                    if has_future_dates:
                        choices.extend([
                            ('__period__next_7_days', _("Next 7 days")),
                            ('__period__next_30_days', _("Next 30 days")),
                        ])
                    is_date_filter = True
                else:
                    item_values = set([obj.__getattribute__(item) for obj in self.get_queryset()])
                    item_values = list(sorted(item_values))
                    item_values = [val for val in item_values if val is not None]
                    if set(item_values) == {True, False}:
                        choices = [
                            ("__true__", _("Yes")),
                            ("__false__", _("No"))
                        ]
                    elif len(item_values) > 0:
                        obj = item_values[0]
                        if isinstance(obj, models.Model):
                            choices = [(obj.id, obj) for obj in item_values]
                        else:
                            choices = [(val, val) for val in item_values]
                options.append({
                    'title': item_title.capitalize(),
                    'parameter_name': item,
                    'choices': choices,
                    'is_date_filter': is_date_filter
                })
        return options

    def get_export_filename(self, file_format):
        date_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        if self.model:
            model = self.model
        else:
            model = self.get_queryset().model
        filename = "%s_%s.%s" % (model.__name__, date_str, file_format.get_extension())
        return filename

    def export(self, queryset):
        file_format = XLS()
        data = self.export_resource().export(queryset)
        export_data = file_format.export_data(data)
        content_type = file_format.get_content_type()
        try:
            response = HttpResponse(export_data, content_type=content_type)
        except TypeError:
            response = HttpResponse(export_data, mimetype=content_type)
        response['Content-Disposition'] = 'attachment; filename=%s' % self.get_export_filename(file_format)
        return response

    def filter_queryset(self, queryset):
        for item in self.list_filter:
            if callable(item):
                filter = item()
                queryset = filter.queryset(self.request, queryset)
            else:
                if type(item) is tuple:
                    item = item[0]
                kwargs = {}
                value = self.request.GET.get(item)
                if value:
                    if value == '__true__':
                        value = True
                    elif value == '__false__':
                        value = False
                    elif value.startswith('__period__'):
                        now = datetime.now()
                        start_date, end_date = None, now
                        value = value.replace('__period__', '')
                        if value == 'today':
                            start_date = datetime(now.year, now.month, now.day, 0, 0, 0)
                        elif value == 'yesterday':
                            yst = now - timedelta(days=1)
                            start_date = datetime(yst.year, yst.month, yst.day, 0, 0, 0)
                            end_date = datetime(yst.year, yst.month, yst.day, 23, 59, 59)
                        elif value == 'last_7_days':
                            b = now - timedelta(days=7)
                            start_date = datetime(b.year, b.month, b.day, 0, 0, 0)
                        elif value == 'since_the_1st':
                            start_date = datetime(now.year, now.month, 1, 0, 0, 0)
                        elif value == 'next_7_days':
                            dl = now + timedelta(days=7)
                            start_date = datetime(now.year, now.month, now.day, 0, 0, 0)
                            end_date = datetime(dl.year, dl.month, dl.day, 23, 59, 59)
                        elif value == 'next_30_days':
                            dl = now + timedelta(days=30)
                            start_date = datetime(now.year, now.month, now.day, 0, 0, 0)
                            end_date = datetime(dl.year, dl.month, dl.day, 23, 59, 59)
                        else:
                            start_date, end_date = value.split(',')
                            start_date += ' 00:00:00'
                            end_date += ' 23:59:59'
                        if start_date:
                            item = item + '__range'
                            value = (start_date, end_date)
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
    label_field = None

    def get_model(self):
        if isinstance(self.model, basestring):
            return get_model(*self.model.split('.'))
        else:
            return self.model

    def get_model_admin(self):
        if isinstance(self.model_admin, basestring):
            return import_by_path(self.model_admin)
        else:
            return self.model_admin

    def get_object(self, **kwargs):
        object_id = kwargs.get('object_id')  # May be overridden with the one from GET data
        object_id = self.request.GET.get('object_id', object_id)
        if object_id:
            model = self.get_model()
            return get_object_or_404(model, pk=object_id)

    def get_model_form(self, obj):
        model = self.get_model()
        model_admin = self.get_model_admin()
        ModelForm = modelform_factory(model, fields=model_admin.fields)
        if obj:
            form = ModelForm(instance=obj)
        else:
            form = ModelForm(instance=model())
        return form

    def get_context_data(self, **kwargs):
        context = super(ChangeObjectBase, self).get_context_data(**kwargs)
        model = self.get_model()
        model_admin = self.get_model_admin()
        model_admin = get_model_admin_instance(model, model_admin)
        obj = self.get_object(**kwargs)
        form = self.get_model_form(obj)
        obj_form = helpers.AdminForm(form, list(model_admin.get_fieldsets(self.request, obj)),
                                     model_admin.get_prepopulated_fields(self.request, obj),
                                     model_admin.get_readonly_fields(self.request, obj))
        model_obj = model()
        date_field_list = []
        datetime_field_list = []
        img_field_list = []
        i = 0
        for key in model_obj.__dict__.keys():
            field = model_obj.__getattribute__(key)
            if isinstance(field, ImageFieldFile):
                if not field.field.editable:
                    continue
                img_obj = {
                    'image': field,
                    'field': key,
                    'help_text': field.field.help_text,
                    'counter': i
                }
                img_field_list.append(img_obj)
                i += 1
            field = form.base_fields.get(key)
            if isinstance(field, DateField):
                date_field_list.append(key)
            if isinstance(field, DateTimeField):
                datetime_field_list.append(key)

        context[self.context_object_name] = obj
        context['obj'] = obj  # Base template recognize the context object only with the name 'obj'
        context['model'] = model_obj._meta.app_label + '.' + model_obj._meta.model_name
        context['verbose_name'] = model_obj._meta.verbose_name
        context['verbose_name_plural'] = model_obj._meta.verbose_name_plural
        context['object_list_url'] = self.get_object_list_url(self.request, obj, **kwargs)
        context['model_admin_form'] = obj_form
        context['label_field'] = self.label_field if self.label_field else 'name'
        context['date_field_list'] = date_field_list
        context['datetime_field_list'] = datetime_field_list
        context['img_field_list'] = img_field_list
        return context

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        if action == 'delete_image':
            model = self.get_model()
            object_id = kwargs.get('object_id')
            obj = get_object_or_404(model, pk=object_id)
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
        model = self.get_model()
        model_admin = self.get_model_admin()
        object_admin = get_model_admin_instance(model, model_admin)
        object_id = kwargs.get('object_id')
        object_id = request.POST.get('object_id', object_id)
        before = None
        if object_id:
            obj = self.get_object(**kwargs)
            before = deepcopy(obj)
        else:
            obj = model()
        model_form = object_admin.get_form(request)
        form = model_form(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
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
                messages.success(request, obj._meta.verbose_name.capitalize() + ' <strong>' + str(obj).decode('utf8') + '</strong> ' + _('successfully updated').decode('utf8'))
            else:
                messages.success(request, obj._meta.verbose_name.capitalize() + ' <strong>' + str(obj).decode('utf8') + '</strong> ' + _('successfully created').decode('utf8'))
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['errors'] = form.errors
            return render(request, self.template_name, context)

    def get_object_list_url(self, request, obj, *args, **kwargs):
        model = self.get_model()
        if self.object_list_url:
            url = reverse(self.object_list_url)
        else:
            try:
                if obj is None:
                    obj = model()
                url = reverse('%s:%s_list' % (obj._meta.app_label, obj._meta.model_name))
            except:
                url = request.META['HTTP_REFERER']
        return url

    def get_change_object_url(self, request, obj, *args, **kwargs):
        model = self.get_model()
        if self.change_object_url:
            url = reverse(self.change_object_url, args=(obj.id, ))
        else:
            try:
                if obj is None:
                    obj = model()
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


class CustomizationImageUploadBackend(DefaultUploadBackend):
    """
    Ajax upload handler for ikwen cover and profile images
    """
    def upload_complete(self, request, filename, *args, **kwargs):
        import os
        from ikwen.conf import settings as ikwen_settings
        from ikwen.core.views import Configuration
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
                        generate_icons(src)
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
