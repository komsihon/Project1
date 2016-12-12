# -*- coding: utf-8 -*-
import json

from django.contrib.admin import helpers
from django.core.urlresolvers import reverse
from django.forms.models import modelform_factory
from django.http.response import HttpResponseRedirect, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from ikwen.foundation.core.views import BaseView, HybridListView

from ikwen.foundation.flatpages.admin import FlatPageAdmin

from ikwen.foundation.accesscontrol.templatetags.auth_tokens import append_auth_tokens
from ikwen.foundation.flatpages.models import FlatPage
from ikwen.foundation.core.utils import get_model_admin_instance


class FlatPageList(HybridListView):
    model = FlatPage
    context_object_name = 'flatpage_list'
    template_name = 'flatpages/flatpage_list.html'

    def render_to_response(self, context, **response_kwargs):
        action = self.request.GET.get('action')
        if action == 'delete':
            selection = self.request.GET['selection'].split(',')
            for page_id in selection:
                page = FlatPage.objects.get(pk=page_id)
                page.delete()
            response = {'message': "%d page(s) deleted." % len(selection)}
            return HttpResponse(json.dumps(response))
        return super(FlatPageList, self).render_to_response(context, **response_kwargs)


class ChangeFlatPage(BaseView):
    template_name = 'flatpages/change_flatpage.html'

    def get_context_data(self, **kwargs):
        context = super(ChangeFlatPage, self).get_context_data(**kwargs)
        page_id = kwargs.get('page_id')  # May be overridden with the one from GET data
        page_id = self.request.GET.get('page_id', page_id)
        page = None
        if page_id:
            page = get_object_or_404(FlatPage, pk=page_id)
        category_admin = get_model_admin_instance(FlatPage, FlatPageAdmin)
        ModelForm = modelform_factory(FlatPage, fields=('title', 'content', 'registration_required'))
        form = ModelForm(instance=page)
        category_form = helpers.AdminForm(form, list(category_admin.get_fieldsets(self.request)),
                                          category_admin.get_prepopulated_fields(self.request))
        context['page'] = page
        context['model_admin_form'] = category_form
        return context

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        page_id = self.request.POST.get('page_id')
        page = None
        if page_id:
            page = get_object_or_404(FlatPage, pk=page_id)
        category_admin = get_model_admin_instance(FlatPage, FlatPageAdmin)
        ModelForm = category_admin.get_form(self.request)
        form = ModelForm(request.POST, instance=page)
        if form.is_valid():
            title = form.cleaned_data['title']
            content = form.cleaned_data['content']
            if page is None:
                page = FlatPage()
                page.url = slugify(title)
            else:
                if page.url != FlatPage.AGREEMENT and page.url != FlatPage.LEGAL_MENTIONS:
                    page.url = slugify(title)
            page.title = title
            page.content = content
            page.registration_required = True if request.POST.get('registration_required') else False
            page.save()
            if page_id:
                next_url = reverse('ikwen:change_flatpage', args=(page_id, )) + '?success=yes'
            else:
                next_url = reverse('ikwen:change_flatpage') + '?success=yes'
            next_url = append_auth_tokens(next_url, request)
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['errors'] = form.errors
            return render(request, self.template_name, context)


class FlatPageView(BaseView):

    def get(self, request, *args, **kwargs):
        url = kwargs['url']
        flatpage = get_object_or_404(FlatPage, url=url)
        context = self.get_context_data(**kwargs)
        context['page'] = flatpage
        template_name = flatpage.template_name if flatpage.template_name else 'flatpages/flatpage_view.html'
        return render(request, template_name, context)
