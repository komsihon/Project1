# -*- coding: utf-8 -*-
import json
import logging
import os
import random
import re
import string
import time
import traceback
from copy import deepcopy
from datetime import datetime, timedelta, date

import pymongo
import requests
from PIL import Image
from ajaxuploader.backends.local import LocalUploadBackend
from django.conf import settings
from django.contrib.admin import AdminSite
from django.core.files import File
from django.core.mail import EmailMessage
from django.db import router
from django.db.models import F, Model
from django.db.models.fields.files import ImageFieldFile as DjangoImageFieldFile
from django.apps import apps
from django.template import Context
from django.template.defaultfilters import urlencode, slugify
from django.template.loader import get_template
from django.utils import timezone
from django.utils.translation import ugettext as _
from pymongo import MongoClient
from pywebpush import webpush

from ikwen.conf import settings as ikwen_settings
from ikwen.core.constants import PC, TABLET, MOBILE
from ikwen.core.fields import ImageFieldFile, MultiImageFieldFile

logger = logging.getLogger('ikwen')


class XEmailMessage(EmailMessage):
    """
    Email message that is logged to the database
    """
    def send(self, fail_silently=False):
        """Sends the email message."""
        if not self.recipients():
            # Don't bother creating the network connection if there's nobody to
            # send to.
            return 0
        from ikwen.core.models import XEmailObject, Service
        try:
            email_type = self.__getattribute__('type')
        except:
            email_type = XEmailObject.TRANSACTIONAL
        try:
            service = self.__getattribute__('service')
            db = service.database
            add_database(db)
            service = Service.objects.using(db).get(pk=service.id)
        except:
            db = 'default'
            service = get_service_instance()
        to = ', '.join(self.to)
        cc = ', '.join(self.cc)
        bcc = ', '.join(self.bcc)
        email = XEmailObject(to=to, cc=cc, bcc=bcc, subject=self.subject, body=self.body, type=email_type)
        sent = 0
        try:
            sent = self.get_connection(fail_silently).send_messages([self])
            if sent:
                email.status = "OK"
                set_counters(service)
                field = email_type.lower() + '_email_history'
                increment_history_field(service, field)
            email.save(using=db)
        except Exception as e:
            email.status = traceback.format_exc()
            email.save(using=db)
            if not fail_silently:
                raise e
        return sent


def to_dict(var):
    try:
        dict_var = deepcopy(var).__dict__
    except AttributeError:
        return var
    for key in dict_var.keys():
        if key[0] == '_':
            del(dict_var[key])
        elif type(dict_var[key]) is datetime:
            dict_var[key] = dict_var[key].strftime('%Y-%m-%d %H:%M:%S')
        elif type(dict_var[key]) is date:
            dict_var[key] = dict_var[key].strftime('%Y-%m-%d')
        elif type(dict_var[key]) is list:
            try:
                dict_var[key] = [item.to_dict() for item in dict_var[key]]
            except AttributeError:
                dict_var[key] = [to_dict(item) for item in dict_var[key]]
        elif isinstance(var.__getattribute__(key), DjangoImageFieldFile) or isinstance(var.__getattribute__(key), ImageFieldFile):
            if var.__getattribute__(key).name:
                dict_var[key + '_url'] = var.__getattribute__(key).url
            else:
                dict_var[key + '_url'] = ''
            del (dict_var[key])
        elif isinstance(var.__getattribute__(key), MultiImageFieldFile):
            if var.__getattribute__(key).name:
                dict_var[key + '_url'] = var.__getattribute__(key).url
                dict_var[key + '_small_url'] = var.__getattribute__(key).small_url
                dict_var[key + '_thumb_url'] = var.__getattribute__(key).thumb_url
            else:
                dict_var[key + '_url'] = ''
                dict_var[key + '_small_url'] = ''
                dict_var[key + '_thumb_url'] = ''
            del (dict_var[key])
        elif isinstance(dict_var[key], Model):
            try:
                dict_var[key] = dict_var[key].to_dict()
            except AttributeError:
                dict_var[key] = to_dict(dict_var[key])
    return dict_var


def get_config_model():
    """
    Returns the Config model class for the current Service.
    """
    config_model_name = getattr(settings, 'IKWEN_CONFIG_MODEL', 'core.Config')
    app_label = config_model_name.split('.')[0]
    model = config_model_name.split('.')[1]
    return apps.get_model(app_label, model)


def get_service_instance(using='default', check_cache=True):
    """
    Gets the Service currently running on this website in the Service
    local database or from foundation database.
    @param using: database alias to search in
    @param check_cache: if True, fetch from cache first
    """
    from ikwen.core.models import Service
    service_id = getattr(settings, 'IKWEN_SERVICE_ID')
    return Service.objects.using(using).select_related('member', 'app').get(pk=service_id)


def add_database_to_settings(db_info, engine='django_mongodb_engine'):
    """
    Adds a database connection to the global settings on the fly.
    That is equivalent to do the following in Django settings file:

    DATABASES = {
        'default': {
            'ENGINE': 'current_database_engine',
            'NAME': 'default_database',
            ...
        },
        'alias': {
            'ENGINE': 'current_database_engine',
            'NAME': database,
            ...
        }
    }

    That connection is named 'database'
    @param db_info: string representing database under the form alias[@<host>:<port>:<username>:<password>]
    @param engine: database engine
    """
    tokens = db_info.strip().split('@')
    alias = tokens[0]
    username, password = None, None
    try:
        db_tokens = tokens[1].split(':')
        host = db_tokens[0]
        port = ''
        if len(db_tokens) >= 2:
            port = db_tokens[1]
        if len(db_tokens) >= 4:
            username = db_tokens[2]
            password = db_tokens[3]
    except IndexError:
        host = getattr(settings, 'DATABASES')['default'].get('HOST', '127.0.0.1')
        port = getattr(settings, 'DATABASES')['default'].get('PORT')
    DATABASES = getattr(settings, 'DATABASES')
    if DATABASES.get(alias) is None:  # If this alias was not yet added
        DATABASES[alias] = {
            'ENGINE': engine,
            'NAME': alias,
            'HOST': host
        }
        if port:
            DATABASES[alias]['PORT'] = port
        if username:
            DATABASES[alias]['USERNAME'] = username
            DATABASES[alias]['PASSWORD'] = password
    setattr(settings, 'DATABASES', DATABASES)


def add_database(alias, engine='django_mongodb_engine'):
    """
    Alias for add_database_to_settings()
    """
    add_database_to_settings(alias, engine=engine)


def get_mail_content(subject, message=None, template_name='core/mails/notice.html', extra_context=None, service=None):
    if not service:
        service = get_service_instance()
    config = service.basic_config
    html_template = get_template(template_name)
    from ikwen.conf.settings import MEDIA_URL
    context = {
        'subject': subject,
        'message': message,
        'service': service,
        'config': config,
        'project_name': service.project_name,
        'company_name': config.company_name,
        'logo': config.logo,
        'year': datetime.now().year,
        'IKWEN_MEDIA_URL': MEDIA_URL
    }
    if extra_context:
        context.update(extra_context)
    d = Context(context)
    return html_template.render(d)


def get_sms_label(config):
    label = config.company_name.strip()
    if len(label) > 11:
        label = label.split(' ')[0][:11]
    label = slugify(label)
    label = ''.join([tk.capitalize() for tk in label.split('-') if tk])
    return label


def send_sms(recipient, text, label=None, script_url=None, fail_silently=True):
    # label is made of 10 first characters of company name without space
    if not (recipient and text):
        return
    config = get_service_instance().config
    if not label:
        label = get_sms_label(config)
    if not script_url:
        script_url = config.sms_api_script_url
    if script_url:
        url = script_url.replace('$label', urlencode(label))\
            .replace('$recipient', recipient)\
            .replace('$text', urlencode(text))
        base_url = url.split('?')[0]
        if fail_silently:
            try:
                requests.get(url)
                logger.debug('SMS submitted to %s through %s' % (recipient, base_url))
            except:
                logger.error('Failed to submit SMS to %s through %s' % (recipient, base_url), exc_info=True)
        else:
            requests.get(url)
            logger.debug('SMS submitted to %s through %s' % (recipient, base_url))


def send_push(sender_weblet, subscription_or_member, title, body, target_page=None, image_url=None):
    """
    Submits a push notification

    :param sender_weblet: Weblet sending the push. If none the current weblet is picked
    :param subscription_or_member: Either a value contained in accesscontrol.PWAProfile.push_subscription or a Member object
    :param title: Title of the Notification
    :param body: Body text of the notification
    :param target_page: URI of the target page, not an absolute URL
    :param image_url: Absolute URL of the image
    :return: number of push successfully submitted, 0 if none was submitted
    """
    from ikwen.accesscontrol.models import Member, PWAProfile
    if not sender_weblet:
        sender_weblet = get_service_instance()
    db = sender_weblet.database
    add_database(db)
    if type(subscription_or_member) == Member:
        push_subscription_list = [pwa_profile.push_subscription for pwa_profile in PWAProfile.objects
                                  .using(db).filter(service=sender_weblet, member=subscription_or_member)]
    else:
        push_subscription_list = [subscription_or_member]

    notification = {
        'title': title,
        'body': body,
        'target': target_page,
        'badge': '%s/%s/icons/android-icon-96x96.png' % (ikwen_settings.CLUSTER_MEDIA_URL, sender_weblet.project_name_slug),
        'icon': '%s/%s/icons/android-icon-512x512.png' % (ikwen_settings.CLUSTER_MEDIA_URL, sender_weblet.project_name_slug),
        'timestamp': int(time.time()) * 1000
    }
    if image_url:
        notification['image'] = image_url
    submitted = 0
    for push_subscription in push_subscription_list:
        try:
            webpush(json.loads(push_subscription), json.dumps(notification),
                    vapid_private_key=ikwen_settings.PUSH_PRIVATE_KEY,
                    vapid_claims={"sub": "mailto: support@ikwen.com"},
                    ttl=86400*2, timeout=60)
            submitted += 1
        except:
            if type(subscription_or_member) == Member:
                logger.error("%s - Failed to send push %s to %s" % (sender_weblet.project_name, title, subscription_or_member.username), exc_info=True)
            else:
                logger.error("%s - Failed to send push %s" % (sender_weblet.project_name, title), exc_info=True)
    return submitted


class DefaultUploadBackend(LocalUploadBackend):
    def update_filename(self, request, filename, *args, **kwargs):
        tokens = filename.split('.')
        ext = tokens[-1]
        name = ''.join(tokens[:-1])
        filename = slugify(name) + '.' + ext
        return super(DefaultUploadBackend, self).update_filename(request, filename, *args, **kwargs)

    def upload_complete(self, request, filename, *args, **kwargs):
        path = self.UPLOAD_DIR + "/" + filename
        self._dest.close()
        media_root = getattr(settings, 'MEDIA_ROOT')
        media_url = getattr(settings, 'MEDIA_URL')
        model_name = request.GET.get('model_name')
        object_id = request.GET.get('object_id')
        required_width = request.GET.get('required_width')
        required_height = request.GET.get('required_height')
        rand = ''.join([random.SystemRandom().choice(string.ascii_letters) for i in range(6)])
        full_path = media_root + path
        if required_width and required_height:
            img = Image.open(full_path)
            if img.size != (int(required_width), int(required_height)):
                return {'error': _('Expected size is %(width)s x %(height)s px.' % {'width': required_width, 'height': required_height}),
                        'wrong_size': True}
        if model_name and object_id:
            s = get_service_instance()
            media_field = request.GET.get('media_field')
            if not media_field:
                media_field = request.GET.get('image_field', 'image')
            label_field = request.GET.get('label_field', 'name')
            tokens = model_name.split('.')
            model = apps.get_model(tokens[0], tokens[1])
            obj = model._default_manager.get(pk=object_id)
            media = obj.__getattribute__(media_field)
            try:
                with open(media_root + path, 'r') as f:
                    content = File(f)
                    current_media_path = media.path if media.name else None
                    upload_to = media.field.upload_to
                    if callable(upload_to):
                        upload_to = upload_to(obj, filename)
                    dir = media_root + upload_to
                    unique_filename = False
                    filename_suffix = 0
                    filename_no_extension, extension = os.path.splitext(filename)
                    try:
                        label = obj.__getattribute__(label_field)
                        if label:
                            seo_filename_no_extension = slugify(label)
                        else:
                            seo_filename_no_extension = obj.__class__.__name__.lower()
                    except:
                        seo_filename_no_extension = obj.__class__.__name__.lower()
                    seo_filename = seo_filename_no_extension + extension
                    if os.path.isfile(os.path.join(dir, seo_filename)):
                        while not unique_filename:
                            try:
                                if filename_suffix == 0:
                                    open(os.path.join(dir, seo_filename))
                                else:
                                    open(os.path.join(dir, seo_filename_no_extension + str(filename_suffix) + extension))
                                filename_suffix += 1
                            except IOError:
                                unique_filename = True
                    if filename_suffix > 0:
                        seo_filename = seo_filename_no_extension + str(filename_suffix) + extension

                    if isinstance(media, DjangoImageFieldFile) or isinstance(media, ImageFieldFile):
                        seo_filename = s.project_name_slug + '_' + seo_filename
                    else:
                        seo_filename = seo_filename.capitalize()

                    destination = os.path.join(dir, seo_filename)
                    if not os.path.exists(dir):
                        os.makedirs(dir)
                    media.save(destination, content)
                    if request.GET.get('upload_to_ikwen') == 'yes':  # Upload to ikwen media folder for access platform wide.
                        destination2_folder = ikwen_settings.MEDIA_ROOT + upload_to
                        if not os.path.exists(destination2_folder):
                            os.makedirs(destination2_folder)
                        destination2 = destination.replace(media_root, ikwen_settings.MEDIA_ROOT)
                        os.rename(destination, destination2)
                        if isinstance(media, MultiImageFieldFile):
                            destination2_small = ikwen_settings.MEDIA_ROOT + media.small_name
                            destination2_thumb = ikwen_settings.MEDIA_ROOT + media.thumb_name
                            os.rename(media.small_path, destination2_small)
                            os.rename(media.thumb_path, destination2_thumb)
                        media_url = ikwen_settings.MEDIA_URL
                    if isinstance(media, MultiImageFieldFile):
                        url = media_url + media.small_name
                        preview_url = url
                    elif isinstance(media, DjangoImageFieldFile) or isinstance(media, ImageFieldFile):
                        url = media_url + media.name
                        preview_url = url
                    else:
                        url = media_url + media.name
                        preview_url = get_preview_from_extension(media.name)
                try:
                    if media and os.path.exists(media_root + path):
                        os.unlink(media_root + path)  # Remove file from upload tmp folder
                except Exception as e:
                    if getattr(settings, 'DEBUG', False):
                        raise e
                if current_media_path:
                    try:
                        if destination != current_media_path and os.path.exists(current_media_path):
                            os.unlink(current_media_path)
                    except OSError as e:
                        if getattr(settings, 'DEBUG', False):
                            raise e
                return {
                    'path': url,
                    'preview': preview_url + '?rand=' + rand
                }
            except IOError as e:
                logger.error("File failed to upload. May be invalid or corrupted image file", exc_info=True)
                if settings.DEBUG:
                    raise e
                return {'error': 'File failed to upload. May be invalid or corrupted image file'}
        elif request.GET.get('is_tiny_mce'):
            tiny_mce_upload_dir = getattr(settings, 'TINY_MCE_UPLOAD_DIR', 'tiny_mce')
            tiny_mce_root = media_root + tiny_mce_upload_dir
            if not os.path.exists(tiny_mce_root):
                os.makedirs(tiny_mce_root)
            src = media_root + self.UPLOAD_DIR + "/" + filename
            dst = tiny_mce_root + '/' + filename
            os.rename(src, dst)
            return {
                'path': media_url + tiny_mce_upload_dir + '/' + filename + '?rand=' + rand
            }
        else:
            path = settings.MEDIA_URL + self.UPLOAD_DIR + "/" + filename
            self._dest.close()
            raw_filename, extension = os.path.splitext(filename)
            resp = {"path": path}
            if extension.lower() not in ['.gif', '.jpeg', '.jpg', '.png', '.svg']:
                resp["preview"] = get_preview_from_extension(filename)
            return resp


def increment_history_field(watch_object, history_field, increment_value=1, index=None):
    """
    Increments the value of the last element of Watch Object. Those are objects with *history* fields
    The matching *total field* (that is the field summing up the list of values since the creation of
    the object) is also incremented by the same value.

    :param watch_object:
    :param history_field:
    :param increment_value:
    :param index:
    :return:
    """
    sequence = watch_object.__dict__[history_field]
    if type(sequence) is list:  # This means that the sequence is an instance of a ListField
        if index is not None:
            sequence[index] += increment_value
            return
        if len(sequence) >= 1:
            sequence[-1] += increment_value
        else:
            sequence.append(increment_value)
    else:
        value_list = [val.strip() for val in sequence.split(',')]
        if index is not None:
            value_list[index] = float(value_list[index]) + increment_value
        else:
            value_list[-1] = float(value_list[-1]) + increment_value
            value_list[-1] = str(value_list[-1])
        watch_object.__dict__[history_field] = ','.join(value_list)
    matching_total_field = 'total_' + history_field.replace('_history', '')
    try:
        watch_object.__dict__[matching_total_field] += increment_value
    except KeyError:
        pass
    db = router.db_for_write(watch_object.__class__, instance=watch_object)
    watch_object.save(using=db)


def increment_history_field_many(history_field, increment_value=1, index=None, *args, **kwargs):
    for watch_object in args:
        increment_history_field(watch_object, history_field, increment_value)


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
            'change': None,
            'change_rate': None
        }

    history_value_list = history_value_list[:-1]  # Strip the last value as it represents today
    if len(history_value_list) == 0:
        return {'total': 0, 'change': None, 'change_rate': None}

    total, total_0, change, change_rate = 0, None, None, None
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
        change = total - total_0
        if total_0 == 0 and total == 0:
            change_rate = 0  # When moving from 0 to 0, we consider change to be 0%
        elif total_0 == 0 and total != 0:
            change_rate = 100  # When moving from 0 to another value, we consider change to be 100%
        else:
            change_rate = float(change) / total_0 * 100

    return {
        'total': total,
        'change': change,
        'change_rate': change_rate
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


def slice_watch_objects(klass, duration=0, time_field='last_payment_on', using='default'):
    """
    Gets a slice of watch objects which time_field match the duration
    Eg:
        # `slice_watch_object(Customer)` returns a list of Customer which
        last_payment_on ranges between today 00:00 and now()

        # `slice_watch_object(Customer, 1)` returns a list of Customer which
        last_payment_on ranges between yesterday 00:00 and yesterday 23:59

        # `slice_watch_object(Customer, 7)` returns a list of Customer which
        last_payment_on ranges between last_week 00:00 and yesterday 23:59
    """
    now = datetime.now()
    midnight = datetime(now.year, now.month, now.day, 0, 0)
    yesterday = now - timedelta(days=1)
    yesterday_end = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    if duration == 0:
        kwargs = {time_field + '__gte': midnight}
        queryset = klass._default_manager.using(using).filter(**kwargs)
    elif duration == 1:
        range_start = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0)
        kwargs = {time_field + '__range': (range_start, yesterday_end)}
        queryset = klass._default_manager.using(using).filter(**kwargs)
    else:
        days_back = duration + 1
        period_start = now - timedelta(days=days_back)
        range_start = datetime(period_start.year, period_start.month, period_start.day, 0, 0)
        kwargs = {time_field + '__range': (range_start, yesterday_end)}
        queryset = klass._default_manager.using(using).filter(**kwargs)
    object_list = list(queryset)
    for obj in object_list:
        set_counters(obj)
    return object_list


def rank_watch_objects(watch_object_list, history_field, duration=0):
    def _cmp(x, y):
        if x.total > y.total:
            return 1
        elif x.total < y.total:
            return -1
        return 0

    object_list_copy = deepcopy(watch_object_list)
    if duration == 0:
        for item in object_list_copy:
            value_list = get_value_list(item.__dict__[history_field])
            if value_list:
                item.total = value_list[-1]
            else:
                item.total = 0
    elif duration == 1:
        for item in object_list_copy:
            value_list = get_value_list(item.__dict__[history_field])
            if len(value_list) >= 2:
                item.total = value_list[-2]
            else:
                item.total = 0
    else:
        duration += 1
        for item in object_list_copy:
            value_list = get_value_list(item.__dict__[history_field])
            length = len(value_list)
            if length >= duration:
                item.total = sum(value_list[-duration:-1])
            else:
                item.total = sum(value_list[-length:-1])
    return sorted(object_list_copy, _cmp, reverse=True)


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
    history_fields = [field for field in watch_object.__dict__.keys() if field.endswith('_history')]
    db = router.db_for_write(watch_object.__class__, instance=watch_object)
    if last_reset:
        diff = now - last_reset
        gap = diff.days
        if diff.days == 0:
            if now.day == last_reset.day:
                for field in history_fields:
                    if type(watch_object.__dict__[field]) is list:
                        if len(watch_object.__dict__[field]) == 0:
                            watch_object.__dict__[field].append(0)
                    else:
                        if not watch_object.__dict__[field]:
                            watch_object.__dict__[field] = '0'
                watch_object.save(using=db)
                return
            else:
                gap = 1
        for field in history_fields:
            if type(watch_object.__dict__[field]) is list:
                extension = [0 for i in range(gap)]
                watch_object.__dict__[field].extend(extension)
                watch_object.__dict__[field] = watch_object.__dict__[field][-366:]
            else:
                extension = ['0' for i in range(gap)]
                res = watch_object.__dict__[field] + ',' + ','.join(extension)
                res = res.split(',')[-366:]
                watch_object.__dict__[field] = ','.join(res)
    else:
        for field in history_fields:
            if type(watch_object.__dict__[field]) is list:
                watch_object.__dict__[field].append(0)
            else:
                watch_object.__dict__[field] = '0'
    watch_object.counters_reset_on = timezone.now()
    watch_object.save(using=db)


def clear_counters(watch_object):
    """
    Empty all history fields and set the matching totals to 0
    """
    history_fields = [field for field in watch_object.__dict__.keys() if field.endswith('_history')]
    db = router.db_for_write(watch_object.__class__, instance=watch_object)
    for field in history_fields:
        if type(watch_object.__dict__[field]) is list:
            watch_object.__dict__[field] = []
        else:
            watch_object.__dict__[field] = ''
        matching_total_field = 'total_' + field.replace('_history', '')
        try:
            watch_object.__dict__[matching_total_field] = 0
        except KeyError:
            pass
    watch_object.counters_reset_on = timezone.now()
    watch_object.save(using=db)


def set_counters_many(*args, **kwargs):
    """
    Call set_counters on multiple WatchObject.
    """
    for watch_object in args:
        set_counters(watch_object)


def extend_left(additional, watch_object, **kwargs):
    """
    Extends a WatchObject on the left by filling
    its history fields with additional zeros.
    """
    history_fields = [field for field in watch_object.__dict__.keys() if field.endswith('_history')]
    for field in history_fields:
        for i in range(additional):
            watch_object.__getattribute__(field).insert(0, 0)


def extend_left_many(additional, *args, **kwargs):
    for watch_object in args:
        extend_left(additional, watch_object)


def add_event(service, codename, member=None, group_id=None, object_id=None, model=None, object_id_list=[]):
    """
    Pushes an event to the ikwen Console and return the created ConsoleEvent object.
    :param service: Service targeted by this event
    :param member: Member to whom the event is aimed
    :param group_id: Id of group to whom the event is aimed
    :param object_id: id of the model involved.
    :param model: django style model name involved in the event. *Eg: billing.Invoice*
    """
    from ikwen.accesscontrol.backends import UMBRELLA
    from ikwen.core.models import ConsoleEventType, ConsoleEvent, Service
    from ikwen.accesscontrol.models import Member

    service = Service.objects.using(UMBRELLA).get(pk=service.id)
    if member:
        member = Member.objects.using(UMBRELLA).get(pk=member.id)
        Member.objects.using(UMBRELLA).filter(pk=member.id).update(personal_notices=F('personal_notices')+1)
    elif group_id:
        add_database_to_settings(service.database)
        for m in Member.objects.using(service.database).all():
            if group_id in m.group_fk_list:
                Member.objects.using(UMBRELLA).filter(pk=m.id).update(personal_notices=F('personal_notices') + 1)
    else:
        add_database_to_settings(service.database)
        for m in Member.objects.using(service.database).all():
            Member.objects.using(UMBRELLA).filter(pk=m.id).update(personal_notices=F('personal_notices') + 1)
    try:
        event_type = ConsoleEventType.objects.using(UMBRELLA).get(app=service.app, codename=codename)
    except ConsoleEventType.DoesNotExist:
        try:
            event_type = ConsoleEventType.objects.using(UMBRELLA).get(codename=codename)
        except ConsoleEventType.DoesNotExist:
            event_type = ConsoleEventType.objects.using(UMBRELLA).create(app=service.app, codename=codename,
                                                                         renderer='ikwen.core.utils.render_event')
    event = ConsoleEvent.objects.using(UMBRELLA).\
        create(service=service, member=member, group_id=group_id,
               event_type=event_type, model=model, object_id=object_id, object_id_list=object_id_list)
    return event


def render_event(event, request):
    """
    Default event renderer
    """
    try:
        model = apps.get_model(event.model)
        db = event.service.database
        add_database(db)
        obj = model.objects.using(db).get(pk=event.object_id)
    except :
        return ''
    html_template = get_template('%s/events/%s.html' % (event.service.app.slug, event.event_type.codename))
    context = {'event': event, 'obj': obj}
    c = Context(context)
    return html_template.render(c)


def get_model_admin_instance(model, model_admin):
    default_site = AdminSite()
    instance = model_admin(model, default_site)
    return instance


def as_matrix(object_list, col_length, strict=False):
    """
    Takes a list and turns it into a matrix with col_length columns

    Ex:
    input_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    as_matrix(input_list, 4) -->  [[1, 2, 3, 4],
                                   [5, 6, 7, 8],
                                   [9, 10, 11, 12]]

    as_matrix(input_list, 6) -->  [[1, 2, 3, 4, 5, 6],
                                   [7, 8, 9, 10, 11, 12]]
    :param object_list: the input list
    :param col_length: length of a column in the output matrix
    :param strict: if True, the output matrix will include the last row if
                    the number of elements equals col_length
    :return:
    """
    if len(object_list) == 0:
        return []
    rows = len(object_list) / col_length
    if not strict and len(object_list) % col_length > 0:
        rows += 1
    matrix = []
    for i in range(rows):
        start = i * col_length
        end = start + col_length
        row = object_list[start:end]
        if row:
            matrix.append(row)
    return matrix


def generate_icons(logo_path, output_folder=None, media_root=None):
    """
    Generate favicon based on a logo image
    :param logo_path: Path to the logo image
    :param output_folder: Folder where to deposit the generated favicons
    :param media_root: The media root to be used
    """
    if not media_root:
        media_root = getattr(settings, 'MEDIA_ROOT')
    if not output_folder:
        ICONS_FOLDER = 'icons/'
    else:
        ICONS_FOLDER = output_folder

    folder = media_root + ICONS_FOLDER
    if not os.path.exists(folder):
        os.makedirs(folder)

    # WEB FAVICONS
    for d in (16, 32, 96, 128, 256):
        img = Image.open(logo_path)
        img.thumbnail((d, d), Image.ANTIALIAS)
        output = folder + 'favicon-%dx%d.png' % (d, d)
        img.save(output, format="PNG", quality=100)

    # iOS FAVICONS
    for d in (57, 60, 72, 76, 114, 120, 144, 152, 180):
        img = Image.open(logo_path)
        img.thumbnail((d, d), Image.ANTIALIAS)
        output = folder + 'apple-icon-%dx%d.png' % (d, d)
        img.save(output, format="PNG", quality=100)

    # Android FAVICONS
    for d in (36, 48, 72, 96, 144, 192, 512):
        img = Image.open(logo_path)
        img.thumbnail((d, d), Image.ANTIALIAS)
        output = folder + 'android-icon-%dx%d.png' % (d, d)
        img.save(output, format="PNG", quality=100)

    # MS FAVICONS
    for d in (70, 144, 150, 310):
        img = Image.open(logo_path)
        img.thumbnail((d, d), Image.ANTIALIAS)
        output = folder + 'ms-icon-%dx%d.png' % (d, d)
        img.save(output, format="PNG", quality=100)


def get_preview_from_extension(filename):
    raw_filename, extension = os.path.splitext(filename)
    if extension in ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.pdf', '.mp3', '.mp4', '.zip', '.xz', '.gz',
                     '.7z', '.rar', '.ods']:
        extension = extension[1:]
    else:
        extension = 'unknown'
    return ikwen_settings.STATIC_URL + 'ikwen/img/ext/%s.png' % extension


def to_snake_case(s):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', s)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# *** PayPal Stuffs *** #

EC_ENDPOINT = 'https://api-3t.sandbox.paypal.com/nvp' if getattr(settings, 'DEBUG', False) \
    else 'https://api-3t.paypal.com/nvp'


def parse_paypal_response(response_string):
    result = {}
    for pair in response_string.split('&'):
        tokens = pair.split('=')
        result[tokens[0]] = tokens[1]
    return result


def get_item_list(model_name, item_fk_list):
    tk = model_name.split('.')
    model = apps.get_model(tk[0], tk[1])
    return list(model._default_manager.filter(pk__in=item_fk_list))


def get_device_type(request):
    if request.user_agent.is_mobile:
        return MOBILE
    if request.user_agent.is_tablet:
        return TABLET
    return PC


def setup_pwa(service, is_naked_domain=True, reload_web_server=False):
    service.activate_ssl(is_naked_domain, reload_web_server)
    service.generate_pwa_manifest()

    # Add index to ikwen_pwa_profile collection
    host = getattr(settings, 'DATABASES')['default'].get('HOST', '127.0.0.1')
    port = getattr(settings, 'DATABASES')['default'].get('PORT', 27017)

    client = MongoClient(host, port)
    dbh = client[service.database]
    dbh.ikwen_pwa_profile.create_index([('service_id', pymongo.ASCENDING)])
    dbh.ikwen_pwa_profile.create_index([('member_id', pymongo.ASCENDING)])
    dbh.ikwen_pwa_profile.create_index([('device_type', pymongo.ASCENDING)])
    dbh.ikwen_pwa_profile.create_index([('installed_on', pymongo.ASCENDING)])
    dbh.ikwen_pwa_profile.create_index([('subscribed_to_push_on', pymongo.ASCENDING)])

    service.is_pwa_ready = True
    service.save()
