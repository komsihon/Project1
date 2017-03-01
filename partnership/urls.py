
from django.conf.urls import patterns, url, include
from django.contrib.auth.decorators import permission_required
from ikwen.flatpages.views import FlatPageView

from ikwen.core.views import DefaultHome

from ikwen.partnership.views import Dashboard, ApplicationList, ServiceList, ChangeService

urlpatterns = patterns(
    '',
    url(r'^$', DefaultHome.as_view(), name='home'),
    url(r'^dashboard/$', permission_required('accesscontrol.sudo')(Dashboard.as_view()), name='admin_home'),
    url(r'^apps/$', permission_required('accesscontrol.sudo')(ApplicationList.as_view()), name='app_list'),
    url(r'^services/$', permission_required('accesscontrol.sudo')(ServiceList.as_view()), name='service_list'),
    url(r'^changeService/(?P<service_id>[-\w]+)/$', permission_required('accesscontrol.sudo')(ChangeService.as_view()), name='change_service'),

    url(r'^kakocase/', include('ikwen_kakocase.kakocase.urls', namespace='kakocase')),
    url(r'^billing/', include('ikwen.billing.urls', namespace='billing')),
    url(r'^ikwen/cashout/', include('ikwen.cashout.urls', namespace='cashout')),
    url(r'^ikwen/', include('ikwen.core.urls', namespace='ikwen')),
    url(r'^page/(?P<url>[-\w]+)/$', FlatPageView.as_view(), name='flatpage'),
)
