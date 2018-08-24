#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")
import subprocess

from ikwen.core.models import *
from ikwen.core.utils import *
from ikwen.billing.models import PaymentMean
from ikwen_kakocase.kako.models import *
from ikwen.theming.models import Template, Theme
from ikwen.partnership.models import PartnerProfile
from ikwen.cashout.models import CashOutMethod
from ikwen_kakocase.kakocase.models import OperatorProfile as KCOperatorProfile
from ikwen_shavida.shavida.models import OperatorProfile as SVDOperatorProfile
from ikwen.accesscontrol.models import Member


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


def rename_projects_media_root(app_slug, **kwargs):
    app = Application.objects.get(slug=app_slug)
    for s in Service.objects.filter(app=app):
        settings_template = app_slug + '/cloud_setup/settings.html'
        current_media_root = MEDIA_ROOT + s.project_name_slug + '/'
        if s.domain:
            media_root = MEDIA_ROOT + s.domain + '/'
        else:
            print "Could not determine domain name for %s. Skipping ..." % s.project_name_slug
            continue
        try:
            if os.path.exists(current_media_root):
                os.rename(current_media_root, media_root)
                print "%s renamed to %s" % (current_media_root, media_root)
            else:
                continue
            s.reload_settings(settings_template, **kwargs)
            print "Settings reloaded for %s" % str(s)
        except:
            print "Could not reload Project %s. Skipping ..." % s.project_name


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
        # total = Member.objects.using(db).all().count()
        # steps = total / 500 + 1
        # for i in range(steps):
        #     start = i * 500
        #     finish = (i + 1) * 500
        #     for member in Member.objects.using(db).all()[start:finish]:
        #         rename = False
        #         if member.photo.name:
        #             photo_name = member.photo.name
        #             new_photo_name = photo_name.replace('ikwen/', '')
        #             member.photo = new_photo_name
        #             if photo_name != new_photo_name:
        #                 rename = True
        #                 print "Renaming %s to %s" % (photo_name, new_photo_name)
        #         if member.cover_image.name:
        #             cover_image_name = member.cover_image.name
        #             new_cover_image_name = cover_image_name.replace('ikwen/', '')
        #             member.cover_image = new_cover_image_name
        #             if cover_image_name != new_cover_image_name:
        #                 rename = True
        #                 print "Renaming %s to %s" % (cover_image_name, new_cover_image_name)
        #         if rename:
        #             member.save(using=db)
        #
        # for config in Config.objects.using(db).all():
        #     rename = False
        #     if config.logo.name:
        #         logo_name = config.logo.name
        #         new_logo_name = logo_name.replace('ikwen/', '')
        #         config.logo = new_logo_name
        #         if logo_name != new_logo_name:
        #             rename = True
        #             print "Renaming %s to %s" % (logo_name, new_logo_name)
        #     if config.cover_image.name:
        #         cover_image_name = config.cover_image.name
        #         new_cover_image_name = cover_image_name.replace('ikwen/', '')
        #         config.cover_image = new_cover_image_name
        #         if cover_image_name != new_cover_image_name:
        #             rename = True
        #             print "Renaming %s to %s" % (cover_image_name, new_cover_image_name)
        #     if rename:
        #         config.save(using=db)

        # for config in KCOperatorProfile.objects.using(db).all():
        #     rename = False
        #     if config.logo.name:
        #         logo_name = config.logo.name
        #         new_logo_name = logo_name.replace('ikwen/', '')
        #         config.logo = new_logo_name
        #         if logo_name != new_logo_name:
        #             rename = True
        #             print "Renaming %s to %s" % (logo_name, new_logo_name)
        #     if config.cover_image.name:
        #         cover_image_name = config.cover_image.name
        #         new_cover_image_name = cover_image_name.replace('ikwen/', '')
        #         config.cover_image = new_cover_image_name
        #         if cover_image_name != new_cover_image_name:
        #             rename = True
        #             print "Renaming %s to %s" % (cover_image_name, new_cover_image_name)
        #     if rename:
        #         config.save(using=db)
        #
        # for config in SVDOperatorProfile.objects.using(db).all():
        #     rename = False
        #     if config.logo.name:
        #         logo_name = config.logo.name
        #         new_logo_name = logo_name.replace('ikwen/', '')
        #         config.logo = new_logo_name
        #         if logo_name != new_logo_name:
        #             rename = True
        #             print "Renaming %s to %s" % (logo_name, new_logo_name)
        #     if config.cover_image.name:
        #         cover_image_name = config.cover_image.name
        #         new_cover_image_name = cover_image_name.replace('ikwen/', '')
        #         config.cover_image = new_cover_image_name
        #         if cover_image_name != new_cover_image_name:
        #             rename = True
        #             print "Renaming %s to %s" % (cover_image_name, new_cover_image_name)
        #     if rename:
        #         config.save(using=db)

        # for com in CashOutMethod.objects.using(db).all():
        #     if com.logo.name:
        #         logo_name = com.logo.name
        #         new_logo_name = logo_name.replace('ikwen/', '')
        #         com.logo = new_logo_name
        #         if logo_name != new_logo_name:
        #             print "Renaming %s to %s" % (logo_name, new_logo_name)
        #             com.save(using=db)

        for app in Application.objects.using(db).all():
            if app.logo.name:
                logo_name = app.logo.name
                new_logo_name = logo_name.replace('ikwen/', '')
                app.logo = new_logo_name
                if logo_name != new_logo_name:
                    print "Renaming %s to %s" % (logo_name, new_logo_name)
                    app.save(using=db)

        # for mean in PaymentMean.objects.using(db).all():
        #     rename = False
        #     if mean.logo.name:
        #         logo_name = mean.logo.name
        #         new_logo_name = logo_name.replace('ikwen/', '')
        #         mean.logo = new_logo_name
        #         if logo_name != new_logo_name:
        #             rename = True
        #             print "Renaming %s to %s" % (logo_name, new_logo_name)
        #     if mean.watermark.name:
        #         watermark_name = mean.watermark.name
        #         new_watermark_name = watermark_name.replace('ikwen/', '')
        #         mean.watermark = new_watermark_name
        #         if watermark_name != new_watermark_name:
        #             rename = True
        #             print "Renaming %s to %s" % (watermark_name, new_watermark_name)
        #     if rename:
        #         mean.save(using=db)

        # for tpl in Template.objects.using(db).all():
        #     if tpl.preview.name:
        #         preview_name = tpl.preview.name
        #         new_preview_name = preview_name.replace('ikwen/', '')
        #         tpl.preview = new_preview_name
        #         if preview_name != new_preview_name:
        #             print "Renaming %s to %s" % (preview_name, new_preview_name)
        #             tpl.save(using=db)
        #
        # for theme in Theme.objects.using(db).all():
        #     rename = False
        #     if theme.logo.name:
        #         logo_name = theme.logo.name
        #         new_logo_name = logo_name.replace('ikwen/', '')
        #         theme.logo = new_logo_name
        #         if logo_name != new_logo_name:
        #             rename = True
        #             print "Renaming %s to %s" % (logo_name, new_logo_name)
        #     if theme.preview.name:
        #         preview_name = theme.preview.name
        #         new_preview_name = preview_name.replace('ikwen/', '')
        #         theme.preview = new_preview_name
        #         if preview_name != new_preview_name:
        #             rename = True
        #             print "Renaming %s to %s" % (preview_name, new_preview_name)
        #     if rename:
        #         theme.save(using=db)

        # src_cfg = '/home/ikwen/assets_media/%s/ikwen/configs' % service.project_name_slug
        # src_tlg = '/home/ikwen/assets_media/%s/ikwen/theme_logos' % service.project_name_slug
        # dst = '/home/ikwen/assets_media/%s/' % service.project_name_slug
        # subprocess.call(['mv', src_cfg, dst])
        # subprocess.call(['mv', src_tlg, dst])