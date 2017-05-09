
from django.conf.urls import patterns, url
from django.contrib.auth.decorators import login_required, permission_required
from ikwen.billing.paypal.views import SetExpressCheckout

from ikwen.billing.jumbopay.views import jumbopay_local_api

from ikwen.billing.views import InvoiceList, InvoiceDetail, NoticeMail, change_billing_cycle, list_members, \
    list_subscriptions, IframeAdmin, PaymentMeanList, set_credentials, toggle_payment_mean, MoMoSetCheckout, DeployCloud, \
    init_momo_transaction, check_momo_transaction_status

urlpatterns = patterns(
    '',
    url(r'^deployCloud/(?P<app_slug>[-\w]+)/$', permission_required('accesscontrol.sudo')(DeployCloud.as_view()), name='deploy_cloud'),

    url(r'^invoices/$', login_required(InvoiceList.as_view()), name='invoice_list'),
    url(r'^invoiceDetail/(?P<invoice_id>[-\w]+)/$', login_required(InvoiceDetail.as_view()), name='invoice_detail'),
    url(r'^paymentMeans/$', permission_required('accesscontrol.sudo')(PaymentMeanList.as_view()), name='payment_mean_list'),
    url(r'^set_credentials$', set_credentials, name='set_credentials'),
    url(r'^toggle_payment_mean$', toggle_payment_mean, name='toggle_payment_mean'),
    url(r'^change_billing_cycle$', change_billing_cycle, name='change_billing_cycle'),
    url(r'^list_members$', list_members, name='list_members'),
    url(r'^list_subscriptions$', list_subscriptions, name='list_subscriptions'),

    url(r'^MoMo/setCheckout/$', MoMoSetCheckout.as_view(), name='momo_set_checkout'),
    url(r'^MoMo/initTransaction/$', init_momo_transaction, name='init_momo_transaction'),
    url(r'^MoMo/checkTransaction/$', check_momo_transaction_status, name='check_momo_transaction_status'),

    url(r'^JumboPayAPI/$', jumbopay_local_api, name='jumbopay_local_api'),  # For Unit Tests only
    url(r'^JumboPayAPI/(?P<op>[-\w]+)$', jumbopay_local_api, name='jumbopay_local_api'),  # For Unit Tests only

    url(r'^paypal/setCheckout/$', SetExpressCheckout.as_view(), name='paypal_set_checkout'),

    url(r'^noticeMail$', NoticeMail.as_view()),

    url(r'^(?P<model_name>[-\w]+)/$', login_required(IframeAdmin.as_view()), name='iframe_admin'),
    url(r'^(?P<app_name>[-\w]+)/(?P<model_name>[-\w]+)/$', login_required(IframeAdmin.as_view()), name='iframe_admin'),
)
