
from django.urls import path
from django.contrib.auth.decorators import permission_required
from ikwen.theming.views import ThemeList, ConfigureTheme, delete_logo

urlpatterns = [
    path('themes/', permission_required('accesscontrol.sudo')(ThemeList.as_view()), name='theme_list'),
    path('configure/<theme_id>/', permission_required('accesscontrol.sudo')(ConfigureTheme.as_view()), name='configure_theme'),
    path('delete_logo', delete_logo, name='delete_logo'),
]
