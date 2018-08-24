# -*- coding: utf-8 -*-
import json

import requests
from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import Group
from ikwen.core.utils import add_event, get_service_instance
from permission_backend_nonrel.models import UserPermissionList

from ikwen.accesscontrol.models import Member, COMMUNITY, MEMBER_JOINED_IN, SUDO
from permission_backend_nonrel.backends import NonrelPermissionBackend

__author__ = 'Kom Sihon'

UMBRELLA = 'umbrella'  # The alias for the top most database in ikwen platform
ARCH_EMAIL = 'arch@ikwen.com'


class LocalDataStoreBackend(NonrelPermissionBackend):
    def authenticate(self, username=None, password=None, **kwargs):
        uid = kwargs.get('uid')
        if uid:
            try:
                user = Member.objects.using('default').get(pk=uid)
            except Member.DoesNotExist:
                try:
                    user = Member.objects.using(UMBRELLA).get(pk=uid)
                    username = user.username
                except Member.DoesNotExist:
                    return None
        else:
            try:
                if username:
                    username = username.strip().lower()
                user = Member.objects.using(UMBRELLA).get(username=username)
                if not user.check_password(password):
                    return None
            except Member.DoesNotExist:
                for m in Member.objects.using(UMBRELLA).filter(email=username):
                    if m.check_password(password):
                        user = m
                        # At this stage turns the username initially input as a email into the actual username
                        # Else the search of the user in the default database will rather use that email.
                        username = m.username
                        break
                else:
                    try:
                        phone = kwargs.get('phone')
                        if not phone:
                            return None
                        user = Member.objects.using(UMBRELLA).get(phone=phone)
                        if not user.check_password(password):
                            return None
                        username = user.username
                    except Member.DoesNotExist:
                        return None
        try:
            user = Member.objects.using('default').get(username=username)
        except Member.DoesNotExist:
            community = Group.objects.get(name=COMMUNITY)
            if user.email != ARCH_EMAIL:
                user.is_iao = False
                user.is_bao = False
                user.is_superuser = False
                user.is_staff = False
                user.date_joined = datetime.now()
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