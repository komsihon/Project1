# -*- coding: utf-8 -*-
from threading import Thread

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Sum
from djangotoolbox.admin import admin
from django.utils.translation import gettext as _
from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.billing.models import MoMoTransaction

from ikwen.core.models import Service, Config, CASH_OUT_REQUEST_PAID
from ikwen.core.models import OperatorWallet
from ikwen.core.utils import get_mail_content, add_event, set_counters, increment_history_field
from ikwen.cashout.models import CashOutMethod, CashOutRequest, CashOutAddress

__author__ = 'Kom Sihon'


class CashOutMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'image', 'is_active', )
    search_fields = ('name', )
    ordering = ('-id', )


class CashOutRequestAdmin(admin.ModelAdmin):
    list_display = ('service', 'member', 'amount_payable', 'method', 'account_number', 'created_on', 'status', 'teller', )
    search_fields = ('name', 'teller_username', )
    list_filter = ('created_on', )
    ordering = ('-id', )

    def get_queryset(self, request):
        return super(CashOutRequestAdmin, self).get_queryset(request).using('wallets')

    def get_readonly_fields(self, request, obj=None):
        if obj.status == CashOutRequest.PAID:
            return 'service_id', 'member_id', 'method', 'account_number', 'amount', 'amount_paid', 'paid_on', 'reference', 'status', 'name', 'teller_username'
        return 'service_id', 'member_id', 'amount', 'method', 'account_number', 'name', 'teller_username'

    def save_model(self, request, obj, form, change):
        if obj.status == CashOutRequest.PAID:
            if not obj.reference:
                self.message_user(request, "Reference number missing", messages.ERROR)
                return
            obj.teller_username = request.user.username
            service = Service.objects.get(pk=obj.service_id)
            wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=service.id, provider=obj.provider)
            method = CashOutMethod.objects.get(slug=obj.provider)
            address = CashOutAddress.objects.using(UMBRELLA).get(service=service, method=method)
            with transaction.atomic(using='wallets'):
                queryset = MoMoTransaction.objects.using('wallets') \
                    .filter(service_id=service.id, created_on__gt=obj.paid_on,
                            is_running=False, status=MoMoTransaction.SUCCESS, wallet=obj.provider)
                aggr = queryset.aggregate(Sum('amount'))
                aggr_fees = queryset.aggregate(Sum('fees'))
                aggr_dara_fees = queryset.aggregate(Sum('dara_fees'))
                amount_successful = 0
                if aggr['amount__sum']:
                    amount_successful = aggr['amount__sum'] - aggr_fees['fees__sum'] - aggr_dara_fees['dara_fees__sum']
                wallet.balance = amount_successful
                wallet.save(using='wallets')
                iao = service.member
                if getattr(settings, 'TESTING', False):
                    IKWEN_SERVICE_ID = getattr(settings, 'IKWEN_ID')
                    ikwen_service = Service.objects.get(pk=IKWEN_SERVICE_ID)
                else:
                    from ikwen.conf.settings import IKWEN_SERVICE_ID
                    ikwen_service = Service.objects.get(pk=IKWEN_SERVICE_ID)
                retailer = service.retailer
                if retailer:
                    retailer_config = Config.objects.get(service=retailer)
                    sender = '%s <no-reply@%s>' % (retailer_config.company_name, retailer.domain)
                    event_originator = retailer
                else:
                    sender = 'ikwen <no-reply@ikwen.com>'
                    event_originator = ikwen_service

                add_event(event_originator, CASH_OUT_REQUEST_PAID, member=iao, object_id=obj.id)

                subject = _("Money transfer confirmation")
                html_content = get_mail_content(subject, '', template_name='cashout/mails/payment_notice.html',
                                                extra_context={'cash_out_request': obj, 'business': service,
                                                               'address': address, 'service': event_originator})
                msg = EmailMessage(subject, html_content, sender, [iao.email])
                msg.bcc = ['rsihon@gmail.com']
                msg.content_subtype = "html"
                Thread(target=lambda m: m.send(), args=(msg,)).start()

                set_counters(ikwen_service)
                increment_history_field(ikwen_service, 'cash_out_history', obj.amount)
                increment_history_field(ikwen_service, 'cash_out_count_history')
        super(CashOutRequestAdmin, self).save_model(request, obj, form, change)


if getattr(settings, 'IS_UMBRELLA', False):
    admin.site.register(CashOutMethod, CashOutMethodAdmin)
    admin.site.register(CashOutRequest, CashOutRequestAdmin)
