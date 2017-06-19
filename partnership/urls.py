
from django.conf.urls import patterns, url, include
from django.contrib.auth.decorators import permission_required
from ikwen.core.views import load_event_content

from ikwen.accesscontrol.views import SignIn

from ikwen.flatpages.views import FlatPageView

from ikwen.partnership.views import Dashboard, ApplicationList, ServiceList, ChangeService, DeployCloud

urlpatterns = patterns(
    '',
    url(r'^$', SignIn.as_view(), name='home'),
    url(r'^dashboard/$', permission_required('accesscontrol.sudo')(Dashboard.as_view()), name='dashboard'),
    url(r'^apps/$', permission_required('accesscontrol.sudo')(ApplicationList.as_view()), name='app_list'),
    url(r'^services/$', permission_required('accesscontrol.sudo')(ServiceList.as_view()), name='service_list'),
    url(r'^changeService/(?P<service_id>[-\w]+)/$', permission_required('accesscontrol.sudo')(ChangeService.as_view()), name='change_service'),

    url(r'^kakocase/', include('ikwen_kakocase.kakocase.urls', namespace='kakocase')),
    url(r'^shavida/', include('ikwen_shavida.shavida.urls', namespace='shavida')),
    url(r'^billing/', include('ikwen.billing.urls', namespace='billing')),
    url(r'^ikwen/cashout/', include('ikwen.cashout.urls', namespace='cashout')),
    url(r'^ikwen/', include('ikwen.core.urls', namespace='ikwen')),
    url(r'^page/(?P<url>[-\w]+)/$', FlatPageView.as_view(), name='flatpage'),
    url(r'^deployCloud/(?P<app_slug>[-\w]+)/$', DeployCloud.as_view(), name='deploy_cloud'),
    url(r'^load_event_content/$', load_event_content, name='load_event_content'),
)
