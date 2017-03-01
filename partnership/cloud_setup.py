# -*- coding: utf-8 -*-
import shutil
import sys
import os

import subprocess
from threading import Thread

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.template import Context
from django.template.defaultfilters import slugify
from django.template.loader import get_template
from permission_backend_nonrel.models import UserPermissionList, GroupPermissionList

from ikwen.accesscontrol.models import SUDO

from ikwen.flatpages.models import FlatPage

from ikwen.conf.settings import STATIC_ROOT, STATIC_URL, MEDIA_ROOT, MEDIA_URL

from ikwen.partnership.models import PartnerProfile

from ikwen.billing.utils import get_next_invoice_number
from django.utils.translation import gettext as _

from ikwen.billing.models import Invoice, NEW_INVOICE_EVENT, PaymentMean, InvoicingConfig, \
    JUMBOPAY_MOMO, IkwenInvoiceItem, InvoiceEntry

from ikwen.core.utils import add_database_to_settings, add_event, get_mail_content

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.models import Service, OperatorWallet

from ikwen.core.tools import generate_django_secret_key, generate_random_key
from datetime import datetime, timedelta

from ikwen_kakocase.kakocase.models import OperatorProfile

__author__ = 'Kom Sihon'

SETUP_MONTHS_COUNT = 6

if getattr(settings, 'LOCAL_DEV', False):
    CLOUD_FOLDER = '/home/komsihon/PycharmProjects/CloudTest/ikwenRetailer/'
else:
    CLOUD_FOLDER = '/home/ikwen/Cloud/ikwenRetailer/'


def deploy(app, member, project_name, monthly_cost, billing_cycle, domain=None, is_pro_version=False):
    project_name_slug = slugify(project_name)  # Eg: slugify('Cool Shop') = 'cool-shop'
    ikwen_name = project_name_slug.replace('-', '')  # Eg: cool-shop --> 'coolshop'
    i = 0
    while True:
        try:
            Service.objects.using(UMBRELLA).get(project_name_slug=ikwen_name)
            i += 1
            ikwen_name = "%s%d" % (ikwen_name, i)
        except Service.DoesNotExist:
            break
    database = ikwen_name
    if not domain:
        domain = ikwen_name + '.ikwen.com'
    admin_url = domain + '/dashboard'
    domain_type = Service.SUB if '.ikwen.com' in domain else Service.MAIN
    now = datetime.now()
    expiry = now + timedelta(days=15)
    service = Service(member=member, app=app, project_name=project_name, project_name_slug=ikwen_name, domain=domain,
                      database=database, url='http://' + domain, domain_type=domain_type, expiry=expiry,
                      admin_url='http://' + admin_url, billing_cycle=billing_cycle,
                      monthly_cost=monthly_cost, version=Service.TRIAL)
    service.save(using=UMBRELLA)

    # Create a copy of template application in the Cloud folder
    app_folder = CLOUD_FOLDER + '000Tpl/AppSkeleton'
    website_home_folder = CLOUD_FOLDER + ikwen_name
    media_root = MEDIA_ROOT + ikwen_name + '/'
    if not os.path.exists(media_root):
        os.makedirs(media_root)
    media_url = MEDIA_URL + ikwen_name + '/'
    if os.path.exists(website_home_folder):
        shutil.rmtree(website_home_folder)
    shutil.copytree(app_folder, website_home_folder)

    # Re-create settings.py file as well as apache.conf file for the newly created project
    secret_key = generate_django_secret_key()
    api_signature = generate_random_key(20)
    allowed_hosts = '%s, www.%s' % (domain, domain)
    settings_tpl = get_template('partnership/cloud_setup/settings.html')
    settings_context = Context({'secret_key': secret_key, 'database': database,
                                'service': service, 'static_root': STATIC_ROOT, 'static_url': STATIC_URL,
                                'media_root': media_root, 'media_url': media_url, 'app_folder': app_folder,
                                'allowed_hosts': allowed_hosts, 'debug': getattr(settings, 'DEBUG', False)})
    fh = open(website_home_folder + '/conf/settings.py', 'w')
    fh.writelines(settings_tpl.render(settings_context))
    fh.close()

    if service.id not in member.collaborates_on_fk_list:
        member.collaborates_on_fk_list.append(service.id)
    if service not in member.customer_on_fk_list:
        member.customer_on.append(service.id)

    member.is_iao = True
    member.save(using=UMBRELLA)

    # Import template database and set it up
    subprocess.call(['mongorestore', '-d', database, CLOUD_FOLDER + '000Tpl/DB'])
    add_database_to_settings(database)

    member.is_bao = True
    member.is_staff = True
    member.is_superuser = True

    app.save(using=database)
    member.save(using=database)

    # Copy payment means to local database
    for mean in PaymentMean.objects.using(UMBRELLA).all():
        if mean.slug == JUMBOPAY_MOMO:
            mean.is_main = True
            mean.is_active = True
        else:
            mean.is_main = False
            if is_pro_version:
                mean.is_active = True
            else:
                mean.is_active = False
        mean.save(using=database)

    FlatPage.objects.using(database).create(url=FlatPage.AGREEMENT, title=FlatPage.AGREEMENT)
    FlatPage.objects.using(database).create(url=FlatPage.LEGAL_MENTIONS, title=FlatPage.LEGAL_MENTIONS)
    for group in Group.objects.using(database).all():
        try:
            gpl = GroupPermissionList.objects.get(group=group)
            group.id = None
            group.save(using=database)   # Recreate the group in the service DB with a new id.
            gpl.group = group    # And update GroupPermissionList object with the newly re-created group
            gpl.save(using=database)
        except GroupPermissionList.DoesNotExist:
            group.id = None
            group.save(using=database)  # Re-create the group in the service DB with anyway.

    # Add member to SUDO Group
    sudo_group = Group.objects.using(database).get(name=SUDO)
    obj_list, created = UserPermissionList.objects.using(database).get_or_create(user=member)
    obj_list.group_fk_list.append(sudo_group.id)
    obj_list.save(using=database)

    OperatorWallet.objects.using('wallets').create(nonrel_id=service.id)
    mail_signature = "%s<br>" \
                     "<a href='%s'>%s</a>" % (project_name, 'http://' + domain, domain)
    config = OperatorProfile(service=service, api_signature=api_signature, is_pro_version=is_pro_version,
                             currency_code='XAF', currency_symbol='XAF', signature=mail_signature)
    config.save(using=UMBRELLA)
    base_config = config.get_base_config()
    base_config.save(using=UMBRELLA)
    service.save(using=database)
    config.save(using=database)
    InvoicingConfig.objects.using(database).create()

    # Apache Server cloud_setup
    if getattr(settings, 'LOCAL_DEV'):
        apache_tpl = get_template('core/cloud_setup/apache.conf.local.html')
    else:
        apache_tpl = get_template('core/cloud_setup/apache.conf.html')
    apache_context = Context({'ikwen_name': ikwen_name})
    fh = open(website_home_folder + '/apache.conf', 'w')
    fh.writelines(apache_tpl.render(apache_context))
    fh.close()

    subprocess.call(['sudo', 'ln', '-sf', website_home_folder + '/apache.conf', '/etc/apache2/sites-enabled/' + domain + '.conf'])
    subprocess.call(['sudo', 'service', 'apache2', 'reload'])

    # Send notification and Invoice to customer
    number = get_next_invoice_number()
    now = datetime.now()
    setup_cost = monthly_cost * SETUP_MONTHS_COUNT
    item = IkwenInvoiceItem(label="ikwen apps retail platform", amount=setup_cost)
    invoice_entries = [InvoiceEntry(item=item, total=setup_cost)]
    invoice = Invoice(subscription=service, amount=setup_cost, number=number, due_date=expiry, last_reminder=now,
                      reminders_sent=1, is_one_off=True, months_count=SETUP_MONTHS_COUNT, entries=invoice_entries)
    invoice.save(using=UMBRELLA)
    add_event(service, NEW_INVOICE_EVENT, member=member, object_id=invoice.id)
    sender = 'ikwen <no-reply@ikwen.com>'
    invoice_url = 'http://www.ikwen.com' + reverse('billing:invoice_detail', args=(invoice.id,))
    subject = _("Your retail platform %s was created" % project_name)
    html_content = get_mail_content(subject, '', template_name='core/cloud_setup/service_activated.html',
                                    extra_context={'service_activated': service, 'invoice': invoice,
                                                   'member': member, 'invoice_url': invoice_url})
    msg = EmailMessage(subject, html_content, sender, [member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg, )).start()
    return service
