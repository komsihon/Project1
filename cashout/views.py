import json
from time import strptime

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.template import Context
from django.template.loader import get_template
from django.utils.module_loading import import_by_path
from django.views.generic import TemplateView

from ikwen.core.constants import PENDING

from ikwen.accesscontrol.models import Member

from ikwen.accesscontrol.backends import UMBRELLA
from django.core.mail import EmailMessage
from django.utils.translation import gettext as _
from threading import Thread

from ikwen.core.utils import get_service_instance, add_event, get_mail_content, get_config_model
from ikwen.core.models import CASH_OUT_REQUEST_EVENT, OperatorWallet, Config, Service
from ikwen.cashout.models import CashOutRequest, CashOutAddress, CashOutMethod


def _get_service(request, using=None):
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
    business = _get_service(request, using=UMBRELLA)
    try:
        address = CashOutAddress.objects.using(UMBRELLA).get(service=business, method=method)
    except CashOutAddress.DoesNotExist:
        return HttpResponse(json.dumps({'error': _("No Payment method. Please set one first.")}),
                            'content-type: text/json')
    try:
        CashOutRequest.objects.using('wallets').get(service_id=business.id, provider=provider, status=PENDING)
        return HttpResponse(json.dumps({'error': _("You already have a pending request for this wallet.")}),
                            'content-type: text/json')
    except CashOutRequest.DoesNotExist:
        pass
    iao_profile = get_config_model().objects.using(UMBRELLA).get(service=business)
    member = request.user
    wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=business.id, provider=provider)
    if wallet.balance < iao_profile.cash_out_min:
        response = {'error': 'Balance too low', 'cash_out_min': iao_profile.cash_out_min}
        return HttpResponse(json.dumps(response), 'content-type: text/json')
    with transaction.atomic():
        amount = wallet.balance * (100 - iao_profile.cash_out_rate) / 100
        cor = CashOutRequest(service_id=business.id, member_id=member.id, amount=amount,
                             method=method.name, account_number=address.account_number, provider=provider)
        cor.save(using='wallets')
        # TODO: Implement direct payment to user mobile when everything is stable
        # success, message, amount = False, None, wallet.balance
        # if method.type == Payment.MOBILE_MONEY:
        #     amount = int(wallet.balance)
        #     tx = do_cashin(address.account_number, amount, 'accesscontrol.Member', member.id)
        #     if tx.status == MoMoTransaction.SUCCESS:
        #         success = True
        #         message = tx.status  # Set message as status to have a short error message
        #         cor.save(using='wallets')
        # if not success:
        #     return HttpResponse(json.dumps({'error': message}), 'content-type: text/json')
        # iao_profile.lower_balance(amount)
        iao = business.member
        if getattr(settings, 'TESTING', False):
            IKWEN_SERVICE_ID = getattr(settings, 'IKWEN_ID')
            ikwen_service = Service.objects.get(pk=IKWEN_SERVICE_ID)
        else:
            from ikwen.conf.settings import IKWEN_SERVICE_ID
            ikwen_service = Service.objects.using(UMBRELLA).get(pk=IKWEN_SERVICE_ID)
        retailer = business.retailer
        if retailer:
            vendor = retailer
        else:
            vendor = ikwen_service
        vendor_config = Config.objects.using(UMBRELLA).get(service=vendor)
        sender = '%s <no-reply@%s>' % (vendor_config.company_name, vendor.domain)

        add_event(vendor, CASH_OUT_REQUEST_EVENT, member=iao, object_id=cor.id)
        subject = _("Cash-out request on %s" % business.project_name)
        html_content = get_mail_content(subject, '', template_name='cashout/mails/request_notice.html',
                                        extra_context={'cash_out_request': cor, 'business': business,
                                                       'service': vendor, 'config': vendor_config, 'iao': iao,
                                                       'wallet': wallet, 'iao_profile': iao_profile})
        msg = EmailMessage(subject, html_content, sender, [iao.email])
        msg.bcc = ['k.sihon@ikwen.com', 'contact@ikwen.com']
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()

    return HttpResponse(json.dumps({'success': True}), 'content-type: text/json')


def manage_payment_address(request, *args, **kwargs):
    action = request.GET['action']
    address_id = request.GET.get('address_id')
    if action == 'update':
        service = _get_service(request, using=UMBRELLA)
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
                address = CashOutAddress()
        address.service = service
        address.method = method
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
        service = _get_service(self.request, using=UMBRELLA)
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
