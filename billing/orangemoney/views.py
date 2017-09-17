import json
from datetime import datetime
from threading import Thread

import requests
import time
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.http.response import HttpResponseRedirect
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
        amount = request.session['amount']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    username = request.user.username if request.user.is_authenticated() else None
    momo_tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT,
                                                              phone=phone, amount=amount, model=model_name,
                                                              object_id=object_id, wallet=ORANGE_MONEY, username=username)
    request.session['tx_id'] = momo_tx.id
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    notif_url = request.session['notif_url']
    notif_url += '/%d' % momo_tx.id
    data = {'order_id': object_id,
            'amount': int(amount),
            'lang': 'fr',
            'reference': service.config.company_name.upper(),
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
        except SSLError:
            momo_tx.status = MoMoTransaction.SSL_ERROR
        except Timeout:
            momo_tx.status = MoMoTransaction.TIMEOUT
        except RequestException:
            import traceback
            momo_tx.status = MoMoTransaction.REQUEST_EXCEPTION
            momo_tx.message = traceback.format_exc()
        except:
            import traceback
            momo_tx.status = MoMoTransaction.SERVER_ERROR
            momo_tx.message = traceback.format_exc()


def check_transaction_status(request):
    api_url = getattr(settings, 'ORANGE_MONEY_API_URL') + '/transactionstatus'
    amount = request.session['amount']
    object_id = request.session['object_id']
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    data = {'order_id': object_id,
            'amount': int(amount),
            'pay_token': request.session['pay_token']}
    om = json.loads(PaymentMean.objects.get(slug=ORANGE_MONEY).credentials)
    t0 = datetime.now()
    while True:
        time.sleep(1)
        t1 = datetime.now()
        diff = t1 - t0
        if diff.seconds >= (10 * 60):
            break
        try:
            # tx_status_log.info("Checking transaction")
            headers.update({'Authorization': 'Bearer ' + om['access_token']})
            r = requests.post(api_url, headers=headers, data=json.dumps(data), verify=False, timeout=130)
            resp = r.json()
            status = resp['status']
            if status == 'FAILED':
                break
            if status == 'SUCCESS':
                request.session['processor_tx_id'] = resp['txnid']
                path = getattr(settings, 'MOMO_AFTER_CASH_OUT')
                momo_after_checkout = import_by_path(path)
                with transaction.atomic():
                    try:
                        tx_id = request.session['tx_id']
                        MoMoTransaction.objects.using('wallets').filter(pk=tx_id).update(is_running=False)
                        momo_after_checkout(request, signature=request.session['signature'], tx_id=tx_id)
                    except:
                        logger.error("Orange Money: Error while running callback function", exc_info=True)
                break
        except:
            logger.error("Orange Money: Failure while querying transaction status", exc_info=True)
            continue
