# -*- coding: utf-8 -*-
import os
import subprocess
from threading import Thread

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.core.urlresolvers import reverse
from django.db import models, router
from django.db import transaction
from django.db.models import get_model
from django.db.models.signals import post_delete
from django.utils import timezone
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext_lazy as _
from django.template.loader import get_template
from django.template import Context
from django_mongodb_engine.contrib import MongoDBManager
from djangotoolbox.fields import ListField

from ikwen.conf.settings import STATIC_ROOT, STATIC_URL, CLUSTER_MEDIA_ROOT, CLUSTER_MEDIA_URL
from ikwen.core.fields import MultiImageField
from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.core.utils import add_database_to_settings, to_dict, get_service_instance, get_config_model


WELCOME_ON_IKWEN_EVENT = 'WelcomeOnIkwen'
CASH_OUT_REQUEST_EVENT = 'CashOutRequest'
CASH_OUT_REQUEST_PAID = 'CashOutRequestPaid'
SERVICE_DEPLOYED = 'ServiceDeployed'

RETAIL_APP_SLUG = 'ikwen-retail'  # Slug of the 'ikwen App retail' Application


class Model(models.Model):
    """
    Helper base Model that defines two fields: created_on and updated_on.
    Both are DateTimeField. updated_on automatically receives the current
    datetime whenever the model is updated in the database
    """
    created_on = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_on = models.DateTimeField(default=timezone.now, auto_now=True, db_index=True)

    def get_from(self, db):
        add_database_to_settings(db)
        return type(self).objects.using(db).get(pk=self.id)

    class Meta:
        abstract = True

    def to_dict(self):
        var = to_dict(self)
        return var


class AbstractWatchModel(Model):
    """
    A Watch model is a model with history fields used to keep progression
    of some data on a daily basis, so to ease the report visualizations.
    """
    counters_reset_on = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        abstract = True

    def to_dict(self):
        var = super(AbstractWatchModel, self).to_dict()
        del(var['counters_reset_on'])
        return var


class Application(AbstractWatchModel):
    LOGOS_FOLDER = 'app_logos'

    PENDING = 'Pending'
    SUBMITTED = 'Submitted'
    REJECTED = 'Rejected'
    ACTIVE = 'Active'
    STATUS_CHOICES = (
        (PENDING, 'Pending'),
        (SUBMITTED, 'Submitted'),
        (REJECTED, 'Rejected'),
        (ACTIVE, 'Active'),
    )

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(unique=True)
    version = models.CharField(max_length=30)
    logo = models.ImageField(upload_to=LOGOS_FOLDER, blank=True, null=True)
    url = models.URLField(max_length=150)
    short_description = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    base_monthly_cost = models.PositiveIntegerField(default=0)
    operators_count = models.PositiveIntegerField(default=0, blank=True)
    deployment_url_name = models.CharField(max_length=100, blank=True, null=True,
                                      help_text=_("Django URL name: <strong>[<em>namespace</em>:]view_name</strong> "
                                                  "of the view that handles deployment of this application."))
    referrer_bind_callback = models.CharField(max_length=150, blank=True, null=True,
                                              help_text=_("Callback to run to actually bind a referrer to a member "
                                                          "in this application."))
    is_public = models.BooleanField(default=True,
                                    help_text=_("If true, the <em>Deploy</em> button appears on the "
                                                "application's description page on ikwen website."))

    turnover_history = ListField(editable=False)
    earnings_history = ListField(editable=False)
    deployment_earnings_history = ListField(editable=False)
    transaction_earnings_history = ListField(editable=False)
    invoice_earnings_history = ListField(editable=False)
    custom_service_earnings_history = ListField(editable=False)
    cash_out_history = ListField(editable=False)

    deployment_count_history = ListField(editable=False)
    transaction_count_history = ListField(editable=False)
    invoice_count_history = ListField(editable=False)
    custom_service_count_history = ListField(editable=False)
    cash_out_count_history = ListField(editable=False)

    total_turnover = models.IntegerField(default=0)
    total_earnings = models.IntegerField(default=0)
    total_deployment_earnings = models.IntegerField(default=0)
    total_transaction_earnings = models.IntegerField(default=0)
    total_invoice_earnings = models.IntegerField(default=0)
    total_custom_service_earnings = models.IntegerField(default=0)
    total_deployment_count = models.IntegerField(default=0)
    total_transaction_count = models.IntegerField(default=0)
    total_invoice_count = models.IntegerField(default=0)
    total_custom_service_count = models.IntegerField(default=0)
    total_cash_out = models.IntegerField(default=0)
    total_cash_out_count = models.IntegerField(default=0)

    class Meta:
        db_table = 'ikwen_application'

    def __unicode__(self):
        return self.name

    def _get_cover_image(self):
        try:
            app_service = Service.objects.get(project_name_slug=self.slug)
            config = Config.objects.get(service=app_service)
            return config.cover_image
        except:
            pass
    cover_image = property(_get_cover_image)


class Service(models.Model):
    """
    An instance of an ikwen :class:`Application` deployed by a :class:`accesscontrol.models.Member`.
    """
    LOGO_PLACEHOLDER = settings.STATIC_URL + 'ikwen/img/logo-placeholder.jpg'
    PENDING = 'Pending'
    SUSPENDED = 'Suspended'
    CANCELED = 'Canceled'
    ACTIVE = 'Active'
    STATUS_CHOICES = (
        (PENDING, _('Pending')),
        (SUSPENDED, _('Suspended')),
        (CANCELED, _('Canceled')),
        (ACTIVE, _('Active'))
    )

    MONTHLY = 'Monthly'
    QUARTERLY = 'Quarterly'
    BI_ANNUALLY = 'Bi-Annually'
    YEARLY = 'Yearly'
    BILLING_CYCLES_CHOICES = (
        (YEARLY, _('Yearly')),
        (BI_ANNUALLY, _('Bi-Annually')),
        (QUARTERLY, _('Quarterly')),
        (MONTHLY, _('Monthly'))
    )

    MAIN = 'Main'
    SUB = 'Sub'
    DOMAIN_TYPE_CHOICES = (
        (MAIN, _('Main')),
        (SUB, _('Sub'))
    )

    FREE = 'Free'
    TRIAL = 'Trial'
    FULL = 'Full'
    VERSION_CHOICES = (
        (FREE, _('Free')),
        (TRIAL, _('Trial')),
        (FULL, _('Full'))
    )
    # Member has null=True because a Service object can be created
    # and bound to a Member later in the code
    member = models.ForeignKey('accesscontrol.Member', blank=True, null=True)
    app = models.ForeignKey(Application, blank=True, null=True)
    project_name = models.CharField(max_length=60,
                                    help_text="Name of the project")
    project_name_slug = models.SlugField(unique=True)
    home_folder = models.CharField(max_length=150, blank=True, null=True, default='',
                                   help_text="The absolute path to website home folder on the server")
    settings_template = models.CharField(max_length=255, blank=True, null=True,
                                         help_text="Template name for generating actual settings of this service")
    database = models.CharField(max_length=150, blank=True)
    domain_type = models.CharField(max_length=15, blank=True, choices=DOMAIN_TYPE_CHOICES)
    domain = models.CharField(max_length=100, unique=True, blank=True, null=True)
    url = models.CharField(max_length=100, blank=True,
                           help_text="URL of the service. WRITE IT WITHOUT A TRAILING SLASH")
    admin_url = models.CharField(max_length=150, blank=True,
                                 help_text=_("URL of the service's admin panel. WRITE IT WITHOUT A TRAILING SLASH"))
    has_ssl = models.BooleanField(default=False,
                                  help_text=_("If true, it means the service has its SSL Certificate installed."))
    is_pwa_ready = models.BooleanField(default=False,
                                       help_text=_("True when everything is set to get the PWA working"))
    api_signature = models.CharField(_("API Signature"), max_length=60, unique=True,
                                     help_text="Use it in your http API calls. More on "
                                               "<a href='http://support.ikwen.com/generic/APISignature'>"
                                               "support.ikwen.com/generic/APISignature</a>")
    billing_plan = models.ForeignKey('billing.CloudBillingPlan', blank=True, null=True)
    billing_cycle = models.CharField(max_length=30, choices=BILLING_CYCLES_CHOICES, default=MONTHLY)
    monthly_cost = models.PositiveIntegerField()
    version = models.CharField(max_length=15, blank=True, choices=VERSION_CHOICES)  # Free, Trial, Full
    status = models.CharField(max_length=15, default=PENDING, choices=STATUS_CHOICES)
    is_public = models.BooleanField(default=True,
                                    help_text=_("If true, the service can appear in ikwen search results."))
    # Date of expiry of the service. The billing system automatically sets it to
    # IkwenInvoice.due_date + IkwenInvoice.tolerance
    # IkwenInvoice in this case is the invoice addressed to client for this Service
    expiry = models.DateField(blank=True, null=True,
                              help_text=_("Date of expiry of the service."))
    since = models.DateTimeField(default=timezone.now)
    updated_on = models.DateTimeField(default=timezone.now, auto_now_add=True)
    retailer = models.ForeignKey('self', blank=True, null=True, related_name='+')

    community_history = ListField(editable=False)
    turnover_history = ListField(editable=False)
    earnings_history = ListField(editable=False)
    transaction_earnings_history = ListField(editable=False)
    invoice_earnings_history = ListField(editable=False)
    custom_service_earnings_history = ListField(editable=False)
    cash_out_history = ListField(editable=False)

    transactional_email_history = ListField(editable=False)
    rewarding_email_history = ListField(editable=False)
    revival_email_history = ListField(editable=False)

    transaction_count_history = ListField(editable=False)
    invoice_count_history = ListField(editable=False)
    custom_service_count_history = ListField(editable=False)
    cash_out_count_history = ListField(editable=False)

    total_community = models.IntegerField(default=0)
    total_turnover = models.IntegerField(default=0)
    total_earnings = models.IntegerField(default=0)
    total_transaction_earnings = models.IntegerField(default=0)
    total_invoice_earnings = models.IntegerField(default=0)
    total_custom_service_earnings = models.IntegerField(default=0)
    total_cash_out = models.IntegerField(default=0)

    total_transaction_count = models.IntegerField(default=0)
    total_invoice_count = models.IntegerField(default=0)
    total_custom_service_count = models.IntegerField(default=0)
    total_cash_out_count = models.IntegerField(default=0)

    total_transactional_email = models.IntegerField(default=0)
    total_rewarding_email = models.IntegerField(default=0)
    total_revival_email = models.IntegerField(default=0)

    counters_reset_on = models.DateTimeField(blank=True, null=True, editable=False)

    objects = MongoDBManager()

    class Meta:
        db_table = 'ikwen_service'
        unique_together = ('app', 'project_name', )

    def _get_ikwen_name(self):
        return self.project_name_slug

    def _set_ikwen_name(self, value):
        self.__dict__['project_name_slug'] = value

    ikwen_name = property(_get_ikwen_name, _set_ikwen_name)

    def _get_go_url(self):
        if self.project_name_slug in ['ikwen', 'foulassi', 'daraja']:
            return 'https://' + self.domain
        return 'https://go.ikwen.com/' + self.project_name_slug
    go_url = property(_get_go_url)

    def __unicode__(self):
        return u'%s: %s' % (self.project_name, self.url)

    def to_dict(self):
        var = to_dict(self)
        basic_config = self.basic_config
        var['logo'] = basic_config.logo.name if basic_config.logo.name else Service.LOGO_PLACEHOLDER
        var['short_description'] = basic_config.short_description
        try:
            del(var['database'])
            del(var['turnover_history'])
            del(var['earnings_history'])
            del(var['transaction_earnings_history'])
            del(var['invoice_earnings_history'])
            del(var['custom_service_earnings_history'])
            del(var['cash_out_history'])
            del(var['transaction_count_history'])
            del(var['invoice_count_history'])
            del(var['custom_service_count_history'])
            del(var['cash_out_count_history'])
        except Exception as e:
            if getattr(settings, 'DEBUG', False):
                raise e
        return var

    def _get_created_on(self):
        return self.since
    created_on = property(_get_created_on)

    def _get_config(self):
        """
        Gets the Service configuration based on the model
        stated in IKWEN_CONFIG_MODEL setting.
        """
        config_model = get_config_model()
        db = router.db_for_read(self.__class__, instance=self)
        config = config_model.objects.using(db).get(service=self)
        return config
    config = property(_get_config)

    def _get_basic_config(self):
        """
        Gets the Config object in UMBRELLA database for this Service
        """
        config = Config.objects.using('umbrella').get(service=self)
        return config
    basic_config = property(_get_basic_config)

    def _get_details(self):
        return "Application: <em>%(app_name)s</em><br>" \
               "Running as: <em>%(project_name)s</em><br>" \
               "On: <em><a href='%(url)s' target='_blank'>%(url)s</a></em>" % {'app_name': self.app.name,
                                                                               'project_name': self.project_name,
                                                                               'url': self.url}
    details = property(_get_details)

    def get_profile_url(self):
        url = reverse('ikwen:company_profile', args=(self.project_name_slug,))
        return ikwenize(url)

    def save(self, *args, **kwargs):
        """
        In real world, this object is replicated in the sub_database for consistency purposes and so will hardly
        be modified from that database since :class:`Service` object is never exposed in the admin interface of the IAO.
        So said the save() method on this object will generally be called when the object is being manipulated
        from the upper Ikwen website itself. The changes made from there must then be replicated to the sub database.

        The replication is made by adding the actual Service database to DATABASES in settings and calling
        save(using=database).
        """
        using = kwargs.pop('using', 'default')
        if getattr(settings, 'IS_IKWEN', False) and using != self.database and self.id:
            # If we are on Ikwen itself, replicate save or update on the current Service database
            add_database_to_settings(self.database)
            super(Service, self).save(using=self.database, *args, **kwargs)
            if not self.id:
                # Upon creation of a Service object. Add the member who owns it in the
                # Service's database as a staff, then increment operators_count for the Service.app
                self.app.operators_count += 1
                self.app.save()
        super(Service, self).save(using=using, *args, **kwargs)

    def _get_wallet(self, provider):
        try:
            wallet = OperatorWallet.objects.using('wallets').get(nonrel_id=self.id, provider=provider)
        except OperatorWallet.DoesNotExist:
            wallet = OperatorWallet.objects.using('wallets').create(nonrel_id=self.id, provider=provider)
        return wallet

    def _get_balance(self):
        balance = 0
        for wallet in OperatorWallet.objects.using('wallets').filter(nonrel_id=self.id):
            balance += wallet.balance
        return balance
    balance = property(_get_balance)

    def raise_balance(self, amount, provider=None):
        from ikwen.billing.mtnmomo.views import MTN_MOMO
        if not provider:
            provider = MTN_MOMO
        wallet = self._get_wallet(provider)
        with transaction.atomic():
            wallet.balance += amount
            wallet.save(using='wallets')

    def lower_balance(self, amount, provider=None):
        from ikwen.billing.mtnmomo.views import MTN_MOMO
        if not provider:
            provider = MTN_MOMO
        wallet = self._get_wallet(provider)
        if wallet.balance < amount:
            raise ValueError("Amount larger than current balance.")
        with transaction.atomic():
            wallet.balance -= amount
            wallet.save(using='wallets')

    def update_domain(self, new_domain, is_naked_domain=True, web_server_config_template=None):
        """
        Update domain of a service to a new one. Rewrites the web server
        config file and reloads it.
        """
        previous_domain = self.domain
        if not web_server_config_template:
            if self.has_ssl:
                web_server_config_template = '%s/cloud_setup/apache_ssl.conf.html' % self.app.slug
            else:
                web_server_config_template = '%s/cloud_setup/apache.conf.html' % self.app.slug
        apache_tpl = get_template(web_server_config_template)
        apache_context = Context({'is_naked_domain': is_naked_domain, 'domain': new_domain, 'ikwen_name': self.project_name_slug})
        fh = open(self.home_folder + '/apache.conf', 'w')
        fh.write(apache_tpl.render(apache_context))
        fh.close()

        if "go.ikwen.com" not in self.url:
            subprocess.call(['sudo', 'unlink', '/etc/apache2/sites-enabled/' + previous_domain + '.conf'])

        self.domain = new_domain
        self.url = 'http://' + new_domain
        self.save(using='umbrella')
        db = self.database
        add_database_to_settings(db)
        self.save(using=db)
        if self.retailer:
            db = self.retailer.database
            add_database_to_settings(db)
            self.save(using=db)

        subprocess.call(['sudo', 'ln', '-sf', self.home_folder + '/apache.conf', '/etc/apache2/sites-enabled/' + new_domain + '.conf'])
        from ikwen.core.tools import reload_server
        Thread(target=reload_server).start()

    def activate_ssl(self, is_naked_domain=True, reload_web_server=False):
        """
        Creates and activates an SSL Certificate for the domain
        """
        if "go.ikwen.com" in self.url:
            return

        subprocess.call(['sudo', 'unlink', '/etc/apache2/sites-enabled/' + self.domain + '.conf'])

        from ikwen.core.log import ikwen_error_log_filename
        eh = open(ikwen_error_log_filename, 'a')
        if is_naked_domain:  # Generate certificate for the raw domain and www
            val = subprocess.call(['sudo', 'certbot', 'certonly', '--apache',
                                   '-d', self.domain, '-d', 'www.' + self.domain], stderr=eh)
        else:
            val = subprocess.call(['sudo', 'certbot', 'certonly', '--apache', '-d', self.domain], stderr=eh)

        if val != 0:
            eh.close()
            raise OSError("Failed to generate and install SSL certificate for %s" % self.domain)
        web_server_config_template = '%s/cloud_setup/apache_ssl.conf.html' % self.app.slug
        apache_tpl = get_template(web_server_config_template)
        apache_context = Context({'is_naked_domain': is_naked_domain, 'domain': self.domain, 'ikwen_name': self.project_name_slug})
        fh = open(self.home_folder + '/apache.conf', 'w')
        fh.write(apache_tpl.render(apache_context))
        fh.close()

        subprocess.call(['sudo', 'ln', '-sf', self.home_folder + '/apache.conf', '/etc/apache2/sites-enabled/' + self.domain + '.conf'])
        self.has_ssl = True
        db = self.database
        add_database_to_settings(db)
        self.save(using='umbrella')
        self.save(using=db)
        if reload_web_server:
            from ikwen.core.tools import reload_server
            Thread(target=reload_server).start()

    def reload_settings(self, settings_template=None, **kwargs):
        """
        Recreate the settings file from settings template and touches
        the WSGI file to cause the server to reload the changes.
        """
        from ikwen.core.tools import generate_django_secret_key

        secret_key = generate_django_secret_key()
        allowed_hosts = '"%s", "www.%s", "ikwen.com", "go.ikwen.com"' % (self.domain, self.domain)
        media_root = CLUSTER_MEDIA_ROOT + self.project_name_slug + '/'
        media_url = CLUSTER_MEDIA_URL + self.project_name_slug + '/'
        c = {'secret_key': secret_key, 'ikwen_name': self.project_name_slug, 'service': self,
             'static_root': STATIC_ROOT, 'static_url': STATIC_URL, 'media_root': media_root, 'media_url': media_url,
             'allowed_hosts': allowed_hosts, 'debug': getattr(settings, 'DEBUG', False)}
        c.update(kwargs)
        if not settings_template:
            if self.settings_template:
                settings_template = self.settings_template
            else:
                settings_template = '%s/cloud_setup/settings.html' % self.app.slug
        settings_tpl = get_template(settings_template)
        fh = open(self.home_folder + '/conf/settings.py', 'w')
        fh.write(settings_tpl.render(Context(c)))
        fh.close()
        subprocess.call(['touch', self.home_folder + '/conf/wsgi.py'])

    def purge(self, config_model_name, db_host=None):
        """
        Deletes the project totally, together with project files, media and databases
        """
        import os
        import shutil
        from ikwen.accesscontrol.models import Member
        from ikwen.accesscontrol.backends import UMBRELLA
        media_root = CLUSTER_MEDIA_ROOT + self.project_name_slug + '/'
        is_naked_domain = "go.ikwen.com" not in self.url
        if is_naked_domain:
            apache_alias = '/etc/apache2/sites-enabled/' + self.domain + '.conf'
            if os.path.exists(apache_alias):
                os.unlink(apache_alias)
        go_apache_alias = '/etc/apache2/sites-enabled/go_ikwen/' + self.project_name_slug + '.conf'
        if os.path.exists(go_apache_alias):
            os.unlink(go_apache_alias)
        if os.path.exists(media_root):
            shutil.rmtree(media_root)
        if os.path.exists(self.home_folder):
            shutil.rmtree(self.home_folder)

        db = self.database
        add_database_to_settings(db)
        ConsoleEvent.objects.filter(service=self).delete()
        group_ids = [group.id for group in Group.objects.using(db).all()]
        for m in Member.objects.using(db).all():
            try:
                m = m.get_from(UMBRELLA)
            except:
                continue
            try:
                m.collaborates_on_fk_list.remove(self.id)
            except ValueError:
                pass
            try:
                m.customer_on_fk_list.remove(self.id)
            except ValueError:
                pass
            for fk in group_ids:
                try:
                    m.group_fk_list.remove(fk)
                except:
                    pass
            m.save(using=UMBRELLA)

        member = self.member
        if len(member.collaborates_on_fk_list) == 0:
            member.is_iao = False
            member.save()

        app = self.app
        app.operators_count = Service.objects.filter(app=app).count() - 1
        app.save()

        from pymongo import MongoClient
        if not db_host:
            db_host = getattr(settings, 'DATABASES')['default'].get('HOST', '127.0.0.1')
        client = MongoClient(db_host, 27017)
        client.drop_database(self.database)

        app_label = config_model_name.split('.')[0]
        model = config_model_name.split('.')[1]
        config_model = get_model(app_label, model)
        retailer = self.retailer
        if retailer:
            add_database_to_settings(retailer.database)
        try:
            config = config_model.objects.get(service=self)
            base_config = config.get_base_config()
            base_config.delete()
            if retailer:
                config_model.objects.using(retailer.database).filter(service=self).delete()
            config.delete()
        except:
            pass
        if retailer:
            Service.objects.using(retailer.database).filter(project_name_slug=self.project_name_slug).delete()
        self.delete()

    def generate_pwa_manifest(self):
        manifest_template = 'core/cloud_setup/manifest.json.html'
        manifest_tpl = get_template(manifest_template)
        config = self.config
        from ikwen.conf.settings import MEDIA_ROOT
        logo_path = MEDIA_ROOT + config.logo.name
        if not os.path.exists(logo_path):
            # TODO: Set a reminder to ask user to upload a 512x512 logo
            pass
        app_name = ' '.join([token.capitalize() for token in self.project_name.split(' ')])
        apache_context = Context({'app_name': app_name, 'short_description': config.short_description})
        fh = open(self.home_folder + '/conf/manifest.json', 'w')
        fh.write(manifest_tpl.render(apache_context))
        fh.close()


class AbstractConfig(Model):
    """
    General configurations of a :class:`Service` that the user can input.
    """
    HTTP_API = 'HTTP_API'
    GSM_MODEM = 'GSM_MODEM'
    SMS_SENDING_METHOD_CHOICES = (
        (HTTP_API, _('HTTP API')),
        (GSM_MODEM, _('GSM Modem')),
    )
    LOGO_UPLOAD_TO = 'configs/logos'
    COVER_UPLOAD_TO = 'configs/cover_images'
    service = models.OneToOneField(Service, related_name='+')
    balance = models.FloatField(_("balance"), default=0)
    company_name = models.CharField(max_length=60, verbose_name=_("Website / Company name"),
                                    help_text=_("Website/Company name as you want it to appear in mails and pages."))
    company_name_slug = models.SlugField(db_index=True)
    address = models.CharField(max_length=150, blank=True, verbose_name=_("Company address"),
                               help_text=_("Your company address."))
    country = models.ForeignKey('core.Country', blank=True, null=True, related_name='+',
                                help_text=_("Country where HQ of the company are located."))
    city = models.CharField(max_length=60, blank=True,
                            help_text=_("City where HQ of the company are located."))
    latitude = models.CharField(max_length=60, blank=True,
                                help_text=_("Latitude of the Company location."))
    longitude = models.CharField(max_length=60, blank=True,
                                 help_text=_("Longitude of the Company location."))
    short_description = models.CharField(max_length=150, blank=True,
                                         help_text=_("Short description of your business <em>(150 chars max.)</em>."))
    description = models.TextField(blank=True,
                                   help_text=_("More detailed description of your business."))
    slogan = models.CharField(max_length=60, blank=True,
                              help_text=_("Your slogan <em>(60 chars max.)</em>."))
    currency_code = models.CharField(max_length=5, default='XAF',
                                     help_text=_("Code of your currency. Eg: <strong>USD, GBP, EUR, XAF,</strong> ..."))
    currency_symbol = models.CharField(max_length=5, default='XAF',
                                       help_text=_("Symbol of your currency, Eg: <strong>$, £, €, XAF</strong>."))
    cash_out_min = models.IntegerField(_("cash-out minimum"), blank=True, null=True,
                                       default=getattr(settings, 'CASH_OUT_MIN', 0),
                                       help_text="Minimum balance that allows cash out.")
    cash_out_rate = models.IntegerField(_("cash-out rate"), blank=True, null=True,
                                        default=getattr(settings, 'CASH_OUT_RATE', 0),
                                        help_text="Fees charged to IAO upon cash out. Rate calculated from amount "
                                                  "on the wallet at the moment of cash out.")
    logo = models.ImageField(upload_to=LOGO_UPLOAD_TO, verbose_name=_("Your logo"), blank=True, null=True, editable=False,
                             help_text=_("Image in <strong>PNG with transparent background</strong> is advised. "
                                         "(Maximum 400 x 400px)"))
    cover_image = models.ImageField(upload_to=COVER_UPLOAD_TO, blank=True, null=True, editable=False,
                                    help_text=_("Cover image used as decoration of company's profile page "
                                                "and also to use on top of the mails. (Max. 800px width)"))
    brand_color = models.CharField(_("Brand color"), max_length=7, default="#ffffff", blank=True, null=True,
                                   help_text=_("HEX code for the color of top bar on mobile devices."))
    signature = models.TextField(blank=True, verbose_name=_("Mail signature"),
                                 help_text=_("Signature on all mails. HTML allowed."))
    invitation_message = models.TextField(_("Invitation message"), blank=True, null=True,
                                          help_text="Message to send to user to invite to register on your platform.")
    welcome_message = models.TextField(blank=True, verbose_name=_("Welcome message"),
                                       help_text="Model of message to send to user upon registration.")
    contact_email = models.EmailField(verbose_name=_("Contact email"),
                                      help_text="Contact email of the company for customers to send inquiries.")
    contact_phone = models.CharField(max_length=60, blank=True, null=True,
                                     help_text=_("Main phone number for your customers to contact you."))
    whatsapp_phone = models.IntegerField(blank=True, null=True,
                                         help_text=_("Phone number to contact you on WhatsApp. Write without +."))
    facebook_link = models.URLField(blank=True,
                                    help_text=_("Facebook link. Eg: https://www.facebook.com/mywebsite"))
    twitter_link = models.URLField(blank=True,
                                   help_text=_("Twitter link. Eg: https://www.twitter.com/mywebsite"))
    youtube_link = models.URLField(blank=True,
                                   help_text=_("Youtube link. Eg: https://www.youtube.com/mywebsite"))
    instagram_link = models.URLField(blank=True,
                                     help_text=_("Instagram link. Eg: https://www.instagram.com/mywebsite"))
    linkedin_link = models.URLField(blank=True,
                                    help_text=_("LinkedIn link. Eg: https://www.linkedin.com/mywebsite"))
    scripts = models.TextField(blank=True,
                               help_text=_("External scripts like <em>Google Analytics tracking code, Facebook Pixels</em>, "
                                           "etc. <br> Please refer to <a href='http://support.ikwen.com/tutorials/external-scripts'> "
                                           "support.ikwen.com/tutorials/external-scripts</a> for detailed instructions on "
                                           "how to add external scripts to your platform."))
    allow_paypal_direct = models.BooleanField(editable=getattr(settings, 'IS_IKWEN', False), default=False,
                                              help_text=_("Check to allow <strong>PayPal Direct Checkout</strong> "
                                                          "that lets user enter his bank card directly."))
    sms_sending_method = models.CharField(max_length='15', verbose_name=_("SMS Sending method"),
                                          choices=SMS_SENDING_METHOD_CHOICES, blank=True,
                                          help_text=_("Method used to send SMS from the platform. If <strong>Modem</strong>, "
                                                      "SMS will be queued and later read by a modem from the remote url "
                                                      "<em>/ikwen/get_queued_sms</em> and sent locally."))
    sms_api_script_url = models.CharField(max_length=255, blank=True, verbose_name=_("Script URL"),
                                          help_text=_("Model of SMS script url with parameters values written as <strong>$parameter</strong>. "
                                                      "They will be replaced when sending. "
                                                      "Eg: <em>http://smsapi.org/?user=<strong>&lt;APIUsername&gt;</strong>&password=<strong>&lt;APIPassword&gt;</strong>"
                                                      "&sender_param=<strong>$label</strong>&recipient_param=<strong>$recipient</strong>&text_param=<strong>$text</strong></em>"))
    is_pro_version = models.BooleanField(_("pro version"), default=False,
        help_text=_("Standard version uses <strong>ikwen</strong> payment accounts (PayPal, MobileMoney, "
                    "BankCard, etc.) and collects user's money upon purchases. He can later request a Cash-out and "
                    "his money will be sent to him by any mean."
                    "Pro version users can access more advanced configuration options like:"
                    "<ul><li>Personal Payment accounts (Personal PayPal, Personal Mobile Money, etc.)</li>"
                    "<li>Set the Checkout minimum without restriction</li>"
                    "<li>Technical tools like configuring their own Google Analytics scripts, etc.</li></ul>"))
    is_standalone = models.BooleanField(default=False,
                                        help_text=_("If checked, the service is considered to be running in total "
                                                    "isolation from ikwen platform and thus has his own umbrella "
                                                    "database and all links point internally; no link to ikwen.com"))
    register_with_email = models.BooleanField(default=True,
                                              help_text=_("If checked, visitors will be asked for email upon "
                                                          "registration."))
    register_with_dob = models.BooleanField(default=False,
                                            help_text=_("If checked, visitors will be asked for date of birth upon "
                                                        "registration."))
    decimal_precision = models.IntegerField(default=2)
    can_manage_currencies = models.BooleanField(default=False)
    last_currencies_rates_update = models.DateTimeField(editable=False, null=True)
    registration_number = models.CharField(_("Company registration number"), max_length=60, blank=True, null=True)
    taxpayer_number = models.CharField(_("Taxpayer number"), max_length=60, blank=True, null=True)

    class Meta:
        verbose_name_plural = _("Configurations of the platform")
        abstract = True

    def __unicode__(self):
        return 'Config ' + str(self.service)

    def get_base_config(self):
        """
        Acts like a casting operator that returns a :class:`Config` version of
        IKWEN_CONFIG_MODEL. That *simpler* Config object is used by ikwen to render a
        CompanyProfile page rather than a Configuration object from any model of the
        application powering the project which Profile page is being rendered.

        Applications using a custom Config model (extending AbstractBaseConfig) must
        save a :class:`Config` object in the UMBRELLA database.

        Assuming that you create an ikwen application which uses a custom
        Config model defined as such

        class MyAppCustomConfig(AbstractBaseConfig):
            custom_var = models.CharField(max_length=30)
            ...

        When you save an instance of MyAppCustomConfig model, save a Config model also. Do it this way:

        custom_config = MyAppCustomConfig()
        custom_config.custom_var = 'Custom value'
        custom_config.save()
        base_config = custom_config.get_base_config()
        base_config.save(using=UMBRELLA)
        """
        try:
            from ikwen.accesscontrol.backends import UMBRELLA
            config = Config.objects.using(UMBRELLA).get(service=self.service)
        except Config.DoesNotExist:
            config = Config(service=self.service)
        config.company_name = self.company_name
        config.company_name_slug = self.company_name_slug
        config.short_description = self.short_description
        config.description = self.description
        config.slogan = self.slogan
        config.invitation_message = self.invitation_message
        config.logo = self.logo
        config.latitude = self.latitude
        config.longitude = self.longitude
        config.cover_image = self.cover_image
        config.signature = self.signature
        config.contact_email = self.contact_email
        config.contact_phone = self.contact_phone
        config.cash_out_min = self.cash_out_min
        config.cash_out_rate = self.cash_out_rate
        config.currency_code = self.currency_code
        config.currency_symbol = self.currency_symbol
        return config

    def save(self, *args, **kwargs):
        super(AbstractConfig, self).save(*args, **kwargs)
        if type(self) is not Config:  # If it is any descending class
            from ikwen.accesscontrol.backends import UMBRELLA
            base_config = self.get_base_config()
            base_config.save(using=UMBRELLA)

    def raise_balance(self, amount, provider=None):
        self.service.raise_balance(amount, provider)

    def lower_balance(self, amount, provider=None):
        self.service.lower_balance(amount, provider)


class Config(AbstractConfig):
    """
    Default Configurations options derived from :class:`AbstractConfig`.
    It Adds nothing to :class:`AbstractConfig`. Its only purpose is to
    create a concrete class.
    """

    class Meta:
        db_table = 'ikwen_config'

    def save(self, *args, **kwargs):
        using = kwargs.pop('using', 'default')
        if getattr(settings, 'IS_IKWEN', False):
            db = self.service.database
            add_database_to_settings(db)
            try:
                obj_mirror = Config.objects.using(db).get(pk=self.id)
                obj_mirror.currency_code = self.currency_code
                obj_mirror.currency_symbol = self.currency_symbol
                obj_mirror.cash_out_min = self.cash_out_min
                obj_mirror.cash_out_rate = self.cash_out_rate
                obj_mirror.is_pro_version = self.is_pro_version
                obj_mirror.is_standalone = self.is_standalone
                obj_mirror.can_manage_currencies = self.can_manage_currencies
                obj_mirror.sms_api_script_url = self.sms_api_script_url
                super(Config, obj_mirror).save(using=db)
            except Config.DoesNotExist:
                pass
        super(Config, self).save(using=using)


class OperatorWallet(Model):
    nonrel_id = models.CharField(max_length=24)
    provider = models.CharField(max_length=60,
                                help_text="Wallet operator from which we collected the money. "
                                          "It is actually the slug of the PaymentMean.")
    balance = models.FloatField(_("balance"), default=0)

    class Meta:
        db_table = 'ikwen_operator_wallet'
        unique_together = 'nonrel_id', 'provider'

    def _get_payment_mean(self):
        from ikwen.billing.models import PaymentMean
        try:
            return PaymentMean.objects.get(slug=self.provider)
        except PaymentMean.DoesNotExist:
            pass
    payment_mean = property(_get_payment_mean)


class Country(Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    iso2 = models.CharField(max_length=2, unique=True, db_index=True)
    iso3 = models.CharField(max_length=3, unique=True, db_index=True)

    def __unicode__(self):
        return self.name

    class Meta:
        db_table = 'ikwen_country'


class ConsoleEventType(Model):
    """
    Type of events targeted to the Member console.

    :attr:`app` :class:`Application` this type of event applies to.
    :attr:`codename`
    :attr:`title`
    :attr:`title_mobile` Title to use on mobile devices.
    :attr:`target_url_name` Name of the url to hit to view the list of objects that triggered
                            this event. It is typically used to create the *View all* link
    :attr:`renderer` dotted name of the function to call to render an event of this type the :attr:`member` Console.
    :attr:`min_height` the min height space the browser should reserve to display this event.
                       It helps have a smoother rendering of the timeline as it loads.
    Write it under the dotted form 'package.module.function_name'. :attr:`renderer`
    is called as such: function_name(service, event_type, member, object_id, model)
    """
    BUSINESS = 'Business'
    PERSONAL = 'Personal'
    TARGET_CHOICES = (
        (BUSINESS, 'Business'),
        (PERSONAL, 'Personal')
    )
    app = models.ForeignKey(Application, blank=True, null=True)
    codename = models.CharField(max_length=150)
    title = models.CharField(max_length=150, blank=True)
    title_mobile = models.CharField(max_length=100, blank=True)
    target_url_name = models.CharField(max_length=100, blank=True)
    renderer = models.CharField(max_length=255)
    min_height = models.IntegerField(max_length=255, blank=True, null=True)

    objects = MongoDBManager()

    class Meta:
        db_table = 'ikwen_console_event_type'
        unique_together = (
            ('app', 'codename'),
        )

    def __unicode__(self):
        return self.codename

    def get_responsive_title(self, request):
        if request.user_agent.is_mobile and self.title_mobile:
            return self.title_mobile
        return self.title


class ConsoleEvent(Model):
    """
    An event targeted to the Member console.

    :attr:`service` :class:`Service` from which event was fired. It helps retrieve Application and IA0.
    :attr:`member` :class:`Member` to which the event is aimed at.
    :attr:`group_id` Id of group targeted by this event. Note that this group is defined
                     in the service's database and not on ikwen's database. ikwen keeps
                     track of groups of members in their different *Services*.
    :attr:`event_type` :class:`ConsoleEventType` for this event.
    Events of the same type will be grouped under a same :attr:`ConsoleEventType.title`

    :attr:`object_id` id of the object involved in the :attr:`service` database
    """
    PENDING = 'Pending'
    PROCESSED = 'Processed'
    service = models.ForeignKey(Service, related_name='+', default=get_service_instance, db_index=True)
    member = models.ForeignKey('accesscontrol.Member', db_index=True, blank=True, null=True)
    group_id = models.CharField(max_length=24, blank=True, null=True)
    event_type = models.ForeignKey(ConsoleEventType, related_name='+')
    model = models.CharField(max_length=100, blank=True, null=True)
    object_id = models.CharField(max_length=24, blank=True, null=True, db_index=True)
    object_id_list = ListField()

    class Meta:
        db_table = 'ikwen_console_event'

    def render(self, request=None):
        renderer = import_by_path(self.event_type.renderer)
        return renderer(self, request)

    def to_dict(self):
        var = to_dict(self)
        service = self.service
        config = service.config
        var['project_url'] = service.go_url
        var['project_name'] = service.project_name
        var['project_logo_url'] = config.logo.url if config.logo.name else ''
        var['created_on'] = naturaltime(self.created_on)
        var['min_height'] = self.event_type.min_height
        del(var['model'])
        del(var['object_id'])
        del(var['service_id'])
        del(var['member_id'])
        del(var['group_id'])
        del(var['event_type_id'])
        return var


class QueuedSMS(Model):
    recipient = models.CharField(max_length=18)
    text = models.TextField()

    class Meta:
        db_table = 'ikwen_queued_sms'


class Photo(models.Model):
    UPLOAD_TO = 'photos'
    image = MultiImageField(upload_to=UPLOAD_TO, max_size=800)

    def delete(self, *args, **kwargs):
        try:
            os.unlink(self.image.path)
            os.unlink(self.image.small_path)
            os.unlink(self.image.thumb_path)
        except:
            pass
        super(Photo, self).delete(*args, **kwargs)

    def __unicode__(self):
        return self.image.url


class XEmailObject(models.Model):
    """
    An outbound email issued by a Service. Useful to log
    outgoing emails from the actual Service
    """
    TRANSACTIONAL = "Transactional"
    REWARDING = "Rewarding"
    REVIVAL = "Revival"
    TYPE_CHOICES = (
        (TRANSACTIONAL, _("Transactional")),
        (REWARDING, _("Continuous Rewarding")),
        (REVIVAL, _("Revival")),
    )
    to = models.CharField(max_length=255, db_index=True)
    cc = models.CharField(max_length=255, blank=True, null=True)
    bcc = models.CharField(max_length=255, blank=True, null=True)
    subject = models.CharField(max_length=255, db_index=True)
    body = models.TextField()
    status = models.TextField(db_index=True)  # "OK" if mail sent.
    type = models.CharField(max_length=30, choices=TYPE_CHOICES, default=TRANSACTIONAL, db_index=True)
    created_on = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        db_table = 'ikwen_sent_email'

    def __unicode__(self):
        return self.to


class Module(Model):
    """
    Any application module that might be integrated to 
    a website. Eg. Blog, Donate, Subscriptions
    """
    UPLOAD_TO = 'modules'
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to=UPLOAD_TO, null=True,
                             help_text="Logo of the module (100px x 100px).")
    monthly_cost = models.FloatField(default=0,
                                     help_text="What user pays monthly for this module.")
    description = models.TextField(blank=True, null=True)
    title = models.CharField(max_length=30,
                             help_text="Title that appears in the menu bar of the website")
    image = MultiImageField(upload_to=UPLOAD_TO, max_size=800, null=True,
                            help_text="Image on the module page as the visitor will see it. "
                                      "Used to decorate or/and give more explanations.")
    content = models.TextField(blank=True, null=True,
                               help_text="Text on the module page as the visitor will see it. "
                                         "Can be used to give some explanations")
    is_active = models.BooleanField(default=False,
                                    help_text="Check/Uncheck to turn the module Active/Inactive")
    is_pro = models.BooleanField(default=True,
                                 help_text="Designates whether this modules is available "
                                           "only to PRO version websites")
    config_model_name = models.CharField(max_length=100, blank=True, null=True,
                                         help_text="Model name of the config for this module.")
    config_model_admin = models.CharField(max_length=100, blank=True, null=True,
                                          help_text="Model Admin of the config for this module.")
    url_name = models.CharField(max_length=60,
                                help_text="Django url name of the module "
                                          "Meaning a name under the form [namespace:]url_name")
    homepage_section_renderer = models.CharField(max_length=100,
                                                 help_text="Function that renders the module as "
                                                           "a homepage section.")

    class Meta:
        db_table = 'ikwen_module'

    def __unicode__(self):
        return self.name

    def _get_config_model(self):
        tokens = self.config_model_name.split('.')
        model = get_model(tokens[0], tokens[1])
        return model
    config_model = property(_get_config_model)

    def _get_config(self):
        try:
            return self.config_model._default_manager.all()[0]
        except IndexError:
            pass
    config = property(_get_config)

    def render(self, request=None):
        renderer = import_by_path(self.homepage_section_renderer)
        return renderer(self, request)


def delete_object_events(sender, **kwargs):
    """
    Receiver of the post_delete signal that also deletes any ConsoleEvent
    targeting the recently deleted object. This to ensure that we do not
    attempt to render an event which matching object was deleted and thus
    causing an error on the Console.
    """
    if sender == ConsoleEvent:  # Avoid unending recursive call
        return
    instance = kwargs['instance']
    from ikwen.accesscontrol.backends import UMBRELLA

    ConsoleEvent.objects.using(UMBRELLA).filter(object_id=instance.pk).delete()


post_delete.connect(delete_object_events, dispatch_uid="object_post_delete_id")
