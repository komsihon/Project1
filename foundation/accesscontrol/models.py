# -*- coding: utf-8 -*-
from django.conf import settings
from django.contrib.auth.models import BaseUserManager, AbstractUser, Permission
from django.db import models
from django.utils.translation import gettext as _
from djangotoolbox.fields import ListField, EmbeddedModelField

from ikwen.foundation.core.models import Service
from ikwen.foundation.core.utils import to_dict


class MemberManager(BaseUserManager):

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('Username must be set')
        member = self.model(username=username, **extra_fields)
        service_id = getattr(settings, 'IKWEN_SERVICE_ID', None)
        debug = getattr(settings, 'DEBUG', False)
        if not debug:
            if service_id:
                member.entry_service = Service.objects.get(pk=service_id)
        member.set_password(password)
        member.save()
        return member

    def create_superuser(self, email, password, **extra_fields):
        member = self.create_user(email, password, **extra_fields)
        member.is_staff = True
        member.is_superuser = True
        member.save()
        return member


class Member(AbstractUser):
    MALE = 'Male'
    FEMALE = 'Female'
    # TODO: Create and set this field in collection ikwen_member in database itself
    full_name = models.CharField(max_length=150, db_index=True)
    phone = models.CharField(max_length=18, unique=True, blank=True)
    gender = models.CharField(max_length=15, blank=True)
    dob = models.DateField(blank=True, null=True)
    entry_service = models.ForeignKey(Service, blank=True, null=True, related_name='members',
                                      help_text=_("Service where user registered for the first time on ikwen"))
    is_iao = models.BooleanField('IAO', default=False,
                                 help_text=_('Designates whether this user is an '
                                             '<strong>IAO</strong> (Ikwen Application Operator).'))
    collaborates_on = ListField(EmbeddedModelField('Service'), editable=False,
                                help_text="Services on which member collaborates without being the IAO.")
    phone_verified = models.BooleanField(_('Phone verification status'), default=False,
                                         help_text=_('Designates whether this phone number has been '
                                                     'verified by sending a confirmation code by SMS.'))
    business_notices = models.IntegerField(default=0,
                                           help_text="Number of pending business notifications.")
    personal_notices = models.IntegerField(default=0,
                                           help_text="Number of pending personal notifications.")

    objects = MemberManager()

    class Meta:
        db_table = 'ikwen_member'

    def __unicode__(self):
        return self.get_username()

    def _get_display_joined(self):
        return '%02d/%02d/%d %02d:%02d' % (self.date_joined.day, self.date_joined.month, self.date_joined.year,
                                           self.date_joined.hour, self.date_joined.minute)
    display_date_joined = property(_get_display_joined)

    def save(self, *args, **kwargs):
        from ikwen.foundation.core.backends import UMBRELLA
        self.full_name = self.get_full_name()
        using = 'default'
        if kwargs.get('using'):
            using = kwargs['using']
            del(kwargs['using'])
        databases = getattr(settings, 'DATABASES')
        if databases.get(UMBRELLA):
            member = Member.objects.using(UMBRELLA).get(pk=self.id) if self.id else None
            new_is_staff_value = self.is_staff
            umbrella_is_staff_value = member.is_staff if member else False
            self.is_staff = umbrella_is_staff_value  # staff status should not take effect in UMBRELLA database
            super(Member, self).save(using=UMBRELLA, *args, **kwargs)
            self.is_staff = new_is_staff_value
        super(Member, self).save(using=using, *args, **kwargs)  # Now copy to the application default database

    def get_apps_operated(self):
        return list(Service.objects.filter(member=self))

    def to_dict(self):
        var = to_dict(self)
        var['date_joined'] = self.display_date_joined
        del(var['last_login'])
        del(var['password'])
        del(var['is_superuser'])
        del(var['is_staff'])
        del(var['is_active'])
        return var