import json
from time import strptime

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.db import transaction
from django.http import HttpResponse
from django.template import Context
from django.template.loader import get_template
from ikwen.accesscontrol.models import Member

from ikwen.accesscontrol.backends import UMBRELLA
from django.core.mail import EmailMessage
from django.utils.translation import gettext as _
from threading import Thread

from ikwen.core.utils import get_service_instance, add_event, get_mail_content, get_config_model

from ikwen.core.views import BaseView

from ikwen.core.models import CASH_OUT_REQUEST_EVENT, OperatorWallet, Config, Service
from ikwen.cashout.models import CashOutRequest, CashOutAddress, CashOutMethod


# TODO: Write test for this function. Create and call the right template in the sending of mail
@permission_required('accesscontrol.sudo')
def request_cash_out(request, *args, **kwargs):
    address_id = request.GET['address_id']
    address = CashOutAddress.objects.using(UMBRELLA).get(pk=address_id)
    if not address:
        return HttpResponse(json.dumps({'error': "Cash-out address not set"}), 'content-type: text/json')
    business = get_service_instance(using=UMBRELLA)
    iao_profile = get_config_model().objects.using(UMBRELLA).get(service=business)
    member = request.user
    wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=business.id)
    if wallet.balance < iao_profile.cash_out_min:
        response = {'error': 'Balance too low', 'cash_out_min': iao_profile.cash_out_min}
        return HttpResponse(json.dumps(response), 'content-type: text/json')
    with transaction.atomic():
        method = address.method
        cor = CashOutRequest(service_id=business.id, member_id=member.id, amount=wallet.balance,
                             method=method.name, account_number=address.account_number)
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
            retailer_config = Config.objects.using(UMBRELLA).get(service=retailer)
            sender = '%s <no-reply@%s>' % (retailer_config.company_name, retailer.domain)
            event_originator = retailer
        else:
            sender = 'ikwen <no-reply@ikwen.com>'
            event_originator = ikwen_service

        add_event(event_originator, CASH_OUT_REQUEST_EVENT, member=iao, object_id=cor.id)

        subject = _("Cash-out request on %s" % business.project_name)
        html_content = get_mail_content(subject, '', template_name='cashout/mails/request_notice.html',
                                        extra_context={'cash_out_request': cor, 'business': business,
                                                       'service': event_originator})
        msg = EmailMessage(subject, html_content, sender, [iao.email])
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()

    return HttpResponse(json.dumps({'success': True}), 'content-type: text/json')


@permission_required('accesscontrol.sudo')
def manage_payment_address(request, *args, **kwargs):
    action = request.GET['action']
    address_id = request.GET.get('address_id')
    if action == 'update':
        service = get_service_instance(using=UMBRELLA)
        method_id = request.GET['method_id']
        name = request.GET['name']
        account_number = request.GET['account_number']
        method = CashOutMethod.objects.using(UMBRELLA).get(pk=method_id)
        if address_id:
            address = CashOutAddress.objects.using(UMBRELLA).get(pk=address_id)
        else:
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


class Payments(BaseView):
    template_name = 'cashout/payments.html'

    def get_context_data(self, **kwargs):
        service = get_service_instance(using=UMBRELLA)
        context = super(Payments, self).get_context_data(**kwargs)
        from datetime import datetime
        context['now'] = datetime.now()
        context['wallet'] = OperatorWallet.objects.using('wallets').get(nonrel_id=service.id)
        payments = []
        for p in CashOutRequest.objects.using('wallets').filter(service_id=service.id).order_by('-id'):
            # Re-transform created_on into a datetime object
            try:
                p.created_on = datetime(*strptime(p.created_on[:19], '%Y-%m-%d %H:%M:%S')[:6])
            except TypeError:
                pass
            payments.append(p)
        context['payments'] = payments
        context['payment_addresses'] = CashOutAddress.objects.using(UMBRELLA).filter(service=service)
        context['payment_methods'] = CashOutMethod.objects.using(UMBRELLA).all()
        context['cash_out_min'] = service.config.cash_out_min
        return context
