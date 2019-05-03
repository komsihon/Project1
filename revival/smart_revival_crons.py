#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import logging
from datetime import datetime, timedelta

sys.path.append("/home/libran/virtualenv/lib/python2.7/site-packages")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")

from django.core import mail
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import get_model, Q
from django.utils import timezone
from django.utils.module_loading import import_by_path
from django.utils.translation import activate
from django.conf import settings

from echo.models import Balance
from echo.utils import notify_for_empty_messaging_credit, notify_for_low_messaging_credit, LOW_MAIL_LIMIT
from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.core.constants import PENDING, COMPLETE, STARTED
from ikwen.core.utils import XEmailMessage
from ikwen.core.models import XEmailObject
from ikwen.accesscontrol.models import Member
from ikwen.core.utils import add_database, set_counters_many, set_counters, increment_history_field
from ikwen.revival.models import Revival, Target, MemberProfile, ProfileTag
from ikwen.rewarding.utils import REFERRAL

# from ikwen.core.log import CRONS_LOGGING
# logging.config.dictConfig(CRONS_LOGGING)
logger = logging.getLogger('ikwen.crons')

MAX_BATCH_SEND = 500
MAX_AUTO_REWARDS = 3  # Max number of mails sent for the same Revival topic


def notify_profiles(debug=False):
    """
    Cron job that revive users by mail. Must be configured
    to run with a settings file having 'umbrella' as default database.
    :return:
    """
    t0 = datetime.now()
    seven_hours_ago = t0 - timedelta(hours=7)
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

        try:
            mail_renderer = import_by_path(revival.mail_renderer)
            kwargs = {}
            if revival.get_kwargs:
                get_kwargs = import_by_path(revival.get_kwargs)
                kwargs = get_kwargs(revival)
        except:
            revival.is_running = False
            revival.save()
            logger.error("Error when starting revival %s for %s" % (revival.mail_renderer, revival.service), exc_info=True)
            continue

        service = revival.service
        db = service.database
        add_database(db)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0:
            revival.is_running = False
            revival.save()
            try:
                notify_for_empty_messaging_credit(service, balance)
            except:
                logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
            continue
        if 0 < balance.mail_count < LOW_MAIL_LIMIT:
            try:
                notify_for_low_messaging_credit(service, balance)
            except:
                logger.error("Failed to notify %s for low messaging credit." % service, exc_info=True)
        tk = revival.model_name.split('.')
        model = get_model(tk[0], tk[1])
        try:
            obj = model._default_manager.using(db).get(pk=revival.object_id)
        except ObjectDoesNotExist:
            revival.is_running = False
            revival.save()
            continue
        try:
            profile_tag = ProfileTag.objects.using(db).get(pk=revival.profile_tag_id)
        except:
            revival.is_running = False
            revival.save()
            continue

        if revival.status != PENDING:
            revival.is_running = False
            revival.save()
            continue

        set_counters(profile_tag)
        revival_local = Revival.objects.using(db).get(pk=revival.id)
        if debug:
            member_queryset = Member.objects.using(db).filter(is_superuser=True)
        else:
            member_queryset = Member.objects.using(db).filter(date_joined__lte=seven_hours_ago)
        total = member_queryset.count()
        chunks = total / 500 + 1
        target_count = 0
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for member in member_queryset.order_by('date_joined')[start:finish]:
                try:
                    profile = MemberProfile.objects.using(db).get(member=member)
                except MemberProfile.DoesNotExist:
                    ref_tag = ProfileTag.objects.using(db).get(slug=REFERRAL)
                    profile = MemberProfile.objects.using(db).create(member=member, tag_fk_list=[ref_tag.id])
                if revival.profile_tag_id in profile.tag_fk_list:
                    if debug:
                        tag = ProfileTag.objects.using(db).get(pk=revival.profile_tag_id)
                        print "Profiles matching on %s for member %s" % (tag, member)
                    if member.email:
                        Target.objects.using(db).get_or_create(revival=revival_local, member=member)
                        target_count += 1

        if target_count == 0:
            revival.is_running = False
            revival.save()
            continue

        revival.run_on = datetime.now()
        revival.status = STARTED
        revival.total = revival_local.target_set.all().count()
        revival.save()

        connection = mail.get_connection()
        try:
            connection.open()
        except:
            revival.is_running = False
            revival.save()
            logger.error(u"Connexion error", exc_info=True)
            continue

        logger.debug("Running notify_profiles() %s for %s" % (revival.mail_renderer, revival.service))
        for target in revival_local.target_set.select_related('member').filter(notified=False)[:MAX_BATCH_SEND]:
            if not debug and balance.mail_count == 0:
                revival.is_running = False
                revival.save()
                try:
                    notify_for_empty_messaging_credit(service, balance)
                except:
                    logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
                break
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')

            if getattr(settings, 'UNIT_TESTING', False):
                sender, subject, html_content = mail_renderer(target, obj, revival, **kwargs)
            else:
                try:
                    sender, subject, html_content = mail_renderer(target, obj, revival, **kwargs)
                except:
                    logger.error("Could not render mail for member %s, Revival %s, Obj: %s" % (member.email, revival.mail_renderer, str(obj)), exc_info=True)
                    continue

            if not html_content:
                continue
            if debug:
                subject = 'Test - ' + subject
            msg = XEmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            msg.type = XEmailObject.REVIVAL
            try:
                with transaction.atomic(using=WALLETS_DB_ALIAS):
                    if not debug:
                        balance.mail_count -= 1
                        balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.notified = True
                        target.revived_on = t0
                        target.save()
                        total_mail += 1
                        increment_history_field(profile_tag, 'smart_revival_history')
                    else:
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
            except:
                logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
            revival.progress += 1
            revival.save()

        revival.is_running = False
        if revival.progress > 0 and revival.progress >= revival.total:
            revival.status = COMPLETE
        revival.save()

        try:
            connection.close()
        except:
            revival.is_running = False
            revival.save()

    diff = datetime.now() - t0
    logger.debug("notify_profiles() run %d revivals. %d mails sent in %s" % (total_revival, total_mail, diff))


def notify_profiles_retro(debug=False):
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

        try:
            mail_renderer = import_by_path(revival.mail_renderer)
            kwargs = {}
            if revival.get_kwargs:
                get_kwargs = import_by_path(revival.get_kwargs)
                kwargs = get_kwargs(revival)
        except:
            revival.is_running = False
            revival.save()
            logger.error("Error when starting revival %s for %s" % (revival.mail_renderer, revival.service), exc_info=True)
            continue

        start_on = datetime.now()
        service = revival.service
        db = revival.service.database
        add_database(db)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0:
            revival.is_running = False
            revival.save()
            try:
                notify_for_empty_messaging_credit(service, balance)
            except:
                logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
            continue
        if 0 < balance.mail_count < LOW_MAIL_LIMIT:
            try:
                notify_for_low_messaging_credit(service, balance)
            except:
                logger.error("Failed to notify %s for low messaging credit." % service, exc_info=True)
        tk = revival.model_name.split('.')
        model = get_model(tk[0], tk[1])
        try:
            obj = model._default_manager.using(db).get(pk=revival.object_id)
        except ObjectDoesNotExist:
            revival.is_running = False
            revival.save()
            continue
        try:
            profile_tag = ProfileTag.objects.using(db).get(pk=revival.profile_tag_id)
        except:
            revival.is_running = False
            revival.save()
            continue
        set_counters(profile_tag)
        revival_local = Revival.objects.using(db).get(pk=revival.id)
        extra = 0
        if debug:
            member_queryset = Member.objects.using(db).filter(is_superuser=True)
        else:
            member_queryset = Member.objects.using(db).all()
        total = member_queryset.count()
        chunks = total / 500 + 1
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for member in member_queryset[start:finish]:
                try:
                    profile = MemberProfile.objects.using(db).get(member=member)
                except MemberProfile.DoesNotExist:
                    ref_tag = ProfileTag.objects.using(db).get(slug=REFERRAL)
                    profile = MemberProfile.objects.using(db).create(member=member, tag_fk_list=[ref_tag.id])
                if revival.profile_tag_id in profile.tag_fk_list:
                    if debug:
                        tag = ProfileTag.objects.using(db).get(pk=revival.profile_tag_id)
                        print "Profiles matching on %s for member %s" % (tag, member)
                    if member.email:
                        Target.objects.using(db).get_or_create(revival=revival_local, member=member)
                        extra += 1

        if extra == 0:
            revival.is_running = False
            revival.save()
            continue

        revival.run_on = datetime.now()
        revival.status = STARTED
        revival.total += extra
        revival.save()
        connection = mail.get_connection()
        try:
            connection.open()
        except:
            revival.is_running = False
            revival.save()
            logger.error(u"Connexion error", exc_info=True)
            continue

        logger.debug("Running notify_profiles_retro() %s for %s" % (revival.mail_renderer, revival.service))
        for target in revival_local.target_set.select_related('member').filter(created_on__gte=start_on)[:MAX_BATCH_SEND]:
            if not debug and balance.mail_count == 0:
                revival.is_running = False
                revival.save()
                try:
                    notify_for_empty_messaging_credit(service, balance)
                except:
                    logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
                break
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')

            if getattr(settings, 'UNIT_TESTING', False):
                sender, subject, html_content = mail_renderer(target, obj, revival, **kwargs)
            else:
                try:
                    sender, subject, html_content = mail_renderer(target, obj, revival, **kwargs)
                except:
                    logger.error("Could not render mail for member %s, Revival %s, Obj: %s" % (member.email, revival.mail_renderer, str(obj)), exc_info=True)
                    continue

            if not html_content:
                continue
            if debug:
                subject = 'Test retro - ' + subject
            msg = XEmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            msg.type = XEmailObject.REVIVAL
            try:
                with transaction.atomic(using=WALLETS_DB_ALIAS):
                    if not debug:
                        balance.mail_count -= 1
                        balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.revived_on = t0
                        target.save()
                        increment_history_field(profile_tag, 'smart_revival_history')
                        total_mail += 1
                    else:
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
            except:
                logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
            revival.progress += 1
            revival.save()

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


def rerun_complete_revivals(debug=False):
    """
    Re-run Revivals with status = COMPLETE to keep users engaged
    """
    t0 = datetime.now()
    total_revival, total_mail = 0, 0
    three_days_ago = timezone.now() - timedelta(days=3)
    for revival in Revival.objects.select_related('service').filter(status=COMPLETE, is_active=True):
        try:
            refreshed = Revival.objects.get(pk=revival.id)
            if refreshed.is_running:
                continue
            refreshed.is_running = True
            refreshed.save()
            total_revival += 1
        except Revival.DoesNotExist:
            continue

        try:
            mail_renderer = import_by_path(revival.mail_renderer)
            kwargs = {}
            if revival.get_kwargs:
                get_kwargs = import_by_path(revival.get_kwargs)
                kwargs = get_kwargs(revival)
        except:
            revival.is_running = False
            revival.save()
            logger.error("Error when starting revival %s for %s" % (revival.mail_renderer, revival.service), exc_info=True)
            continue

        service = revival.service
        db = revival.service.database
        add_database(db)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0:
            revival.is_running = False
            revival.save()
            try:
                notify_for_empty_messaging_credit(service, balance)
            except:
                logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
            continue
        if 0 < balance.mail_count < LOW_MAIL_LIMIT:
            try:
                notify_for_low_messaging_credit(service, balance)
            except:
                logger.error("Failed to notify %s for low messaging credit." % service, exc_info=True)
        tk = revival.model_name.split('.')
        model = get_model(tk[0], tk[1])
        try:
            obj = model._default_manager.using(db).get(pk=revival.object_id)
        except ObjectDoesNotExist:
            revival.is_running = False
            revival.save()
            continue
        try:
            profile_tag = ProfileTag.objects.using(db).get(pk=revival.profile_tag_id)
        except:
            revival.is_running = False
            revival.save()
            continue

        set_counters_many(profile_tag)
        revival_local = Revival.objects.using(db).get(pk=revival.id)

        target_queryset = revival_local.target_set.select_related('member').filter(revived_on__lte=three_days_ago,
                                                                                   revival_count__lt=MAX_AUTO_REWARDS)
        if target_queryset.count() == 0:
            revival.is_running = False
            revival.save()
            continue
        revival.run_on = timezone.now()
        revival.status = STARTED
        revival.save()
        connection = mail.get_connection()
        try:
            connection.open()
        except:
            revival.is_running = False
            revival.save()
            logger.error(u"Connexion error", exc_info=True)
            continue

        logger.debug("Running rerun_complete_revivals() %s for %s" % (revival.mail_renderer, revival.service))
        for target in target_queryset.order_by('updated_on')[:MAX_BATCH_SEND]:
            if not debug and balance.mail_count == 0:
                revival.is_running = False
                revival.save()
                try:
                    notify_for_empty_messaging_credit(service, balance)
                except:
                    logger.error("Failed to notify %s for empty messaging credit." % service, exc_info=True)
                break
            member = target.member
            if debug and not member.is_superuser:
                continue
            if member.language:
                activate(member.language)
            else:
                activate('en')

            if getattr(settings, 'UNIT_TESTING', False):
                sender, subject, html_content = mail_renderer(target, obj, revival, **kwargs)
            else:
                try:
                    sender, subject, html_content = mail_renderer(target, obj, revival, **kwargs)
                except:
                    logger.error("Could not render mail for member %s, Revival %s, Obj: %s" % (member.email, revival.mail_renderer, str(obj)), exc_info=True)
                    continue

            if not html_content:
                continue
            if debug:
                subject = 'Test remind - ' + subject
            msg = XEmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            msg.type = XEmailObject.REVIVAL
            try:
                with transaction.atomic(using=WALLETS_DB_ALIAS):
                    if not debug:
                        balance.mail_count -= 1
                        balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.revived_on = t0
                        target.save()
                        total_mail += 1
                        increment_history_field(profile_tag, 'smart_revival_history')
                    else:
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
            except:
                logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)

        revival.is_running = False
        revival.progress += 1
        revival.save()

        try:
            connection.close()
        except:
            revival.is_running = False
            revival.save()

    diff = datetime.now() - t0
    logger.debug("rerun_complete_revivals() run %d revivals. %d mails sent in %s" % (total_revival, total_mail, diff))


if __name__ == '__main__':
    try:
        t0 = datetime.now()
        try:
            DEBUG = sys.argv[1] == 'debug'
        except IndexError:
            DEBUG = False
        if DEBUG:
            print "Smart revivals started in debug mode"
        notify_profiles(DEBUG)
        notify_profiles_retro(DEBUG)
        rerun_complete_revivals(DEBUG)

        diff = datetime.now() - t0
        logger.debug("Smart revivals run in %s" % diff)
    except:
        logger.error("Fatal error occured, cyclic revivals not run", exc_info=True)
