from django.conf.urls import patterns, include, url

from django.contrib import admin
from ikwen.foundation.flatpages.views import FlatPageView

from ikwen.foundation.core.views import DefaultHome, DefaultDashboard

admin.autodiscover()

urlpatterns = patterns(
    '',
    # url(r'^hotspot/', include('hotspot.urls', namespace='hotspot')),
    # url(r'^hotpost/', include('hotspot.urls', namespace='hotspot')),
    # url(r'^hostpost/', include('hotspot.urls', namespace='hotspot')),
    # url(r'^hostpot/', include('hotspot.urls', namespace='hotspot')),
    # url(r'^hospot/', include('hotspot.urls', namespace='hotspot')),
    #
    # url(r'^shavida/', include('shavida.urls', namespace='shavida')),

    url(r'^laakam/', include(admin.site.urls)),
    url(r'^i18n/', include('django.conf.urls.i18n')),
    url(r'^$', DefaultHome.as_view(), name='home'),
    url(r'^dashboard/$', DefaultDashboard.as_view(), name='admin_home'),
    url(r'^billing/', include('ikwen.foundation.billing.urls', namespace='billing')),
    url(r'^', include('ikwen.foundation.core.urls', namespace='ikwen')),
    url(r'^page/(?P<url>[-\w]+)/$', FlatPageView.as_view(), name='flatpage'),
    # url(r'^paypal/', include('paypal.pro.urls', namespace='paypal')),
)
