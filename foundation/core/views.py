# -*- coding: utf-8 -*-
import json
from datetime import datetime
from django.core.exceptions import ImproperlyConfigured
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.template.defaultfilters import slugify
from django.utils import translation
from django.views.generic.base import TemplateView
from django.conf import settings
from django.views.generic.list import ListView

from ikwen.foundation.core.backends import UMBRELLA
from ikwen.foundation.core.models import Service, QueuedSMS
from ikwen.foundation.accesscontrol.models import Member

from ikwen.foundation.core.utils import get_service_instance


class BaseView(TemplateView):
    def get_context_data(self, **kwargs):
        context = super(BaseView, self).get_context_data(**kwargs)
        context['lang'] = translation.get_language()[:2]
        context['year'] = datetime.now().year
        context['config'] = get_service_instance().config
        return context


class HybridListView(ListView):
    """
    Extension of the django builtin :class:`django.views.generic.ListView`. This view is Hybrid because it can
    render HTML or JSON results for Ajax calls.

    :attr:search_field: Name of the default field it uses to filter Ajax requests. Defaults to *name*
    :attr:ordering: Tuple of model fields used to order object list when page is rendered in HTML
    :attr:ajax_ordering: Tuple of model fields used to order results of Ajax requests. It is similar to ordering of
    django admin
    """
    object_count = int(getattr(settings, 'HYBRID_LIST_OBJECT_COUNT', '24'))
    search_field = 'name'
    ordering = ('-created_on', )
    ajax_ordering = ('-created_on', )

    def get_queryset(self):
        if self.queryset is not None:
            queryset = self.queryset
            if hasattr(queryset, '_clone'):
                queryset = queryset._clone()
        elif self.model is not None:
            queryset = self.model._default_manager.all().order_by(*self.ordering)[:self.object_count]
        else:
            raise ImproperlyConfigured("'%s' must define 'queryset' or 'model'"
                                       % self.__class__.__name__)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(HybridListView, self).get_context_data(**kwargs)
        context.update(BaseView().get_context_data())
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('format') == 'json':
            queryset = self.model.objects
            start_date = self.request.GET.get('start_date')
            end_date = self.request.GET.get('end_date')
            if start_date and end_date:
                queryset = queryset.filter(created_on__range=(start_date, end_date))
            elif start_date:
                queryset = queryset.filter(created_on__gte=start_date)
            elif end_date:
                queryset = queryset.filter(created_on__lte=end_date)
            start = int(self.request.GET.get('start'))
            length = int(self.request.GET.get('length'))
            limit = start + length
            queryset = self.get_search_results(queryset)
            queryset = queryset.order_by(*self.ajax_ordering)[start:limit]
            response = [order.to_dict() for order in queryset]
            return HttpResponse(
                json.dumps(response),
                'content-type: text/json',
                **response_kwargs
            )
        else:
            return super(HybridListView, self).render_to_response(context, **response_kwargs)

    def get_search_results(self, queryset):
        """
        Default search function that filters the queryset based on the value of GET parameter q and the search_field
        :param queryset:
        :return:
        """
        search_term = self.request.GET.get('q')
        if search_term and len(search_term) >= 2:
            for word in search_term.split(' '):
                word = slugify(word)[:4]
                if word:
                    kwargs = {self.search_field + '__icontains': word}
                    queryset = queryset.filter(**kwargs)
                    if queryset.count() > 0:
                        break
        return queryset


class Console(BaseView):
    template_name = 'core/console.html'

    def get(self, request, *args, **kwargs):
        debug = getattr(settings, "DEBUG", False)
        if debug:
            return render(request=request, template_name=self.template_name)
        return HttpResponseRedirect('http://www.ikwen.com/forgottenPassword/')


class ServiceList(BaseView):
    template_name = 'core/service_list.html'

    def get_context_data(self, **kwargs):
        context = super(ServiceList, self).get_context_data(**kwargs)
        member = self.request.user
        databases = getattr(settings, 'DATABASES')
        if databases.get(UMBRELLA):
            context['services'] = Service.objects.using(UMBRELLA).filter(member=member).order_by('-since')
        else:
            context['services'] = Service.objects.filter(member=member).order_by('-since')
        # member.is_iao = True
        # app = Application(name="Hotspot")
        # context['services'] = [Service(app=app, project_name="Hotspot Geniusnet", url='http://ikwen.com/hotspot',
        #                                    version=Service.TRIAL, expiry='09-15, 2015')]
        return context


class ServiceDetail(BaseView):
    template_name = 'core/service_detail.html'

    def get_context_data(self, **kwargs):
        context = super(ServiceDetail, self).get_context_data(**kwargs)
        service_id = kwargs['service_id']
        databases = getattr(settings, 'DATABASES')
        if databases.get(UMBRELLA):
            context['service'] = Service.objects.using(UMBRELLA).get(pk=service_id)
        else:
            context['service'] = Service.objects.get(pk=service_id)
        context['billing_cycles'] = Service.BILLING_CYCLES_CHOICES
        return context


def before_paypal_set_checkout(request, *args, **kwargs):
    config = get_service_instance().config
    setattr(settings, 'PAYPAL_WPP_USER', config.paypal_user)
    setattr(settings, 'PAYPAL_WPP_PASSWORD', config.paypal_password)
    setattr(settings, 'PAYPAL_WPP_SIGNATURE', config.paypal_api_signature)
    # return set_ch


def pay_invoice(request, *args, **kwargs):
    member = request.user


def get_queued_sms(request, *args, **kwargs):
    email = request.GET['email']
    password = request.GET['password']
    qty = request.GET.get('quantity')
    if not qty:
        qty = 100
    user = Member.objects.using(UMBRELLA).get(email=email)
    if not user.check_password(password):
        response = {'error': 'E-mail or password not found.'}
    else:
        qs = QueuedSMS.objects.all()[:qty]
        response = [sms.to_dict() for sms in qs]
        qs.delete()
    return HttpResponse(json.dumps(response), 'content-type: text/json')


class PasswordResetInstructionsMail(BaseView):
    template_name = 'core/../accesscontrol/templates/accesscontrol/forgotten_password.html'

    def get(self, request, *args, **kwargs):
        return render(request=request, template_name=self.template_name)
        # debug = getattr(settings, "DEBUG", False)
        # if debug:
        #     return render(request=request, template_name=self.template_name)
        # return HttpResponseRedirect('http://www.ikwen.com/forgottenPassword/')


class Contact(BaseView):
    template_name = 'core/contact.html'


class WelcomeMail(BaseView):
    template_name = 'core/mails/welcome.html'


class BaseExtMail(BaseView):
    template_name = 'core/mails/base.html'


class ServiceExpired(BaseView):
    template_name = 'core/service_expired.html'
