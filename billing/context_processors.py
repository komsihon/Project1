from ikwen.billing.orangemoney.views import ORANGE_MONEY

from ikwen.billing.mtnmomo.views import MTN_MOMO
from ikwen.billing.models import PaymentMean


def payment_means(request):
    """
    Adds PaymentMean objects to context.
    """
    mtn_momo, om, paypal = None, None, None
    try:
        mtn_momo = PaymentMean.objects.get(slug=MTN_MOMO)
    except PaymentMean.DoesNotExist:
        pass
    try:
        om = PaymentMean.objects.get(slug=ORANGE_MONEY)
    except PaymentMean.DoesNotExist:
        pass
    try:
        paypal = PaymentMean.objects.get(slug='paypal')
    except PaymentMean.DoesNotExist:
        pass

    return {
        'mtn_momo': mtn_momo,
        'om': om,
        'paypal': paypal,
        'payment_mean_list': PaymentMean.objects.filter(is_active=True)
    }
