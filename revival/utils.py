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


def render_suggest_create_account_mail(target, obj, revival, **kwargs):
    sender = '%s <no-reply@%s>' % (obj.project_name, obj.domain)
    subject = _("Join us on ikwen and earn free coupons." % obj.project_name)
    template_name = 'revival/mails/suggest_create_account.html'
    join_reward_pack_list = kwargs.pop('reward_pack_list', None)
    if join_reward_pack_list:
        extra_context = {
            'member_name': target.member.first_name,
            'join_reward_pack_list': join_reward_pack_list,
        }
        html_content = get_mail_content(subject, service=obj, template_name=template_name,
                                        extra_context=extra_context)
    else:
        html_content = None
    return sender, subject, html_content


def render_suggest_referral_mail(target, obj, revival, **kwargs):
    sender = '%s <no-reply@%s>' % (obj.project_name, obj.domain)
    subject = _("Invite your friends on %s and earn free coupons." % obj.project_name)
    template_name = 'revival/mails/suggest_referral.html',
    referral_reward_pack_list = kwargs.pop('reward_pack_list', None)
    if referral_reward_pack_list:
        extra_context = {
            'member_name': target.member.first_name,
            'referred_project_name': obj.project_name,
            'referred_project_name_slug': obj.project_name_slug,
            'referral_reward_pack_list': referral_reward_pack_list
        }
        html_content = get_mail_content(subject, service=obj, template_name=template_name,
                                        extra_context=extra_context)
    else:
        html_content = None
    return sender, subject, html_content


def render_tsunami_revival_mail(target, obj, revival, **kwargs):
    sender = 'ikwen Tsunami <no-reply@ikwen.com>'
    if target.revival_count <= 1:
        subject = _("Secure your business by staying close to your customers")
        template_name = 'revival/mails/tsunami_revival_1.html'
    else:
        subject = _("Decide on your turnover")
        template_name = 'revival/mails/tsunami_revival_2.html'
    html_content = get_mail_content(subject, template_name=template_name)
    return sender, subject, html_content