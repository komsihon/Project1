import json
from datetime import datetime
from threading import Thread

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils.translation import ugettext as _

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.core.models import Service, Config, CASH_OUT_REQUEST_PAID, OperatorWallet, CASH_OUT_REQUEST_EVENT
from ikwen.core.utils import add_event, get_mail_content, XEmailMessage, set_counters, increment_history_field, \
    get_config_model
from ikwen.billing.models import MoMoTransaction
from ikwen.cashout.models import CashOutRequest, CashOutAddress, CashOutMethod

from daraja.models import DARAJA, Dara


def create_cashout_request(config, cashout_method, cashout_address):
    now = datetime.now()
    weblet = config.service
    provider = cashout_method.slug
    try:
        last_cashout = CashOutRequest.objects.using('wallets') \
            .filter(service_id=weblet.id, provider=provider, status=CashOutRequest.PAID).order_by('-id')[0]
        start = last_cashout.paid_on
    except:
        start = weblet.since
    queryset = MoMoTransaction.objects.using('wallets') \
        .filter(status=MoMoTransaction.SUCCESS, wallet=provider, processor_tx_id__isnull=False,
                is_running=False, type=MoMoTransaction.CASH_OUT, created_on__range=(start, now))
    if weblet.app.slug == DARAJA:
        dara = Dara.objects.get(member=weblet.member)
        queryset = queryset.filter(dara_id=dara.id)
        if queryset.count() <= 0:
            return
        aggr_dara_fees = queryset.aggregate(Sum('dara_fees'))
        amount_successful = aggr_dara_fees['dara_fees__sum']
    else:
        queryset = queryset.filter(service_id=weblet.id)
        if queryset.count() <= 0:
            return
        aggr = queryset.aggregate(Sum('amount'))
        aggr_fees = queryset.aggregate(Sum('fees'))
        aggr_dara_fees = queryset.aggregate(Sum('dara_fees'))
        amount_successful = aggr['amount__sum'] - aggr_fees['fees__sum'] - aggr_dara_fees['dara_fees__sum']

    cor = CashOutRequest(service_id=weblet.id, member_id=weblet.member.id, amount=amount_successful, paid_on=now,
                         method=cashout_method.name, account_number=cashout_address.account_number, provider=provider,
                         rate=config.cash_out_rate)
    return cor


def get_max_amount(provider):
    from ikwen.billing.mtnmomo.open_api import MTN_MOMO
    if provider == MTN_MOMO:
        return 1e6  # 1,000,000
    else:
        return 5e5  # 500,000


def notify_cashout_and_reset_counters(request, transaction, *args, **kwargs):
    """
    Notifies IAO that request to cashout completed successfully and resets wallet balance accordingly
    :param request:
    :param transaction: MoMoTransaction object used to process this operation
    :return:
    """
    cashout_request = CashOutRequest.objects.using('wallets').get(pk=transaction.object_id)
    cashout_request.status = CashOutRequest.PAID
    cashout_request.reference = transaction.processor_tx_id
    charges = cashout_request.amount * cashout_request.rate / 100
    cashout_request.amount_paid = cashout_request.amount * (100 - cashout_request.rate) / 100
    cashout_request.save()
    weblet = Service.objects.using(UMBRELLA).get(pk=transaction.service_id)
    wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=weblet.id, provider=transaction.wallet)
    method = CashOutMethod.objects.using(UMBRELLA).get(slug=transaction.wallet)
    address = CashOutAddress.objects.using(UMBRELLA).get(service=weblet, method=method)
    with db_transaction.atomic(using='wallets'):
        queryset = MoMoTransaction.objects.using('wallets') \
            .filter(created_on__gt=cashout_request.paid_on, type=MoMoTransaction.CASH_OUT,
                    status=MoMoTransaction.SUCCESS, wallet=cashout_request.provider)
        iao = weblet.member
        if weblet.app.slug == DARAJA:
            dara = Dara.objects.get(member=iao)
            queryset = queryset.filter(dara_id=dara.id)
            if queryset.count() > 0:
                aggr = queryset.aggregate(Sum('dara_fees'))
                amount_successful = aggr['dara_fees__sum']
            else:
                amount_successful = 0
        else:
            queryset = queryset.filter(service_id=weblet.id)
            if queryset.count() > 0:
                aggr = queryset.aggregate(Sum('amount'))
                aggr_fees = queryset.aggregate(Sum('fees'))
                aggr_dara_fees = queryset.aggregate(Sum('dara_fees'))
                amount_successful = aggr['amount__sum'] - aggr_fees['fees__sum'] - aggr_dara_fees['dara_fees__sum']
            else:
                amount_successful = 0
        wallet.balance = amount_successful
        wallet.save(using='wallets')
        if getattr(settings, 'TESTING', False):
            IKWEN_SERVICE_ID = getattr(settings, 'IKWEN_ID')
            ikwen_service = Service.objects.using(UMBRELLA).get(pk=IKWEN_SERVICE_ID)
        else:
            from ikwen.conf.settings import IKWEN_SERVICE_ID
            ikwen_service = Service.objects.using(UMBRELLA).get(pk=IKWEN_SERVICE_ID)
        sender = 'ikwen <no-reply@ikwen.com>'
        event_originator = ikwen_service
        add_event(event_originator, CASH_OUT_REQUEST_PAID, member=iao, object_id=cashout_request.id)

        subject = _("Money transfer confirmation")
        html_content = get_mail_content(subject, '', template_name='cashout/mails/payment_notice.html',
                                        extra_context={'cash_out_request': cashout_request, 'charges': charges,
                                                       'weblet': weblet, 'address': address,
                                                       'service': event_originator})
        msg = XEmailMessage(subject, html_content, sender, [iao.email])
        msg.service = ikwen_service
        msg.bcc = ['rsihon@gmail.com', 'admin@ikwen.com']
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()

        set_counters(ikwen_service)
        increment_history_field(ikwen_service, 'cash_out_history', cashout_request.amount)
        increment_history_field(ikwen_service, 'cash_out_count_history')


def submit_cashout_request_for_manual_processing(**kwargs):
    tx = kwargs.get('transaction')
    if tx:
        cashout_request = CashOutRequest.objects.using('wallets').get(pk=tx.object_id)
        weblet = Service.objects.using(UMBRELLA).get(pk=tx.service_id)
        wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=weblet.id, provider=tx.wallet)
        config = get_config_model().objects.using(UMBRELLA).get(service=weblet)
    else:
        config = kwargs['config']
        wallet = kwargs['wallet']
        cashout_request = kwargs['cashout_request']
        weblet = config.service
    iao = weblet.member
    if getattr(settings, 'TESTING', False):
        IKWEN_SERVICE_ID = getattr(settings, 'IKWEN_ID')
        ikwen_service = Service.objects.get(pk=IKWEN_SERVICE_ID)
    else:
        from ikwen.conf.settings import IKWEN_SERVICE_ID
        ikwen_service = Service.objects.using(UMBRELLA).get(pk=IKWEN_SERVICE_ID)
    retailer = weblet.retailer
    if retailer:
        vendor = retailer
    else:
        vendor = ikwen_service
    vendor_config = Config.objects.using(UMBRELLA).get(service=vendor)
    sender = '%s <no-reply@%s>' % (vendor_config.company_name, vendor.domain)

    add_event(vendor, CASH_OUT_REQUEST_EVENT, member=iao, object_id=cashout_request.id)
    subject = _("Cash-out request on %s" % weblet.project_name)
    html_content = get_mail_content(subject, '', template_name='cashout/mails/request_notice.html',
                                    extra_context={'cash_out_request': cashout_request, 'weblet': weblet,
                                                   'service': vendor, 'config': vendor_config, 'iao': iao,
                                                   'wallet': wallet, 'iao_profile': config})
    msg = EmailMessage(subject, html_content, sender, [iao.email])
    msg.bcc = ['k.sihon@ikwen.com', 'contact@ikwen.com']
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg,)).start()
    return HttpResponse(json.dumps({'success': True, 'manual_processing': True}), 'content-type: text/json')
