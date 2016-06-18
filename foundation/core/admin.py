# -*- coding: utf-8 -*-
from django import forms
from django.http.response import HttpResponseForbidden
from djangotoolbox.admin import admin
from ikwen.foundation.core.backends import UMBRELLA, ARCH_EMAIL
from permission_backend_nonrel.admin import NonrelPermissionCustomUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from ikwen.foundation.core.models import Member, Application, Config, Service
from django.utils.translation import gettext as _
from django.conf import settings

__author__ = 'Kom Sihon'


class MemberCreationForm(forms.ModelForm):
    """A form for creating new users. Includes all the required
    fields, plus a repeated password."""
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Password confirmation', widget=forms.PasswordInput)

    class Meta:
        model = Member
        fields = ('email', 'first_name', 'last_name')

    def clean_password2(self):
        # Check that the two password entries match
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2

    def save(self, commit=True):
        # Save the provided password in hashed format
        member = super(MemberCreationForm, self).save(commit=False)
        member.set_password(self.cleaned_data["password1"])
        if commit:
           member.save()
        return member


class MemberChangeForm(forms.ModelForm):
    """A form for updating users. Includes all the fields on
    the user, but replaces the password field with admin's
    password hash display field.
    """
    password = ReadOnlyPasswordHashField()

    class Meta:
        model = Member

    def clean_password(self):
        # Regardless of what the user provides, return the initial value.
        # This is done here, rather than on the field, because the
        # field does not have access to the initial value
        return self.initial["password"]


class MemberAdmin(NonrelPermissionCustomUserAdmin):
    # The forms to add and change user instances
    # form = MemberChangeForm
    add_form = MemberCreationForm
    # The fields to be used in displaying the User model.
    # These override the definitions on the core UserAdmin
    # that reference specific fields on auth.User.
    list_display = ('username', 'email', 'is_active', 'is_staff', 'is_iao')
    list_filter = ('is_staff', 'is_iao', 'date_joined', )
    fieldsets = (
        (None, {'fields': ('username', 'phone', 'email')}),
        ('Personal info', {'fields': ('first_name', 'last_name', )}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'groups', 'user_permissions', )}),
        ('Important dates', {'fields': ('date_joined', 'last_login',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2')
            }
        ),
    )
    search_fields = ('username', 'email', 'phone', 'first_name', 'last_name')
    readonly_fields = ('username', 'email', 'password', 'phone', 'date_joined', 'last_login', )
    ordering = ('-date_joined', 'email',)
    filter_horizontal = ('groups', 'user_permissions',)

    def get_queryset(self, request):
        databases = getattr(settings, 'DATABASES')
        if databases.get(UMBRELLA):  # Means we are not in the main application
            qs = Member.objects.exclude(email=ARCH_EMAIL)
            ordering = self.get_ordering(request)
            if ordering:
                qs = qs.order_by(*ordering)
            return qs
        else:
            return super(MemberAdmin, self).get_queryset(request)


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
    list_display = ('company_name', 'slogan', 'contact_email', 'contact_phone')
    fieldsets = (
        (_('Branding'), {'fields': ('company_name', 'slogan', 'logo', )}),
        (_('Address & Contact'), {'fields': ('contact_email', 'contact_phone', 'address', 'country', 'city')}),
        (_('Mailing'), {'fields': ('welcome_message', 'mail_banner', 'signature', )}),
        (_('SMS'), {'fields': ('sms_sending_method', 'sms_api_script_url', 'sms_api_username', 'sms_api_password', )}),
        (_('Social'), {'fields': ('facebook_link', 'twitter_link', 'google_plus_link', 'instagram_link', 'linkedin_link', )}),
        (_('PayPal'), {'fields': ('paypal_user', 'paypal_password', 'paypal_api_signature', )}),
        (_('Scripts'), {'fields': ('google_analytics', )}),
    )
    save_on_top = True

    def delete_model(self, request, obj):
        if Config.objects.all().count() == 1:
            return HttpResponseForbidden("You are not allowed to delete Configuration of the platform")
        super(ConfigAdmin, self).delete_model(request, obj)

admin.site.register(Member, MemberAdmin)
admin.site.register(Application, ApplicationAdmin)
admin.site.register(Config, ConfigAdmin)
admin.site.register(Service, ServiceAdmin)
# admin.site.register(Country, CountryAdmin)
