# -*- coding: utf-8 -*-
import json
from datetime import date
from datetime import datetime
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from ikwen.foundation.accesscontrol.backends import UMBRELLA

from ikwen.foundation.core.views import BaseView
from ikwen.foundation.billing.models import Invoice
from ikwen.foundation.billing.utils import get_invoicing_config_instance, get_subscription_model


class BillingBaseView(BaseView):
    def get_context_data(self, **kwargs):
        context = super(BillingBaseView, self).get_context_data(**kwargs)
        context['invoicing_config'] = get_invoicing_config_instance()
        return context


class InvoiceList(BillingBaseView):

    def get_context_data(self, **kwargs):
        context = super(InvoiceList, self).get_context_data(**kwargs)
        subscription_id = kwargs['subscription_id']
        subscription_model = get_subscription_model()
        subscriptions = list(subscription_model.objects.filter(pk=subscription_id))
        context['unpaid_invoices_count'] = Invoice.objects.filter(
            Q(status=Invoice.PENDING) | Q(status=Invoice.OVERDUE),
            subscription__in=subscriptions
        ).count()
        invoices = Invoice.objects.filter(subscription__in=subscriptions).order_by('-date_issued')
        for invoice in invoices:
            if invoice.status == Invoice.PAID:
                payments = list(invoice.payment_set.all().order_by('-id'))
                invoice.paid_on = payments[-1].created_on.strftime('%B %d, %Y %H:%M')
                invoice.method = payments[-1].method
        context['invoices'] = invoices
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        app_label = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'ikwen.foundation.billing.Subscription').split('.')[0]
        return TemplateResponse(request, [
            'billing/%s/invoice_list.html' % app_label,
            'billing/invoice_list.html'
        ], context)


class InvoiceDetail(BillingBaseView):
    template_name = 'billing/invoice_detail.html'

    def get_context_data(self, **kwargs):
        context = super(InvoiceDetail, self).get_context_data(**kwargs)
        invoice_id = self.kwargs['invoice_id']
        invoice = get_object_or_404(Invoice, pk=invoice_id)
        context['invoice'] = invoice
        if getattr(settings, 'IS_IKWEN', False):
            context['customer_config'] = invoice.service.config

        # User may want to extend the payment above the default duration
        # Below are a list of possible extension dates on a year
        expiry = invoice.subscription.expiry
        exp_year = expiry.year
        exp_month = expiry.month
        exp_day = expiry.day
        extensions = []
        for i in (1, 2, 3, 6, 12):
            year = exp_year
            month = exp_month + i
            day = exp_day
            if month > 12:
                year += 1
                month = (exp_month + i) % 12
            valid_date = False
            while not valid_date:
                try:
                    next_expiry = date(year, month, day)
                    extensions.append({'expiry': next_expiry, 'months': i})
                    valid_date = True
                except:
                    day -= 1
        context['extensions'] = extensions
        return context


@login_required
def change_billing_cycle(request, *args, **kwargs):
    subscription_id = request.GET['subscription_id']
    new_cycle = request.GET['new_cycle']
    subscription_model = get_subscription_model()
    if getattr(settings, 'IS_IKWEN', False):
        service = subscription_model.objects.using(UMBRELLA).get(pk=subscription_id)
    else:
        service = subscription_model.objects.get(pk=subscription_id)
    service.billing_cycle = new_cycle
    service.save()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


class NoticeMail(BillingBaseView):
    """
    Preview of invoing system notice mails
    """
    template_name = 'billing/mails/notice.html'

    def get_context_data(self, **kwargs):
        context = super(NoticeMail, self).get_context_data(**kwargs)
        context['invoice_url'] = 'some_url'
        return context