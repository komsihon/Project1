import json

import requests
from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.http.response import HttpResponseRedirect
from requests.exceptions import SSLError

from requests import RequestException
from requests import Timeout

from ikwen.core.utils import get_service_instance

from ikwen.billing.models import PaymentMean, MoMoTransaction

ORANGE_MONEY = 'orange-money'
UNKNOWN_PHONE = '<Unknown>'


def init_web_payment(request, *args, **kwargs):
    ORANGE_MONEY_API_URL = getattr(settings, 'ORANGE_MONEY_API_URL')
    phone = UNKNOWN_PHONE
    service = get_service_instance()
    request.session['phone'] = phone
    if getattr(settings, 'DEBUG_MOMO', False):
        amount = 1
    else:
        amount = request.session['amount']
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    transaction = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT,
                                                                  phone=phone, amount=amount, model=model_name,
                                                                  object_id=object_id)
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    notif_url = request.session['notif_url']
    notif_url += '/%d' % transaction.id
    data = {'order_id': object_id,
            'amount': amount,
            'lang': 'fr',
            'return_url': request.session['return_url'],
            'cancel_url': request.session['cancel_url'],
            'notif_url': notif_url}
    if getattr(settings, 'DEBUG', False):
        om = json.loads(PaymentMean.objects.get(slug=ORANGE_MONEY).credentials)
        headers.update({'Authorization': 'Bearer ' + om['access_token']})
        data.update({'merchant_key': om['merchant_key'], 'currency': 'OUV'})
        r = requests.post(ORANGE_MONEY_API_URL, headers=headers, data=json.dumps(data), verify=False, timeout=130)
        resp = r.json()
        transaction.message = resp['message']
        if resp['status'] == 201:
            request.session['pay_token'] = resp['pay_token']
            request.session['notif_token'] = resp['notif_token']
            transaction.status = MoMoTransaction.SUCCESS
            transaction.save()
            return HttpResponseRedirect(resp['payment_url'])
        else:
            transaction.status = MoMoTransaction.API_ERROR
            transaction.save()
    else:
        try:
            om = json.loads(PaymentMean.objects.get(slug=ORANGE_MONEY).credentials)
        except:
            return HttpResponse("Error, Could not parse Orange Money API parameters.")
        try:
            headers.update({'Authorization': 'Bearer ' + om['access_token']})
            data.update({'merchant_key': om['merchant_key'], 'currency': 'XAF'})
            r = requests.post(ORANGE_MONEY_API_URL, headers=headers, data=json.dumps(data), verify=False, timeout=130)
            resp = r.json()
            transaction.message = resp['message']
            if resp['status'] == 201:
                request.session['pay_token'] = resp['pay_token']
                request.session['notif_token'] = resp['notif_token']
                transaction.status = MoMoTransaction.SUCCESS
                transaction.save()
                return HttpResponseRedirect(resp['payment_url'])
            else:
                transaction.status = MoMoTransaction.API_ERROR
                transaction.save()
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

