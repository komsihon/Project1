from threading import Thread

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.mail import EmailMessage
from django.utils.translation import gettext as _
from permission_backend_nonrel.models import UserPermissionList, GroupPermissionList

from ikwen.accesscontrol.models import Member

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.utils import get_service_instance, get_mail_content


def is_collaborator(member, service):
    if member.is_anonymous():
        return False
    # Reload member information from UMBRELLA database
    member = Member.objects.using(UMBRELLA).get(pk=member.id)
    if service in member.collaborates_on:
        return True
    return False


def is_admin(member):
    service = get_service_instance()
    if service.member == member:
        return True
    if service in member.collaborates_on:
        pass
    return False


def get_members_having_permission(model, codename):
    """
    Gets a list of members having the permission of the given model and codename
    :param model: content_type model
    :param codename: permission codename
    :return: list of Member
    """
    ct = ContentType.objects.get_for_model(model)
    perm_pk = Permission.objects.get(content_type=ct, codename=codename).id
    group_pk_list = [gp.group.pk for gp in
                     GroupPermissionList.objects.raw_query({'permission_fk_list': {'$elemMatch': {'$eq': perm_pk}}})]
    group_user_perm = UserPermissionList.objects.raw_query({'group_fk_list': {'$elemMatch': {'$in': group_pk_list}}})
    user_perm = UserPermissionList.objects.raw_query({'permission_fk_list': {'$elemMatch': {'$eq': perm_pk}}})
    user_perm_list = list(set(group_user_perm) | set(user_perm))
    return [obj.user for obj in user_perm_list]


def send_welcome_email(member, reward_pack_list=None):
    """
    Sends welcome email upon registration of a Member. The default message can
    be edited from the admin in Config.welcome_message
    Following strings in the message will be replaced as such:

    $member_name  -->  member.first_name

    @param member: Member object to whom message is sent
    @param reward_pack_list: rewards sent to Member if it is a
                             platform with Continuous Rewarding active
    """
    service = get_service_instance()
    config = service.config
    subject = _("Welcome to %s" % service.project_name)
    message = None
    if getattr(settings, 'IS_IKWEN', False):
        template_name = 'accesscontrol/mails/welcome_to_ikwen.html'
    else:
        if config.welcome_message.strip():
            message = config.welcome_message.replace('$member_name', member.first_name)
        if reward_pack_list:
            template_name = 'rewarding/mails/community_welcome_pack.html'
        else:
            template_name = 'accesscontrol/mails/community_welcome.html'
    html_content = get_mail_content(subject, message, template_name=template_name,
                                    extra_context={'reward_pack_list': reward_pack_list})
    sender = '%s <no-reply@%s>' % (service.project_name, service.domain)
    msg = EmailMessage(subject, html_content, sender, [member.email])
    msg.content_subtype = "html"
    Thread(target=lambda m: m.send(), args=(msg,)).start()
