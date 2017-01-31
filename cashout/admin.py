# -*- coding: utf-8 -*-
from djangotoolbox.admin import admin
from ikwen.cashout.models import CashOutMethod, CashOutRequest

__author__ = 'Kom Sihon'


class CashOutMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'image', 'is_active', )
    search_fields = ('name', )
    ordering = ('-id', )


class CashOutRequestAdmin(admin.ModelAdmin):
    list_display = ('service', 'member', 'amount', 'method', 'account_number', 'created_on', )
    search_fields = ('member_name', )
    list_filter = ('created_on', )
    ordering = ('-id', )
    readonly_fields = ('service_id', 'member_id', 'amount', 'status', 'method', 'account_number', 'name', )


admin.site.register(CashOutMethod, CashOutMethodAdmin)
admin.site.register(CashOutRequest, CashOutRequestAdmin)
