from django.shortcuts import render
from ikwen.core.views import BaseView, HybridListView


class Dashboard(BaseView):
    pass


class ApplicationList(HybridListView):
    pass


class ApplicationDetail(BaseView):
    pass


class ServiceList(HybridListView):
    pass


class ChangeService(BaseView):
    pass
