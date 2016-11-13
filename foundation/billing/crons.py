#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

from datetime import datetime, timedelta
from django.conf import settings
from django.core import mail
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db.models import get_model
from django.utils import timezone
from django.utils.module_loading import import_by_path

from ikwen.foundation.core.models import Config, QueuedSMS
from ikwen.foundation.core.utils import get_service_instance, send_sms, add_event
from ikwen.foundation.core.utils import get_mail_content
from ikwen.foundation.billing.models import Invoice, InvoicingConfig, INVOICES_SENT_EVENT, \
    NEW_INVOICE_EVENT, INVOICE_REMINDER_EVENT, REMINDERS_SENT_EVENT, OVERDUE_NOTICE_EVENT, OVERDUE_NOTICES_SENT_EVENT, \
    SUSPENSION_NOTICES_SENT_EVENT, SERVICE_SUSPENDED_EVENT, SendingReport
from ikwen.foundation.billing.utils import get_invoice_generated_message, get_invoice_reminder_message, get_invoice_overdue_message, \
    get_service_suspension_message, get_next_invoice_number, get_subscription_model, get_billing_cycle_months_count

import logging
import logging.handlers
error_log = logging.getLogger('crons.error')
error_log.setLevel(logging.ERROR)
error_file_handler = logging.handlers.RotatingFileHandler('billing_crons.log', 'w', 100000, 4)
error_file_handler.setLevel(logging.INFO)
f = logging.Formatter('%(levelname)-10s %(asctime)-27s %(message)s')
error_file_handler.setFormatter(f)
error_log.addHandler(error_file_handler)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")

Subscription = get_subscription_model()


def send_invoices():
    """
    This cron task simply sends the Invoice invoicing_gap days before expiry
    """
    service = get_service_instance()
    config = service.config
    now = datetime.now()
    invoicing_config = InvoicingConfig.objects.all()[0]
    connection = mail.get_connection()
    try:
        connection.open()
    except:
        error_log.error(u"Connexion error", exc_info=True)
    count, total_amount = 0, 0
    for subscription in Subscription.objects.filter(status=Subscription.ACTIVE, expiry__gte=now):
        diff = subscription.expiry - now
        if diff.days == invoicing_config.gap:
            member = subscription.member
            number = get_next_invoice_number()
            if getattr(settings, 'SEPARATE_BILLING_CYCLE', True):
                amount = subscription.monthly_cost * get_billing_cycle_months_count(service.billing_cycle)
            else:
                amount = subscription.product.cost

            path_before = getattr(settings, 'BILLING_BEFORE_NEW_INVOICE', None)
            if path_before:
                before_new_invoice = import_by_path(path_before)
                before_new_invoice(subscription)

            invoice = Invoice.objects.create(subscription=subscription, amount=amount,
                                             number=number, due_date=subscription.expiry)
            count += 1
            total_amount += amount
            add_event(service, member, NEW_INVOICE_EVENT, invoice.id)
            subject, message, sms_text = get_invoice_generated_message(invoice)
            if member.email.find(member.phone) < 0:
                invoice_url = getattr(settings, 'PROJECT_URL') + reverse('billing:invoice_detail', args=(invoice.id, ))
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                                extra_context={'invoice_url': invoice_url})
                # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
                # to be delivered to Spams because of origin check.
                sender = '%s <no-reply@%s.com>' % (config.company_name, config.company_name_slug)
                msg = EmailMessage(subject, html_content, sender, [member.email])
                msg.content_subtype = "html"
                invoice.last_reminder = timezone.now()
                try:
                    if msg.send():
                        invoice.reminders_sent = 1
                    else:
                        error_log.error(u"Invoice #%s generated but mail not sent to %s" % (number, member.email), exc_info=True)
                except:
                    error_log.error(u"Connexion error on Invoice #%s to %s" % (number, member.email), exc_info=True)
                invoice.save()
            if sms_text:
                if member.phone:
                    if config.sms_sending_method == Config.HTTP_API:
                        send_sms(member.phone, sms_text)
                    else:
                        QueuedSMS.objects.create(recipient=member.phone, text=sms_text)

            path_after = getattr(settings, 'BILLING_AFTER_NEW_INVOICE', None)
            if path_after:
                after_new_invoice = import_by_path(path_after)
                after_new_invoice(invoice)

    try:
        connection.close()
    finally:
        report = SendingReport.objects.create(count=count, total_amount=total_amount)
        add_event(service, service.member, INVOICES_SENT_EVENT, report.id)


def send_invoice_reminders():
    """
    This cron task sends Invoice reminder notice to the client if unpaid
    """
    service = get_service_instance()
    config = service.config
    now = datetime.now()
    invoicing_config = InvoicingConfig.objects.all()[0]
    connection = mail.get_connection()
    try:
        connection.open()
    except:
        error_log.error(u"Connexion error", exc_info=True)
    count, total_amount = 0, 0
    for invoice in Invoice.objects.filter(status=Invoice.PENDING, due_date__gte=now, last_reminder__isnull=False):
        diff = now - invoice.last_reminder
        if diff.days == invoicing_config.reminder_delay:
            count += 1
            total_amount += invoice.amount
            member = invoice.subscription.member
            add_event(service, member, INVOICE_REMINDER_EVENT, invoice.id)
            subject, message, sms_text = get_invoice_reminder_message(invoice)
            if member.email.find(member.phone) < 0:
                invoice_url = getattr(settings, 'PROJECT_URL') + reverse('billing:invoice_detail', args=(invoice.id, ))
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                                extra_context={'invoice_url': invoice_url})
                # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
                # to be delivered to Spams because of origin check.
                sender = '%s <no-reply@%s.com>' % (config.company_name, config.company_name_slug)
                msg = EmailMessage(subject, html_content, sender, [member.email])
                msg.content_subtype = "html"
                invoice.last_reminder = timezone.now()
                try:
                    if msg.send():
                        invoice.reminders_sent += 1
                    else:
                        error_log.error(u"Reminder mail for Invoice #%s not sent to %s" % (invoice.number, member.email), exc_info=True)
                except:
                    error_log.error(u"Connexion error on Invoice #%s to %s" % (invoice.number, member.email), exc_info=True)
                invoice.save()
            if sms_text:
                if member.phone:
                    if config.sms_sending_method == Config.HTTP_API:
                        send_sms(member.phone, sms_text)
                    else:
                        QueuedSMS.objects.create(recipient=member.phone, text=sms_text)
    try:
        connection.close()
    finally:
        report = SendingReport.objects.create(count=count, total_amount=total_amount)
        add_event(service, service.member, REMINDERS_SENT_EVENT, report.id)


def send_invoice_overdue_notices():
    """
    This cron task sends notice of Invoice overdue
    """
    service = get_service_instance()
    config = service.config
    now = timezone.now()
    invoicing_config = InvoicingConfig.objects.all()[0]
    connection = mail.get_connection()
    try:
        connection.open()
    except:
        error_log.error(u"Connexion error", exc_info=True)
    count, total_amount = 0, 0
    for invoice in Invoice.objects.filter(status=Invoice.PENDING, due_date__lt=now, overdue_notices_sent__lt=3):
        if invoice.last_overdue_notice:
            diff = now - invoice.last_overdue_notice
        else:
            invoice.status = Invoice.OVERDUE
            invoice.save()
        if not invoice.last_overdue_notice or diff.days == invoicing_config.overdue_delay:
            count += 1
            total_amount += invoice.amount
            member = invoice.subscription.member
            add_event(service, member, OVERDUE_NOTICE_EVENT, invoice.id)
            subject, message, sms_text = get_invoice_overdue_message(invoice)
            if member.email.find(member.phone) < 0:
                invoice_url = getattr(settings, 'PROJECT_URL') + reverse('billing:invoice_detail', args=(invoice.id, ))
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                                extra_context={'invoice_url': invoice_url})
                # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
                # to be delivered to Spams because of origin check.
                sender = '%s <no-reply@%s.com>' % (config.company_name, config.company_name_slug)
                msg = EmailMessage(subject, html_content, sender, [member.email])
                msg.content_subtype = "html"
                invoice.last_overdue_notice = timezone.now()
                try:
                    if msg.send():
                        invoice.overdue_notices_sent += 1
                    else:
                        error_log.error(u"Overdue notice for Invoice #%s not sent to %s" % (invoice.number, member.email), exc_info=True)
                except:
                    error_log.error(u"Connexion error on Invoice #%s to %s" % (invoice.number, member.email), exc_info=True)
                invoice.save()
            if sms_text:
                if member.phone:
                    if config.sms_sending_method == Config.HTTP_API:
                        send_sms(member.phone, sms_text)
                    else:
                        QueuedSMS.objects.create(recipient=member.phone, text=sms_text)
    try:
        connection.close()
    finally:
        report = SendingReport.objects.create(count=count, total_amount=total_amount)
        add_event(service, service.member, OVERDUE_NOTICES_SENT_EVENT, report.id)


def suspend_customers_services():
    """
    This cron task shuts down service and sends notice of Service suspension
    for Invoices which tolerance is exceeded.
    """
    service = get_service_instance()
    config = service.config
    now = timezone.now()
    invoicing_config = InvoicingConfig.objects.all()[0]
    connection = mail.get_connection()
    try:
        connection.open()
    except:
        error_log.error(u"Connexion error", exc_info=True)
    count, total_amount = 0, 0
    deadline = now - timedelta(days=invoicing_config.tolerance)
    for invoice in Invoice.objects.filter(due_date__lte=deadline, status=Invoice.PENDING):
        invoice.status = Invoice.EXCEEDED
        invoice.save()
        action = getattr(settings, 'SERVICE_SUSPENSION_ACTION', None)
        if action:
            count += 1
            total_amount += invoice.amount
            action = import_by_path(action)
            action(invoice.subscription)
            member = invoice.subscription.member
            add_event(service, member, SERVICE_SUSPENDED_EVENT, invoice.id)
            subject, message, sms_text = get_service_suspension_message(invoice)
            if member.email.find(member.phone) < 0:
                invoice_url = getattr(settings, 'PROJECT_URL') + reverse('billing:invoice_detail', args=(invoice.id, ))
                html_content = get_mail_content(subject, message, template_name='billing/mails/notice.html',
                                                extra_context={'invoice_url': invoice_url})
                # Sender is simulated as being no-reply@company_name_slug.com to avoid the mail
                # to be delivered to Spams because of origin check.
                sender = '%s <no-reply@%s.com>' % (config.company_name, config.company_name_slug)
                msg = EmailMessage(subject, html_content, sender, [member.email])
                msg.content_subtype = "html"
                try:
                    if not msg.send():
                        error_log.error(u"Notice of suspension for Invoice #%s not sent to %s" % (invoice.number, member.email), exc_info=True)
                except:
                    error_log.error(u"Connexion error on Invoice #%s to %s" % (invoice.number, member.email), exc_info=True)
            if sms_text:
                if member.phone:
                    if config.sms_sending_method == Config.HTTP_API:
                        send_sms(member.phone, sms_text)
                    else:
                        QueuedSMS.objects.create(recipient=member.phone, text=sms_text)
    try:
        connection.close()
    finally:
        report = SendingReport.objects.create(count=count, total_amount=total_amount)
        add_event(service, service.member, SUSPENSION_NOTICES_SENT_EVENT, report.id)


if __name__ == "__main__":
    try:
        send_invoices()
        send_invoice_reminders()
        send_invoice_overdue_notices()
        suspend_customers_services()
    except:
        error_log.error(u"Fatal error occured", exc_info=True)
