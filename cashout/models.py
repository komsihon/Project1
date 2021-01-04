# -*- coding: utf-8 -*-
from django.conf import settings
from ikwen.billing.models import Payment

from ikwen.accesscontrol.models import Member

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.models import Model, Country, Service
from django.db import models
from django.utils.translation import gettext_lazy as _


class CashOutMethod(Model):
    """
    Method of Cash-Out
    """
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(help_text="Must the same as those of PaymentMean slugs.")
    # The type of method helps determine the algorithm to call to actually
    # perform the operation in the cashout.views.request_cash_out method
    type = models.CharField(max_length=30, blank=True, choices=Payment.METHODS_CHOICES)
    image = models.ImageField(upload_to='cashout_methods',
                              blank=getattr(settings, 'DEBUG', False),
                              null=getattr(settings, 'DEBUG', False))
    is_active = models.BooleanField("active", default=True)

    class Meta:
        db_table = 'ikwen_cash_out_method'

    def __str__(self):
        return self.name


class CashOutAddress(Model):
    """
    Details of Cash-out
    """
    service = models.ForeignKey(Service, related_name='+', on_delete=models.CASCADE)
    # country = models.ForeignKey(Country, blank=True, null=True)
    # city = models.CharField(max_length=60, blank=True, null=True)
    method = models.ForeignKey(CashOutMethod, on_delete=models.CASCADE)
    account_number = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = 'ikwen_cash_out_address'

    def __str__(self):
        return self.method.name + ': ' + self.account_number


class CashOutRequest(Model):
    """
    Request of cash out initiated by an Operator of a any Service.
    A django admin action is used to actually transfer money to the
    user by any available mean.
    """
    PENDING = 'Pending'
    PAID = 'Paid'
    STATUS_CHOICES = (
        (PENDING, 'Pending'),
        (PAID, 'Paid'),
    )
    # service = models.ForeignKey(Service)
    service_id = models.CharField(max_length=24)
    # member = models.ForeignKey('accesscontrol.Member')
    member_id = models.CharField(max_length=24)
    amount = models.IntegerField(default=0)  # Amount requested by the IAO at the time of cash-out request
    rate = models.IntegerField(default=0)  # Rate charged for this cashout
    amount_paid = models.IntegerField(default=0)  # Amount actually paid.
    paid_on = models.DateTimeField(blank=True, null=True)
    provider = models.CharField(max_length=60, editable=False,
                                help_text="Wallet operator from which we collected the money. "
                                          "It is actually the slug of the PaymentMean.")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING)
    # country = models.CharField(max_length=60)
    # city = models.CharField(max_length=60)
    method = models.CharField(_("payment method"), max_length=30,
                              help_text=_("Method used to pay the member"))
    account_number = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    reference = models.CharField(max_length=100)
    teller_username = models.CharField(max_length=100, blank=True, null=True,
                                       help_text=_("Teller who processed this request"))

    class Meta:
        db_table = 'ikwen_cash_out_request'
        permissions = (
            ("ik_manage_cash_out_request", _("Request cash-out")),
        )

    def _get_service(self):
        return Service.objects.using(UMBRELLA).get(pk=self.service_id)
    service = property(_get_service)

    def _get_member(self):
        return Member.objects.using(UMBRELLA).get(pk=self.member_id)
    member = property(_get_member)

    def _get_teller(self):
        if not self.teller_username:
            return
        try:
            return Member.objects.using(UMBRELLA).get(username=self.teller_username)
        except Member.DoesNotExist:
            pass
    teller = property(_get_teller)

    def _get_amount_payable(self):
        return int(self.amount * (100 - self.rate) / 100)
    amount_payable = property(_get_amount_payable)
