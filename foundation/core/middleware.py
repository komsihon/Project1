# -*- coding: utf-8 -*-
"""
This module groups utility middlewares that Ikwen uses.
"""
from datetime import datetime
from django.shortcuts import render
from ikwen.foundation.core.backends import UMBRELLA

from ikwen.foundation.core.models import Service
from ikwen.foundation.core.utils import get_service_instance


class ServiceStatusCheckMiddleware(object):
    """
    This middleware checks that the Service implemented by this platform is Active.
    It checks and makes sure that the current date is prior to expiry and that the
    Service's status is set to Active.

    If those conditions are not met, user is shown an "error" page at an url
    which template is ikwen/service_expired.html
    """

    def process_request(self, request):
        service = get_service_instance(using=UMBRELLA)
        now = datetime.now()
        if service.expiry:
            if now >= service.expiry or service.status != Service.ACTIVE:
                return render(request, 'core/service_expired.html')
