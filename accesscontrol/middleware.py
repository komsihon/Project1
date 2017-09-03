# -*- coding: utf-8 -*-
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
        from ikwen.core.urls import PHONE_CONFIRMATION, LOGOUT, ACCOUNT_SETUP, UPDATE_INFO, UPDATE_PASSWORD
        if rm.namespace == 'ikwen':
            if rm.url_name == LOGOUT or rm.url_name == ACCOUNT_SETUP or rm.url_name == UPDATE_INFO or \
               rm.url_name == UPDATE_PASSWORD or rm.url_name == PHONE_CONFIRMATION:
                return
        if request.user.is_authenticated() and not request.user.phone_verified:
            next_url = reverse('ikwen:phone_confirmation')
            return HttpResponseRedirect(next_url)