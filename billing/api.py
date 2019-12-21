# -*- coding: utf-8 -*-
import json
import logging
import time
from threading import Thread

from currencies.models import Currency
from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import transaction
from django.http import HttpResponse
from django.utils.translation import activate, gettext as _

from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.models import Service
from ikwen.billing.models import Invoice, InvoiceEntry, InvoiceItem, InvoicingConfig
from ikwen.billing.utils import get_subscription_model, get_product_model, \
    get_invoice_generated_message
from ikwen.core.utils import get_mail_content, XEmailMessage, add_database
from echo.models import Balance
from echo.utils import notify_for_low_messaging_credit, LOW_MAIL_LIMIT, notify_for_empty_messaging_credit

logger = logging.getLogger('ikwen')

Product = get_product_model()
Subscription = get_subscription_model()


def pull_invoice(request, *args, **kwargs):
    api_signature = request.POST.get('api_signature')
    try:
        service = Service.objects.get(api_signature=api_signature)
    except:
        notice = "Invalid API Signature."
        response = {'error': notice}
        return HttpResponse(json.dumps(response))

    db = service.database
    add_database(db)
    invoicing_config, update = InvoicingConfig.objects.using(db).get_or_create(service=service)
    if not invoicing_config.pull_invoice:
        notice = "Cannot import when not explicitly configured to do so. You must set activate " \
                 "pull_invoice in your platform configuration for import to work."
        response = {'error': notice}
        return HttpResponse(json.dumps(response))

    lang = request.POST.get('lang', "en")
    activate(lang)
    missing = []
    errors = []
    do_pull = True
    try:
        number = request.POST['invoice_number'].strip()
        try:
            Invoice.objects.using(db).get(number=number)
            errors.append("Invoice with number '%s' already exists. Invoice numbers must be unique." % number)
            do_pull = False
        except Invoice.DoesNotExist:
            pass
    except KeyError:
        missing.append('invoice_number')
        do_pull = False
    try:
        reference_id = request.POST['reference_id']
    except KeyError:
        reference_id = None
        missing.append('reference_id')
        do_pull = False
    try:
        amount = request.POST['amount']
        amount = float(amount)
    except KeyError:
        missing.append('amount')
        do_pull = False
    except ValueError:
        errors.append("Invalid amount '%s'. Expected valid float or int.")
        do_pull = False
    try:
        due_date = request.POST['due_date']
        time.strptime(due_date, '%Y-%m-%d')
    except KeyError:
        missing.append('due_date')
        do_pull = False
    except ValueError:
        errors.append("Invalid due_date '%s'. Expected valid date in the format 'YYYY-mm-dd'.")
        do_pull = False
    try:
        quantity = request.POST['quantity']
    except KeyError:
        missing.append('quantity')
        do_pull = False
    except ValueError:
        errors.append("Invalid quantity '%s'. Expected valid int.")
        do_pull = False
    quantity_unit = request.POST.get('quantity_unit', _("Month(s)"))
    currency_code = request.POST.get('currency_code', 'XAF')
    if reference_id:
        try:
            subscription = Subscription.objects.using(db).select_related('member, product').get(reference_id=reference_id)
        except Subscription.DoesNotExist:
            do_pull = False
            notice = "reference_id '%s' not found." % reference_id
            errors.append(notice)
    if not do_pull:
        response = {
            'error': '\n'.join(errors),
            'missing': 'Following parameters are missing: ' + ', '.join(missing)
        }
        return HttpResponse(json.dumps(response))

    product = subscription.product
    if product:
        short_description = product.name
    else:
        short_description = request.POST.get('short_description', '---')
    invoice_entries = []
    item = InvoiceItem(label=_('Subscription'), amount=amount)
    entry = InvoiceEntry(item=item, short_description=short_description, quantity=quantity,
                         quantity_unit=quantity_unit, total=amount)
    invoice_entries.append(entry)
    invoice = Invoice.objects.using(db).create(number=number, member=subscription.member, subscription=subscription,
                                               amount=amount, months_count=quantity, due_date=due_date,
                                               entries=invoice_entries)
    config = service.config
    member = subscription.member
    if member.email:
        with transaction.atomic(using=WALLETS_DB_ALIAS):
            balance, update = Balance.objects.using(WALLETS_DB_ALIAS).get_or_create(service_id=service.id)
            if 0 < balance.mail_count < LOW_MAIL_LIMIT:
                notify_for_low_messaging_credit(service, balance)
            if balance.mail_count <= 0:
                notify_for_empty_messaging_credit(service, balance)
                return
            subject, message, sms_text = get_invoice_generated_message(invoice)
            try:
                currency = Currency.objects.using(db).get(code=currency_code).symbol
            except:
                try:
                    currency = Currency.active.default().symbol
                except:
                    currency = currency_code

            invoice_url = service.url + reverse('billing:invoice_detail', args=(invoice.id, ))
            html_content = get_mail_content(subject, template_name='billing/mails/notice.html', service=service,
                                            extra_context={'invoice': invoice, 'member_name': member.first_name,
                                                           'invoice_url': invoice_url, 'cta': _("Pay now"),
                                                           'currency': currency})
            sender = '%s <no-reply@%s>' % (config.company_name, service.domain)
            msg = XEmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            balance.mail_count -= 1
            balance.save()
            if getattr(settings, 'UNIT_TESTING', False):
                msg.send()
            else:
                Thread(target=lambda m: m.send(), args=(msg, )).start()
    response = {'success': True, 'invoice_id': invoice.id}
    return HttpResponse(json.dumps(response))
