from django.conf import settings

__author__ = 'Kom Sihon'

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")


def project_url(request):
    """
    Adds PROJECT_URL context variable to the context.
    """
    return {'PROJECT_URL': settings.PROJECT_URL}