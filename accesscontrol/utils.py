from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from permission_backend_nonrel.models import UserPermissionList, GroupPermissionList

from ikwen.accesscontrol.models import Member

from ikwen.accesscontrol.backends import UMBRELLA

from ikwen.core.utils import get_service_instance


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
