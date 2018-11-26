#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
sys.path.append('/home/ikwen/Cloud/Kakocase/tchopetyamo')

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "conf.settings")
import subprocess

from ikwen.core.models import *
from ikwen.core.utils import *
from ikwen.billing.models import PaymentMean
from ikwen_kakocase.kako.models import *
from ikwen.theming.models import Template, Theme
from ikwen.partnership.models import PartnerProfile
from ikwen.accesscontrol.models import Member
from ikwen.revival.models import ProfileTag

def reload_settings(app_slug, **kwargs):
    app = Application.objects.get(slug=app_slug)
    exclude_list = kwargs.pop('exclude_list', [])
    for s in Service.objects.filter(app=app).exclude(project_name_slug__in=exclude_list):
        # db = s.database
        # add_database(db)
        # PaymentMean.objects.using(db).filter(slug='orange-money').delete()
        # om = PaymentMean.objects.get(slug='orange-money')
        # om.save(using=db)
        # momo = PaymentMean.objects.get(slug='mtn-momo')
        # PaymentMean.objects.using(db).filter(slug='mtn-momo').update(button_img_url=momo.button_img_url)
        settings_template = app_slug + '/cloud_setup/settings.html'
        try:
            s.reload_settings(settings_template, **kwargs)
        except:
            print "Could not reload Project %s" % s.project_name


def add_cashflex_payment_mean(app_slug, **kwargs):
    app = Application.objects.get(slug=app_slug)
    exclude_list = kwargs.pop('exclude_list', [])
    for s in Service.objects.filter(app=app).exclude(project_name_slug__in=exclude_list):
        db = s.database
        add_database(db)
        cashflex = PaymentMean.objects.get(slug='cashflex')
        cashflex.save(using=db)


def update_mtn_momo(app_slug, **kwargs):
    app = Application.objects.get(slug=app_slug)
    exclude_list = kwargs.pop('exclude_list', [])
    momo = PaymentMean.objects.get(slug='mtn-momo')
    for s in Service.objects.filter(app=app).exclude(project_name_slug__in=exclude_list):
        db = s.database
        add_database(db)
        PaymentMean.objects.using(db).filter(slug='mtn-momo').update(watermark=momo.watermark)


def reload_projects(app_slug, cloud_folder_name, **kwargs):
    app = Application.objects.get(slug=app_slug)
    for s in Service.objects.filter(app=app):
        try:
            subprocess.call(['touch', '/home/ikwen/Cloud/%s/%s/conf/wsgi.py' % (cloud_folder_name, s.project_name_slug)])
        except Exception as e:
            print e.message


def set_currency_to_xaf(app_slug, config_model, **kwargs):
    app = Application.objects.get(slug=app_slug)
    exclude_list = kwargs.pop('exclude_list', [])
    for s in Service.objects.filter(app=app).exclude(project_name_slug__in=exclude_list):
        db = s.database
        add_database(db)
        c = config_model.objects.using(db).get(service=s)
        c.currency_code = 'XAF'
        c.currency_symbol = 'XAF'
        c.save()


def activate_orange_money(app_slug, **kwargs):
    app = Application.objects.get(slug=app_slug)
    exclude_list = kwargs.pop('exclude_list', [])
    for s in Service.objects.filter(app=app).exclude(project_name_slug__in=exclude_list):
        db = s.database
        add_database(db)
        PaymentMean.objects.using(db).filter(slug='orange-money').update(is_active=True)


def clear_wallets():
    """
    Removes stalled wallets
    :return:
    """
    for wallet in OperatorWallet.objects.using('wallets').all():
        try:
            Service.objects.get(pk=wallet.nonrel_id)
        except Service.DoesNotExist:
            if wallet.balance <= 0:
                wallet.delete()
            else:
                print "Service not found but wallet found with %d" % wallet.balance


def add_themes_to_retailers_websites():
    for retailer in Service.objects.filter(project_name_slug__in=['dyvixitsolutions1']):
        db = retailer.database
        add_database(db)
        config = PartnerProfile.objects.using(db).get(service=retailer)
        theme = Theme.objects.using(db).get(slug='dreamer')
        config.theme = theme
        config.save(using=db)


def set_member_tags():
    t0 = datetime.now()
    for member in Member.objects.all():
        member.tags = slugify(member.first_name + ' ' + member.last_name).replace('-', ' ')
        member.save()
    duration = datetime.now() - t0
    print "Script run in %ds" % duration.seconds


def update_image_names():
    """
    removes ikwen/ at the beginning of image fields for fields
    accesscontrol.Member.photo
    accesscontrol.Member.cover_image

    core.Config.logo
    core.Config.cover_image

    core.Application.logo

    billing.PaymentMean.logo
    billing.PaymentMean.watermark

    theming.Theme.logo
    theming.Theme.preview
    :return:
    """
    for service in Service.objects.using('umbrella').all():
        db = service.database
        if not db:
            continue
        print "Processing database %s" % db
        add_database(db)

        for app in Application.objects.using(db).all():
            if app.logo.name:
                logo_name = app.logo.name
                new_logo_name = logo_name.replace('ikwen/', '')
                app.logo = new_logo_name
                if logo_name != new_logo_name:
                    print "Renaming %s to %s" % (logo_name, new_logo_name)
                    app.save(using=db)


def populate_event_object_id_list():
    total = ConsoleEvent.objects.all().count()
    chunks = total / 500 + 1
    for i in range(chunks):
        start = i * 500
        finish = (i + 1) * 500
        for event in ConsoleEvent.objects.all()[start:finish]:
            event.object_id_list = [event.object_id]
            event.save()


def send_bulk_sms():
    # fh = open('/home/komsihon/Documents/TCHOPETYAMO/Duvaal_Parents_Test.txt')
    fh = open('/home/ikwen/Clients/Tchopetyamo/Duvaal_Parents.txt')
    t0 = datetime.now()
    n = 1
    for recipient in fh.readlines():
        text = u"Cher parent nous innovons,\n" \
               u"dès 6H30 on s'occupe du pti-dej de vos enfants à Duvaal. " \
               u"En+, bénéficiez de -5% pour toute inscription sur tchopetyamo.com\n" \
               u"697506911"
        send_sms("237" + recipient, text, label='Tchopetyamo')
        n += 1
    diff = datetime.now() - t0
    print "%d SMS sent in %d s" % (n, diff.seconds)


def create_basic_profiles():
    for service in Service.objects.all():
        db = service.database
        add_database(db)
        ProfileTag.objects.using(db).create(name="Men", slug="men", is_reserved=True)
        ProfileTag.objects.using(db).create(name="Women", slug="women", is_reserved=True)


if __name__ == "__main__":
    send_bulk_sms()
