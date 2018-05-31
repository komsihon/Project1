import json
import traceback
from datetime import datetime
from threading import Thread

import math
import requests
import time
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.http.response import HttpResponseRedirect
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_by_path
from requests.exceptions import SSLError

from requests import RequestException
from requests import Timeout

from ikwen.core.utils import get_service_instance

from ikwen.billing.models import PaymentMean, MoMoTransaction

import logging
logger = logging.getLogger('ikwen')

ORANGE_MONEY = 'orange-money'
UNKNOWN_PHONE = '<Unknown>'


def init_web_payment(request, *args, **kwargs):
    api_url = getattr(settings, 'ORANGE_MONEY_API_URL') + '/webpayment'
    phone = UNKNOWN_PHONE
    service = get_service_instance()
    request.session['phone'] = phone
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 1
    else:
        amount = int(request.session['amount'])
        if not getattr(settings, 'OM_FEES_ON_MERCHANT', False):
            factor = 1 + getattr(settings, 'OM_FEES', 3.5) / 100
            amount = int(math.ceil(amount * factor))
            if amount % 50 != 0:
                amount = (amount / 50 + 1) * 50
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    username = request.user.username if request.user.is_authenticated() else None
    try:
        momo_tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
    except MoMoTransaction.DoesNotExist:
        momo_tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT,
                                                                  phone=phone, amount=amount, model=model_name,
                                                                  object_id=object_id, wallet=ORANGE_MONEY, username=username)
    request.session['tx_id'] = momo_tx.id
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    notif_url = request.session['notif_url']
    notif_url += '/%d' % momo_tx.id
    company_name = slugify(service.config.company_name).replace('-', ' ')
    data = {'order_id': object_id,
            'amount': amount,
            'lang': 'fr',
            'reference': request.session.get('merchant_name', company_name.upper()),
            'return_url': request.session['return_url'],
            'cancel_url': request.session['cancel_url'],
            'notif_url': notif_url}
    if getattr(settings, 'DEBUG', False):
        om = json.loads(PaymentMean.objects.get(slug=ORANGE_MONEY).credentials)
        headers.update({'Authorization': 'Bearer ' + om['access_token']})
        data.update({'merchant_key': om['merchant_key'], 'currency': 'OUV'})
        r = requests.post(api_url, headers=headers, data=json.dumps(data), verify=False, timeout=130)
        resp = r.json()
        momo_tx.message = resp['message']
        if resp['status'] == 201:
            request.session['pay_token'] = resp['pay_token']
            request.session['notif_token'] = resp['notif_token']
            momo_tx.status = MoMoTransaction.SUCCESS
            momo_tx.save()
            Thread(target=check_transaction_status, args=(request, )).start()
            return HttpResponseRedirect(resp['payment_url'])
        else:
            momo_tx.status = MoMoTransaction.API_ERROR
            momo_tx.save()
    else:
        try:
            om = json.loads(PaymentMean.objects.get(slug=ORANGE_MONEY).credentials)
        except:
            return HttpResponse("Error, Could not parse Orange Money API parameters.")
        try:
            headers.update({'Authorization': 'Bearer ' + om['access_token']})
            data.update({'merchant_key': om['merchant_key'], 'currency': 'XAF'})
            logger.debug("OM: Initiating payment of %dF from %s" % (amount, username))
            r = requests.post(api_url, headers=headers, data=json.dumps(data), verify=False, timeout=130)
            resp = r.json()
            momo_tx.message = resp['message']
            if resp['status'] == 201:
                request.session['pay_token'] = resp['pay_token']
                request.session['notif_token'] = resp['notif_token']
                Thread(target=check_transaction_status, args=(request, )).start()
                return HttpResponseRedirect(resp['payment_url'])
            else:
                momo_tx.status = MoMoTransaction.API_ERROR
                momo_tx.save()
                messages.error(request, 'API Error')
                return HttpResponseRedirect(request.session['cancel_url'])
        except SSLError:
            momo_tx.status = MoMoTransaction.SSL_ERROR
            messages.error(request, 'SSL Error.')
            return HttpResponseRedirect(request.session['cancel_url'])
        except Timeout:
            momo_tx.status = MoMoTransaction.TIMEOUT
            momo_tx.save()
            messages.error(request, 'Timeout. Orange Money Server is taking too long to respond.')
            return HttpResponseRedirect(request.session['cancel_url'])
        except RequestException:
            import traceback
            momo_tx.status = MoMoTransaction.REQUEST_EXCEPTION
            msg = traceback.format_exc()
            momo_tx.message = msg
            momo_tx.save()
            messages.error(request, msg)
            return HttpResponseRedirect(request.session['cancel_url'])
        except:
            import traceback
            momo_tx.status = MoMoTransaction.SERVER_ERROR
            msg = traceback.format_exc()
            if momo_tx.message:
                messages.error(request, momo_tx.message)
            else:
                messages.error(request, msg)
            return HttpResponseRedirect(request.session['cancel_url'])


def check_transaction_status(request):
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    api_url = getattr(settings, 'ORANGE_MONEY_API_URL') + '/transactionstatus'
    amount = int(request.session['amount'])
    token = request.session['pay_token']
    tx_id = request.session['tx_id']
    if not getattr(settings, 'OM_FEES_ON_MERCHANT', False):
        factor = 1 + getattr(settings, 'OM_FEES', 3.5) / 100
        amount = int(math.ceil(amount * factor))
        if amount % 50 != 0:
            amount = (amount / 50 + 1) * 50
    object_id = request.session['object_id']
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    data = {'order_id': object_id,
            'amount': amount,
            'pay_token': token}
    om = json.loads(PaymentMean.objects.get(slug=ORANGE_MONEY).credentials)
    t0 = datetime.now()
    logger.debug("OM: Started checking status for payment %s of %dF from %s" % (token, amount, username))
    while True:
        time.sleep(2)
        t1 = datetime.now()
        diff = t1 - t0
        if diff.seconds >= (10 * 60):
            MoMoTransaction.objects.using('wallets').filter(pk=tx_id)\
                .update(is_running=False, status=MoMoTransaction.DROPPED)
            logger.debug("OM: Payment %s of %dF from %s timed out after waiting for 10mn" % (token, amount, username))
            break
        try:
            headers.update({'Authorization': 'Bearer ' + om['access_token']})
            r = requests.post(api_url, headers=headers, data=json.dumps(data), verify=False, timeout=130)
            resp = r.json()
            status = resp['status']
            if status == 'FAILED':
                logger.debug("OM: Payment %s of %dF from %s failed" % (token, amount, username))
                MoMoTransaction.objects.using('wallets').filter(pk=tx_id)\
                    .update(message=resp['message'], is_running=False, status=MoMoTransaction.FAILURE)
                break
            if status == 'SUCCESS':
                logger.debug("OM: Successful payment %s of %dF from %s" % (token, amount, username))
                processor_tx_id = resp['txnid']
                payments_conf = getattr(settings, 'PAYMENTS', None)
                if payments_conf:
                    conf = request.session['payment_conf']
                    path = payments_conf[conf]['after']
                else:
                    path = getattr(settings, 'MOMO_AFTER_CASH_OUT')
                momo_after_checkout = import_by_path(path)
                with transaction.atomic():
                    try:
                        MoMoTransaction.objects.using('wallets').filter(pk=tx_id)\
                            .update(processor_tx_id=processor_tx_id, message='OK', is_running=False, status=MoMoTransaction.SUCCESS)
                    except:
                        logger.error("Orange Money: Could not mark transaction as Successful. User: %s, Amt: %d" % (request.user.username, int(request.session['amount'])), exc_info=True)
                    else:
                        try:
                            momo_after_checkout(request, signature=request.session['signature'], tx_id=tx_id)
                        except:
                            MoMoTransaction.objects.using('wallets').filter(pk=tx_id)\
                                .update(message=traceback.format_exc())
                            logger.error("Orange Money: Error while running callback. User: %s, Amt: %d" % (request.user.username, int(request.session['amount'])), exc_info=True)
                break
        except:
            logger.error("Orange Money: Failure while querying transaction status", exc_info=True)
            continue
