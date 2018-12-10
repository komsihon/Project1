#!/usr/bin/env python

import os
import sys
import logging
from datetime import datetime


sys.path.append("/home/libran/virtualenv/lib/python2.7/site-packages")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")

from django.core import mail
from django.core.mail import EmailMessage
from django.utils.translation import activate, gettext as _
from ikwen.core.utils import get_mail_content, calculate_watch_info, add_database, set_counters
from ikwen.core.models import Application, Service
from ikwen.accesscontrol.models import Member
from ikwen.revival.models import CCMMonitoringMail

from ikwen.core.log import CRONS_LOGGING
logging.config.dictConfig(CRONS_LOGGING)
logger = logging.getLogger('ikwen.crons')


def send_ccm_report():
    app = Application.objects.get(slug='kakocase')
    service_list = Service.objects.select_related('member').filter(app=app)

    connection = mail.get_connection()
    try:
        connection.open()
    except:
        logger.error("CCM Report: Connexion error", exc_info=True)

    for service in service_list:
        try:
            db = service.database
            add_database(db)
            try:
                service_original = Service.objects.using(db).get(pk=service.id)
            except Service.DoesNotExist:
                continue
            set_counters(service_original)
            ccm_watch = calculate_watch_info(service_original.community_history, 3)
            member = service.member
            if member.language:
                activate(member.language)
            else:
                activate('en')
            try:
                last_mail = CCMMonitoringMail.objects.filter(service=service).order_by('-id')[0]
            except IndexError:
                last_mail = None
            if last_mail:
                now = datetime.now()
                diff = now - last_mail.created_on
                if diff.days <= 2:
                    if ccm_watch['change_rate'] < 100:
                        continue

            ccm_watch['total_member_count'] = Member.objects.using(db).all().count()
            ccm_watch['last_mail'] = last_mail
            ccm_watch['service_name'] = service.project_name

            subject = _("Community progression report")
            html_content = get_mail_content(subject, template_name='monitoring/mails/community_progression.html',
                                            extra_context=ccm_watch)
            cc = [sudo.email for sudo in Member.objects.using(db).filter(is_superuser=True).exclude(pk=member.id)]
            sender = 'ikwen <no-reply@ikwen.com>'
            msg = EmailMessage(subject, html_content, sender, [member.email])
            msg.content_subtype = "html"
            msg.cc = cc
            if not msg.send():
                logger.error("CCM Report not sent to %s for service %s" % (member.email, service), exc_info=True)
            CCMMonitoringMail.objects.create(service=service, subject=subject)
        except:
            logger.error("Could not process CCM Monitoring for service %s" % service, exc_info=True)
            continue

    try:
        connection.close()
    except:
        pass


if __name__ == "__main__":
    try:
        send_ccm_report()
    except:
        logger.error("Fatal error occured, CCM Monitoring not run", exc_info=True)


