# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.utils.translation import ugettext as _, activate

from pywebpush import webpush

from ikwen.conf import settings as ikwen_settings
from ikwen.core.utils import get_service_instance, get_mail_content, get_device_type
from ikwen.accesscontrol.templatetags.auth_tokens import ikwenize
from ikwen.accesscontrol.models import PWAProfile, Member
from ikwen.accesscontrol.backends import UMBRELLA

logger = logging.getLogger('ikwen')


def analytics(request, *args, **kwargs):
    """
    Logs all kind of possible analytics
    """
    action = request.GET.get('action')
    pwa_profile_id = request.COOKIES.get('pwa_profile_id')
    now = datetime.now()
    new_profile = True
    response = {'success': True}
    device_type = get_device_type(request)
    if pwa_profile_id:
        try:
            pwa_profile = PWAProfile.objects.get(pk=pwa_profile_id)
            new_profile = False
        except:
            pwa_profile = PWAProfile(device_type=device_type)
    else:
        pwa_profile = PWAProfile(device_type=device_type)
    if request.user.is_authenticated():
        member = request.user
        if pwa_profile_id and not pwa_profile.member:
            PWAProfile.objects.filter(service=get_service_instance(), member=member, device_type=device_type).delete()
        pwa_profile.member = member
    if action == 'log_pwa_install':
        pwa_profile.installed_pwa_on = now
        notify_pwa_install(pwa_profile.member)
    pwa_profile.save()

    response = HttpResponse(json.dumps(response))
    if new_profile:
        expires = now + timedelta(days=1826)  # Expires in 5 years
        secure = not getattr(settings, 'DEBUG', False)
        response.set_cookie('pwa_profile_id', pwa_profile.id, expires=expires, secure=secure)
    return response


def notify_pwa_install(member):
    service = get_service_instance()
    install_count = PWAProfile.objects.filter(service=service, installed_on__isnull=False).count()
    if member:
        member_detail_view = getattr(settings, 'MEMBER_DETAIL_VIEW', None)
        if member_detail_view:
            target_page = reverse(member_detail_view, args=(member.id, ))
        else:
            target_page = ikwenize(reverse('ikwen:profile', args=(member.id, )))
    else:
        target_page = None

    for staff in Member.objects.filter(is_staff=True):
        if staff.language:
            activate(staff.language)
        else:
            activate('en')

        if member:
            title = member.full_name
            body = _("This customer just installed you app %(app_name)s. You can call or text to say thank you. \n"
                     "Now you have your app installed by %(install_count)d people" % {'app_name': service.project_name,
                                                                                      'install_count': install_count})
        else:
            title = _("New app install")
            body = _("An anonymous visitor just installed your app %(app_name)s. \n"
                     "Now you have it installed by %(install_count)d people" % {'app_name': service.project_name,
                                                                                'install_count': install_count})

        notification = {
            'title': title,
            'body': body,
            'target': target_page,
            'badge': ikwen_settings.MEDIA_URL + 'img/push-badge.png',
            'icon': ikwen_settings.MEDIA_URL + 'icons/android-icon-512x512.png'
        }

        try:
            pwa_profile = PWAProfile.objects.using(UMBRELLA).get(member=staff)
            webpush(json.loads(pwa_profile.push_subscription), json.dumps(notification),
                    vapid_private_key=ikwen_settings.PUSH_PRIVATE_KEY,
                    vapid_claims={"sub": "mailto:ikwen.cm@gmail.com"})
        except:
            try:
                extra_context = {'member_name': staff.first_name, 'message': body}
                if target_page:
                    extra_context['cta_url'] = service.url + target_page
                html_content = get_mail_content(title, template_name='core/mails/pwa_installed_notification.html',
                                                extra_context=extra_context)
                sender = 'ikwen <no-reply@ikwen.com>'
                msg = EmailMessage(title, html_content, sender, [staff.email])
                msg.content_subtype = "html"
                msg.send()
            except:
                logger.error("%s - Failed to send order confirmation email." % service, exc_info=True)
