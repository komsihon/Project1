# -*- coding: utf-8 -*-
import re
from copy import deepcopy
from datetime import datetime, timedelta

import requests
from ajaxuploader.backends.local import LocalUploadBackend
from django.conf import settings
from django.core.cache import cache
from django.db.models import F, Model
from django.db.models.loading import get_model
from django.template import Context
from django.template.defaultfilters import urlencode, slugify
from django.template.loader import get_template
from django.utils import timezone


def to_dict(var):
    try:
        dict_var = deepcopy(var).__dict__
    except AttributeError:
        return var
    for key in dict_var.keys():
        if key[0] == '_' or type(dict_var[key]) is datetime:
            del(dict_var[key])
        elif type(dict_var[key]) is list:
            try:
                dict_var[key] = [item.to_dict() for item in dict_var[key]]
            except AttributeError:
                dict_var[key] = [to_dict(item) for item in dict_var[key]]
        elif isinstance(dict_var[key], Model):
            try:
                dict_var[key] = dict_var[key].to_dict()
            except AttributeError:
                dict_var[key] = to_dict(dict_var[key])
    return dict_var


def strip_datetime_fields(obj):
    """
    Set datetime fields to None in obj. The purpose of this is to make
    the object JSON serializable for django sessions.
    """
    dict_var = deepcopy(obj).__dict__
    for key in dict_var:
        if type(dict_var[key]) is datetime:
            obj.__dict__[key] = None



def get_config_model():
    """
    Returns the Config model class for the current Service.
    """
    config_model_name = getattr(settings, 'IKWEN_CONFIG_MODEL', 'core.Config')
    app_label = config_model_name.split('.')[0]
    model = config_model_name.split('.')[1]
    return get_model(app_label, model)


def get_service_instance(using='default'):
    """
    Gets the Service currently running on this website in the Service
    local database or from foundation database.
    @param using: database alias to search in
    @return:
    """
    from ikwen.foundation.core.models import Service
    service_id = getattr(settings, 'IKWEN_SERVICE_ID')
    service = cache.get(service_id + ':' + using)
    if service:
        return service
    service = Service.objects.using(using).get(pk=service_id)
    cache.set(service_id + ':' + using, service)
    return service


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
    if DATABASES.get(database) is None:
        DATABASES[database] = {
            'ENGINE': 'django_mongodb_engine',
            'NAME': database,
        }
    setattr(settings, 'DATABASES', DATABASES)


def add_dumb_column(database, table, column):
    """
    Add a VARCHAR DEFAULT NULL column to a relational database. The purpose of this function is to
    create replacement column for fields of type ListField or EmbeddedModelField that are not created
    in relational stores when running syncdb.
    """
    import sqlite3
    DATABASES = getattr(settings, 'DATABASES')
    db = DATABASES.get(database)
    engine = db['ENGINE']
    name = db['NAME']
    script = "ALTER TABLE %s ADD %s VARCHAR(10) DEFAULT NULL" % (table, column)
    if engine == 'django.db.backends.sqlite3':
        try:
            with sqlite3.connect(name) as cnx:
                cursor = cnx.cursor()
                cursor.executescript(script)
        except sqlite3.Error as error:
            print (error.message)
    elif engine == 'django.db.backends.mysql':
        pass


def get_mail_content(subject, message=None, template_name='core/mails/notice.html', extra_context=None):
    service = get_service_instance()
    config = service.config
    html_template = get_template(template_name)
    context = {
        'subject': subject,
        'message': message,
        'service': service,
        'config': config,
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


class DefaultUploadBackend(LocalUploadBackend):
    def update_filename(self, request, filename, *args, **kwargs):
        tokens = filename.split('.')
        ext = tokens[-1]
        name = ''.join(tokens[:-1])
        filename = slugify(name) + '.' + ext
        return super(DefaultUploadBackend, self).update_filename(request, filename, *args, **kwargs)


def increment_history_field(watch_object, history_field, increment_value=1):
    """
    Increments the value of the last element of Watch Object. Those are objects with *history* fields
    The matching *total field* (that is the field summing up the list of values since the creation of
    the object) is also incremented by the same value.

    :param watch_object:
    :param history_field:
    :param increment_value:
    :return:
    """
    sequence = watch_object.__dict__[history_field]
    if type(sequence) is list:  # This means that the sequence is an instance of a ListField
        sequence[-1] += increment_value
    else:
        value_list = [val.strip() for val in sequence.split(',')]
        value_list[-1] = float(value_list[-1]) + increment_value
        value_list[-1] = str(value_list[-1])
        watch_object.__dict__[history_field] = ','.join(value_list)
    matching_total_field = 'total_' + history_field.replace('_history', '')
    if watch_object.__dict__.get(matching_total_field):
        watch_object.__dict__[matching_total_field] += increment_value
    watch_object.save()


def calculate_watch_info(history_value_list, duration=0):
    """
    Given a list representing an history of subsequent values of a certain info,
    this function calculates the sum on the given duration and the variation
    compared to the same previous duration.

    :param history_value_list:
    :param duration: Number of previous days on which to pull the report, today not included
        # 0 means pulling report of today
        # 1 means pulling report of yesterday
        # 7 means pulling report of past seven days
        # etc.
    :return:
    """
    if duration == 0:
        return {
            'total': history_value_list[-1],
            'change': None
        }

    history_value_list = history_value_list[:-1]  # Strip the last value as it represents today
    if len(history_value_list) == 0:
        return None

    total, total_0, change = 0, None, None
    if duration == 1:  # When duration is a day, we compare to the same day of the previous week.
        total = history_value_list[-1]
        if len(history_value_list) >= 8:
            total_0 = history_value_list[-8]
    else:
        total = sum(history_value_list[-duration:])
        if len(history_value_list) >= duration * 2:
            start, finish = -duration * 2, -duration
            total_0 = sum(history_value_list[start:finish])

    if total_0 is not None:
        if total_0 == 0:
            change = 100  # When moving from 0 to another value, we consider change to be 100%
        else:
            change = (total - total_0) / float(total_0) * 100

    return {
        'total': total,
        'change': change
    }


def get_value_list(csv_or_sequence):
    """
    Given a *report* field as string of comma separated values or a ListField,
    splits and returns matching list. Does nothing if `csv_or_list` is already a list
    :param csv_or_sequence:
    :return:
    """
    if type(csv_or_sequence) is list:
        return csv_or_sequence
    return [float(val.strip()) for val in csv_or_sequence.split(',')]


def rank_watch_objects(watch_object_list, history_field, duration=0):
    def _cmp(x, y):
        if x.total > y.total:
            return 1
        elif x.total > y.total:
            return -1
        return 0

    if duration == 0:
        for item in watch_object_list:
            value_list = get_value_list(item.__dict__[history_field])
            item.total = value_list[-1]
    elif duration == 1:
        for item in watch_object_list:
            value_list = get_value_list(item.__dict__[history_field])
            if len(value_list) >= 2:
                item.total = value_list[-2]
    else:
        duration += 1
        for item in watch_object_list:
            value_list = get_value_list(item.__dict__[history_field])
            item.total = sum(value_list[-duration:-1])
    return sorted(watch_object_list, _cmp, reverse=True)


def group_history_value_list(days_value_list, group_unit='month'):
    grouped_value_list = []
    ref = timezone.now()
    group_total = 0
    for val in days_value_list[::-1]:
        group_total += val
        ytd = ref - timedelta(days=1)
        if group_unit == 'month' and ytd.month != ref.month:
            grouped_value_list.insert(0, group_total)
            group_total = 0
        elif group_unit == 'week' and ytd.weekday() > ref.weekday():
            grouped_value_list.insert(0, group_total)
            group_total = 0
        ref = ytd
    return grouped_value_list


def set_counters(watch_object, *args, **kwargs):
    now = timezone.now()
    last_reset = watch_object.counters_reset_on
    if last_reset:
        diff = now - last_reset
        gap = diff.days
        if diff.days == 0:
            if now.day == last_reset.day:
                return
            else:
                gap = 1
        for arg in args:
            if type(watch_object.__dict__[arg]) is list:
                extension = [0 for i in range(gap)]
                extension = extension[-366:]
                watch_object.__dict__[arg].extend(extension)
            else:
                extension = ['0' for i in range(gap)]
                extension = extension[-366:]
                watch_object.__dict__[arg] = watch_object.__dict__[arg] + ',' + ','.join(extension)
    else:
        for arg in args:
            if type(watch_object.__dict__[arg]) is list:
                watch_object.__dict__[arg].append(0)
            else:
                if watch_object.__dict__[arg]:
                    watch_object.__dict__[arg] += ',0'
                else:
                    watch_object.__dict__[arg] = 0
    watch_object.counters_reset_on = timezone.now()
    watch_object.save()


def add_event(service, member, target, codename, model, object_id):
    """
    Pushes an event to the ikwen Console.
    :param service: Service targeted by this event
    :param member: Member to whom the event is aimed
    :param target: Target panel where to display the event. One of ConsoleEvent.BUSINESS or ConsoleEvent.PERSONAL
    :param codename: string of your choice to identify the type of event
    :param model: full dotted path to the model involved in the event. *Eg: ikwen.foundation.billing.Invoice*
    :param object_id: id of the model involved.
    """
    from ikwen.foundation.accesscontrol.backends import UMBRELLA
    from ikwen.foundation.core.models import ConsoleEventType, ConsoleEvent, Service
    from ikwen.foundation.accesscontrol.models import Member

    service = Service.objects.using(UMBRELLA).get(pk=service.id)
    member = Member.objects.using(UMBRELLA).get(pk=member.id)
    event_type = ConsoleEventType.objects.using(UMBRELLA).get(app=service.app, codename=codename)
    event = ConsoleEvent.objects.using(UMBRELLA).create(service=service, member=member, target=target,
                                                        event_type=event_type, model=model, object_id=object_id)
    if target == ConsoleEvent.BUSINESS:
        Member.objects.using(UMBRELLA).filter(pk=member.id).update(business_notices=F('business_notices')+1)
    else:
        Member.objects.using(UMBRELLA).filter(pk=member.id).update(personal_notices=F('personal_notices')+1)
    return event
