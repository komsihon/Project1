import json
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.auth.decorators import permission_required
from django.core.files import File
from django.urls import reverse
from django.forms.models import modelform_factory
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView

from ikwen.theming.admin import ThemeAdmin

from ikwen.core.utils import get_model_admin_instance, get_service_instance

from ikwen.theming.models import Theme

from ikwen.core.views import HybridListView


class ThemeList(HybridListView):
    template_name = 'theming/theme_list.html'
    model = Theme
    queryset = Theme.objects.filter(is_active=True)
    context_object_name = 'theme_list'

    def get(self, request, *args, **kwargs):
        theme_id = request.GET.get('theme_id')
        apply = request.GET.get('apply')
        if theme_id:
            theme = get_object_or_404(Theme, pk=theme_id)
            d = theme.to_dict()
            d['template_slug'] = theme.template.slug
            request.session['theme'] = d
            return HttpResponseRedirect(reverse('home'))
        if apply:
            theme_dict = request.session.get('theme')
            if theme_dict:
                theme_id = theme_dict['id']
                theme = get_object_or_404(Theme, pk=theme_id)
                config = get_service_instance().config
                config.theme = theme
                config.save()
                request.session['theme'] = None
        return super(ThemeList, self).get(request, *args, **kwargs)


class ConfigureTheme(TemplateView):
    template_name = 'theming/configure_theme.html'

    def get_context_data(self, **kwargs):
        context = super(ConfigureTheme, self).get_context_data(**kwargs)
        theme_id = kwargs.get('theme_id')  # May be overridden with the one from GET data
        theme_id = self.request.GET.get('theme_id', theme_id)
        theme = None
        if theme_id:
            theme = get_object_or_404(Theme, pk=theme_id)
        theme_admin = get_model_admin_instance(Theme, ThemeAdmin)
        ModelForm = modelform_factory(Theme, fields=('name', 'display', ))
        form = ModelForm(instance=theme)
        theme_form = helpers.AdminForm(form, list(theme_admin.get_fieldsets(self.request)),
                                          theme_admin.get_prepopulated_fields(self.request),
                                          theme_admin.get_readonly_fields(self.request, obj=theme))
        context['theme'] = theme
        context['model_admin_form'] = theme_form
        return context

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        theme_id = self.request.POST.get('theme_id')
        theme = None
        if theme_id:
            theme = get_object_or_404(Theme, pk=theme_id)
        theme_admin = get_model_admin_instance(Theme, ThemeAdmin)
        ModelForm = theme_admin.get_form(self.request)
        form = ModelForm(request.POST, instance=theme)
        if form.is_valid():
            image_url = request.POST.get('image_url')
            if image_url:
                if not theme.logo.name or image_url != theme.logo.url:
                    filename = image_url.split('/')[-1]
                    media_root = getattr(settings, 'MEDIA_ROOT')
                    media_url = getattr(settings, 'MEDIA_URL')
                    image_url = image_url.replace(media_url, '')
                    try:
                        with open(media_root + image_url, 'r') as f:
                            content = File(f)
                            destination = media_root + Theme.UPLOAD_TO + "/" + filename
                            theme.logo.save(destination, content)
                        os.unlink(media_root + image_url)
                    except IOError as e:
                        if getattr(settings, 'DEBUG', False):
                            raise e
                        return {'error': 'File failed to upload. May be invalid or corrupted image file'}
            theme.save()
            messages.success(request, 'Theme ' + _('successfully updated'))
            next_url = reverse('theming:theme_list')
            return HttpResponseRedirect(next_url)
        else:
            context = self.get_context_data(**kwargs)
            context['errors'] = form.errors
            return render(request, self.template_name, context)


@permission_required('accesscontrol.sudo')
def delete_logo(request, *args, **kwargs):
    service = get_service_instance()
    theme = service.config.theme
    try:
        os.unlink(theme.logo.path)
        theme.logo = ''
        theme.save()
    except:
        pass
    return HttpResponse(
        json.dumps({'success': True}),
        content_type='application/json'
    )
