import base64
import json
import traceback
import logging
import time
from datetime import datetime
from threading import Thread

import requests
from requests.exceptions import SSLError
from requests import RequestException
from requests import Timeout

from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.db import transaction
from django.http import HttpResponse
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_by_path
from django.views.decorators.csrf import csrf_exempt

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.utils import get_service_instance
from ikwen.billing.mobile_payment import get_username_and_callback
from ikwen.billing.models import PaymentMean, MoMoTransaction
from ikwen.cashout.utils import submit_cashout_request_for_manual_processing

logger = logging.getLogger('ikwen')

ORANGE_MONEY = 'orange-money'
UNKNOWN_PHONE = '<Unknown>'

if getattr(settings, 'DEBUG', False):
    _OM_API_URL = ' https://apiw.orange.cm'
else:
    _OM_API_URL = ' https://apiw.orange.cm'

BASE_PATH = '/omcoreapis/1.0.2'


def init_om_payment(request, *args, **kwargs):
    phone = request.GET['phone']
    weblet = get_service_instance()
    payment_mean = PaymentMean.objects.get(slug=ORANGE_MONEY)
    try:
        om_credentials = json.loads(payment_mean.credentials)
    except:
        return HttpResponse(json.dumps({'error': "Could not parse OM API parameters."}))
    try:
        generate_access_token(payment_mean)
    except:
        notice = "Failed to generate access_token."
        logger.error("%s - OM: %s" % (weblet.ikwen_name, notice), exc_info=True)
        return HttpResponse(json.dumps({'error': notice}))
    endpoint = _OM_API_URL + BASE_PATH + '/mp/init'
    headers = build_query_headers(payment_mean)
    try:
        r = requests.post(endpoint, headers=headers, verify=False)
        resp = r.json()
        pay_token = resp['data']['payToken']
    except:
        notice = "Failed to get pay_token for payment."
        logger.error("%s - OM: %s" % (weblet.ikwen_name, notice), exc_info=True)
        return HttpResponse(json.dumps({'error': notice}))

    if getattr(settings, 'DEBUG', False):
        amount = 1
    elif getattr(settings, 'DEBUG_MOMO', False):
        amount = 100
    else:
        amount = int(request.GET['amount'])
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    username, callback = get_username_and_callback(request)
    with transaction.atomic(using='wallets'):
        try:
            tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
        except MoMoTransaction.DoesNotExist:
            tx = MoMoTransaction.objects.using('wallets')\
                .create(service_id=weblet.id, type=MoMoTransaction.CASH_OUT, phone=phone, amount=amount,
                        model=model_name, object_id=object_id, task_id=pay_token,  wallet=ORANGE_MONEY,
                        username=username, callback=callback)
        except MoMoTransaction.MultipleObjectsReturned:
            tx = MoMoTransaction.objects.using('wallets').filter(object_id=object_id)[0]
    notif_url = weblet.url + reverse('billing:om_process_notification', args=(tx.id, ))
    data = {
        'subscriberMsisdn': phone,
        'channelUserMsisdn': om_credentials['channelUserMsisdn'],
        'pin': om_credentials['channelUserPin'],
        'amount': str(amount),
        'orderId': str(tx.id).zfill(20),  # Cannot user object_id because only 20 chars are allowed
        'description': model_name,
        'payToken': pay_token,
        'notifUrl': notif_url
    }
    endpoint = _OM_API_URL + BASE_PATH + '/mp/pay'
    if getattr(settings, 'DEBUG', False):
        r = requests.post(endpoint, headers=headers, json=data, verify=False)
        resp = r.json()
        tx.message = resp['message']
        tx.processor_tx_id = resp['data']['txnid']
        if r.status_code == 200 and resp['data']['inittxnstatus'] == '200':
            query_transaction_status(request, weblet, payment_mean, tx)
        else:
            tx.is_running = False
            tx.status = MoMoTransaction.API_ERROR
    else:
        try:
            logger.debug("OM: Initiating payment of %dF from %s" % (amount, username))
            r = requests.post(endpoint, headers=headers, json=data, verify=False)
            resp = r.json()
            tx.message = resp['message']
            tx.processor_tx_id = resp['data']['txnid']
            if resp['data']['inittxnstatus'] == '200':
                status_checker = Thread(target=query_transaction_status, args=(request, weblet, payment_mean, tx))
                status_checker.setDaemon(True)
                status_checker.start()
            else:
                tx.is_running = False
                tx.status = MoMoTransaction.API_ERROR
                messages.error(request, 'API Error')
        except SSLError:
            tx.is_running = False
            tx.status = MoMoTransaction.SSL_ERROR
            logger.error("%s - OM: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except Timeout:
            tx.is_running = False
            tx.status = MoMoTransaction.TIMEOUT
            logger.error("%s - OM: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except RequestException:
            tx.is_running = False
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
            tx.message = traceback.format_exc()
            logger.error("%s - OM: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except:
            tx.is_running = False
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
            logger.error("%s - OM: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
    tx.save(using='wallets')
    return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')


def query_transaction_status(request, weblet, payment_mean, tx):
    op = '/mp/paymentstatus/' if tx.type == MoMoTransaction.CASH_OUT else '/cashin/paymentstatus/'
    op_label = 'payment' if tx.type == MoMoTransaction.CASH_OUT else 'cashin'
    query_url = _OM_API_URL + BASE_PATH + op + tx.task_id
    headers = build_query_headers(payment_mean)
    t0 = datetime.now()
    logger.debug("%s - OM: Started checking status for %s %s of %dF from %s" % (weblet.ikwen_name, op_label, tx.task_id, tx.amount, tx.username))
    while True:
        time.sleep(4)
        t1 = datetime.now()
        diff = t1 - t0
        try:
            with transaction.atomic(using='wallets'):
                MoMoTransaction.objects.using('wallets').get(pk=tx.id, is_running=True)
        except:
            break
        if diff.seconds >= (7 * 60):
            MoMoTransaction.objects.using('wallets').filter(pk=tx.id)\
                .update(is_running=False, status=MoMoTransaction.DROPPED)
            logger.debug("%s - OM: %s %s of %dF from %s timed out after waiting for 7mn" % (weblet.ikwen_name, op_label, tx.task_id, tx.amount, tx.username))
            break
        try:
            r = requests.get(query_url, headers=headers, verify=False)
            resp = r.json()
            status = resp['data']['status']
            if status == 'PENDING':
                continue
            if status == 'FAILED':
                logger.debug("%s - OM: %s %s of %dF from %s failed" % (weblet.ikwen_name, op_label, tx.task_id, tx.amount, tx.username))
                message = resp['message']
                MoMoTransaction.objects.using('wallets').filter(pk=tx.id) \
                    .update(message=message, is_running=False, status=MoMoTransaction.FAILURE)
                if tx.type == MoMoTransaction.CASH_IN:
                    submit_cashout_request_for_manual_processing(transaction=tx)
            if status.lower().startswith('success'):
                logger.debug("%s - OM: Successful %s %s of %dF from %s" % (weblet.ikwen_name, op_label, tx.task_id, tx.amount, tx.username))
                with transaction.atomic(using='wallets'):
                    try:
                        tx.message = 'OK'
                        tx.is_running = False
                        tx.status = MoMoTransaction.SUCCESS
                        tx.save(using='wallets')
                    except:
                        logger.error("%s - OM: Could not mark transaction as Successful. User: %s, Amt: %s, TXID: %s" % (weblet.ikwen_name, tx.username, tx.amount, tx.id), exc_info=True)
                    else:
                        if tx.callback:
                            try:
                                momo_after_checkout = import_by_path(tx.callback)
                                momo_after_checkout(request, transaction=tx, signature=request.session.get('signature'))
                            except:
                                MoMoTransaction.objects.using('wallets').filter(pk=tx.id)\
                                    .update(message=traceback.format_exc())
                                logger.error("%s - OM: Error while running %s callback. User: %s, Amt: %d" % (weblet.ikwen_name, op_label, tx.username, tx.amount), exc_info=True)
            else:
                if tx.type == MoMoTransaction.CASH_IN:
                    submit_cashout_request_for_manual_processing(transaction=tx)
            break
        except:
            logger.error("%s - OM: Failure while querying transaction status" % weblet.ikwen_name, exc_info=True)
            continue


@csrf_exempt
@transaction.atomic(using='wallets')
def process_notification(request, *args, **kwargs):
    weblet = get_service_instance()
    logger.debug("%s - OM - New notification: %s, Body: %s" % (weblet.ikwen_name, request.META['REQUEST_URI'], request.body))
    tx_id = kwargs['tx_id']
    try:
        resp = json.loads(request.body)
        tx = MoMoTransaction.objects.using('wallets').get(pk=tx_id, is_running=True)
    except ValueError:
        notice = "Could not parse callback data."
        logger.error("%s - OM: %s" % (weblet.ikwen_name, notice), exc_info=True)
        return HttpResponse(notice)
    except MoMoTransaction.DoesNotExist:
        logger.error("%s - OM: Could not find transaction with id %s." % (weblet.ikwen_name, tx_id), exc_info=True)
        return HttpResponse("Notification successfully received.")

    tx.is_running = False
    if resp['status'].lower().startswith('success') and resp['payToken'] == tx.task_id:
        tx.status = MoMoTransaction.SUCCESS
        tx.message = 'OK'
        tx.save(using='wallets')
        try:
            momo_after_checkout = import_by_path(tx.callback)
            momo_after_checkout(request, transaction=tx)
        except:
            tx.message = traceback.format_exc()
            logger.error("%s - OM: Failure while running callback. User: %s, Amt: %d" % (weblet.ikwen_name, tx.username, tx.amount), exc_info=True)
    else:
        if tx.type == MoMoTransaction.CASH_IN:
            submit_cashout_request_for_manual_processing(transaction=tx)
        tx.status = MoMoTransaction.API_ERROR
        tx.message = resp['status']
        tx.save(using='wallets')
    return HttpResponse("Notification successfully received.")


def send_money(request, cashout_request):
    weblet = cashout_request.service
    username = weblet.member.username
    amount = int(cashout_request.amount * (100 - cashout_request.rate) / 100)
    phone = cashout_request.account_number
    payment_mean = PaymentMean.objects.using(UMBRELLA).get(slug=ORANGE_MONEY)
    callback = 'ikwen.cashout.utils.notify_cashout_and_reset_counters'
    om_credentials = json.loads(payment_mean.credentials)
    endpoint = _OM_API_URL + BASE_PATH + '/cashin/init'
    headers = build_query_headers(payment_mean)
    if getattr(settings, 'DEBUG', False):
        amount = 1
    r = requests.post(endpoint, headers=headers, verify=False)
    resp = r.json()
    pay_token = resp['data']['payToken']
    model_name = 'cashout.CashOutRequest'
    with transaction.atomic(using='wallets'):
        tx = MoMoTransaction.objects.using('wallets') \
            .create(service_id=weblet.id, type=MoMoTransaction.CASH_IN, username=username, phone=phone,
                    wallet=ORANGE_MONEY, amount=amount, task_id=pay_token, callback=callback,
                    model=model_name, object_id=cashout_request.id)
    phone = slugify(phone).replace('-', '')
    data = {
        'subscriberMsisdn': phone,
        'channelUserMsisdn': om_credentials['channelUserMsisdn'],
        'pin': om_credentials['channelUserPin'],
        'amount': str(amount),
        'orderId': str(tx.id).zfill(20),
        'description': "Pay to %s" % username,
        'payToken': pay_token
    }
    endpoint = _OM_API_URL + BASE_PATH + '/cashin/pay'
    if getattr(settings, 'DEBUG', False):
        r = requests.post(endpoint, headers=headers, json=data, verify=False)
        resp = r.json()
        tx.message = resp['message']
        status = resp['data']['status']
        tx.processor_tx_id = resp['data']['txnid']
        if status.lower().startswith('success'):
            tx.status = MoMoTransaction.SUCCESS
        else:
            tx.status = MoMoTransaction.API_ERROR
    else:
        try:
            logger.debug("OM: Initiating cashin of %dF to %s:%s. Token: %s" % (amount, username, phone, pay_token))
            r = requests.post(endpoint, headers=headers, json=data, verify=False)
            resp = r.json()
            tx.message = resp['message']
            status = resp['data']['status']
            tx.processor_tx_id = resp['data']['txnid']
            if status.lower().startswith('success'):
                tx.is_running = False
                tx.status = MoMoTransaction.SUCCESS
                if tx.callback:
                    try:
                        momo_after_checkout = import_by_path(tx.callback)
                        momo_after_checkout(request, transaction=tx)
                    except:
                        tx.message = traceback.format_exc()
                        logger.error("%s - OM: Failure while running callback. User: %s, Amt: %d" % (weblet.ikwen_name, tx.username, tx.amount), exc_info=True)
            elif status == 'PENDING':
                tx.status = None
                status_checker = Thread(target=query_transaction_status, args=(request, weblet, payment_mean, tx))
                status_checker.setDaemon(True)
                status_checker.start()
            else:
                tx.is_running = False
                tx.status = MoMoTransaction.API_ERROR
        except SSLError:
            tx.is_running = False
            tx.status = MoMoTransaction.SSL_ERROR
            logger.error("%s - OM: Failed Cashin of %dF to %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except Timeout:
            tx.is_running = False
            tx.status = MoMoTransaction.TIMEOUT
            logger.error("%s - OM: Failed Cashin of %dF to %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except RequestException:
            tx.is_running = False
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
            tx.message = traceback.format_exc()
            logger.error("%s - OM: Failed Cashin of %dF to %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except:
            tx.is_running = False
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
            logger.error("%s - OM: Failed Cashin of %dF to %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
    tx.save(using='wallets')
    return tx


def generate_access_token(payment_mean):
    om = json.loads(payment_mean.credentials)
    auth_header = base64.b64encode('%s:%s' % (om['consumer_key'], om['consumer_secret']))
    headers = {
        'Authorization': 'Basic ' + auth_header,
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {'grant_type': 'client_credentials'}
    endpoint = _OM_API_URL + '/token'
    logger.debug("OM: Requesting Access Token")
    r = requests.post(endpoint, headers=headers, data=data, verify=False)
    resp = r.json()
    om['access_token'] = resp['access_token']
    payment_mean.credentials = json.dumps(om)
    payment_mean.save()
    return resp['access_token']


def build_query_headers(payment_mean):
    om = json.loads(payment_mean.credentials)
    auth_token = base64.b64encode('%s:%s' % (om['api_username'], om['api_password']))
    headers = {
        'Authorization': 'Bearer ' + om['access_token'],
        'X-AUTH-TOKEN': auth_token,
        'Content-Type': 'application/json'
    }
    return headers
