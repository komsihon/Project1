import json

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.db import transaction
from django.http import HttpResponse

from ikwen.billing.jumbopay.views import do_cashin

from ikwen.billing.models import Payment, MoMoTransaction

from ikwen.conf.settings import WALLETS_DB_ALIAS

from ikwen.accesscontrol.backends import UMBRELLA
from django.core.mail import EmailMessage
from django.utils.translation import gettext as _
from threading import Thread

from ikwen.core.utils import get_service_instance, add_event, get_mail_content

from ikwen.core.views import BaseView

from ikwen.core.models import CASH_OUT_REQUEST_EVENT, OperatorWallet, Config
from ikwen.cashout.models import CashOutRequest, CashOutAddress, CashOutMethod


# TODO: Write test for this function. Create and call the right template in the sending of mail
@permission_required('core.ik_manage_cash_out_request')
def request_cash_out(request, *args, **kwargs):
    address_id = request.GET['address_id']
    address = CashOutAddress.objects.using(UMBRELLA).get(pk=address_id)
    if not address:
        return HttpResponse(json.dumps({'error': "Cash-out address not set"}), 'content-type: text/json')
    service = get_service_instance(using=UMBRELLA)
    iao_profile = service.config
    member = request.user
    wallet = OperatorWallet.objects.using(WALLETS_DB_ALIAS).get(mongo_id=iao_profile.id)
    if wallet.balance < iao_profile.cash_out_min:
        response = {'error': 'Balance too low', 'cash_out_min': iao_profile.cash_out_min}
        return HttpResponse(json.dumps(response), 'content-type: text/json')
    with transaction.atomic():
        method = address.method
        cor = CashOutRequest.objects.using(WALLETS_DB_ALIAS).create(service_id=service.id, member_id=member.id,
                                                           amount=wallet.balance, method=method.name,
                                                           account_number=address.account_number)
        success, message, amount = False, None, None
        if method.type == Payment.MOBILE_MONEY:
            amount = int(wallet.balance)
            tx = do_cashin(address.account_number, amount, 'accesscontrol.Member', member.id)
            if tx.status == MoMoTransaction.SUCCESS:
                success = True
                message = tx.status  # Set message as status to have a short error message
        if not success:
            return HttpResponse(json.dumps({'error': message}), 'content-type: text/json')
        iao_profile.lower_balance(amount)
        add_event(service, member, CASH_OUT_REQUEST_EVENT, cor.id)
        iao = service.member
        if member != iao:
            add_event(service, iao, CASH_OUT_REQUEST_EVENT, cor.id)
            subject = _("Cash-out request on %s" % service.project_name)
            html_content = get_mail_content(subject, '', template_name='core/mails/cash_out_request_notice.html',
                                            extra_context={'cash_out_request': cor, 'member': member})
            retailer = service.retailer
            if retailer:
                retailer_config = Config.objects.using(UMBRELLA).get(service=retailer)
                sender = '%s <no-reply@%s>' % (retailer_config.company_name, retailer.domain)
            else:
                sender = 'ikwen <no-reply@ikwen.com>'
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


def render_cash_out_request_event(event):
    pass


class Payments(BaseView):
    template_name = 'cashout/payments.html'

    def get_context_data(self, **kwargs):
        service = get_service_instance(using=UMBRELLA)
        context = super(Payments, self).get_context_data(**kwargs)
        context['payments'] = CashOutRequest.objects.using(WALLETS_DB_ALIAS).filter(service_id=service.id).order_by('-id')
        context['payment_addresses'] = CashOutAddress.objects.using(UMBRELLA).filter(service=service)
        context['payment_methods'] = CashOutMethod.objects.using(UMBRELLA).all()
        return context
