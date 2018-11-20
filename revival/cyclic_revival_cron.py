# -*- coding: utf-8 -*-
import os
import logging
from datetime import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")

from currencies.models import Currency

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils.translation import activate, gettext as _

from core.utils import increment_history_field
from echo.models import Balance, SMS
from echo.utils import notify_for_empty_messaging_credit, EMAIL, SMS, EMAIL_AND_SMS
from echo.views import count_pages
from ikwen.conf.settings import WALLETS_DB_ALIAS
from ikwen.accesscontrol.models import Member
from ikwen.core.utils import add_database, get_mail_content, send_sms, get_sms_label, set_counters
from ikwen.core.models import Config
from ikwen.revival.models import MemberProfile, CyclicRevival, CyclicTarget, ProfileTag

logger = logging.getLogger('ikwen.crons')

MAX_BATCH_SEND = 500


def notify_profiles():
    t0 = datetime.now()
    total_mail, total_sms = 0, 0
    logger.debug("Starting cyclic revival")
    today = t0.date()
    queryset = CyclicRevival.objects.select_related('service')\
        .filter(next_run_on=today, hour_of_sending=t0.hour, end_on__gt=today, is_active=True)
    for revival in queryset:
        service = revival.service
        db = service.database
        add_database(db)
        balance = Balance.objects.using(WALLETS_DB_ALIAS).get(service_id=service.id)
        if balance.mail_count == 0 and balance.sms_count == 0:
            notify_for_empty_messaging_credit(service, EMAIL_AND_SMS)
            continue

        label = get_sms_label(service.config)
        notified_empty_mail_credit = False
        notified_empty_sms_credit = False
        member_queryset = Member.objects.using(db).all()
        total = member_queryset.count()
        try:
            profile_tag = ProfileTag.objects.using(db).get(pk=revival.profile_tag_id)
        except ProfileTag.DoesNotExist:
            revival.delete()
            continue
        set_counters(profile_tag)
        chunks = total / 500 + 1
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for member in member_queryset.order_by('date_joined')[start:finish]:
                try:
                    profile = MemberProfile.objects.using(db).get(member=member)
                except MemberProfile.DoesNotExist:
                    continue
                match = set(profile.tag_list) & {profile_tag.slug}
                if len(match) > 0:
                    if member.email:
                        CyclicTarget.objects.get_or_create(revival=revival, member=member)
        revival.set_next_run_date()

        connection = mail.get_connection()
        try:
            connection.open()
        except:
            logger.error(u"Connexion error", exc_info=True)

        for target in revival.cyclictarget_set.select_related('member'):
            member = target.member
            if member.language:
                activate(member.language)
            else:
                activate('en')
            subject = revival.mail_subject
            message = revival.mail_content.replace('$client', member.first_name)
            sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
            try:
                currency = Currency.objects.using(using=db).get(is_base=True)
            except Currency.DoesNotExist:
                currency = None
            extra_context = {
                'revival': revival,
                'currency': currency,
                'media_url': getattr(settings, 'CLUSTER_MEDIA_URL') + service.project_name_slug
            }
            html_content = get_mail_content(subject, message, template_name='revival/mails/default.html',
                                            service=service, extra_context=extra_context)
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"

            if balance.mail_count == 0 and not notified_empty_mail_credit:
                notify_for_empty_messaging_credit(service, EMAIL)
                notified_empty_mail_credit = True
            else:
                with transaction.atomic(using=WALLETS_DB_ALIAS):
                    try:
                        balance.mail_count -= 1
                        balance.save()
                        if msg.send():
                            target.revival_count += 1
                            target.save()
                            total_mail += 1
                            increment_history_field(profile_tag, 'cyclic_revival_mail_history')
                        else:
                            transaction.rollback(using=WALLETS_DB_ALIAS)
                            logger.error("Cyclic revival with subject %s not sent for member %s" % (subject, member.email),
                                     exc_info=True)
                    except:
                        transaction.rollback(using=WALLETS_DB_ALIAS)
            if revival.sms_text:
                if balance.sms_count == 0 and not notified_empty_sms_credit:
                    notify_for_empty_messaging_credit(service, SMS)
                    notified_empty_sms_credit = True
                else:
                    sms_text = revival.sms_text.replace('$client', member.first_name)
                    page_count = count_pages(sms_text)
                    with transaction.atomic(using=WALLETS_DB_ALIAS):
                        try:
                            balance.sms_count -= page_count
                            balance.save()
                            send_sms(recipient=member.phone, text=sms_text, fail_silently=False)
                            total_sms += 1
                            increment_history_field(profile_tag, 'cyclic_revival_sms_history')
                            SMS.objects.create(recipient=member.phone, text=sms_text, label=label)
                        except:
                            transaction.rollback(using=WALLETS_DB_ALIAS)
            if balance.mail_count == 0 and balance.sms_count == 0:
                break
        try:
            connection.close()
        except:
            pass
        diff = datetime.now() - t0
        logger.debug("%d revivals run. %d mails and %d SMS sent in %s" % (queryset.count(), total_mail, total_sms, diff))


if __name__ == '__main__':
    try:
        notify_profiles()
    except:
        logger.error("Fatal error occured, cyclic revivals not run", exc_info=True)