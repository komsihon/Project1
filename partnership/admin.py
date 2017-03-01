from django.conf import settings
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from ikwen.core.models import Application

from ikwen.core.utils import get_service_instance, add_database_to_settings

from ikwen.partnership.models import PartnerProfile, ApplicationRetailConfig

if getattr(settings, 'IS_IKWEN', False):
    _fieldsets = [
        (_('Company'), {'fields': ('service', 'company_name', 'short_description', 'slogan', 'description')}),
        (_('Business'), {'fields': ('currency_code', 'currency_symbol',
                                    'cash_out_min', 'is_certified', 'is_pro_version')}),
        (_('SMS'), {'fields': ('sms_api_script_url', 'sms_api_username', 'sms_api_password', )}),
        (_('Mailing'), {'fields': ('welcome_message', 'signature',)})
    ]
    _readonly_fields = ('service', 'api_signature', )
else:
    service = get_service_instance()
    config = service.config
    _readonly_fields = ('api_signature', 'is_certified',)
    _fieldsets = [
        (_('Company'), {'fields': ('company_name', 'short_description', 'slogan', 'description')}),
        (_('Address & Contact'), {'fields': ('contact_email', 'contact_phone', 'address', 'country', 'city')}),
        (_('Mailing'), {'fields': ('welcome_message', 'signature', )}),
    ]


class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ('service', 'company_name', 'short_description', 'contact_email', 'contact_phone')
    fieldsets = _fieldsets
    readonly_fields = _readonly_fields
    list_filter = ('company_name', 'contact_email', )
    save_on_top = True

    def delete_model(self, request, obj):
        self.message_user(request, "You are not allowed to delete Configuration of the platform")


class ApplicationRetailConfigAdmin(admin.ModelAdmin):
    list_display = ('partner', 'app', 'ikwen_monthly_cost', 'ikwen_tx_share_rate')
    raw_id_fields = ('partner',)
    list_filter = ('partner', )
    readonly_fields = ('created_on', 'updated_on')
    save_on_top = True

    def save_model(self, request, obj, form, change):
        super(ApplicationRetailConfigAdmin, self).save_model(request, obj, form, change)
        if obj.partner:
            db = obj.partner.database
            add_database_to_settings(db)
            try:
                Application.objects.using(db).get(pk=obj.app.id)
            except Application.DoesNotExist:
                obj.app.save(using=db)


if getattr(settings, 'IS_UMBRELLA', False):
    admin.site.register(PartnerProfile, PartnerProfileAdmin)
    admin.site.register(ApplicationRetailConfig, ApplicationRetailConfigAdmin)
