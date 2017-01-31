
from django.conf.urls import patterns, url
from django.contrib.auth.decorators import permission_required
from ikwen.theming.views import ThemeList, ConfigureTheme

urlpatterns = patterns(
    '',
    url(r'^themes/$', permission_required('accesscontrol.sudo')(ThemeList.as_view()), name='theme_list'),
    url(r'^configure/(?P<theme_id>[-\w]+)/$', permission_required('accesscontrol.sudo')(ConfigureTheme.as_view()), name='configure_theme'),
)
