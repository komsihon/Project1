from django.conf import settings

from ikwen.foundation.core.views import IKWEN_BASE_URL

__author__ = 'Kom Sihon'

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")


def base_urls(request):
    """
    Adds utility project url and ikwen base url context variable to the context.
    """
    return {
        'base_urls': {
            'IKWEN': IKWEN_BASE_URL,
            'PROJECT': getattr(settings, 'PROJECT_URL', '')
        }
    }
