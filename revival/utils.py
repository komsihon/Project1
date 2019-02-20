# -*- coding: utf-8 -*-
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from django.utils.translation import gettext as _
from ikwen.accesscontrol.models import Member
from ikwen.core.utils import get_mail_content
from ikwen.revival.models import MemberProfile, ProfileTag


def set_profile_tag_member_count():
    d = {}
    for profile_tag in ProfileTag.objects.all():
        d[profile_tag] = 0
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
            except MultipleObjectsReturned:
                for profile in MemberProfile.objects.filter(member=member)[1:]:
                    profile.delete()
                member_profile = MemberProfile.objects.get(member=member)

            for profile_tag in ProfileTag.objects.filter(pk__in=member_profile.tag_fk_list):
                d[profile_tag] += 1

    for profile_tag, value in d.items():
        profile_tag.member_count = value
        profile_tag.save()


def render_suggest_create_account_mail(target, service, revival, **kwargs):
    if not target.member.is_ghost:
        return None, None, None
    sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
    config = service.config
    invitation_message = config.__getattribute__('invitation_message')
    template_name = 'revival/mails/suggest_create_account.html'
    join_reward_pack_list = kwargs.pop('reward_pack_list', None)
    if join_reward_pack_list:
        subject = _("Join us on ikwen and earn free coupons." % service.project_name)
    else:
        subject = _("Join our community on ikwen.")
    if invitation_message or join_reward_pack_list:
        extra_context = {
            'member_name': target.member.first_name,
            'join_reward_pack_list': join_reward_pack_list,
            'invitation_message': invitation_message
        }
        html_content = get_mail_content(subject, service=service, template_name=template_name,
                                        extra_context=extra_context)
    else:
        html_content = None
    return sender, subject, html_content


def render_suggest_referral_mail(target, service, revival, **kwargs):
    sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
    subject = _("Invite your friends on %s and earn free coupons." % service.project_name)
    template_name = 'revival/mails/suggest_referral.html'
    referral_reward_pack_list = kwargs.pop('reward_pack_list', None)
    extra_context = {
        'member_name': target.member.first_name,
        'referred_project_name': service.project_name,
        'referred_project_name_slug': service.project_name_slug,
        'referral_reward_pack_list': referral_reward_pack_list
    }
    html_content = get_mail_content(subject, service=service, template_name=template_name,
                                    extra_context=extra_context)
    if not referral_reward_pack_list:
        if not getattr(settings, 'UNIT_TESTING', False):
            html_content = None
    return sender, subject, html_content


def render_tsunami_revival_mail(target, obj, revival, **kwargs):
    if target.revival_count >= 2:
        return None, None, None
    sender = 'ikwen Tsunami <no-reply@ikwen.com>'
    member = target.member
    lang = member.language
    if not lang:
        lang = 'fr'
    lang = lang[:2]
    if lang != 'en' and lang != 'fr':
        lang = 'en'
    if target.revival_count <= 0:
        subject = _("Secure your business by staying close to your customers")
        template_name = 'revival/mails/tsunami/revival_1_%s.html' % lang
    else:
        subject = _("Decide on your turnover")
        template_name = 'revival/mails/tsunami/revival_2_%s.html' % lang
    html_content = get_mail_content(subject, template_name=template_name)
    return sender, subject, html_content