from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from ikwen.core.models import Model, Application


class Template(Model):
    app = models.ForeignKey(Application, on_delete=models.CASCADE)
    name = models.CharField(max_length=100,
                            help_text="Name of this template")
    slug = models.SlugField()
    preview = models.ImageField(upload_to='ikwen/template_previews',
                                blank=getattr(settings, 'DEBUG'), null=getattr(settings, 'DEBUG'))

    class Meta:
        db_table = 'ikwen_template'

    def __str__(self):
        return "%s: %s" % (self.app.name, self.name)


class Theme(Model):
    UPLOAD_TO = 'theme_logos'
    COMPACT = 'Compact'
    COZY = 'Cozy'
    COMFORTABLE = 'Comfortable'
    DISPLAY_CHOICES = (
        (COMPACT, _('Compact')),
        (COZY, _('Cozy')),
        (COMFORTABLE, _('Comfortable'))
    )
    template = models.ForeignKey(Template, on_delete=models.CASCADE)
    name = models.CharField(max_length=100,
                            help_text="Name of this theme")
    slug = models.SlugField()
    preview = models.ImageField(upload_to='theme_previews',
                                blank=getattr(settings, 'DEBUG', False), null=getattr(settings, 'DEBUG', False))
    logo = models.ImageField(upload_to=UPLOAD_TO, editable=False, blank=True, null=True,
                             help_text="This is not the logo of the theme actually, but the logo of the website "
                                       "when using this theme. User may want different logos for different themes.")
    display = models.CharField(max_length=30, choices=DISPLAY_CHOICES)
    cost = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'ikwen_theme'

    def __str__(self):
        return "%s (%s)" % (str(self.template), self.name)


class ThemePreview(Model):
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='ikwen/theme_previews')
