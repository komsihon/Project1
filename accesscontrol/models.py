# -*- coding: utf-8 -*-

from django.conf import settings
from django.contrib.auth.models import BaseUserManager, AbstractUser, Group
from django.urls import reverse
from django.db.models.signals import post_delete
from django.template.defaultfilters import slugify
from django.utils.datetime_safe import strftime
from django.utils.translation import gettext as _, get_language

from djongo import models

from ikwen.core.constants import DEVICE_FAMILY_CHOICES
from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.core.fields import MultiImageField
from ikwen.core.models import Service, Model, OperatorWallet
from ikwen.core.utils import add_event, to_dict, get_service_instance, add_database_to_settings


SUDO = 'Sudo'
COMMUNITY = 'Community'
# Business events
ACCESS_REQUEST_EVENT = 'AccessRequestEvent'
ACCESS_GRANTED_EVENT = 'AccessGrantedEvent'
MEMBER_JOINED_IN = 'MemberJoinedIn'

# Personal events
WELCOME_EVENT = 'WelcomeEvent'

DEFAULT_GHOST_PWD = '__0000'


class MemberManager(BaseUserManager):

    def create_user(self, username, password=None, **extra_fields):
        from ikwen.accesscontrol.backends import UMBRELLA
        from ikwen.conf.settings import IKWEN_SERVICE_ID
        if not username:
            raise ValueError('Username must be set')
        try:
            phone = str(extra_fields.get('phone', ''))
            email = extra_fields.get('email', '')
            if phone and phone.startswith('237') and len(phone) == 12:  # When saving ghost contacts '237' is stripped
                phone = phone[3:]
            try:
                member = Member.objects.get(phone=phone, is_ghost=True)
            except:
                try:
                    member = Member.objects.get(email=email, is_ghost=True)
                except:
                    member = Member.objects.get(username=username, is_ghost=True)
            member.is_ghost = False
            member.username = username
            for key, value in extra_fields.items():
                member.__dict__[key] = value
        except Member.DoesNotExist:
            member = self.model(username=username, **extra_fields)

        member.full_name = u'%s %s' % (member.first_name.split(' ')[0], member.last_name.split(' ')[0])
        member.tags = slugify(member.first_name + ' ' + member.last_name).replace('-', ' ')
        service_id = getattr(settings, 'IKWEN_SERVICE_ID')
        ikwen_community = Group.objects.using(UMBRELLA).get(name=COMMUNITY)
        member.customer_on_fk_list = [IKWEN_SERVICE_ID]
        member.group_fk_list = [ikwen_community.id]
        member.groups.add(ikwen_community)
        service = get_service_instance()
        member.entry_service = service
        if service_id != IKWEN_SERVICE_ID:
            service_community = Group.objects.get(name=COMMUNITY)
            member.customer_on_fk_list.append(service_id)
            member.group_fk_list.append(service_community.id)

        member.set_password(password)
        member.save(using=UMBRELLA)
        member.save(using='default')
        member.groups.add(ikwen_community)

        from ikwen.accesscontrol.utils import set_member_basic_profile_tags
        set_member_basic_profile_tags(member)

        if service_id != IKWEN_SERVICE_ID:
            # This block is not added above because member must have
            # already been created before we can add an event for that member
            # So, DO NOT MOVE THIS ABOVE
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
            sudo_group = Group.objects.get(name=SUDO)
            member.groups.add(sudo_group)
        return member


class Member(AbstractUser):
    AVATAR = settings.STATIC_URL + 'ikwen/img/login-avatar.jpg'
    PROFILE_UPLOAD_TO = 'members/profile_photos'
    COVER_UPLOAD_TO = 'members/cover_images'
    MALE = 'Male'
    FEMALE = 'Female'
    is_ghost = models.BooleanField(default=False,
                                   help_text="Ghost users are created manually by site owner. They can still register "
                                             "normally afterwards. Ghost members are useful because they can be "
                                             "enrolled in revivals without actually having an account on the website")
    full_name = models.CharField(max_length=150, db_index=True)
    tags = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    phone = models.CharField(max_length=30, db_index=True, blank=True, null=True)
    gender = models.CharField(max_length=15, blank=True, null=True)
    dob = models.DateField(blank=True, null=True, db_index=True)
    birthday = models.IntegerField(blank=True, null=True, db_index=True)  # Integer value of birthday only as MMDD. Eg:1009 for Oct. 09
    language = models.CharField(max_length=10, blank=True, null=True, default=get_language)
    photo = MultiImageField(upload_to=PROFILE_UPLOAD_TO, blank=True, null=True, max_size=600, small_size=200, thumb_size=100)
    cover_image = models.ImageField(upload_to=COVER_UPLOAD_TO, blank=True, null=True)
    entry_service = models.ForeignKey(Service, blank=True, null=True, related_name='+', on_delete=models.SET_NULL,
                                      help_text=_("Service where user registered for the first time on ikwen"))
    is_iao = models.BooleanField('IAO', default=False, editable=False,
                                 help_text=_('Designates whether this user is an '
                                             '<strong>IAO</strong> (Ikwen Application Operator).'))
    is_bao = models.BooleanField('Bao', default=False, editable=False,
                                 help_text=_('Designates whether this user is the Bao in the current service. '
                                             'Bao is the highest person in a deployed ikwen application. The only that '
                                             'can change or block Sudo.'))
    collaborates_on_fk_list = models.JSONField(editable=False,
                                               help_text="Services on which member collaborates being the IAO or no.")
    customer_on_fk_list = models.JSONField(editable=False,
                                           help_text="Services on which member was granted mere member access.")
    group_fk_list = models.JSONField(editable=False,
                                     help_text="Groups' ids of the member across different Services.")
    email_verified = models.BooleanField(_('Email verification status'), default=False,
                                         help_text=_('Designates whether this email has been verified.'))
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

    def __str__(self):
        return self.get_username()

    def save(self, **kwargs):
        if self.dob:
            self.birthday = int(self.dob.strftime('%m%d'))
        super(Member, self).save(**kwargs)

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
                self.customer_on_fk_list.remove(pk)
                self.save()
        return res
    customer_on = property(_get_customer_on)

    def _get_collaborates_on(self):
        from ikwen.accesscontrol.backends import UMBRELLA
        res = []
        for pk in self.collaborates_on_fk_list:
            try:
                res.append(Service.objects.using(UMBRELLA).get(pk=pk))
            except:
                self.collaborates_on_fk_list.remove(pk)
                self.save()
        return res
    collaborates_on = property(_get_collaborates_on)

    def _get_profile_tag_list(self):
        from ikwen.revival.models import MemberProfile, ProfileTag
        member_profile, change = MemberProfile.objects.get_or_create(member=self)
        res = []
        for pk in member_profile.tag_fk_list:
            try:
                res.append(ProfileTag.objects.get(pk=pk, is_active=True, is_auto=False, is_reserved=False))
            except:
                member_profile.tag_fk_list.remove(pk)
                member_profile.save()
        return res
    profile_tag_list = property(_get_profile_tag_list)

    def _get_preference_list(self):
        from ikwen.revival.models import MemberProfile, ProfileTag
        member_profile, change = MemberProfile.objects.get_or_create(member=self)
        res = []
        for pk in member_profile.tag_fk_list:
            try:
                res.append(ProfileTag.objects.get(pk=pk, is_active=True, is_auto=True, is_reserved=False))
            except:
                member_profile.tag_fk_list.remove(pk)
                member_profile.save()
        return res
    preference_list = property(_get_preference_list)

    def propagate_changes(self):
        for s in self.get_services():
            db = s.database
            add_database_to_settings(db)
            Member.objects.using(db).filter(pk=self.id)\
                .update(email=self.email, phone=self.phone, gender=self.gender, first_name=self.first_name,
                        last_name=self.last_name, full_name=self.first_name + ' ' + self.last_name,
                        photo=self.photo.name, cover_image=self.cover_image.name, phone_verified=self.phone_verified,
                        email_verified=self.email_verified, language=self.language)

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
        member_detail_view = getattr(settings, 'MEMBER_DETAIL_VIEW', 'ikwen:profile')
        url = reverse(member_detail_view, args=(self.id, ))
        if member_detail_view == 'ikwen:profile':
            url = ikwenize(url)
        var['url'] = url
        var['permissions'] = ','.join([perm.id for perm in self.user_permissions.all()])
        del(var['password'])
        del(var['is_superuser'])
        del(var['is_staff'])
        del(var['is_active'])
        return var


class PWAProfile(Model):
    service = models.ForeignKey(Service, default=get_service_instance, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, blank=True, null=True, on_delete=models.SET_NULL)
    device_type = models.CharField(max_length=100, choices=DEVICE_FAMILY_CHOICES, db_index=True)
    installed_on = models.DateTimeField(blank=True, null=True, db_index=True)
    subscribed_to_push_on = models.DateTimeField(blank=True, null=True, db_index=True)
    push_subscription = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'ikwen_pwa_profile'


class OfficialIdentityDocument(Model):
    member = models.ForeignKey(Member, db_index=True, on_delete=models.CASCADE)
    number = models.CharField(max_length=100, db_index=True)
    issue = models.DateField()
    expiry = models.DateField()

    class Meta:
        abstract = True


class IDCard(OfficialIdentityDocument):
    scan_front = models.ImageField(upload_to='id_cards')
    scan_back = models.ImageField(upload_to='id_cards')

    class Meta:
        db_table = 'ikwen_id_cards'


class Passport(OfficialIdentityDocument):
    scan = models.ImageField(upload_to='passports')

    class Meta:
        db_table = 'ikwen_passport'


class AccessRequest(Model):
    PENDING = 'Pending'
    CONFIRMED = 'Confirmed'
    REJECTED = 'Rejected'

    member = models.ForeignKey(Member, db_index=True, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, related_name='+', db_index=True, on_delete=models.CASCADE)
    group_name = models.CharField(max_length=60, blank=True, default=COMMUNITY)
    status = models.CharField(max_length=30, default=CONFIRMED)

    class Meta:
        db_table = 'ikwen_access_request'

    def get_description(self):
        if self.type == self.COLLABORATION_REQUEST:
            return _('This person would like to have access and collaborate with you')
        return _('This person would like to have access to your services')


class OwnershipTransfer(Model):
    MAX_DELAY = 48

    sender = models.ForeignKey(Member, on_delete=models.CASCADE)
    target_id = models.CharField(max_length=24)  # ID of the target Member

    class Meta:
        db_table = 'ikwen_ownership_transfer'

    def _get_target(self):
        return Member.objects.using('umbrella').get(pk=self.target_id)
    target = property(_get_target)


def delete_member_profile(sender, **kwargs):
    """
    Receiver of the post_delete signal for Member. This signal mostly
    deletes associated MemberProfile
    """
    if sender != Member:  # Avoid unending recursive call
        return
    instance = kwargs['instance']
    from ikwen.revival.models import MemberProfile
    MemberProfile.objects.filter(member=instance).delete()


post_delete.connect(delete_member_profile, dispatch_uid="member_post_delete_id")
