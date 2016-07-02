# -*- coding: utf-8 -*-

__author__ = 'Kom Sihon'

from django import forms
#from captcha.fields import ReCaptchaField


class MemberForm(forms.Form):
    username = forms.CharField(max_length=30)
    password = forms.CharField(max_length=30)
    password2 = forms.CharField(max_length=30)
    phone = forms.IntegerField()
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60)


class PasswordResetForm(forms.Form):
    username = forms.CharField()
    email = forms.EmailField()
    #captcha = ReCaptchaField()


