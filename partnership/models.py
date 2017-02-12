from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from ikwen.core.models import Model, Service, Application, AbstractConfig


class PartnerProfile(AbstractConfig):
    api_signature = models.CharField(_("API Signature"), max_length=60, unique=True, db_index=True,
                                     help_text="Use it in your http API calls. More on "
                                               "<a href='http://support.ikwen.com/APISignature'>"
                                               "support.ikwen.com/APISignature</a>")
    return_url = models.URLField(blank=True,
                                 help_text="Transaction details are routed to this URL upon checkout confirmation. See "
                                           "<a href='http://support.ikwen.com/ikwen-retail/configuration-return-url'>"
                                           "support.ikwen.com/ikwen-retail/configuration-return-url</a> for more.")


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
