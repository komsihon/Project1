# -*- coding: utf-8 -*-
import os
import subprocess
from threading import Thread

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http.response import HttpResponseForbidden
from djangotoolbox.admin import admin
from ikwen.core.utils import generate_icons, get_mail_content, get_service_instance

from ikwen.core.models import RETAIL_APP_SLUG, Module

from ikwen.core.models import Application, Config, Service, ConsoleEventType, XEmailObject
from django.utils.translation import gettext_lazy as _

import logging
logger = logging.getLogger('ikwen')


class CustomBaseAdmin(admin.ModelAdmin):

    class Media:
        if not getattr(settings, 'IS_IKWEN', False):
            css = {
                "all": ("ikwen/admin/css/base.css", "ikwen/admin/css/changelists.css", "ikwen/admin/css/dashboard.css",
                        "ikwen/admin/css/forms.css", "ikwen/admin/css/ie.css", "ikwen/admin/css/login.css",
                        "ikwen/admin/css/widget.css", "ikwen/font-awesome/css/font-awesome.min.css",
                        "ikwen/css/flatly.bootstrap.min.css", "ikwen/css/grids.css",
                        "ikwen/billing/admin/css/custom.css",)
            }
        js = ("ikwen/js/jquery-1.12.4.min.js", "ikwen/js/jquery.autocomplete.min.js",
              "ikwen/billing/admin/js/custom.js",)


class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'logo', 'url', 'created_on', 'operators_count', )
    search_fields = ('name', )
    ordering = ('-id', '-operators_count', )
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ('total_turnover', 'total_earnings', 'total_deployment_earnings', 'total_transaction_earnings',
                       'total_invoice_earnings', 'total_custom_service_earnings', 'total_deployment_count', 'total_transaction_count',
                       'total_invoice_count', 'total_custom_service_count', 'total_cash_out', 'total_cash_out_count')
    save_on_top = True

    def save_model(self, request, obj, form, change):
        super(ApplicationAdmin, self).save_model(request, obj, form, change)
        try:
            media_root = getattr(settings, 'MEDIA_ROOT')
            if os.path.exists(obj.logo.path):
                output_folder = 'ikwen/favicons/%s/' % obj.slug
                if not os.path.exists(media_root + output_folder):
                    os.makedirs(media_root + output_folder)
                generate_icons(obj.logo.path, output_folder)
                filename = obj.logo.name.split('/')[-1]
                dst = obj.logo.name.replace(filename, obj.slug + '-logo.png')
                os.rename(obj.logo.path, media_root + dst)
                obj.logo = dst
                obj.save()
        except ValueError:
            pass


class ServiceAdmin(admin.ModelAdmin):
    list_display = ('project_name', 'app', 'member', 'monthly_cost', 'expiry', 'since', 'version', 'status', )
    list_select_related = ('app', 'member', )
    raw_id_fields = ('member', )
    search_fields = ('project_name', )
    list_filter = ('app', 'version', 'expiry', 'since', 'status', 'is_public', 'is_pwa_ready',)
    ordering = ('-id', )
    readonly_fields = ('retailer', 'since',
                       'total_turnover', 'total_earnings', 'total_transaction_earnings', 'total_custom_service_earnings',
                       'total_invoice_earnings', 'total_transaction_count', 'total_cash_out',
                       'total_invoice_count', 'total_custom_service_count', 'total_cash_out_count')
    actions = ['reload_projects', 'reload_settings']

    def save_model(self, request, obj, form, change):
        if obj.app.slug == RETAIL_APP_SLUG and not change:
            from ikwen.partnership.cloud_setup import deploy
            member = request.user
            project_name = request.POST['project_name']
            monthly_cost = request.POST['monthly_cost']
            billing_cycle = request.POST['billing_cycle']
            domain = request.POST['domain']
            is_pro_version = True if request.POST.get('is_pro_version') else False
            deploy(obj.app, member, project_name, monthly_cost, billing_cycle, domain, is_pro_version)
        else:
            try:
                before = Service.objects.get(pk=obj.id)
            except Service.DoesNotExist:
                before = None
            super(ServiceAdmin, self).save_model(request, obj, form, change)
            if before and before.domain != obj.domain:
                service = get_service_instance()
                new_domain = obj.domain
                obj.domain = before.domain
                is_naked_domain = True if request.POST['domain_type'] == Service.MAIN else False
                obj.update_domain(new_domain, is_naked_domain)
                obj.reload_settings(obj.settings_template, is_naked_domain=is_naked_domain)
                subject = _("Your domain name was changed")
                html_content = get_mail_content(subject, template_name='core/mails/domain_updated.html',
                                                extra_context={'website': obj})
                sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
                msg = EmailMessage(subject, html_content, sender, [obj.member.email])
                msg.content_subtype = "html"
                msg.bcc = ['contact@ikwen.com']
                Thread(target=lambda m: m.send(), args=(msg,)).start()

    def reload_projects(self, request, queryset):
        failed = []
        for service in queryset:
            try:
                subprocess.call(['touch', '%s/conf/wsgi.py' % service.home_folder])
            except:
                failed.append(service.project_name_slug)
                msg = "Failed to reload project %s" % service.project_name_slug
                logger.error(msg, exc_info=True)
        if len(failed) == 0:
            messages.success(request, "Projects successfully reloaded.")
        else:
            if len(failed) == 1:
                messages.error(request, "%s project failed to reload. Check error log" % failed[0])
            else:
                msg = "%s and %d other project failed to reload. Check error log" % (failed[0], len(failed) - 1)
                messages.error(request, msg)

    def reload_settings(self, request, queryset):
        failed = []
        for service in queryset:
            try:
                service.reload_settings()
            except:
                failed.append(service.project_name_slug)
                msg = "Failed to reload settings for project %s" % service.project_name_slug
                logger.error(msg, exc_info=True)
        if len(failed) == 0:
            messages.success(request, "Projects settings successfully reloaded.")
        else:
            if len(failed) == 1:
                messages.error(request, "%s project settings failed to reload. Check error log" % failed[0])
            else:
                msg = "%s and %d other project settings failed to reload. Check error log" % (failed[0], len(failed) - 1)
                messages.error(request, msg)


if getattr(settings, 'IS_IKWEN', False):
    _list_display = ('service', 'company_name', 'short_description', 'contact_email', 'contact_phone')
    _general_fields = ('service', 'company_name', 'short_description', 'slogan', 'description',
                       'currency_code', 'currency_symbol', 'is_pro_version', 'is_standalone')
else:
    _list_display = ('company_name', 'short_description', 'contact_email', 'contact_phone')
    _general_fields = ('company_name', 'short_description', 'slogan',
                       'description', 'currency_code', 'currency_symbol')


class ConfigAdmin(admin.ModelAdmin):
    list_display = _list_display
    fieldsets = (
        (_('General'), {'fields': _general_fields}),
        (_('Branding'), {'fields': ('brand_color',)}),
        (_('Address & Contact'), {'fields': ('contact_email', 'contact_phone', 'address', 'country', 'city')}),
        (_('Social'), {'fields': ('facebook_link', 'twitter_link', 'instagram_link', 'linkedin_link', )}),
        (_('Mailing'), {'fields': ('welcome_message', 'signature', )}),
        (_('External scripts'), {'fields': ('scripts', )}),
    )
    raw_id_fields = ('service', )
    list_filter = ('company_name', 'contact_email', )
    save_on_top = True

    def delete_model(self, request, obj):
        if Config.objects.all().count() == 1:
            return HttpResponseForbidden("You are not allowed to delete Configuration of the platform")
        super(ConfigAdmin, self).delete_model(request, obj)

    def get_queryset(self, request):
        try:
            from daraja.models import DARAJA
            app = Application.objects.get(slug=DARAJA)
            dara_service_id_list = [service.id for service in Service.objects.filter(app=app)]
            return Config.objects.exclude(service__in=dara_service_id_list)
        except:
            pass
        return super(ConfigAdmin, self).get_queryset(request)

    def get_readonly_fields(self, request, obj=None):
        if not request.user.is_superuser:
            return ('service',)
        return ()


class ConsoleEventTypeAdmin(admin.ModelAdmin):
    list_display = ('app', 'codename', 'title', 'renderer', 'min_height',)
    search_fields = ('codename', 'title',)
    list_filter = ('app',)


class ModuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'is_pro', 'url_name', 'homepage_section_renderer',)
    search_fields = ('name', )
    if getattr(settings, 'IS_IKWEN', False):
        fields = ('name', 'slug', 'description', 'url_name', 'homepage_section_renderer', 'is_pro')
    else:
        fields = ('title', 'content', 'is_active', )


class XEmailObjectAdmin(admin.ModelAdmin):
    list_display = ('to', 'subject', 'body', 'created_on')


if getattr(settings, 'IS_UMBRELLA', False):
    admin.site.register(Application, ApplicationAdmin)
    admin.site.register(Config, ConfigAdmin)
    admin.site.register(Service, ServiceAdmin)
    admin.site.register(ConsoleEventType, ConsoleEventTypeAdmin)
    admin.site.register(Module, ModuleAdmin)
# admin.site.register(Country, CountryAdmin)
