from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django.conf import settings
from djangotoolbox.fields import ListField, EmbeddedModelField

from ikwen.foundation.accesscontrol.models import Member
from ikwen.foundation.core.utils import to_dict

from ikwen.foundation.core.models import Model, AbstractConfig, AbstractWatchModel

# Number of seconds since the Order was issued, that the Retailer
# has left to commit to deliver the customer himself. After that
# time, delivery will be automatically assigned to a logistics company
TIME_LEFT_TO_COMMIT_TO_SELF_DELIVERY = 6 * 3600
CASH_OUT_MIN = getattr(settings, 'KAKOCASE_CASH_OUT_MIN', 5000)

# ikwen.core.ConsoleEventType Code names
CASH_OUT_REQUEST_EVENT = 'CashOutRequestEvent'
PROVIDER_ADDED_PRODUCTS_EVENT = 'ProviderAddedProductsEvent'
PROVIDER_REMOVED_PRODUCT_EVENT = 'ProviderRemovedProductEvent'
PROVIDER_PUSHED_PRODUCT_EVENT = 'ProviderPushedProductEvent'
# End Code names


class City(Model):
    name = models.CharField(max_length=60)

    def __unicode__(self):
        return self.name


class BusinessCategory(Model):
    """
    Type of products that a provider sells.
    """
    name = models.CharField(max_length=100, unique=True,
                            help_text=_("Name of the category."))
    slug = models.SlugField(unique=True,
                            help_text=_("Slug of the category."))
    description = models.TextField(blank=True,
                                   help_text=_("Description of the category. (May contain HTML)"))

    def __unicode__(self):
        return self.name


class DeliveryOption(Model):
    """
    Delivery options applicable to all Kakocase retail websites.

    :attr:`name`: Name of the option
    :attr:`slug`: Slug of the option
    :attr:`description`: Description
    :attr:`cost`: How much the customer pays
    :attr:`max_delay`: Max duration (in hours) it should take to deliver the package.
    """
    name = models.CharField(max_length=100,
                            help_text=_("Name of the option."))
    slug = models.SlugField(help_text=_("Slug of the option."))
    description = models.TextField(blank=True,
                                   help_text=_("Description of the option. (May contain HTML)"))
    cost = models.FloatField(help_text="Cost of the option.")
    max_delay = models.IntegerField(help_text="Max duration (in hours) it should take to deliver the package.")

    def __unicode__(self):
        return self.name


class DelayReason(models.Model):
    """
    Possible delivery delay reason that must be preset
    by Kakocase platform administrators so that end user
    may choose among them.
    """
    value = models.CharField(max_length=255)


class OperatorProfile(AbstractConfig):
    PROVIDER = 'Provider'
    RETAILER = 'Retailer'
    DELIVERY_MAN = 'DeliveryMan'

    MANUAL_UPDATE = 'Auto'
    AUTO_UPDATE = 'Manual'

    STRAIGHT = 'Straight'
    UPON_CONFIRMATION = 'Confirmation'
    PAYMENT_DELAY_CHOICES = (
        (STRAIGHT, _('Straight')),
        (UPON_CONFIRMATION, _('Upon buyer confirmation')),
    )
    api_signature = models.CharField(max_length=30, unique=True, db_index=True)
    business_type = models.CharField(max_length=30)  # PROVIDER, RETAILER or DELIVERY_MAN

    ikwen_share = models.IntegerField(default=2,
                                      help_text=_("Percentage ikwen collects on the turnover made by this person."))
    payment_delay = models.CharField(max_length=30, choices=PAYMENT_DELAY_CHOICES, default=UPON_CONFIRMATION,
                                     help_text=_("When cash is deposited on trader's account. Right when the "
                                                 "buyer pays or when he acknowledges reception of the order."))
    cash_out_min = models.IntegerField(default=CASH_OUT_MIN,
                                       help_text="Minimum balance that allows cash out.")
    is_certified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    balance = models.IntegerField(default=0)

    # LOCATION INFO
    cities_covered = ListField(EmbeddedModelField(City), blank=True, null=True)  # Only DeliveryMan can have more than 1

    # REPORT INFORMATION
    # The following fields ending with _history are kept as a comma separated string of 366 values, each of which
    # representing the value of the variable on a day of the 366 previous (current day being the last)
    # Yes we could have simply used a ListField, but this object is supposed to be stored in a relational database
    # that has no support for such field type. Keeping these values this way allows us to easily and rapidly
    # determine report on the yesterday, past 7 days, and past 30 days, without having to run complex and resource
    # greedy SQL queries.
    items_traded_history = models.TextField(blank=True)
    turnover_history = models.TextField(blank=True)
    earnings_history = models.TextField(blank=True)
    orders_count_history = models.TextField(blank=True)
    broken_products_history = models.TextField(blank=True)  # Products reported as broken upon reception by buyer
    late_deliveries_history = models.TextField(blank=True)  # Orders reported as delivered too late

    # SUMMARY INFORMATION
    total_items_traded = models.IntegerField(default=0)
    total_turnover = models.IntegerField(default=0)
    total_earnings = models.IntegerField(default=0)
    total_orders_count = models.IntegerField(default=0)
    total_broken_products = models.IntegerField(default=0)
    total_late_deliveries = models.IntegerField(default=0)

    counters_reset_on = models.DateTimeField(default=timezone.now)

    # Information below apply to PROVIDER only
    business_category = models.ForeignKey(BusinessCategory, blank=True, null=True)
    stock_updated_on = models.DateTimeField(blank=True, null=True,
                                            help_text=_("Last time provider updated the stock"))
    last_stock_update_method = models.CharField(max_length=10, blank=True, null=True)  # MANUAL_UPDATE or AUTO_UPDATE
    avg_collection_delay = models.IntegerField(default=120, blank=True,
                                               help_text="When provider runs his own retail website, this is the "
                                                         "average delay in minutes before the user can come and collect his order.")

    class Meta:
        permissions = (
            ("role_request_cash_out", _("Request cash-out")),
            ("role_manage_products'", _("Manage products")),
            ("role_manage_marketing_tools'", _("Manage marketing tools")),
        )

    def __unicode__(self):
        return self.company_name

    def get_operation_city(self):
        return self.cities_covered[-1]

    def to_dict(self):
        var = to_dict(self)
        del(var['ikwen_share'])
        del(var['payment_delay'])
        del(var['created_on'])
        del(var['updated_on'])
        del(var['stock_updated_on'])
        del(var['counters_reset_on'])
        print var
        return var


class CashOutRequest(Model):
    """
    Request of cash out initiated by an Operator of a Kakocase website.
    A django admin action is used to actually transfer money to the
    user by any available mean.
    """
    PENDING = 'Pending'
    PAID = 'Paid'
    member = models.ForeignKey(Member)
    profile_type = models.CharField(max_length=15)
    amount = models.IntegerField(default=0)
    status = models.CharField(max_length=15, default=PENDING)
