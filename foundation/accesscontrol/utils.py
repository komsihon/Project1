from ikwen.foundation.accesscontrol.models import Member

from ikwen.foundation.accesscontrol.backends import UMBRELLA

from ikwen.foundation.core.utils import get_service_instance


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


