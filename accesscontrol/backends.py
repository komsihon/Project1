# -*- coding: utf-8 -*-
import json

import requests
from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models import Q

from ikwen.core.utils import add_event, get_service_instance
from permission_backend_nonrel.models import UserPermissionList

from ikwen.accesscontrol.models import Member, COMMUNITY, MEMBER_JOINED_IN, SUDO
from ikwen.revival.models import MemberProfile
from permission_backend_nonrel.backends import NonrelPermissionBackend

__author__ = 'Kom Sihon'

UMBRELLA = 'umbrella'  # The alias for the top most database in ikwen platform
ARCH_EMAIL = 'arch@ikwen.com'


class LocalDataStoreBackend(NonrelPermissionBackend):
    def authenticate(self, username=None, password=None, **kwargs):
        uid = kwargs.get('uid')
        api_signature = kwargs.get('api_signature')
        if uid:
            try:
                user = Member.objects.using('default').get(pk=uid)
            except Member.DoesNotExist:
                try:
                    user = Member.objects.using(UMBRELLA).get(pk=uid)
                    username = user.username
                except Member.DoesNotExist:
                    return None
        elif api_signature:
            service = kwargs.pop('service', None)
            if not service:
                service = get_service_instance()
            if api_signature != service.api_signature:
                return None
            return service.member
        else:
            try:
                if username:
                    username = username.strip().lower()
                user = Member.objects.using(UMBRELLA).get(username=username)
            except Member.DoesNotExist:
                try:
                    user = Member.objects.using(UMBRELLA).get(email=username)
                    username = user.username
                except:
                    try:
                        phone = kwargs.get('phone')
                        if not phone:
                            return None
                        user = Member.objects.using(UMBRELLA).get(phone=phone)
                        username = user.username
                    except Member.DoesNotExist:
                        return None
        try:
            user = Member.objects.using('default').get(username=username, is_ghost=False)
        except Member.DoesNotExist:
            try:
                ghost = Member.objects.using('default').get(Q(email=user.email) | Q(phone=user.phone), is_ghost=True)
                MemberProfile.objects.filter(member=ghost).update(member=user)
                ghost.delete()
            except Member.DoesNotExist:
                return
            community = Group.objects.get(name=COMMUNITY)
            if user.email != ARCH_EMAIL:
                user.is_iao = False
                user.is_bao = False
                user.is_superuser = False
                user.is_staff = False
                user.date_joined = datetime.now()
                user.last_login = datetime.now()
                service = get_service_instance()
                user.add_service(service.id)
                user.add_group(community.id)
                sudo_group = Group.objects.get(name=SUDO)
                add_event(service, MEMBER_JOINED_IN, group_id=sudo_group.id, object_id=user.id)
                add_event(service, MEMBER_JOINED_IN, member=user, object_id=user.id)
            user.save(using='default')  # Saves the user to the default application database if not exists there

            if user.email != ARCH_EMAIL:
                perm_list, created = UserPermissionList.objects.get_or_create(user=user)
                perm_list.group_fk_list.append(community.id)
                perm_list.save()

        if getattr(settings, 'AUTH_WITHOUT_PASSWORD', False) and not user.is_staff:
            return user
        if not user.check_password(password):
            return None
        return user

    def get_user(self, user_id):
        try:
            return Member.objects.get(pk=user_id)
        except Member.DoesNotExist:
            return None


def check_user_remote(username=None, password=None):
    """
    Checks member into the centralized Ikwen members database on a remote server
    @param username:
    @param password:
    @return:
    """
    service_id = getattr(settings, 'IKWEN_SERVICE_ID')
    endpoint = 'http://accounts.ikwen.com'
    params = {
        'key': service_id,
        'username': username,
        'password': password
    }
    r = requests.get(endpoint, params=params)
    response = json.loads(r.content.decode('utf8'))
    if response.get('success'):
        return response['member']
    return None
