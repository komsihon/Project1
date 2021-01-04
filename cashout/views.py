import json
import logging
import traceback
from time import strptime

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.template import Context
from django.template.loader import get_template
from django.utils.module_loading import import_string as import_by_path
from django.views.generic import TemplateView
from django.utils.translation import gettext as _

from ikwen.core.constants import PENDING
from ikwen.core.utils import get_service_instance, get_config_model
from ikwen.core.models import OperatorWallet, Service
from ikwen.accesscontrol.models import Member
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.billing.models import MoMoTransaction
from ikwen.billing.mtnmomo.open_api import send_money as momo_send_money, MTN_MOMO
from ikwen.billing.orangemoney.wso2_api import send_money as om_send_money, ORANGE_MONEY
from ikwen.cashout.models import CashOutRequest, CashOutAddress, CashOutMethod
from ikwen.cashout.utils import create_cashout_request, get_max_amount, submit_cashout_request_for_manual_processing

logger = logging.getLogger('ikwen')


def _get_weblet(request, using=None):
    path = getattr(settings, 'GET_WALLET_SERVICE', None)
    if path:
        finder = import_by_path(path)
        if using:
            return finder(request, using=using)
        return finder(request)
    return get_service_instance(using=using)


# TODO: Write test for this function. Create and call the right template in the sending of mail
def request_cash_out(request, *args, **kwargs):
    provider = request.GET['provider']
    method = CashOutMethod.objects.using(UMBRELLA).get(slug=provider)
    weblet = _get_weblet(request, using=UMBRELLA)
    try:
        address = CashOutAddress.objects.using(UMBRELLA).get(service=weblet, method=method)
    except CashOutAddress.DoesNotExist:
        return HttpResponse(json.dumps({'error': _("No Payment method. Please set one first.")}),
                            'content-type: text/json')
    try:
        CashOutRequest.objects.using('wallets').get(service_id=weblet.id, provider=provider, status=PENDING)
        return HttpResponse(json.dumps({'error': _("You already have a pending request for this wallet.")}),
                            'content-type: text/json')
    except CashOutRequest.DoesNotExist:
        pass
    config = get_config_model().objects.using(UMBRELLA).select_related('service').get(service=weblet)
    wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=weblet.id, provider=provider)
    with transaction.atomic():
        cashout_request = create_cashout_request(config=config, cashout_method=method, cashout_address=address)
        if cashout_request.amount < config.cash_out_min:
            response = {'error': 'Balance too low', 'cash_out_min': config.cash_out_min}
            return HttpResponse(json.dumps(response), 'content-type: text/json')
        cashout_request.save(using='wallets')
        max_amount = get_max_amount(provider)  # Process max amount related things here
        if getattr(settings, 'DEBUG', False):
            if provider == MTN_MOMO:
                tx = momo_send_money(request, cashout_request)
            elif provider == ORANGE_MONEY:
                tx = om_send_money(request, cashout_request)
        else:
            try:
                if provider == MTN_MOMO:
                    tx = momo_send_money(request, cashout_request)
                elif provider == ORANGE_MONEY:
                    tx = om_send_money(request, cashout_request)
            except:
                notice = "Failed to submit Cashout."
                logger.error("%s: %s" % (weblet.ikwen_name, notice), exc_info=True)
        if tx.status is None or tx.status == MoMoTransaction.SUCCESS:
            return HttpResponse(json.dumps({'success': True}), 'content-type: text/json')
        return submit_cashout_request_for_manual_processing(config=config, wallet=wallet,
                                                            cashout_request=cashout_request)


def manage_payment_address(request, *args, **kwargs):
    action = request.GET['action']
    address_id = request.GET.get('address_id')
    if action == 'update':
        service = _get_weblet(request, using=UMBRELLA)
        method_id = request.GET['method_id']
        name = request.GET['name']
        account_number = request.GET['account_number']
        method = CashOutMethod.objects.using(UMBRELLA).get(pk=method_id)
        if address_id:
            address = CashOutAddress.objects.using(UMBRELLA).get(pk=address_id)
        else:
            try:
                CashOutAddress.objects.using(UMBRELLA).get(service=service, method=method)
                return HttpResponse(json.dumps({'error': "Cash-out address already exists for this payment method."}), 'content-type: text/json')
            except CashOutAddress.DoesNotExist:
                address = CashOutAddress.objects.using(UMBRELLA).create(service=service, method=method)
        address.name = name
        address.account_number = account_number
        address.save(using=UMBRELLA)
        return HttpResponse(json.dumps({'address_id': address.id}), 'content-type: text/json')
    elif action == 'delete':
        CashOutAddress.objects.using(UMBRELLA).get(pk=address_id).delete(using=UMBRELLA)
        return HttpResponse(json.dumps({'success': True}), 'content-type: text/json')


def render_cash_out_request_event(event, request):
    try:
        cor = CashOutRequest.objects.using('wallets').get(pk=event.object_id)
    except CashOutRequest.DoesNotExist:
        return None
    html_template = get_template('cashout/events/request_notice.html')
    service = Service.objects.get(pk=cor.service_id)
    currency_symbol = service.config.currency_symbol
    member = Member.objects.get(pk=cor.member_id)
    from ikwen.conf import settings as ikwen_settings
    c = Context({'cor':  cor, 'service': service,  'currency_symbol': currency_symbol, 'member': member,
                 'MEMBER_AVATAR': ikwen_settings.MEMBER_AVATAR, 'IKWEN_MEDIA_URL': ikwen_settings.MEDIA_URL,
                 'is_iao': service.member == member})
    return html_template.render(c)


def render_cash_out_request_paid(event, request):
    try:
        cor = CashOutRequest.objects.using('wallets').get(pk=event.object_id)
    except CashOutRequest.DoesNotExist:
        return None
    html_template = get_template('cashout/events/payment_notice.html')
    service = Service.objects.get(pk=cor.service_id)
    currency_symbol = service.config.currency_symbol
    member = Member.objects.get(pk=cor.member_id)
    from ikwen.conf import settings as ikwen_settings
    c = Context({'cor':  cor, 'service': service,  'currency_symbol': currency_symbol, 'member': member,
                 'MEMBER_AVATAR': ikwen_settings.MEMBER_AVATAR, 'IKWEN_MEDIA_URL': ikwen_settings.MEDIA_URL,
                 'is_iao': service.member == member})
    return html_template.render(c)


class Payments(TemplateView):
    template_name = 'cashout/payments.html'

    def get_context_data(self, **kwargs):
        service = _get_weblet(self.request, using=UMBRELLA)
        context = super(Payments, self).get_context_data(**kwargs)
        from datetime import datetime
        cash_out_min = service.config.cash_out_min
        wallets = OperatorWallet.objects.using('wallets').filter(nonrel_id=service.id)
        context['wallets'] = wallets
        payments = []
        for p in CashOutRequest.objects.using('wallets').filter(service_id=service.id).order_by('-id')[:10]:
            # Re-transform created_on into a datetime object
            try:
                p.created_on = datetime(*strptime(p.created_on[:19], '%Y-%m-%d %H:%M:%S')[:6])
            except TypeError:
                pass
            if p.amount_paid:
                p.amount = p.amount_paid
            payments.append(p)
        context['payments'] = payments
        context['payment_addresses'] = CashOutAddress.objects.using(UMBRELLA).filter(service=service)
        context['payment_methods'] = CashOutMethod.objects.using(UMBRELLA).all()
        context['cash_out_min'] = cash_out_min
        context['can_cash_out'] = wallets.filter(balance__gte=cash_out_min).count() > 0
        return context
