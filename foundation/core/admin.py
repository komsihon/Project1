# -*- coding: utf-8 -*-
from django.http.response import HttpResponseForbidden
from djangotoolbox.admin import admin
from ikwen.foundation.core.models import Application, Config, Service
from django.utils.translation import gettext as _

__author__ = 'Kom Sihon'


class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'logo', 'url', 'created_on', 'operators_count', )
    search_fields = ('name', )
    ordering = ('-id', '-operators_count', )
    prepopulated_fields = {"slug": ("name",)}


class ServiceAdmin(admin.ModelAdmin):
    list_display = ('project_name', 'app', 'member', 'monthly_cost', 'expiry', 'since', 'version', 'status', )
    raw_id_fields = ('member', )
    search_fields = ('project_name', )
    list_filter = ('app', 'version', 'expiry', 'since', 'status', )
    ordering = ('-id', )


class ConfigAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'short_description', 'contact_email', 'contact_phone')
    fieldsets = (
        (_('General'), {'fields': ('company_name', 'short_description', )}),
        (_('Address & Contact'), {'fields': ('contact_email', 'contact_phone', 'address', 'country', 'city')}),
        (_('Mailing'), {'fields': ('welcome_message', 'signature', )}),
        # (_('SMS'), {'fields': ('sms_sending_method', 'sms_api_script_url', 'sms_api_username', 'sms_api_password', )}),
        (_('Social'), {'fields': ('facebook_link', 'twitter_link', 'google_plus_link', 'instagram_link', 'linkedin_link', )}),
        # (_('PayPal'), {'fields': ('paypal_user', 'paypal_password', 'paypal_api_signature', )}),
        # (_('Scripts'), {'fields': ('google_analytics', )}),
    )
    save_on_top = True

    def delete_model(self, request, obj):
        if Config.objects.all().count() == 1:
            return HttpResponseForbidden("You are not allowed to delete Configuration of the platform")
        super(ConfigAdmin, self).delete_model(request, obj)

admin.site.register(Application, ApplicationAdmin)
admin.site.register(Config, ConfigAdmin)
admin.site.register(Service, ServiceAdmin)
# admin.site.register(Country, CountryAdmin)
