from django.db import models
from ikwen.theming.models import Theme

from ikwen.core.models import Model, Service, Application, AbstractConfig


class PartnerProfile(AbstractConfig):
    theme = models.ForeignKey(Theme, blank=True, null=True, related_name='+')


class ApplicationRetailConfig(Model):
    partner = models.ForeignKey(Service, related_name='+', on_delete=models.CASCADE)
    app = models.ForeignKey(Application, on_delete=models.CASCADE)
    ikwen_monthly_cost = models.IntegerField(help_text="Amount ikwen collects monthly for any Service deployed "
                                                       "with this application. Extra goes to the retailer. If this "
                                                       "application has <em>CloudBillingPlan</em>s, they will override "
                                                       "this value with the one defined in their monthly_cost field.")
    ikwen_tx_share_rate = models.FloatField(default=75,
                                            help_text="Share rate ikwen collects on transactions on "
                                                      "websites deployed by this partner with this application.")
