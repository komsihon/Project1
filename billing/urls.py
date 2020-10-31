
from django.urls import path
from django.contrib.auth.decorators import login_required, permission_required

from ikwen.billing.paypal.views import SetExpressCheckout
from ikwen.billing.api import pull_invoice

from ikwen.billing.views import PaymentMeanList, set_credentials, toggle_payment_mean, MoMoSetCheckout, DeployCloud, \
    TransactionLog
from ikwen.billing.invoicing.views import InvoiceList, InvoiceDetail, change_billing_cycle, list_members, \
    list_subscriptions, ProductList, ChangeProduct, SubscriptionList, ChangeSubscription, AdminInvoiceList, \
    Configuration, upload_subscription_file, PaymentList
from ikwen.billing.public.views import Pricing, Donate
from ikwen.billing.mtnmomo.open_api import init_momo_transaction, check_momo_transaction_status, process_notification
from ikwen.billing.yup.views import yup_process_notification
from ikwen.billing.uba.views import uba_process_approved, uba_process_declined_or_cancelled
from ikwen.billing.collect import confirm_service_invoice_payment

urlpatterns = [
    path('deployCloud/<slug:app_slug>/', permission_required('accesscontrol.sudo')(DeployCloud.as_view()), name='deploy_cloud'),

    path('products/', permission_required('billing.ik_manage_product')(ProductList.as_view()), name='product_list'),
    path('changeProduct/', permission_required('billing.ik_manage_product')(ChangeProduct.as_view()), name='change_product'),
    path('changeProduct/<object_id>/', permission_required('billing.ik_manage_product')(ChangeProduct.as_view()), name='change_product'),
    path('subscriptions', permission_required('billing.ik_manage_subscription')(SubscriptionList.as_view()), name='subscription_list'),
    path('changeSubscription/', permission_required('billing.ik_manage_subscription')(ChangeSubscription.as_view()), name='change_subscription'),
    path('changeSubscription/<object_id>/', permission_required('billing.ik_manage_subscription')(ChangeSubscription.as_view()), name='change_subscription'),
    path('invoices/', login_required(InvoiceList.as_view()), name='invoice_list'),
    path('manageInvoices/', permission_required('billing.ik_manage_invoice')(AdminInvoiceList.as_view()), name='admin_invoice_list'),
    path('payments/', permission_required('billing.ik_manage_invoice')(PaymentList.as_view()), name='payment_list'),
    path('invoiceDetail/<invoice_id>/', InvoiceDetail.as_view(), name='invoice_detail'),
    path('paymentMeans/', permission_required('accesscontrol.sudo')(PaymentMeanList.as_view()), name='payment_mean_list'),
    path('set_credentials', set_credentials, name='set_credentials'),
    path('toggle_payment_mean', toggle_payment_mean, name='toggle_payment_mean'),
    path('change_billing_cycle', change_billing_cycle, name='change_billing_cycle'),
    path('list_members', list_members, name='list_members'),
    path('list_subscriptions', list_subscriptions, name='list_subscriptions'),
    path('configuration/', permission_required('accesscontrol.sudo')(Configuration.as_view()), name='configuration'),

    path('upload_subscription_file', upload_subscription_file, name='upload_subscription_file'),
    path('api/pull_invoice', pull_invoice, name='pull_invoice'),

    path('pricing/', Pricing.as_view(), name='pricing'),
    path('donate/', Donate.as_view(), name='donate'),
    path('confirm_service_invoice_payment/<tx_id>/<signature>/<int:extra_months>',
        confirm_service_invoice_payment, name='confirm_service_invoice_payment'),

    path('MoMo/setCheckout/', MoMoSetCheckout.as_view(), name='momo_set_checkout'),
    path('MoMo/initTransaction/', init_momo_transaction, name='init_momo_transaction'),
    path('MoMo/checkTransaction/', check_momo_transaction_status, name='check_momo_transaction_status'),

    path('mtnmomo/notify', process_notification, name='process_notification'),
    path('mtnmomo/notify/<tx_id>', process_notification, name='process_notification'),
    path('yup/notify', yup_process_notification, name='yup_notify'),
    path('uba/notify_success', uba_process_approved, name='uba_process_approved'),
    path('uba/notify_declined', uba_process_declined_or_cancelled, name='uba_process_declined'),
    path('uba/notify_cancelled', uba_process_declined_or_cancelled, name='uba_process_cancelled'),

    path('transactions/', permission_required('billing.ik_view_transaction_log')(TransactionLog.as_view()), name='transaction_log'),

    path('paypal/setCheckout/', SetExpressCheckout.as_view(), name='paypal_set_checkout')
]
