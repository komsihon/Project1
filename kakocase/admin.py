from django.conf import settings
from django.contrib import admin
from ikwen.kakocase.models import OperatorProfile


class OperatorProfileAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        if getattr(settings, 'IS_IKWEN'):
            db = self.service.database
            obj_mirror = OperatorProfile.objects.using(db).get(pk=self.id)
            obj_mirror.ikwen_share = obj.ikwen_share
            obj_mirror.save(using=db)
        super(OperatorProfileAdmin, self).save(request, obj, form, change)
