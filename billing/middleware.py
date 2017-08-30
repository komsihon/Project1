# -*- coding: utf-8 -*-

from datetime import datetime

from ikwen.billing.utils import refresh_currencies_exchange_rates

from ikwen.core.utils import get_service_instance


class CurrenciesRatesMiddleware(object):

    def process_request(self, request):
        config = get_service_instance().config
        if not config.is_pro_version:
            return
        now = datetime.now()
        if config.last_currencies_rates_update:
            diff = now - config.last_currencies_rates_update
            if diff.seconds > 3600:
                # Update currencies every hour
                refresh_currencies_exchange_rates()
