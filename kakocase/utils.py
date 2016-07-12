# -*- coding: utf-8 -*-
from django.utils.translation import gettext_lazy as _

from ikwen.foundation.billing.models import InvoicingConfig, Invoice


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
    number = Invoice.objects.all().count() + 1
    return "A%d" % number if auto else "M%d" % number


def get_cash_out_requested_message(member):
    """
    Returns a tuple (mail subject, mail body, sms text) to send to
    member upon generation of an invoice
    @param invoice: Invoice object
    """
    subject = _("Cash-out requested by %s" % member.full_name)
    message = _("Dear %(member_name)s,<br><br>"
                "This is a notice that an invoice has been generated on %(date_issued)s.<br><br>"
                "<strong style='font-size: 1.2em'>Invoice #%(invoice_number)s</strong><br>"
                "Amount: %(amount).2f %(currency)s<br>"
                "Due Date:  %(due_date)s<br><br>"
                "<strong>Invoice items:</strong><br>"
                "<span style='color: #111'>%(invoice_description)s</span><br><br>"
                "Thank you for your business with "
                "%(company_name)s." % {'member_name': member.first_name,
                                       'company_name': config.company_name,
                                       'invoice_number': invoice.number,
                                       'amount': invoice.amount,
                                       'currency': invoicing_config.currency,
                                       'date_issued': invoice.date_issued.strftime('%B %d, %Y'),
                                       'due_date': invoice.due_date.strftime('%B %d, %Y'),
                                       'invoice_description': invoice.subscription.details})
    return subject, message
