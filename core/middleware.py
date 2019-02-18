# -*- coding: utf-8 -*-
"""
This module groups utility middlewares that Ikwen uses.
"""

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http.response import HttpResponseRedirect

from ikwen.core.urls import SERVICE_DETAIL, SIGN_IN, DO_SIGN_IN, SERVICE_EXPIRED, LOAD_EVENT, LOGOUT

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.models import Service
from ikwen.core.utils import get_service_instance


class ServiceStatusCheckMiddleware(object):
    """
    This middleware checks that the Service implemented by this platform is Active.
    It checks and makes sure that the Service's status is set to Active.

    If those conditions are not met, user is shown an "error" page at an url
    which template is core/service_expired.html
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        if getattr(settings, 'IS_IKWEN', False):
            return
        rm = request.resolver_match
        service = get_service_instance(using=UMBRELLA)
        retailer = service.retailer

        if retailer and retailer.status != Service.PENDING and retailer.status != Service.ACTIVE:
            # If a retailer is suspended, so are all his customers
            if rm.namespace == 'ikwen' and rm.url_name in [SERVICE_EXPIRED, LOAD_EVENT]:
                return
            return HttpResponseRedirect(reverse('ikwen:' + SERVICE_EXPIRED))
        if service.status != Service.PENDING and service.status != Service.ACTIVE:
            if request.user.is_authenticated() and request.user == service.member:
                if rm.namespace == 'ikwen':
                    if rm.url_name in [SERVICE_EXPIRED, SERVICE_DETAIL, LOAD_EVENT, SIGN_IN, DO_SIGN_IN, LOGOUT]:
                        return
                query_string = request.META['QUERY_STRING']
                service_detail_url = reverse('ikwen:' + SERVICE_DETAIL, args=(service.id, )) + '?' + query_string
                return HttpResponseRedirect(service_detail_url)
            if rm.namespace == 'ikwen':
                if rm.url_name in [SERVICE_EXPIRED, SERVICE_DETAIL, LOAD_EVENT, SIGN_IN, DO_SIGN_IN, LOGOUT]:
                    return
            return HttpResponseRedirect(reverse('ikwen:' + SERVICE_EXPIRED))
        elif rm.namespace == 'ikwen' and rm.url_name == SERVICE_EXPIRED:
            return


class HideError403Middleware(object):
    """
    This middleware sends the user back to website home in
    case of Error 403
    """
    def process_response(self, request, response):
        if getattr(settings, 'DEBUG', False):
            return response
        if response.status_code == 403:
            logout = reverse('ikwen:logout')
            return HttpResponseRedirect(logout)
        return response
