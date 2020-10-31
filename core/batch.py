#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

from daraja.models import Dara

sys.path.append('/home/ikwen/Cloud/Kakocase/tchopetyamo')

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "conf.settings")
import subprocess
import pymongo
from pymongo import MongoClient

from ikwen.core.models import *
from ikwen.core.utils import *
from ikwen.billing.models import PaymentMean
from ikwen_kakocase.kako.models import *
from ikwen.theming.models import Template, Theme
from ikwen.partnership.models import PartnerProfile
from ikwen.accesscontrol.models import Member
from ikwen.revival.models import ProfileTag, Revival, MemberProfile
from ikwen.rewarding.utils import JOIN, REFERRAL


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
            print("Could not reload Project %s" % s.project_name)


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
            print(e.message)


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
                print("Service not found but wallet found with %d" % wallet.balance)


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
    print("Script run in %ds" % duration.seconds)


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
        print("Processing database %s" % db)
        add_database(db)

        for app in Application.objects.using(db).all():
            if app.logo.name:
                logo_name = app.logo.name
                new_logo_name = logo_name.replace('ikwen/', '')
                app.logo = new_logo_name
                if logo_name != new_logo_name:
                    print("Renaming %s to %s" % (logo_name, new_logo_name))
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
    fh = open('/home/ikwen/Contacts_Promote_02_21.csv')
    t0 = datetime.now()
    n = 1
    for line in fh.readlines():
        tk = line.split(',')
        recipient = tk[2]
        if not recipient:
            continue
        text = u"Promote ce sont des opportunités. " \
               u"IKWEN TSUNAMI est la plateforme optimisée pour suivre " \
               u"et fidéliser vos clients.Découvrez et obtenez-la gratuitement.\n" \
               u"656123522"
        send_sms("237" + recipient, text, label='ikwen')
        print("Sending to %s" % recipient)
        n += 1
    diff = datetime.now() - t0
    print("%d SMS sent in %d s" % (n, diff.seconds))


def create_basic_profiles():
    for service in Service.objects.all():
        db = service.database
        add_database(db)
        ProfileTag.objects.using(db).create(name="Men", slug="men", is_reserved=True)
        ProfileTag.objects.using(db).create(name="Women", slug="women", is_reserved=True)


def set_revival_profile_tag_id():
    app = Application.objects.get(slug='kakocase')
    for service in Service.objects.filter(app=app):
        db = service.database
        add_database(db)
        try:
            join_tag = ProfileTag.objects.using(db).get(slug=JOIN)
            Revival.objects.using(db).filter(mail_renderer='ikwen.revival.utils.render_suggest_create_account_mail')\
                .update(profile_tag_id=join_tag.id)
            Revival.objects.using('umbrella').filter(service=service, mail_renderer='ikwen.revival.utils.render_suggest_create_account_mail')\
                .update(profile_tag_id=join_tag.id)
        except ProfileTag.DoesNotExist:
            print("Join tag not found for %s" % service)

        try:
            ref_tag = ProfileTag.objects.using(db).get(slug=REFERRAL)
            Revival.objects.using(db).filter(service=service, mail_renderer='ikwen.revival.utils.render_suggest_referral_mail')\
                .update(profile_tag_id=ref_tag.id)
            Revival.objects.using('umbrella').filter(service=service, mail_renderer='ikwen.revival.utils.render_suggest_referral_mail')\
                .update(profile_tag_id=ref_tag.id)
        except ProfileTag.DoesNotExist:
            print("Referral tag not found for %s" % service)

        Revival.objects.using(db)\
            .exclude(mail_renderer__in=['ikwen.revival.utils.render_suggest_create_account_mail',
                                        'ikwen.revival.utils.render_suggest_referral_mail']).delete()
        Revival.objects.using('umbrella')\
            .exclude(mail_renderer__in=['ikwen.revival.utils.render_suggest_create_account_mail',
                                        'ikwen.revival.utils.render_suggest_referral_mail']).delete()


def move_member_profile_tag_list_to_tag_fk_list():

    for service in Service.objects.all():
        db = service.database
        add_database(db)
        total = MemberProfile.objects.using(db).all().count()
        chunks = total / 500 + 1
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for profile in MemberProfile.objects.using(db).all()[start:finish]:
                if profile.tag_fk_list:
                    continue
                tag_fk_list = []
                for slug in profile.tag_list:
                    try:
                        tag = ProfileTag.objects.using(db).get(slug=slug)
                        tag_fk_list.append(tag.id)
                    except ProfileTag.DoesNotExist:
                        continue
                profile.tag_fk_list = tag_fk_list
                profile.save()


def create_join_and_referral_tag():
    for service in Service.objects.all():
        db = service.database
        add_database(db)

        join, update = ProfileTag.objects.using(db).get_or_create(slug=JOIN)
        join.name = JOIN
        join.is_auto = True
        join.save()

        ref, update = ProfileTag.objects.using(db).get_or_create(slug=REFERRAL)
        ref.name = REFERRAL
        ref.is_auto = True
        ref.save()


def create_index_on_revival():
    import pymongo
    from pymongo import MongoClient
    client = MongoClient('46.101.107.75', 27017)

    for service in Service.objects.all():
        if not service.database:
            continue
        print("Creating index for %s" % service.database)
        db = client[service.database]
        db.revival_revival.create_index([('service', pymongo.ASCENDING),
                                         ('profile_tag_id', pymongo.ASCENDING)], unique=True)
        db.revival_cyclicrevival.drop_index('profile_tag_id_1')
        db.revival_cyclicrevival.create_index([('service', pymongo.ASCENDING),
                                               ('profile_tag_id', pymongo.ASCENDING)], unique=True)


def correct_indexes_on_profiletag():
    import pymongo
    from pymongo import MongoClient
    client = MongoClient('46.101.107.75', 27017)

    for service in Service.objects.all():
        if not service.database:
            continue
        print("Creating index for %s" % service.database)
        db = client[service.database]
        try:
            db.revival_profiletag.drop_index('name_1')
        except:
            print("name_1 index not found on %s" % service.database)
        db.revival_profiletag.create_index([('name', pymongo.ASCENDING), ('is_auto', pymongo.ASCENDING)], unique=True)
        add_database(service.database)
        ProfileTag.objects.using(service.database).filter(is_auto=True).delete()
        for category in ProductCategory.objects.using(service.database).all():
            slug = '__' + category.slug
            ProfileTag.objects.using(service.database).create(name=category.name, slug=slug, is_auto=True)


def clear_ikwen_members_from_tchopetyamo_umbrella():
    delete_list = []
    total = MemberProfile.objects.using('umbrella').all().count()
    chunks = total / 500 + 1
    for i in range(chunks):
        start = i * 500
        finish = (i + 1) * 500
        for member in Member.objects.using('umbrella').all()[start:finish]:
            try:
                Member.objects.get(pk=member.id)
            except Member.DoesNotExist:
                delete_list.append(member.id)
    for pk in delete_list:
        Member.objects.using('umbrella').filter(pk=pk).delete()


def create_index_on_revival():
    client = MongoClient('46.101.107.75', 27017)

    for service in Service.objects.all():
        if not service.database:
            continue
        print("Creating index for %s" % service.database)
        db = client[service.database]
        db.revival_revival.create_index([('service', pymongo.ASCENDING),
                                         ('profile_tag_id', pymongo.ASCENDING)], unique=True)
        db.revival_cyclicrevival.drop_index('profile_tag_id_1')
        db.revival_cyclicrevival.create_index([('service', pymongo.ASCENDING),
                                               ('profile_tag_id', pymongo.ASCENDING)], unique=True)


def create_sent_mail_collection():
    client = MongoClient('46.101.107.75', 27017)

    for service in Service.objects.all():
        if not service.database:
            continue
        print("Creating index for %s" % service.database)
        db = client[service.database]
        db.ikwen_sent_mail.create_index([('to', pymongo.ASCENDING)])
        db.ikwen_sent_mail.create_index([('subject', pymongo.ASCENDING)])
        db.ikwen_sent_mail.create_index([('type', pymongo.ASCENDING)])
        db.ikwen_sent_mail.create_index([('created_on', pymongo.ASCENDING)])


def create_go_links():
    app_list = list(Application.objects.filter(slug__in=['kakocase', 'shavida', 'webnode']))
    for service in Service.objects.filter(app__in=app_list):
        try:
            go_apache_tpl = get_template('core/cloud_setup/apache.conf.local.html')
            apache_context = Context({'home_folder': service.home_folder, 'ikwen_name': service.ikwen_name})
            fh = open(service.home_folder + '/go_apache.conf', 'w')
            fh.write(go_apache_tpl.render(apache_context))
            fh.close()
            vhost = '/etc/apache2/sites-enabled/go_ikwen/' + service.ikwen_name + '.conf'
            subprocess.call(['sudo', 'ln', '-sf', service.home_folder + '/go_apache.conf', vhost])
        except:
            print("Failed for %s" % service)
            continue


def shift_favicons_to_icons():
    """
    Rename favicons folder to icons
    :return:
    """
    cluster_media_root = getattr(settings, 'CLUSTER_MEDIA_ROOT')
    for service in Service.objects.all():
        favicons_folder = cluster_media_root + service.project_name_slug + '/favicons'
        if os.path.exists(favicons_folder):
            icons_folder = cluster_media_root + service.project_name_slug + '/icons'
            try:
                os.rename(favicons_folder, icons_folder)
            except:
                print("Failed to rename %s to %s" % (favicons_folder, icons_folder))


def delete_duplicate_users_from_local_dbs():
    client = MongoClient('46.101.107.75', 27017)

    for service in Service.objects.filter(project_name_slug__in=['xmboa', 'ebonixe', 'maisonnouss', 'deboyshop']):
        db = service.database
        if not db or db == 'ikwen_umbrella_prod':
            continue
        add_database(db)
        delete_list = set()
        total = Member.objects.using(db).all().count()
        chunks = total / 500 + 1
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for member in Member.objects.using(db).all()[start:finish]:
                try:
                    Member.objects.using('umbrella').get(pk=member.id)
                except Member.DoesNotExist:
                    delete_list.add(member.id)
                try:
                    Member.objects.using('umbrella').get(email=member.email)
                except Member.DoesNotExist:
                    delete_list.add(member.id)
                try:
                    Member.objects.using('umbrella').get(phone=member.phone)
                except Member.DoesNotExist:
                    delete_list.add(member.id)
        Member.objects.using(db).filter(pk__in=list(delete_list)).delete()

        dbh = client[db]
        dbh.ikwen_member.create_index([('email', pymongo.ASCENDING)], unique=True)
        dbh.ikwen_member.create_index([('phone', pymongo.ASCENDING)], unique=True)


def set_birthdays():
    for service in Service.objects.filter(project_name_slug='tchopetyamo'):
        db = service.database
        add_database(db)
        total = Member.objects.using(db).filter(dob__isnull=False).count()
        chunks = total / 500 + 1
        for i in range(chunks):
            start = i * 500
            finish = (i + 1) * 500
            for member in Member.objects.using(db).filter(dob__isnull=False)[start:finish]:
                member.birthday = member.dob.strftime('%m%d')
                member.save(using=db)


def set_index_on_dob():
    client = MongoClient('46.101.107.75', 27017)

    app = Application.objects.get(slug='foulassi')
    for service in Service.objects.filter(app=app):
        db = service.database
        if not db:
            continue
        dbh = client[db]
        dbh.foulassi_student.create_index([('dob', pymongo.ASCENDING)])
        dbh.foulassi_student.create_index([('birthday', pymongo.ASCENDING)])

    dbh = client['ikwen_umbrella_prod']
    dbh.foulassi_student.create_index([('dob', pymongo.ASCENDING)])
    dbh.foulassi_student.create_index([('birthday', pymongo.ASCENDING)])


def create_apache_vhost_symlinks():
    for service in Service.objects.all():
        if service.app == 'daraja' and service.project_name_slug != 'daraja':
            continue
        if os.path.exists(service.home_folder + '/go_apache.conf'):
            fh = open(service.home_folder + '/go_apache.conf')
            content = [line.replace('/home/yayatoo/virtualenv/local/lib/python2.7/site-packages', '/home/ikwen/Tools/venv/lib/python2.7/site-packages')
                       for line in fh.readlines()]
            fh.close()
            fh = open(service.home_folder + '/go_apache.conf', 'w')
            fh.writelines(content)
            fh.close()
            subprocess.call(['sudo', 'ln', '-sf', service.home_folder + '/go_apache.conf',
                             '/etc/apache2/sites-enabled/go_apache/' + service.project_name_slug + '.conf'])
        if os.path.exists(service.home_folder + '/apache.conf'):
            fh = open(service.home_folder + '/apache.conf')
            content = [line.replace('/home/yayatoo/virtualenv/local/lib/python2.7/site-packages', '/home/ikwen/Tools/venv/lib/python2.7/site-packages')
                       for line in fh.readlines()]
            fh.close()
            fh = open(service.home_folder + '/apache.conf', 'w')
            fh.writelines(content)
            fh.close()
            subprocess.call(['sudo', 'ln', '-sf', service.home_folder + '/apache.conf',
                             '/etc/apache2/sites-enabled/' + service.domain + '.conf'])
