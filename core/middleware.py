# -*- coding: utf-8 -*-
"""
This module groups utility middlewares that Ikwen uses.
"""
from datetime import datetime

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http.response import HttpResponseRedirect

from ikwen.core.urls import SERVICE_DETAIL, SIGN_IN, SERVICE_EXPIRED, LOAD_EVENT, LOGOUT

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.models import Service
from ikwen.core.utils import get_service_instance


class ServiceStatusCheckMiddleware(object):
    """
    This middleware checks that the Service implemented by this platform is Active.
    It checks and makes sure that the current date is prior to expiry and that the
    Service's status is set to Active.

    If those conditions are not met, user is shown an "error" page at an url
    which template is core/service_expired.html
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        if getattr(settings, 'IS_IKWEN', False):
            return
        service = get_service_instance(using=UMBRELLA)
        retailer = service.retailer
        if retailer and retailer.status != Service.ACTIVE:
            # If a retailer is suspended, so are all his customers
            return HttpResponseRedirect(reverse('ikwen:' + SERVICE_EXPIRED))
        if service.expiry:
            now = datetime.now()
            if now.date() > service.expiry or service.status != Service.ACTIVE:
                rm = request.resolver_match
                if request.user.is_authenticated() and request.user == service.member:
                    if rm.namespace == 'ikwen':
                        if rm.url_name in [SERVICE_EXPIRED, SERVICE_DETAIL, LOAD_EVENT, SIGN_IN, LOGOUT]:
                            return None
                    query_string = request.META['QUERY_STRING']
                    service_detail_url = reverse('ikwen:' + SERVICE_DETAIL, args=(service.id, )) + '?' + query_string
                    return HttpResponseRedirect(service_detail_url)
                if rm.namespace == 'ikwen':
                    if rm.url_name in [SERVICE_EXPIRED, SERVICE_DETAIL, LOAD_EVENT, SIGN_IN, LOGOUT]:
                        return None
                return HttpResponseRedirect(reverse('ikwen:' + SERVICE_EXPIRED))
