# -*- coding: utf-8 -*-
from django.conf import settings
from django.contrib.auth.models import BaseUserManager, AbstractUser
from django.core.urlresolvers import reverse
from django.db import models
from django.utils.translation import gettext as _
from django_mongodb_engine.contrib import RawQueryMixin
from djangotoolbox.fields import ListField, EmbeddedModelField
from ikwen.foundation.accesscontrol.templatetags.auth_tokens import ikwenize
from permission_backend_nonrel.models import UserPermissionList

from ikwen.foundation.core.fields import MultiImageField

from ikwen.foundation.core.models import Service, Model
from ikwen.foundation.core.utils import to_dict, get_service_instance


class MemberManager(BaseUserManager, RawQueryMixin):

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('Username must be set')
        member = self.model(username=username, **extra_fields)
        member.full_name = u'%s %s' % (member.first_name.split(' ')[0], member.last_name.split(' ')[0])
        service_id = getattr(settings, 'IKWEN_SERVICE_ID', None)
        debug = getattr(settings, 'DEBUG', False)
        if not debug:
            if service_id:
                service = get_service_instance()
                member.entry_service = service
                member.customer_on.append(service)
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
    AVATAR = settings.STATIC_URL + 'ikwen/img/login-avatar.jpg'
    PROFILE_UPLOAD_TO = 'ikwen/members/profile_photos'
    COVER_UPLOAD_TO = 'ikwen/members/cover_images'
    MALE = 'Male'
    FEMALE = 'Female'
    # TODO: Create and set field full_name in collection ikwen_member in database itself
    full_name = models.CharField(max_length=150, db_index=True)
    phone = models.CharField(max_length=18, unique=True, blank=True)
    gender = models.CharField(max_length=15, blank=True)
    dob = models.DateField(blank=True, null=True)
    photo = MultiImageField(upload_to=PROFILE_UPLOAD_TO, blank=True, null=True)
    cover_image = models.ImageField(upload_to=COVER_UPLOAD_TO, blank=True, null=True)
    entry_service = models.ForeignKey(Service, blank=True, null=True, related_name='+',
                                      help_text=_("Service where user registered for the first time on ikwen"))
    is_iao = models.BooleanField('IAO', default=False,
                                 help_text=_('Designates whether this user is an '
                                             '<strong>IAO</strong> (Ikwen Application Operator).'))
    collaborates_on = ListField(EmbeddedModelField('core.Service'), editable=False,
                                help_text="Services on which member collaborates being the IAO or no.")
    customer_on = ListField(EmbeddedModelField('core.Service'), editable=False,
                            help_text="Services on which member was granted customer access.")
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

    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name.split(' ')[0]

    def _get_display_joined(self):
        return '%02d/%02d/%d %02d:%02d' % (self.date_joined.day, self.date_joined.month, self.date_joined.year,
                                           self.date_joined.hour, self.date_joined.minute)
    display_date_joined = property(_get_display_joined)

    def save(self, *args, **kwargs):
        from ikwen.foundation.accesscontrol.backends import UMBRELLA
        using = 'default'
        if kwargs.get('using'):
            using = kwargs['using']
            del(kwargs['using'])
        if not getattr(settings, 'IS_IKWEN', False):
            member = Member.objects.using(UMBRELLA).get(pk=self.id) if self.id else None
            new_is_staff_value = self.is_staff
            umbrella_is_staff_value = member.is_staff if member else False
            self.is_staff = umbrella_is_staff_value  # staff status should not take effect in UMBRELLA database
            super(Member, self).save(using=UMBRELLA, *args, **kwargs)
            self.is_staff = new_is_staff_value
        super(Member, self).save(using=using, *args, **kwargs)  # Now copy to the application default database

    def get_apps_operated(self):
        return list(Service.objects.filter(member=self))

    def get_status(self):
        if self.is_active:
            return 'Active'
        return 'Blocked'

    def get_notice_count(self):
        return self.business_notices + self.personal_notices

    def to_dict(self):
        var = to_dict(self)
        var['date_joined'] = self.display_date_joined
        var['status'] = self.get_status()
        var['photo'] = self.photo.small_url if self.photo.name else Member.AVATAR
        url = reverse('ikwen:profile', args=(self.id, ))
        var['url'] = ikwenize(url)
        try:
            var['permissions'] = ','.join(UserPermissionList.objects.get(user=self).permission_fk_list)
        except UserPermissionList.DoesNotExist:
            var['permissions'] = ''
        del(var['collaborates_on'])
        del(var['customer_on'])
        del(var['password'])
        del(var['is_superuser'])
        del(var['is_staff'])
        del(var['is_active'])
        return var


class OfficialIdentityDocument(Model):
    member = models.ForeignKey(Member, db_index=True)
    number = models.CharField(max_length=100, db_index=True)
    issue = models.DateField()
    expiry = models.DateField()

    class Meta:
        abstract = True


class IDCard(OfficialIdentityDocument):
    scan_front = models.ImageField(upload_to='ikwen/id_cards')
    scan_back = models.ImageField(upload_to='ikwen/id_cards')

    class Meta:
        db_table = 'ikwen_id_cards'


class Passport(OfficialIdentityDocument):
    scan = models.ImageField(upload_to='ikwen/passports')

    class Meta:
        db_table = 'ikwen_passports'


SUDO = 'Sudo'
# Business events
COLLABORATION_REQUEST_EVENT = 'CollaborationRequestEvent'
ACCESS_GRANTED_EVENT = 'AccessGrantedEvent'
SERVICE_REQUEST_EVENT = 'ServiceRequestEvent'

# Personal events
CUSTOMER_REGISTERED_EVENT = 'CustomerRegisteredEvent'


class AccessRequest(Model):
    COLLABORATION_REQUEST = 'CollaborationRequest'
    SERVICE_REQUEST = 'ServiceRequest'

    PENDING = 'Pending'
    CONFIRMED = 'Confirmed'
    REJECTED = 'Rejected'

    member = models.ForeignKey(Member, db_index=True)
    service = models.ForeignKey(Service, related_name='+', db_index=True)
    type = models.CharField(max_length=30)  # COLLABORATION_REQUEST or SERVICE_REQUEST
    group_name = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=30, default=PENDING)

    class Meta:
        db_table = 'ikwen_accessrequest'

    def get_title(self):
        if self.type == self.COLLABORATION_REQUEST:
            return _('Collaboration request')
        return _('Service request')

    def get_description(self):
        if self.type == self.COLLABORATION_REQUEST:
            return _('This person would like to have access and collaborate with you')
        return _('This person would like to have access to your services')
