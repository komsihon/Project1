import json
from threading import Thread

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_by_path
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
    username = request.user.username if request.user.is_authenticated() else None
    try:
        tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
    except MoMoTransaction.DoesNotExist:
        tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT,
                                                             phone=phone, amount=amount, model=model_name,
                                                             object_id=object_id, wallet=MTN_MOMO, username=username)
    if getattr(settings, 'DEBUG', False):
        request_payment(request, tx)
    else:
        Thread(target=request_payment, args=(request, tx, )).start()
    return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')


def request_payment(request, transaction):
    """
    Calls the HTTP MTN Mobile Money API and updates the MoMoTransaction
    status in the database upon completion of the request.
    """
    MTN_MOMO_API_URL = getattr(settings, 'MTN_MOMO_API_URL')
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 100
    else:
        amount = int(transaction.amount)
    data = {'idbouton': 2, 'typebouton': 'PAIE', 'submit.x': 104, 'submit.y': 70,
            '_cIP': '', '_amount': amount, '_tel': transaction.phone}
    cashout_url = MTN_MOMO_API_URL
    if getattr(settings, 'UNIT_TESTING', False):
        transaction.processor_tx_id = 'tx_1'
        transaction.task_id = 'task_1'
        transaction.message = 'Success'
        transaction.status = MoMoTransaction.SUCCESS
    elif getattr(settings, 'DEBUG', False):
        mtn_momo = json.loads(PaymentMean.objects.get(slug=MTN_MOMO).credentials)
        data.update({'_email': mtn_momo['merchant_email']})
        r = requests.get(cashout_url, params=data, verify=False, timeout=300)
        resp = r.json()
        transaction.processor_tx_id = resp['TransactionID']
        transaction.task_id = resp['ProcessingNumber']
        transaction.message = resp['StatusDesc']
        if resp['StatusCode'] == '01':
            username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
            logger.debug("Successful MoMo payment of %dF from %s: %s" % (amount, username, transaction.phone))
            transaction.status = MoMoTransaction.SUCCESS
        else:
            transaction.status = MoMoTransaction.API_ERROR
    else:
        try:
            mtn_momo = json.loads(PaymentMean.objects.get(slug=MTN_MOMO).credentials)
        except:
            return HttpResponse("Error, Could not parse MoMo API parameters.")
        try:
            username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
            data.update({'_email': mtn_momo['merchant_email']})
            logger.debug("Initing MoMo payment of %dF from %s: %s" % (amount, username, transaction.phone))
            r = requests.get(cashout_url, params=data, verify=False, timeout=300)
            resp = r.json()
            transaction.processor_tx_id = resp['TransactionID']
            transaction.task_id = resp['ProcessingNumber']
            transaction.message = resp['StatusDesc']
            if resp['StatusCode'] == '01':
                logger.debug("Successful MoMo payment of %dF from %s: %s" % (amount, username, transaction.phone))
                transaction.status = MoMoTransaction.SUCCESS
            else:
                transaction.status = MoMoTransaction.API_ERROR
        except KeyError:
            import traceback
            transaction.status = MoMoTransaction.FAILURE
            transaction.message = traceback.format_exc()
            logger.error("MTN MoMo: Failed to init transaction", exc_info=True)
        except SSLError:
            transaction.status = MoMoTransaction.SSL_ERROR
        except Timeout:
            transaction.status = MoMoTransaction.TIMEOUT
        except RequestException:
            import traceback
            transaction.status = MoMoTransaction.REQUEST_EXCEPTION
            transaction.message = traceback.format_exc()
            logger.error("MTN MoMo: Failed to init transaction", exc_info=True)
        except:
            import traceback
            transaction.status = MoMoTransaction.SERVER_ERROR
            transaction.message = traceback.format_exc()
            logger.error("MTN MoMo: Failed to init transaction", exc_info=True)

    transaction.save(using='wallets')


@transaction.atomic
def check_momo_transaction_status(request, *args, **kwargs):
    tx_id = request.GET['tx_id']
    tx = MoMoTransaction.objects.using('wallets').get(pk=tx_id)

    # When a MoMoTransaction is created, its status is None or empty string
    # So perform a double check. First, make sure a status has been set
    if tx.is_running and tx.status:
        tx.is_running = False
        tx.save(using='wallets')
        if tx.status == MoMoTransaction.SUCCESS:
            request.session['tx_id'] = tx_id
            payments_conf = getattr(settings, 'PAYMENTS', None)
            if payments_conf:
                conf = request.session['payment_conf']
                path = payments_conf[conf]['after']
            else:
                path = getattr(settings, 'MOMO_AFTER_CASH_OUT')
            momo_after_checkout = import_by_path(path)
            if getattr(settings, 'DEBUG', False):
                resp_dict = momo_after_checkout(request, signature=request.session['signature'])
                return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
            else:
                try:
                    resp_dict = momo_after_checkout(request, signature=request.session['signature'])
                    return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
                except:
                    logger.error("MTN MoMo: Failure while running callback. User: %s, Amt: %d" % (request.user.username, int(request.session['amount'])), exc_info=True)
                    return HttpResponse(json.dumps({'error': 'Unknown server error in AFTER_CASH_OUT'}))
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

