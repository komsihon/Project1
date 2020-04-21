# -*- coding: utf-8 -*-
__author__ = 'Kom Sihon'

from django import forms
from django.conf import settings
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.models import Permission, Group
from djangotoolbox.admin import admin
from django.utils.translation import ugettext as _
from import_export import resources, fields
from permission_backend_nonrel.admin import NonrelPermissionCustomUserAdmin

from ikwen.core.utils import get_service_instance
from ikwen.accesscontrol.backends import ARCH_EMAIL
from ikwen.accesscontrol.models import Member
from permission_backend_nonrel.models import UserPermissionList


service = get_service_instance()


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
        # field does not have accesscontrol to the initial value
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
        if not getattr(settings, 'IS_IKWEN', False):  # Means we are not in the main application
            qs = Member.objects.exclude(email=ARCH_EMAIL)
            ordering = self.get_ordering(request)
            if ordering:
                qs = qs.order_by(*ordering)
            return qs
        else:
            return super(MemberAdmin, self).get_queryset(request)


class MemberResource(resources.ModelResource):
    registration = fields.Field(column_name=_('Registration'))
    name = fields.Field(column_name=_('Name'))
    gender = fields.Field(column_name=_('Gender'))
    email = fields.Field(column_name=_('Email'))
    phone = fields.Field(column_name=_('Phone'))
    if service.config.register_with_dob:
        dob = fields.Field(column_name=_('Birthday'))
    profiles = fields.Field(column_name=_('Profiles'))
    preferences = fields.Field(column_name=_('Preferences'))

    class Meta:
        model = UserPermissionList
        if service.config.register_with_dob:
            fields = ('registration', 'name', 'gender', 'email', 'phone', 'dob', 'profiles', 'preferences')
            export_order = ('registration', 'name', 'gender', 'email', 'dob', 'phone', 'profiles', 'preferences')
        else:
            fields = ('registration', 'name', 'gender', 'email', 'phone', 'profiles', 'preferences')
            export_order = ('registration', 'name', 'gender', 'email', 'phone', 'profiles', 'preferences')

    def dehydrate_registration(self, obj):
        return obj.user.date_joined.strftime('%y-%m-%d %H:%M')

    def dehydrate_name(self, obj):
        return obj.user.full_name

    def dehydrate_gender(self, obj):
        try:
            return _(obj.user.gender)
        except:
            return '---'

    def dehydrate_email(self, obj):
        return obj.user.email

    def dehydrate_phone(self, obj):
        return obj.user.phone

    def dehydrate_dob(self, obj):
        try:
            return obj.user.dob.strftime('%y-%m-%d')
        except:
            return '---'

    def dehydrate_profiles(self, obj):
        profile_tag_list = [tag.name for tag in obj.user.profile_tag_list]
        return ", ".join(profile_tag_list)

    def dehydrate_preferences(self, obj):
        preference_list = [tag.name for tag in obj.user.preference_list]
        return ", ".join(preference_list)


if getattr(settings, 'IS_UMBRELLA', False):
    admin.site.register(Member, MemberAdmin)
elif not getattr(settings, 'IS_IKWEN', False):
    try:
        admin.site.unregister(Group)
    except NotRegistered:
        pass
    try:
        admin.site.unregister(Permission)
    except NotRegistered:
        pass
