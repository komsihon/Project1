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
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from permission_backend_nonrel.models import UserPermissionList, GroupPermissionList

from ikwen.accesscontrol.models import Member
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.utils import get_service_instance, get_mail_content, send_sms

logger = logging.getLogger('ikwen')


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
            next_url = reverse('ikwen:email_confirmation')
            return HttpResponseRedirect(next_url)
        super(VerifiedEmailTemplateView, self).get(request, *args, **kwargs)


class EmailConfirmationPrompt(TemplateView):
    template_name = 'accesscontrol/email_confirmation.html'

    def send_code(self, request, new_code=False):
        member = request.user
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = default_token_generator.make_token(member)

        do_send = False
        try:
            uid = request.session['uid']  # Test whether there's a pending code in session
            if new_code:
                request.session['uid'] = uid
                do_send = True
        except KeyError:
            request.session['uid'] = uid
            do_send = True

        if do_send:
            subject = _("Confirm your email and get started !")
            template_name = 'accesscontrol/mails/confirm_email.html'
            confirmation_url = 'http://www.ikwen.com' + reverse('ikwen:confirm_email', args=(uid, token))
            html_content = get_mail_content(subject, template_name=template_name,
                                            extra_context={'confirmation_url': confirmation_url,
                                                           'member_name': member.first_name})
            sender = 'ikwen <no-reply@ikwen.com>'
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            Thread(target=lambda m: m.send(), args=(msg,)).start()

    def get(self, request, *args, **kwargs):
        next_url = request.META.get('REFERER')
        if not next_url:
            next_url = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
        member = request.user
        if member.is_authenticated() and member.email_verified:
            return HttpResponseRedirect(reverse(next_url))
        if getattr(settings, 'DEBUG', False):
            self.send_code(request)
        else:
            try:
                self.send_code(request)
            except:
                logger.error('Failed to submit email to %s' % member.email, exc_info=True)
                messages.error(request, _('Could not send code. Please try again later'))
        return super(EmailConfirmationPrompt, self).get(request, *args, **kwargs)

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
            return super(EmailConfirmationPrompt, self).render_to_response(context, **response_kwargs)

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

    def get(self, request, *args, **kwargs):
        uidb64, token = kwargs['uidb64'], kwargs['token']
        member = self.get_member(uidb64)
        if member is not None and default_token_generator.check_token(member, token):
            member.email_verified = True
            member.save()
        context = super(ConfirmEmail, self).get_context_data(**kwargs)
        context['email_confirmed'] = True
        return render(request, self.template_name, context)
