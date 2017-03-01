from django.conf import settings
from django.shortcuts import render
from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.models import Application, Service

from ikwen.core.views import BaseView, HybridListView


class Dashboard(BaseView):
    pass


class ApplicationList(HybridListView):
    template_name = 'partnership/application_list.html'
    model = Application
    context_object_name = 'application_list'

    def get_queryset(self):
        return Application.objects.exclude(deployment_url_name='')


class ApplicationDetail(BaseView):
    pass


class ServiceList(HybridListView):
    template_name = 'partnership/service_list.html'
    model = Service
    context_object_name = 'service_list'


class ChangeService(BaseView):
    pass
