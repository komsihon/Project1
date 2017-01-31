# -*- coding: utf-8 -*-
import json

import requests
from django.conf import settings

from ikwen.accesscontrol.models import Member
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
                user = Member.objects.using(UMBRELLA).get(username=username)
                if not user.check_password(password):
                    return None
            except Member.DoesNotExist:
                for m in Member.objects.using(UMBRELLA).filter(email=username):
                    if m.check_password(password):
                        user = m
                        break
                else:
                    try:
                        phone = kwargs.get('phone')
                        if not phone:
                            return None
                        user = Member.objects.using(UMBRELLA).get(phone=phone)
                        if not user.check_password(password):
                            return None
                    except Member.DoesNotExist:
                        return None
        try:
            user = Member.objects.using('default').get(username=username)
        except Member.DoesNotExist:
            user.save(using='default')  # Saves the user to the default application database if not exists there
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