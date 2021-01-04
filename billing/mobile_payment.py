# -*- coding: utf-8 -*-
import logging

from django.conf import settings

logger = logging.getLogger('ikwen')


def get_username_and_callback(request):
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    payments_conf = getattr(settings, 'PAYMENTS', None)
    if payments_conf:
        conf = request.session['payment_conf']
        callback = payments_conf[conf]['after']
    else:
        callback = getattr(settings, 'MOMO_AFTER_CASH_OUT')
    return username, callback

