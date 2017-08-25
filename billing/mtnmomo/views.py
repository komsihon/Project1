import json
from threading import Thread

import requests
from django.conf import settings
from django.http import HttpResponse
from requests.exceptions import SSLError

from requests import RequestException
from requests import Timeout

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.utils import get_service_instance

from ikwen.billing.models import PaymentMean, MoMoTransaction

import logging
logger = logging.getLogger('ikwen')

MTN_MOMO = 'mtn-momo'


def init_request_payment(request, *args, **kwargs):
    service = get_service_instance(UMBRELLA)
    phone = request.GET['phone']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    amount = request.session['amount']
    tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT, phone=phone,
                                                         amount=amount, model=model_name, object_id=object_id)
    if getattr(settings, 'DEBUG', False):
        request_payment(tx)
    else:
        Thread(target=request_payment, args=(tx, )).start()
    return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')


def request_payment(transaction):
    """
    Calls the HTTP MTN Mobile Money API and updates the MoMoTransaction
    status in the database upon completion of the request.
    """
    MTN_MOMO_API_URL = getattr(settings, 'MTN_MOMO_API_URL')
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 100
    else:
        amount = transaction.amount
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
        r = requests.get(cashout_url, params=data, verify=False, timeout=130)
        resp = r.json()
        transaction.processor_tx_id = resp['TransactionID']
        transaction.task_id = resp['ProcessingNumber']
        transaction.message = resp['StatusDesc']
        if resp['StatusCode'] == '100':
            transaction.status = MoMoTransaction.API_ERROR
        else:
            transaction.status = MoMoTransaction.SUCCESS
    else:
        try:
            mtn_momo = json.loads(PaymentMean.objects.get(slug=MTN_MOMO).credentials)
        except:
            return HttpResponse("Error, Could not parse MoMo API parameters.")
        try:
            data.update({'_email': mtn_momo['merchant_email']})
            r = requests.get(cashout_url, params=data, verify=False, timeout=130)
            resp = r.json()
            transaction.processor_tx_id = resp['TransactionID']
            transaction.task_id = resp['ProcessingNumber']
            transaction.message = resp['StatusDesc']
            if resp['StatusCode'] == '100':
                transaction.status = MoMoTransaction.API_ERROR
            else:
                transaction.status = MoMoTransaction.SUCCESS
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


