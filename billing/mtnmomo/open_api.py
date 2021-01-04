import base64
import json
import traceback
import time
from datetime import datetime
from threading import Thread

import requests
import uuid

from bson import ObjectId
from django.conf import settings
from django.urls import reverse
from django.db import transaction
from django.http import HttpResponse
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_string as import_by_path
from django.utils.translation import ugettext as _
from django.views.decorators.csrf import csrf_exempt
from ikwen.core.templatetags.url_utils import strip_base_alias

from ikwen.cashout.utils import submit_cashout_request_for_manual_processing

from ikwen.conf.settings import IKWEN_SERVICE_ID
from ikwen.billing.mobile_payment import get_username_and_callback
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


def init_momo_payment(request, *args, **kwargs):
    phone = slugify(request.GET['phone'])
    if phone[:3] == '237':
        phone = phone[3:]
    request.session['phone'] = phone
    payment_mean = PaymentMean.objects.get(slug=MTN_MOMO)
    refresh_collection_token(payment_mean)  # Eventually refresh access token if near to expire
    weblet = get_service_instance()
    try:
        momo_credentials = json.loads(payment_mean.credentials)
    except:
        return HttpResponse(json.dumps({'error': "Failed to parse MoMo API parameters."}))

    service = get_service_instance(UMBRELLA)
    phone = request.GET['phone']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    amount = request.session['amount']
    reference_id = str(uuid.uuid4())
    username, callback = get_username_and_callback(request)
    with transaction.atomic(using='wallets'):
        try:
            tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
        except MoMoTransaction.DoesNotExist:
            tx = MoMoTransaction.objects.using('wallets')\
                .create(service_id=service.id, type=MoMoTransaction.CASH_OUT, phone=phone, amount=amount,
                        model=model_name, object_id=object_id, wallet=MTN_MOMO, username=username,
                        task_id=reference_id, callback=callback)
        except MoMoTransaction.MultipleObjectsReturned:
            tx = MoMoTransaction.objects.using('wallets').filter(object_id=object_id)[0]
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 100
    else:
        amount = int(tx.amount)
    headers = {
        'Authorization': 'Bearer ' + momo_credentials['access_token'],
        'X-Reference-Id': reference_id,
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': momo_credentials['subscription_key']
    }
    phone = slugify(tx.phone).replace('-', '')
    if len(phone) == 9:
        phone = '237' + phone
    data = {'amount': amount, 'externalId': tx.object_id,
            'payer': {'partyIdType': 'MSISDN', 'partyId': phone},
            'payerMessage': _('Payment of %(amount)s on %(vendor)s' % {'amount': amount, 'vendor': weblet.project_name}),
            'payeeNote': 'Payment on %s: %s from %s' % (weblet.project_name, amount, phone)}
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
                         "Amt: %s, Uname: %s, Phone: %s" % (weblet.ikwen_name, amount, username, tx.phone))
            query_transaction_status(request, weblet, momo_credentials, tx)
        else:
            tx.is_running = False
            logger.error("%s - MTN MoMo: Transaction of %dF from %s: %s failed with Code %s" % (weblet.ikwen_name, amount, username, tx.phone, r.status_code))
            tx.status = MoMoTransaction.API_ERROR
    else:
        try:
            callback_url = reverse('billing:momo_process_notification', args=(tx.id, ))
            logger.debug("MoMo Callback URL: " + callback_url)
            username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
            logger.debug("MTN MoMo: Initiating payment of %dF from %s: %s" % (amount, username, tx.phone))
            headers.update({
                'X-Callback-Url': weblet.url + strip_base_alias(callback_url),  # Callback may not to work, so we also check transaction status
                'X-Target-Environment': 'mtncameroon'
            })
            data.update({'currency': 'XAF'})
            r = requests.post(endpoint, headers=headers, json=data, verify=False)
            if r.status_code == 202:
                logger.debug("%s - MoMo: Request to pay submitted. "
                             "Amt: %s, Uname: %s, Phone: %s" % (weblet.ikwen_name, amount, username, tx.phone))
                status_checker = Thread(target=query_transaction_status, args=(request, weblet, momo_credentials, tx))
                status_checker.setDaemon(True)
                status_checker.start()
            else:
                logger.error("%s - MoMo: Transaction of %dF from %s: %s failed with Code %s" % (weblet.ikwen_name, amount, username, tx.phone, r.status_code))
                tx.is_running = False
                tx.status = MoMoTransaction.API_ERROR
        except SSLError:
            tx.is_running = False
            tx.status = MoMoTransaction.SSL_ERROR
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except Timeout:
            tx.is_running = False
            tx.status = MoMoTransaction.TIMEOUT
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except RequestException:
            tx.is_running = False
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
            tx.message = traceback.format_exc()
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except:
            tx.is_running = False
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)

    tx.save(using='wallets')
    return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')


def query_transaction_status(request, weblet, momo_credentials, tx):
    """
    This function verifies the status of the transaction on MTN MoMo Server
    When the transaction completes successfully the callback is run
    """
    if tx.type == MoMoTransaction.CASH_OUT:
        op = '/collection/v1_0/requesttopay/'
        op_label = 'payment'
        access_token = momo_credentials['access_token']
        subscription_key = momo_credentials['subscription_key']
    else:
        op = '/disbursement/v1_0/transfer/'
        op_label = 'cashin'
        access_token = momo_credentials['disbursement_access_token']
        subscription_key = momo_credentials['disbursement_subscription_key']
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    query_url = _OPEN_API_URL + op + tx.task_id
    t0 = datetime.now()
    logger.debug("%s - MoMo: Started checking status for "
                 "%s %s of %sF from %s" % (weblet.ikwen_name, op_label, tx.id, tx.amount, username))
    while True:
        time.sleep(4)
        t1 = datetime.now()
        diff = t1 - t0
        try:
            with transaction.atomic(using='wallets'):
                MoMoTransaction.objects.using('wallets').get(pk=tx.id, is_running=True)
        except:
            break
        if diff.seconds >= (10 * 60):
            MoMoTransaction.objects.using('wallets').filter(pk=tx.id)\
                .update(is_running=False, status=MoMoTransaction.DROPPED)
            logger.debug("%s - MoMo: %s %s of %sF from %s timed out after waiting for 10mn" % (weblet.ikwen_name, op_label, tx.id, tx.amount, username))
            break
        try:
            headers = {
                'Authorization': 'Bearer ' + access_token,
                'X-Reference-Id': tx.task_id,
                'X-Target-Environment': 'sandbox' if getattr(settings, 'DEBUG', False) else 'mtncameroon',
                'Content-Type': 'application/json',
                'Ocp-Apim-Subscription-Key': subscription_key
            }
            r = requests.get(query_url, headers=headers, verify=False)
            resp = r.json()
            if resp['status'] == 'PENDING':
                continue
            elif resp['status'] == 'SUCCESSFUL':
                with transaction.atomic(using='wallets'):
                    tx.is_running = False
                    tx.processor_tx_id = resp['financialTransactionId']
                    tx.message = 'OK'
                    tx.status = MoMoTransaction.SUCCESS
                    tx.save(using='wallets')
                    if tx.callback:
                        try:
                            momo_after_checkout = import_by_path(tx.callback)
                            momo_after_checkout(request, transaction=tx, signature=request.session.get('signature'))
                        except:
                            tx.message = traceback.format_exc()
                            logger.error("%s - MoMo: Failure while running callback. User: %s, Amt: %d" % (
                                weblet.project_name, tx.username, tx.amount), exc_info=True)
            else:
                if tx.type == MoMoTransaction.CASH_IN:
                    submit_cashout_request_for_manual_processing(transaction=tx)
                logger.error("%s - MoMo: Query transaction status failed with status %s" % (weblet.ikwen_name, resp['status']), exc_info=True)
                tx.is_running = False
                tx.status = MoMoTransaction.API_ERROR
                tx.message = resp['reason']['message']
            tx.save(using='wallets')
            break
        except:
            logger.error("%s - MoMo: Failure while querying transaction status" % weblet.ikwen_name, exc_info=True)
            continue


@csrf_exempt
@transaction.atomic(using='wallets')
def process_notification(request, *args, **kwargs):
    weblet = get_service_instance()
    logger.debug("%s - MoMo - New notification: %s" % (weblet.ikwen_name, request.META['REQUEST_URI']))
    logger.debug("%s - MoMo - New notification Body: %s" % (weblet.ikwen_name, request.body))
    tx_id = kwargs['tx_id']
    try:
        resp = json.loads(request.body)
        tx = MoMoTransaction.objects.using('wallets').get(pk=tx_id, is_running=True)
    except ValueError:
        notice = "Could not parse callback data."
        logger.error("%s - MTN MoMo: %s" % (weblet.ikwen_name, notice), exc_info=True)
        return HttpResponse(notice)
    except MoMoTransaction.DoesNotExist:
        logger.error("%s - MTN MoMo: Could not find transaction with id %s." % (weblet.ikwen_name, tx_id), exc_info=True)
        return HttpResponse("Notification successfully received.")

    tx.is_running = False
    if resp['status'] == 'SUCCESSFUL' and tx.object_id == resp['externalId']:
        tx.processor_tx_id = resp['financialTransactionId']
        tx.status = MoMoTransaction.SUCCESS
        tx.message = 'OK'
        tx.save(using='wallets')
        if tx.callback:
            try:
                momo_after_checkout = import_by_path(tx.callback)
                momo_after_checkout(request, transaction=tx)
            except:
                tx.message = traceback.format_exc()
                logger.error("%s - MTN MoMo: Failure while running callback. User: %s, Amt: %d" % (weblet.ikwen_name, tx.username, tx.amount), exc_info=True)
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
    payment_mean = PaymentMean.objects.using(UMBRELLA).get(slug=MTN_MOMO)
    callback = 'ikwen.cashout.utils.notify_cashout_and_reset_counters'
    momo_credentials = json.loads(payment_mean.credentials)
    token = generate_disbursement_token(payment_mean)
    reference_id = str(uuid.uuid4())
    model_name = 'cashout.CashOutRequest'
    with transaction.atomic(using='wallets'):
        tx = MoMoTransaction.objects.using('wallets') \
            .create(service_id=weblet.id, type=MoMoTransaction.CASH_IN, username=username, phone=phone, amount=amount,
                    model=model_name, object_id=cashout_request.id, wallet=MTN_MOMO, task_id=reference_id,
                    status=None, callback=callback)
    headers = {
        'Authorization': 'Bearer ' + token,
        'X-Reference-Id': reference_id,
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': momo_credentials['disbursement_subscription_key']
    }
    phone = slugify(tx.phone).replace('-', '')
    if len(phone) == 9:
        phone = '237' + phone
    data = {'amount': amount, 'externalId': tx.object_id,
            'payee': {'partyIdType': 'MSISDN', 'partyId': phone},
            'payerMessage': _('Cashin of %(amount)s on %(vendor)s' % {'amount': amount, 'vendor': weblet.project_name}),
            'payeeNote': 'Cashin on %s: %s from %s' % (weblet.project_name, amount, phone)}
    endpoint = _OPEN_API_URL + '/disbursement/v1_0/transfer'
    if getattr(settings, 'UNIT_TESTING', False):
        tx.processor_tx_id = 'tx_1'
        tx.message = 'OK'
        tx.is_running = False
        tx.status = MoMoTransaction.SUCCESS
        if tx.callback:
            momo_after_checkout = import_by_path(tx.callback)
            momo_after_checkout(request, transaction=tx)
    elif getattr(settings, 'DEBUG', False):
        headers.update({'X-Target-Environment': 'sandbox'})
        data.update({'currency': 'EUR'})
        r = requests.post(endpoint, headers=headers, json=data, verify=False, timeout=300)
        if r.status_code == 202:
            logger.debug("%s - MoMo: Request to cashin submitted. "
                         "Amt: %s, Uname: %s, Phone: %s" % (weblet.ikwen_name, amount, username, tx.phone))
            query_transaction_status(request, weblet, momo_credentials, tx)
        else:
            tx.is_running = False
            tx.status = MoMoTransaction.API_ERROR
            logger.error("%s - MoMo: Cashin of %d from %s: %s failed with Code %s" % (weblet.ikwen_name, amount, username, tx.phone, r.status_code))
    else:
        try:
            username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
            logger.debug("MoMo: Initiating cashin of %dF from %s: %s" % (amount, username, tx.phone))
            callback_url = reverse('billing:momo_process_notification', args=(tx.id, ))
            headers.update({
                'X-Callback-Url': weblet.url + strip_base_alias(callback_url),  # Callback may not work at times, so we also check transaction status
                'X-Target-Environment': 'mtncameroon'
            })
            data.update({'currency': 'XAF'})
            r = requests.post(endpoint, headers=headers, json=data, verify=False)
            if r.status_code == 202:
                logger.debug("%s - MoMo: Request to cashin submitted. "
                             "Amt: %s, Uname: %s, Phone: %s" % (weblet.ikwen_name, amount, username, tx.phone))
                status_checker = Thread(target=query_transaction_status, args=(request, weblet, momo_credentials, tx))
                status_checker.setDaemon(True)
                status_checker.start()
            else:
                tx.is_running = False
                tx.status = MoMoTransaction.API_ERROR
                logger.error("%s - MoMo: Transaction of %dF from %s: %s failed with Code %s" % (weblet.ikwen_name, amount, username, tx.phone, r.status_code))
        except SSLError:
            tx.is_running = False
            tx.status = MoMoTransaction.SSL_ERROR
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except Timeout:
            tx.is_running = False
            tx.status = MoMoTransaction.TIMEOUT
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except RequestException:
            tx.is_running = False
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
            tx.message = traceback.format_exc()
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
        except:
            tx.is_running = False
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
            logger.error("%s - MoMo: Failed to init transaction of %dF from %s: %s" % (weblet.ikwen_name, amount, username, tx.phone), exc_info=True)
    tx.save(using='wallets')
    return tx


def refresh_collection_token(payment_mean):
    momo = json.loads(payment_mean.credentials)
    auth_header = base64.b64encode('%s:%s' % (momo['api_user'], momo['api_key']))
    subscription_key = momo['subscription_key'].strip()
    headers = {'Authorization': 'Basic ' + auth_header, 'Ocp-Apim-Subscription-Key': subscription_key}
    endpoint = _OPEN_API_URL + "/collection/token/"
    logger.debug("MoMo: Updating Access Token")
    try:
        r = requests.post(endpoint, headers=headers, verify=False)
        resp = r.json()
        access_token = resp['access_token']
        momo['access_token'] = access_token
        payment_mean.credentials = json.dumps(momo)
        payment_mean.save()
    except:
        logger.error("MoMo: Failed to update access_token", exc_info=True)


def generate_disbursement_token(payment_mean):
    momo = json.loads(payment_mean.credentials)
    auth_header = base64.b64encode('%s:%s' % (momo['disbursement_api_user'], momo['disbursement_api_key']))
    subscription_key = momo['disbursement_subscription_key'].strip()
    headers = {'Authorization': 'Basic ' + auth_header, 'Ocp-Apim-Subscription-Key': subscription_key}
    endpoint = _OPEN_API_URL + "/disbursement/token/"
    logger.debug("MoMo: Requesting Disbursement Access Token")
    r = requests.post(endpoint, headers=headers, verify=False)
    resp = r.json()
    momo['disbursement_access_token'] = resp['access_token']
    payment_mean.credentials = json.dumps(momo)
    payment_mean.save()
    return resp['access_token']


def test_request_payment():
    amount = 100
    payment_mean = PaymentMean.objects.get(slug=MTN_MOMO)
    mtn_momo = json.loads(payment_mean.credentials)
    refresh_collection_token(payment_mean)  # Eventually refresh access token if near to expire
    weblet = get_service_instance()
    phone = '237675187705'
    tx_uuid = str(uuid.uuid4())
    data = {'amount': amount, 'currency': 'EUR', 'externalId': '000001',
            'payer': {'partyIdType': 'MSISDN', 'partyId': phone},
            'payerMessage': _('Payment of %(amount)s on %(vendor)s' % {'amount': amount, 'vendor': weblet.project_name}),
            'payeeNote': 'Payment on %s: %s from %s' % (weblet.ikwen_name, amount, phone)}
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
