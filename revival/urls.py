
from django.conf.urls import patterns, url
from django.contrib.auth.decorators import permission_required

from ikwen.revival.views import ProfileTagList, ChangeProfileTag

urlpatterns = patterns(
    '',
    url(r'^profileTags/$', permission_required('accesscontrol.sudo')(ProfileTagList.as_view()), name='profiletag_list'),
    url(r'^changeProfileTag/$', permission_required('accesscontrol.sudo')(ChangeProfileTag.as_view()), name='change_profiletag'),
    url(r'^changeProfileTag/(?P<object_id>[-\w]+)$', permission_required('accesscontrol.sudo')(ChangeProfileTag.as_view()), name='change_profiletag'),
)
