from django.urls import path

from django.contrib.auth.decorators import permission_required, user_passes_test

from ikwen.accesscontrol.utils import is_bao
from ikwen.cashout.views import Payments, manage_payment_address, request_cash_out

urlpatterns = [
    path('', permission_required('accesscontrol.sudo')(Payments.as_view()), name='home'),
    path('manage_payment_address/', user_passes_test(is_bao)(manage_payment_address), name='manage_payment_address'),
    path('request_cash_out/', user_passes_test(is_bao)(request_cash_out), name='request_cash_out'),
]
