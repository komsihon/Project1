# -*- coding: utf-8 -*-

from datetime import datetime

from django.conf import settings

from ikwen.billing.utils import refresh_currencies_exchange_rates, detect_and_set_currency_by_ip

from ikwen.core.utils import get_service_instance


class CurrenciesRatesMiddleware(object):

    def process_request(self, request):
        config = get_service_instance().config
        if not config.can_manage_currencies:
            return
        detect_and_set_currency_by_ip(request)
        now = datetime.now()
        if config.last_currencies_rates_update:
            diff = now - config.last_currencies_rates_update
            if diff.seconds > getattr(settings, 'CURRENCIES_REFRESH_TIMEOUT', 86400):
                # Update currencies every day
                refresh_currencies_exchange_rates()
