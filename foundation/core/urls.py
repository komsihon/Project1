from django.conf import settings
from django.conf.urls import patterns, url

from django.contrib.auth.decorators import login_required

from foundation.core.views import Console
from ikwen.foundation.core.views import SignIn, ForgottenPassword, update_info, update_password, register, \
    ServiceList, ServiceDetail, WelcomeMail, BaseExtMail, Contact, account_setup, ServiceExpired, get_queued_sms

urlpatterns = patterns(
    '',
    url(r'^logout$', 'django.contrib.auth.views.logout', {'next_page': getattr(settings, "LOGOUT_REDIRECT_URL")}, name='logout'),
    url(r'^signOut$', 'django.contrib.auth.views.logout', {'next_page': getattr(settings, "LOGOUT_REDIRECT_URL")}),
    url(r'^signIn/$', SignIn.as_view(), name='sign_in'),
    url(r'^console/$', Console.as_view(), name='console'),
    url(r'^forgottenPassword/$', ForgottenPassword.as_view(), name='forgotten_password'),
    url(r'^services/$', login_required(ServiceList.as_view()), name='service_list'),
    url(r'^serviceDetail/(?P<service_id>[-\w]+)/$', login_required(ServiceDetail.as_view()), name='service_detail'),
    url(r'^accountSetup/$', account_setup, name='account_setup'),
    url(r'^register$', register, name='register'),
    url(r'^update_info$', update_info, name='update_info'),
    url(r'^update_password$', update_password, name='update_password'),
    url(r'^contact/$', Contact.as_view(), name='contact'),
    url(r'^get_queued_sms$', get_queued_sms, name='get_queued_sms'),

    # These URLs are for verification purposes. They are not regular pages of Ikwen website
    url(r'^welcomeMail$', WelcomeMail.as_view()),
    url(r'^baseExtMail$', BaseExtMail.as_view()),
    url(r'^serviceExpired$', ServiceExpired.as_view()),
)
