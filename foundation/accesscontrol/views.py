# -*- coding: utf-8 -*-
import json
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.template.defaultfilters import urlencode
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_by_path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from ikwen.foundation.core.views import BaseView

from ikwen.foundation.core.forms import MemberForm
from ikwen.foundation.accesscontrol.models import Member
from django.utils.translation import gettext as _

from ikwen.foundation.core.utils import get_service_instance, get_mail_content


def register(request, *args, **kwargs):
    form = MemberForm(request.POST)
    if form.is_valid():
        username = form.cleaned_data['username']
        phone = form.cleaned_data['phone']
        email = form.cleaned_data.get('email')
        first_name = form.cleaned_data.get('first_name')
        last_name = form.cleaned_data.get('last_name')
        query_string = request.META.get('QUERY_STRING')
        try:
            member = Member.objects.get(email=email)
        except Member.DoesNotExist:
            try:
                member = Member.objects.get(phone=phone)
            except Member.DoesNotExist:
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
                    next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
                    next_url = reverse(next_url_view)
                return HttpResponseRedirect(next_url + "?" + query_string)
            else:
                msg = _("You already created an Ikwen account with this phone on %s. Use it to login." % member.entry_service.project_name)
                existing_account_url = reverse('ikwen:sign_in') + "?existingPhone=yes&msg=%s&%s" % (msg, query_string)
                return HttpResponseRedirect(existing_account_url.strip('&'))
        else:
            msg = _("You already created an Ikwen account with this email on %s. Use it to login." % member.entry_service.project_name)
            existing_account_url = reverse('ikwen:sign_in') + "?existingEmail=yes&msg=%s&%s" % (msg, query_string)
            return HttpResponseRedirect(existing_account_url.strip('&'))
    else:
        context = {'register_form': form}
        return render(request, 'accesscontrol/sign_in.html', context)


class SignIn(BaseView):
    template_name = 'accesscontrol/sign_in.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            next_url = request.REQUEST.get('next')
            if next_url:
                return HttpResponseRedirect(next_url)
            next_url_view = getattr(settings, 'LOGIN_REDIRECT_URL', 'home')
            return HttpResponseRedirect(reverse(next_url_view))
        return render(request=request, template_name=self.template_name)

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
                        next_url = reverse('ikwen:service_list')
                    else:
                        next_url = reverse('ikwen:account_setup')
            if query_string:
                return HttpResponseRedirect(next_url + "?" + query_string)
            return HttpResponseRedirect(next_url)
        else:
            context = {'login_form': form}
            if form.errors:
                error_message = getattr(settings, 'IKWEN_LOGIN_FAILED_ERROR_MSG',
                                        _("Invalid login/password or account inactive"))
                context['error_message'] = error_message
            return render(request, 'accesscontrol/sign_in.html', context)


class ForgottenPassword(BaseView):
    template_name = 'accesscontrol/forgotten_password.html'

    def get(self, request, *args, **kwargs):
        debug = getattr(settings, "DEBUG", False)
        if debug:
            return render(request=request, template_name=self.template_name)
        return HttpResponseRedirect('http://www.ikwen.com/forgottenPassword/')


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
    html_content = get_mail_content(subject, message, template_name='core/mails/welcome.html')
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
    # debug = getattr(settings, "DEBUG", False)
    # if debug:
    #     return render(request=request, template_name=self.template_name)
    # return HttpResponseRedirect('http://www.ikwen.com/accountSetup/')


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


class PasswordResetInstructionsMail(BaseView):
    template_name = 'accesscontrol/forgotten_password.html'

    def get(self, request, *args, **kwargs):
        return render(request=request, template_name=self.template_name)
        # debug = getattr(settings, "DEBUG", False)
        # if debug:
        #     return render(request=request, template_name=self.template_name)
        # return HttpResponseRedirect('http://www.ikwen.com/forgottenPassword/')