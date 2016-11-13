# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from ikwen.foundation.core.models import Model


class FlatPage(Model):
    AGREEMENT = 'agreement'
    LEGAL_MENTIONS = 'legal-mentions'

    url = models.CharField(_('URL'), max_length=100, unique=True, db_index=True)
    title = models.CharField(_('title'), max_length=200)
    content = models.TextField(_('content'), blank=True)
    template_name = models.CharField(_('template name'), max_length=70, blank=True, editable=False,
        help_text=_("Example: 'flatpages/contact_page.html'. If this isn't provided, the system will use 'flatpages/default.html'."))
    registration_required = models.BooleanField(_('registration required'),
        help_text=_("If this is checked, only logged-in users will be able to view the page."),
        default=False)

    class Meta:
        db_table = 'ikwen_flatpage'
        verbose_name = _('flat page')
        verbose_name_plural = _('flat pages')
        ordering = ('url',)

    def __str__(self):
        return "%s -- %s" % (self.url, self.title)

    def delete(self, *args, **kwargs):
        if self.url == FlatPage.AGREEMENT or self.url == FlatPage.LEGAL_MENTIONS:
            return  # Cannot delete those two
