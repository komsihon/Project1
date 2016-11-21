# -*- coding: utf-8 -*-
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.models import get_current_site
from django.core.mail import EmailMessage
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from ikwen.foundation.core.utils import get_mail_content, get_service_instance

from ikwen.foundation.accesscontrol.models import Member

__author__ = 'Kom Sihon'

from django import forms
from django.utils.translation import gettext_lazy as _
#from captcha.fields import ReCaptchaField


class MemberForm(forms.Form):
    username = forms.CharField(max_length=30)
    password = forms.CharField(max_length=30)
    password2 = forms.CharField(max_length=30)
    phone = forms.IntegerField(required=False)
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60)


class PasswordResetForm(forms.Form):
    email = forms.EmailField(label=_("Email"), max_length=254)

    def save(self, use_https=False, request=None):
        """
        Generates a one-use only link for resetting password and sends to the user.
        """
        config = get_service_instance().config
        email = self.cleaned_data["email"]
        active_users = Member.objects.filter(email__iexact=email, is_active=True)
        for member in active_users:
            # Make sure that no email is sent to a user that actually has
            # a password marked as unusable
            if not member.has_usable_password():
                continue
            current_site = get_current_site(request)
            domain = current_site.domain
            c = {
                'domain': domain,
                'uid': urlsafe_base64_encode(force_bytes(member.pk)),
                'member': member,
                'token': default_token_generator.make_token(member),
                'protocol': 'https' if use_https else 'http',
            }
            subject = _("Password reset instructions")
            html_content = get_mail_content(subject,
                                            template_name='accesscontrol/mails/password_reset_instructions.html',
                                            extra_context=c)
            contact_email = config.contact_email if config.contact_email else 'no-reply@ikwen.com'
            sender = '%s <%s>' % (config.company_name, contact_email)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            msg.send()


class SetPasswordForm(forms.Form):
    """
    A form that lets a user change set their password without entering the old
    password
    """
    error_messages = {
        'password_mismatch': _("The two password fields didn't match."),
    }
    new_password1 = forms.CharField(label=_("New password"),
                                    widget=forms.PasswordInput)
    new_password2 = forms.CharField(label=_("New password confirmation"),
                                    widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(SetPasswordForm, self).__init__(*args, **kwargs)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError(
                    self.error_messages['password_mismatch'],
                    code='password_mismatch',
                )
        return password2

    def save(self, commit=True):
        self.user.set_password(self.cleaned_data['new_password1'])
        if commit:
            self.user.save()
        return self.user
