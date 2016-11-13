# -*- coding: utf-8 -*-
from djangotoolbox.admin import admin

__author__ = 'Kom Sihon'


class FlatPageAdmin(admin.ModelAdmin):
    fields = ('title', 'content', 'registration_required', )
# admin.site.register(Country, CountryAdmin)
