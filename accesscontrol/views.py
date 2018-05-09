# -*- coding: utf-8 -*-
import json
import random
import string
from threading import Thread
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse, NoReverseMatch
from django.core.validators import validate_email
from django.db.models import Q
from django.http.response import HttpResponseRedirect, HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode, urlunquote
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache, cache_page
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView
from permission_backend_nonrel.models import UserPermissionList
from permission_backend_nonrel.utils import add_permission_to_user, add_user_to_group

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.forms import MemberForm, PasswordResetForm, SMSPasswordResetForm, SetPasswordForm, \
    SetPasswordFormSMSRecovery
from ikwen.accesscontrol.models import Member, AccessRequest, ACCESS_REQUEST_EVENT, \
    SUDO, ACCESS_GRANTED_EVENT, COMMUNITY, WELCOME_EVENT
from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.core.models import Application, Service, ConsoleEvent, WELCOME_ON_IKWEN_EVENT
from ikwen.core.utils import get_service_instance, get_mail_content, add_database_to_settings, add_event, set_counters, \
    increment_history_field
from ikwen.core.utils import send_sms
from ikwen.core.views import HybridListView, IKWEN_BASE_URL

import logging
logger = logging.getLogger('ikwen')


class Register(TemplateView):
    template_name = 'accesscontrol/register.html'

    def get_context_data(self, **kwargs):
        context = super(Register, self).get_context_data(**kwargs)
        context['range_1_31'] = range(1, 32)
        context['range_1_12'] = range(1, 13)
        max_year = datetime.now().year - 17
        min_year = max_year - 80
        context['year_list'] = range(max_year, min_year, -1)
        return context

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            next_url = request.REQUEST.get('next')
            if next_url:
                return HttpResponseRedirect(next_url)
            else:
                next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', None)
                if next_url_view:
                    next_url = reverse(next_url_view)
                else:
                    next_url = ikwenize(reverse('ikwen:console'))
            return HttpResponseRedirect(next_url)
        return super(Register, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        form = MemberForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].strip().lower()
            phone = form.cleaned_data.get('phone', '')
            email = form.cleaned_data.get('email', '').strip().lower()
            first_name = form.cleaned_data.get('first_name', '').strip()
            last_name = form.cleaned_data.get('last_name', '').strip()
            try:
                year = request.POST['year']
                month = request.POST['month']
                day = request.POST['day']
                dob = datetime(int(year), int(month), int(day))
            except:
                dob = None
            sign_in_url = reverse('ikwen:register')
            query_string = request.META.get('QUERY_STRING')
            try:
                validate_email(username)
                email = username
            except ValidationError:
                pass
            try:
                member = Member.objects.get(username=username)
            except Member.DoesNotExist:
                if phone:
                    try:
                        member = Member.objects.get(phone=phone)
                    except Member.DoesNotExist:
                        pass
                    else:
                        msg = _("You already have an account on ikwen with this phone. It was created on %s. "
                                "Use it to login." % member.entry_service.project_name)
                        messages.info(request, msg)
                        if query_string:
                            sign_in_url += "?" + query_string
                        return HttpResponseRedirect(sign_in_url)
                password = form.cleaned_data['password']
                password2 = form.cleaned_data['password2']
                if password != password2:
                    msg = _("Sorry, passwords mismatch.")
                    messages.error(request, msg)
                    register_url = reverse('ikwen:register')
                    if query_string:
                        register_url += "?" + query_string
                    return HttpResponseRedirect(register_url)
                Member.objects.create_user(username=username, phone=phone, email=email, password=password,
                                           first_name=first_name, last_name=last_name, dob=dob)
                member = authenticate(username=username, password=password)
                login(request, member)
                events = getattr(settings, 'IKWEN_REGISTER_EVENTS', ())
                for path in events:
                    event = import_by_path(path)
                    event(request, *args, **kwargs)
                import ikwen.conf.settings as ikwen_settings
                ikwen_service = Service.objects.using(UMBRELLA).get(pk=ikwen_settings.IKWEN_SERVICE_ID)
                add_event(ikwen_service, WELCOME_ON_IKWEN_EVENT, member)
                if not getattr(settings, 'IS_IKWEN', False):
                    service = get_service_instance()
                    add_event(service, WELCOME_EVENT, member)
                    set_counters(service)
                    increment_history_field(service, 'community_history')
                send_welcome_email(member)
                next_url = request.REQUEST.get('next')
                if next_url:
                    # Remove next_url from the original query_string
                    next_url = next_url.split('?')[0]
                    query_string = urlunquote(query_string).replace('next=%s' % next_url, '').strip('?').strip('&')
                    next_url += "?" + query_string
                else:
                    if getattr(settings, 'IS_IKWEN', False):
                        next_url = reverse('ikwen:console')
                    else:
                        next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', None)
                        if next_url_view:
                            next_url = reverse(next_url_view)
                        else:
                            next_url = ikwenize(reverse('ikwen:console'))
                return HttpResponseRedirect(next_url)
            else:
                msg = _("You already have an account on ikwen with this username. It was created on %s. "
                        "Use it to login." % member.entry_service.project_name)
                messages.info(request, msg)
                if query_string:
                    sign_in_url += "?" + query_string
                return HttpResponseRedirect(sign_in_url)
        else:
            context = self.get_context_data(**kwargs)
            context['register_form'] = form
            return render(request, 'accesscontrol/register.html', context)


class SignIn(TemplateView):
    template_name = 'accesscontrol/sign_in.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            next_url = request.REQUEST.get('next')
            if next_url:
                return HttpResponseRedirect(next_url)
            elif not getattr(settings, 'IS_IKWEN', False) and request.user.is_staff:
                return staff_router(request, *args, **kwargs)
            else:
                next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', None)
                if next_url_view:
                    next_url = reverse(next_url_view)
                else:
                    next_url = ikwenize(reverse('ikwen:console'))
            return HttpResponseRedirect(next_url)
        return super(SignIn, self).get(request, *args, **kwargs)

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def post(self, request, *args, **kwargs):
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            member = form.get_user()
            m2 = member.get_from(UMBRELLA)
            member.business_notices = m2.business_notices
            member.personal_notices = m2.personal_notices
            login(request, member)
            events = getattr(settings, 'IKWEN_LOGIN_EVENTS', ())
            for path in events:
                event = import_by_path(path)
                event(request, *args, **kwargs)
            query_string = request.META.get('QUERY_STRING')
            next_url = request.REQUEST.get('next')
            if next_url:
                # Remove next_url from the original query_string
                next_url = next_url.split('?')[0]
                query_string = urlunquote(query_string).replace('next=%s' % next_url, '').strip('?').strip('&')
            else:
                if not getattr(settings, 'IS_IKWEN', False) and member.is_staff:
                    return staff_router(request, *args, **kwargs)
                else:
                    next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', None)
                    if next_url_view:
                        next_url = reverse(next_url_view)
                    else:
                        next_url = ikwenize(reverse('ikwen:console'))
            return HttpResponseRedirect(next_url + "?" + query_string)
        else:
            context = self.get_context_data(**kwargs)
            context['login_form'] = form
            if form.errors:
                error_message = getattr(settings, 'IKWEN_LOGIN_FAILED_ERROR_MSG',
                                        _("Invalid username/password or account inactive"))
                context['error_message'] = error_message
            return render(request, 'accesscontrol/sign_in.html', context)


class SignInMinimal(SignIn):
    template_name = 'accesscontrol/sign_in_minimal.html'

    def get_context_data(self, **kwargs):
        context = super(SignInMinimal, self).get_context_data(**kwargs)
        context['range_1_31'] = range(1, 32)
        context['range_1_12'] = range(1, 13)
        max_year = datetime.now().year - 17
        min_year = max_year - 80
        context['year_list'] = range(max_year, min_year, -1)
        return context

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            super(SignInMinimal, self).get(request, *args, **kwargs)
        username = request.GET.get('username')
        if username:
            try:
                Member.objects.using(UMBRELLA).get(username__iexact=username)
                response = {'existing': True}
            except Member.DoesNotExist:
                try:
                    Member.objects.using(UMBRELLA).filter(email__iexact=username)[0]
                    response = {'existing': True}
                except IndexError:
                    try:
                        Member.objects.using(UMBRELLA).get(phone=username)
                        response = {'existing': True}
                    except Member.DoesNotExist:
                        response = {'existing': False}
            return HttpResponse(json.dumps(response), 'content-type: text/json')
        return super(SignInMinimal, self).get(request, *args, **kwargs)


@login_required
def staff_router(request, *args, **kwargs):
    """
    This view routes Staff user to his correct homepage
    as defined in the STAFF_ROUTER setting. Failing to
    """
    member = request.user
    next_url = reverse('ikwen:staff_without_permission')
    routes = getattr(settings, 'STAFF_ROUTER', None)
    if routes:
        for route in routes:
            perm = route[0]
            url_name = route[1]
            params = route[2] if len(route) > 2 else None
            if member.has_perm(perm):
                if params:
                    if type(params) is tuple:
                        next_url = reverse(url_name, args=params)
                    else:  # params are supposed to be a dictionary here
                        next_url = reverse(url_name, kwargs=params)
                else:
                    next_url = reverse(url_name)
                break
    elif member.is_superuser:
        try:
            next_url = reverse('sudo_home')
        except NoReverseMatch:
            next_url = reverse(getattr(settings, 'LOGIN_REDIRECT_URL', 'home'))

    return HttpResponseRedirect(next_url)


class StaffWithoutPermission(TemplateView):
    template_name = 'accesscontrol/staff_without_permission.html'


class ForgottenPassword(TemplateView):
    template_name = 'accesscontrol/forgotten_password.html'

    def get_context_data(self, **kwargs):
        context = super(ForgottenPassword, self).get_context_data(**kwargs)
        sms_recovery = getattr(settings, 'PASSWORD_RECOVERY_METHOD', 'mail').lower() == 'sms'
        context['sms_recovery'] = sms_recovery
        return context

    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        # TODO: Handle mail sending failure
        sms_recovery = getattr(settings, 'PASSWORD_RECOVERY_METHOD', 'mail').lower() == 'sms'
        if sms_recovery:
            form = SMSPasswordResetForm(request.POST)
            if form.is_valid():
                request.session['phone'] = form.cleaned_data['phone']
                return HttpResponseRedirect(reverse('ikwen:set_new_password_sms_recovery'))
            else:
                context = self.get_context_data(**kwargs)
                context['form'] = form
                return render(request, self.template_name, context)
        else:
            form = PasswordResetForm(request.POST)
            if form.is_valid():
                opts = {
                    'use_https': request.is_secure(),
                    'request': request,
                }
                form.save(**opts)
                return HttpResponseRedirect(reverse('ikwen:forgotten_password') + '?success=yes')
            else:
                context = self.get_context_data(**kwargs)
                context['form'] = form
                return render(request, self.template_name, context)


class SetNewPassword(TemplateView):
    """
    View that checks the hash in a password reset link and presents a
    form for entering a new password.
    """
    template_name = 'accesscontrol/set_new_password.html'

    def get_member(self, uidb64):
        try:
            uid = urlsafe_base64_decode(uidb64)
            member = Member.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, Member.DoesNotExist):
            member = None
        return member

    def get(self, request, *args, **kwargs):
        uidb64, token = kwargs['uidb64'], kwargs['token']
        member = self.get_member(uidb64)
        validlink = False
        if member is not None and default_token_generator.check_token(member, token):
            validlink = True
        context = {
            'uidb64': uidb64,
            'token': token,
            'validlink': validlink,
            'service': get_service_instance()
        }
        return render(request, self.template_name, context)

    # Doesn't need csrf_protect since no-one can guess the URL
    @method_decorator(sensitive_post_parameters())
    @method_decorator(never_cache)
    def post(self, request, uidb64, *args, **kwargs):
        member = self.get_member(uidb64)
        form = SetPasswordForm(member, request.POST)
        if form.is_valid():
            form.save()
            msg = _("Password successfully reset.")
            messages.success(request, msg)
            return HttpResponseRedirect(reverse('ikwen:sign_in'))
        else:
            context = self.get_context_data(**kwargs)
            context['form'] = form
            return render(request, self.template_name, context)


class SetNewPasswordSMSRecovery(TemplateView):
    template_name = 'accesscontrol/set_new_password_sms_recovery.html'

    def send_code(self, request, new_code=False):
        service = get_service_instance()
        reset_code = ''.join([random.SystemRandom().choice(string.digits) for _ in range(4)])
        do_send = False
        try:
            current = request.session['reset_code']  # Test whether there's a pending reset_code in session
            if new_code:
                request.session['reset_code'] = reset_code
                do_send = True
        except KeyError:
            request.session['reset_code'] = reset_code
            do_send = True

        if do_send:
            phone = slugify(request.session['phone']).replace('-', '')
            if len(phone) == 9:
                phone = '237' + phone  # This works only for Cameroon
            text = 'Your password reset code is %s' % reset_code
            try:
                main_link = service.config.sms_api_script_url
                if not main_link:
                    main_link = getattr(settings, 'SMS_MAIN_LINK', None)
                send_sms(phone, text, script_url=main_link, fail_silently=False)
            except:
                fallback_link = getattr(settings, 'SMS_FALLBACK_LINK', None)
                send_sms(phone, text, script_url=fallback_link)

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if getattr(settings, 'DEBUG', False):
            self.send_code(request)
        else:
            try:
                self.send_code(request)
            except:
                context['error_message'] = _('Could not send code. Please try again later')
        return super(SetNewPasswordSMSRecovery, self).get(request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        response = {'success': True}
        if self.request.GET.get('action') == 'new_code':
            if getattr(settings, 'DEBUG', False):
                self.send_code(self.request, new_code=True)
            else:
                try:
                    self.send_code(self.request, new_code=True)
                except:
                    response = {'error': _('Could not send code. Please try again later')}
            return HttpResponse(json.dumps(response), 'content-type: text/json', **response_kwargs)
        else:
            return super(SetNewPasswordSMSRecovery, self).render_to_response(context, **response_kwargs)

    @method_decorator(sensitive_post_parameters())
    @method_decorator(never_cache)
    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        form = SetPasswordFormSMSRecovery(request.POST)
        if form.is_valid():
            reset_code = request.session.get('reset_code')
            if reset_code != form.cleaned_data['reset_code']:
                context = self.get_context_data(**kwargs)
                context['error_message'] = _('Invalid code. Please try again')
                return render(request, self.template_name, context)
            new_pwd1 = form.cleaned_data['new_password1']
            new_pwd2 = form.cleaned_data['new_password2']
            if new_pwd1 != new_pwd2:
                context = self.get_context_data(**kwargs)
                context['error_message'] = _('Passwords mismatch. Please try again')
                return render(request, self.template_name, context)
            phone = request.session['phone']
            active_users = Member.objects.filter(Q(phone=phone) | Q(username=phone),
                                                 is_active=True)
            for member in active_users:
                # Make sure that no SMS is sent to a user that actually has
                # a password marked as unusable
                if not member.has_usable_password():
                    continue
                member.propagate_password_change(new_pwd1)
            msg = _("Password successfully reset.")
            messages.success(request, msg)
            next_url = reverse('ikwen:sign_in') + '?phone=' + phone
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['form'] = form
            return render(request, self.template_name, context)


def send_welcome_email(member):
    """
    Sends welcome email upon registration of a Member. The default message can
    be edited from the admin in Config.welcome_message
    Following strings in the message will be replaced as such:

    $member_name  -->  member.first_name

    @param member: Member object to whom message is sent
    """
    service = get_service_instance()
    config = service.config
    subject = _("Welcome to %s" % service.project_name)
    if config.welcome_message:
        message = config.welcome_message.replace('$member_name', member.first_name)
    else:
        message = _("Welcome %(member_name)s,<br><br>"
                    "Your registration was successful and you can now enjoy our service.<br><br>"
                    "Thank you." % {'member_name': member.first_name})
    html_content = get_mail_content(subject, message, template_name='accesscontrol/mails/welcome.html')
    sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
    msg = EmailMessage(subject, html_content, sender, [member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg,)).start()


class AccountSetup(TemplateView):
    template_name= 'accesscontrol/account.html'


@login_required
def update_info(request, *args, **kwargs):
    member = request.user
    email = request.GET.get('email')
    phone = request.GET.get('phone')
    name = request.GET.get('name')
    gender = request.GET.get('gender')
    if email:
        try:
            Member.objects.get(email=email)
            response = {'error': _('This e-mail already exists.')}
            return HttpResponse(json.dumps(response), content_type='application/json')
        except Member.DoesNotExist:
            member.email = email
    if phone:
        try:
            Member.objects.get(phone=phone)
            response = {'error': _('This phone already exists.')}
            return HttpResponse(json.dumps(response), content_type='application/json')
        except Member.DoesNotExist:
            member.phone = phone
    if name:
        name_tokens = name.split(' ')
        first_name = name_tokens[0]
        last_name = ' '.join(name_tokens[1:])
        member.first_name = first_name
        member.last_name = last_name
    if gender:
        if not member.gender:
            member.gender = gender  # Set gender only if previously not set
    member.save(update_fields=['first_name', 'last_name', 'email', 'phone', 'gender'])
    member.propagate_changes()
    response = {'message': _('Your information were successfully updated.')}
    return HttpResponse(json.dumps(response), content_type='application/json')


@login_required
def update_password(request, *args, **kwargs):
    """
    View that changes the password of the user when he intentionally
    decides to do so from his account management panel.
    """
    member = Member.objects.using(UMBRELLA).get(pk=request.user.id)
    password = request.GET.get('password')
    if check_password(password, member.password):
        password1 = request.GET.get('password1')
        password2 = request.GET.get('password2')
        response = {'message': _('Your password was successfully updated.')}  # Default is everything going well
        if password1:
            if password1 != password2:
                response = {'error': _("Passwords don't match.")}
            else:
                member.propagate_password_change(password1)
                response = {'message': _('Your password was successfully updated.')}
    else:
        response = {'error': _("The current password is incorrect!")}
    return HttpResponse(
        json.dumps(response),
        content_type='application/json'
    )


class Profile(TemplateView):
    template_name = 'accesscontrol/profile.html'

    @method_decorator(cache_page(60 * 5))
    def get(self, request, *args, **kwargs):
        member_id = kwargs['member_id']
        member = get_object_or_404(Member, pk=member_id)
        context = super(Profile, self).get_context_data(**kwargs)
        if request.user.is_authenticated() and request.user.is_iao:
            rqs = []
            for rq in AccessRequest.objects.filter(member=member, status=AccessRequest.PENDING):
                rq_service = rq.service
                if rq_service in request.user.collaborates_on:
                    add_database_to_settings(rq_service.database)
                    groups = list(Group.objects.using(rq_service.database).exclude(name=SUDO).order_by('name'))
                    groups.append(Group.objects.using(rq_service.database).get(name=SUDO))  # Sudo will appear last
                    rqs.append({'rq': rq, 'groups': groups})
            context['access_request_list'] = rqs
        context['profile_name'] = member.full_name
        context['profile_email'] = member.email
        context['profile_phone'] = member.phone
        context['profile_gender'] = member.gender
        context['profile_photo_url'] = member.photo.small_url if member.photo.name else ''
        context['profile_cover_url'] = member.cover_image.url if member.cover_image.name else ''
        context['member'] = member
        return render(request, self.template_name, context)


class CompanyProfile(TemplateView):
    """
    Can either be a company profile or an ikwen App description page.
    In the case of an ikwen App. The *Deploy* link will appear.
    """
    template_name = 'accesscontrol/profile.html'

    def get(self, request, *args, **kwargs):
        context = super(CompanyProfile, self).get_context_data(**kwargs)
        project_name_slug = kwargs['project_name_slug']
        service = get_object_or_404(Service, project_name_slug=project_name_slug)
        try:
            app = Application.objects.get(slug=project_name_slug)
            context['app'] = app
            try:
                app_deploy_template = 'apps/%s.html' % app.slug
                get_template(app_deploy_template)
                self.template_name = app_deploy_template
            except:
                pass
        except Application.DoesNotExist:
            pass
        config = service.config
        context['is_company'] = True
        context['page_service'] = service  # Updates the service context defined in TemplateView
        context['page_config'] = config
        context['profile_name'] = service.project_name
        context['profile_email'] = config.contact_email
        context['profile_phone'] = config.contact_phone
        context['profile_address'] = config.address
        context['profile_city'] = config.city
        context['profile_photo_url'] = config.logo.url if config.logo.name else ''
        context['profile_cover_url'] = config.cover_image.url if config.cover_image.name else ''
        if request.user.is_authenticated():
            try:
                AccessRequest.objects.get(member=request.user, service=service,
                                          status=AccessRequest.PENDING)
                context['is_member'] = True  # Causes the "Join" button not to appear when there's a pending Access Request
            except AccessRequest.DoesNotExist:
                try:
                    add_database_to_settings(service.database)
                    Member.objects.using(service.database).get(pk=request.user.id)
                    context['is_member'] = True
                except Member.DoesNotExist:
                    context['is_member'] = False
        return render(request, self.template_name, context)


class Community(HybridListView):
    MAX = 50
    page_size = 50
    template_name = 'accesscontrol/community.html'
    context_object_name = 'nonrel_perm_list'
    ordering = ('-id', )
    ajax_ordering = ('-id', )

    def get_queryset(self):
        group_name = self.request.GET.get('group_name')
        if group_name:
            group_id = Group.objects.get(name=group_name).id
        else:
            group_id = Group.objects.get(name=COMMUNITY).id
        return UserPermissionList.objects.raw_query({'group_fk_list': {'$elemMatch': {'$eq': group_id}}})

    def get_context_data(self, **kwargs):
        context = super(Community, self).get_context_data(**kwargs)
        groups = [Group.objects.get(name=COMMUNITY)]
        groups.extend(list(Group.objects.exclude(name__in=[COMMUNITY, SUDO]).order_by('name')))
        context['groups'] = groups
        context['sudo_group'] = Group.objects.get(name=SUDO)
        context['permissions'] = Permission.objects.filter(codename__startswith='ik_')
        return context


class MemberList(HybridListView):
    template_name = 'accesscontrol/member_list.html'
    context_object_name = 'customer_list'
    model = Member
    search_field = 'full_name'
    ordering = ('first_name', '-id', )
    ajax_ordering = ('first_name', '-id', )
    page_size = 2


@permission_required('accesscontrol.ik_manage_customer')
def load_member_detail(request, *args, **kwargs):
    member_id = request.GET['member_id']
    member = Member.objects.get(pk=member_id)
    path = getattr(settings, 'CUSTOMER_DETAIL_RENDERER', 'ikwen.accesscontrol.views.render_customer_detail')
    fn = import_by_path(path)
    content = fn(member)
    return HttpResponse(content)


def render_customer_detail(member):
    html_template = get_template('accesscontrol/snippets/customer_detail.html')
    c = Context({'member': member})
    return html_template.render(c)


@permission_required('accesscontrol.sudo')
def list_collaborators(request, *args, **kwargs):
    q = request.GET['q'].lower()
    if len(q) < 2:
        return
    q = q[:4]
    results = []
    for m in Member.objects.filter(full_name__icontains=q):
        try:
            results.append(m.to_dict())
        except:
            pass
    return HttpResponse(json.dumps(results), content_type='application/json')


class AccessRequestList(TemplateView):
    """
    Lists all Access requests for the admin to process them all from
    a single page rather than going to everyone's profile
    """
    template_name = 'accesscontrol/access_request_list.html'

    def get_context_data(self, **kwargs):
        context = super(AccessRequestList, self).get_context_data(**kwargs)
        rqs = []
        services = self.request.user.collaborates_on
        for rq in AccessRequest.objects.filter(service__in=services, status=AccessRequest.PENDING):
            if rq.service in self.request.user.collaborates_on:
                add_database_to_settings(rq.service.database)
                groups = Group.objects.using(rq.service.database).exclude(name=SUDO).order_by('name')
                rqs.append({'rq': rq, 'groups': groups})
        context['access_requests'] = rqs
        return context


@login_required  # The user must be logged in to ikwen and not his own service, this view runs on ikwen
def request_access(request, *args, **kwargs):
    service_id = request.GET['service_id']
    format = request.GET.get('format')
    service = Service.objects.get(pk=service_id)
    member = Member.objects.get(pk=request.user.id)
    try:
        AccessRequest.objects.get(member=member, service=service)
    except AccessRequest.DoesNotExist:
        rq = AccessRequest.objects.create(member=member, service=service)
        subject = _("Request to join")
        message = _("Hi %(iao_name)s,<br><br>%(member_name)s requested to join you on "
                    "<b>%(project_name)s</b>.<br><br>" % {'iao_name': service.member.first_name,
                                                          'member_name': member.full_name,
                                                          'project_name': service.project_name})
        add_event(service, ACCESS_REQUEST_EVENT, member=service.member, object_id=rq.id)
        html_content = get_mail_content(subject, message, template_name='core/mails/notice.html',
                                        extra_context={'cta_text': _("View"),
                                                       'cta_url': IKWEN_BASE_URL + reverse('ikwen:profile', args=(member.id, ))})
        sender = '%s <%s>' % ('ikwen', 'no-reply@ikwen.com')
        msg = EmailMessage(subject, html_content, sender, [service.member.email])
        # msg = EmailMessage(subject, html_content, sender, ['nouty1931@rhyta.com'])  # Testing
        msg.content_subtype = "html"
        Thread(target=lambda m: m.send(), args=(msg, )).start()
    if format == 'json':
        return HttpResponse(json.dumps({'success': True}), content_type='application/json')
    else:
        next_url = service.get_profile_url()
        return HttpResponseRedirect(next_url + '?successfulRequest=yes')


@login_required   # The user must be logged in to ikwen and not his own service, this view runs on ikwen
def grant_access(request, *args, **kwargs):
    if not request.user.is_iao:
        # TODO: Verify that IA0 is actually the owner of the service for which the request is made
        return HttpResponseForbidden('Only IA0 May grant access')
    request_id = request.GET['request_id']
    group_id = request.GET.get('group_id')
    rq = AccessRequest.objects.get(pk=request_id)
    rq_member = rq.member
    rq_service = rq.service
    count = Member.objects.raw_query({'collaborates_on_fk_list': {'$elemMatch': {'$eq': rq_service.id}}}).count()
    if count > Community.MAX:
        response = {'error': "Maximum of %d collaborators reached" % Community.MAX}
        return HttpResponse(json.dumps(response), content_type='application/json')
    database = rq_service.database
    add_database_to_settings(database)
    group = Group.objects.using(database).get(pk=group_id)
    rq.member.customer_on_fk_list.append(rq_service.id)
    if group.name != COMMUNITY:
        rq_member.collaborates_on_fk_list.append(rq_service.id)
    rq_member.group_fk_list.append(group.id)
    rq_member.save()

    if group.name != COMMUNITY:
        rq_member.is_staff = True
    if group.name == SUDO:
        rq_member.is_superuser = True
    rq_member.is_iao = False
    rq_member.save(using=database)
    member = Member.objects.using(database).get(pk=rq_member.id)  # Reload from local database to avoid database router error
    obj_list, created = UserPermissionList.objects.using(database).get_or_create(user=member)
    obj_list.group_fk_list.append(group.id)
    obj_list.save(using=database)
    rq.status = AccessRequest.CONFIRMED
    rq.group_name = group.name
    rq.save()
    try:
        ConsoleEvent.objects.get(member=request.user, object_id=rq.id).delete()
    except ConsoleEvent.DoesNotExist:
        pass
    add_event(rq_service, WELCOME_EVENT, member=rq_member, object_id=rq.id)
    add_event(rq_service, ACCESS_GRANTED_EVENT, member=rq_service.member, object_id=rq.id)
    set_counters(rq_service)
    increment_history_field(rq_service, 'community_history')
    subject = _("You were added to %s community" % rq_service.project_name)
    message = _("Hi %(member_name)s,<br><br>You were added to <b>%(project_name)s</b> community.<br><br>"
                "Thanks for joining us." % {'member_name': rq_member.first_name,
                                            'project_name': rq_service.project_name})
    html_content = get_mail_content(subject, message, template_name='core/mails/notice.html',
                                    extra_context={'cta_text': _("Join"),
                                                   'cta_url': rq_service.admin_url})
    sender = '%s <no-reply@%s>' % (rq_service.project_name, rq_service.domain)
    msg = EmailMessage(subject, html_content, sender, [rq_member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg, )).start()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


@login_required   # The user must be logged in to ikwen and not his own service, this view runs on ikwen
def deny_access(request, *args, **kwargs):
    if not request.user.is_iao:
        # TODO: Verify that IA0 is actually the owner of the service for which the request is made
        return HttpResponseForbidden('Only IA0 May deny access')
    request_id = request.GET['request_id']
    ConsoleEvent.objects.get(object_id=request_id).delete()
    AccessRequest.objects.get(pk=request_id).delete()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


@permission_required('accesscontrol.sudo')
def set_collaborator_permissions(request, *args, **kwargs):
    permission_id_list = request.GET['permission_ids'].split(',')
    member_id = request.GET['member_id']
    member = Member.objects.get(pk=member_id)
    obj = UserPermissionList.objects.get(user=member)
    obj.permission_list = []
    obj.permission_fk_list = []
    obj.save()
    if permission_id_list:
        for perm_id in permission_id_list:
            perm = Permission.objects.get(pk=perm_id)
            add_permission_to_user(perm, member)
            # Add Django original permissions of the content_type so that
            # member can manipulate the object in the django admin app. This
            # because ikwen admin can sometimes embed django admin in iframe.
            ct = perm.content_type
            django_perms = Permission.objects.filter(content_type=ct).exclude(codename__istartswith='ik_')
            for perm in django_perms:
                add_permission_to_user(perm, member)
        member.is_staff = True
    else:
        member.is_staff = False
    member.save()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


@permission_required('accesscontrol.sudo')
def move_member_to_group(request, *args, **kwargs):
    group_id = request.GET['group_id']
    member_id = request.GET['member_id']
    if member_id == request.user.id:
        # One cannot move himself
        return HttpResponse(json.dumps({'error': "One cannot move himself"}), content_type='application/json')
    group = Group.objects.get(pk=group_id)
    member = Member.objects.get(pk=member_id)
    if member.is_bao:
        return HttpResponse(json.dumps({'error': "Bao can only be transferred."}), content_type='application/json')
    if group.name == SUDO:
        if not request.user.is_bao:
            return HttpResponse(json.dumps({'error': "Only Bao User can transfer member here."}), content_type='application/json')
        member.is_staff = True
        member.is_superuser = True
    else:
        member.is_staff = False
        member.is_superuser = False
    member.save()
    obj = UserPermissionList.objects.get(user=member)
    obj.permission_list = []
    obj.permission_fk_list = []
    obj.group_fk_list = []
    obj.save()
    add_user_to_group(member,  group)
    member_umbrella = Member.objects.using(UMBRELLA).get(pk=member_id)
    
    service = get_service_instance()
    collaborates_on_fk_list = member_umbrella.collaborates_on_fk_list
    if group.name == COMMUNITY:
        if service.id in collaborates_on_fk_list:
            collaborates_on_fk_list.remove(service.id)
    else:
        if service.id not in collaborates_on_fk_list:
            collaborates_on_fk_list.append(service.id)
    Member.objects.filter(pk=member_id).update(collaborates_on_fk_list=collaborates_on_fk_list)
    Member.objects.using(UMBRELLA).filter(pk=member_id).update(collaborates_on_fk_list=collaborates_on_fk_list)

    for grp in Group.objects.exclude(name__in=[COMMUNITY, SUDO]):
        try:
            member_umbrella.group_fk_list.remove(grp.id)
        except ValueError:
            pass
    member_umbrella.group_fk_list.append(group.id)
    member_umbrella.save(using=UMBRELLA)
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


# @permission_required('accesscontrol.sudo')
# def send_request_to_become_bao(request, *args, **kwargs):
#     group_id = request.GET['group_id']
#     member_id = request.GET['member_id']
#     if member_id == request.user.id:
#         # One cannot block himself
#         return HttpResponse(json.dumps({'error': "One cannot move himself"}), content_type='application/json')
#     group = Group.objects.get(pk=group_id)
#     member = Member.objects.get(pk=member_id)
#     if member.is_bao:
#         return HttpResponse(json.dumps({'error': "BAO can only be transferred."}), content_type='application/json')
#     obj = UserPermissionList.objects.get(user=member)
#     obj.permission_list = []
#     obj.permission_fk_list = []
#     obj.group_fk_list = []
#     obj.save()
#     add_user_to_group(member,  group)
#     return HttpResponse(json.dumps({'success': True}), content_type='application/json')


@permission_required('accesscontrol.sudo')
def toggle_member(request, *args, **kwargs):
    member_id = request.GET['member_id']
    if member_id == request.user.id:
        # One cannot block himself
        return HttpResponse(json.dumps({'error': "One cannot block himself"}), content_type='application/json')
    member = Member.objects.get(pk=member_id)
    if member.is_bao:
        return HttpResponse(json.dumps({'error': "BAO can only be transferred."}), content_type='application/json')
    if member.is_active:
        member.is_active = False
    else:
        member.is_active = True
    member.save()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


def render_access_request_event(event, request):
    try:
        access_request = AccessRequest.objects.using(UMBRELLA).get(pk=event.object_id)
    except AccessRequest.DoesNotExist:
        return None
    html_template = get_template('accesscontrol/events/access_request.html')
    from ikwen.conf.settings import MEDIA_URL
    c = Context({'rq': access_request, 'IKWEN_MEDIA_URL': MEDIA_URL})
    return html_template.render(c)


def render_welcome_event(event, request):
    html_template = get_template('accesscontrol/events/welcome_event.html')
    c = Context({})
    return html_template.render(c)


def render_welcome_on_ikwen_event(event, request):
    html_template = get_template('accesscontrol/events/welcome_on_ikwen.html')
    c = Context({})
    return html_template.render(c)


def render_access_granted_event(event, request):
    try:
        access_request = AccessRequest.objects.using(UMBRELLA).get(pk=event.object_id)
    except AccessRequest.DoesNotExist:
        return None
    html_template = get_template('accesscontrol/events/access_granted.html')
    database = event.service.database
    add_database_to_settings(database)
    member = Member.objects.using(database).get(pk=event.member.id)
    from ikwen.conf.settings import MEDIA_URL
    c = Context({'service': access_request.service, 'member': access_request.member,
                 'group_name': access_request.group_name, 'is_iao': member.is_iao, 'IKWEN_MEDIA_URL': MEDIA_URL})
    return html_template.render(c)


def render_member_joined_event(event, request):
    request_user = Member.objects.get(pk=request.GET['member_id'])
    try:
        member = Member.objects.get(pk=event.object_id)
    except AccessRequest.DoesNotExist:
        return None
    html_template = get_template('accesscontrol/events/access_granted.html')
    from ikwen.conf.settings import MEDIA_URL
    c = Context({'service': get_service_instance(), 'member': member,
                 'group_name': COMMUNITY, 'IKWEN_MEDIA_URL': MEDIA_URL, 'is_iao': member != request_user})
    return html_template.render(c)


class PhoneConfirmation(TemplateView):
    template_name = 'accesscontrol/phone_confirmation.html'

    def send_code(self, request, new_code=False):
        service = get_service_instance()
        member = request.user
        code = ''.join([random.SystemRandom().choice(string.digits) for _ in range(4)])
        do_send = False
        try:
            current = request.session['code']  # Test whether there's a pending code in session
            if new_code:
                request.session['code'] = code
                do_send = True
        except KeyError:
            request.session['code'] = code
            do_send = True

        if do_send:
            phone = slugify(member.phone).replace('-', '')
            if len(phone) == 9:
                phone = '237' + phone  # This works only for Cameroon
            text = 'Your %s confirmation code is %s' % (service.project_name, code)
            try:
                main_link = service.config.sms_api_script_url
                if not main_link:
                    main_link = getattr(settings, 'SMS_MAIN_LINK', None)
                send_sms(phone, text, script_url=main_link, fail_silently=False)
            except:
                fallback_link = getattr(settings, 'SMS_FALLBACK_LINK', None)
                send_sms(phone, text, script_url=fallback_link, fail_silently=False)

    def get(self, request, *args, **kwargs):
        next_url = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
        member = request.user
        if member.is_authenticated() and member.phone_verified:
            return HttpResponseRedirect(reverse(next_url))
        if getattr(settings, 'DEBUG', False):
            self.send_code(request)
        else:
            try:
                self.send_code(request)
            except:
                logger.error('Failed to submit SMS to %s' % member.phone, exc_info=True)
                messages.error(request, _('Could not send code. Please try again later'))
        return super(PhoneConfirmation, self).get(request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        response = {'success': True}
        if self.request.GET.get('action') == 'new_code':
            if getattr(settings, 'DEBUG', False):
                self.send_code(self.request, new_code=True)
            else:
                try:
                    self.send_code(self.request, new_code=True)
                except:
                    response = {'error': _('Could not send code. Please try again later')}
            return HttpResponse(json.dumps(response), 'content-type: text/json', **response_kwargs)
        else:
            return super(PhoneConfirmation, self).render_to_response(context, **response_kwargs)

    def post(self, request, *args, **kwargs):
        member = request.user
        code = request.session.get('code')
        if code != request.POST['code']:
            context = self.get_context_data(**kwargs)
            context['error_message'] = _('Invalid code. Please try again')
            return render(request, self.template_name, context)
        member.phone_verified = True
        member.save()
        next_url = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
        return HttpResponseRedirect(reverse(next_url))
