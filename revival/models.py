# -*- coding: utf-8 -*-
import calendar
from datetime import datetime, timedelta
from random import random

from django.utils.translation import gettext_lazy as _
from django.db import models

from djongo import models

from ikwen.core.fields import MultiImageField
from ikwen.core.constants import PENDING
from ikwen.core.models import Model, Service, AbstractWatchModel
from ikwen.accesscontrol.models import Member


class ProfileTag(AbstractWatchModel):
    name = models.CharField(max_length=60)
    slug = models.SlugField(unique=True)
    member_count = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_reserved = models.BooleanField(default=False)
    is_auto = models.BooleanField(default=False)
    smart_revival_history = models.JSONField()
    cyclic_revival_mail_history = models.JSONField()
    cyclic_revival_sms_history = models.JSONField()

    smart_total_revival = models.IntegerField(default=0)
    total_cyclic_mail_revival = models.IntegerField(default=0)
    total_cyclic_sms_revival = models.IntegerField(default=0)

    class Meta:
        unique_together = ('name', 'is_auto')

    def __str__(self):
        return self.name


class CyclicRevival(Model):
    UPLOAD_TO = 'revival/cyclic_mail_images'

    service = models.ForeignKey(Service, related_name='+', on_delete=models.CASCADE)
    profile_tag_id = models.CharField(max_length=24, db_index=True)
    hour_of_sending = models.IntegerField(default=9, db_index=True)
    days_cycle = models.IntegerField(blank=True, null=True,
                                     help_text=_("Run revival every N days"))
    day_of_week_list = models.JSONField()
    day_of_month_list = models.JSONField()
    mail_subject = models.CharField(max_length=150, blank=True, null=True)
    mail_content = models.TextField(blank=True, null=True)
    mail_image = MultiImageField(upload_to=UPLOAD_TO, max_size=800, blank=True, null=True)
    sms_text = models.TextField(blank=True, null=True)
    next_run_on = models.DateField(default=datetime.now, db_index=True)
    end_on = models.DateField(db_index=True, blank=True, null=True)
    items_fk_list = models.JSONField()
    is_active = models.BooleanField(default=False, db_index=True)
    is_running = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = ('service', 'profile_tag_id', )

    def set_next_run_date(self):
        if self.days_cycle:
            self.next_run_on = self.next_run_on + timedelta(days=self.days_cycle)
        elif len(self.day_of_week_list):
            self.day_of_week_list.sort()
            today = datetime.now().weekday() + 1
            count = len(self.day_of_week_list)
            try:
                i = self.day_of_week_list.index(today)
                if count > 1:
                    i = (i + 1) % count
                next_day = self.day_of_week_list[i]
                if next_day > today:
                    ext = next_day - today
                else:
                    ext = next_day - today + 7
                self.next_run_on = self.next_run_on + timedelta(days=ext)
            except:
                pass
        elif len(self.day_of_month_list):
            self.day_of_month_list.sort()
            now = datetime.now()
            today = now.day
            count = len(self.day_of_month_list)
            days_count = calendar.monthrange(now.year, now.month)[1]
            try:
                i = self.day_of_month_list.index(today)
                if count > 1:
                    i = (i + 1) % count
                next_day = self.day_of_month_list[i]
                if next_day > today:
                    ext = next_day - today
                else:
                    ext = next_day - today + days_count
                self.next_run_on = self.next_run_on + timedelta(days=ext)
            except:
                pass
        self.save()


class MemberProfile(Model):
    member = models.ForeignKey(Member, unique=True, on_delete=models.CASCADE)
    tag_list = models.JSONField()
    tag_fk_list = models.JSONField()


class ObjectProfile(Model):
    model_name = models.CharField(max_length=60)
    object_id = models.CharField(max_length=60)

    class Meta:
        unique_together = ('model_name', 'object_id', )


class Revival(Model):
    service = models.ForeignKey(Service, related_name='+', on_delete=models.CASCADE)
    model_name = models.CharField(max_length=150, db_index=True)
    object_id = models.CharField(max_length=60, db_index=True)
    profile_tag_id = models.CharField(max_length=24, blank=True, null=True, db_index=True)  # Tag targeted by this revival
    status = models.CharField(max_length=60, default=PENDING)
    progress = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    mail_renderer = models.CharField(max_length=100)
    get_kwargs = models.CharField(max_length=100, blank=True, null=True)
    run_on = models.DateTimeField(blank=True, null=True, editable=False, db_index=True)
    is_active = models.BooleanField(default=True)
    is_running = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = ('service', 'profile_tag_id', 'mail_renderer', 'get_kwargs', )


class Target(Model):
    revival = models.ForeignKey(Revival, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    revival_count = models.IntegerField(default=0)
    notified = models.BooleanField(default=False)
    revived_on = models.DateTimeField(blank=True, null=True, db_index=True)
    rand = models.FloatField(default=random, db_index=True)


class CyclicTarget(Model):
    revival = models.ForeignKey(CyclicRevival, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    revival_count = models.IntegerField(default=1)


class CCMMonitoringMail(Model):
    JOINS = "Joins"
    REVIVALS = "Revivals"

    service = models.ForeignKey(Service, related_name='+', on_delete=models.CASCADE)
    type = models.CharField(max_length=30, default=JOINS)
    subject = models.CharField(max_length=30)
