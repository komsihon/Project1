import json

from django.contrib.auth.decorators import permission_required
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import HttpResponse

from ikwen.foundation.accesscontrol.backends import UMBRELLA
from ikwen.foundation.accesscontrol.models import Member
from ikwen.foundation.core.models import ConsoleEvent
from ikwen.foundation.core.utils import get_service_instance, get_mail_content, add_event
from ikwen.kakocase.models import OperatorProfile, CashOutRequest, CASH_OUT_REQUEST_EVENT
from ikwen.kakocase.utils import get_cash_out_requested_message

# TODO: Copy all delivery men OperatorProfile to the local database in retailer platform deployment script
# because


# TODO: Write test for this function. Create and call the right template in the sending of mail
@permission_required('kakocase.manage_cash_out_request')
def request_cash_out(request, *args, **kwargs):
    service = get_service_instance(using=UMBRELLA)
    config = service.config
    member = request.user
    member_rel = Member.objects.using('rel').get(username=member.username)
    if config.business_type == OperatorProfile.PROVIDER:
        balance = member_rel.provider.balance
    else:
        balance = member_rel.retailer.balance
    if balance < config.cash_out_min:
        response = {'error': 'Balance too low', 'cash_out_min': config.cash_out_min}
        return HttpResponse(json.dumps(response), 'content-type: text/json')
    response = {'success': True}
    with transaction.atomic():
        try:
            CashOutRequest.objects.using('ikwen_kc_rel').get(status=CashOutRequest.PENDING)
        except CashOutRequest.DoesNotExist:
            CashOutRequest.objects.using('ikwen_kc_rel').create(member=request.user, amount=balance,
                                                                profile_type=config.business_type)
            car = CashOutRequest.objects.using('default').create(member=request.user, amount=balance,
                                                                 profile_type=config.business_type)
            if member != config.service.member:
                add_event(service, service.member, CASH_OUT_REQUEST_EVENT, car.id)
                subject, message = get_cash_out_requested_message(member)
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                                extra_context={'member': member})
                sender = '%s <%s>' % ('Ikwen', 'no-reply@ikwen.com')
                msg = EmailMessage(subject, html_content, sender, [config.service.member.email])
                msg.content_subtype = "html"
                msg.send()
        else:
            response = {'error': 'You still have a pending Cash-out Request.'}
    return HttpResponse(json.dumps(response), 'content-type: text/json')
