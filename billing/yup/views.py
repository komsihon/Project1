import json
import traceback

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.http.response import HttpResponseRedirect
from django.shortcuts import render
from django.template.defaultfilters import slugify
from django.utils.module_loading import import_by_path

from ikwen.core.utils import get_service_instance
from ikwen.billing.models import PaymentMean, MoMoTransaction

import logging
logger = logging.getLogger('ikwen')

YUP = 'yup'
UNKNOWN_PHONE = '<Unknown>'
CURRENCY = "XAF"


def init_yup_web_payment(request, *args, **kwargs):
    api_url = getattr(settings, 'YUP_API_URL', 'https://33027.tagpay.fr/online/online.php')
    yup = json.loads(PaymentMean.objects.get(slug=YUP).credentials)
    phone = UNKNOWN_PHONE
    service = get_service_instance()
    request.session['phone'] = phone
    amount = int(request.session['amount'])

    model_name = request.session['model_name']
    object_id = request.session['object_id']
    if request.user.is_authenticated():
        username = request.user.username
        language = request.user.language
    else:
        username = None
        language = 'en'

    # Request a session id
    try:
        params = {'merchantid': yup['merchant_id']}
        session_id_request = requests.get(api_url, params=params, verify=False)
    except requests.exceptions.HTTPError as errh:
        logger.error("YUP: Http Error:", errh)
        return HttpResponseRedirect(request.session['cancel_url'])
    except requests.exceptions.ConnectionError as errc:
        logger.error("Error Connecting:", errc)
        return HttpResponseRedirect(request.session['cancel_url'])
    except requests.exceptions.Timeout as errt:
        logger.error("Timeout Error:", errt)
        return HttpResponseRedirect(request.session['cancel_url'])
    except requests.exceptions.RequestException as err:
        logger.error("OOps: Something Else", err)
        return HttpResponse(request.session['cancel_url'])

    session_id_resp_message = session_id_request.text
    if session_id_resp_message[:2] == "NO":
        logger.debug("YUP: Unable to provide a session with %s as Merchand ID" % (yup['merchant_id']))
        logger.debug("YUP: SERVER ERR TEXT is : %s" % session_id_resp_message)
        return HttpResponse("Error, YUP: Unable to provide a session with %s as Merchand ID; Please check and restart" % (yup['merchant_id']))
    else:
        logger.debug("YUP: Session ID OK; ")
        session_id = session_id_resp_message.replace('OK:', '')
    payments_conf = getattr(settings, 'PAYMENTS', None)
    if payments_conf:
        conf = request.session['payment_conf']
        path = payments_conf[conf]['after']
    else:
        path = getattr(settings, 'MOMO_AFTER_CASH_OUT')
    with transaction.atomic(using='wallets'):
        try:
            momo_tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
        except MoMoTransaction.DoesNotExist:
            momo_tx = MoMoTransaction.objects.using('wallets').create(service_id=service.id, type=MoMoTransaction.CASH_OUT,
                                                                      phone=phone, amount=amount, model=model_name,
                                                                      object_id=object_id, wallet=YUP, username=username,
                                                                      callback=path)
        except MoMoTransaction.MultipleObjectsReturned:
            momo_tx = MoMoTransaction.objects.using('wallets').filter(object_id=object_id)[0]

    request.session['tx_id'] = momo_tx.id
    accept_url = request.session['return_url']
    # accept_url += '/%d' % momo_tx.id
    company_name = slugify(service.config.company_name).replace('-', ' ')

    logger.debug("YUP: Initiating paymentof %dF with %s as Merchand ID" % (amount, yup['merchant_id']))
    context = {
        'api_url': api_url,
        'sessionid': session_id,
        'merchantid': yup['merchant_id'],
        'amount': amount,
        'currency': CURRENCY,
        'purchaseref': object_id,
        'phone': phone,
        'brand': company_name,
        'description': '',
        'declineurl': request.session['cancel_url'],
        'cancelurl': request.session['cancel_url'],
        'accepturl': accept_url,
        'text':  '',
        'language': language
    }
    return render(request, 'billing/yup/do_redirect.html', context)


def yup_process_notification(request, *args, **kwargs):
    logger.debug("YUP: New incoming notification %s" % request.META['REQUEST_URI'])

    amount = request.GET['amount']
    object_id = request.GET['purchaseref']
    paymentref = request.GET['paymentref']
    error_text = request.GET.get('error')
    status = request.GET['status']
    try:
        tx = MoMoTransaction.objects.using('wallets').get(object_id=object_id)
    except:
        logger.error("YUP: Failure while querying transaction status", exc_info=True)
        return HttpResponse("OK")
    logger.debug("YUP: Successful payment of %dF from %s" % (tx.amount, tx.username))
    if status == "OK":
        path = tx.callback
        momo_after_checkout = import_by_path(path)
        with transaction.atomic(using='wallets'):
            try:
                with transaction.atomic():
                    MoMoTransaction.objects.using('wallets').filter(object_id=object_id) \
                        .update(processor_tx_id=paymentref, message='OK', is_running=False,
                                status=MoMoTransaction.SUCCESS)
            except:
                logger.error("YUP: Could not mark transaction as Successful. User: %s, Amt: %d" % (tx.username, tx.amount), exc_info=True)
            else:
                try:
                    momo_after_checkout(request, transaction=tx)
                except:
                    MoMoTransaction.objects.using('wallets').filter(object_id=object_id) \
                        .update(message=traceback.format_exc())
                    logger.error("YUP: Error while running callback. User: %s, Amt: %d" % (tx.username, tx.amount), exc_info=True)
    elif error_text != 'AUTHENTICATION':
        with transaction.atomic(using='wallets'):
            try:
                if "CANCEL" in error_text:
                    logger.debug("YUP: transaction canceled. User: %s, Amt: %d " % (tx.username, tx.amount))
                    MoMoTransaction.objects.using('wallets').filter(object_id=object_id) \
                        .update(message=error_text, is_running=False, status=MoMoTransaction.DROPPED)
                else:
                    logger.debug("YUP: transaction failed. User: %s, Amt: %d " % (tx.username, tx.amount))
                    MoMoTransaction.objects.using('wallets').filter(object_id=object_id) \
                        .update(message=error_text, is_running=False, status=MoMoTransaction.FAILURE)
            except:
                logger.error("YUP: Could not mark transaction as Failed or Canceled. User: %s, Amt: %s" % (tx.username, tx.amount), exc_info=True)

    return HttpResponse('OK')
