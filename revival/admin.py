from django.contrib import admin


class ProfileTagAdmin(admin.ModelAdmin):
    fields = ('name', )
