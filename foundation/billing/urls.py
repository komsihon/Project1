
from django.conf.urls import patterns, url
from django.contrib.auth.decorators import login_required

from ikwen.foundation.billing.views import InvoiceList, InvoiceDetail, NoticeMail

urlpatterns = patterns(
    '',
    url(r'^invoices/$', login_required(InvoiceList.as_view()), name='invoice_list'),
    url(r'^invoiceDetail/(?P<invoice_id>[-\w]+)/$', login_required(InvoiceDetail.as_view()), name='invoice_detail'),
    url(r'^noticeMail$', NoticeMail.as_view()),
)
