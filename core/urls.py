from django.conf import settings
from django.urls import path

from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.views.decorators.csrf import csrf_exempt

from ikwen.core.appmodule.views import ModuleList, ConfigureModule, ChangeModule

from ikwen.flatpages.views import ChangeFlatPage

from ikwen.flatpages.views import FlatPageList

from ikwen.core.views import get_location_by_ip, PWAConfig, DashboardBase

from ikwen.accesscontrol.views import SignIn, SignInMinimal, AccountSetup, update_info, \
    update_password, ForgottenPassword, SetNewPassword, Profile, Community, CompanyProfile, \
    join, set_collaborator_permissions, move_member_to_group, toggle_member, \
    list_collaborators, MemberList, deny_access, Register, StaffWithoutPermission, \
    staff_router, SetNewPasswordSMSRecovery, upload_contacts_file, transfer_ownership
from ikwen.accesscontrol.utils import EmailConfirmationPrompt, ConfirmEmail, PhoneConfirmation, is_staff, \
    update_push_subscription
from ikwen.core.views import Console, ServiceDetail, WelcomeMail, BaseExtMail, \
    ServiceExpired, reset_notices_counter, get_queued_sms, LegalMentions, TermsAndConditions, Configuration, \
    upload_customization_image, list_projects, upload_image, load_event_content, SentEmailLog, SentEmailDetail

from ikwen.core.analytics import analytics


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
EMAIL_CONFIRMATION = 'email_confirmation'
CONFIRM_EMAIL = 'confirm_email'
STAFF_ROUTER = 'staff_router'

logout_redirect_url = getattr(settings, "LOGOUT_REDIRECT_URL", None)
if not logout_redirect_url:
    logout_redirect_url = getattr(settings, 'LOGIN_URL')

urlpatterns = [
    path('logout', 'django.contrib.auth.views.logout', {'next_page': logout_redirect_url}, name=LOGOUT),
    path('signOut', 'django.contrib.auth.views.logout', {'next_page': logout_redirect_url}),
    path('signIn', SignInMinimal.as_view(), name=SIGN_IN),
    path('doSignIn', SignIn.as_view(), name=DO_SIGN_IN),
    path('register', Register.as_view(), name=REGISTER),
    path('phoneConfirmation/', login_required(PhoneConfirmation.as_view()), name=PHONE_CONFIRMATION),
    path('emailConfirmation/', login_required(EmailConfirmationPrompt.as_view()), name=EMAIL_CONFIRMATION),
    path('confirmEmail/<slug:uidb64>/<slug:token>/', ConfirmEmail.as_view(), name=CONFIRM_EMAIL),

    path('api/user/check', SignInMinimal.as_view(), name='api_check_user'),
    path('api/user/register', csrf_exempt(Register.as_view()), name='api_register'),
    path('api/user/login', csrf_exempt(SignIn.as_view()), name='api_sign_in'),
    path('api/user/request_email_reset', csrf_exempt(ForgottenPassword.as_view()), name='api_request_email_password_reset'),
    path('api/user/request_sms_reset_code', SetNewPasswordSMSRecovery.as_view(), name='api_request_sms_reset_code'),
    path('api/user/sms_reset', csrf_exempt(SetNewPasswordSMSRecovery.as_view()), name='api_sms_reset_password'),

    path('accountSetup/', login_required(AccountSetup.as_view()), name='account_setup'),
    path('update_info', update_info, name=UPDATE_INFO),
    path('update_password', update_password, name=UPDATE_PASSWORD),

    path('forgottenPassword/', ForgottenPassword.as_view(), name='forgotten_password'),
    path('setNewPassword/<slug:uidb64>/<slug:token>/', SetNewPassword.as_view(), name='set_new_password'),
    path('setNewPasswordSMSRecovery/', SetNewPasswordSMSRecovery.as_view(), name='set_new_password_sms_recovery'),

    path('profile/<member_id>/', login_required(Profile.as_view()), name='profile'),
    path('join', join, name='join'),
    path('set_collaborator_permissions', set_collaborator_permissions, name='set_collaborator_permissions'),
    path('move_member_to_group', move_member_to_group, name='move_member_to_group'),
    path('deny_access', deny_access, name='deny_access'),
    path('toggle_member', toggle_member, name='toggle_member'),
    path('transfer_ownership/<transfer_id>', transfer_ownership, name='transfer_ownership'),
    path('community/', permission_required('accesscontrol.ik_manage_community')(Community.as_view()), name='community'),
    path('upload_contacts_file/', permission_required('accesscontrol.ik_manage_community')(upload_contacts_file), name='upload_contacts_file'),
    path('flatPages/', permission_required('accesscontrol.sudo')(FlatPageList.as_view()), name='flatpage_list'),
    path('flatPage/', permission_required('accesscontrol.sudo')(ChangeFlatPage.as_view()), name='change_flatpage'),
    path('flatPage/<page_id>/', permission_required('accesscontrol.sudo')(ChangeFlatPage.as_view()), name='change_flatpage'),
    path('list_collaborators', list_collaborators, name='list_collaborators'),
    path('staffRouter/', staff_router, name=STAFF_ROUTER),
    path('staffWithoutPermission/', StaffWithoutPermission.as_view(), name='staff_without_permission'),

    path('customers/', MemberList.as_view(), name='member_list'),
    path('dashboard/', DashboardBase.as_view(), name='dashboard'),

    path('console/', login_required(Console.as_view()), name='console'),
    path('load_event_content/', load_event_content, name='load_event_content'),
    path('upload_image', upload_image, name='upload_image'),
    path('upload_customization_image', upload_customization_image, name='upload_customization_image'),
    path('reset_notices_counter', reset_notices_counter, name='reset_notices_counter'),
    path('modules/', permission_required('accesscontrol.sudo')(ModuleList.as_view()), name='module_list'),
    path('module/<object_id>/', permission_required('accesscontrol.sudo')(ChangeModule.as_view()), name='change_module'),
    path('module/<object_id>/configuration/', permission_required('accesscontrol.sudo')(ConfigureModule.as_view()), name='configure_module'),
    path('configuration/', permission_required('accesscontrol.sudo')(Configuration.as_view()), name='configuration'),
    path('configuration/<service_id>/', permission_required('accesscontrol.sudo')(Configuration.as_view()), name='configuration'),
    path('serviceDetail/', permission_required('accesscontrol.sudo')(ServiceDetail.as_view()), name=SERVICE_DETAIL),
    path('serviceDetail/<service_id>/', permission_required('accesscontrol.sudo')(ServiceDetail.as_view()), name=SERVICE_DETAIL),
    path('list_projects', list_projects, name='list_projects'),
    path('get_location_by_ip', get_location_by_ip, name='get_location_by_ip'),

    path('error909/', ServiceExpired.as_view(), name='service_expired'),
    path('get_queued_sms', get_queued_sms, name='get_queued_sms'),
    path('legal-mentions', LegalMentions.as_view(), name='legal_mentions'),
    path('terms-and-conditions', TermsAndConditions.as_view(), name='terms_and_conditions'),

    # The following url link to the page which display  emails log.
    path('sentEmailLog/', user_passes_test(is_staff)(SentEmailLog.as_view()), name='sent_email_log'),
    path('sentEmailDetail/<object_id>', user_passes_test(is_staff)(SentEmailDetail.as_view()), name='sent_email_detail'),

    path('PWAConfig', permission_required('accesscontrol.sudo')(PWAConfig.as_view()), name='pwa_config'),
    path('analytics', analytics, name='analytics'),
    path('update_push_subscription', update_push_subscription),

    path('<slug:project_name_slug>/', CompanyProfile.as_view(), name='company_profile'),
]
