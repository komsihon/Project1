from django.conf import settings
from django import template
from django.template.defaultfilters import stringfilter

from ikwen.core.utils import get_service_instance

register = template.Library()


@register.filter
@stringfilter
def strip_base_alias(uri):
    """
    Strips the WSGIScriptAlias at the beginning of a URL and
    the naked equivalent. This serves create valid URL from the
    go.ikwen.com weblet.
    Normally concatenating a Service.url with a reversed URL from that service will
    result in a wrong URL if we are accessing the service through its GO link.
    Let's say we have a Service such that:
     # Service.url = 'http://mybusiness.cm'
     # Service.go_url = 'http://go.ikwen.com/mybusiness
    If we do this from the GO link ...
        Service.url + reverse('ikwen:sign_in')  ==> 'http://mybusiness.cm/mybusiness/ikwen/signIn --> WRONG
    But ...
        Service.url + strip_base_alias(reverse('ikwen:sign_in')) ==> 'http://mybusiness.cm/ikwen/signIn --> GOOD !
    """
    base_alias = getattr(settings, 'WSGI_SCRIPT_ALIAS', '/' + get_service_instance().ikwen_name)
    if uri.startswith(base_alias):
        uri = uri[len(base_alias):]
    return uri
