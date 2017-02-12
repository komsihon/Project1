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
    slug = models.SlugField()
    # The type of method helps determine the algorithm to call to actually
    # perform the operation in the cashout.views.request_cash_out method
    type = models.CharField(max_length=30, blank=True, choices=Payment.METHODS_CHOICES)
    image = models.ImageField(upload_to='ikwen/cashout_methods',
                              blank=getattr(settings, 'DEBUG', False),
                              null=getattr(settings, 'DEBUG', False))
    is_active = models.BooleanField("active", default=True)

    class Meta:
        db_table = 'ikwen_cash_out_method'

    def __unicode__(self):
        return self.name


class CashOutAddress(Model):
    """
    Details of Cash-out
    """
    service = models.ForeignKey(Service, related_name='+')
    # country = models.ForeignKey(Country, blank=True, null=True)
    # city = models.CharField(max_length=60, blank=True, null=True)
    method = models.ForeignKey(CashOutMethod)
    account_number = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = 'ikwen_cash_out_address'

    def __unicode__(self):
        return self.method.name + ': ' + self.account_number


class CashOutRequest(Model):
    """
    Request of cash out initiated by an Operator of a any Service.
    A django admin action is used to actually transfer money to the
    user by any available mean.
    """
    PENDING = 'Pending'
    PAID = 'Paid'
    # service = models.ForeignKey(Service)
    service_id = models.CharField(max_length=24)
    # member = models.ForeignKey('accesscontrol.Member')
    member_id = models.CharField(max_length=24)
    amount = models.IntegerField(default=0)
    status = models.CharField(max_length=15, default=PENDING)
    # country = models.CharField(max_length=60)
    # city = models.CharField(max_length=60)
    method = models.CharField(_("payment method"), max_length=30,
                              help_text=_("Method used to pay the member"))
    account_number = models.CharField(max_length=100)
    name = models.CharField(max_length=100)

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
