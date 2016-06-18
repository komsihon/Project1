from django.db import models
from django.utils.translation import gettext_lazy as _

from ikwen.foundation.core.models import Model, Service


class City(Model):
    name = models.CharField(max_length=60)


class KakoOperator(Model):
    PROVIDER = 'Provider'
    RETAILER = 'Retailer'
    DELIVERY_MAN = 'DeliveryMan'

    STRAIGHT = 'Straight'
    UPON_CONFIRMATION = 'Confirmation'
    PAYMENT_DELAY_CHOICES = (
        (STRAIGHT, _('Straight')),
        (UPON_CONFIRMATION, _('Upon buyer confirmation')),
    )
    service = models.OneToOneField(Service)
    business_type = models.CharField(max_length=30)
    ikwen_share = models.IntegerField(default=2,
                                      help_text=_("Percentage ikwen collects on the revenue made by this person."))
    payment_delay = models.CharField(max_length=30, choices=PAYMENT_DELAY_CHOICES,
                                     help_text=_("When cash is deposited on trader's account. Right when the "
                                                 "buyer pays or when he acknowledge reception of the order."))
    certified = models.BooleanField(default=False)
