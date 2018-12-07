#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import logging
from datetime import datetime

sys.path.append("/home/libran/virtualenv/lib/python2.7/site-packages")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "conf.settings")

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
    service_list = Service.objects.filter(app=app)
    for service in service_list:
        db = service.database
        add_database(db)
        service_original = Service.objects.using(db).get(pk=service.id)          # Positionnement sur la DB spécifique du client (app)
        set_counters(service_original)                                           # Autocomplétion des "blancs" d'inactivité
        ccm_watch = calculate_watch_info(service_original.customer_history, 3)
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

        subject = _("Community progression report")
        html_content = get_mail_content(subject, template_name='monitoring/community_progression.html',
                                        extra_context=ccm_watch)
        cc = [sudo.email for sudo in Member.objects.using(db).filter(is_superuser=True).exclude(pk=member.id)]
        sender = 'ikwen <no-reply@ikwen.com>'
        msg = EmailMessage(subject, html_content, sender, [member.email])
        msg.content_subtype = "html"
        msg.cc = cc
        msg.send()
        CCMMonitoringMail.objects.create(service=service, subject=subject)


if __name__ == "__main__":
    try:
        send_ccm_report()
    except:
        logger.error("Fatal error occured, cyclic revivals not run", exc_info=True)


