from django.db import models

from ikwen.core.models import Model, Service, Application, AbstractConfig


class PartnerProfile(AbstractConfig):
    pass


class ApplicationRetailConfig(Model):
    partner = models.ForeignKey(Service, related_name='+')
    app = models.ForeignKey(Application)
    ikwen_monthly_cost = models.IntegerField(help_text="Amount ikwen collects monthly for any Service deployed "
                                                       "with this application. Extra goes to the retailer. If this "
                                                       "application has <em>CloudBillingPlan</em>s, they will override "
                                                       "this value with the one defined in their monthly_cost field.")
    ikwen_tx_share_rate = models.FloatField(default=75,
                                            help_text="Share rate ikwen collects on transactions on "
                                                      "websites deployed by this partner with this application.")
