# -*- coding: utf-8 -*-

__author__ = 'Kom Sihon'

from django import forms


class ChangeServiceForm(forms.Form):
    billing_cycle = forms.CharField(max_length=30)
    monthly_cost = forms.IntegerField()
