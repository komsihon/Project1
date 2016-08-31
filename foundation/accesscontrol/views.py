# -*- coding: utf-8 -*-
import json
from threading import Thread

from ajaxuploader.views import AjaxFileUploader
from bson import ObjectId
from django.conf import settings
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.core.validators import validate_email
from django.http.response import HttpResponseRedirect, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.template import Context
from django.template.defaultfilters import urlencode
from django.template.loader import get_template
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from ikwen.foundation.accesscontrol.utils import is_collaborator

from ikwen.foundation.accesscontrol.backends import UMBRELLA

from ikwen.foundation.core.models import Service, Application, ConsoleEvent, ConsoleEventType
from permission_backend_nonrel.models import UserPermissionList
from permission_backend_nonrel.utils import add_permission_to_user, add_user_to_group

from ikwen.foundation.accesscontrol.forms import MemberForm, PasswordResetForm, SetPasswordForm
from ikwen.foundation.accesscontrol.models import Member, AccessRequest, COLLABORATION_REQUEST_EVENT, \
    SERVICE_REQUEST_EVENT, SUDO, ACCESS_GRANTED_EVENT
from ikwen.foundation.core.utils import get_service_instance, get_mail_content, add_database_to_settings, add_event
from ikwen.foundation.core.views import BaseView, HybridListView


def register(request, *args, **kwargs):
    form = MemberForm(request.POST)
    if form.is_valid():
        username = form.cleaned_data['username']
        phone = form.cleaned_data.get('phone', '')
        email = form.cleaned_data.get('email', '')
        first_name = form.cleaned_data.get('first_name')
        last_name = form.cleaned_data.get('last_name')
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
                    msg = _("You already created an Ikwen account with this phone on %s. Use it to login." % member.entry_service.project_name)
                    existing_account_url = reverse('ikwen:sign_in') + "?existingPhone=yes&msg=%s&%s" % (msg, query_string)
                    return HttpResponseRedirect(existing_account_url.strip('&'))
            password = form.cleaned_data['password']
            password2 = form.cleaned_data['password2']
            if password != password2:
                return HttpResponseRedirect(reverse('ikwen:sign_in') + "?passwordMismatch=yes&" + query_string)
            Member.objects.create_user(username=username, phone=phone, email=email, password=password,
                                       first_name=first_name, last_name=last_name)
            member = authenticate(username=username, password=password)
            login(request, member)
            events = getattr(settings, 'IKWEN_REGISTER_EVENTS', ())
            for path in events:
                event = import_by_path(path)
                event(request, *args, **kwargs)
            send_welcome_email(member)
            next_url = request.REQUEST.get('next')
            if next_url:
                # Remove next_url from the original query_string
                query_string = query_string.replace('next=%s' % urlencode(next_url), '').strip('&')
            else:
                next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', 'ikwen:console')
                next_url = reverse(next_url_view)
            return HttpResponseRedirect(next_url + "?" + query_string)
        else:
            msg = _("You already created an Ikwen account with this username on %s. Use it to login." % member.entry_service.project_name)
            existing_account_url = reverse('ikwen:sign_in') + "?existingUsername=yes&msg=%s&%s" % (msg, query_string)
            return HttpResponseRedirect(existing_account_url.strip('&'))
    else:
        context = {'register_form': form, 'service': get_service_instance()}
        return render(request, 'accesscontrol/sign_in.html', context)


class SignIn(BaseView):
    template_name = 'accesscontrol/sign_in.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            next_url = request.REQUEST.get('next')
            if next_url:
                return HttpResponseRedirect(next_url)
            next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', 'ikwen:console')
            return HttpResponseRedirect(reverse(next_url_view))
        return render(request, self.template_name, {'service': get_service_instance()})

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def post(self, request, *args, **kwargs):
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            member = form.get_user()
            login(request, member)
            events = getattr(settings, 'IKWEN_LOGIN_EVENTS', ())
            for path in events:
                event = import_by_path(path)
                event(request, *args, **kwargs)
            query_string = request.META.get('QUERY_STRING')
            next_url = request.REQUEST.get('next')
            if next_url:
                # Remove next_url from the original query_string
                query_string = query_string.replace('next=%s' % urlencode(next_url), '').strip('&')
            else:
                next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL')
                if next_url_view:
                    next_url = reverse(next_url_view)
                else:
                    if member.is_iao:
                        next_url = reverse('admin_home')
                    else:
                        next_url = reverse('ikwen:console')
            if query_string:
                return HttpResponseRedirect(next_url + "?" + query_string)
            return HttpResponseRedirect(next_url)
        else:
            context = {'login_form': form}
            if form.errors:
                error_message = getattr(settings, 'IKWEN_LOGIN_FAILED_ERROR_MSG',
                                        _("Invalid username/password or account inactive"))
                context['error_message'] = error_message
                context['service'] = get_service_instance()
            return render(request, 'accesscontrol/sign_in.html', context)


class ForgottenPassword(BaseView):
    template_name = 'accesscontrol/forgotten_password.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {'service': get_service_instance()})

    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        # TODO: Handle mail sending failure
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            opts = {
                'use_https': request.is_secure(),
                'request': request,
            }
            form.save(**opts)
            return HttpResponseRedirect(reverse('ikwen:forgotten_password') + '?success=yes')


class SetNewPassword(BaseView):
    """
    View that checks the hash in a password reset link and presents a
    form for entering a new password.
    """
    template_name = 'accesscontrol/set_new_password.html'

    def get_member(self, uidb64, token):
        assert uidb64 is not None and token is not None  # checked by URLconf
        try:
            uid = urlsafe_base64_decode(uidb64)
            member = Member.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, Member.DoesNotExist):
            member = None
        return member

    def get(self, request, *args, **kwargs):
        uidb64, token = kwargs['uidb64'], kwargs['token']
        member = self.get_member(uidb64, token)
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
    def post(self, request, uidb64, token, *args, **kwargs):
        member = self.get_member(uidb64, token)
        form = SetPasswordForm(member, request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('ikwen:sign_in') + '?successPasswordReset=yes')


def send_welcome_email(member):
    """
    Sends welcome email upon registration of a Member. The default message can
    be edited from the admin in Config.welcome_message
    Following strings in the message will be replaced as such:

    $member_name  -->  member.first_name

    @param member: Member object to whom message is sent
    """
    config = get_service_instance().config
    subject = _("Welcome to %s" % config.company_name)
    if config.welcome_message:
        message = config.welcome_message.replace('$member_name', member.first_name)
    else:
        message = _("Welcome %(member_name)s,<br><br>"
                    "Your registration was successful and you can now enjoy our service.<br><br>"
                    "Thank you." % {'member_name': member.first_name})
    html_content = get_mail_content(subject, message, template_name='accesscontrol/mails/welcome.html')
    sender = '%s <%s>' % (config.company_name, config.contact_email)
    msg = EmailMessage(subject, html_content, sender, [member.email])
    msg.content_subtype = "html"
    msg.send()


@login_required
def account_setup(request, template_name='accesscontrol/account.html', extra_context=None):
    context = {}
    if extra_context is not None:
        # extra_context can be a dictionary or a callable that returns a dictionary
        if type(extra_context).__name__ == 'function':
            context.update(extra_context(request))
        else:
            context.update(extra_context)
    return render(request, template_name, context)


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
    member.save()
    response = {'message': _('Your information were successfully updated.')}
    return HttpResponse(json.dumps(response), content_type='application/json')


@login_required
def update_password(request, *args, **kwargs):
    """
    View that changes the password of the user when he intentionally
    decides to do so from his account management panel.
    """
    member = request.user
    password = request.GET.get('password')
    if check_password(password, member.password):
        password1 = request.GET.get('password1')
        password2 = request.GET.get('password2')
        response = {'message': _('Your password was successfully updated.')}  # Default is everything going well
        if password1:
            if password1 != password2:
                response = {'error': _("Passwords don't match.")}
            else:
                member.set_password(password1)
                member.save()
                response = {'message': _('Your password was successfully updated.')}
    else:
        response = {'error': _("The current password is incorrect!")}
    return HttpResponse(
        json.dumps(response),
        content_type='application/json'
    )


class Profile(BaseView):
    template_name = 'accesscontrol/profile.html'

    def get_context_data(self, **kwargs):
        member_id = kwargs.get('member_id', None)
        if member_id:
            member = Member.objects.using(UMBRELLA).get(pk=member_id)
        else:
            member = self.request.user

        context = super(Profile, self).get_context_data(**kwargs)
        if self.request.user.is_authenticated() and self.request.user.is_iao:
            rqs = []
            for rq in AccessRequest.objects.using(UMBRELLA).filter(member=member, status=AccessRequest.PENDING):
                if rq.service in self.request.user.collaborates_on:
                    add_database_to_settings(rq.service.database)
                    groups = Group.objects.using(rq.service.database).exclude(name=SUDO).order_by('name')
                    rqs.append({'rq': rq, 'groups': groups})
            context['access_requests'] = rqs
        context['profile_name'] = member.full_name
        context['profile_email'] = member.email
        context['profile_phone'] = member.phone
        context['profile_gender'] = member.gender
        context['profile_photo_url'] = member.photo.small_url if member.photo.name else ''
        context['profile_cover_url'] = member.cover_image.url if member.cover_image.name else ''
        context['member'] = member
        return context


class CompanyProfile(BaseView):
    template_name = 'accesscontrol/profile.html'

    def get_context_data(self, **kwargs):
        app = Application.objects.get(slug=kwargs['app_slug'])
        project_name_slug = kwargs['project_name_slug']
        service = Service.objects.get(app=app, project_name_slug=project_name_slug)
        config = service.config
        context = super(CompanyProfile, self).get_context_data(**kwargs)
        context['is_company'] = True
        context['service'] = service  # Updates the service context defined in BaseView
        context['config'] = config
        context['profile_name'] = service.project_name
        context['profile_email'] = config.contact_email
        context['profile_phone'] = config.contact_phone
        context['profile_address'] = config.address
        context['profile_city'] = config.city
        context['profile_photo_url'] = config.logo.url if config.logo.name else ''
        context['profile_cover_url'] = config.cover_image.url if config.cover_image.name else ''
        try:
            AccessRequest.objects.using(UMBRELLA).get(member=self.request.user, service=service,
                                                      type=AccessRequest.COLLABORATION_REQUEST, status=AccessRequest.PENDING)
            context['is_collabo'] = True
        except:
            is_collabo = is_collaborator(self.request.user, service)
            context['is_collabo'] = is_collabo
        try:
            add_database_to_settings(service.database)
            Member.objects.using(service.database)
            context['is_customer'] = True
        except Member.DoesNotExist:
            context['is_customer'] = False
        return context


class Collaborators(HybridListView):
    template_name = 'accesscontrol/collabos.html'
    context_object_name = 'nonrel_perm_list'
    ordering = ('-id', )
    ajax_ordering = ('-id', )

    def get_queryset(self):
        group_name = self.request.GET.get('group_name')
        if group_name:
            group_id = Group.objects.get(name=group_name).id
        else:
            group_id = Group.objects.exclude(name=SUDO).order_by('name')[0].id
        return UserPermissionList.objects.raw_query({'group_fk_list': {'$elemMatch': {'$eq': group_id}}})

    def get_context_data(self, **kwargs):
        context = super(Collaborators, self).get_context_data(**kwargs)
        context['groups'] = Group.objects.exclude(name=SUDO).order_by('name')
        context['sudo_group'] = Group.objects.get(name=SUDO)
        context['permissions'] = Permission.objects.filter(codename__startswith='ik_')
        return context


@permission_required('accesscontrol.sudo')
def list_collaborators(request, *args, **kwargs):
    q = request.GET['q']
    if len(q) < 2:
        return
    q = q[:4]
    service = get_service_instance()
    queryset = Member.objects.raw_query({'collaborates_on': {'$elemMatch': {'id': ObjectId(service.id)}}})
    # TODO: Substring search directly in the raw query rather than in the list comprehension
    members = [member.to_dict() for member in queryset if q in member.full_name.lower()]
    return HttpResponse(json.dumps(members), content_type='application/json')


@login_required  # The user must be logged in to ikwen and not his own service, this view runs on ikwen
def request_access(request, *args, **kwargs):
    service_id = request.GET['service_id']
    access_type = request.GET['access_type']
    format = request.GET.get('format')
    service = Service.objects.using(UMBRELLA).get(pk=service_id)
    member = Member.objects.using(UMBRELLA).get(pk=request.user.id)
    rq = AccessRequest.objects.using(UMBRELLA).create(member=member, service=service, type=access_type)
    if access_type == AccessRequest.COLLABORATION_REQUEST:
        event_type = COLLABORATION_REQUEST_EVENT
    else:
        event_type = SERVICE_REQUEST_EVENT
    add_event(service, service.member, ConsoleEvent.BUSINESS, event_type, 'accesscontrol.AccessRequest', rq.id)
    subject = _("Collaboration access request")
    message = _("Hi %(member_name)s,<br><br>%(collabo_name)s requested access to collaborate with you on "
                "<b>%(project_name)s</b>.<br><br>" % {'member_name': service.member.first_name,
                                                      'collabo_name': member.full_name,
                                                      'project_name': service.project_name})
    html_content = get_mail_content(subject, message, template_name='core/mails/notice.html',
                                    extra_context={'cta_text': _("View"),
                                                   'cta_url': 'http://www.ikwen.com' + reverse('ikwen:profile', args=(member.id, ))})
    sender = '%s <%s>' % ('IKWEN', 'contact@ikwen.com')
    msg = EmailMessage(subject, html_content, sender, [service.member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg, )).start()
    if format == 'json':
        return HttpResponse(json.dumps({'success': True}), content_type='application/json')
    else:
        next_url = request.GET['next_url']
        return HttpResponseRedirect(next_url + '?success=yes')


@login_required   # The user must be logged in to ikwen and not his own service, this view runs on ikwen
def grant_access_to_collaborator(request, *args, **kwargs):
    if not request.user.is_iao:
        # TODO: Verify that IA0 is actually the owner of the service for which the request is made
        return HttpResponseForbidden('Only IA0 May grant access')
    # TODO: Work on access revocation also
    request_id = request.GET['request_id']
    group_id = request.GET['group_id']
    event = ConsoleEvent.objects.using(UMBRELLA).get(member=request.user, object_id=request_id)
    rq = AccessRequest.objects.using(UMBRELLA).get(pk=request_id)
    rq.member.collaborates_on.append(rq.service)
    rq.member.save()
    database = rq.service.database
    add_database_to_settings(database)
    group = Group.objects.using(database).get(pk=group_id)
    rq.member.save(using=database)
    member = Member.objects.using(database).get(pk=rq.member.id)  # Reload from local database to avoid database router error
    obj_list, created = UserPermissionList.objects.using(database).get_or_create(user=member)
    obj_list.group_fk_list.append(group.id)
    obj_list.save(using=database)
    rq.status = AccessRequest.CONFIRMED
    rq.group_name = group.name
    rq.save()
    event.status = ConsoleEvent.PROCESSED
    event.save()
    new_event = add_event(rq.service, rq.member, ConsoleEvent.BUSINESS,
                          ACCESS_GRANTED_EVENT, 'accesscontrol.AccessRequest', rq.id)
    new_event.status = ConsoleEvent.PROCESSED
    new_event.save()
    subject = _("Collaboration access granted")
    message = _("Hi %(member_name)s,<br><br>You were granted access to collaborate on <b>%(project_name)s</b> as "
                "<b>%(group_name)s</b>.<br><br>" % {'member_name': rq.member.first_name,
                                                    'project_name': rq.service.project_name,
                                                    'group_name': rq.group_name})
    html_content = get_mail_content(subject, message, template_name='core/mails/notice.html',
                                    extra_context={'cta_text': _("Join"),
                                                   'cta_url': rq.service.admin_url})
    sender = '%s <%s>' % ('IKWEN', 'contact@ikwen.com')
    msg = EmailMessage(subject, html_content, sender, [rq.member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg, )).start()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


@permission_required('accesscontrol.sudo')
def set_collaborator_permissions(request, *args, **kwargs):
    permission_ids = request.GET['permission_ids']
    member_id = request.GET['member_id']
    member = Member.objects.get(pk=member_id)
    obj = UserPermissionList.objects.get(user=member)
    obj.permission_list = []
    obj.permission_fk_list = []
    obj.save()
    if permission_ids:
        for perm_id in permission_ids.split(','):
            perm = Permission.objects.get(pk=perm_id)
            add_permission_to_user(perm, member)
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


@permission_required('accesscontrol.sudo')
def move_collaborator_to_group(request, *args, **kwargs):
    group_id = request.GET['group_id']
    member_id = request.GET['member_id']
    group = Group.objects.get(pk=group_id)
    member = Member.objects.get(pk=member_id)
    obj = UserPermissionList.objects.get(user=member)
    obj.permission_list = []
    obj.permission_fk_list = []
    obj.group_fk_list = []
    obj.save()
    add_user_to_group(member,  group)
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


@permission_required('accesscontrol.sudo')
def toggle_member(request, *args, **kwargs):
    member_id = request.GET['member_id']
    member = Member.objects.get(pk=member_id)
    if member.is_active:
        member.is_active = False
    else:
        member.is_active = True
    member.save()
    return HttpResponse(json.dumps({'success': True}), content_type='application/json')


def render_collaboration_request_event(access_request):
    html_template = get_template('accesscontrol/events/collaboration_request.html')
    context = {'rq': access_request}
    d = Context(context)
    return html_template.render(d)


def render_access_granted_event(access_request):
    html_template = get_template('accesscontrol/events/access_granted.html')
    context = {'rq': access_request}
    d = Context(context)
    return html_template.render(d)
