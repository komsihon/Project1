# -*- coding: utf-8 -*-
"""
This module groups utility middlewares that Ikwen uses.
"""
from datetime import datetime

from django.core.urlresolvers import reverse
from django.http.response import HttpResponseRedirect

from ikwen.foundation.core.urls import SERVICE_DETAIL, REGISTER, SIGN_IN, SERVICE_EXPIRED, LOAD_EVENT

from ikwen.foundation.accesscontrol.backends import UMBRELLA
from ikwen.foundation.core.models import Service
from ikwen.foundation.core.utils import get_service_instance


class ServiceStatusCheckMiddleware(object):
    """
    This middleware checks that the Service implemented by this platform is Active.
    It checks and makes sure that the current date is prior to expiry and that the
    Service's status is set to Active.

    If those conditions are not met, user is shown an "error" page at an url
    which template is core/service_expired.html
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        service = get_service_instance(using=UMBRELLA)
        if service.expiry:
            now = datetime.now()
            if now >= service.expiry or service.status != Service.ACTIVE:
                rm = request.resolver_match
                if rm.namespace == 'ikwen':
                    if rm.url_name in [SERVICE_EXPIRED, SERVICE_DETAIL, LOAD_EVENT]:
                        return None
                    if rm.url_name == REGISTER or rm.url_name == SIGN_IN:
                        return HttpResponseRedirect(reverse('ikwen:' + SERVICE_EXPIRED))
                    query_string = request.META['QUERY_STRING']
                    service_detail_url = reverse('ikwen:' + SERVICE_DETAIL, args=(service.id, )) + '?' + query_string
                    return HttpResponseRedirect(service_detail_url)
                return HttpResponseRedirect(reverse('ikwen:' + SERVICE_EXPIRED))
