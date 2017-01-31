import json
from threading import Thread

import requests
from django.conf import settings
from django.core.urlresolvers import reverse
from django.db.models.loading import get_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_by_path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from ikwen.core.views import IKWEN_BASE_URL
from requests import RequestException
from requests import Timeout

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.utils import get_service_instance

from ikwen.billing.models import PaymentMean, MoMoTransaction

from ikwen.core.views import BaseView

if getattr(settings, 'DEBUG', False):
    JUMBOPAY_API_URL = 'https://154.70.100.194/api/sandbox/v2/'
    API_KEY = 'c18c884c0a3fcc756f81e0b28d636208'
else:
    JUMBOPAY_API_URL = 'https://154.70.100.194/api/live/v2/'


class MoMoCheckout(BaseView):
    template_name = 'billing/momo_checkout.html'

    def get_context_data(self, **kwargs):
        context = super(MoMoCheckout, self).get_context_data(**kwargs)
        context['payment_mean'] = get_object_or_404(PaymentMean, slug='jumbopay-momo')
        return context

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def post(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        path = getattr(settings, 'MOMO_BEFORE_CASH_OUT')
        momo_before_checkout = import_by_path(path)
        momo_before_checkout(request, *args, **kwargs)
        return render(request, self.template_name, context)


def init_momo_cashout(request, *args, **kwargs):
    service = get_service_instance(UMBRELLA)
    phone = request.GET['phone']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    amount = request.session['amount']
    tx = MoMoTransaction.objects.using(UMBRELLA).create(service=service, type=MoMoTransaction.CASH_OUT, phone=phone,
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
    if getattr(settings, 'TESTING', False):
        JUMBOPAY_API_URL = 'http://localhost/ikwen' + reverse('billing:jumbopay_local_api')
    label = '%s:%s' % (transaction.model, transaction.object_id)
    data = {'amount': transaction.amount, 'libelle': label, 'phonenumber': transaction.phone, 'lang': 'en'}
    cashout_url = JUMBOPAY_API_URL + 'cashout'
    if getattr(settings, 'DEBUG', False):
        jumbopay = json.loads(PaymentMean.objects.get(slug='jumbopay-momo').credentials)
        r = requests.post(cashout_url, data=data, timeout=130)
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
            key = jumbopay['api_key']
            r = requests.post(cashout_url, data=data, timeout=130)
            resp = r.json()
            message = resp['message'][0]
            transaction.processor_tx_id = message['transactionid']
            transaction.task_id = message['task']
            transaction.message = message['msg']
            if resp['error']:
                transaction.status = MoMoTransaction.API_ERROR
            else:
                transaction.status = MoMoTransaction.SUCCESS
        except Timeout:
            transaction.status = MoMoTransaction.TIMEOUT
        except RequestException:
            transaction.status = MoMoTransaction.REQUEST_EXCEPTION
        except:
            import traceback
            transaction.status = MoMoTransaction.SERVER_ERROR
            transaction.message = traceback.format_exc()

    transaction.save(using=UMBRELLA)


def check_momo_transaction_status(request, *args, **kwargs):
    tx_id = request.GET['tx_id']
    tx = MoMoTransaction.objects.using(UMBRELLA).get(pk=tx_id)

    # When a MoMoTransaction is created, its status is None or empty string
    # So perform a double check. First, make sure a status has been set
    if tx.status:
        if tx.status == MoMoTransaction.SUCCESS:
            path = getattr(settings, 'MOMO_AFTER_CASH_OUT')
            momo_after_checkout = import_by_path(path)
            resp_dict = momo_after_checkout(request, *args, **kwargs)
            return HttpResponse(json.dumps(resp_dict), 'content-type: text/json')
        return HttpResponse(json.dumps({'error': tx.status}), 'content-type: text/json')
    return HttpResponse(json.dumps({'running': True}), 'content-type: text/json')


def do_cashin(phone, amount, model_name, object_id):
    """
    Calls the *Cashin* HTTP JumboPay API to pay an IAO.
    """
    if getattr(settings, 'TESTING', False):
        JUMBOPAY_API_URL = 'http://localhost/ikwen' + reverse('billing:jumbopay_local_api')
    service = get_service_instance()
    tx = MoMoTransaction.objects.using(UMBRELLA).create(service=service, type=MoMoTransaction.CASH_IN, phone=phone,
                                                        amount=amount, model=model_name, object_id=object_id)
    label = '%s:%s' % (tx.model, tx.object_id)
    data = {'amount': tx.amount, 'libelle': label, 'phonenumber': phone, 'lang': 'en'}
    cashin_url = JUMBOPAY_API_URL + 'cashin'
    if getattr(settings, 'DEBUG', False):
        jumbopay = json.loads(PaymentMean.objects.get(slug='jumbopay-momo').credentials)
        r = requests.post(cashin_url, data=data, timeout=130)
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
            key = jumbopay['api_key']
            r = requests.post(cashin_url, data=data, timeout=130)
            resp = r.json()
            message = resp['message'][0]
            tx.processor_tx_id = message['transactionid']
            tx.task_id = message['task']
            tx.message = message['msg']
            if resp['error']:
                tx.status = MoMoTransaction.API_ERROR
            else:
                tx.status = MoMoTransaction.SUCCESS
        except Timeout:
            tx.status = MoMoTransaction.TIMEOUT
        except RequestException:
            tx.status = MoMoTransaction.REQUEST_EXCEPTION
        except:
            import traceback
            tx.status = MoMoTransaction.SERVER_ERROR
            tx.message = traceback.format_exc()
    tx.save(using=UMBRELLA)
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