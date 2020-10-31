
from django.urls import path, include
from django.contrib.auth.decorators import permission_required
from ikwen.core.views import load_event_content

from ikwen.flatpages.views import FlatPageView

from ikwen.partnership.views import Dashboard, ApplicationList, ServiceList, ChangeService, DeployCloud, AdminHome
from ikwen_webnode.webnode.views import Home

urlpatterns = [
    path('', Home.as_view(), name='home'),
    path('kakocase/', include('ikwen_kakocase.kakocase.urls', namespace='kakocase')),
    # path('shavida/', include('ikwen_shavida.shavida.urls', namespace='shavida')),
    path('blog/', include('ikwen_webnode.blog.urls', namespace='blog')),
    path('web/', include('ikwen_webnode.web.urls', namespace='web')),
    path('items/', include('ikwen_webnode.items.urls', namespace='items')),

    path('billing/', include('ikwen.billing.urls', namespace='billing')),
    path('ikwen/home/', permission_required('accesscontrol.sudo')(AdminHome.as_view()), name='home'),
    path('ikwen/dashboard/', permission_required('accesscontrol.sudo')(Dashboard.as_view()), name='dashboard'),
    path('ikwen/apps/', permission_required('accesscontrol.sudo')(ApplicationList.as_view()), name='app_list'),
    path('ikwen/services/', permission_required('accesscontrol.sudo')(ServiceList.as_view()), name='service_list'),
    path('ikwen/changeService/<service_id>/', permission_required('accesscontrol.sudo')(ChangeService.as_view()), name='change_service'),
    path('ikwen/cashout/', include('ikwen.cashout.urls', namespace='cashout')),
    path('ikwen/theming/', include('ikwen.theming.urls', namespace='theming')),
    path('ikwen/', include('ikwen.core.urls', namespace='ikwen')),
    path('page/<slug:url>/', FlatPageView.as_view(), name='flatpage'),
    path('deployCloud/', DeployCloud.as_view(), name='deploy_cloud'),
    path('load_event_content/', load_event_content, name='load_event_content'),
    path('', include('ikwen_webnode.webnode.urls', namespace='webnode')),
]
