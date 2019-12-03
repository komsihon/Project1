import json
import traceback
import xml.etree.ElementTree as ET
from threading import Thread

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_by_path
from django.views.decorators.csrf import csrf_exempt
from requests.exceptions import SSLError

from requests import RequestException
from requests import Timeout

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.utils import get_service_instance

from ikwen.billing.models import PaymentMean, MoMoTransaction

import logging
logger = logging.getLogger('ikwen')

MTN_MOMO = 'mtn-momo'


def init_momo_transaction(request, *args, **kwargs):
    phone = slugify(request.GET['phone'])
    if phone[:3] == '237':
        phone = phone[3:]
    request.session['phone'] = phone
    return init_request_payment(request, *args, **kwargs)


def init_request_payment(request, *args, **kwargs):
    service = get_service_instance(UMBRELLA)
    phone = request.GET['phone']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    amount = request.session['amount']
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
                                                                 object_id=object_id, wallet=MTN_MOMO, username=username,
                                                                 callback=callback)
        except MoMoTransaction.MultipleObjectsReturned:
            tx = MoMoTransaction.objects.using('wallets').filter(object_id=object_id)[0]
    if getattr(settings, 'DEBUG', False):
        request_payment(request, tx)
    else:
        Thread(target=request_payment, args=(request, tx, )).start()
    return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')


def request_payment(request, tx):
    """
    Calls the HTTP MTN Mobile Money API and updates the MoMoTransaction
    status in the database upon completion of the request.
    """
    svc = get_service_instance()
    MTN_MOMO_API_URL = getattr(settings, 'MTN_MOMO_API_URL', 'https://developer.mtn.cm/OnlineMomoWeb/faces/transaction/transactionRequest.xhtml')
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 100
    else:
        amount = int(tx.amount)
    data = {'idbouton': 2, 'typebouton': 'PAIE', 'submit.x': 104, 'submit.y': 70,
            '_cIP': '', '_amount': amount, '_tel': tx.phone}
    cashout_url = MTN_MOMO_API_URL
    momo_after_checkout = import_by_path(tx.callback)
    if getattr(settings, 'UNIT_TESTING', False):
        tx.processor_tx_id = 'tx_1'
        tx.task_id = 'task_1'
        tx.message = 'Success'
        tx.is_running = False
        tx.status = MoMoTransaction.SUCCESS
        request.session['next_url'] = 'http://nextUrl'
        momo_after_checkout(request, transaction=tx, signature=request.session['signature'])
    elif getattr(settings, 'DEBUG', False):
        mtn_momo = json.loads(PaymentMean.objects.get(slug=MTN_MOMO).credentials)
        data.update({'_email': mtn_momo['merchant_email']})
        r = requests.get(cashout_url, params=data, verify=False, timeout=300)
        resp = r.json()
        tx.task_id = resp['ProcessingNumber']
        if resp['StatusCode'] == '01':
            logger.debug("%s - Successful MoMo payment of %dF from %s: %s" % (svc.project_name, amount, username, tx.phone))
            tx.processor_tx_id = resp['TransactionID']
            tx.message = resp['StatusDesc']
            tx.is_running = False
            tx.status = MoMoTransaction.SUCCESS
            momo_after_checkout(request, transaction=tx, signature=request.session['signature'])
        elif resp['StatusCode'] == '1000' and resp['StatusDesc'] == 'Pending':
            # Don't do anything here. Listen and process transaction on the callback URL view
            pass
        else:
            tx.status = MoMoTransaction.API_ERROR
    else:
        try:
            mtn_momo = json.loads(PaymentMean.objects.get(slug=MTN_MOMO).credentials)
        except:
            return HttpResponse("%s - Error, Could not parse MoMo API parameters." % svc.project_name)
        try:
            username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
            data.update({'_email': mtn_momo['merchant_email']})
            logger.debug("MTN MoMo: Initiating payment of %dF from %s: %s" % (amount, username, tx.phone))
            r = requests.get(cashout_url, params=data, verify=False, timeout=300)
            tx.is_running = False
            resp = r.json()
            tx.task_id = resp['ProcessingNumber']
            if resp['StatusCode'] == '01':
                logger.debug("%s - MTN MoMo: Successful payment of %dF from %s: %s" % (svc.project_name, amount, username, tx.phone))
                tx.processor_tx_id = resp['TransactionID']
                tx.message = resp['StatusDesc']
                tx.is_running = False
                tx.status = MoMoTransaction.SUCCESS
                tx.save(using='wallets')
                if getattr(settings, 'DEBUG', False):
                    momo_after_checkout(request, transaction=tx, signature=request.session['signature'])
                else:
                    with transaction.atomic(using='wallets'):
                        try:
                            momo_after_checkout(request, transaction=tx, signature=request.session['signature'])
                            tx.message = 'OK'
                        except:
                            tx.message = traceback.format_exc()
                            tx.save(using='wallets')
                            logger.error("%s - MTN MoMo: Failure while running callback. User: %s, Amt: %d" % (svc.project_name, request.user.username, int(request.session['amount'])), exc_info=True)
            elif resp['StatusCode'] == '1000' and resp['StatusDesc'] == 'Pending':
                # Don't do anything here. Listen and process transaction on the callback URL view
                logger.debug("%s - MTN MoMo: RequestPayment completed with ProcessingNumber %s" % (svc.project_name, tx.task_id))
            else:
                logger.error("%s - MTN MoMo: Transaction of %dF from %s: %s failed with message %s" % (svc.project_name, amount, username, tx.phone, resp['StatusDesc']))
                tx.status = MoMoTransaction.API_ERROR
                tx.message = resp['StatusDesc']
        except KeyError:
            tx.status = MoMoTransaction.FAILURE
            tx.message = traceback.format_exc()
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (svc.project_name, amount, username, tx.phone), exc_info=True)
        except SSLError:
            tx.status = MoMoTransaction.SSL_ERROR
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (svc.project_name, amount, username, tx.phone), exc_info=True)
        except Timeout:
            tx.status = MoMoTransaction.TIMEOUT
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (svc.project_name, amount, username, tx.phone), exc_info=True)
        except RequestException:
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
            tx.message = traceback.format_exc()
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (svc.project_name, amount, username, tx.phone), exc_info=True)
        except:
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
            logger.error("%s - MTN MoMo: Failed to init transaction of %dF from %s: %s" % (svc.project_name, amount, username, tx.phone), exc_info=True)

    tx.save(using='wallets')


@csrf_exempt
def process_notification(request, *args, **kwargs):
    svc = get_service_instance()
    logger.debug("%s - MTN MoMo - New notification: %s" % (svc.project_name, request.META['REQUEST_URI']))
    logger.debug("%s - MTN MoMo - New notification Body: %s" % (svc.project_name, request.body))
    try:
        resp = ET.fromstring(request.body)
        processing_number = resp.find(".//{http://www.csapi.org/schema/momopayment/local/v1_0}ProcessingNumber").text
        tx = MoMoTransaction.objects.using('wallets').get(task_id=processing_number)
    except (ET.ParseError, AttributeError):
        notice = "Invalid SOAP data in notification."
        logger.error("%s - MTN MoMo: %s" % (svc.project_name, notice), exc_info=True)
        return HttpResponse(notice)
    except MoMoTransaction.DoesNotExist:
        logger.error("%s - MTN MoMo: Could not find transaction with task_id %s." % (svc.project_name, processing_number), exc_info=True)
        return HttpResponse("Notification successfully received.")
    status_code = resp.find(".//{http://www.csapi.org/schema/momopayment/local/v1_0}StatusCode").text
    if status_code == '01':
        logger.debug("%s - MTN MoMo: Successful payment of %dF from %s: %s" % (svc.project_name, tx.amount, tx.username, tx.phone))
        tx_id = resp.find(".//{http://www.csapi.org/schema/momopayment/local/v1_0}MOMTransactionID").text
        tx.processor_tx_id = tx_id
        tx.is_running = False
        tx.status = MoMoTransaction.SUCCESS
        tx.save(using='wallets')
        momo_after_checkout = import_by_path(tx.callback)
        try:
            momo_after_checkout(request, transaction=tx)
            tx.message = 'OK'
        except:
            tx.message = traceback.format_exc()
            logger.error("%s - MTN MoMo: Failure while running callback. User: %s, Amt: %d" % (svc.project_name, tx.username, tx.amount), exc_info=True)
    else:
        tx.status = MoMoTransaction.API_ERROR
        status_desc = resp.find(".//{http://www.csapi.org/schema/momopayment/local/v1_0}StatusDesc").text
        tx.message = status_desc
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

