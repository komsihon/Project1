# -*- coding: utf-8 -*-

from django.utils.translation import gettext as _
from ikwen.accesscontrol.models import Member
from ikwen.core.utils import get_mail_content
from ikwen.revival.models import MemberProfile, ProfileTag


def set_profile_tag_member_count():
    ProfileTag.objects.all().update(member_count=0)
    member_queryset = Member.objects.all()
    total = member_queryset.count()
    chunks = total / 500 + 1
    for i in range(chunks):
        start = i * 500
        finish = (i + 1) * 500
        for member in member_queryset[start:finish]:
            try:
                member_profile = MemberProfile.objects.get(member=member)
            except MemberProfile.DoesNotExist:
                continue
            for profile_tag in ProfileTag.objects.filter(slug__in=member_profile.tag_list):
                profile_tag.member_count += 1
                profile_tag.save()


def render_suggest_referral_mail(target, obj, revival):
    subject = _("Invite your friends on %s and earn free coupons." % obj.project_name)
    template_name = 'revival/mails/suggest_referral.html'
    extra_context = {
        'member_name': target.member.first_name,
        'referred_project_name': obj.project_name,
        'referred_project_name_slug': obj.project_name_slug
    }
    html_content = get_mail_content(subject, template_name=template_name,
                                    extra_context=extra_context)
    return subject, html_content


def render_app_revival_mail(target, obj, revival):
    subject = _("Rediscover %s" % obj.name)
    template_name = 'revival/mails/%s_revival_%d.html' % (obj.slug, target.revival_count)
    message = _("")
    html_content = get_mail_content(subject, message, template_name=template_name,
                                    extra_context={})
    return subject, html_content