from django.core.cache import cache

from ikwen.billing.mtnmomo.views import MTN_MOMO
from ikwen.billing.orangemoney.views import ORANGE_MONEY
from ikwen.billing.models import PaymentMean
from ikwen.accesscontrol.backends import UMBRELLA
from daraja.models import Dara, BonusWallet, DARA_CASH


def payment_means(request):
    """
    Adds PaymentMean objects to context.
    """
    key = 'payment_means:' + request.user.username
    means = cache.get(key)
    if means:
        return means

    mtn_momo, om, paypal = None, None, None
    try:
        mtn_momo = PaymentMean.objects.get(slug=MTN_MOMO, is_active=True)
    except PaymentMean.DoesNotExist:
        pass
    try:
        om = PaymentMean.objects.get(slug=ORANGE_MONEY, is_active=True)
    except PaymentMean.DoesNotExist:
        pass
    try:
        paypal = PaymentMean.objects.get(slug='paypal', is_active=True)
    except PaymentMean.DoesNotExist:
        pass

    means = {
        'mtn_momo': mtn_momo,
        'om': om,
        'paypal': paypal,
        'payment_mean_list': list(PaymentMean.objects.exclude(slug=DARA_CASH).filter(is_active=True))
    }
    try:
        dara = Dara.objects.using(UMBRELLA).get(member=request.user)
        bonus_wallet, update = BonusWallet.objects.using('wallets').get_or_create(dara_id=dara.id)
        dara_cash = PaymentMean.objects.get(slug='dara-cash', is_active=True)
        dara_cash.balance = bonus_wallet.cash
        means['dara_cash'] = dara_cash
        means['payment_mean_list'].append(dara_cash)
    except:
        pass
    cache.set(key, means, 5 * 60)
    return means
