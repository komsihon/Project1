import json
from threading import Thread

import requests
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from requests.exceptions import SSLError

from requests import RequestException
from requests import Timeout

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.utils import get_service_instance

from ikwen.billing.models import PaymentMean, MoMoTransaction


def init_momo_cashout(request, *args, **kwargs):
    service = get_service_instance(UMBRELLA)
    phone = request.GET['phone']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    amount = request.session['amount']
    tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT, phone=phone,
                                                         amount=amount, model=model_name, object_id=object_id)
    if getattr(settings, 'DEBUG', False):
        call_cashout(tx)
    else:
        Thread(target=call_cashout, args=(tx, )).start()
    return HttpResponse(json.dumps({'success': True, 'tx_id': tx.id}), 'content-type: text/json')


def call_cashout(transaction):
    """
    Calls the HTTP JumboPay API and updates the MoMoTransaction
    status in the database upon completion of the request.
    """
    JUMBOPAY_API_URL = getattr(settings, 'JUMBOPAY_API_URL', 'https://154.70.100.194/api/live/v2/')
    label = '%s:%s' % (transaction.model, transaction.object_id)
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 100
    else:
        amount = transaction.amount
    data = {'amount': amount, 'libelle': label, 'phonenumber': transaction.phone, 'lang': 'en'}
    cashout_url = JUMBOPAY_API_URL + 'cashout'
    if getattr(settings, 'DEBUG', False):
        jumbopay = json.loads(PaymentMean.objects.get(slug='jumbopay-momo').credentials)
        headers = {'Authorization': jumbopay['api_key'], 'Content-Type': 'application/x-www-form-urlencoded'}
        r = requests.post(cashout_url, headers=headers, data=data, verify=False, timeout=130)
        resp = r.json()
        message = resp['message'][0]
        transaction.processor_tx_id = message['transactionid']
        transaction.task_id = message['task']
        transaction.message = message['msg']
        if resp['error']:
            transaction.status = MoMoTransaction.API_ERROR
        else:
            transaction.status = MoMoTransaction.SUCCESS
    else:
        try:
            jumbopay = json.loads(PaymentMean.objects.get(slug='jumbopay-momo').credentials)
        except:
            return HttpResponse("Error, Could not parse JumboPay parameters.")
        try:
            headers = {'Authorization': jumbopay['api_key'], 'Content-Type': 'application/x-www-form-urlencoded'}
            cert = getattr(settings, 'JUMBOPAY_SSL_CERTIFICATE', None)
            if cert:
                r = requests.post(cashout_url, cert=cert, headers=headers, data=data, timeout=130)
            else:
                r = requests.post(cashout_url, headers=headers, data=data, verify=False, timeout=130)
            resp = r.json()
            message = resp['message'][0]
            transaction.processor_tx_id = message['transactionid']
            transaction.task_id = message['task']
            transaction.message = message['msg']
            if resp['error']:
                transaction.status = MoMoTransaction.API_ERROR
            else:
                transaction.status = MoMoTransaction.SUCCESS
        except SSLError:
            transaction.status = MoMoTransaction.SSL_ERROR
        except Timeout:
            transaction.status = MoMoTransaction.TIMEOUT
        except RequestException:
            import traceback
            transaction.status = MoMoTransaction.REQUEST_EXCEPTION
            transaction.message = traceback.format_exc()
        except:
            import traceback
            transaction.status = MoMoTransaction.SERVER_ERROR
            transaction.message = traceback.format_exc()

    transaction.save(using='wallets')


def do_cashin(phone, amount, model_name, object_id):
    """
    Calls the *Cashin* HTTP JumboPay API to pay an IAO.
    """
    JUMBOPAY_API_URL = getattr(settings, 'JUMBOPAY_API_URL', 'https://154.70.100.194/api/live/v2/')
    service = get_service_instance()
    tx = MoMoTransaction.objects.using(UMBRELLA).create(service=service, type=MoMoTransaction.CASH_IN, phone=phone,
                                                        amount=amount, model=model_name, object_id=object_id)
    label = '%s:%s' % (tx.model, tx.object_id)
    data = {'amount': tx.amount, 'libelle': label, 'phonenumber': phone, 'lang': 'en'}
    cashin_url = JUMBOPAY_API_URL + 'cashin'
    if getattr(settings, 'DEBUG', False):
        jumbopay = json.loads(PaymentMean.objects.using(UMBRELLA).get(slug='jumbopay-momo').credentials)
        headers = {'Authorization': jumbopay['api_key'],
                   'Content-Type': 'application/x-www-form-urlencoded'}
        r = requests.post(cashin_url, headers=headers, data=data, verify=False, timeout=130)
        resp = r.json()
        message = resp['message'][0]
        tx.processor_tx_id = message['transactionid']
        tx.task_id = message['task']
        tx.message = message['msg']
        if resp['error']:
            tx.status = MoMoTransaction.API_ERROR
        else:
            tx.status = MoMoTransaction.SUCCESS
    else:
        try:
            jumbopay = json.loads(PaymentMean.objects.get(slug='jumbopay-momo').credentials)
        except:
            return HttpResponse("Error, Could not parse JumboPay parameters.")
        try:
            headers = {'Authorization': jumbopay['api_key'],
                       'Content-Type': 'application/x-www-form-urlencoded'}
            cert = getattr(settings, 'JUMBOPAY_SSL_CERTIFICATE', None)
            if cert:
                r = requests.post(cashin_url, cert=cert, headers=headers, data=data, timeout=130)
            else:
                r = requests.post(cashin_url, headers=headers, data=data, verify=False, timeout=130)
            resp = r.json()
            message = resp['message'][0]
            tx.processor_tx_id = message['transactionid']
            tx.task_id = message['task']
            tx.message = message['msg']
            if resp['error']:
                tx.status = MoMoTransaction.API_ERROR
            else:
                tx.status = MoMoTransaction.SUCCESS
        except SSLError:
            tx.status = MoMoTransaction.SSL_ERROR
        except Timeout:
            tx.status = MoMoTransaction.TIMEOUT
        except RequestException:
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
        except:
            import traceback
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
    tx.save(using='wallets')
    return tx


@csrf_exempt
def jumbopay_local_api(request, op, *args, **kwargs):
    """
    This view serves for UNIT TESTS purposes only by simulating
    JumboPay CASHIN/CASHOUT API calls
    """
    if op == 'cashin':
        response = {
            "error": False,
            "message": [{
                "msg": "Successful Cashin",
                "transactionid": "tx1",
                "task": "task1"
            }]
        }
    if op == 'cashout':
        response = {
            "error": False,
            "message": [{
                "msg": "Successful Cashout",
                "transactionid": "tx2",
                "task": "task2"
            }]
        }
    return HttpResponse(json.dumps(response), 'content-type: text/json')