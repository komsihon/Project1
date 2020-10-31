#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")

from django.db import transaction
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.auth.models import Group
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string as import_by_path
from django.utils.translation import gettext as _

from ikwen.accesscontrol.models import SUDO
from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.models import Service
from ikwen.core.utils import get_service_instance, send_sms, add_event, add_database, XEmailMessage
from ikwen.core.utils import get_mail_content
from ikwen.billing.models import Invoice, InvoicingConfig, INVOICES_SENT_EVENT, \
    SUSPENSION_NOTICES_SENT_EVENT, SERVICE_SUSPENDED_EVENT, SendingReport, InvoiceEntry, InvoiceItem
from ikwen.billing.utils import get_invoice_generated_message, get_service_suspension_message, \
    get_next_invoice_number, get_subscription_model, get_billing_cycle_months_count

from echo.models import Balance
from echo.utils import LOW_MAIL_LIMIT, notify_for_low_messaging_credit, notify_for_empty_messaging_credit, LOW_SMS_LIMIT

logger = logging.getLogger('ikwen.crons')

Subscription = get_subscription_model()


def send_expiry_reminders():
    """
    This cron task simply sends the Invoice *invoicing_gap* days before Subscription *expiry*
    """
    ikwen_service = get_service_instance()
    now = datetime.now()
    invoicing_config = InvoicingConfig.objects.all()[0]
    connection = mail.get_connection()
    try:
        connection.open()
    except:
        logger.error(u"Connexion error", exc_info=True)

    reminder_date_time = now + timedelta(days=invoicing_config.gap)

    for invoicing_config in InvoicingConfig.objects.exclude(service=ikwen_service):
        service = invoicing_config.service
        if service.status != Service.ACTIVE or invoicing_config.pull_invoice:
            continue
        db = service.database
        add_database(db)
        config = service.basic_config
        subscription_qs = Subscription.objects.using(db)\
            .selected_related('member, product').filter(status=Subscription.ACTIVE,
                                                        monthly_cost__gt=0, expiry=reminder_date_time.date())
        count, total_amount = 0, 0
        for subscription in subscription_qs:
            member = subscription.member
            number = get_next_invoice_number()
            months_count = get_billing_cycle_months_count(subscription.billing_cycle)
            amount = subscription.monthly_cost * months_count

            path_before = getattr(settings, 'BILLING_BEFORE_NEW_INVOICE', None)
            if path_before:
                before_new_invoice = import_by_path(path_before)
                val = before_new_invoice(subscription)
                if val is not None:  # Returning a not None value cancels the generation of a new Invoice for this Service
                    continue

            short_description = subscription.product.short_description
            item = InvoiceItem(label=_('Subscription'), amount=amount)
            entry = InvoiceEntry(item=item, short_description=short_description, quantity=months_count, total=amount)
            invoice = Invoice.objects.create(member=member, subscription=subscription, amount=amount, number=number,
                                             due_date=subscription.expiry, months_count=months_count, entries=[entry])
            count += 1
            total_amount += amount

            subject, message, sms_text = get_invoice_generated_message(invoice)
            balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
            if member.email:
                if 0 < balance.mail_count < LOW_MAIL_LIMIT:
                    notify_for_low_messaging_credit(service, balance)
                if balance.mail_count <= 0 and not getattr(settings, 'UNIT_TESTING', False):
                    notify_for_empty_messaging_credit(service, balance)
                else:
                    invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id,))
                    html_content = get_mail_content(subject, message, service=service,
                                                    template_name='billing/mails/notice.html',
                                                    extra_context={'invoice_url': invoice_url, 'cta': _("Pay now"),
                                                                   'currency': config.currency_symbol})
                    # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
                    # to be delivered to Spams because of origin check.
                    sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
                    msg = XEmailMessage(subject, html_content, sender, [member.email])
                    msg.content_subtype = "html"
                    msg.service = service
                    invoice.last_reminder = timezone.now()
                    try:
                        with transaction.atomic(using=WALLETS_DB_ALIAS):
                            if msg.send():
                                balance.mail_count -= 1
                                balance.save()
                                logger.debug("1st Invoice reminder for %s sent to %s" % (subscription, member.email))
                            else:
                                logger.error(u"Invoice #%s generated but mail not sent to %s" % (number, member.email),
                                             exc_info=True)
                    except:
                        logger.error(u"Connexion error on Invoice #%s to %s" % (number, member.email), exc_info=True)

            if sms_text and member.phone:
                if 0 < balance.sms_count < LOW_SMS_LIMIT:
                    notify_for_low_messaging_credit(service, balance)
                if balance.sms_count <= 0 and not getattr(settings, 'UNIT_TESTING', False):
                    notify_for_empty_messaging_credit(service, balance)
                    continue
                try:
                    with transaction.atomic(using=WALLETS_DB_ALIAS):
                        balance.sms_count -= 1
                        balance.save()
                        phone = member.phone if len(member.phone) > 9 else '237' + member.phone
                        send_sms(phone, sms_text, fail_silently=False)
                except:
                    logger.error(u"SMS for invoice #%s not sent to %s" % (number, member.email), exc_info=True)

            path_after = getattr(settings, 'BILLING_AFTER_NEW_INVOICE', None)
            if path_after:
                after_new_invoice = import_by_path(path_after)
                after_new_invoice(invoice)

        if count > 0:
            report = SendingReport.objects.using(db).create(count=count, total_amount=total_amount)
            sudo_group = Group.objects.using(db).get(name=SUDO)
            add_event(ikwen_service, INVOICES_SENT_EVENT, group_id=sudo_group.id, object_id=report.id)
    try:
        connection.close()
    except:
        pass


def suspend_subscriptions():
    """
    This cron task shuts down service and sends notice of Service suspension
    for Invoices which tolerance is exceeded.
    """
    ikwen_service = get_service_instance()
    now = datetime.now()
    connection = mail.get_connection()
    try:
        connection.open()
    except:
        logger.error(u"Connexion error", exc_info=True)

    for invoicing_config in InvoicingConfig.objects.all():
        service = invoicing_config.service
        if service.status != Service.ACTIVE:
            continue
        config = service.basic_config
        db = service.database
        add_database(db)
        deadline = now - timedelta(days=invoicing_config.tolerance)
        invoice_qs = Invoice.objects.using(db).select_related('subscription')\
            .filter(due_date__lte=deadline, status=Invoice.OVERDUE)
        count, total_amount = 0, 0
        for invoice in invoice_qs:
            due_date = invoice.due_date
            due_datetime = datetime(due_date.year, due_date.month, due_date.day)
            diff = now - due_datetime
            subscription = invoice.subscription
            tolerance = subscription.tolerance
            if diff.days < tolerance:
                continue
            invoice.status = Invoice.EXCEEDED
            invoice.save()
            count += 1
            total_amount += invoice.amount
            subscription.status = Subscription.SUSPENDED
            subscription.save()
            member = subscription.member
            add_event(service, SERVICE_SUSPENDED_EVENT, member=member, object_id=invoice.id)
            subject, message, sms_text = get_service_suspension_message(invoice)
            balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
            if member.email:
                if 0 < balance.mail_count < LOW_MAIL_LIMIT:
                    notify_for_low_messaging_credit(service, balance)
                if balance.mail_count <= 0 and not getattr(settings, 'UNIT_TESTING', False):
                    notify_for_empty_messaging_credit(service, balance)
                else:
                    invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id,))
                    html_content = get_mail_content(subject, message, service=service, template_name='billing/mails/notice.html',
                                                    extra_context={'member_name': member.first_name, 'invoice': invoice,
                                                                   'invoice_url': invoice_url, 'cta': _("Pay now"),
                                                                   'currency': config.currency_symbol})
                    # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
                    # to be delivered to Spams because of origin check.
                    sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
                    msg = XEmailMessage(subject, html_content, sender, [member.email])
                    msg.service = service
                    msg.content_subtype = "html"
                    try:
                        with transaction.atomic(using=WALLETS_DB_ALIAS):
                            if msg.send():
                                balance.mail_count -= 1
                                balance.save()
                            else:
                                logger.error(u"Notice of suspension for Invoice #%s not sent to %s" % (invoice.number, member.email), exc_info=True)
                    except:
                        print("Sending mail to %s failed" % member.email)
                        logger.error(u"Connexion error on Invoice #%s to %s" % (invoice.number, member.email), exc_info=True)

            if sms_text and member.phone:
                if 0 < balance.sms_count < LOW_SMS_LIMIT:
                    notify_for_low_messaging_credit(service, balance)
                if balance.sms_count <= 0 and not getattr(settings, 'UNIT_TESTING', False):
                    notify_for_empty_messaging_credit(service, balance)
                    continue
                try:
                    with transaction.atomic(using=WALLETS_DB_ALIAS):
                        balance.sms_count -= 1
                        balance.save()
                        phone = member.phone if len(member.phone) > 9 else '237' + member.phone
                        send_sms(phone, sms_text, fail_silently=False)
                except:
                    logger.error(
                        u"SMS overdue notice for invoice #%s not sent to %s" % (invoice.number, member.phone),
                        exc_info=True)

        if count > 0:
            report = SendingReport.objects.using(db).create(count=count, total_amount=total_amount)
            sudo_group = Group.objects.using(db).get(name=SUDO)
            add_event(ikwen_service, SUSPENSION_NOTICES_SENT_EVENT, group_id=sudo_group.id, object_id=report.id)

    try:
        connection.close()
    except:
        pass


if __name__ == "__main__":
    try:
        send_invoices()
        send_invoice_reminders()
        send_invoice_overdue_notices()
        suspend_customers_services()
    except:
        logger.error(u"Fatal error occured", exc_info=True)
