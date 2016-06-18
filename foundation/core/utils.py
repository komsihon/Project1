# -*- coding: utf-8 -*-
import re

import requests
from datetime import datetime
from django.conf import settings
from django.template import Context
from django.template.loader import get_template
from django.template.defaultfilters import urlencode


def to_dict(var):
    dict_var = var.__dict__
    for key in dict_var.keys():
        if key[0] == '_':
            del(dict_var[key])
        elif dict_var[key] is object:
            dict_var = to_dict(dict_var[key])
    return dict_var


def get_service_instance(from_umbrella=False):
    """
    Gets the Service currently running on this website in the Service
    local database or from foundation database.
    @param from_umbrella: if True search in umbrella database else search in local database
    @return:
    """
    from ikwen.foundation.core.backends import UMBRELLA
    from ikwen.foundation.core.models import Service
    service_id = getattr(settings, 'IKWEN_SERVICE_ID')
    return Service.objects.using(UMBRELLA).get(pk=service_id) if from_umbrella else Service.objects.get(pk=service_id)


def add_database_to_settings(database):
    """
    Adds a database connection to the global settings on the fly.
    That is equivalent to do the following in Django settings file:

    DATABASES = {
        'default': {
            'ENGINE': 'current_database_engine',
            'NAME': 'default_database',
            ...
        },
        'database': {
            'ENGINE': 'current_database_engine',
            'NAME': database,
            ...
        }
    }

    That connection is named 'database'
    @param database: name of the connection
    """
    DATABASES = getattr(settings, 'DATABASES')
    DATABASES[database] = {
        'ENGINE': 'django_mongodb_engine',
        'NAME': database,
    }
    setattr(settings, 'DATABASES', DATABASES)


def get_mail_content(subject, message, template_name, extra_context=None):
    service = get_service_instance()
    config = service.config
    html_template = get_template(template_name)
    context = {
        'website_url': service.url,
        'subject': subject,
        'company_name': config.company_name,
        'message': message,
        'slogan': config.slogan,
        'logo': config.logo,
        'banner': config.mail_banner,
        'signature': config.signature,
        'year': datetime.now().year
    }
    if extra_context:
        context.update(extra_context)
    d = Context(context)
    return html_template.render(d)


def send_sms(recipient, text):
    # label is made of 10 first characters of company name without space
    config = get_service_instance().config
    label = config.company_name.split(' ')[0][:10]
    label = urlencode(label)
    script_url = config.sms_api_script_url
    username = config.sms_api_username
    password = config.sms_api_password
    if script_url and username and password:
        url = script_url.replace('$username', username)\
            .replace('$password', password)\
            .replace('$label', urlencode(label))\
            .replace('$recipient', recipient)\
            .replace('$text', urlencode(text))
        requests.get(url)


def remove_special_words(s):
    s = re.sub("^the ", '', s)
    s = re.sub("^at ", '', s)
    s = re.sub("^in ", '', s)
    s = re.sub("^le ", '', s)
    s = re.sub("^la ", '', s)
    s = re.sub("^les ", '', s)
    s = re.sub("^l'", '', s)
    s = re.sub("^un ", '', s)
    s = re.sub("^une ", '', s)
    s = re.sub("^des ", '', s)
    s = re.sub("^d'", '', s)
    s = re.sub("^de ", '', s)
    s = re.sub("^du ", '', s)
    s = re.sub("^a ", '', s)
    s = re.sub("^et ", '', s)
    s = re.sub("^en ", '', s)
    s = s.replace(" the ", " ")\
        .replace(" at ", " ")\
        .replace(" in ", " ")\
        .replace(" of ", " ")\
        .replace(" le ", " ")\
        .replace(" la ", " ")\
        .replace(" les ", " ")\
        .replace(" l'", " ")\
        .replace(" un ", " ")\
        .replace(" une ", " ")\
        .replace(" des ", " ")\
        .replace(" d'", " ")\
        .replace(" de ", " ")\
        .replace(" du ", " ")\
        .replace(" a ", " ")\
        .replace(" et ", " ")\
        .replace(" en ", " ")\
        .replace(" 1", "")\
        .replace(" 2", "")\
        .replace(" 3", "")\
        .replace(" 4", "")\
        .replace(" 5", "")\
        .replace(" 6", "")\
        .replace(" 7", "")\
        .replace(" 8", "")\
        .replace(" 9", "")
    return s
