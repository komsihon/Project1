# -*- coding: utf-8 -*-
import logging
import string
from datetime import datetime, timedelta
import random
from threading import Thread

from currencies.models import Currency
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.utils.http import urlquote
from django.utils.translation import gettext as _

from echo.utils import LOW_MAIL_LIMIT, notify_for_low_messaging_credit, notify_for_empty_messaging_credit
from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.constants import CONFIRMED
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import SUDO
from ikwen.billing.models import Invoice, Payment, PAYMENT_CONFIRMATION, InvoiceEntry, Product, InvoiceItem, Donation, \
    SupportBundle, SupportCode
from ikwen.billing.mtnmomo.views import MTN_MOMO
from ikwen.billing.utils import get_invoicing_config_instance, get_days_count, get_payment_confirmation_message, \
    share_payment_and_set_stats, get_next_invoice_number, refill_tsunami_messaging_bundle, get_subscription_model, \
    notify_event
from ikwen.core.models import Service
from ikwen.core.utils import add_database_to_settings, get_service_instance, add_event, get_mail_content, XEmailMessage
from echo.models import Balance

logger = logging.getLogger('ikwen')

Subscription = get_subscription_model()


def set_invoice_checkout(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_BEFORE_CHECKOUT"
    """
    invoice_id = request.POST['product_id']
    invoice = Invoice.objects.select_related('subscription').get(pk=invoice_id)
    member = invoice.subscription.member
    if member and not member.is_ghost:
        if request.user != member:
            next_url = reverse('ikwen:sign_in')
            referrer = request.META.get('HTTP_REFERER')
            if referrer:
                next_url += '?' + urlquote(referrer)
            return HttpResponseRedirect(next_url)
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
    except IndexError:
        amount_paid = 0
    amount = invoice.amount - amount_paid
    if extra_months:
        amount += invoice.service.monthly_cost * extra_months
    if invoicing_config.processing_fees_on_customer:
        amount += config.ikwen_share_fixed
    request.session['amount'] = amount
    request.session['model_name'] = 'billing.Invoice'
    request.session['object_id'] = invoice_id
    request.session['extra_months'] = extra_months

    mean = request.GET.get('mean', MTN_MOMO)
    request.session['mean'] = mean
    request.session['notif_url'] = service.url  # Orange Money only
    request.session['cancel_url'] = service.url + reverse('billing:invoice_detail', args=(invoice_id, )) # Orange Money only
    request.session['return_url'] = service.url + reverse('billing:invoice_detail', args=(invoice_id, ))


def confirm_service_invoice_payment(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_AFTER_CHECKOUT"
    """
    tx = kwargs.get('transaction')
    now = datetime.now()
    ikwen_service = get_service_instance()
    invoice_id = request.session['object_id']
    amount = request.session['amount']
    invoice = Invoice.objects.get(pk=invoice_id)
    invoice.paid += amount
    invoice.status = Invoice.PAID
    invoice.save()
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY,
                                     amount=amount, processor_tx_id=tx.processor_tx_id)
    service = invoice.service
    extra_months = request.session['extra_months']
    total_months = invoice.months_count + extra_months
    days = get_days_count(total_months)
    if service.status == Service.SUSPENDED:
        invoicing_config = get_invoicing_config_instance()
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
    mean = request.session['mean']
    is_early_payment = False
    if service.app.slug == 'kakocase' or service.app.slug == 'webnode':
        if invoice.due_date <= now.date():
            is_early_payment = True
        refill_tsunami_messaging_bundle(service, is_early_payment)
    share_payment_and_set_stats(invoice, total_months, mean)
    member = request.user
    vendor = service.retailer
    if vendor:
        add_database_to_settings(vendor.database)
        sudo_group = Group.objects.using(vendor.database).get(name=SUDO)
    else:
        vendor = ikwen_service
        sudo_group = Group.objects.using(UMBRELLA).get(name=SUDO)
    add_event(vendor, PAYMENT_CONFIRMATION, member=member, object_id=invoice.id)
    add_event(vendor, PAYMENT_CONFIRMATION, group_id=sudo_group.id, object_id=invoice.id)

    if member.email:
        invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id,))
        subject, message, sms_text = get_payment_confirmation_message(payment, member)
        html_content = get_mail_content(subject, message, service=vendor, template_name='billing/mails/notice.html',
                                        extra_context={'member_name': member.first_name, 'invoice': invoice,
                                                       'cta': _("View invoice"), 'invoice_url': invoice_url,
                                                       'early_payment': is_early_payment})
        sender = '%s <no-reply@%s>' % (vendor.config.company_name, ikwen_service.domain)
        msg = XEmailMessage(subject, html_content, sender, [member.email])
        if vendor != ikwen_service:
            msg.service = vendor
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg,)).start()
    return HttpResponseRedirect(request.session['return_url'])


def confirm_invoice_payment(request, *args, **kwargs):
    """
    This function has no URL associated with it.
    It serves as ikwen setting "MOMO_AFTER_CHECKOUT"
    """
    tx = kwargs.get('transaction')
    now = datetime.now()
    service = get_service_instance()
    config = service.config
    invoicing_config = get_invoicing_config_instance()
    invoice_id = request.session['object_id']
    amount = request.session['amount']
    invoice = Invoice.objects.select_related('subscription').get(pk=invoice_id)
    invoice.paid += amount
    invoice.status = Invoice.PAID
    if invoicing_config.processing_fees_on_customer:
        invoice.processing_fees = config.ikwen_share_fixed
    invoice.save()
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY,
                                     amount=amount, processor_tx_id=tx.processor_tx_id)
    subscription = invoice.subscription
    if invoicing_config.separate_billing_cycle:
        extra_months = request.session['extra_months']
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
    mean = request.session['mean']
    share_payment_and_set_stats(invoice, total_months, mean)
    member = request.user
    sudo_group = Group.objects.using(UMBRELLA).get(name=SUDO)
    add_event(service, PAYMENT_CONFIRMATION, member=member, object_id=invoice.id)
    add_event(service, PAYMENT_CONFIRMATION, group_id=sudo_group.id, object_id=invoice.id)

    if invoicing_config.return_url:
        params = {'reference_id': subscription.reference_id, 'invoice_number': invoice.number,
                  'amount_paid': amount, 'extra_months': extra_months}
        Thread(target=notify_event, args=(service, invoicing_config.return_url, params)).start()

    balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
    if member.email:
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
            balance.mail_count -= 1
            balance.save()
            Thread(target=lambda m: m.send(), args=(msg,)).start()
    return HttpResponseRedirect(request.session['return_url'])


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
    request.session['notif_url'] = service.url # Orange Money only
    request.session['cancel_url'] = service.url + reverse('billing:pricing') # Orange Money only
    request.session['return_url'] = reverse('billing:invoice_detail', args=(invoice.id, ))


def product_do_checkout(request, *args, **kwargs):
    tx = kwargs.get('transaction')
    invoice_id = request.session['object_id']
    mean = request.session['mean']
    invoice = Invoice.objects.get(pk=invoice_id)
    member = request.user
    subscription = invoice.subscription
    subscription.status = Subscription.ACTIVE
    subscription.save()
    invoice.status = Invoice.PAID
    invoice.save()
    payment = Payment.objects.create(invoice=invoice, method=Payment.MOBILE_MONEY,
                                     amount=invoice.amount, processor_tx_id=tx.processor_tx_id)
    share_payment_and_set_stats(invoice, payment_mean_slug=mean)
    service = get_service_instance()
    config = service.config

    balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
    if member.email:
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
    request.session['notif_url'] = service.url # Orange Money only
    request.session['cancel_url'] = service.url + reverse('billing:donate') # Orange Money only
    request.session['return_url'] = service.url + reverse('billing:donate')


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
    return HttpResponseRedirect(request.session['return_url'])
