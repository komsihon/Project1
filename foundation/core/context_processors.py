from django.conf import settings
from django.core.urlresolvers import reverse
from ikwen.foundation.flatpages.models import FlatPage

from ikwen.foundation.core.views import IKWEN_BASE_URL


def project_settings(request):
    """
    Adds utility project url and ikwen base url context variable to the context.
    """
    console_uri = reverse('ikwen:console')
    if not getattr(settings, 'IS_IKWEN', False):
        console_uri = console_uri.replace('/ikwen', '')
        if getattr(settings, 'DEBUG', False):
            console_uri = console_uri.replace(getattr(settings, 'WSGI_SCRIPT_ALIAS'), '')
    return {
        'settings': {
            'IS_IKWEN': getattr(settings, 'IS_IKWEN', False),
            'IKWEN_SERVICE_ID': getattr(settings, 'IKWEN_SERVICE_ID'),
            'IKWEN_BASE_URL': IKWEN_BASE_URL,
            'IKWEN_CONSOLE_URL': IKWEN_BASE_URL + console_uri,
            'AGREEMENT_URL': reverse('flatpage', args=(FlatPage.AGREEMENT, )),
            'LEGAL_MENTIONS_URL': reverse('flatpage', args=(FlatPage.LEGAL_MENTIONS, )),
            'PROJECT_URL': getattr(settings, 'PROJECT_URL', ''),
            'MEMBER_AVATAR': getattr(settings, 'MEMBER_AVATAR', 'login-avatar.jpg')
        }
    }
