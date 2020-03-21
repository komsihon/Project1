from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.core.urlresolvers import reverse, NoReverseMatch
from django.utils import translation
from django.utils.formats import get_format

from ikwen.core.models import Module, Service

from ikwen.conf import settings as ikwen_settings
from ikwen.flatpages.models import FlatPage

from ikwen.core.views import IKWEN_BASE_URL


def project_settings(request):
    """
    Adds utility project url and ikwen base url context variable to the context.
    """
    key = 'project_settings'
    settings_var = cache.get(key)
    if settings_var:
        return settings_var

    console_uri = reverse('ikwen:console')
    if not getattr(settings, 'IS_IKWEN', False):
        console_uri = console_uri.replace('/ikwen', '')
        console_uri = console_uri.replace(getattr(settings, 'WSGI_SCRIPT_ALIAS', ''), '')

    # DEPRECATED ! agreement_page, legal_mentions_page, about_page defined below is now better
    agreement_url, legal_mentions_url = None, None
    try:
        agreement_url = reverse('flatpage', args=(FlatPage.AGREEMENT, ))
    except NoReverseMatch:
        pass
    try:
        legal_mentions_url = reverse('flatpage', args=(FlatPage.LEGAL_MENTIONS, ))
    except NoReverseMatch:
        pass

    agreement_page, legal_mentions_page, about_page = None, None, None
    try:
        agreement_page = FlatPage.objects.get(url=FlatPage.AGREEMENT).to_dict()
    except:
        pass
    try:
        legal_mentions_page = FlatPage.objects.get(url=FlatPage.LEGAL_MENTIONS).to_dict()
    except:
        pass
    try:
        about_page = FlatPage.objects.get(url='about').to_dict()
    except:
        pass

    service = Service.objects.get(pk=getattr(settings, 'IKWEN_SERVICE_ID'))
    config = service.config

    lang = translation.get_language()
    use_l10n = getattr(settings, 'USE_L10N', False)
    settings_var = {
        'settings': {
            'DEBUG': getattr(settings, 'DEBUG', False),
            'IS_IKWEN': getattr(settings, 'IS_IKWEN', False),
            'IS_UMBRELLA': getattr(settings, 'IS_UMBRELLA', False),
            'REGISTER_WITH_DOB': getattr(settings, 'REGISTER_WITH_DOB', False),
            'IKWEN_SERVICE_ID': getattr(settings, 'IKWEN_SERVICE_ID'),
            'IKWEN_BASE_URL': IKWEN_BASE_URL,
            'IKWEN_CONSOLE_URL': IKWEN_BASE_URL + console_uri,
            'IKWEN_MEDIA_URL': ikwen_settings.MEDIA_URL,
            'CLUSTER_MEDIA_URL': ikwen_settings.CLUSTER_MEDIA_URL,
            'AGREEMENT_URL': agreement_url,
            'LEGAL_MENTIONS_URL': legal_mentions_url,
            'PROJECT_URL': getattr(settings, 'PROJECT_URL', ''),
            'MEMBER_AVATAR': getattr(settings, 'MEMBER_AVATAR', 'ikwen/img/login-avatar.jpg'),
            'DECIMAL_SEPARATOR': get_format('DECIMAL_SEPARATOR', lang, use_l10n=use_l10n),
            'THOUSAND_SEPARATOR': get_format('THOUSAND_SEPARATOR', lang, use_l10n=use_l10n),
            'MEMBER_DETAIL_VIEW': getattr(settings, 'MEMBER_DETAIL_VIEW', None)
        },
        'service': service,
        'config': config,
        'lang': lang[:2],
        'year': datetime.now().year,
        'currency_code': config.currency_code,
        'currency_symbol': config.currency_symbol,
        'agreement_page': agreement_page,
        'legal_mentions_page': legal_mentions_page,
        'about_page': about_page,
    }
    cache_timeout = getattr(settings, 'CACHE_TIMEOUT', 5)
    cache.set(key, settings_var, cache_timeout * 60)
    return settings_var


def app_modules(request):
    """
    Grabs all active app modules
    """
    key = 'app_modules'
    modules = cache.get(key)
    if modules:
        return modules

    modules = {'app_modules': Module.objects.all().count() > 0}
    for obj in Module.objects.filter(is_active=True):
        modules[obj.slug] = obj.to_dict()

    cache_timeout = getattr(settings, 'CACHE_TIMEOUT', 5)
    cache.set(key, modules, cache_timeout * 60)
    return modules
