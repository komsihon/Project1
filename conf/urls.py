from django.conf.urls import patterns, include, url

from django.contrib import admin
from ikwen.flatpages.views import FlatPageView

from ikwen.core.views import DefaultHome

admin.autodiscover()

urlpatterns = patterns(
    '',
    url(r'^$', DefaultHome.as_view(), name='home'),
    url(r'^laakam/', include(admin.site.urls)),
    url(r'^i18n/', include('django.conf.urls.i18n')),
    url(r'^billing/', include('ikwen.billing.urls', namespace='billing')),
    url(r'^cashout/', include('ikwen.cashout.urls', namespace='cashout')),
    url(r'^retail/', include('ikwen.partnership.urls', namespace='partnership')),
    url(r'^theming/', include('ikwen.theming.urls', namespace='theming')),
    url(r'^rewarding/', include('ikwen.rewarding.urls', namespace='rewarding')),
    url(r'^revival/', include('ikwen.revival.urls', namespace='revival')),
    url(r'^kakocase/', include('ikwen_kakocase.kakocase.urls', namespace='kakocase')),
    url(r'^shavida/', include('ikwen_shavida.shavida.urls', namespace='shavida')),
    url(r'^webnode/', include('ikwen_webnode.webnode.urls', namespace='webnode')),

    url(r'^echo/', include('echo.urls', namespace='echo')),
    url(r'^page/(?P<url>[-\w]+)/$', FlatPageView.as_view(), name='flatpage'),
    url(r'^', include('ikwen.core.urls', namespace='ikwen')),
)
