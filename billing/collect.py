# -*- coding: utf-8 -*-
import json
import logging
import string
from datetime import datetime, timedelta
import random
from threading import Thread

import requests
from currencies.models import Currency
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models import Sum
from django.http import HttpResponseRedirect, HttpResponse
from django.utils.translation import gettext as _, activate

from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.constants import CONFIRMED
from ikwen.core.models import Service
from ikwen.core.utils import add_database_to_settings, get_service_instance, add_event, get_mail_content, XEmailMessage
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import SUDO
from ikwen.billing.models import Invoice, Payment, PAYMENT_CONFIRMATION, InvoiceEntry, Product, InvoiceItem, Donation, \
    SupportBundle, SupportCode, MoMoTransaction
from ikwen.billing.mtnmomo.views import MTN_MOMO
from ikwen.billing.utils import get_invoicing_config_instance, get_days_count, get_payment_confirmation_message, \
    share_payment_and_set_stats, get_next_invoice_number, refill_tsunami_messaging_bundle, get_subscription_model, \
    notify_event, generate_pdf_invoice
from ikwen.billing.decorators import momo_gateway_request, momo_gateway_callback

from daraja.models import DARAJA

logger = logging.getLogger('ikwen')

Subscription = get_subscription_model()


@momo_gateway_request
def set_invoice_checkout(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_BEFORE_CHECKOUT"
    """
    invoice_id = request.POST['product_id']
    invoice = Invoice.objects.select_related('subscription').get(pk=invoice_id)
    service = get_service_instance()
    config = service.config
    invoicing_config = get_invoicing_config_instance()
    try:
        extra_months = int(request.POST.get('extra_months', '0'))
    except ValueError:
        extra_months = 0
    try:
        aggr = Payment.objects.filter(invoice=invoice).aggregate(Sum('amount'))
        amount_paid = aggr['amount__sum']
    except:
        amount_paid = 0
    amount = invoice.amount - amount_paid
    if extra_months:
        amount += invoice.service.monthly_cost * extra_months
    if invoicing_config.processing_fees_on_customer:
        amount += config.ikwen_share_fixed

    signature = ''.join([random.SystemRandom().choice(string.ascii_letters + string.digits) for i in range(16)])
    model_name = 'billing.Invoice'
    mean = request.GET.get('mean', MTN_MOMO)
    payer_id = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    MoMoTransaction.objects.using(WALLETS_DB_ALIAS).filter(object_id=invoice_id).delete()
    tx = MoMoTransaction.objects.using(WALLETS_DB_ALIAS)\
        .create(service_id=service.id, type=MoMoTransaction.CASH_OUT, amount=amount, phone='N/A', model=model_name,
                object_id=invoice_id, task_id=signature, wallet=mean, username=payer_id, is_running=True)
    notification_url = reverse('billing:confirm_service_invoice_payment', args=(tx.id, signature, extra_months))
    cancel_url = reverse('billing:invoice_detail', args=(invoice_id, ))
    return_url = reverse('billing:invoice_detail', args=(invoice_id, ))
    return amount, notification_url, return_url, cancel_url


@momo_gateway_callback
def confirm_service_invoice_payment(request, *args, **kwargs):
    """
    This view is run after successful user cashout "MOMO_AFTER_CHECKOUT"
    """
    tx = kwargs['tx']  # Decoration with @momo_gateway_callback makes 'tx' available in kwargs
    extra_months = int(kwargs['extra_months'])
    invoice_id = tx.object_id
    amount = tx.amount
    now = datetime.now()
    ikwen_service = get_service_instance()
    invoice = Invoice.objects.get(pk=invoice_id)
    invoice.paid += amount
    invoice.status = Invoice.PAID
    invoice.save()
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY,
                                     amount=amount, processor_tx_id=tx.processor_tx_id)
    service = invoice.service
    total_months = invoice.months_count + extra_months
    days = get_days_count(total_months)
    invoicing_config = get_invoicing_config_instance()
    if service.status == Service.SUSPENDED:
        days -= invoicing_config.tolerance  # Catch-up days that were offered before service suspension
        expiry = now + timedelta(days=days)
        expiry = expiry.date()
    elif service.expiry:
        expiry = service.expiry + timedelta(days=days)
    else:
        expiry = now + timedelta(days=days)
        expiry = expiry.date()
    service.expiry = expiry
    service.status = Service.ACTIVE
    if invoice.is_one_off:
        service.version = Service.FULL
        try:
            support_bundle = SupportBundle.objects.get(type=SupportBundle.TECHNICAL, channel=SupportBundle.PHONE, cost=0)
            token = ''.join([random.SystemRandom().choice(string.digits) for i in range(6)])
            support_expiry = now + timedelta(days=support_bundle.duration)
            SupportCode.objects.create(service=service, token=token, bundle=support_bundle,
                                       balance=support_bundle.quantity, expiry=support_expiry)
            logger.debug("Free Support Code created for %s" % service)
        except SupportBundle.DoesNotExist:
            logger.error("Free Support Code not created for %s" % service, exc_info=True)
    service.save()
    mean = tx.wallet
    is_early_payment = False
    if service.app.slug == 'kakocase' or service.app.slug == 'webnode':
        if invoice.due_date <= now.date():
            is_early_payment = True
        refill_tsunami_messaging_bundle(service, is_early_payment)
    share_payment_and_set_stats(invoice, total_months, mean, tx)
    member = service.member
    vendor = service.retailer
    vendor_is_dara = vendor and vendor.app.slug == DARAJA
    if vendor and not vendor_is_dara:
        add_database_to_settings(vendor.database)
        sudo_group = Group.objects.using(vendor.database).get(name=SUDO)
    else:
        vendor = ikwen_service
        sudo_group = Group.objects.using(UMBRELLA).get(name=SUDO)
    add_event(vendor, PAYMENT_CONFIRMATION, member=member, object_id=invoice.id)
    add_event(vendor, PAYMENT_CONFIRMATION, group_id=sudo_group.id, object_id=invoice.id)

    try:
        invoice_pdf_file = generate_pdf_invoice(invoicing_config, invoice)
    except:
        invoice_pdf_file = None

    if member.email:
        activate(member.language)
        invoice_url = ikwen_service.url + reverse('billing:invoice_detail', args=(invoice.id,))
        subject, message, sms_text = get_payment_confirmation_message(payment, member)
        html_content = get_mail_content(subject, message, service=vendor, template_name='billing/mails/notice.html',
                                        extra_context={'member_name': member.first_name, 'invoice': invoice,
                                                       'cta': _("View invoice"), 'invoice_url': invoice_url,
                                                       'early_payment': is_early_payment})
        sender = '%s <no-reply@%s>' % (vendor.config.company_name, ikwen_service.domain)
        msg = XEmailMessage(subject, html_content, sender, [member.email])
        if vendor != ikwen_service and not vendor_is_dara:
            msg.service = vendor
        if invoice_pdf_file:
            msg.attach_file(invoice_pdf_file)
        msg.content_subtype = "html"
        if getattr(settings, 'UNIT_TESTING', False):
            msg.send()
        else:
            Thread(target=lambda m: m.send(), args=(msg,)).start()
    return HttpResponse("Notification received")


@momo_gateway_callback
def confirm_invoice_payment(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_AFTER_CHECKOUT"
    """
    from echo.models import Balance
    from echo.utils import LOW_MAIL_LIMIT, notify_for_low_messaging_credit, notify_for_empty_messaging_credit
    tx = kwargs['tx']  # Decoration with @momo_gateway_callback makes 'tx' available in kwargs
    extra_months = int(kwargs['extra_months'])
    now = datetime.now()
    service = get_service_instance()
    config = service.config
    invoicing_config = get_invoicing_config_instance()
    invoice_id = tx.object_id
    amount = tx.amount
    invoice = Invoice.objects.select_related('subscription', 'member').get(pk=invoice_id)
    invoice.paid += amount
    invoice.status = Invoice.PAID
    if invoicing_config.processing_fees_on_customer:
        invoice.processing_fees = config.ikwen_share_fixed
    invoice.save()
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY,
                                     amount=amount, processor_tx_id=tx.processor_tx_id)
    subscription = invoice.subscription
    from ikwen_foulassi.foulassi.models import SchoolConfig
    from ikwen_foulassi.foulassi.views import SCHOOL_WEBSITE_MONTH_COUNT
    if subscription.app.slug == 'foulassi' and invoice.months_count == SCHOOL_WEBSITE_MONTH_COUNT:
        school_config = SchoolConfig.objects.get(service=subscription)
        school_config.website_is_active = True
        school_config.save()
        subscription.monthly_cost += int(invoice.amount / 12)
        subscription.save()
        extra_months, total_months = 0, None
    else:
        if invoicing_config.separate_billing_cycle:
            total_months = invoice.months_count + extra_months
            days = get_days_count(total_months)
        else:
            extra_months = 0
            days = invoice.subscription.product.duration
            total_months = None
        if subscription.status == Service.SUSPENDED:
            invoicing_config = get_invoicing_config_instance()
            days -= invoicing_config.tolerance  # Catch-up days that were offered before service suspension
            expiry = now + timedelta(days=days)
            expiry = expiry.date()
        elif subscription.expiry:
            expiry = subscription.expiry + timedelta(days=days)
        else:
            expiry = now + timedelta(days=days)
            expiry = expiry.date()
        subscription.expiry = expiry
        subscription.status = Service.ACTIVE
        subscription.save()
    mean = tx.wallet
    share_payment_and_set_stats(invoice, total_months, mean)
    member = invoice.member
    sudo_group = Group.objects.using(UMBRELLA).get(name=SUDO)
    if member:
        add_event(service, PAYMENT_CONFIRMATION, member=member, object_id=invoice.id)
    add_event(service, PAYMENT_CONFIRMATION, group_id=sudo_group.id, object_id=invoice.id)

    if invoicing_config.return_url:
        params = {'reference_id': subscription.reference_id, 'invoice_number': invoice.number,
                  'amount_paid': amount, 'processor_tx_id': tx.processor_tx_id, 'extra_months': extra_months}
        Thread(target=notify_event, args=(service, invoicing_config.return_url, params)).start()

    try:
        invoice_pdf_file = generate_pdf_invoice(invoicing_config, invoice)
    except:
        invoice_pdf_file = None

    balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
    if member and member.email:
        if 0 < balance.mail_count < LOW_MAIL_LIMIT:
            notify_for_low_messaging_credit(service, balance)
        if balance.mail_count <= 0:
            notify_for_empty_messaging_credit(service, balance)
        else:
            try:
                currency = Currency.active.default().symbol
            except:
                currency = config.currency_code
            invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id,))
            subject, message, sms_text = get_payment_confirmation_message(payment, member)
            html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                            extra_context={'member_name': member.first_name, 'invoice': invoice,
                                                           'cta': _("View invoice"), 'invoice_url': invoice_url,
                                                           'currency': currency})
            sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
            msg = XEmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            if invoice_pdf_file:
                msg.attach_file(invoice_pdf_file)
            balance.mail_count -= 1
            balance.save()
            Thread(target=lambda m: m.send(), args=(msg,)).start()
    return HttpResponse("Notification received")


@momo_gateway_request
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
                                     last_reminder=now, is_one_off=product.is_one_off, entries=[entry], months_count=months_count)
    amount = invoice.amount
    signature = ''.join([random.SystemRandom().choice(string.ascii_letters + string.digits) for i in range(16)])
    model_name = 'billing.Invoice'
    mean = request.GET.get('mean', MTN_MOMO)
    payer_id = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    MoMoTransaction.objects.using(WALLETS_DB_ALIAS).filter(object_id=invoice.id).delete()
    tx = MoMoTransaction.objects.using(WALLETS_DB_ALIAS)\
        .create(service_id=service.id, type=MoMoTransaction.CASH_OUT, amount=amount, phone='N/A', model=model_name,
                object_id=invoice.id, task_id=signature, wallet=mean, username=payer_id, is_running=True)
    notification_url = reverse('billing:product_do_checkout', args=(tx.id, signature))
    cancel_url = request.META['HTTP_REFERER']
    return_url = reverse('billing:invoice_detail', args=(invoice.id, ))
    return amount, notification_url, return_url, cancel_url


@momo_gateway_callback
def product_do_checkout(request, *args, **kwargs):
    from echo.models import Balance
    from echo.utils import LOW_MAIL_LIMIT, notify_for_low_messaging_credit, notify_for_empty_messaging_credit
    tx = kwargs['tx']
    invoice = Invoice.objects.get(pk=tx.object_id)
    member = invoice.member
    subscription = invoice.subscription
    subscription.status = Subscription.ACTIVE
    subscription.save()
    invoice.status = Invoice.PAID
    invoice.save()
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY,
                                     amount=invoice.amount, processor_tx_id=tx.processor_tx_id)
    share_payment_and_set_stats(invoice, payment_mean_slug=tx.wallet)
    service = get_service_instance()
    config = service.config

    balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
    if member and member.email:
        if 0 < balance.mail_count < LOW_MAIL_LIMIT:
            notify_for_low_messaging_credit(service, balance)
        if balance.mail_count <= 0 and not getattr(settings, 'UNIT_TESTING', False):
            notify_for_empty_messaging_credit(service, balance)
        else:
            invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id,))
            subject, message, sms_text = get_payment_confirmation_message(payment, member)
            html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                            extra_context={'member_name': member.first_name, 'invoice': invoice,
                                                           'cta': _("View invoice"), 'invoice_url': invoice_url})
            sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            Thread(target=lambda m: m.send(), args=(msg,)).start()
    messages.success(request, _("Successful payment. Your subscription is now active."))
    return HttpResponseRedirect(request.session['return_url'])


@momo_gateway_request
def donation_set_checkout(request, *args, **kwargs):
    service = get_service_instance()
    member = request.user
    amount = float(request.POST['amount'])
    message = request.POST.get('message')
    if member.is_authenticated() and not request.POST.get('anonymous_donation'):
        donation = Donation.objects.create(member=member, amount=amount, message=message)
    else:
        donation = Donation.objects.create(amount=amount, message=message)
    signature = ''.join([random.SystemRandom().choice(string.ascii_letters + string.digits) for i in range(16)])
    model_name = 'billing.Donation'
    mean = request.GET.get('mean', MTN_MOMO)
    payer_id = request.user.username if request.user.is_authenticated() else '<Anonymous>'
    tx = MoMoTransaction.objects.using(WALLETS_DB_ALIAS) \
        .create(service_id=service.id, type=MoMoTransaction.CASH_OUT, amount=amount, phone='N/A', model=model_name,
                object_id=donation.id, task_id=signature, wallet=mean, username=payer_id, is_running=True)
    notification_url = reverse('billing:confirm_service_invoice_payment', args=(tx.id, signature))
    cancel_url = reverse('billing:donate')
    return_url = reverse('billing:donate')
    return amount, notification_url, return_url, cancel_url


@momo_gateway_callback
def donation_do_checkout(request, *args, **kwargs):
    tx = kwargs['tx']
    donation = Donation.objects.get(pk=tx.object_id)
    donation.status = CONFIRMED
    donation.save()
    share_payment_and_set_stats(donation, payment_mean_slug=tx.wallet)
    service = get_service_instance()
    # config = service.config
    # if member.email:
    #     subject, message, sms_text = get_payment_confirmation_message(payment, member)
    #     html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html')
    #     sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
    #     msg = EmailMessage(subject, html_content, sender, [member.email])
    #     msg.content_subtype = "html"
    #     Thread(target=lambda m: m.send(), args=(msg,)).start()
    return HttpResponse("Notification received.")
