# -*- coding: utf-8 -*-
import logging

from django.conf import settings
from django.db.models.loading import get_model
from django.views.generic import TemplateView

from ikwen.billing.models import Product
from ikwen.core.views import HybridListView

logger = logging.getLogger('ikwen')


class Pricing(HybridListView):
    """
    Pricing view that shows up billing Product user
    may subscribe to.
    """
    queryset = Product.objects.filter(is_active=True)
    ordering = ('order_of_appearance', 'cost', )
    template_name = 'billing/public/pricing.html'
    context_object_name = 'product_list'


class Donate(TemplateView):
    template_name = 'billing/public/donate.html'
