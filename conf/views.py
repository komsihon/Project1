# -*- coding: utf-8 -*-
from django.http.response import HttpResponseRedirect

__author__ = 'komsihon'

from django.views.generic import TemplateView


class Home(TemplateView):
    template_name = 'home.html'