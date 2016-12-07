# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest
from permission_backend_nonrel.models import UserPermissionList
from permission_backend_nonrel.utils import add_permission_to_user

from ikwen.foundation.core.utils import add_database_to_settings

from ikwen.foundation.accesscontrol.tests_auth import wipe_test_data
from ikwen.foundation.accesscontrol.models import Member, AccessRequest
from ikwen.foundation.core.models import Service, ConsoleEventType, ConsoleEvent


class IkwenAccessControlTestCase(unittest.TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/accesscontrol/')
    def test_request_access(self):
        """
        Requesting access must create an AccessRequest object and the corresponding ConsoleEvent.
        The IAO of the service for which collaboration was requested must see that on his console.
        """
        self.client.login(username='member3', password='admin')
        response = self.client.get(reverse('ikwen:request_access'),
                                   {'service_id': '56eb6d04b37b3379b531b102',
                                    'format': 'json'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])
        self.assertEqual(AccessRequest.objects.filter(status=AccessRequest.PENDING).count(), 1)
        self.assertEqual(Member.objects.get(username='member2').business_notices, 1)
        self.client.logout()
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:console'))
        s = Member.objects.get(username='member2').collaborates_on[0]
        et = ConsoleEventType.objects.get(pk='56eb6db3379b531a0104b371')
        self.assertEqual(len(response.context['access_request_events'][s]), 1)
        response = self.client.get(reverse('ikwen:access_request_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['access_requests']), 1)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/accesscontrol/')
    def test_grant_access(self):
        """
        Granting access to collaborator adds him in the local database and
        create the corresponding UserPermissionList object with the right group
        """
        member3 = Member.objects.get(pk='56eb6d04b37b3379b531e013')
        member2 = Member.objects.get(pk='56eb6d04b37b3379b531e012')
        service = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        et = ConsoleEventType.objects.get(pk='56eb6db3379b531a0104b371')  # Collaboration Access Request event type
        group_id = '5804b37b3379b531e01eb6d2'
        add_database_to_settings(service.database)
        Group.objects.using(service.database).create(pk=group_id, name='Collabo')
        UserPermissionList.objects.using(service.database).all().delete()
        rq = AccessRequest.objects.create(member=member3, service=service)
        ConsoleEvent.objects.create(event_type=et, service=service, member=member2,
                                    model='accesscontrol.AccessRequest', object_id=rq.id)
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:grant_access'),
                                   {'group_id': group_id,
                                    'request_id': rq.id})
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])
        rq = AccessRequest.objects.get(member=member3)
        self.assertEqual(rq.status, AccessRequest.CONFIRMED)
        self.assertEqual(ConsoleEvent.objects.filter(member=service.member, event_type=et).count(), 0)
        perm_obj = UserPermissionList.objects.using(service.database).get(user=member3)
        self.assertListEqual(perm_obj.group_fk_list, [group_id])
        self.client.logout()
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:console'))
        s2 = Member.objects.get(username='member2').collaborates_on[0]
        self.assertEqual(len(response.context['event_list']), 1)
        self.client.logout()
        self.client.login(username='member3', password='admin')
        response = self.client.get(reverse('ikwen:console'), {'target': 'Personal'})
        s3 = Member.objects.get(username='member3').collaborates_on[-1]
        self.assertEqual(len(response.context['event_list']), 1)
        from pymongo import Connection
        cnx = Connection()
        cnx.drop_database(service.database)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_list_collaborators(self):
        """
        Lists collaborators with name containing the query 'q' and return a JSON Array of objects.
        Collaborators have their field collaborates_on carrying the current service
        """
        ct = ContentType.objects.all()[0]
        Permission.objects.all().delete()
        perm1 = Permission.objects.create(codename='ik_action1', name="Can do action 1", content_type=ct)
        m4 = Member.objects.get(username='member4')
        add_permission_to_user(perm1, m4)
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:list_collaborators'), {'q': 'tch'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(len(json_response), 1)
        self.assertEqual(json_response[0]['id'], '56eb6d04b37b3379b531e014')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_set_collaborator_permissions(self):
        """
        Setting collaborator's permissions clears preceding permissions and just reset them as new.
        This done to avoid to append the same permission multiple times in the permissions lists
        """
        ct = ContentType.objects.all()[0]
        Permission.objects.all().delete()
        perm1 = Permission.objects.create(codename='ik_action1', name="Can do action 1", content_type=ct)
        perm2 = Permission.objects.create(codename='ik_action2', name="Can do action 2", content_type=ct)
        perm3 = Permission.objects.create(codename='ik_action3', name="Can do action 3", content_type=ct)
        perm4 = Permission.objects.create(codename='ik_action4', name="Can do action 4", content_type=ct)
        m3 = Member.objects.get(username='member3')
        add_permission_to_user(perm1, m3)
        add_permission_to_user(perm2, m3)
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:set_collaborator_permissions'),
                                    {'member_id': m3.id, 'permission_ids': perm3.id + ',' + perm4.id})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])
        obj = UserPermissionList.objects.get(user=m3)
        self.assertIn(perm3.id, obj.permission_fk_list)
        self.assertIn(perm4.id, obj.permission_fk_list)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_move_member_to_group(self):
        """
        Make sure the url is reachable
        """
        ct = ContentType.objects.all()[0]
        Permission.objects.all().delete()
        perm1 = Permission.objects.create(codename='ik_action1', name="Can do action 1", content_type=ct)
        m3 = Member.objects.get(username='member3')
        add_permission_to_user(perm1, m3)
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:move_member_to_group'),
                                    {'member_id': m3.id, 'group_id': '5804b37b3379b531e01eb6d1'})
        self.assertEqual(response.status_code, 200)
        obj = UserPermissionList.objects.get(user=m3)
        self.assertListEqual(obj.permission_list, [])
        self.assertListEqual(obj.permission_fk_list, [])
        self.assertListEqual(obj.group_fk_list, ['5804b37b3379b531e01eb6d1'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_Collaborators(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:community'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_MemberList(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:member_list'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_AccessRequestList(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:access_request_list'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_view_member_profile(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:profile', args=('56eb6d04b37b3379b531e013', )))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_view_company_profile(self):
        """
        Make sure the url is reachable
        """
        response = self.client.get(reverse('ikwen:company_profile', args=('ikwen-service-2',)))
        self.assertEqual(response.status_code, 200)
