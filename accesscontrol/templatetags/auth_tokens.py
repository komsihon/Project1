from django.conf import settings

from ikwen.accesscontrol.middleware import UID_B64, TOKEN
from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()


@register.filter
@stringfilter
def append_auth_tokens(url, request):
    """
    Given a base 64 uid and a token, returns the matching :class:`ikwen.foundation.core.models.Member`
    if they are correct, else return None
    """
    uidb64 = request.GET.get(UID_B64)
    token = request.GET.get(TOKEN)
    if not uidb64 or not token:
        return url
    from urlparse import urlparse
    o = urlparse(url)
    if o.query:
        return url + '&%s=%s&%s=%s' % (UID_B64, uidb64, TOKEN, token)
    else:
        return url + '?%s=%s&%s=%s' % (UID_B64, uidb64, TOKEN, token)


@register.filter
@stringfilter
def ikwenize(uri):
    """
    Returns the equivalent URL on IKWEN website
    Ex: ikwenize('/console') = 'http://www.ikwen.com/console'
    """
    if not getattr(settings, 'IS_UMBRELLA', False):
        uri = uri.replace('/ikwen', '')
    script_alias = getattr(settings, 'WSGI_SCRIPT_ALIAS', '')
    uri = uri[len(script_alias):]
    from ikwen.core.views import IKWEN_BASE_URL
    url = IKWEN_BASE_URL + uri
    return url
