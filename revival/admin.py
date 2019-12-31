from django.contrib import admin
from ikwen.revival.models import ProfileTag, Revival


class ProfileTagAdmin(admin.ModelAdmin):
    fields = ('name', )
    list_display = ('name', 'member_count', 'is_active', 'is_reserved', 'smart_total_revival', 'total_cyclic_mail_revival')


class RevivalAdmin(admin.ModelAdmin):
    list_display = ('service', 'mail_renderer', 'model_name', 'object_id', 'profile_tag_id', 'status',
                    'progress', 'total', 'get_kwargs', 'run_on', 'is_active', 'is_running')


admin.site.register(ProfileTag, ProfileTagAdmin)
admin.site.register(Revival, RevivalAdmin)
