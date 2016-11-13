# -*- coding: utf-8 -*-
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.core.cache import cache
from django.core.urlresolvers import reverse
from django.db import models, router
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.module_loading import import_by_path
from django.utils.translation import gettext_lazy as _
from django_mongodb_engine.contrib import MongoDBManager

from ikwen.foundation.core.utils import add_database_to_settings, to_dict, get_service_instance, get_config_model


WELCOME_ON_IKWEN_EVENT = 'WelcomeOnIkwen'


class Model(models.Model):
    created_on = models.DateTimeField(default=timezone.now)
    updated_on = models.DateTimeField(default=timezone.now, auto_now=True)

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


class Application(Model):
    LOGOS_FOLDER = 'ikwen/app_logos'

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

    class Meta:
        db_table = 'ikwen_application'

    def __unicode__(self):
        return self.name


class Service(models.Model):
    """
    An instance of an Ikwen :class:`Application` that a :class:`Member` is operating.
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
        (MONTHLY, _('Monthly')),
        (QUARTERLY, _('Quarterly')),
        (BI_ANNUALLY, _('Bi-Annually')),
        (YEARLY, _('Yearly'))
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
    project_name_slug = models.SlugField()
    database = models.CharField(max_length=150, blank=True)
    domain_type = models.CharField(max_length=15, blank=True, choices=DOMAIN_TYPE_CHOICES)
    url = models.URLField(blank=True,
                          help_text="URL of the service. WRITE IT WITHOUT A TRAILING SLASH")
    admin_url = models.URLField(blank=True,
                                help_text=_("URL of the service's admin panel. WRITE IT WITHOUT A TRAILING SLASH"))
    billing_cycle = models.CharField(max_length=30, choices=BILLING_CYCLES_CHOICES, blank=True)
    monthly_cost = models.PositiveIntegerField()
    version = models.CharField(max_length=15, blank=True, choices=VERSION_CHOICES)  # Free, Trial, Full
    status = models.CharField(max_length=15, default=PENDING, choices=STATUS_CHOICES)
    # Date of expiry of the service. The billing system automatically sets it to
    # IkwenInvoice.due_date + IkwenInvoice.tolerance
    # IkwenInvoice in this case is the invoice addressed to client for this Service
    expiry = models.DateTimeField(blank=True, null=True,
                                  help_text=_("Date of expiry of the service."))
    invoice_tolerance = models.IntegerField(default=1,
                                            help_text=_("Number of overdue days allowed. "
                                                        "After that, severe action must be undertaken."))
    since = models.DateTimeField(default=timezone.now)
    updated_on = models.DateTimeField(default=timezone.now, auto_now_add=True)

    objects = MongoDBManager()

    class Meta:
        db_table = 'ikwen_service'
        unique_together = ('app', 'project_name', )

    def __unicode__(self):
        return u'%s: %s' % (self.project_name, self.member.email)

    def to_dict(self):
        var = to_dict(self)
        config = self.config
        var['logo'] = config.logo.url if config.logo.name else Service.LOGO_PLACEHOLDER
        var['short_description'] = config.short_description
        return var

    def _get_created_on(self):
        return self.since
    created_on = property(_get_created_on)

    def _get_config(self):
        config_model = get_config_model()
        db = router.db_for_read(self.__class__, instance=self)
        config = cache.get(self.id + ':config:' + db)
        if config:
            return config
        config = config_model.objects.using(db).get(service=self)
        cache.set(self.id + ':config:' + db, config)
        return config
    config = property(_get_config)

    def _get_details(self):
        return "Application: <em>%(app_name)s</em><br>" \
               "Running as: <em>%(project_name)s</em><br>" \
               "On: <em>%(url)s</em>" % {'app_name': self.app.name, 'project_name': self.project_name, 'url': self.url}
    details = property(_get_details)

    def get_profile_url(self):
        from ikwen.foundation.core.views import IKWEN_BASE_URL
        return IKWEN_BASE_URL + reverse('ikwen:company_profile', args=(self.app.slug, self.project_name_slug))

    def save(self, *args, **kwargs):
        """
        In real world, this object is replicated in the sub_database for consistency purposes and so will hardly
        be modified from that database since :class:`Service` object is never exposed in the admin interface of the IAO.
        So said the save() method on this object will generally be called when the object is being manipulated
        from the upper Ikwen website itself. The changes made from there must then be replicated to the sub database.

        The replication is made by adding the actual Service database to DATABASES in settings and calling
        save(using=database).
        """
        using = 'default'
        if kwargs.get('using'):
            using = kwargs['using']
            del(kwargs['using'])
        if getattr(settings, 'IS_IKWEN', False):
            # If we are on Ikwen itself, replicate save or update on the current Service database
            add_database_to_settings(self.database)
            if not self.id:
                # Upon creation of a Service object. Add the member who owns it in the
                # Service's database as a staff, then increment operators_count for the Service.app
                self.app.operators_count += 1
                self.app.save()
            super(Service, self).save(using=self.database, *args, **kwargs)
        super(Service, self).save(using=using, *args, **kwargs)


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
    LOGO_UPLOAD_TO = 'ikwen/configs/logos'
    COVER_UPLOAD_TO = 'ikwen/configs/cover_images'
    service = models.OneToOneField(Service, editable=False, related_name='+')
    company_name = models.CharField(max_length=60, verbose_name=_("Website / Company name"),
                                    help_text=_("Website/Company name as you want it to appear in mails and pages."))
    company_name_slug = models.SlugField(db_index=True)
    address = models.CharField(max_length=150, blank=True, verbose_name=_("Company address"),
                               help_text=_("Your company address."))
    country = models.ForeignKey('core.Country', blank=True, null=True, related_name='+',
                                help_text=_("Country where HQ of the company are located."))
    city = models.CharField(max_length=60, blank=True,
                            help_text=_("City where HQ of the company are located."))
    short_description = models.CharField(max_length=150, blank=True,
                                         help_text=_("Short description of your business <em>(150 chars max.)</em>."))
    description = models.TextField(blank=True,
                                   help_text=_("More detailed description of your business."))
    slogan = models.CharField(max_length=18, blank=True,
                              help_text=_("Your slogan <em>(18 chars max.)</em>."))
    currency_code = models.CharField(max_length=5, default='USD',
                                     help_text=_("Code of your currency. Eg: <strong>USD, GBP, EUR, XAF,</strong> ..."))
    currency_symbol = models.CharField(max_length=5, default='$',
                                       help_text=_("Symbol of your currency, Eg: <strong>$, £, €, F</strong>."))
    logo = models.ImageField(upload_to=LOGO_UPLOAD_TO, verbose_name=_("Your logo"), blank=True, null=True,
                             help_text=_("Image in <strong>PNG with transparent background</strong> is advised. "
                                         "(Maximum 400 x 400px)"))
    cover_image = models.ImageField(upload_to=COVER_UPLOAD_TO, blank=True, null=True,
                                    help_text=_("Cover image used as decoration of company's profile page "
                                                "and also to use on top of the mails. (Max. 800px width)"))
    signature = models.TextField(blank=True, verbose_name=_("Mail signature"),
                                 help_text=_("Signature on all mails. HTML allowed."))
    welcome_message = models.TextField(blank=True, verbose_name=_("Welcome message"),
                                       help_text="Model of message to send to user upon registration.")
    contact_email = models.EmailField(verbose_name=_("Contact email"),
                                      help_text="Contact email of the company for customers to send inquiries.")
    contact_phone = models.CharField(max_length=30, blank=True,
                                     help_text=_("Main phone number for your customers to contact you."))
    facebook_link = models.URLField(blank=True,
                                    help_text=_("Facebook link. Eg: https://www.facebook.com/mywebsite"))
    twitter_link = models.URLField(blank=True,
                                   help_text=_("Twitter link. Eg: https://www.twitter.com/mywebsite"))
    google_plus_link = models.URLField(blank=True,
                                       help_text=_("Google+ link. Eg: https://www.googleplus.com/mywebsite"))
    youtube_link = models.URLField(blank=True,
                                   help_text=_("Youtube link. Eg: https://www.youtube.com/mywebsite"))
    instagram_link = models.URLField(blank=True,
                                     help_text=_("Instagram link. Eg: https://www.instagram.com/mywebsite"))
    tumblr_link = models.URLField(blank=True,
                                  help_text=_("Tumblr link. Eg: https://www.tumblr.com/mywebsite"))
    linkedin_link = models.URLField(blank=True,
                                    help_text=_("LinkedIn link. Eg: https://www.linkedin.com/mywebsite"))
    scripts = models.TextField(blank=True,
                               help_text=_("External scripts like <em>Google Analytics tracking code, Facebook Pixels</em>, "
                                           "etc. <br> Please refer to <a href='http://support.ikwen.com/tutorials/external-scripts'> "
                                           "support.ikwen.com/tutorials/external-scripts</a> for detailed instructions on "
                                           "how to add external scripts to your platform."))
    paypal_user = models.CharField(_("Username for PayPal API"), max_length=60, blank=True)
    paypal_password = models.CharField(_("PayPal password"), max_length=60, blank=True)
    paypal_api_signature = models.CharField(_("PayPal API Signature"), max_length=60, blank=True)
    paypal_merchant_id = models.CharField(_("PayPal Merchant ID"), max_length=60, blank=True)
    # allow_paypal_direct = models.BooleanField(default=False, verbose_name=_("PAYPAL API SIGNATURE"),
    #                                           help_text=_("Check to allow PayPal direct Checkout that allows user "
    #                                                       "to enter his bank card directly."))
    sms_sending_method = models.CharField(max_length='15', verbose_name=_("SMS Sending method"),
                                          choices=SMS_SENDING_METHOD_CHOICES, blank=True,
                                          help_text=_("Method used to send SMS from the platform. If <strong>Modem</strong>, "
                                                      "SMS will be queued and later read by a modem from the remote url "
                                                      "<em>/ikwen/get_queued_sms</em> and sent locally."))
    sms_api_script_url = models.CharField(max_length=255, blank=True, verbose_name=_("Script URL"),
                                          help_text=_("Model of SMS script url with parameters values written as <strong>$parameter</strong>. "
                                                      "They will be replaced when sending. "
                                                      "Eg: <em>http://smsapi.org/?user_param=<strong>$username</strong>&password_param=<strong>$password</strong>"
                                                      "&sender_param=<strong>$label</strong>&recipient_param=<strong>$recipient</strong>&text_param=<strong>$text</strong></em>"))
    sms_api_username = models.CharField(max_length=100, blank=True)
    sms_api_password = models.CharField(max_length=100, blank=True)

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
            from ikwen.foundation.accesscontrol.backends import UMBRELLA
            config = Config.objects.using(UMBRELLA).get(service=self.service)
        except Config.DoesNotExist:
            config = Config(service=self.service)
        config.company_name = self.company_name
        config.company_name_slug = self.company_name_slug
        config.short_description = self.short_description
        config.description = self.description
        config.slogan = self.slogan
        config.logo = self.logo
        config.cover_image = self.cover_image
        config.signature = self.signature
        config.contact_email = self.contact_email
        config.contact_phone = self.contact_phone
        return config

    def save(self, *args, **kwargs):
        super(AbstractConfig, self).save(*args, **kwargs)
        if type(self) is not Config:  # If it is any descending class
            from ikwen.foundation.accesscontrol.backends import UMBRELLA
            base_config = self.get_base_config()
            base_config.save(using=UMBRELLA)


class Config(AbstractConfig):
    """
    Default Configurations options derived from :class:`ikwen.foundation.core.models.AbstractConfig`.
    It Adds nothing to :class:`ikwen.foundation.core.models.AbstractConfig`. Its only purpose is to
    create a concrete class.
    """

    class Meta:
        db_table = 'ikwen_config'


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
    :attr:`target` Whether to appear as BUSINESS or PERSONAL notice.
    :attr:`target_url_name` Name of the url to hit to view the list of objects that triggered
                            this event. It is typically used to create the *View all* link
    :attr:`renderer` dotted name of the function to call to render an event of this type the :attr:`member` Console.
    Write it under the dotted form 'package.module.function_name'. :attr:`renderer`
    is called as such: function_name(service, event_type, member, object_id, model)
    """
    BUSINESS = 'Business'
    PERSONAL = 'Personal'
    app = models.ForeignKey(Application)
    codename = models.CharField(max_length=150)
    title = models.CharField(max_length=150)
    title_mobile = models.CharField(max_length=100, blank=True)
    target = models.CharField(max_length=15)  # BUSINESS or PERSONAL
    target_url_name = models.CharField(max_length=100, blank=True)
    renderer = models.CharField(max_length=255)

    objects = MongoDBManager()

    class Meta:
        db_table = 'ikwen_consoleeventtype'
        unique_together = (
            ('app', 'codename'),
            ('app', 'title'),
        )

    def __unicode__(self):
        return self.codename

    def get_resp_title(self, request):
        if request.user_agent.is_mobile and self.title_mobile:
            return self.title_mobile
        return self.title


class ConsoleEvent(Model):
    """
    An event targeted to the Member console.

    :attr:`service` :class:`Service` from which event was fired. It helps retrieve Application and IA0.
    :attr:`member` :class:`Member` to which the event is aimed at.
    :attr:`event_type` :class:`ConsoleEventType` for this event.
    Events of the same type will be grouped under a same :attr:`ConsoleEventType.title`

    :attr:`object_id` id of the object involved in the :attr:`service` database
    """
    PENDING = 'Pending'
    PROCESSED = 'Processed'
    service = models.ForeignKey(Service, related_name='+', default=get_service_instance, db_index=True)
    member = models.ForeignKey('accesscontrol.Member', db_index=True)
    event_type = models.ForeignKey(ConsoleEventType, related_name='+')
    model = models.CharField(max_length=100, blank=True, null=True)
    object_id = models.CharField(max_length=24, db_index=True)

    class Meta:
        db_table = 'ikwen_consoleevent'

    def render(self):
        renderer = import_by_path(self.event_type.renderer)
        return renderer(self)

    def to_dict(self):
        var = to_dict(self)
        var['project_url'] = self.service.url
        var['project_name'] = self.service.project_name
        var['created_on'] = naturaltime(self.created_on)
        del(var['model'])
        del(var['object_id'])
        del(var['service_id'])
        del(var['member_id'])
        del(var['event_type_id'])
        return var


class QueuedSMS(Model):
    recipient = models.CharField(max_length=18)
    text = models.TextField()

    class Meta:
        db_table = 'ikwen_queuedsms'


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
    from ikwen.foundation.accesscontrol.backends import UMBRELLA
    ConsoleEvent.objects.using(UMBRELLA).filter(object_id=instance.pk).delete()


post_delete.connect(delete_object_events, dispatch_uid="object_post_delete_id")