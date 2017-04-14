# -*- coding: utf-8 -*-
from django.conf import settings
from django.contrib.auth.models import BaseUserManager, AbstractUser, Group
from django.core.urlresolvers import reverse
from django.db import models
from django.utils.datetime_safe import strftime
from django.utils.translation import gettext as _
from django_mongodb_engine.contrib import RawQueryMixin
from djangotoolbox.fields import ListField
from ikwen.core.utils import add_event
from permission_backend_nonrel.models import UserPermissionList

from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.core.fields import MultiImageField
from ikwen.core.models import Service, Model
from ikwen.core.utils import to_dict, get_service_instance, add_database_to_settings


SUDO = 'Sudo'
COMMUNITY = 'Community'
# Business events
ACCESS_REQUEST_EVENT = 'AccessRequestEvent'
ACCESS_GRANTED_EVENT = 'AccessGrantedEvent'
MEMBER_JOINED_IN = 'MemberJoinedIn'

# Personal events
WELCOME_EVENT = 'WelcomeEvent'


class MemberManager(BaseUserManager, RawQueryMixin):

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('Username must be set')
        member = self.model(username=username, **extra_fields)
        member.full_name = u'%s %s' % (member.first_name.split(' ')[0], member.last_name.split(' ')[0])
        service_id = getattr(settings, 'IKWEN_SERVICE_ID')
        from ikwen.accesscontrol.backends import UMBRELLA
        from ikwen.conf.settings import IKWEN_SERVICE_ID
        ikwen_community = Group.objects.using(UMBRELLA).get(name=COMMUNITY)
        member.customer_on_fk_list.append(IKWEN_SERVICE_ID)
        member.group_fk_list.append(ikwen_community.id)
        service = get_service_instance()
        member.entry_service = service
        if service_id != IKWEN_SERVICE_ID:
            service_community = Group.objects.get(name=COMMUNITY)
            member.customer_on_fk_list.append(service_id)
            member.group_fk_list.append(service_community.id)

        member.set_password(password)
        member.save(using=UMBRELLA)
        member.save(using='default')
        perm_list, created = UserPermissionList.objects.using(UMBRELLA).get_or_create(user=member)
        perm_list.group_fk_list.append(ikwen_community.id)
        perm_list.save(using=UMBRELLA)

        if service_id != IKWEN_SERVICE_ID:
            # This block is not added above because member must have
            # already been created before we can add an event for that member
            # So, DO NOT MOVE THIS ABOVE
            perm_list, created = UserPermissionList.objects.get_or_create(user=member)
            perm_list.group_fk_list.append(service_community.id)
            perm_list.save()
            sudo_group = Group.objects.get(name=SUDO)
            add_event(service, MEMBER_JOINED_IN, group_id=sudo_group.id, object_id=member.id)
            add_event(service, MEMBER_JOINED_IN, member=member, object_id=member.id)

        return member

    def create_superuser(self, username, password, **extra_fields):
        member = self.create_user(username, password, **extra_fields)
        member.collaborate_on_fk_list = []
        if getattr(settings, 'IS_IKWEN', False):
            member.customer_on_fk_list = []
        else:
            member.customer_on_fk_list = [getattr(settings, 'IKWEN_SERVICE_ID')]
        member.is_staff = True
        member.is_superuser = True
        member.is_iao = True
        member.is_bao = True
        member.save()
        if not getattr(settings, 'IS_IKWEN', False):
            group = Group.objects.get(name=SUDO)
            perm_list = UserPermissionList.objects.get(user=member)
            perm_list.group_fk_list = [group.id]
            perm_list.save()
        return member


class Member(AbstractUser):
    AVATAR = settings.STATIC_URL + 'ikwen/img/login-avatar.jpg'
    PROFILE_UPLOAD_TO = 'ikwen/members/profile_photos'
    COVER_UPLOAD_TO = 'ikwen/members/cover_images'
    MALE = 'Male'
    FEMALE = 'Female'
    # TODO: Create and set field full_name in collection ikwen_member in database itself
    full_name = models.CharField(max_length=150, db_index=True)
    phone = models.CharField(max_length=30, db_index=True, blank=True, null=True)
    gender = models.CharField(max_length=15, blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    photo = MultiImageField(upload_to=PROFILE_UPLOAD_TO, blank=True, null=True, max_size=600, small_size=200, thumb_size=100)
    cover_image = models.ImageField(upload_to=COVER_UPLOAD_TO, blank=True, null=True)
    entry_service = models.ForeignKey(Service, blank=True, null=True, related_name='+',
                                      help_text=_("Service where user registered for the first time on ikwen"))
    is_iao = models.BooleanField('IAO', default=False, editable=False,
                                 help_text=_('Designates whether this user is an '
                                             '<strong>IAO</strong> (Ikwen Application Operator).'))
    is_bao = models.BooleanField('Bao', default=False, editable=False,
                                 help_text=_('Designates whether this user is the Bao in the current service. '
                                             'Bao is the highest person in a deployed ikwen application. The only that '
                                             'can change or block Sudo.'))
    collaborates_on_fk_list = ListField(editable=False,
                                        help_text="Services on which member collaborates being the IAO or no.")
    customer_on_fk_list = ListField(editable=False,
                                    help_text="Services on which member was granted mere member access.")
    group_fk_list = ListField(editable=False,
                              help_text="Groups' ids of the member across different Services.")
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
        return self.full_name.split(' ')[0]

    def _get_display_joined(self):
        return strftime(self.date_joined, '%y/%m/%d %H:%M')
    display_date_joined = property(_get_display_joined)

    def get_from(self, db):
        add_database_to_settings(db)
        return type(self).objects.using(db).get(pk=self.id)

    def get_apps_operated(self):
        return list(Service.objects.filter(member=self))

    def get_status(self):
        if self.is_active:
            return 'Active'
        return 'Blocked'

    def get_notice_count(self):
        return self.business_notices + self.personal_notices

    def get_services(self):
        return list(set(self.collaborates_on) | set(self.customer_on))

    def _get_customer_on(self):
        from ikwen.accesscontrol.backends import UMBRELLA
        res = []
        for pk in self.customer_on_fk_list:
            try:
                res.append(Service.objects.using(UMBRELLA).get(pk=pk))
            except:
                pass
        return res
    customer_on = property(_get_customer_on)

    def _get_collaborates_on(self):
        from ikwen.accesscontrol.backends import UMBRELLA
        res = []
        for pk in self.collaborates_on_fk_list:
            try:
                res.append(Service.objects.using(UMBRELLA).get(pk=pk))
            except:
                pass
        return res
    collaborates_on = property(_get_collaborates_on)

    def propagate_changes(self):
        for s in self.get_services():
            db = s.database
            add_database_to_settings(db)
            Member.objects.using(db).filter(pk=self.id)\
                .update(email=self.email, phone=self.phone,
                        first_name=self.first_name, last_name=self.last_name, gender=self.gender)

    def propagate_password_change(self, new_password):
        for s in self.get_services():
            db = s.database
            add_database_to_settings(db)
            try:
                m = Member.objects.using(db).get(pk=self.id)
                m.set_password(new_password)
                m.save(using=db)
            except Member.DoesNotExist:
                pass

    def add_service(self, service_id):
        """
        Adds the service_id in the collaborates_on_fk_list
        for this Member
        """
        from ikwen.accesscontrol.backends import UMBRELLA
        m = Member.objects.using(UMBRELLA).get(pk=self.id)
        m.customer_on_fk_list.append(service_id)
        m.save(using=UMBRELLA)

    def add_group(self, group_id):
        """
        Adds the service_id in the group_fk_list
        for this Member
        """
        from ikwen.accesscontrol.backends import UMBRELLA
        m = Member.objects.using(UMBRELLA).get(pk=self.id)
        m.group_fk_list.append(group_id)
        m.save(using=UMBRELLA)

    def to_dict(self):
        self.collaborate_on_fk_list = []  # Empty this as it is useless and may cause error
        self.customer_on_fk_list = []  # Empty this as it is useless and may cause error
        var = to_dict(self)
        var['date_joined'] = self.display_date_joined
        var['status'] = self.get_status()
        import ikwen.conf.settings
        var['photo'] = ikwen.conf.settings.MEDIA_URL + self.photo.small_name if self.photo.name else Member.AVATAR
        url = reverse('ikwen:profile', args=(self.id, ))
        var['url'] = ikwenize(url)
        try:
            var['permissions'] = ','.join(UserPermissionList.objects.get(user=self).permission_fk_list)
        except UserPermissionList.DoesNotExist:
            var['permissions'] = ''
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


class AccessRequest(Model):
    PENDING = 'Pending'
    CONFIRMED = 'Confirmed'
    REJECTED = 'Rejected'

    member = models.ForeignKey(Member, db_index=True)
    service = models.ForeignKey(Service, related_name='+', db_index=True)
    group_name = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=30, default=PENDING)

    class Meta:
        db_table = 'ikwen_access_request'

    def get_description(self):
        if self.type == self.COLLABORATION_REQUEST:
            return _('This person would like to have access and collaborate with you')
        return _('This person would like to have access to your services')
