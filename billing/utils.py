# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

import requests
from requests.exceptions import SSLError, Timeout, RequestException

from django.conf import settings
from django.db import transaction
from django.db.models import get_model
from django.utils.translation import gettext as _

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.billing.models import InvoicingConfig, Invoice, AbstractSubscription, Payment
from ikwen.core.models import Service, OperatorWallet
from ikwen.core.utils import get_service_instance
from ikwen.core.utils import set_counters, increment_history_field, add_database_to_settings
from ikwen.partnership.models import ApplicationRetailConfig

logger = logging.getLogger('ikwen')


def get_invoicing_config_instance(using=UMBRELLA):
    service = get_service_instance(using=using)
    invoicing_config, update = InvoicingConfig.objects.using(using).get_or_create(service=service)
    return invoicing_config


def get_days_count(months_count):
    """
    Computes the number of days of extension based on the number of months
    """
    if months_count < 3:
        days = months_count * 30
    elif months_count < 6:
        days = months_count * 30 + 1
    elif months_count < 9:
        days = months_count * 30 + 2
    elif months_count < 12:
        days = months_count * 30 + 3
    elif months_count < 15:
        days = 365 + (months_count % 12) * 30
    elif months_count < 18:
        days = 365 + 1 + (months_count % 12) * 30
    elif months_count < 21:
        days = 365 + 2 + (months_count % 12) * 30
    elif months_count < 24:
        days = 365 + 3 + (months_count % 12) * 30
    else:
        days = 365 * 2 + (months_count % 12) * 30
    return days


def get_billing_cycle_days_count(billing_cycle):
    if billing_cycle == Service.MONTHLY:
        return 30
    if billing_cycle == Service.QUARTERLY:
        return 91
    if billing_cycle == Service.BI_ANNUALLY:
        return 182
    return 365


def get_billing_cycle_months_count(billing_cycle):
    if billing_cycle == Service.MONTHLY:
        return 1
    if billing_cycle == Service.QUARTERLY:
        return 3
    if billing_cycle == Service.BI_ANNUALLY:
        return 6
    if billing_cycle == Service.YEARLY:
        return 12


def get_months_count_billing_cycle(months_count):
    if months_count == 1:
        return Service.MONTHLY
    if months_count == 3:
        return Service.QUARTERLY
    if months_count == 6:
        return Service.BI_ANNUALLY
    if months_count == 12:
        return Service.YEARLY


def get_product_model():
    model_name = getattr(settings, 'BILLING_PRODUCT_MODEL', 'billing.Product')
    if not model_name:
        return None
    return get_model(*model_name.split('.'))


def get_subscription_model():
    model_name = getattr(settings, 'BILLING_SUBSCRIPTION_MODEL', 'billing.Subscription')
    return get_model(*model_name.split('.'))


def get_next_invoice_number(auto=True):
    """
    Generates the number to use for the next invoice. Auto-generated numbers
    start with "A" whereas manually generated invoice (those generated from the admin panel)
    start with  "M". This is to avoid collision whenever an Invoice is manually generated
    when cron task is running.

    So said if there are currently 999 invoices in the database and the Invoice is
    generated by the cron job, the generated number will be "A1000". If generated
    from the admin, it should be "M1000"

    @param auto: boolean telling whether it was generated by a cron or not
    @return: number identifying the Invoice
    """
    d = datetime.now().strftime('%m%y')
    number = Invoice.objects.all().count() + 1
    return "A%d/%s" % (number, d) if auto else "M%d/%s" % (number, d)


def get_subscription_registered_message(subscription):
    """
    Returns a tuple (mail subject, mail body, sms text) to send to
    member upon registration of a Subscription in the database
    @param subscription: Subscription object
    """
    config = get_service_instance().config
    invoicing_config = get_invoicing_config_instance()
    member = subscription.member
    new_invoice_subject = invoicing_config.new_invoice_subject
    new_invoice_message = invoicing_config.new_invoice_message
    subject = new_invoice_subject if new_invoice_subject else _("Subscription activated")
    try:
        details = subscription.product.get_details()
    except:
        subscription = get_subscription_model().objects.get(pk=subscription.id)
        details = subscription.details
    if new_invoice_message:
        message = new_invoice_message.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$amount', config.currency_symbol + ' ' + subscription.monthly_cost)\
            .replace('$details', details)\
            .replace('$short_description', subscription.product.short_description)
    else:
        message = _("Dear %(member_name)s,<br><br>"
                    "Your subscription to <strong>%(product_name)s</strong> (%(short_description)s) is confirmed. "
                    "See details below:<br><br>"
                    "<span>%(details)s</span><br>"
                    "Monthly cost: <strong>%(currency)s</strong> %(amount).2f<br>"
                    "Billing cycle: %(billing_cyle)s<br><br>"
                    "Thank you for your business with "
                    "%(company_name)s." % {'member_name': member.first_name,
                                           'product_name': subscription.product.name,
                                           'short_description': subscription.product.short_description,
                                           'amount': subscription.monthly_cost,
                                           'billing_cyle': subscription.billing_cycle,
                                           'currency': config.currency_symbol,
                                           'details': details,
                                           'company_name': config.company_name})
    sms = None
    # if invoicing_config.new_invoice_sms:
    #     sms = invoicing_config.new_invoice_sms.replace('$member_name', member.first_name)\
    #         .replace('$company_name', config.company_name)\
    #         .replace('$invoice_number', subscription.number)\
    #         .replace('$amount', subscription.amount + ' ' + config.currency_symbol)\
    #         .replace('$date_issued', subscription.date_issued)\
    #         .replace('$due_date', subscription.due_date)\
    #         .replace('$invoice_description', subscription.subscription.details)
    return subject, message, sms


def get_invoice_generated_message(invoice):
    """
    Returns a tuple (mail subject, mail body, sms text) to send to
    member upon generation of an invoice
    @param invoice: Invoice object
    @param invoicing_config: InvoicingConfig object
    """
    config = get_service_instance().config
    invoicing_config = get_invoicing_config_instance()
    member = invoice.subscription.member
    new_invoice_subject = invoicing_config.new_invoice_subject
    new_invoice_message = invoicing_config.new_invoice_message
    subject = new_invoice_subject if new_invoice_subject else _("Customer Invoice")
    try:
        details = invoice.subscription.product.get_details()
    except:
        subscription = get_subscription_model().objects.get(pk=invoice.subscription.id)
        details = subscription.details
    if new_invoice_message:
        message = new_invoice_message.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    else:
        message = _("This is a notice that an invoice has been generated on %s." % invoice.date_issued.strftime('%B %d, %Y'))
    sms = None
    if invoicing_config.new_invoice_sms:
        sms = invoicing_config.new_invoice_sms.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    return subject, message, sms


def get_invoice_reminder_message(invoice):
    """
    Returns a tuple (mail subject, mail body, sms text) to send to
    member as reminder of Invoice payment.
    @param invoice: Invoice object
    """
    config = get_service_instance().config
    invoicing_config = get_invoicing_config_instance()
    member = invoice.subscription.member
    reminder_subject = invoicing_config.reminder_subject
    reminder_message = invoicing_config.reminder_message
    subject = reminder_subject if reminder_subject else _("Invoice Payment Reminder")
    try:
        details = invoice.subscription.product.get_details()
    except:
        subscription = get_subscription_model().objects.get(pk=invoice.subscription.id)
        details = subscription.details
    if reminder_message:
        message = reminder_message.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    else:
        message = _("This is a billing reminder that your invoice No. %(invoice_number)s "
                    "which was generated on %(date_issued)s is due "
                    "on %(due_date)s." % {'invoice_number': invoice.number,
                                          'date_issued': invoice.date_issued.strftime('%B %d, %Y'),
                                          'due_date': invoice.due_date.strftime('%B %d, %Y')})
    sms = None
    if invoicing_config.reminder_sms:
        sms = invoicing_config.reminder_sms.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    return subject, message, sms


def get_invoice_overdue_message(invoice):
    """
    Returns a tuple (mail subject, mail body, sms text) to send to
    member as reminder of Invoice overdue.
    @param invoice: Invoice object
    """
    config = get_service_instance().config
    invoicing_config = get_invoicing_config_instance()
    member = invoice.subscription.member
    overdue_subject = invoicing_config.overdue_subject
    overdue_message = invoicing_config.overdue_message
    try:
        details = invoice.subscription.product.get_details()
    except:
        subscription = get_subscription_model().objects.get(pk=invoice.subscription.id)
        details = subscription.details

    subject = _("First %s" % overdue_subject) if overdue_subject else _('First notice of Invoice Overdue')
    if invoice.overdue_notices_sent == 1:
        subject = _("Second %s" % overdue_subject) if overdue_subject else _('Second notice of Invoice Overdue')
    elif invoice.overdue_notices_sent == 2:
        subject = _("Third and last %s" % overdue_subject) if overdue_subject else _('Third and last notice of Invoice Overdue')

    if overdue_message:
        message = overdue_message.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    else:
        message = _("This is a billing reminder that your "
                    "invoice No. %(invoice_number)s which was due on %(due_date)s "
                    "is now overdue." % {'invoice_number': invoice.number,
                                         'due_date': invoice.due_date.strftime('%B %d, %Y')})
    sms = None
    if invoicing_config.overdue_sms:
        sms = invoicing_config.overdue_sms.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    return subject, message, sms


def get_service_suspension_message(invoice):
    """
    Returns a tuple (mail subject, mail body, sms text) to send to
    member as notice of Service suspension.
    @param invoice: Invoice object
    """
    config = get_service_instance().config
    invoicing_config = get_invoicing_config_instance()
    member = invoice.subscription.member
    service_suspension_subject = invoicing_config.payment_confirmation_subject
    service_suspension_message = invoicing_config.payment_confirmation_message
    subject = service_suspension_subject if service_suspension_subject else _("Notice of Service Suspension")
    try:
        details = invoice.subscription.product.get_details()
    except:
        subscription = get_subscription_model().objects.get(pk=invoice.subscription.id)
        details = subscription.details
    if service_suspension_message:
        message = service_suspension_message.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    else:
        message = _("This a notice of <strong>service suspension</strong> because of unpaid Invoice "
                    "<strong>No. %(invoice_number)s</strong> generated on %(date_issued)s and due "
                    "on %(due_date)s." % {'invoice_number': invoice.number,
                                          'date_issued': invoice.date_issued.strftime('%B %d, %Y'),
                                          'due_date': invoice.due_date.strftime('%B %d, %Y')})
    sms = None
    if invoicing_config.service_suspension_sms:
        sms = invoicing_config.service_suspension_sms.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    return subject, message, sms


def get_payment_confirmation_message(payment, member):
    """
    Returns a tuple (mail subject, mail body, sms text) to send to
    member as receipt of Invoice payment.
    @param payment: Payment object
    """
    config = get_service_instance().config
    invoicing_config = get_invoicing_config_instance()
    invoice = payment.invoice
    payment_confirmation_subject = invoicing_config.payment_confirmation_subject
    payment_confirmation_message = invoicing_config.payment_confirmation_message
    subject = payment_confirmation_subject if payment_confirmation_subject else _("Invoice Payment Confirmation")
    try:
        details = invoice.subscription.product.get_details()
    except:
        subscription = get_subscription_model().objects.get(pk=invoice.subscription.id)
        details = subscription.details
    if payment_confirmation_message:
        message = payment_confirmation_message.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    else:
        message = _("This is a payment receipt of %(currency)s %(amount).2f "
                    "for Invoice <strong>No. %(invoice_number)s</strong> generated on %(date_issued)s "
                    "towards the services provided by us. Below is a summary "
                    "of the invoice." % {'invoice_number': invoice.number,
                                         'amount': invoice.amount,
                                         'currency': config.currency_symbol,
                                         'date_issued': invoice.date_issued.strftime('%B %d, %Y')})
    sms = None
    if invoicing_config.payment_confirmation_sms:
        sms = invoicing_config.payment_confirmation_sms.replace('$member_name', member.first_name)\
            .replace('$company_name', config.company_name)\
            .replace('$invoice_number', invoice.number)\
            .replace('$amount', invoice.amount + ' ' + config.currency_symbol)\
            .replace('$date_issued', invoice.date_issued)\
            .replace('$due_date', invoice.due_date)\
            .replace('$invoice_description', details)
    return subject, message, sms


def pay_with_wallet_balance(invoice):
    service = invoice.subscription
    amount0 = invoice.amount
    amount = invoice.amount
    with transaction.atomic():
        for wallet in OperatorWallet.objects.using('wallets').filter(nonrel_id=invoice.service.id).order_by('-balance'):
            if wallet.balance >= amount0:
                service.lower_balance(amount, provider=wallet.provider)
                share_payment_and_set_stats(invoice, payment_mean_slug=wallet.provider)
                break
            else:
                debit = min(amount, wallet.balance)
                service.lower_balance(debit, provider=wallet.provider)
                invoice.amount = debit
                share_payment_and_set_stats(invoice, payment_mean_slug=wallet.provider)
                amount -= debit
                if amount == 0:
                    break
    total_months = invoice.months_count
    days = get_days_count(total_months)
    service.expiry += timedelta(days=days)
    service.save()
    invoice.amount = amount0
    invoice.status = Invoice.PAID
    invoice.save()
    Payment.objects.create(invoice=invoice, method=Payment.WALLET_DEBIT, amount=invoice.amount)


def notify_event(service, url, params):
    project_name = service.project_name
    try:
        r = requests.get(url, params)
        logger.debug("%s: HTTP %s - Notification sent to %s" % (project_name, r.status_code, r.url))
    except SSLError:
        logger.error("%s: SSL Error while hitting %s" % (project_name, url), exc_info=True)
    except Timeout:
        logger.error("%s: Timeout %s" % (project_name, url), exc_info=True)
    except RequestException:
        logger.error("%s: Request exception %s" % (project_name, url), exc_info=True)
    except:
        logger.error("%s: Server error %s" % (project_name, url), exc_info=True)


def suspend_subscription(subscription):
    subscription.status = AbstractSubscription.SUSPENDED
    subscription.save()


def share_payment_and_set_stats(invoice, total_months=None, payment_mean_slug='mtn-momo'):
    if getattr(settings, 'IS_IKWEN', False):
        # This is ikwen collecting payment for Invoice of its Cloud apps
        _share_payment_and_set_stats_ikwen(invoice, total_months, payment_mean_slug)
    else:
        _share_payment_and_set_stats_other(invoice, payment_mean_slug)


def _share_payment_and_set_stats_ikwen(invoice, total_months, payment_mean_slug='mtn-momo'):
    service_umbrella = Service.objects.get(pk=invoice.service.id)
    app_umbrella = service_umbrella.app
    ikwen_earnings = invoice.amount

    partner = service_umbrella.retailer
    if partner:
        if invoice.entries:
            ikwen_earnings = 0
            for entry in invoice.entries:
                ikwen_earnings += entry.item.price * entry.quantity
        else:
            retail_config = ApplicationRetailConfig.objects.get(partner=partner, app=app_umbrella)
            if retail_config:
                ikwen_earnings = retail_config.ikwen_monthly_cost * total_months
            else:
                billing_plan = service_umbrella.billing_plan
                ikwen_earnings = billing_plan.monthly_cost * total_months
        partner_earnings = invoice.amount - ikwen_earnings
        add_database_to_settings(partner.database)
        partner_original = Service.objects.using(partner.database).get(pk=partner.id)

        partner.raise_balance(partner_earnings, payment_mean_slug)

        service_partner = Service.objects.using(partner.database).get(pk=service_umbrella.id)
        app_partner = service_partner.app

        set_counters(partner_original)
        increment_history_field(partner_original, 'turnover_history', invoice.amount)
        increment_history_field(partner_original, 'invoice_earnings_history', partner_earnings)
        increment_history_field(partner_original, 'earnings_history', partner_earnings)
        increment_history_field(partner_original, 'invoice_count_history')

        set_counters(service_partner)
        increment_history_field(service_partner, 'invoice_earnings_history', partner_earnings)
        increment_history_field(service_partner, 'earnings_history', partner_earnings)
        increment_history_field(service_partner, 'invoice_count_history')

        set_counters(app_partner)
        increment_history_field(app_partner, 'invoice_earnings_history', partner_earnings)
        increment_history_field(app_partner, 'earnings_history', partner_earnings)
        increment_history_field(app_partner, 'invoice_count_history')

        set_counters(partner)
        increment_history_field(partner, 'turnover_history', invoice.amount)
        increment_history_field(partner, 'invoice_earnings_history', ikwen_earnings)
        increment_history_field(partner, 'earnings_history', ikwen_earnings)
        increment_history_field(partner, 'invoice_count_history')

        partner_app = partner.app  # This is going to be the ikwen core/retail app
        set_counters(partner_app)
        increment_history_field(partner_app, 'turnover_history', invoice.amount)
        increment_history_field(partner_app, 'invoice_earnings_history', ikwen_earnings)
        increment_history_field(partner_app, 'earnings_history', ikwen_earnings)
        increment_history_field(partner_app, 'invoice_count_history')

    set_counters(service_umbrella)
    increment_history_field(service_umbrella, 'turnover_history', invoice.amount)
    increment_history_field(service_umbrella, 'invoice_earnings_history', ikwen_earnings)
    increment_history_field(service_umbrella, 'earnings_history', ikwen_earnings)
    increment_history_field(service_umbrella, 'invoice_count_history')

    app_umbrella = service_umbrella.app  # The app powering the site that is paying the invoice
    set_counters(app_umbrella)
    increment_history_field(app_umbrella, 'turnover_history', invoice.amount)
    increment_history_field(app_umbrella, 'invoice_earnings_history', ikwen_earnings)
    increment_history_field(app_umbrella, 'earnings_history', ikwen_earnings)
    increment_history_field(app_umbrella, 'invoice_count_history')


def _share_payment_and_set_stats_other(invoice, payment_mean_slug='mtn-momo'):
    service = get_service_instance(check_cache=False)
    service_umbrella = get_service_instance(UMBRELLA, check_cache=False)
    config = service_umbrella.config
    invoicing_config = get_invoicing_config_instance()
    if invoicing_config.processing_fees_on_customer:
        ikwen_earnings = config.ikwen_share_fixed
        service_earnings = invoice.amount
    else:
        ikwen_earnings = invoice.amount * config.ikwen_share_rate / 100
        ikwen_earnings += config.ikwen_share_fixed
        service_earnings = invoice.amount - ikwen_earnings  # Earnings of IAO of this website

    service.raise_balance(service_earnings, payment_mean_slug)

    set_counters(service)
    increment_history_field(service, 'turnover_history', invoice.amount)
    increment_history_field(service, 'earnings_history', service_earnings)
    increment_history_field(service, 'invoice_count_history')

    if ikwen_earnings == 0:
        return

    partner = service.retailer
    if partner:
        partner_umbrella = Service.objects.using(UMBRELLA).get(pk=partner.id)
        service_partner = Service.objects.using(partner.database).get(service=partner.id)
        retail_config = ApplicationRetailConfig.objects.using(UMBRELLA).get(partner=partner, app=service.app)
        partner_earnings = ikwen_earnings * (100 - retail_config.ikwen_tx_share_rate) / 100
        ikwen_earnings -= partner_earnings

        partner.raise_balance(partner_earnings, payment_mean_slug)

        set_counters(service_partner)
        increment_history_field(service_partner, 'turnover_history', invoice.amount)
        increment_history_field(service_partner, 'earnings_history', partner_earnings)
        increment_history_field(service_partner, 'transaction_earnings_history', partner_earnings)
        increment_history_field(service_partner, 'transaction_count_history')

        app_partner = service_partner.app
        set_counters(app_partner)
        increment_history_field(app_partner, 'turnover_history', invoice.amount)
        increment_history_field(app_partner, 'earnings_history', partner_earnings)
        increment_history_field(app_partner, 'transaction_earnings_history', partner_earnings)
        increment_history_field(app_partner, 'transaction_count_history')

        set_counters(partner_umbrella)
        increment_history_field(partner_umbrella, 'turnover_history', invoice.amount)
        increment_history_field(partner_umbrella, 'earnings_history', ikwen_earnings)
        increment_history_field(partner_umbrella, 'transaction_earnings_history', ikwen_earnings)
        increment_history_field(partner_umbrella, 'transaction_count_history')

        partner_app_umbrella = partner_umbrella.app
        set_counters(partner_app_umbrella)
        increment_history_field(partner_app_umbrella, 'turnover_history', invoice.amount)
        increment_history_field(partner_app_umbrella, 'earnings_history', ikwen_earnings)
        increment_history_field(partner_app_umbrella, 'transaction_earnings_history', ikwen_earnings)
        increment_history_field(partner_app_umbrella, 'transaction_count_history')

    set_counters(service_umbrella)
    increment_history_field(service_umbrella, 'turnover_history', invoice.amount)
    increment_history_field(service_umbrella, 'earnings_history', ikwen_earnings)
    increment_history_field(service_umbrella, 'transaction_earnings_history', ikwen_earnings)
    increment_history_field(service_umbrella, 'transaction_count_history')

    app_umbrella = service_umbrella.app
    set_counters(app_umbrella)
    increment_history_field(app_umbrella, 'turnover_history', invoice.amount)
    increment_history_field(app_umbrella, 'earnings_history', ikwen_earnings)
    increment_history_field(app_umbrella, 'transaction_earnings_history', ikwen_earnings)
    increment_history_field(app_umbrella, 'transaction_count_history')


def refresh_currencies_exchange_rates():
    import requests
    from currencies.models import Currency
    from ikwen.conf.settings import OPENEXCHANGE_APP_ID

    if Currency.active.all().count() < 2:
        return

    config = get_service_instance().config
    now = datetime.now()
    url = 'https://openexchangerates.org/api/latest.json'
    params = {'app_id': OPENEXCHANGE_APP_ID, 'base': 'USD'}
    if getattr(settings, 'DEBUG', False):
        r = requests.get(url, params=params)
        rates = r.json()['rates']
        base = Currency.active.base()
        ub_factor = rates[base.code]  # USD factor against base currency
        for crcy in Currency.objects.all():
            uc_factor = rates[crcy.code]  # USD factor against this currency
            crcy.factor = uc_factor / ub_factor
            crcy.save()
        config.last_currencies_rates_update = now
        config.save()
    else:
        try:
            r = requests.get(url, params=params)
            rates = r.json()['rates']
            base = Currency.active.base()
            ub_factor = rates[base.code]  # USD factor against base currency
            for crcy in Currency.objects.all():
                uc_factor = rates[crcy.code]  # USD factor against this currency
                crcy.factor = uc_factor / ub_factor
                crcy.save()
            config.last_currencies_rates_update = now
            config.save()
        except:
            logger.error("Failure while querying Exchange Rates API", exc_info=True)


def refill_tsunami_messaging_bundle(service, is_early_payment):
    from ikwen_kakocase.kakocase.models import OperatorProfile as KakocaseProfile
    from ikwen_webnode.webnode.models import OperatorProfile as WebNodeProfile
    from echo.models import Balance

    if service.app.slug == 'kakocase':
        config = KakocaseProfile.objects.get(service=service)
    elif service.app.slug == 'webnode':
        config = WebNodeProfile.objects.get(service=service)
    bundle = config.__getattribute__('bundle')
    if bundle:
        balance, update = Balance.objects.using('wallets').get_or_create(service_id=service.id)
        if is_early_payment:
            if bundle.early_payment_sms_count:
                balance.sms_count = bundle.early_payment_sms_count
            else:
                balance.sms_count = bundle.sms_count
            if bundle.early_payment_mail_count:
                balance.mail_count = bundle.early_payment_mail_count
            else:
                balance.mail_count = bundle.mail_count
        else:
            balance.sms_count = bundle.sms_count
            balance.mail_count = bundle.mail_count
        balance.save()
