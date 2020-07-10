import json
import traceback
from datetime import datetime

import requests
from requests.exceptions import SSLError, RequestException
from requests import Timeout
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http.response import HttpResponseRedirect
from django.utils.module_loading import import_by_path

from ikwen.core.utils import get_service_instance
from ikwen.billing.models import PaymentMean, MoMoTransaction

import logging
logger = logging.getLogger('ikwen')

UBA = 'uba'
UNKNOWN_PHONE = '<Unknown>'
CURRENCY = "950"
API_URL = getattr(settings, 'UBA_API_URL', None)
UBA_PAYMENT_PORTAL_URL = getattr(settings, 'UBA_PAYMENT_PORTAL_URL', None)


def init_uba_web_payment(request, *args, **kwargs):
    model_name = request.session['model_name']
    object_id = request.session['object_id']
    service = get_service_instance()
    username = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    phone = request.user.phone if request.user.is_authenticated() and request.user.phone else '+237690000000'
    email = request.user.email if request.user.is_authenticated() and request.user.email else 'customer@unknown.jbo'
    first_name = request.user.first_name if request.user.is_authenticated() else '<MK>'
    last_name = request.user.last_name if request.user.is_authenticated() else '<MK>'
    amount = int(request.session['amount'])
    with transaction.atomic(using='wallets'):
        try:
            momo_tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
        except MoMoTransaction.DoesNotExist:
            momo_tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT,
                                                                      phone=phone, amount=amount, model=model_name,
                                                                      object_id=object_id, wallet=UBA, username=username)
        except MoMoTransaction.MultipleObjectsReturned:
            momo_tx = MoMoTransaction.objects.using('wallets').filter(object_id=object_id)[0]
    uba = json.loads(PaymentMean.objects.get(slug=UBA).credentials)
    data = {'merchantId': uba['merchantId'],'serviceKey': uba['serviceKey'], 'countryCurrencyCode': 950}
    data.update({
        'description': request.session['description'],
        'customerFirstName': first_name,
        'referenceNumber': object_id,
        'customerLastname': last_name,
        'customerEmail': email,
        'noOfItems': request.session['noOfItems'],
        'customerPhoneNumber': phone,
        'date': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'total': amount
    })
    try:
        resp = requests.post(API_URL, data, verify = False, timeout = 130)
    except SSLError:
        momo_tx.status = MoMoTransaction.SSL_ERROR
        messages.error(request, 'SSL Error.')
        return HttpResponseRedirect(request.session['cancel_url'])
    except Timeout:
        momo_tx.status = MoMoTransaction.TIMEOUT
        momo_tx.save()
        messages.error(request, 'Timeout. Orange Money Server is taking too long to respond.')
        return HttpResponseRedirect(request.session['cancel_url'])
    except RequestException:
        import traceback
        momo_tx.status = MoMoTransaction.REQUEST_EXCEPTION
        msg = traceback.format_exc()
        momo_tx.message = msg
        momo_tx.save()
        messages.error(request, msg)
        return HttpResponseRedirect(request.session['cancel_url'])
    except:
        import traceback
        momo_tx.status = MoMoTransaction.SERVER_ERROR
        msg = traceback.format_exc()
        if momo_tx.message:
            messages.error(request, momo_tx.message)
        else:
            messages.error(request, msg)
        return HttpResponseRedirect(request.session['cancel_url'])

    if resp.status_code == 200:
        payment_url = "%s%s" % (UBA_PAYMENT_PORTAL_URL, resp.text)
        return HttpResponseRedirect(payment_url)
    else:
        momo_tx.status = MoMoTransaction.API_ERROR
        momo_tx.save()


def uba_process_approved(request, *args, **kwargs):
    object_id = request.POST['refNo']
    cipg_tx_id = request.POST['transactionID']
    try:
        tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
    except:
        logger.error("UBA: Failure while querying transaction status", exc_info=True)
    else:
        logger.debug("UBA: Successful payment of %dF from %s" % (tx.amount, tx.username))

        payments_conf = getattr(settings, 'PAYMENTS', None)
        if payments_conf:
            conf = request.session['payment_conf']
            path = payments_conf[conf]['after']
        else:
            path = getattr(settings, 'MOMO_AFTER_CASH_OUT')
        momo_after_checkout = import_by_path(path)
        with transaction.atomic(using='wallets'):
            try:
                MoMoTransaction.objects.using('wallets').filter(object_id=object_id) \
                    .update(processor_tx_id=cipg_tx_id, message='OK', is_running=False,
                            status=MoMoTransaction.SUCCESS)
            except:
                logger.error("UBA: Could not mark transaction as Successful. User: %s, Amt: %d" % (
                request.user.username, int(request.session['amount'])), exc_info=True)
            else:
                try:
                    momo_after_checkout(request, signature=request.session['signature'], tx_id=object_id)
                except:
                    MoMoTransaction.objects.using('wallets').filter(pk=object_id) \
                        .update(message=traceback.format_exc())
                    logger.error("UBA: Error while running callback. User: %s, Amt: %d" % (tx.username, tx.amount), exc_info=True)
        return HttpResponseRedirect(request.session['return_url'])


def uba_process_declined_or_cancelled(request, *args, **kwargs):
    object_id = request.POST['refNo']
    status = MoMoTransaction.FAILURE
    message = 'Transaction failed.'
    tx = MoMoTransaction.objects.using('wallets').filter(object_id=object_id) \
        .update(message=message, status=status, is_running=False)
    logger.debug("UBA: payment failed of %dF from %s" % (tx[0].amount, tx[0].username))
    return HttpResponseRedirect(request.session['cancel_url'])
