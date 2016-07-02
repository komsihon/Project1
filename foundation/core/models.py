# -*- coding: utf-8 -*-
from django.conf import settings
from django.db.models.loading import get_model
from django.utils import timezone
from django.db import models
from django.utils.translation import gettext as _
from django_mongodb_engine.contrib import MongoDBManager

from ikwen.foundation.core.utils import add_database_to_settings, to_dict


class Model(models.Model):
    created_on = models.DateTimeField(default=timezone.now)
    updated_on = models.DateTimeField(default=timezone.now, auto_now_add=True)

    class Meta:
        abstract = True


class Application(Model):
    LOGOS_FOLDER = 'app_logos/'

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
    logo = models.ImageField(upload_to=LOGOS_FOLDER, blank=True, null=True)
    url = models.URLField(max_length=150)
    description = models.CharField(max_length=150, blank=True)
    base_monthly_cost = models.PositiveIntegerField()
    operators_count = models.PositiveIntegerField(default=0, blank=True)

    class Meta:
        db_table = 'ikwen_application'

    def __unicode__(self):
        return self.name


class Service(models.Model):
    """
    An instance of an Ikwen :class:`Application` that a :class:`Member` is operating.
    """
    objects = MongoDBManager()
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
                                    help_text="Text that can be used as a subdomain for the project: "
                                              "Eg: project_name.ikwen.com")
    database = models.CharField(max_length=150, blank=True)
    domain_type = models.CharField(max_length=15, blank=True, choices=DOMAIN_TYPE_CHOICES)
    url = models.URLField(blank=True)
    admin_url = models.URLField(blank=True, help_text=_("Access to application's control panel"))
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

    class Meta:
        db_table = 'ikwen_service'
        unique_together = ('app', 'project_name', )

    def __unicode__(self):
        return u'%s: %s' % (self.project_name, self.member.email)

    def _get_created_on(self):
        return self.since
    created_on = property(_get_created_on)

    def _get_config(self):
        config_model_name = getattr(settings, 'IKWEN_CONFIG_MODEL', 'core.Config')
        app_label = config_model_name.split('.')[0]
        model = config_model_name.split('.')[1]
        config_model = get_model(app_label, model)
        return config_model.objects.all()[0]
    config = property(_get_config)

    def _get_details(self):
        return "Application: <em>%(app_name)s</em><br>" \
               "Running as: <em>%(project_name)s</em><br>" \
               "On: <em>%(url)s</em>" % {'app_name': self.app.name, 'project_name': self.project_name, 'url': self.url}
    details = property(_get_details)

    def save(self, *args, **kwargs):
        """
        In real world, this object is replicated in the sub_database for consistency purposes and so will hardly
        be modified from that database since :class:`Service` object is never exposed in the admin interface of the IAO.
        So said the save() method on this object will generally be called when the object is being manipulated
        from the upper Ikwen website itself. The changes made from there must then be replicated to the sub database.

        The replication is made by adding the actual Service database to DATABASES in settings and calling
        save(using=database).

        Let's recall that we determine if we are on Ikwen website by testing that there is no DATABASE connection
        named 'foundation', since 'foundation' is the 'default' database there.
        """
        from ikwen.foundation.core.backends import UMBRELLA
        using = 'default'
        if kwargs.get('using'):
            using = kwargs['using']
            del(kwargs['using'])
        databases = getattr(settings, 'DATABASES')
        if not databases.get(UMBRELLA):
            # If we are on Ikwen itself, replicate save or update on the current Service database
            add_database_to_settings(self.database)
            if not self.id:
                # Upon creation of a Service object. Add the member who owns it in the
                # Service's database as a staff, then increment operators_count for the Service.app
                self.member.is_iao = True
                self.member.save()
                self.member.is_staff = True
                self.member.save(using=self.database)
                self.app.operators_count += 1
                self.app.save()
                link = self.url.replace('http://', '').replace('https://', '')
                mail_signature = "%s<br>" \
                                 "<a href='%s'>%s</a>" % (self.project_name, self.url, link)
                Config.objects.using(self.database).create(service=self, company_name=self.project_name,
                                                           contact_email=self.member.email,  signature=mail_signature)
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
    service = models.OneToOneField(Service, editable=False, related_name='+')
    company_name = models.CharField(max_length=30, verbose_name=_("Website / Company name"),
                                    help_text=_("Website/Company name as you want it to appear in mails and pages."))
    company_name_slug = models.SlugField()
    address = models.CharField(max_length=30, blank=True, verbose_name=_("Company address"),
                               help_text=_("Website/Company name as you want it to appear in mails and pages."))
    country = models.ForeignKey('core.Country', blank=True, null=True, related_name='+',
                                help_text=_("Country where HQ of the company are located."))
    city = models.CharField(max_length=60, blank=True,
                            help_text=_("City where HQ of the company are located."))
    slogan = models.CharField(max_length=100, blank=True, verbose_name=_("Company slogan"),
                              help_text=_("Slogan of your company."))
    logo = models.ImageField(upload_to='logo', verbose_name=_("Your logo"), blank=True, null=True,
                             help_text=_("Image in <strong>PNG with transparent background</strong> is advised. "
                                         "(Maximum 400 x 400px)"))
    cover_image = models.ImageField(upload_to='cover_image', blank=True, null=True,
                                    help_text=_("Cover image used as decoration of company's profile page "
                                                "and also to use on top of the mails. (Max. 800px width)"))
    signature = models.TextField(blank=True, verbose_name=_("Mail signature"),
                                 help_text=_("Signature on all mails. HTML allowed."))
    welcome_message = models.TextField(blank=True, verbose_name=_("Welcome message"),
                                       help_text="Model of message to send to user upon registration.")
    contact_email = models.EmailField(verbose_name=_("Contact email"),
                                      help_text="Contact email of the company for customers to send inquiries.")
    contact_phone = models.CharField(max_length=18, blank=True,
                                     help_text=_("Main phone number for your customers to contact you."))
    facebook_link = models.URLField(blank=True,
                                    help_text=_("Facebook link. Eg: https://www.facebook.com/myvodstore"))
    twitter_link = models.URLField(blank=True,
                                   help_text=_("Twitter link. Eg: https://www.twitter.com/myvodstore"))
    google_plus_link = models.URLField(blank=True,
                                       help_text=_("Google+ link. Eg: https://www.googleplus.com/myvodstore"))
    instagram_link = models.URLField(blank=True,
                                     help_text=_("Instagram link. Eg: https://www.instagram.com/myvodstore"))
    linkedin_link = models.URLField(blank=True,
                                    help_text=_("LinkedIn link. Eg: https://www.linkedin.com/myvodstore"))
    google_analytics = models.TextField(blank=True,
                                        help_text=_("Google Analytics tracking code."))
    paypal_user = models.CharField(max_length=60, blank=True, verbose_name=_("PAYPAL USER"),
                                   help_text=_("Username for PayPal API"))
    paypal_password = models.CharField(max_length=60, blank=True, verbose_name=_("PAYPAL PASSWORD"),
                                       help_text=_("Password for PayPal API"))
    paypal_api_signature = models.CharField(max_length=60, blank=True, verbose_name=_("PAYPAL API SIGNATURE"),
                                            help_text=_("API Signature for PayPal API"))
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


class Config(AbstractConfig):
    """
    Default Configurations options derived from :class:`ikwen.foundation.core.models.AbstractConfig`.
    It Adds nothing to :class:`ikwen.foundation.core.models.AbstractConfig`. Its only purpose is to
    create a concrete class.
    """

    class Meta:
        db_table = 'ikwen_config'


class Country(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField()

    class Meta:
        db_table = 'ikwen_country'


class ConsoleEventType(Model):
    """
    Type of events targeted to the Member console.

    :attr:`app` :class:`Application` this type of event applies to.
    :attr:`title`
    :attr:`title_mobile` Title to use on mobile devices.
    :attr:`renderer` dotted name of the function to call to render an event of this type the :attr:`member` Console.
    Write it under the dotted form 'package.module.function_name'. :attr:`renderer`
    is called as such: function_name(service, event_type, member, object_id, model)
    """
    app = models.ForeignKey(Application)
    code_name = models.CharField(max_length=150)
    title = models.CharField(max_length=150)
    title_mobile = models.CharField(max_length=100, blank=True)
    renderer = models.CharField(max_length=255)

    class Meta:
        db_table = 'ikwen_consoleeventtype'


class ConsoleEvent(Model):
    """
    An event targeted to the Member console.

    :attr:`service` :class:`Service` from which event was fired. It helps retrieve Application and IA0.

    :attr:`event_type` :class:`ConsoleEventType` for this event.
    Events of the same type will be grouped under a same :attr:`ConsoleEventType.title`

    :attr:`member` :class:`Member` to which the event is aimed at.

    :attr:`model` dotted name of the model under the form 'app_label.model_class_name'

    :attr:`object_id` id of the object involved in the :attr:`service` database
    """
    service = models.ForeignKey(Service)
    event_type = models.ForeignKey(ConsoleEventType)
    member = models.ForeignKey('accesscontrol.Member')
    model = models.CharField(max_length=100)
    object_id = models.CharField(max_length=24)

    class Meta:
        db_table = 'ikwen_consoleevent'


class QueuedSMS(Model):
    recipient = models.CharField(max_length=18)
    text = models.TextField()

    def to_dict(self):
        var = to_dict(self)
        del(var['created_on'])
        del(var['updated_on'])
        return var

    class Meta:
        db_table = 'ikwen_queuedsms'
