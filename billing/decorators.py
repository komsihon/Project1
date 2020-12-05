# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseRedirect

from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.templatetags.url_utils import strip_base_alias
from ikwen.core.utils import get_service_instance
from ikwen.billing.models import MoMoTransaction
from ikwen.billing.mtnmomo.open_api import MTN_MOMO

logger = logging.getLogger('ikwen')


def momo_gateway_request(fn):
    """
    Decorator that does necessary operations to contact gateway for
    a payment processing. Decorated function must return the following:

    `amount`: Amount to be paid by the user
    `notification_url`: callback URL that will be hit after payment processing
    the view function behind the callback URL must be decorated with the @momo_gateway_callback
    `return_url`: URL of page where user is redirected after successful payment
    `cancel_url`: URL of page where user is redirected if anything goes wrong
    """
    def wrapper(*args, **kwargs):
        request = args[0]
        mean = request.GET.get('mean', MTN_MOMO)
        service = get_service_instance()
        config = service.config
        payer_id = request.user.username if request.user.is_authenticated() else '<Anonymous>'
        amount, notification_url, return_url, cancel_url = fn(*args, **kwargs)
        if getattr(settings, 'UNIT_TESTING', False):
            return HttpResponse(json.dumps({'notification_url': notification_url}), content_type='text/json')
        gateway_url = getattr(settings, 'IKWEN_PAYMENT_GATEWAY_URL', 'http://payment.ikwen.com/v1')
        endpoint = gateway_url + '/request_payment'
        if not notification_url.lower().startswith('http'):
            notification_url = service.url + strip_base_alias(notification_url)
        if not return_url.lower().startswith('http'):
            return_url = service.url + strip_base_alias(return_url)
        if not cancel_url.lower().startswith('http'):
            cancel_url = service.url + strip_base_alias(cancel_url)
        params = {
            'username': getattr(settings, 'IKWEN_PAYMENT_GATEWAY_USERNAME', service.project_name_slug),
            'amount': amount,
            'merchant_name': config.company_name,
            'notification_url': notification_url,
            'return_url': return_url,
            'cancel_url': cancel_url,
            'payer_id': payer_id
        }
        try:
            r = requests.get(endpoint, params)
            resp = r.json()
            token = resp.get('token')
            if token:
                next_url = gateway_url + '/checkoutnow/' + resp['token'] + '?mean=' + mean
            else:
                logger.error("%s - Init payment flow failed with URL %s and message %s" % (service.project_name, r.url, resp['errors']))
                messages.error(request, resp['errors'])
                next_url = cancel_url
        except:
            logger.error("%s - Init payment flow failed with URL." % service.project_name, exc_info=True)
            next_url = cancel_url
        return HttpResponseRedirect(next_url)
    return wrapper


def momo_gateway_callback(fn):
    """
    Decorator that does necessary checks upon the call of the
    function that runs behind the URL hit by ikwen MoMo Gateway.
    """
    def wrapper(*args, **kwargs):
        request = args[0]
        status = request.GET['status']
        message = request.GET['message']
        operator_tx_id = request.GET['operator_tx_id']
        phone = request.GET['phone']
        tx_id = kwargs.pop('tx_id')
        try:
            tx = MoMoTransaction.objects.using(WALLETS_DB_ALIAS).get(pk=tx_id, is_running=True)
            if not getattr(settings, 'DEBUG', False):
                tx_timeout = getattr(settings, 'IKWEN_PAYMENT_GATEWAY_TIMEOUT', 15) * 60
                expiry = tx.created_on + timedelta(seconds=tx_timeout)
                if datetime.now() > expiry:
                    return HttpResponse("Transaction %s timed out." % tx_id)

            tx.status = status
            tx.message = 'OK' if status == MoMoTransaction.SUCCESS else message
            tx.processor_tx_id = operator_tx_id
            tx.phone = phone
            tx.is_running = False
            tx.save()
        except:
            raise Http404("Transaction %s not found" % tx_id)
        if status != MoMoTransaction.SUCCESS:
            return HttpResponse("Notification for transaction %s received with status %s" % (tx_id, status))
        signature = tx.task_id

        callback_signature = kwargs['signature']
        no_check_signature = request.GET.get('ncs')
        if getattr(settings, 'DEBUG', False):
            if not no_check_signature:
                if callback_signature != signature:
                    return HttpResponse('Invalid transaction signature')
        else:
            if callback_signature != signature:
                return HttpResponse('Invalid transaction signature')
        kwargs['tx'] = tx
        return fn(*args, **kwargs)
    return wrapper
