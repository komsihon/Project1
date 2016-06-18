from django.conf.urls import patterns, include, url

from django.contrib import admin

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
    url(r'^', include('ikwen.foundation.core.urls', namespace='ikwen')),
    url(r'^billing/', include('ikwen.foundation.billing.urls', namespace='billing')),
    # url(r'^paypal/', include('paypal.pro.urls', namespace='paypal')),
)
