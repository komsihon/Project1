# -*- coding: utf-8 -*-
import json
import logging
import random
import string
from threading import Thread

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Permission
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.template.defaultfilters import slugify
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode, base36_to_int
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from permission_backend_nonrel.models import UserPermissionList, GroupPermissionList

from ikwen.conf.settings import IKWEN_SERVICE_ID
from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.accesscontrol.models import Member
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.models import Service
from ikwen.core.utils import get_service_instance, get_mail_content, send_sms
from ikwen.revival.models import MemberProfile, ProfileTag
from ikwen.rewarding.utils import JOIN, REFERRAL

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
    msg = EmailMessage(subject, html_content, sender, [member.email])
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
            next_url = reverse('ikwen:email_confirmation')
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
            ikwen_service = Service.objects.using(UMBRELLA).get(pk=IKWEN_SERVICE_ID)
            html_content = get_mail_content(subject, service=ikwen_service, template_name=template_name,
                                            extra_context={'confirmation_url': ikwenize(confirmation_url),
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
            if member.is_authenticated():
                email_verified = Member.objects.using(UMBRELLA).get(pk=member.id).email_verified
                if email_verified:
                    next_url = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
                    return HttpResponseRedirect(reverse(next_url))
            next_url = request.GET.get('next')
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
