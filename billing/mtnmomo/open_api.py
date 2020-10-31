import json
import traceback
import time
from datetime import datetime
from threading import Thread

import requests
import uuid
from django.conf import settings
from django.urls import reverse
from django.db import transaction
from django.http import HttpResponse
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_string as import_by_path
from django.utils.translation import ugettext as _
from django.views.decorators.csrf import csrf_exempt
from requests.exceptions import SSLError

from requests import RequestException
from requests import Timeout

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.utils import get_service_instance, add_database
from ikwen.core.models import Service
from ikwen.billing.models import PaymentMean, MoMoTransaction

import logging
logger = logging.getLogger('ikwen')

MTN_MOMO = 'mtn-momo'
if getattr(settings, 'DEBUG', False):
    _OPEN_API_URL = 'https://sandbox.momodeveloper.mtn.com'
else:
    _OPEN_API_URL = 'https://proxy.momoapi.mtn.com'


def init_momo_transaction(request, *args, **kwargs):
    phone = slugify(request.GET['phone'])
    if phone[:3] == '237':
        phone = phone[3:]
    request.session['phone'] = phone
    return init_request_payment(request, *args, **kwargs)


def init_request_payment(request, *args, **kwargs):
    payment_mean = PaymentMean.objects.get(slug=MTN_MOMO)
    refresh_access_token(payment_mean)  # Eventually refresh access token if near to expire
    weblet = get_service_instance()
    try:
        momo_credentials = json.loads(payment_mean.credentials)
    except:
        return HttpResponse("%s - Error, Could not parse MoMo API parameters." % weblet.project_name_slug)

    service = get_service_instance(UMBRELLA)
    phone = request.GET['phone']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    amount = request.session['amount']
    task_id = str(uuid.uuid4())
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    payments_conf = getattr(settings, 'PAYMENTS', None)
    if payments_conf:
        conf = request.session['payment_conf']
        callback = payments_conf[conf]['after']
    else:
        callback = getattr(settings, 'MOMO_AFTER_CASH_OUT')
    with transaction.atomic(using='wallets'):
        try:
            tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
            return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')
        except MoMoTransaction.DoesNotExist:
            tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT,
                                                                 phone=phone, amount=amount, model=model_name,
                                                                 object_id=object_id, wallet=MTN_MOMO,
                                                                 username=username, task_id=task_id, callback=callback)
        except MoMoTransaction.MultipleObjectsReturned:
            tx = MoMoTransaction.objects.using('wallets').filter(object_id=object_id)[0]
    if getattr(settings, 'DEBUG', False):
        request_payment(request, weblet, momo_credentials, tx)
    else:
        payment_handler = Thread(target=request_payment, args=(request, weblet, momo_credentials, tx, ))
        payment_handler.setDaemon(True)
        payment_handler.start()
    return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')


def request_payment(request, weblet, momo_credentials, tx):
    """
    Calls the HTTP MTN Mobile Money API and updates the MoMoTransaction
    status in the database upon completion of the request.
    """
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 100
    else:
        amount = int(tx.amount)
    phone = slugify(tx.phone).replace('-', '')
    if len(phone) == 9:
        phone = '237' + phone
    data = {'amount': amount, 'externalId': tx.object_id,
            'payer': {'partyIdType': 'MSISDN', 'partyId': phone},
            'payerMessage': _('Payment of %(amount)s on %(vendor)s' % {'amount': amount, 'vendor': weblet.project_name}),
            'payeeNote': 'Payment on %s: %s from %s' % (weblet.project_name, amount, phone)}
    callback_url = weblet.url + reverse('billing:process_notification', args=(tx.id, ))
    logger.debug("MoMo Callback URL: " + callback_url)
    headers = {
        'Authorization': 'Bearer ' + momo_credentials['access_token'],
        # 'X-Callback-Url': callback_url,   Callback tend not to work at times, so check transaction status rather
        'X-Reference-Id': tx.task_id,
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': momo_credentials['subscription_key']
    }
    endpoint = _OPEN_API_URL + '/collection/v1_0/requesttopay'
    if getattr(settings, 'UNIT_TESTING', False):
        tx.processor_tx_id = 'tx_1'
        tx.task_id = 'task_1'
        tx.message = 'Success'
        tx.is_running = False
        tx.status = MoMoTransaction.SUCCESS
        request.session['next_url'] = 'http://nextUrl'
        momo_after_checkout = import_by_path(tx.callback)
        momo_after_checkout(request, transaction=tx, signature=request.session['signature'])
    elif getattr(settings, 'DEBUG', False):
        headers.update({'X-Target-Environment': 'sandbox'})
        data.update({'currency': 'EUR'})
        r = requests.post(endpoint, headers=headers, json=data, verify=False, timeout=300)
        if r.status_code == 202:
            logger.debug("%s - MTN MoMo: Request to pay submitted. "
                         "Amt: %s, Uname: %s, Phone: %s" % (weblet.project_name, amount, username, tx.phone))
            Thread(target=query_transaction_status, args=(request, weblet, momo_credentials, tx)).start()
        else:
            logger.error("%s - MTN MoMo: Transaction of %dF from %s: %s failed with Code %s" % (weblet.project_name, amount, username, tx.phone, r.status_code))
            tx.status = MoMoTransaction.API_ERROR
    else:
        try:
            username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
            logger.debug("MTN MoMo: Initiating payment of %dF from %s: %s" % (amount, username, tx.phone))
            headers.update({'X-Target-Environment': 'mtncameroon'})
            data.update({'currency': 'XAF'})
            r = requests.post(endpoint, headers=headers, json=data, verify=False)
            if r.status_code == 202:
                logger.debug("%s - MTN MoMo: Request to pay submitted. "
                             "Amt: %s, Uname: %s, Phone: %s" % (weblet.project_name, amount, username, tx.phone))
                query_transaction_status(request, weblet, momo_credentials, tx)
            else:
                logger.error("%s - MTN MoMo: Transaction of %dF from %s: %s failed with Code %s" % (weblet.project_name, amount, username, tx.phone, r.status_code))
                tx.status = MoMoTransaction.API_ERROR
        except SSLError:
            tx.status = MoMoTransaction.SSL_ERROR
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.project_name, amount, username, tx.phone), exc_info=True)
        except Timeout:
            tx.status = MoMoTransaction.TIMEOUT
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.project_name, amount, username, tx.phone), exc_info=True)
        except RequestException:
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
            tx.message = traceback.format_exc()
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.project_name, amount, username, tx.phone), exc_info=True)
        except:
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.project_name, amount, username, tx.phone), exc_info=True)

    tx.save(using='wallets')


def query_transaction_status(request, weblet, momo_credentials, tx):
    """
    This function verifies the status of the transaction on MTN MoMo Server
    When the transaction completes sucessfully the callback is run
    """
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    query_url = _OPEN_API_URL + '/collection/v1_0/requesttopay/' + tx.task_id
    t0 = datetime.now()
    logger.debug("MTN MoMo: Started checking status for "
                 "transaction %s of %sF from %s" % (tx.id, tx.amount, username))
    while True:
        time.sleep(2)
        t1 = datetime.now()
        diff = t1 - t0
        if diff.seconds >= (10 * 60):
            MoMoTransaction.objects.using('wallets').filter(pk=tx.id)\
                .update(is_running=False, status=MoMoTransaction.DROPPED)
            logger.debug("MTN MoMo: Transaction %s of %sF from %s timed out after waiting for 10mn" % (tx.id, tx.amount, username))
            break
        try:
            headers = {
                'Authorization': 'Bearer ' + momo_credentials['access_token'],
                'X-Reference-Id': tx.task_id,
                'X-Target-Environment': 'sandbox' if getattr(settings, 'DEBUG', False) else 'mtncameroon',
                'Content-Type': 'application/json',
                'Ocp-Apim-Subscription-Key': momo_credentials['subscription_key']
            }
            r = requests.get(query_url, headers=headers, verify=False)
            resp = r.json()
            if resp['status'] == 'PENDING':
                continue
            elif resp['status'] == 'SUCCESSFUL':
                momo_after_checkout = import_by_path(tx.callback)
                with transaction.atomic(using='wallets'):
                    tx.is_running = False
                    tx.processor_tx_id = resp['financialTransactionId']
                    tx.status = MoMoTransaction.SUCCESS
                    tx.save(using='wallets')
                    try:
                        momo_after_checkout(request, transaction=tx, signature=request.session['signature'])
                        tx.message = 'OK'
                    except:
                        tx.message = traceback.format_exc()
                        logger.error("%s - MTN MoMo: Failure while running callback. User: %s, Amt: %d" % (
                            weblet.project_name, tx.username, tx.amount), exc_info=True)
            else:
                logger.error("MTN MoMo: Query transaction status failed with status %s" % resp['status'], exc_info=True)
                tx.is_running = False
                tx.status = MoMoTransaction.API_ERROR
                tx.message = resp['reason']['message']
            tx.save(using='wallets')
            break
        except:
            logger.error("MTN MoMo: Failure while querying transaction status", exc_info=True)
            continue


@csrf_exempt
def process_notification(request, *args, **kwargs):
    weblet = get_service_instance()
    logger.debug("%s - MTN MoMo - New notification: %s" % (weblet.project_name, request.META['REQUEST_URI']))
    logger.debug("%s - MTN MoMo - New notification Body: %s" % (weblet.project_name, request.body))
    tx_id = kwargs['tx_id']
    try:
        resp = json.loads(request.body)
        tx = MoMoTransaction.objects.using('wallets').get(pk=tx_id)
    except ValueError:
        notice = "Could not parse callback data."
        logger.error("%s - MTN MoMo: %s" % (weblet.project_name, notice), exc_info=True)
        return HttpResponse(notice)
    except MoMoTransaction.DoesNotExist:
        logger.error("%s - MTN MoMo: Could not find transaction with id %s." % (weblet.project_name_slug, tx_id), exc_info=True)
        return HttpResponse("Notification successfully received.")

    tx.is_running = False
    if resp['status'] == 'SUCCESSFUL':
        tx.processor_tx_id = resp['financialTransactionId']
        tx.status = MoMoTransaction.SUCCESS
        tx.save(using='wallets')
        momo_after_checkout = import_by_path(tx.callback)
        try:
            momo_after_checkout(request, transaction=tx)
            tx.message = 'OK'
        except:
            tx.message = traceback.format_exc()
            logger.error("%s - MTN MoMo: Failure while running callback. User: %s, Amt: %d" % (weblet.project_name, tx.username, tx.amount), exc_info=True)
    else:
        tx.status = MoMoTransaction.API_ERROR
        tx.message = resp['status']
    tx.save(using='wallets')
    return HttpResponse("Notification successfully received.")


@transaction.atomic
def check_momo_transaction_status(request, *args, **kwargs):
    tx_id = request.GET['tx_id']
    tx = MoMoTransaction.objects.using('wallets').get(pk=tx_id)

    # When a MoMoTransaction is created, its status is None or empty string
    # So perform a check first to make sure a status has been set
    if tx.status:
        if tx.status == MoMoTransaction.SUCCESS:
            resp_dict = {'success': True, 'return_url': request.session['return_url']}
            return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
        resp_dict = {'error': tx.status, 'message': ''}
        if getattr(settings, 'DEBUG', False):
            resp_dict['message'] = tx.message
        elif tx.status == MoMoTransaction.FAILURE:
            resp_dict['message'] = 'Ooops! You may have refused authorization. Please try again.'
        elif tx.status == MoMoTransaction.API_ERROR:
            resp_dict['message'] = 'Your balance may be insufficient. Please check and try again.'
        elif tx.status == MoMoTransaction.TIMEOUT:
            resp_dict['message'] = 'MTN Server is taking too long to respond. Please try again later'
        elif tx.status == MoMoTransaction.REQUEST_EXCEPTION:
            resp_dict['message'] = 'Could not init transaction with MTN Server. Please try again later'
        elif tx.status == MoMoTransaction.SERVER_ERROR:
            resp_dict['message'] = 'Unknown server error. Please try again later'
        return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
    return HttpResponse(json.dumps({'running': True}), 'content-type: text/json')


def refresh_access_token(payment_mean):
    diff = datetime.now() - payment_mean.updated_on
    credentials = json.loads(payment_mean.credentials)
    access_token_timeout = getattr(settings, 'MOMO_ACCESS_TOKEN_TIMEOUT', 3000)
    if credentials.get('access_token') and diff.total_seconds() < access_token_timeout:
        return
    auth_header = credentials['auth_header'].replace('Basic ', '').strip()
    subscription_key = credentials['subscription_key'].strip()
    headers = {'Authorization': 'Basic ' + auth_header, 'Ocp-Apim-Subscription-Key': subscription_key}
    endpoint = _OPEN_API_URL + "/collection/token/"
    logger.debug("MoMo: Updating Access Token")
    try:
        r = requests.post(endpoint, headers=headers, verify=False)
        resp = r.json()
        access_token = resp['access_token']
        credentials['access_token'] = access_token
        payment_mean.credentials = json.dumps(credentials)
        payment_mean.save()
        logger.debug("MoMo: access_token successfully updated to %s" % access_token)

        # Propagate that change to all ikwen apps using a centralized OM account.
        # Those are the one with config.is_pro_version = False
        config = get_service_instance().config
        if config.is_pro_version:
            return
        Thread(target=propagate_access_token_refresh, args=(payment_mean, )).start()
    except:
        logger.error("MoMo: Failed to update access_token", exc_info=True)


def propagate_access_token_refresh(payment_mean):
    for weblet in Service.objects.using(UMBRELLA).all():
        try:
            config = weblet.basic_config
            if config.is_pro_version:
                continue
            db = weblet.database
            add_database(db)
            PaymentMean.objects.using(db).filter(slug=MTN_MOMO).update(credentials=payment_mean.credentials)
        except:
            pass


def test_request_payment():
    amount = 100
    payment_mean = PaymentMean.objects.get(slug=MTN_MOMO)
    mtn_momo = json.loads(payment_mean.credentials)
    refresh_access_token(payment_mean)  # Eventually refresh access token if near to expire
    weblet = get_service_instance()
    phone = '237675187705'
    tx_uuid = str(uuid.uuid4())
    data = {'amount': amount, 'currency': 'EUR', 'externalId': '000001',
            'payer': {'partyIdType': 'MSISDN', 'partyId': phone},
            'payerMessage': _('Payment of %(amount)s on %(vendor)s' % {'amount': amount, 'vendor': weblet.project_name}),
            'payeeNote': 'Payment on %s: %s from %s' % (weblet.project_name, amount, phone)}
    callback_url = 'http://payment.ikwen.com' + reverse('billing:process_notification', args=(1,))
    headers = {
        'Authorization': 'Bearer ' + mtn_momo['access_token'],
        'X-Callback-Url': callback_url,
        'X-Reference-Id': tx_uuid,
        'X-Target-Environment': 'sandbox',
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': mtn_momo['subscription_key']
    }
    endpoint = 'https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay'
    r = requests.post(endpoint, headers=headers, json=data, verify=False, timeout=300)
    if r.status_code == 202:
        print("MTN MoMo: Request to pay submitted. Amt: %s, Phone: %s" % (amount, phone))
    else:
        print("MTN MoMo: Transaction of %dF failed with Code %s" % (amount, r.status_code))


if __name__ == "__main__":
    test_request_payment()
