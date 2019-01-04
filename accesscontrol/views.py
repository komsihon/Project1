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
from django.db.models import Q, Sum
from django.http.response import HttpResponseRedirect, HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode, urlunquote, urlquote
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache, cache_page
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView
from permission_backend_nonrel.models import UserPermissionList
from permission_backend_nonrel.utils import add_permission_to_user, add_user_to_group

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.utils import send_welcome_email, shift_ghost_member, import_ghost_profile_to_member
from ikwen.accesscontrol.forms import MemberForm, PasswordResetForm, SMSPasswordResetForm, SetPasswordForm, \
    SetPasswordFormSMSRecovery
from ikwen.accesscontrol.models import Member, AccessRequest, \
    SUDO, ACCESS_GRANTED_EVENT, COMMUNITY, WELCOME_EVENT, DEFAULT_GHOST_PWD
from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.core.constants import MALE, FEMALE
from ikwen.core.models import Application, Service, ConsoleEvent, WELCOME_ON_IKWEN_EVENT
from ikwen.core.utils import get_service_instance, get_mail_content, add_database_to_settings, add_event, set_counters, \
    increment_history_field
from ikwen.core.utils import send_sms
from ikwen.core.views import HybridListView
from ikwen.revival.models import ProfileTag, MemberProfile, Revival, ObjectProfile
from ikwen.revival.utils import set_profile_tag_member_count
from ikwen.rewarding.models import Coupon, CumulatedCoupon, Reward, CROperatorProfile, CouponSummary, ReferralRewardPack
from ikwen.rewarding.utils import reward_member, get_coupon_summary_list, JOIN

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
            gender = form.cleaned_data.get('gender')
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
                member = Member.objects.using(UMBRELLA).get(username=username)
                if member.is_ghost:
                    raise Member.DoesNotExist()
            except Member.DoesNotExist:
                if phone:
                    try:
                        member = Member.objects.using(UMBRELLA).get(phone=phone)
                        if member.is_ghost:
                            raise Member.DoesNotExist()
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
                                           first_name=first_name, last_name=last_name, dob=dob, gender=gender)
                member = authenticate(username=username, password=password)
                login(request, member)
                events = getattr(settings, 'IKWEN_REGISTER_EVENTS', ())
                for path in events:
                    event = import_by_path(path)
                    event(request, *args, **kwargs)
                import ikwen.conf.settings as ikwen_settings
                ikwen_service = Service.objects.using(UMBRELLA).get(pk=ikwen_settings.IKWEN_SERVICE_ID)
                add_event(ikwen_service, WELCOME_ON_IKWEN_EVENT, member)
                reward_pack_list = None
                if not getattr(settings, 'IS_IKWEN', False):
                    service = get_service_instance()
                    add_event(service, WELCOME_EVENT, member)
                    set_counters(service)
                    increment_history_field(service, 'community_history')
                    reward_pack_list, coupon_count = reward_member(service, member, Reward.JOIN)
                send_welcome_email(member, reward_pack_list)
                if request.GET.get('join'):
                    return join(request, *args, **kwargs)
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

                Thread(target=set_profile_tag_member_count).start()
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
        response = {'existing': False}
        if username:
            try:
                member = Member.objects.using(UMBRELLA).get(username__iexact=username)
                if not member.is_ghost:
                    response = {'existing': True}
            except Member.DoesNotExist:
                try:
                    member = Member.objects.using(UMBRELLA).filter(email__iexact=username)[0]
                    if not member.is_ghost:
                        response = {'existing': True}
                except IndexError:
                    try:
                        member = Member.objects.using(UMBRELLA).get(phone=username)
                        if not member.is_ghost:
                            response = {'existing': True}
                    except Member.DoesNotExist:
                        pass
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
            context['uidb64'] = uidb64
            context['token'] = kwargs['token']
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
            if member.email != email:
                member.email_verified = False
    if phone:
        try:
            Member.objects.get(phone=phone)
            response = {'error': _('This phone already exists.')}
            return HttpResponse(json.dumps(response), content_type='application/json')
        except Member.DoesNotExist:
            member.phone = phone
            if member.phone != phone:
                member.phone_verified = False
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
        context['coupon_summary_list'] = get_coupon_summary_list(member)
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
        try:
            cr_profile = CROperatorProfile.objects.get(service=service, is_active=True)
        except CROperatorProfile.DoesNotExist:
            pass
        else:
            coupon_qs = Coupon.objects.filter(service=service, status=Coupon.APPROVED, is_active=True)
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
                coupon_list = []
                for coupon in coupon_qs:
                    try:
                        cumul = CumulatedCoupon.objects.get(coupon=coupon, member=request.user)
                        coupon.count = cumul.count
                        coupon.ratio = float(cumul.count) / coupon.heap_size * 100
                    except CumulatedCoupon.DoesNotExist:
                        coupon.count = 0
                        coupon.ratio = 0
                    coupon_list.append(coupon)
            else:
                coupon_list = coupon_qs
            url = getattr(settings, 'PROJECT_URL') + reverse('ikwen:company_profile', args=(project_name_slug, ))
            if request.user.is_authenticated():
                url += '?referrer=' + request.user.id
                context['coupon_summary_list'] = get_coupon_summary_list(request.user)
            context['url'] = urlquote(url)
            context['cr_profile'] = cr_profile
            context['coupon_list'] = coupon_list
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
        group_list = [Group.objects.get(name=COMMUNITY)]
        group_list.extend(list(Group.objects.exclude(name__in=[COMMUNITY, SUDO]).order_by('name')))
        context['group_list'] = group_list
        context['sudo_group'] = Group.objects.get(name=SUDO)
        context['profiletag_list'] = ProfileTag.objects.exclude(slug__in=['men', 'women']).filter(is_active=True, is_auto=False)
        return context

    def render_to_response(self, context, **response_kwargs):
        action = self.request.GET.get('action')
        if action == 'load_member_detail':
            return self.load_member_detail(context)
        elif action == 'set_member_profiles':
            return self.set_member_profiles(context)
        elif action == 'add_ghost_member':
            return self.add_ghost_member()
        return super(Community, self).render_to_response(context, **response_kwargs)

    def load_member_detail(self, context):
        member_id = self.request.GET['member_id']
        member = Member.objects.get(pk=member_id)
        obj = UserPermissionList.objects.get(user=member)
        try:
            group = Group.objects.get(pk=obj.group_fk_list[0])
        except:
            group = Group.objects.get(name=COMMUNITY)

        member.group = group
        permission_list = list(Permission.objects.filter(codename__startswith='ik_'))
        for perm in permission_list:
            if perm.id in obj.permission_fk_list:
                perm.is_active = True

        member_profile, update = MemberProfile.objects.get_or_create(member=member)
        profiletag_list = list(ProfileTag.objects.filter(is_active=True, is_auto=False))
        for tag in profiletag_list:
            if tag.slug in member_profile.tag_list:
                tag.is_selected = True
        context['member'] = member
        context['permission_list'] = permission_list
        context['profiletag_list'] = profiletag_list
        return render(self.request, 'accesscontrol/snippets/member_detail.html', context)

    def set_member_profiles(self, *args, **kwargs):
        tag_id_list = []
        tag_ids = self.request.GET['tag_ids']
        if tag_ids:
            tag_id_list = tag_ids.split(',')
        member_id = self.request.GET['member_id']
        member = Member.objects.get(pk=member_id)
        tag_list = []
        for tag in ProfileTag.objects.filter(pk__in=tag_id_list):
            tag_list.append(tag.slug)
            if tag.slug == 'men':
                if not member.gender:
                    Member.objects.using('default').filter(pk=member_id).update(gender=MALE)
                    Member.objects.using(UMBRELLA).filter(pk=member_id).update(gender=MALE)
            elif tag.slug == 'women':
                if not member.gender:
                    Member.objects.using('default').filter(pk=member_id).update(gender=FEMALE)
                    Member.objects.using(UMBRELLA).filter(pk=member_id).update(gender=FEMALE)
        member_profile = MemberProfile.objects.get(member=member)
        member_profile.tag_list = tag_list
        member_profile.save()
        Thread(target=set_profile_tag_member_count).start()
        return HttpResponse(json.dumps({'success': True}), content_type='application/json')

    def add_ghost_member(self, *args, **kwargs):
        name = self.request.GET.get('name', '')
        gender = self.request.GET.get('gender', '')
        email = self.request.GET.get('email', '')
        phone = self.request.GET.get('phone', '')
        tag_ids = self.request.GET.get('tag_ids')
        if email:
            try:
                Member.objects.filter(email=email)[0]
                response = {'error': _("This email already exists")}
                HttpResponse(json.dumps(response), content_type='application/json')
            except:
                pass
        if phone:
            phone = slugify(phone).replace('-', '')
            if phone.startswith('237') and len(phone) == 12:
                phone = phone[3:]
            try:
                Member.objects.filter(phone=phone)[0]
                response = {'error': _("This phone already exists")}
                HttpResponse(json.dumps(response), content_type='application/json')
            except:
                pass
            try:
                Member.objects.filter(phone='237' + phone)[0]
                response = {'error': _("This phone already exists")}
                HttpResponse(json.dumps(response), content_type='application/json')
            except:
                pass

        tag_id_list = []
        if tag_ids:
            tag_id_list = tag_ids.split(',')
        first_name, last_name = '', ''
        if name:
            tk = name.split(' ')
            first_name = tk[0]
            if len(tk) >= 2:
                last_name = ' '.join(tk[1:])

        username = email if email else phone
        member = Member.objects.create_user(username, DEFAULT_GHOST_PWD, first_name=first_name, last_name=last_name,
                                            email=email, phone=phone, gender=gender, is_ghost=True)
        tag_list = [JOIN]
        for tag in ProfileTag.objects.filter(pk__in=tag_id_list):
            tag_list.append(tag.slug)
        member_profile = MemberProfile.objects.get(member=member)
        member_profile.tag_list.extend(tag_list)
        member_profile.save()

        service = Service.objects.using(UMBRELLA).get(pk=getattr(settings, 'IKWEN_SERVICE_ID'))
        Revival.objects.using(UMBRELLA).get_or_create(service=service, model_name='core.Service', object_id=service.id,
                                                      mail_renderer='ikwen.revival.utils.render_suggest_create_account_mail',
                                                      get_kwargs='ikwen.rewarding.utils.get_join_reward_pack_list')
        tag = JOIN
        ProfileTag.objects.get_or_create(name=tag, slug=tag, is_auto=True)
        object_profile, update = ObjectProfile.objects.get_or_create(model_name='core.Service', object_id=service.id)
        object_profile.tag_list.append(tag)
        object_profile.save()

        Thread(target=set_profile_tag_member_count).start()
        response = {'success': True, 'member': member.to_dict()}
        return HttpResponse(json.dumps(response), content_type='application/json')


class MemberList(HybridListView):
    context_object_name = 'customer_list'
    model = Member
    search_field = 'tags'
    ordering = ('first_name', '-id', )
    ajax_ordering = ('first_name', '-id', )


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


@login_required   # The user must be logged in to ikwen and not his own service, this view runs on ikwen
def join(request, *args, **kwargs):
    service_id = request.GET.get('service_id')
    slug = request.GET.get('join')
    referrer_id = request.GET.get('referrer')
    format = request.GET.get('format')
    if service_id:
        service = get_object_or_404(Service, pk=service_id)
    else:
        service = get_object_or_404(Service, project_name_slug=slug)
        service_id = service.id
    member = request.user
    if service_id in member.customer_on_fk_list:
        if format == 'json':
            return HttpResponse(json.dumps({'success': True}), content_type='application/json')
        else:
            next_url = service.get_profile_url()
            notice = _("You were added to our community. Thank you for joining us.")
            messages.success(request, notice)
            return HttpResponseRedirect(next_url)
    try:
        rq = AccessRequest.objects.get(member=member, service=service)
    except AccessRequest.DoesNotExist:
        rq = AccessRequest.objects.create(member=member, service=service)
    db = service.database
    add_database_to_settings(db)
    group = Group.objects.using(db).get(name=COMMUNITY)
    member.customer_on_fk_list.append(service.id)
    if group.id not in member.group_fk_list:
        member.group_fk_list.append(group.id)
    member.save()
    member.is_staff = False
    member.is_superuser = False
    member.is_iao = False
    member.date_joined = datetime.now()
    member.last_login = datetime.now()
    shift_ghost_member(member, db=db)
    member.save(using=db)
    import_ghost_profile_to_member(member, db=db)
    member = Member.objects.using(db).get(pk=member.id)  # Reload from local database to avoid database router error
    obj_list, created = UserPermissionList.objects.using(db).get_or_create(user=member)
    obj_list.group_fk_list.append(group.id)
    obj_list.save(using=db)
    add_event(service, WELCOME_EVENT, member=member, object_id=rq.id)
    add_event(service, ACCESS_GRANTED_EVENT, member=service.member, object_id=rq.id)
    set_counters(service)
    increment_history_field(service, 'community_history')
    events = getattr(settings, 'IKWEN_REGISTER_EVENTS', ())
    for path in events:
        event = import_by_path(path)
        try:
            event(request, *args, **kwargs)
        except:
            pass
    reward_pack_list, coupon_count = reward_member(service, member, Reward.JOIN)
    subject = _("You just joined %s community" % service.project_name)
    reward, join_coupon_count, referral_coupon_count = None, 0, 0
    if reward_pack_list:
        template_name = 'rewarding/mails/community_welcome_pack.html'
        coupon_summary = CouponSummary.objects.using(UMBRELLA).get(service=service, member=member)
        aggr = ReferralRewardPack.objects.filter(service=service).aggregate(Sum('count'))
        join_coupon_count = coupon_summary.count
        referral_coupon_count = aggr['count__sum']
        reward = {'join_coupon_count': join_coupon_count, 'referral_coupon_count': referral_coupon_count}
    else:
        template_name = 'accesscontrol/mails/community_welcome.html'

    html_content = get_mail_content(subject, template_name=template_name,
                                    extra_context={'reward_pack_list': reward_pack_list,
                                                   'joined_service': service, 'joined_project_name': service.project_name,
                                                   'joined_logo': service.config.logo})
    sender = 'ikwen <no-reply@ikwen.com>'
    msg = EmailMessage(subject, html_content, sender, [member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg, )).start()
    if referrer_id:
        referrer = Member.objects.get(pk=referrer_id)
        referrer_profile, update = MemberProfile.objects.get_or_create(member=referrer)
        referrer_tag_list = referrer_profile.tag_list
        if 'men' in referrer_tag_list:
            referrer_tag_list.remove('men')
        if 'women' in referrer_tag_list:
            referrer_tag_list.remove('women')
        member_profile, update = MemberProfile.objects.get_or_create(member=member)
        member_profile.tag_list.extend(referrer_tag_list)
        if member.gender == MALE:
            member_profile.tag_list.append('men')
        elif member.gender == FEMALE:
            member_profile.tag_list.append('women')
        member_profile.save()
        referral_pack_list, coupon_count = reward_member(service, referrer, Reward.REFERRAL)
        if referral_pack_list:
            referrer_subject = _("%s is offering you %d coupons for your referral to %s" % (service.project_name, coupon_count, member.full_name))
            template_name = 'rewarding/mails/referral_reward.html'
            CouponSummary.objects.using(UMBRELLA).get(service=service, member=referrer)
            html_content = get_mail_content(referrer_subject, template_name=template_name,
                                            extra_context={'referral_pack_list': referral_pack_list, 'coupon_count': coupon_count,
                                                           'joined_service': service, 'referee_name': member.full_name,
                                                           'joined_logo': service.config.logo})
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            Thread(target=lambda m: m.send(), args=(msg, )).start()

    if format == 'json':
        response = {'success': True, 'reward': reward, 'project_name': service.project_name,
                    'ikwen_page': service.get_profile_url()}
        return HttpResponse(json.dumps(response), content_type='application/json')
    else:
        query = '?joined=' + service.project_name_slug
        if join_coupon_count:
            query += '&join_coupon_count=%d' % join_coupon_count
        if referral_coupon_count:
            query += '&referral_coupon_count=%d' % referral_coupon_count
        next_url = service.get_profile_url() + query
        notice = _("You were added to our community. Thank you for joining us.")
        messages.success(request, notice)
        return HttpResponseRedirect(next_url)


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
    permission_id_list = []
    permission_ids = request.GET['permission_ids']
    if permission_ids:
        permission_id_list = permission_ids.split(',')
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

    if group.name == COMMUNITY:
        member.is_staff = False
    else:
        member.is_staff = True

    if group.name == SUDO:
        if not request.user.is_bao:
            return HttpResponse(json.dumps({'error': "Only Bao User can transfer member here."}), content_type='application/json')
        member.is_superuser = True
    else:
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

    group_fk_list = list(set(member_umbrella.group_fk_list))
    for grp in Group.objects.exclude(name=COMMUNITY):
        try:
            group_fk_list.remove(grp.id)
        except ValueError:
            pass
    group_fk_list.append(group.id)
    group_fk_list.sort()
    member_umbrella.group_fk_list = group_fk_list
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
