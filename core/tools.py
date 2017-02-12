# -*- coding: utf-8 -*-

# import os
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikwen.conf.settings")
from django.contrib.auth.models import Group
from ikwen.flatpages.models import FlatPage
from permission_backend_nonrel.models import UserPermissionList
from permission_backend_nonrel.utils import add_user_to_group

from ikwen.accesscontrol.models import COMMUNITY

from ikwen.accesscontrol.models import SUDO

from ikwen.billing.models import InvoicingConfig

from ikwen.accesscontrol.backends import UMBRELLA
from django.template.defaultfilters import slugify
from ikwen.core.utils import get_config_model
from ikwen.accesscontrol.models import Member
from ikwen.core.models import Application, Service


def setup_dev_env(app_name, username, database=None, project_name=None,
                  project_url=None, admin_url=None, base_monthly_cost=0):
    try:
        app = Application.objects.using(UMBRELLA).get(name=app_name)
        app.save(using='default')
    except Application.DoesNotExist:
        slug = slugify(app_name)
        app = Application.objects.using(UMBRELLA).create(name=app_name, slug=slug, version='1.0',
                                                         url=slug + '.com', base_monthly_cost=base_monthly_cost)
        app.save(using='default')
    app = Application.objects.using(UMBRELLA).get(pk=app.id)
    m = Member.objects.using(UMBRELLA).get(username=username)
    if not project_name:
        project_name = app_name
    project_name_slug = slugify(project_name).replace('-', '')
    if not database:
        database = project_name_slug
    domain = project_name_slug + '.test'
    if project_url:
        url = project_url
    else:
        url = 'http://localhost/' + project_name_slug
    if not admin_url:
        admin_url = 'http://localhost/ikwen'
    s = Service.objects.using(UMBRELLA).create(app=app, member=m, project_name=project_name, database=database, url=url,
                                               admin_url=admin_url, project_name_slug=project_name_slug,
                                               monthly_cost=base_monthly_cost, billing_cycle=Service.MONTHLY,
                                               domain=domain, version=Service.FREE)
    s.save(using='default')
    link = s.url.replace('http://', '').replace('https://', '')
    mail_signature = "%s<br>" \
                     "<a href='%s'>%s</a>" % (s.project_name, s.url, link)
    config_model = get_config_model()
    c = config_model.objects.using(UMBRELLA).create(service=s, company_name=project_name, contact_email=m.email,
                                                    company_name_slug=project_name_slug, signature=mail_signature)
    c.save(using='default')
    InvoicingConfig.objects.create(name='Default')
    FlatPage.objects.create(url=FlatPage.AGREEMENT, title=FlatPage.AGREEMENT)
    FlatPage.objects.create(url=FlatPage.LEGAL_MENTIONS, title=FlatPage.LEGAL_MENTIONS)
    Group.objects.create(name=COMMUNITY)
    sudo_group = Group.objects.create(name=SUDO)
    UserPermissionList.objects.create(user=m)
    add_user_to_group(m,  sudo_group)

    if s.id not in m.collaborates_on_fk_list:
        m.collaborates_on_fk_list.append(s.id)
    if s not in m.customer_on_fk_list:
        m.customer_on.append(s.id)
    m.is_superuser = True
    m.is_staff = True
    m.is_iao = True
    m.is_bao = True
    m.save()
    m.business_notices = 0
    m.personal_notices = 0
    m.save(using='default')
    print "\nDev environment successfully created."
    print "Add this to your project settings: IKWEN_SERVICE_ID = '%s'\n\n" % s.pk


def generate_random_key(length):
    import random
    import string
    special_chars = string.punctuation.replace("\\", '').replace("'", '').replace('"', '')
    generated_key = ''.join([random.SystemRandom().choice(string.ascii_letters + string.digits + special_chars)
                             for _ in range(length)])
    return generated_key


def generate_django_secret_key():
    return generate_random_key(50)


# if __name__ == "__main__":
#     import sys
#     if len(sys.argv) < 3:
#         print "At least 2 arguments are required: app_name and username"
#     project_name, database, base_monthly_cost = None, None, 0
#     if len(sys.argv) >= 4:
#         database = sys.argv[3]
#     if len(sys.argv) >= 5:
#         project_name = sys.argv[4]
#     if len(sys.argv) >= 6:
#         base_monthly_cost = sys.argv[5]
#     setup_dev_env(sys.argv[1], sys.argv[2], database, project_name, base_monthly_cost)

