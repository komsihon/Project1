# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta
from threading import Thread

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models.loading import get_model
from django.http import HttpResponseRedirect
from django.utils.http import urlquote
from django.utils.translation import gettext as _
from ikwen.core.constants import CONFIRMED

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import SUDO
from ikwen.billing.models import Invoice, Payment, PAYMENT_CONFIRMATION, InvoiceEntry, Product, InvoiceItem, Donation
from ikwen.billing.mtnmomo.views import MTN_MOMO
from ikwen.billing.orangemoney.views import ORANGE_MONEY
from ikwen.billing.utils import get_invoicing_config_instance, get_days_count, \
    get_payment_confirmation_message, share_payment_and_set_stats, get_next_invoice_number
from ikwen.core.models import Service
from ikwen.core.utils import add_database_to_settings, get_service_instance, add_event, get_mail_content

logger = logging.getLogger('ikwen')

subscription_model_name = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')
app_label = subscription_model_name.split('.')[0]
model = subscription_model_name.split('.')[1]
Subscription = get_model(app_label, model)


def set_invoice_checkout(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_BEFORE_CHECKOUT"
    """
    if request.user.is_anonymous():
        next_url = reverse('ikwen:sign_in')
        referrer = request.META.get('HTTP_REFERER')
        if referrer:
            next_url += '?' + urlquote(referrer)
        return HttpResponseRedirect(next_url)
    service = get_service_instance()
    config = service.config
    invoice_id = request.POST['invoice_id']
    try:
        extra_months = int(request.POST.get('extra_months', '0'))
    except ValueError:
        extra_months = 0
    invoice = Invoice.objects.get(pk=invoice_id)
    amount = invoice.amount
    if extra_months:
        amount += invoice.service.monthly_cost * extra_months
    if config.__dict__.get('processing_fees_on_customer'):
        amount += config.ikwen_share_fixed
    request.session['amount'] = amount
    request.session['model_name'] = 'billing.Invoice'
    request.session['object_id'] = invoice_id
    request.session['extra_months'] = extra_months

    mean = request.GET.get('mean', MTN_MOMO)
    request.session['mean'] = mean
    if mean == MTN_MOMO:
        request.session['is_momo_payment'] = True
    elif mean == ORANGE_MONEY:
        request.session['notif_url'] = service.url
        request.session['return_url'] = service.url + reverse('billing:invoice_detail', args=(invoice_id, ))
        request.session['cancel_url'] = service.url + reverse('billing:invoice_detail', args=(invoice_id, ))
        request.session['is_momo_payment'] = False


def confirm_invoice_payment(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_AFTER_CHECKOUT"
    """
    service = get_service_instance()
    config = service.config
    invoice_id = request.session['object_id']
    invoice = Invoice.objects.get(pk=invoice_id)
    invoice.status = Invoice.PAID
    if config.__dict__.get('processing_fees_on_customer'):
        invoice.processing_fees = config.ikwen_share_fixed
    invoice.save()
    amount = request.session['amount']
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY, amount=amount)
    s = invoice.service
    if config.__dict__.get('separate_billing_cycle', True):
        extra_months = request.session['extra_months']
        total_months = invoice.months_count + extra_months
        days = get_days_count(total_months)
    else:
        days = invoice.subscription.product.duration
        total_months = None
    if s.status == Service.SUSPENDED:
        invoicing_config = get_invoicing_config_instance()
        days -= invoicing_config.tolerance  # Catch-up days that were offered before service suspension
        expiry = datetime.now() + timedelta(days=days)
        expiry = expiry.date()
    elif s.expiry:
        expiry = s.expiry + timedelta(days=days)
    else:
        expiry = datetime.now() + timedelta(days=days)
        expiry = expiry.date()
    s.expiry = expiry
    s.status = Service.ACTIVE
    if invoice.is_one_off:
        s.version = Service.FULL
    s.save()
    mean = request.session['mean']
    share_payment_and_set_stats(invoice, total_months, mean)
    member = request.user
    add_event(service, PAYMENT_CONFIRMATION, member=member, object_id=invoice.id)
    partner = s.retailer
    if partner:
        add_database_to_settings(partner.database)
        sudo_group = Group.objects.using(partner.database).get(name=SUDO)
    else:
        sudo_group = Group.objects.using(UMBRELLA).get(name=SUDO)
    add_event(service, PAYMENT_CONFIRMATION, group_id=sudo_group.id, object_id=invoice.id)
    if member.email:
        subject, message, sms_text = get_payment_confirmation_message(payment, member)
        html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
        sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
        msg = EmailMessage(subject, html_content, sender, [member.email])
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()
    next_url = service.url + reverse('billing:invoice_detail', args=(invoice.id, ))
    return {'success': True, 'next_url': next_url}


def product_set_checkout(request, *args, **kwargs):
    service = get_service_instance()
    product_id = request.POST['product_id']
    product = Product.objects.get(pk=product_id)
    member = request.user
    now = datetime.now()
    expiry = now + timedelta(days=product.duration)
    subscription = Subscription.objects.create(member=member, product=product, since=now, expiry=expiry)
    number = get_next_invoice_number()
    item = InvoiceItem(label=product.name)
    entry = InvoiceEntry(item=item, short_description=product.short_description, total=product.cost)
    months_count = product.duration / 30
    invoice = Invoice.objects.create(subscription=subscription, amount=product.cost, number=number, due_date=now,
                                     last_reminder=now, is_one_off=True, entries=[entry], months_count=months_count)

    request.session['amount'] = product.cost
    request.session['model_name'] = 'billing.Invoice'
    request.session['object_id'] = invoice.id

    mean = request.GET.get('mean', MTN_MOMO)
    request.session['mean'] = mean
    if mean == MTN_MOMO:
        request.session['is_momo_payment'] = True
    elif mean == ORANGE_MONEY:
        request.session['notif_url'] = service.url
        request.session['return_url'] = service.url + reverse('billing:pricing')
        request.session['cancel_url'] = service.url + reverse('billing:pricing')
        request.session['is_momo_payment'] = False


def product_do_checkout(request, *args, **kwargs):
    invoice_id = request.session['object_id']
    mean = request.session['mean']
    invoice = Invoice.objects.get(pk=invoice_id)
    member = request.user
    subscription = invoice.subscription
    subscription.status = Subscription.ACTIVE
    subscription.save()
    invoice.status = Invoice.PAID
    invoice.save()
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY, amount=invoice.amount)
    share_payment_and_set_stats(invoice, payment_mean_slug=mean)
    service = get_service_instance()
    config = service.config
    if member.email:
        subject, message, sms_text = get_payment_confirmation_message(payment, member)
        html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
        sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
        msg = EmailMessage(subject, html_content, sender, [member.email])
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()
    messages.success(request, _("Successful payment. Your subscription is now active."))
    next_url = service.url + reverse('billing:invoice_detail', args=(invoice.id, ))
    return {'success': True, 'next_url': next_url}


def donation_set_checkout(request, *args, **kwargs):
    service = get_service_instance()
    member = request.user
    amount = float(request.POST['amount'])
    message = request.POST.get('message')
    if member.is_authenticated() and not request.POST.get('anonymous_donation'):
        donation = Donation.objects.create(member=member, amount=amount, message=message)
    else:
        donation = Donation.objects.create(amount=amount, message=message)
    request.session['amount'] = donation.amount
    request.session['model_name'] = 'billing.Donation'
    request.session['object_id'] = donation.id

    mean = request.GET.get('mean', MTN_MOMO)
    request.session['mean'] = mean
    if mean == MTN_MOMO:
        request.session['is_momo_payment'] = True
    elif mean == ORANGE_MONEY:
        request.session['notif_url'] = service.url
        request.session['return_url'] = service.url + reverse('billing:donate')
        request.session['cancel_url'] = service.url + reverse('billing:donate')
        request.session['is_momo_payment'] = False


def donation_do_checkout(request, *args, **kwargs):
    donation_id = request.session['object_id']
    mean = request.session['mean']
    donation = Donation.objects.get(pk=donation_id)
    donation.status = CONFIRMED
    donation.save()
    share_payment_and_set_stats(donation, payment_mean_slug=mean)

    service = get_service_instance()
    # config = service.config
    # if member.email:
    #     subject, message, sms_text = get_payment_confirmation_message(payment, member)
    #     html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
    #     sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
    #     msg = EmailMessage(subject, html_content, sender, [member.email])
    #     msg.content_subtype = "html"
    #     Thread(target=lambda m: m.send(), args=(msg,)).start()
    messages.success(request, _("Successful payment. Thank you soooo much for your donation."))
    next_url = service.url + reverse('billing:donate')
    return {'success': True, 'next_url': next_url}
