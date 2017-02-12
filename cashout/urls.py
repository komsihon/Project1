from django.conf.urls import patterns, url

from django.contrib.auth.decorators import permission_required

from ikwen.cashout.views import Payments, manage_payment_address, request_cash_out

urlpatterns = patterns(
    '',
    url(r'^$', permission_required('accesscontrol.sudo')(Payments.as_view()), name='home'),
    url(r'^manage_payment_address/$', manage_payment_address, name='manage_payment_address'),
    url(r'^request_cash_out/$', request_cash_out, name='request_cash_out'),
)
