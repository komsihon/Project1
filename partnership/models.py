from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from ikwen.core.utils import add_database_to_settings

from ikwen.core.models import Model, Service, Application, AbstractConfig


class PartnerProfile(AbstractConfig):
    api_signature = models.CharField(_("API Signature"), max_length=60, unique=True, db_index=True,
                                     help_text="Use it in your http API calls. More on "
                                               "<a href='http://support.ikwen.com/APISignature'>"
                                               "support.ikwen.com/APISignature</a>")
    return_url = models.URLField(blank=True,
                                 help_text="Payment details are routed to this URL upon checkout confirmation. See "
                                           "<a href='http://support.ikwen.com/billing/configuration-return-url'>"
                                           "support.ikwen.com/billing/configuration-return-url</a> for more details.")

    def save(self, *args, **kwargs):
        using = kwargs.get('using')
        if using:
            del(kwargs['using'])
        else:
            using = 'default'
        if getattr(settings, 'IS_IKWEN', False):
            db = self.service.database
            add_database_to_settings(db)
            try:
                obj_mirror = PartnerProfile.objects.using(db).get(pk=self.id)
                obj_mirror.currency_code = self.currency_code
                obj_mirror.currency_symbol = self.currency_symbol
                obj_mirror.cash_out_min = self.cash_out_min
                obj_mirror.is_certified = self.is_certified
                obj_mirror.is_pro_version = self.is_pro_version
                super(PartnerProfile, obj_mirror).save(using=db)
            except PartnerProfile.DoesNotExist:
                pass
        super(PartnerProfile, self).save(using=using)


class ApplicationRetailConfig(Model):
    partner = models.ForeignKey(Service, related_name='+')
    app = models.ForeignKey(Application)
    ikwen_monthly_cost = models.IntegerField(help_text="Amount ikwen collects monthly for any Service deployed "
                                                       "with this application. Extra goes to the retailer. If this "
                                                       "application has <em>CloudBillingPlan</em>s, they will override "
                                                       "this value with the one defined in their monthly_cost field.")
    ikwen_tx_share_rate = models.FloatField(default=50,
                                            help_text="Share rate ikwen collects on transactions on "
                                                      "websites deployed by this partner with this application.")
