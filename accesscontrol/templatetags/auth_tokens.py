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
    url = uri
    if not getattr(settings, 'IS_IKWEN', False):
        from ikwen.core.views import IKWEN_BASE_URL
        uri = uri.replace('/ikwen', '')
        if getattr(settings, 'DEBUG', False):
            uri = uri.replace(getattr(settings, 'WSGI_SCRIPT_ALIAS'), '')
        url = IKWEN_BASE_URL + uri
    return url
