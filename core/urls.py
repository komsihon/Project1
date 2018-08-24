from django.conf import settings
from django.conf.urls import patterns, url

from django.contrib.auth.decorators import login_required, permission_required
from ikwen.core.appmodule.views import ModuleList, ConfigureModule, ChangeModule

from ikwen.flatpages.views import ChangeFlatPage

from ikwen.flatpages.views import FlatPageList

from ikwen.core.views import get_location_by_ip

from ikwen.accesscontrol.views import SignIn, SignInMinimal, AccountSetup, update_info, \
    update_password, ForgottenPassword, SetNewPassword, Profile, Community, CompanyProfile, \
    join, set_collaborator_permissions, move_member_to_group, toggle_member, \
    list_collaborators, MemberList, load_member_detail, AccessRequestList, deny_access, Register, \
    StaffWithoutPermission, staff_router, PhoneConfirmation, SetNewPasswordSMSRecovery
from ikwen.core.views import Console, ServiceDetail, WelcomeMail, BaseExtMail, \
    ServiceExpired, reset_notices_counter, get_queued_sms, LegalMentions, TermsAndConditions, Configuration, \
    upload_customization_image, list_projects, upload_image, load_event_content

REGISTER = 'register'
SIGN_IN = 'sign_in'
DO_SIGN_IN = 'do_sign_in'
LOGOUT = 'logout'
ACCOUNT_SETUP = 'account_setup'
UPDATE_INFO = 'update_info'
UPDATE_PASSWORD = 'update_password'
SERVICE_DETAIL = 'service_detail'
SERVICE_EXPIRED = 'service_expired'
LOAD_EVENT = 'load_event_content'
PHONE_CONFIRMATION = 'phone_confirmation'

urlpatterns = patterns(
    '',
    url(r'^logout$', 'django.contrib.auth.views.logout', {'next_page': getattr(settings, "LOGIN_URL")}, name=LOGOUT),
    url(r'^signOut$', 'django.contrib.auth.views.logout', {'next_page': getattr(settings, "LOGIN_URL")}),
    url(r'^signIn/$', SignInMinimal.as_view(), name=SIGN_IN),
    url(r'^doSignIn/$', SignIn.as_view(), name=DO_SIGN_IN),
    url(r'^register/$', Register.as_view(), name=REGISTER),
    url(r'^phoneConfirmation/$', login_required(PhoneConfirmation.as_view()), name=PHONE_CONFIRMATION),

    url(r'^accountSetup/$', login_required(AccountSetup.as_view()), name='account_setup'),
    url(r'^update_info$', update_info, name=UPDATE_INFO),
    url(r'^update_password$', update_password, name=UPDATE_PASSWORD),

    url(r'^forgottenPassword/$', ForgottenPassword.as_view(), name='forgotten_password'),
    url(r'^setNewPassword/(?P<uidb64>[-\w]+)/(?P<token>[-\w]+)/$', SetNewPassword.as_view(), name='set_new_password'),
    url(r'^setNewPasswordSMSRecovery/$', SetNewPasswordSMSRecovery.as_view(), name='set_new_password_sms_recovery'),

    url(r'^profile/(?P<member_id>[-\w]+)/$', login_required(Profile.as_view()), name='profile'),
    url(r'^join$', join, name='join'),
    url(r'^set_collaborator_permissions$', set_collaborator_permissions, name='set_collaborator_permissions'),
    url(r'^move_member_to_group$', move_member_to_group, name='move_member_to_group'),
    url(r'^accessRequests/$', login_required(AccessRequestList.as_view()), name='access_request_list'),
    url(r'^deny_access$', deny_access, name='deny_access'),
    url(r'^toggle_member$', toggle_member, name='toggle_member'),
    url(r'^community/$', permission_required('accesscontrol.sudo')(Community.as_view()), name='community'),
    url(r'^flatPages/$', permission_required('accesscontrol.sudo')(FlatPageList.as_view()), name='flatpage_list'),
    url(r'^flatPage/$', permission_required('accesscontrol.sudo')(ChangeFlatPage.as_view()), name='change_flatpage'),
    url(r'^flatPage/(?P<page_id>[-\w]+)/$', permission_required('accesscontrol.sudo')(ChangeFlatPage.as_view()), name='change_flatpage'),
    url(r'^list_collaborators$', list_collaborators, name='list_collaborators'),
    url(r'^staffRouter/$', staff_router, name='staff_router'),
    url(r'^staffWithoutPermission/$', StaffWithoutPermission.as_view(), name='staff_without_permission'),

    url(r'^customers/$', MemberList.as_view(), name='member_list'),
    url(r'^load_member_detail$', load_member_detail, name='load_member_detail'),

    url(r'^console/$', login_required(Console.as_view()), name='console'),
    url(r'^load_event_content/$', load_event_content, name='load_event_content'),
    url(r'^upload_image$', upload_image, name='upload_image'),
    url(r'^upload_customization_image$', upload_customization_image, name='upload_customization_image'),
    url(r'^reset_notices_counter$', reset_notices_counter, name='reset_notices_counter'),
    url(r'^modules/$', permission_required('accesscontrol.sudo')(ModuleList.as_view()), name='module_list'),
    url(r'^module/(?P<object_id>[-\w]+)/$', permission_required('accesscontrol.sudo')(ChangeModule.as_view()), name='change_module'),
    url(r'^module/(?P<object_id>[-\w]+)/configuration/$', permission_required('accesscontrol.sudo')(ConfigureModule.as_view()), name='configure_module'),
    url(r'^configuration/$', permission_required('accesscontrol.sudo')(Configuration.as_view()), name='configuration'),
    url(r'^configuration/(?P<service_id>[-\w]+)/$', permission_required('accesscontrol.sudo')(Configuration.as_view()), name='configuration'),
    url(r'^serviceDetail/(?P<service_id>[-\w]+)/$', permission_required('accesscontrol.sudo')(ServiceDetail.as_view()), name=SERVICE_DETAIL),
    url(r'^list_projects$', list_projects, name='list_projects'),
    url(r'^get_location_by_ip$', get_location_by_ip, name='get_location_by_ip'),

    url(r'^error909/$', ServiceExpired.as_view(), name='service_expired'),
    url(r'^get_queued_sms$', get_queued_sms, name='get_queued_sms'),
    url(r'^legal-mentions$', LegalMentions.as_view(), name='legal_mentions'),
    url(r'^terms-and-conditions$', TermsAndConditions.as_view(), name='terms_and_conditions'),

    url(r'^(?P<project_name_slug>[-\w]+)/$', CompanyProfile.as_view(), name='company_profile'),

    # These URLs are for verification purposes. They are not regular pages of Ikwen website
    url(r'^welcomeMail$', WelcomeMail.as_view()),
    url(r'^baseExtMail$', BaseExtMail.as_view()),
)
