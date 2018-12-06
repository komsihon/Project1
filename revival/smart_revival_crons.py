#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import logging
from datetime import datetime, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")

from django.core import mail
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import get_model, Q
from django.utils import timezone
from django.utils.module_loading import import_by_path
from django.utils.translation import activate

from echo.models import Balance
from echo.utils import notify_for_empty_messaging_credit, EMAIL
from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.constants import PENDING, COMPLETE, STARTED
from ikwen.accesscontrol.models import Member
from ikwen.core.utils import add_database, set_counters_many, increment_history_field_many
from ikwen.revival.models import Revival, Target, ObjectProfile, MemberProfile, ProfileTag
from ikwen.rewarding.utils import REFERRAL


from ikwen.core.log import CRONS_LOGGING
logging.config.dictConfig(CRONS_LOGGING)
logger = logging.getLogger('ikwen.crons')

MAX_BATCH_SEND = 500
MAX_AUTO_REWARDS = 5  # Max number of mails sent for the same Revival topic


def notify_profiles():
    """
    Cron job that revive users by mail. Must be configured
    to run with a settings file having 'umbrella' as default database.
    :return:
    """
    t0 = datetime.now()
    total_revival, total_mail = 0, 0
    for revival in Revival.objects.select_related('service').exclude(status=COMPLETE, is_active=False):
        try:
            refreshed = Revival.objects.get(pk=revival.id)
            if refreshed.is_running:
                continue
            refreshed.is_running = True
            refreshed.save()
            total_revival += 1
        except Revival.DoesNotExist:
            continue
        service = revival.service
        db = service.database
        add_database(db)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0:
            notify_for_empty_messaging_credit(service, EMAIL)
            continue
        tk = revival.model_name.split('.')
        model = get_model(tk[0], tk[1])
        try:
            obj = model._default_manager.using(db).get(pk=revival.object_id)
            object_profile = ObjectProfile.objects.using(db).get(object_id=revival.object_id)
        except ObjectDoesNotExist:
            continue
        profile_tag_list = []
        for tag in object_profile.tag_list:
            try:
                profile_tag = ProfileTag.objects.using(db).get(slug=tag)
                profile_tag_list.append(profile_tag)
            except:
                continue

        if revival.status != PENDING:
            continue

        set_counters_many(*profile_tag_list)
        revival_local = Revival.objects.using(db).get(pk=revival.id)
        if debug:
            member_queryset = Member.objects.using(db).filter(is_superuser=True)
        else:
            member_queryset = Member.objects.using(db).all()
        total = member_queryset.count()
        chunks = total / 500 + 1
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for member in member_queryset.order_by('date_joined')[start:finish]:
                try:
                    profile = MemberProfile.objects.using(db).get(member=member)
                except MemberProfile.DoesNotExist:
                    profile = MemberProfile.objects.using(db).create(member=member, tag_list=[REFERRAL])
                match = set(profile.tag_list) & set(object_profile.tag_list)
                if len(match) > 0:
                    if debug:
                        print "Profiles matching on %s for member %s" % (match, member)
                    if member.email:
                        Target.objects.using(db).get_or_create(revival=revival_local, member=member)
        revival.run_on = datetime.now()
        revival.status = STARTED
        revival.total = revival_local.target_set.all().count()
        revival.save()

        connection = mail.get_connection()
        try:
            connection.open()
        except:
            logger.error(u"Connexion error", exc_info=True)
        for target in revival_local.target_set.select_related('member').filter(notified=False)[:MAX_BATCH_SEND]:
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')
            mail_renderer = import_by_path(revival.mail_renderer)
            subject, html_content = mail_renderer(target, obj, revival)
            if not html_content:
                continue
            if debug:
                subject = 'Test - ' + subject
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            try:
                with transaction.atomic(using=WALLETS_DB_ALIAS):
                    if not debug:
                        balance.mail_count -= 1
                        balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.notified = True
                        target.save()
                        total_mail += 1
                        increment_history_field_many('smart_revival_history', args=profile_tag_list)
                    else:
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
            except:
                logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
            revival.progress += 1
            revival.save()
        else:
            revival.is_running = False
            if revival.progress > 0 and revival.progress >= revival.total:
                revival.status = COMPLETE
            revival.save()

        try:
            connection.close()
        except:
            pass

    diff = datetime.now() - t0
    logger.debug("notify_profiles() run %d revivals. %d mails sent in %s" % (total_revival, total_mail, diff))


def notify_profiles_retro():
    """
    Cron job that revive users by mail. Must be configured
    to run with a settings file having 'umbrella' as default database.
    """
    t0 = datetime.now()
    total_revival, total_mail = 0, 0
    for revival in Revival.objects.select_related('service').filter(Q(status=COMPLETE) | Q(status=STARTED),
                                                                    is_active=True):
        try:
            refreshed = Revival.objects.get(pk=revival.id)
            if refreshed.is_running:
                continue
            refreshed.is_running = True
            refreshed.save()
            total_revival += 1
        except Revival.DoesNotExist:
            continue
        start_on = datetime.now()
        service = revival.service
        db = revival.service.database
        add_database(db)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0:
            notify_for_empty_messaging_credit(service, EMAIL)
            continue
        tk = revival.model_name.split('.')
        model = get_model(tk[0], tk[1])
        try:
            obj = model._default_manager.using(db).get(pk=revival.object_id)
            object_profile = ObjectProfile.objects.using(db).get(object_id=revival.object_id)
        except ObjectDoesNotExist:
            continue
        profile_tag_list = []
        for tag in object_profile.tag_list:
            try:
                profile_tag = ProfileTag.objects.using(db).get(slug=tag)
                profile_tag_list.append(profile_tag)
            except:
                continue
        set_counters_many(*profile_tag_list)
        revival_local = Revival.objects.using(db).get(pk=revival.id)
        extra = 0
        if debug:
            member_queryset = Member.objects.using(db).filter(is_superuser=True)
        else:
            member_queryset = Member.objects.using(db).filter(date_joined__gt=revival.run_on)
        total = member_queryset.count()
        chunks = total / 500 + 1
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for member in member_queryset[start:finish]:
                try:
                    profile = MemberProfile.objects.using(db).get(member=member)
                except MemberProfile.DoesNotExist:
                    profile = MemberProfile.objects.using(db).create(member=member, tag_list=[REFERRAL])
                match = set(profile.tag_list) & set(object_profile.tag_list)
                if len(match) > 0:
                    if member.email:
                        Target.objects.using(db).get_or_create(revival=revival_local, member=member)
                        extra += 1

        revival.run_on = datetime.now()
        revival.status = STARTED
        revival.total += extra
        revival.save()
        connection = mail.get_connection()
        try:
            connection.open()
        except:
            logger.error(u"Connexion error", exc_info=True)
        for target in revival_local.target_set.select_related('member').filter(created_on__gte=start_on)[:MAX_BATCH_SEND]:
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')
            mail_renderer = import_by_path(revival.mail_renderer)
            subject, html_content = mail_renderer(target, obj, revival)
            if not html_content:
                continue
            if debug:
                subject = 'Test retro - ' + subject
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            try:
                with transaction.atomic(using=WALLETS_DB_ALIAS):
                    if not debug:
                        balance.mail_count -= 1
                        balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.save()
                        increment_history_field_many('smart_revival_history', args=profile_tag_list)
                        total_mail += 1
                    else:
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
            except:
                logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
            revival.progress += 1
            revival.save()
        else:
            revival.is_running = False
            if revival.progress >= revival.total:
                revival.status = COMPLETE
            revival.save()

        try:
            connection.close()
        except:
            pass

    diff = datetime.now() - t0
    logger.debug("notify_profiles_retro() run %d revivals. %d mails sent in %s" % (total_revival, total_mail, diff))


def rerun_complete_revivals():
    """
    Re-run Revivals with status = COMPLETE to keep users engaged
    """
    t0 = datetime.now()
    total_revival, total_mail = 0, 0
    one_week_ago = timezone.now() - timedelta(days=3)
    for revival in Revival.objects.select_related('service').filter(run_on__lte=one_week_ago, status=COMPLETE,
                                                                    is_active=True):
        try:
            refreshed = Revival.objects.get(pk=revival.id)
            if refreshed.is_running:
                continue
            refreshed.is_running = True
            refreshed.save()
            total_revival += 1
        except Revival.DoesNotExist:
            continue
        service = revival.service
        db = revival.service.database
        add_database(db)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0:
            notify_for_empty_messaging_credit(service, EMAIL)
            continue
        tk = revival.model_name.split('.')
        model = get_model(tk[0], tk[1])
        try:
            obj = model._default_manager.using(db).get(pk=revival.object_id)
            object_profile = ObjectProfile.objects.using(db).get(object_id=revival.object_id)
        except ObjectDoesNotExist:
            continue
        profile_tag_list = []
        for tag in object_profile.tag_list:
            try:
                profile_tag = ProfileTag.objects.using(db).get(slug=tag)
                profile_tag_list.append(profile_tag)
            except:
                continue

        set_counters_many(*profile_tag_list)
        revival_local = Revival.objects.using(db).get(pk=revival.id)

        revival.run_on = timezone.now()
        revival.status = STARTED
        revival.save()
        connection = mail.get_connection()
        try:
            connection.open()
        except:
            logger.error(u"Connexion error", exc_info=True)
        for target in revival_local.target_set.select_related('member').filter(revival_count__lt=MAX_AUTO_REWARDS).order_by('updated_on')[:MAX_BATCH_SEND]:
            member = target.member
            if debug and not member.is_superuser:
                continue
            if member.language:
                activate(member.language)
            else:
                activate('en')
            mail_renderer = import_by_path(revival.mail_renderer)
            subject, html_content = mail_renderer(target, obj, revival)
            if not html_content:
                continue
            if debug:
                subject = 'Test remind - ' + subject
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            try:
                with transaction.atomic(using=WALLETS_DB_ALIAS):
                    if not debug:
                        balance.mail_count -= 1
                        balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.save()
                        total_mail += 1
                        increment_history_field_many('smart_revival_history', args=profile_tag_list)
                    else:
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
            except:
                logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
        else:
            revival.is_running = False
            revival.progress += 1
            revival.save()

        try:
            connection.close()
        except:
            pass

    diff = datetime.now() - t0
    logger.debug("rerun_complete_revivals() run %d revivals. %d mails sent in %s" % (total_revival, total_mail, diff))


if __name__ == '__main__':
    try:
        t0 = datetime.now()
        try:
            debug = sys.argv[1] == 'debug'
        except IndexError:
            debug = False
        if debug:
            print "Smart revivals started in debug mode"
        notify_profiles()
        notify_profiles_retro()
        rerun_complete_revivals()

        diff = datetime.now() - t0
        logger.debug("Smart revivals run in %s" % diff)
    except:
        logger.error("Fatal error occured, cyclic revivals not run", exc_info=True)
