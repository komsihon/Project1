from ikwen.conf.settings import MOMO_SLUG

from ikwen.billing.models import PaymentMean


def payment_means(request):
    """
    Adds PaymentMean objects to context.
    """
    mtn_momo, om, paypal = None, None, None
    try:
        mtn_momo = PaymentMean.objects.get(slug=MOMO_SLUG)
    except PaymentMean.DoesNotExist:
        pass

    return {
        'mtn_momo': mtn_momo,
        'om': om,
        'paypal': paypal
    }
