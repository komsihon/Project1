# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.urlresolvers import reverse
from django.http.response import HttpResponseRedirect
from django.utils.http import urlsafe_base64_decode

UID_B64 = 'key'
TOKEN = 'rand'
TOKEN_CHUNK = 15


class XDomainTokenAuthMiddleware(object):
    """
    Middleware that authenticates user across domains using those two:
        * uidb64: Base 64 encoded user Id
        * token: characters of the encoded user password in the range [-TOKEN_CHUNK:-1]
    Those two parameters are passed around as GET data. When detected on a URL,
    the middleware will check if they are valid and login the user.
    """
    def process_request(self, request):
        uidb64 = request.GET.get(UID_B64)
        token = request.GET.get(TOKEN)
        if request.user.is_authenticated():
            if uidb64 and token:
                uid = urlsafe_base64_decode(uidb64)
                member = request.user
                if member.id != uid or token != member.password[-TOKEN_CHUNK:-1]:
                    logout(request)
                    tokens_string = UID_B64 + '=' + uidb64 + '&' + TOKEN + '=' + token
                    raw_next_url = request.build_absolute_uri().replace(tokens_string, '').strip('?').strip('&')
                    return HttpResponseRedirect(raw_next_url)
        else:
            if uidb64 and token:
                uid = urlsafe_base64_decode(uidb64)
                member = authenticate(uid=uid)
                if token == member.password[-TOKEN_CHUNK:-1]:
                    login(request, member)

        if request.user.is_authenticated():
            # Copy notices count from UMBRELLA database that keeps actual values
            from ikwen.accesscontrol.backends import UMBRELLA
            if not getattr(settings, 'IS_IKWEN', False):
                m2 = request.user.get_from(UMBRELLA)
                request.user.business_notices = m2.business_notices
                request.user.personal_notices = m2.personal_notices


class PhoneVerificationMiddleware(object):
    """
    Middleware that checks whether Member has a verified phone number.
    If not, he is prompted to do so. Note that the application should
    have functional HTTP SMS API configured for this to work.
    SMS API link is read from AbstractConfig.sms_api_script_url
    """
    def process_view(self, request, view_func, view_args, view_kwargs):
        rm = request.resolver_match
        if rm.namespace == 'ikwen':
            from ikwen.core.urls import PHONE_CONFIRMATION, LOGOUT,\
                ACCOUNT_SETUP, UPDATE_INFO, UPDATE_PASSWORD,  STAFF_ROUTER
            if rm.url_name in [LOGOUT, ACCOUNT_SETUP, UPDATE_INFO, UPDATE_PASSWORD, PHONE_CONFIRMATION, STAFF_ROUTER]:
                return
        if request.user.is_authenticated() and not request.user.phone_verified:
            next_url = reverse('ikwen:phone_confirmation')
            return HttpResponseRedirect(next_url)


class EmailVerificationMiddleware(object):
    """
    Middleware that checks whether Member has a verified email address.
    If not, he is prompted to do so.
    """
    def process_view(self, request, view_func, view_args, view_kwargs):
        rm = request.resolver_match
        if rm.namespace == 'ikwen':
            from ikwen.core.urls import EMAIL_CONFIRMATION, CONFIRM_EMAIL, LOGOUT,\
                ACCOUNT_SETUP, UPDATE_INFO, UPDATE_PASSWORD,  STAFF_ROUTER
            if rm.url_name in [LOGOUT, ACCOUNT_SETUP, UPDATE_INFO, UPDATE_PASSWORD,
                               EMAIL_CONFIRMATION, STAFF_ROUTER, CONFIRM_EMAIL]:
                return
        if request.user.is_authenticated() and request.user.is_staff and not request.user.email_verified:
            # First check if email not already verified in umbrella database
            from ikwen.accesscontrol.models import Member
            from ikwen.accesscontrol.backends import UMBRELLA
            email_verified = Member.objects.using(UMBRELLA).get(pk=request.user.id).email_verified
            if email_verified:
                # If email already verified in umbrella, report it to local database
                member = request.user
                member.email_verified = True
                member.propagate_changes()
                return

            next_url = request.GET.get('next', request.META.get('HTTP_REFERER'))
            confirm_url = reverse('ikwen:email_confirmation')
            if next_url:
                confirm_url += '?next=' + next_url
            return HttpResponseRedirect(confirm_url)


class PWAMiddleware(object):
    """
    Performs necessary operations for User accessing using PWA
    1 - Redirect to homepage
    2 - Bind the PWAProfile if Member is authenticated
    """
    def process_response(self, request, response):
        from ikwen.core.utils import get_device_type, get_service_instance
        from ikwen.accesscontrol.models import Member, PWAProfile
        if request.GET.get('__pwa'):
            pwa_profile_id = request.COOKIES.get('pwa_profile_id')
            now = datetime.now()
            new_profile = True
            device_type = get_device_type(request)
            if pwa_profile_id:
                try:
                    pwa_profile = PWAProfile.objects.get(pk=pwa_profile_id)
                    new_profile = False
                except:
                    pwa_profile = PWAProfile(device_type=device_type)
            else:
                pwa_profile = PWAProfile(device_type=device_type)
            if request.user.is_authenticated():
                member = request.user
                if pwa_profile_id and not pwa_profile.member:
                    PWAProfile.objects.filter(service=get_service_instance(), member=member, device_type=device_type).delete()
                pwa_profile.member = Member.objects.get(pk=member.id)
            pwa_profile.save()

            new_response = response
            next_url = request.GET.get('next', request.META.get('HTTP_REFERER'))
            if not request.GET.get('__no_redirect'):
                login_url = reverse('ikwen:sign_in')
                if next_url:
                    login_url += '?next=' + next_url
                new_response = HttpResponseRedirect(login_url)

            if new_profile:
                expires = now + timedelta(days=1826)  # Expires in 5 years
                secure = not getattr(settings, 'DEBUG', False)
                new_response.set_cookie('pwa_profile_id', pwa_profile.id, expires=expires, secure=secure)

            return new_response
        return response
