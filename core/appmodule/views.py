# -*- coding: utf-8 -*-
from django.contrib import messages
from django.contrib.admin import helpers
from django.forms.models import modelform_factory
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from ikwen.core.utils import get_model_admin_instance
from ikwen.core.admin import ModuleAdmin
from ikwen.core.models import Module
from ikwen.core.views import HybridListView, ChangeObjectBase


class ModuleList(HybridListView):
    model = Module
    ordering = ('name', )
    context_object_name = 'module_list'
    template_name = 'core/module_list.html'


class ChangeModule(ChangeObjectBase):
    model = Module
    model_admin = ModuleAdmin
    context_object_name = 'obj'
    template_name = 'core/change_module.html'


class ConfigureModule(TemplateView):
    model = Module
    model_admin = ModuleAdmin
    template_name = 'core/configure_module.html'

    def get_context_data(self, **kwargs):
        context = super(ConfigureModule, self).get_context_data(**kwargs)
        object_id = kwargs.get('object_id')  # May be overridden with the one from GET data
        module = get_object_or_404(Module, pk=object_id)
        config_model = module.config_model
        config_model_admin = import_by_path(module.config_model_admin)
        model_admin = get_model_admin_instance(config_model, config_model_admin)
        ModelForm = modelform_factory(config_model, fields=model_admin.fields)
        form = ModelForm(instance=module.config)
        config_form = helpers.AdminForm(form, list(model_admin.get_fieldsets(self.request)),
                                        model_admin.get_prepopulated_fields(self.request),
                                        model_admin.get_readonly_fields(self.request))
        context['module'] = module
        context['model_admin_form'] = config_form
        return context

    def post(self, request, *args, **kwargs):
        object_id = kwargs.get('object_id')
        module = get_object_or_404(self.model, pk=object_id)
        config_model = module.config_model
        config_model_admin = import_by_path(module.config_model_admin)
        model_admin = get_model_admin_instance(config_model, config_model_admin)
        config = module.config
        if config is None:
            config = module.config_model()
        model_form = model_admin.get_form(request)
        form = model_form(request.POST, instance=config)
        if form.is_valid():
            form.save()
            next_url = request.META['HTTP_REFERER']
            messages.success(request, 'Module configuration ' + _('successfully updated'))
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['errors'] = form.errors
            return render(request, self.template_name, context)
