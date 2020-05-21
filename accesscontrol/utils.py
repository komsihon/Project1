# -*- coding: utf-8 -*-
import csv
import json
import logging
import random
import string
from datetime import datetime, timedelta
from threading import Thread

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Permission
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.template.defaultfilters import slugify
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode, base36_to_int
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from permission_backend_nonrel.models import UserPermissionList, GroupPermissionList

from ikwen.conf.settings import IKWEN_SERVICE_ID, WALLETS_DB_ALIAS
from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.accesscontrol.models import Member, DEFAULT_GHOST_PWD, PWAProfile
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.models import Service, XEmailObject
from ikwen.core.constants import MALE, FEMALE
from ikwen.core.utils import get_service_instance, get_mail_content, send_sms, XEmailMessage
from ikwen.revival.models import MemberProfile, ProfileTag, Revival
from ikwen.revival.utils import set_profile_tag_member_count
from ikwen.rewarding.utils import get_join_reward_pack_list, JOIN, REFERRAL

logger = logging.getLogger('ikwen')


def is_staff(member):
    if member.is_anonymous():
        return False
    return member.is_staff


def is_collaborator(member, service):
    if member.is_anonymous():
        return False
    # Reload member information from UMBRELLA database
    member = Member.objects.using(UMBRELLA).get(pk=member.id)
    if service in member.collaborates_on:
        return True
    return False


def is_admin(member):
    service = get_service_instance()
    if service.member == member:
        return True
    if service in member.collaborates_on:
        pass
    return False


def is_bao(member):
    if member.is_anonymous():
        return False
    return member.is_bao


def get_members_having_permission(model, codename):
    """
    Gets a list of members having the permission of the given model and codename
    :param model: content_type model
    :param codename: permission codename
    :return: list of Member
    """
    ct = ContentType.objects.get_for_model(model)
    perm_pk = Permission.objects.get(content_type=ct, codename=codename).id
    group_pk_list = [gp.group.pk for gp in
                     GroupPermissionList.objects.raw_query({'permission_fk_list': {'$elemMatch': {'$eq': perm_pk}}})]
    group_user_perm = UserPermissionList.objects.raw_query({'group_fk_list': {'$elemMatch': {'$in': group_pk_list}}})
    user_perm = UserPermissionList.objects.raw_query({'permission_fk_list': {'$elemMatch': {'$eq': perm_pk}}})
    user_perm_list = list(set(group_user_perm) | set(user_perm))
    return [obj.user for obj in user_perm_list]


def send_welcome_email(member, reward_pack_list=None):
    """
    Sends welcome email upon registration of a Member. The default message can
    be edited from the admin in Config.welcome_message
    Following strings in the message will be replaced as such:

    $member_name  -->  member.first_name

    @param member: Member object to whom message is sent
    @param reward_pack_list: rewards sent to Member if it is a
                             platform with Continuous Rewarding active
    """
    message = None
    if reward_pack_list:
        template_name = 'rewarding/mails/community_welcome_pack.html'
        service = reward_pack_list[0].service
    else:
        service = get_service_instance()
        config = service.config
        if getattr(settings, 'IS_IKWEN', False):
            template_name = 'accesscontrol/mails/welcome_to_ikwen.html'
        else:
            if config.welcome_message.strip():
                message = config.welcome_message.replace('$member_name', member.first_name)
            template_name = 'accesscontrol/mails/community_welcome.html'
    subject = _("Welcome to %s" % service.project_name)
    html_content = get_mail_content(subject, message, template_name=template_name,
                                    extra_context={'reward_pack_list': reward_pack_list})
    sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
    msg = XEmailMessage(subject, html_content, sender, [member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg,)).start()


class PhoneConfirmation(TemplateView):
    template_name = 'accesscontrol/phone_confirmation.html'

    def send_code(self, request, new_code=False):
        service = get_service_instance()
        member = request.user
        code = ''.join([random.SystemRandom().choice(string.digits) for _ in range(4)])
        do_send = False
        try:
            current = request.session['code']  # Test whether there's a pending code in session
            if new_code:
                request.session['code'] = code
                do_send = True
        except KeyError:
            request.session['code'] = code
            do_send = True

        if do_send:
            phone = slugify(member.phone).replace('-', '')
            if len(phone) == 9:
                phone = '237' + phone  # This works only for Cameroon
            text = 'Your %s confirmation code is %s' % (service.project_name, code)
            try:
                main_link = service.config.sms_api_script_url
                if not main_link:
                    main_link = getattr(settings, 'SMS_MAIN_LINK', None)
                send_sms(phone, text, script_url=main_link, fail_silently=False)
            except:
                fallback_link = getattr(settings, 'SMS_FALLBACK_LINK', None)
                send_sms(phone, text, script_url=fallback_link, fail_silently=False)

    def get(self, request, *args, **kwargs):
        next_url = request.META.get('REFERER')
        if not next_url:
            next_url = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
        member = request.user
        if member.is_authenticated() and member.phone_verified:
            return HttpResponseRedirect(reverse(next_url))
        if getattr(settings, 'DEBUG', False):
            self.send_code(request)
        else:
            try:
                self.send_code(request)
            except:
                logger.error('Failed to submit SMS to %s' % member.phone, exc_info=True)
                messages.error(request, _('Could not send code. Please try again later'))
        return super(PhoneConfirmation, self).get(request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        response = {'success': True}
        if self.request.GET.get('action') == 'new_code':
            if getattr(settings, 'DEBUG', False):
                self.send_code(self.request, new_code=True)
            else:
                try:
                    self.send_code(self.request, new_code=True)
                except:
                    response = {'error': _('Could not send code. Please try again later')}
            return HttpResponse(json.dumps(response), 'content-type: text/json', **response_kwargs)
        else:
            return super(PhoneConfirmation, self).render_to_response(context, **response_kwargs)

    def post(self, request, *args, **kwargs):
        member = request.user
        code = request.session.get('code')
        if code != request.POST['code']:
            context = self.get_context_data(**kwargs)
            context['error_message'] = _('Invalid code. Please try again')
            return render(request, self.template_name, context)
        member.phone_verified = True
        member.save()
        next_url = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
        return HttpResponseRedirect(reverse(next_url))


class VerifiedEmailTemplateView(TemplateView):
    """
    Views extending this will require email confirmation from user
    """
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated() and not request.user.email_verified:
            email_verified = Member.objects.using(UMBRELLA).get(pk=request.user.id).email_verified
            if email_verified:
                # If email already verified in umbrella, report it to local database
                member = request.user
                member.email_verified = True
                member.propagate_changes()
                return super(VerifiedEmailTemplateView, self).get(request, *args, **kwargs)
            referrer = request.META.get('HTTP_REFERER', '/')
            next_url = reverse('ikwen:email_confirmation') + '?next=' + referrer
            return HttpResponseRedirect(next_url)
        return super(VerifiedEmailTemplateView, self).get(request, *args, **kwargs)


class EmailConfirmationPrompt(TemplateView):
    template_name = 'accesscontrol/email_confirmation.html'

    def send_code(self, request, new_code=False, next_url=None):
        member = request.user
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = default_token_generator.make_token(member)

        do_send = False
        try:
            current = request.session['uid']  # Test whether there's a pending code in session
            if new_code:
                request.session['uid'] = uid
                do_send = True
        except KeyError:
            request.session['uid'] = uid
            do_send = True

        if do_send:
            subject = _("Confirm your email and get started !")
            template_name = 'accesscontrol/mails/confirm_email.html'
            confirmation_url = reverse('ikwen:confirm_email', args=(uid, token))
            service = get_service_instance()
            if service.config.is_standalone:
                confirmation_url = service.url + confirmation_url
            else:
                confirmation_url = ikwenize(confirmation_url)
            ikwen_service = Service.objects.using(UMBRELLA).get(pk=IKWEN_SERVICE_ID)
            html_content = get_mail_content(subject, service=ikwen_service, template_name=template_name,
                                            extra_context={'confirmation_url': confirmation_url,
                                                           'member_name': member.first_name, 'next_url': next_url})
            sender = 'ikwen <no-reply@ikwen.com>'
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            Thread(target=lambda m: m.send(), args=(msg,)).start()

    def get(self, request, *args, **kwargs):
        if self.request.GET.get('action') == 'new_code':
            response = {'success': True}
            next_url = request.GET.get('next')
            if getattr(settings, 'DEBUG', False):
                self.send_code(self.request, new_code=True, next_url=next_url)
            else:
                try:
                    self.send_code(self.request, new_code=True, next_url=next_url)
                except:
                    response = {'error': _('Could not send code. Please try again later')}
            return HttpResponse(json.dumps(response), 'content-type: text/json')
        else:
            member = request.user
            next_url = request.GET.get('next')
            if member.is_authenticated():
                email_verified = Member.objects.using(UMBRELLA).get(pk=member.id).email_verified
                if email_verified:
                    if not next_url:
                        next_url = reverse(getattr(settings, 'LOGIN_REDIRECT_URL', 'home'))
                    return HttpResponseRedirect(next_url)
            if getattr(settings, 'DEBUG', False):
                self.send_code(request, next_url=next_url)
            else:
                try:
                    self.send_code(request, next_url=next_url)
                except:
                    logger.error('Failed to submit email to %s' % member.email, exc_info=True)
                    messages.error(request, _('Could not send code. Please try again later'))
            return super(EmailConfirmationPrompt, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        member = request.user
        code = request.session.get('code')
        if code != request.POST['code']:
            context = self.get_context_data(**kwargs)
            context['error_message'] = _('Invalid code. Please try again')
            return render(request, self.template_name, context)
        member.phone_verified = True
        member.propagate_changes()
        next_url = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
        return HttpResponseRedirect(reverse(next_url))


class ConfirmEmail(TemplateView):
    """
    Confirms the member email from uid and token
    sent in the confirmation link.
    """
    template_name = 'accesscontrol/email_confirmation.html'

    def get_member(self, uidb64):
        try:
            uid = urlsafe_base64_decode(uidb64)
            member = Member.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, Member.DoesNotExist):
            member = None
        return member

    def check_token(self, user, token):
        """
        Check that a password reset token is correct for a given user.
        """
        # Parse the token
        try:
            ts_b36, hash = token.split("-")
        except ValueError:
            return False

        try:
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False

        return True

    def get(self, request, *args, **kwargs):
        uidb64, token = kwargs['uidb64'], kwargs['token']
        member = self.get_member(uidb64)
        next_url = request.GET.get('next')
        if member.email_verified:
            if next_url:
                return HttpResponseRedirect(next_url)
        context = super(ConfirmEmail, self).get_context_data(**kwargs)
        if member is not None and self.check_token(member, token):
            member.email_verified = True
            member.propagate_changes()
            context['email_confirmed'] = True
            context['next_url'] = next_url
        else:
            messages.error(request, _("Could not confirm email"))
        return render(request, self.template_name, context)


def invite_member(service, member):
    sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
    config = service.config
    try:
        invitation_message = config.__getattribute__('invitation_message')
    except AttributeError:
        return
    template_name = 'revival/mails/suggest_create_account.html'
    kwargs = get_join_reward_pack_list(service=service)
    join_reward_pack_list = kwargs['reward_pack_list']
    if join_reward_pack_list:
        subject = _("Join us on ikwen and earn free coupons." % service.project_name)
        email_type = XEmailObject.REWARDING
    else:
        subject = _("Join our community on ikwen.")
        email_type = XEmailObject.REVIVAL
    if invitation_message or join_reward_pack_list:
        with transaction.atomic(using=WALLETS_DB_ALIAS):
            from echo.models import Balance
            from echo.utils import LOW_MAIL_LIMIT, notify_for_low_messaging_credit, notify_for_empty_messaging_credit
            balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
            if 0 < balance.mail_count < LOW_MAIL_LIMIT:
                try:
                    notify_for_low_messaging_credit(service, balance)
                except:
                    logger.error("Failed to notify %s for low messaging credit." % service, exc_info=True)
            if balance.mail_count == 0 and not getattr(settings, 'UNIT_TESTING', False):
                try:
                    notify_for_empty_messaging_credit(service, balance)
                except:
                    logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
                return
        invitation_message = invitation_message.replace('$client', member.first_name)
        extra_context = {
            'member_name': member.first_name,
            'join_reward_pack_list': join_reward_pack_list,
            'invitation_message': invitation_message
        }
        try:
            html_content = get_mail_content(subject, service=service, template_name=template_name,
                                            extra_context=extra_context)
            msg = XEmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            msg.type = email_type
            if not getattr(settings, 'UNIT_TESTING', False):
                balance.mail_count -= 1
            balance.save()
            Thread(target=lambda m: m.send(), args=(msg,)).start()
            notice = "%s: Invitation sent message to member after ghost registration attempt" % service.project_name_slug
            logger.error(notice, exc_info=True)
        except:
            notice = "%s: Failed to send invite message to member after ghost registration attempt" % service.project_name_slug
            logger.error(notice, exc_info=True)


def bind_referrer_to_member(request, service):
    app = service.app
    if service.project_name_slug == 'playground':
        referrer_bind_callback = import_by_path('playground.views.referee_registration_callback')
        referrer_bind_callback(request, service=service)
    elif app.referrer_bind_callback:
        referrer_bind_callback = import_by_path(app.referrer_bind_callback)
        referrer_bind_callback(request, service=service)


def shift_ghost_member(member, db='default'):
    phone = str(member.phone)
    if phone.startswith('237') and len(phone) == 12:  # When saving ghost contacts '237' is stripped
        phone = phone[3:]
    shifted_phone = '__' + phone
    shifted_email = '__' + member.email
    shifted_username = '__' + member.username
    Member.objects.using(db).filter(phone=phone, is_ghost=True).update(phone=shifted_phone)
    Member.objects.using(db).filter(email=member.email, is_ghost=True).update(email=shifted_email)
    Member.objects.using(db).filter(username=member.username, is_ghost=True).update(username=shifted_username)


def import_ghost_profile_to_member(member, db='default'):
    phone = str(member.phone)
    if phone.startswith('237') and len(phone) == 12:  # When saving ghost contacts '237' is stripped
        phone = phone[3:]
    shifted_phone = '__' + phone
    shifted_email = '__' + member.email
    ghost_tag_fk_list = []
    try:
        ghost = Member.objects.using(db).get(phone=shifted_phone, is_ghost=True)
        ghost_tag_fk_list = MemberProfile.objects.using(db).get(member=ghost).tag_fk_list
        UserPermissionList.objects.using(db).filter(user=ghost).delete()
    except:
        pass
    try:
        ghost = Member.objects.using(db).get(email=shifted_email, is_ghost=True)
        ghost_tag_fk_list.extend(MemberProfile.objects.using(db).get(member=ghost).tag_fk_list)
        UserPermissionList.objects.using(db).filter(user=ghost).delete()
    except:
        pass

    ghost_tag_fk_list = list(set(ghost_tag_fk_list))
    men_tag, update = ProfileTag.objects.using(db).get_or_create(name='Men', slug='men', is_reserved=True)
    women_tag, update = ProfileTag.objects.using(db).get_or_create(name='Women', slug='women', is_reserved=True)
    join_tag, update = ProfileTag.objects.using(db).get_or_create(name=JOIN, slug=JOIN, is_auto=True)
    ref_tag, update = ProfileTag.objects.get_or_create(name=REFERRAL, slug=REFERRAL, is_auto=True)
    try:
        # Gender entered by user is more trustworthy that one set by website owner
        ghost_tag_fk_list.remove(men_tag.id)
    except:
        pass
    try:
        ghost_tag_fk_list.remove(women_tag.id)
    except:
        pass
    try:
        ghost_tag_fk_list.remove(join_tag.id)
    except:
        pass
    ghost_tag_fk_list.append(ref_tag.id)

    if not member.phone and shifted_phone != '__':
        member.phone = shifted_phone[2:]
    if not member.email and shifted_email != '__':
        member.email = shifted_email[2:]

    member.save()
    member_profile, update = MemberProfile.objects.using(db).get_or_create(member=member)
    member_profile.tag_fk_list.extend(ghost_tag_fk_list)
    member_profile.save()
    Member.objects.using(db).filter(phone=shifted_phone, is_ghost=True).delete()
    Member.objects.using(db).filter(email=shifted_email, is_ghost=True).delete()


def set_member_basic_profile_tags(member, db='default'):
    member_profile, update = MemberProfile.objects.using(db).get_or_create(member=member)
    men_tag, update = ProfileTag.objects.using(db).get_or_create(name='Men', slug='men', is_reserved=True)
    women_tag, update = ProfileTag.objects.using(db).get_or_create(name='Women', slug='women', is_reserved=True)
    join_tag, update = ProfileTag.objects.using(db).get_or_create(name=JOIN, slug=JOIN, is_auto=True)
    ref_tag, update = ProfileTag.objects.using(db).get_or_create(name=REFERRAL, slug=REFERRAL, is_auto=True)

    try:
        member_profile.tag_fk_list.remove(men_tag.id)
    except:
        pass
    try:
        member_profile.tag_fk_list.remove(women_tag.id)
    except:
        pass
    try:
        member_profile.tag_fk_list.remove(join_tag.id)
    except:
        pass

    if member.gender == MALE:
        member_profile.tag_fk_list.append(men_tag.id)
    elif member.gender == FEMALE:
        member_profile.tag_fk_list.append(women_tag.id)
    if not member.is_ghost:
        member_profile.tag_fk_list.append(ref_tag.id)

    member_profile.save(using=db)


class DateJoinedFilter(object):
    title = _('Registration')
    parameter_name = 'date_joined'
    is_date_filter = True

    def lookups(self):
        choices = [
            ('__period__today', _("Today")),
            ('__period__yesterday', _("Yesterday")),
            ('__period__last_7_days', _("Last 7 days")),
            ('__period__last_30_days', _("Last 30 days")),
        ]
        return choices

    def queryset(self, request, queryset):
        value = request.GET.get(self.parameter_name)
        if not value:
            return queryset

        now = datetime.now()
        start_date, end_date = None, now
        value = value.replace('__period__', '')
        if value == 'today':
            start_date = datetime(now.year, now.month, now.day, 0, 0, 0)
        elif value == 'yesterday':
            yst = now - timedelta(days=1)
            start_date = datetime(yst.year, yst.month, yst.day, 0, 0, 0)
            end_date = datetime(yst.year, yst.month, yst.day, 23, 59, 59)
        elif value == 'last_7_days':
            b = now - timedelta(days=7)
            start_date = datetime(b.year, b.month, b.day, 0, 0, 0)
        elif value == 'last_30_days':
            b = now - timedelta(days=30)
            start_date = datetime(b.year, b.month, b.day, 0, 0, 0)
        else:
            start_date, end_date = value.split(',')
            start_date += ' 00:00:00'
            end_date += ' 23:59:59'
        member_qs = Member.objects.filter(date_joined__range=(start_date, end_date))
        member_id_list = [member.id for member in member_qs]
        queryset = queryset.filter(user_id__in=member_id_list)
        return queryset


class DOBFilter(object):
    title = _('Birthday')
    parameter_name = 'dob'

    def lookups(self):
        choices = [
            ('__period__today', _("Today")),
            ('__period__tomorrow', _("Tomorrow")),
            ('__period__next_7_days', _("Next 7 days")),
            ('__period__next_30_days', _("Next 30 days")),
        ]
        return choices

    def queryset(self, request, queryset):
        value = request.GET.get(self.parameter_name)
        if not value:
            return queryset

        now = datetime.now()
        value = value.replace('__period__', '')
        member_qs = Member.objects.filter(dob__isnull=False)
        if value == 'today':
            birthday = int(now.strftime('%m%d'))
            member_qs = member_qs.filter(birthday=birthday)
        elif value == 'tomorrow':
            target = now + timedelta(days=1)
            birthday = int(target.strftime('%m%d'))
            member_qs = member_qs.filter(birthday=birthday)
        elif value == 'next_7_days':
            start = now + timedelta(days=1)
            end = now + timedelta(days=7)
            start = int(start.strftime('%m%d'))
            end = int(end.strftime('%m%d'))
            member_qs = member_qs.filter(birthday__range=(start, end))
        else:  # value == '__period__next_30_days'
            start = now + timedelta(days=1)
            end = now + timedelta(days=30)
            start = int(start.strftime('%m%d'))
            end = int(end.strftime('%m%d'))
            member_qs = member_qs.filter(birthday__range=(start, end))
        member_id_list = [member.id for member in member_qs]
        queryset = queryset.filter(user_id__in=member_id_list)
        return queryset


def import_contacts(filename, dry_run=True):
    abs_path = getattr(settings, 'MEDIA_ROOT') + filename
    fh = open(abs_path, 'r')
    line = fh.readline()
    fh.close()
    data = line.split(',')
    delimiter = ',' if len(data) > 0 else ';'
    error = None
    row_length = 5

    tag = JOIN
    join_tag, update = ProfileTag.objects.get_or_create(name=tag, slug=tag, is_auto=True)
    service = Service.objects.using(UMBRELLA).get(pk=getattr(settings, 'IKWEN_SERVICE_ID'))
    Revival.objects.using(UMBRELLA).get_or_create(service=service, model_name='core.Service', object_id=service.id,
                                                  mail_renderer='ikwen.revival.utils.render_suggest_create_account_mail',
                                                  profile_tag_id=join_tag.id,
                                                  get_kwargs='ikwen.rewarding.utils.get_join_reward_pack_list')

    with open(abs_path) as csv_file:
        csv_reader = csv.reader(csv_file, delimiter=delimiter)
        i = -1
        for row in csv_reader:
            i += 1
            if i == 0:
                continue
            if len(row) < row_length:
                error = _("Missing information on line %(line)d. %(found)d tokens found, "
                          "but %(expected)d expected." % {'line': i + 1, 'found': len(row), 'expected': row_length})
                break
            first_name = row[0].strip()
            if not first_name:
                error = _("Missing first name on line %d." % (i + 1))
                break
            last_name = row[1].strip()
            if not last_name:
                error = _("Missing last name on line %d." % (i + 1))
                break
            gender = row[2].strip()
            if gender.lower().startswith("m") or gender == _('man'):
                gender = MALE
            elif gender.lower().startswith("f") or gender == _('woman'):
                gender = FEMALE
            else:
                error = _("Unknown gender <strong>%(gender)s</strong> on line %(line)s. "
                          "Must be either <b>Man</b> or <b>Woman</b>" % {'gender': gender, 'line': i + 1})
                break
            email = row[3].strip()
            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    error = _("Invalid email <strong>%(email)s</strong> on "
                              "line %(line)d" % {'email': email, 'line': (i + 1)})
                    break
            phone = row[4].strip()
            if phone:
                phone = slugify(phone).replace('-', '')

            if not (phone or email):
                error = _("No phone or email on line %d" % (i + 1))
                break

            profile_names = row[5].split(',')
            tag_fk_list = [join_tag.id]
            profile_error = False
            for name in profile_names:
                name = name.strip()
                try:
                    profile = ProfileTag.objects.get(name=name)
                    tag_fk_list.append(profile.id)
                except ProfileTag.DoesNotExist:
                    error = _("Unexisting profile <strong>%(name)s</strong> on line %(line)d. "
                              "Please create first." % {'name': name, 'line': (i + 1)})
                    profile_error = True
                    break

            if profile_error:
                break

            if not dry_run:
                try:
                    try:
                        Member.objects.get(email=email)
                        continue
                    except Member.DoesNotExist:
                        pass
                    try:
                        Member.objects.get(phone=phone)
                        continue
                    except Member.DoesNotExist:
                        pass
                    username = email if email else phone
                    full_name = first_name + ' ' + last_name
                    member = Member.objects.create_user(username, DEFAULT_GHOST_PWD, email=email, phone=phone,
                                                        gender=gender, first_name=first_name, last_name=last_name,
                                                        full_name=full_name, is_ghost=True)
                    member_profile, update = MemberProfile.objects.get_or_create(member=member)
                    member_profile.tag_fk_list.extend(tag_fk_list)
                    member_profile.save()
                except:
                    continue
        Thread(target=set_profile_tag_member_count).start()
    return error


def update_push_subscription(request, *args, **kwargs):
    """
    Saves the user push subscription to the Database
    """
    pwa_profile_id = request.COOKIES.get('pwa_profile_id')
    now = datetime.now()
    new_profile = True
    response = {'success': True}
    if pwa_profile_id:
        try:
            pwa_profile = PWAProfile.objects.get(pk=pwa_profile_id)
            new_profile = False
        except:
            pwa_profile = PWAProfile()
    else:
        pwa_profile = PWAProfile()
    if request.user.is_authenticated():
        member = request.user
        if pwa_profile_id and not pwa_profile.member:
            PWAProfile.objects.filter(member=member).delete()
        pwa_profile.member = member
    push_subscription = request.POST['value']
    pwa_profile.subscribed_to_push_on = now
    pwa_profile.push_subscription = push_subscription
    pwa_profile.save()

    response = HttpResponse(json.dumps(response))
    if new_profile:
        expires = now + timedelta(days=1826)  # Expires in 5 years
        secure = not getattr(settings, 'DEBUG', False)
        response.set_cookie('pwa_profile_id', pwa_profile.id, expires=expires, secure=secure)
    return response
