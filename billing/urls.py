
from django.conf.urls import patterns, url
from django.contrib.auth.decorators import login_required, permission_required

from ikwen.billing.paypal.views import SetExpressCheckout
from ikwen.billing.api import pull_invoice

from ikwen.billing.views import PaymentMeanList, set_credentials, toggle_payment_mean, MoMoSetCheckout, DeployCloud, \
    TransactionLog
from ikwen.billing.invoicing.views import InvoiceList, InvoiceDetail, change_billing_cycle, list_members, \
    list_subscriptions, ProductList, ChangeProduct, SubscriptionList, ChangeSubscription, AdminInvoiceList, \
    Configuration, upload_subscription_file, PaymentList
from ikwen.billing.public.views import Pricing, Donate
from ikwen.billing.mtnmomo.open_api import process_notification as momo_process_notification
from ikwen.billing.orangemoney.wso2_api import process_notification as om_process_notification
from ikwen.billing.yup.views import yup_process_notification
from ikwen.billing.uba.views import uba_process_approved, uba_process_declined_or_cancelled
from ikwen.billing.collect import confirm_service_invoice_payment, product_do_checkout

urlpatterns = patterns(
    '',
    url(r'^deployCloud/(?P<app_slug>[-\w]+)/$', permission_required('accesscontrol.sudo')(DeployCloud.as_view()), name='deploy_cloud'),

    url(r'^products/$', permission_required('billing.ik_manage_product')(ProductList.as_view()), name='product_list'),
    url(r'^changeProduct/$', permission_required('billing.ik_manage_product')(ChangeProduct.as_view()), name='change_product'),
    url(r'^changeProduct/(?P<object_id>[-\w]+)/$', permission_required('billing.ik_manage_product')(ChangeProduct.as_view()), name='change_product'),
    url(r'^subscriptions$', permission_required('billing.ik_manage_subscription')(SubscriptionList.as_view()), name='subscription_list'),
    url(r'^changeSubscription/$', permission_required('billing.ik_manage_subscription')(ChangeSubscription.as_view()), name='change_subscription'),
    url(r'^changeSubscription/(?P<object_id>[-\w]+)/$', permission_required('billing.ik_manage_subscription')(ChangeSubscription.as_view()), name='change_subscription'),
    url(r'^invoices/$', login_required(InvoiceList.as_view()), name='invoice_list'),
    url(r'^manageInvoices/$', permission_required('billing.ik_manage_invoice')(AdminInvoiceList.as_view()), name='admin_invoice_list'),
    url(r'^payments/$', permission_required('billing.ik_manage_invoice')(PaymentList.as_view()), name='payment_list'),
    url(r'^invoiceDetail/(?P<invoice_id>[-\w]+)/$', InvoiceDetail.as_view(), name='invoice_detail'),
    url(r'^paymentMeans/$', permission_required('accesscontrol.sudo')(PaymentMeanList.as_view()), name='payment_mean_list'),
    url(r'^set_credentials$', set_credentials, name='set_credentials'),
    url(r'^toggle_payment_mean$', toggle_payment_mean, name='toggle_payment_mean'),
    url(r'^change_billing_cycle$', change_billing_cycle, name='change_billing_cycle'),
    url(r'^list_members$', list_members, name='list_members'),
    url(r'^list_subscriptions$', list_subscriptions, name='list_subscriptions'),
    url(r'^configuration/$', permission_required('accesscontrol.sudo')(Configuration.as_view()), name='configuration'),

    url(r'^upload_subscription_file', upload_subscription_file, name='upload_subscription_file'),
    url(r'^api/pull_invoice', pull_invoice, name='pull_invoice'),

    url(r'^pricing/$', Pricing.as_view(), name='pricing'),
    url(r'^donate/$', Donate.as_view(), name='donate'),
    url(r'^product_do_checkout/(?P<tx_id>[-\w]+)/(?P<signature>[-\w]+)$', product_do_checkout, name='product_do_checkout'),
    url(r'^confirm_service_invoice_payment/(?P<tx_id>[-\w]+)/(?P<signature>[-\w]+)/(?P<extra_months>[\d]+)$',
        confirm_service_invoice_payment, name='confirm_service_invoice_payment'),

    url(r'^MoMo/setCheckout/$', MoMoSetCheckout.as_view(), name='momo_set_checkout'),

    url(r'^mtnmomo/notify$', momo_process_notification, name='momo_process_notification'),
    url(r'^mtnmomo/notify/(?P<tx_id>[-\w]+)$', momo_process_notification, name='momo_process_notification'),
    url(r'^om/notify/(?P<tx_id>[-\w]+)$', om_process_notification, name='om_process_notification'),
    url(r'^yup/notify$', yup_process_notification, name='yup_notify'),
    url(r'^uba/notify_success$', uba_process_approved, name='uba_process_approved'),
    url(r'^uba/notify_declined$', uba_process_declined_or_cancelled, name='uba_process_declined'),
    url(r'^uba/notify_cancelled$', uba_process_declined_or_cancelled, name='uba_process_cancelled'),

    url(r'^transactions/$', permission_required('billing.ik_view_transaction_log')(TransactionLog.as_view()), name='transaction_log'),

    url(r'^paypal/setCheckout/$', SetExpressCheckout.as_view(), name='paypal_set_checkout'),
)
