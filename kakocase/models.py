from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djangotoolbox.fields import ListField, EmbeddedModelField

from ikwen.foundation.accesscontrol.backends import UMBRELLA
from ikwen.foundation.accesscontrol.models import Member
from ikwen.foundation.core.models import Model, AbstractConfig, AbstractWatchModel, Service
from ikwen.foundation.core.utils import to_dict, add_database_to_settings, set_counters, increment_history_field

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
CUSTOMER_ORDERED_EVENT = 'CustomerOrderedEvent'
CUSTOMER_RECEIVED_PACKAGE_EVENT = 'CustomerReceivedPackageEvent'
# End Code names


class City(Model):
    name = models.CharField(max_length=60)

    def __unicode__(self):
        return self.name


class ProductCategory(AbstractWatchModel):
    """
    Category of :class:`kako.models.Product`. User must select the category from
    a list so, upon installation of the project some categories must be set.
    """
    name = models.CharField(max_length=100, unique=True,
                            help_text=_("Name of the category."))
    slug = models.SlugField(unique=True,
                            help_text=_("Slug of the category."))
    description = models.TextField(blank=True,
                                   help_text=_("Description of the category. (May contain HTML)"))
    items_count = models.IntegerField(default=0,
                                      help_text="Number of products in this category.")
    # A list of 366 integer values, each of which representing the number of items of this category
    # that were traded (sold or delivered) on a day out of the 366 previous (current day being the last)
    items_traded_history = ListField(blank=True, null=True)
    turnover_history = ListField(blank=True, null=True)
    earnings_history = ListField(blank=True, null=True)
    orders_count_history = ListField(blank=True, null=True)

    # SUMMARY INFORMATION
    total_items_traded = models.IntegerField(default=0)
    total_turnover = models.IntegerField(default=0)
    total_earnings = models.IntegerField(default=0)
    total_orders_count = models.IntegerField(default=0)

    def __unicode__(self):
        return self.name

    def report_counters_to_umbrella(self):
        umbrella_obj = ProductCategory.objects.using(UMBRELLA).get(pk=self.id)
        set_counters(umbrella_obj)
        increment_history_field(umbrella_obj, 'items_traded_history')
        increment_history_field(umbrella_obj, 'turnover_history')
        increment_history_field(umbrella_obj, 'orders_count_history')
        umbrella_obj.save()

    def save(self, **kwargs):
        if getattr(settings, 'IS_IKWEN', False):
            for operator in OperatorProfile.objects.all():
                db = operator.service.database
                add_database_to_settings(db)
                try:
                    obj_mirror = ProductCategory.objects.using(db).get(pk=self.id)
                    obj_mirror.name = self.name
                    obj_mirror.slug = self.slug
                    super(ProductCategory, obj_mirror).save()
                except ProductCategory.DoesNotExist:
                    pass
        super(ProductCategory, self).save(**kwargs)


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
    product_categories = ListField(EmbeddedModelField('ProductCategory'))

    def __unicode__(self):
        return self.name


class DeliveryOption(Model):
    """
    Delivery options applicable to all Kakocase retail websites.

    :attr:`company`: Company offering that option
    :attr:`name`: Name of the option
    :attr:`slug`: Slug of the option
    :attr:`description`: Description
    :attr:`cost`: How much the customer pays
    :attr:`max_delay`: Max duration (in hours) it should take to deliver the package.
    """
    company = models.ForeignKey(Service)
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
    rel_id = models.IntegerField(default=0, unique=True,
                                 help_text="Id of this object in the relational database, since these objects are kept"
                                           "in the relational database with traditional autoincrement Ids.")
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
    balance = models.FloatField(default=0)

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

    def __unicode__(self):
        return self.company_name

    def get_operation_city(self):
        return self.cities_covered[-1]

    def get_rel(self):
        if getattr(settings, 'TESTING', False):
            return self
        REL_DS = getattr(settings, 'REL_DS')
        return OperatorProfile.objects.using(REL_DS).get(pk=self.rel_id)

    def get_from(self, db):
        add_database_to_settings(db)
        return OperatorProfile.objects.using(db).get(pk=self.id)

    def report_counters_to_umbrella(self):
        umbrella_obj = OperatorProfile.objects.using(UMBRELLA).get(pk=self.id)
        umbrella_obj.items_traded_history = self.items_traded_history
        umbrella_obj.turnover_history = self.turnover_history
        umbrella_obj.earnings_history = self.earnings_history
        umbrella_obj.orders_count_history = self.orders_count_history
        umbrella_obj.broken_products_history = self.broken_products_history
        umbrella_obj.late_deliveries_history = self.late_deliveries_history
        umbrella_obj.total_items_traded = self.total_items_traded
        umbrella_obj.total_turnover = self.total_turnover
        umbrella_obj.total_earnings = self.total_earnings
        umbrella_obj.total_orders_count = self.total_orders_count
        umbrella_obj.total_broken_products = self.total_broken_products
        umbrella_obj.total_late_deliveries = self.total_late_deliveries
        umbrella_obj.save()

    def save(self, **kwargs):
        if getattr(settings, 'IS_IKWEN', False):
            db = self.service.database
            add_database_to_settings(db)
            obj_mirror = OperatorProfile.objects.using(db).get(pk=self.id)
            obj_mirror.ikwen_share = self.ikwen_share
            obj_mirror.payment_delay = self.payment_delay
            obj_mirror.cash_out_min = self.cash_out_min
            obj_mirror.is_certified = self.is_certified
            super(OperatorProfile, obj_mirror).save(using=db)
        super(OperatorProfile, self).save(**kwargs)

    def to_dict(self):
        var = to_dict(self)
        del(var['ikwen_share'])
        del(var['payment_delay'])
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

    class Meta:
        permissions = (
            ("manage_cash_out_requests", _("Request cash-out")),
        )


class PaymentInfo(Model):
    """
    Information on who should receive and how money earned as
    :class:`OperatorProfile` should be sent.
    """
    member = models.OneToOneField(Member)
    method = models.CharField(max_length=30)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30)
    email = models.EmailField()
