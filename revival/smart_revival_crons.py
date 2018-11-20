# -*- coding: utf-8 -*-
import os
import logging
from datetime import timedelta

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

logger = logging.getLogger('ikwen.crons')

MAX_BATCH_SEND = 500
MAX_AUTO_REWARDS = 5  # Max number of mails sent for the same Revival topic


def notify_profiles():
    """
    Cron job that revive users by mail. Must be configured
    to run with a settings file having 'umbrella' as default database.
    :return:
    """
    for revival in Revival.objects.select_related('service').exclude(status=COMPLETE, is_active=False):
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
        set_counters_many(*profile_tag_list)
        if revival.status == PENDING:
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
                        continue
                    match = set(profile.tag_list) & set(object_profile.tag_list)
                    if len(match) > 0:
                        if member.email:
                            Target.objects.get_or_create(revival=revival, member=member)
            revival.run_on = timezone.now()
            revival.status = STARTED
            revival.total = revival.target_set.all().count()
            revival.save()

        connection = mail.get_connection()
        try:
            connection.open()
        except:
            logger.error(u"Connexion error", exc_info=True)
        for target in revival.target_set.select_related('member').filter(notified=False)[:MAX_BATCH_SEND]:
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')
            mail_renderer = import_by_path(revival.mail_renderer)
            subject, html_content = mail_renderer(target, obj, revival)
            if not html_content:
                continue
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            with transaction.atomic(using=WALLETS_DB_ALIAS):
                try:
                    balance.mail_count -= 1
                    balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.notified = True
                        target.save()
                        increment_history_field_many('smart_revival_history', args=profile_tag_list)
                    else:
                        transaction.rollback(using=WALLETS_DB_ALIAS)
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
                except:
                    transaction.rollback(using=WALLETS_DB_ALIAS)
                    logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
            revival.progress += 1
            revival.save()
        else:
            if revival.progress >= revival.total:
                revival.status = COMPLETE
                revival.save()

        try:
            connection.close()
        except:
            pass


def notify_profiles_retro():
    """
    Cron job that revive users by mail. Must be configured
    to run with a settings file having 'umbrella' as default database.
    """
    for revival in Revival.objects.select_related('service').filter(Q(status=COMPLETE) | Q(status=STARTED),
                                                                    is_active=True):
        start_on = timezone.now()
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
        extra = 0
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
                    continue
                match = set(profile.tag_list) & set(object_profile.tag_list)
                if len(match) > 0:
                    if member.email:
                        Target.objects.get_or_create(revival=revival, member=member)
                        extra += 1

        revival.run_on = timezone.now()
        revival.status = STARTED
        revival.total += extra
        revival.save()
        connection = mail.get_connection()
        try:
            connection.open()
        except:
            logger.error(u"Connexion error", exc_info=True)
        for target in revival.target_set.select_related('member').filter(created_on__gte=start_on)[:MAX_BATCH_SEND]:
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')
            mail_renderer = import_by_path(revival.mail_renderer)
            subject, html_content = mail_renderer(target, obj, revival)
            if not html_content:
                continue
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            with transaction.atomic(using=WALLETS_DB_ALIAS):
                try:
                    balance.mail_count -= 1
                    balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.save()
                        increment_history_field_many('smart_revival_history', args=profile_tag_list)
                    else:
                        transaction.rollback(using=WALLETS_DB_ALIAS)
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
                except:
                    transaction.rollback(using=WALLETS_DB_ALIAS)
                    logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
            revival.progress += 1
            revival.save()
        else:
            if revival.progress >= revival.total:
                revival.status = COMPLETE
                revival.save()

        try:
            connection.close()
        except:
            pass


def rerun_complete_revivals():
    """
    Re-run Revivals with status = COMPLETE to keep users engaged
    """
    one_week_ago = timezone.now() - timedelta(days=3)
    for revival in Revival.objects.select_related('service').filter(run_on__lte=one_week_ago, status=COMPLETE,
                                                                    is_active=True):
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

        revival.run_on = timezone.now()
        revival.save()
        connection = mail.get_connection()
        try:
            connection.open()
        except:
            logger.error(u"Connexion error", exc_info=True)
        for target in revival.target_set.select_related('member').filter(revival_count__lt=MAX_AUTO_REWARDS).order_by('updated_on')[:MAX_BATCH_SEND]:
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')
            mail_renderer = import_by_path(revival.mail_renderer)
            subject, html_content = mail_renderer(target, obj, revival)
            if not html_content:
                continue
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            with transaction.atomic(using=WALLETS_DB_ALIAS):
                try:
                    balance.mail_count -= 1
                    balance.save()
                    if msg.send():
                        target.revival_count += 1
                        target.save()
                        increment_history_field_many('smart_revival_history', args=profile_tag_list)
                    else:
                        transaction.rollback(using=WALLETS_DB_ALIAS)
                        logger.error("Member %s not notified for Content %s" % (member.email, str(obj)),
                                     exc_info=True)
                except:
                    transaction.rollback(using=WALLETS_DB_ALIAS)
                    logger.error("Member %s not notified for Content %s" % (member.email, str(obj)), exc_info=True)
        else:
            revival.progress += 1
            revival.save()

        try:
            connection.close()
        except:
            pass


if __name__ == '__main__':
    try:
        notify_profiles()
    except:
        logger.error("Fatal error occured, cyclic revivals not run", exc_info=True)
