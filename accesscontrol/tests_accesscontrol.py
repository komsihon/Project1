# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from permission_backend_nonrel.models import UserPermissionList
from permission_backend_nonrel.utils import add_permission_to_user

from ikwen.core.utils import add_database_to_settings

from ikwen.accesscontrol.tests_auth import wipe_test_data
from ikwen.accesscontrol.models import Member, COMMUNITY
from ikwen.core.models import Service, ConsoleEventType, ConsoleEvent
from ikwen.revival.models import MemberProfile


class IkwenAccessControlTestCase(unittest.TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml', 'member_profiles']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/accesscontrol/')
    def test_join(self):
        """
        Joining adds the requesting member in the service local database and
        create the corresponding UserPermissionList object with the right group
        """
        service = Service.objects.get(pk='56eb6d04b37b3379b531b102')
        et = ConsoleEventType.objects.get(pk='56eb6db3379b531a0104b371')  # Collaboration Access Request event type
        group_id = '5804b37b3379b531e01eb6d2'
        add_database_to_settings(service.database)
        Group.objects.using(service.database).create(pk=group_id, name=COMMUNITY)
        UserPermissionList.objects.using(service.database).all().delete()
        self.client.login(username='member3', password='admin')
        response = self.client.get(reverse('ikwen:join'), {'service_id': service.id, 'format': 'json'})
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])
        member3 = Member.objects.get(pk='56eb6d04b37b3379b531e013')
        self.assertIn(group_id, member3.group_fk_list)
        self.assertEqual(ConsoleEvent.objects.filter(member=service.member, event_type=et).count(), 0)
        perm_obj = UserPermissionList.objects.using(service.database).get(user=member3)
        self.assertListEqual(perm_obj.group_fk_list, [group_id])
        self.client.logout()
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:console'))
        self.assertEqual(len(response.context['event_list']), 1)
        self.client.logout()
        self.client.login(username='member3', password='admin')
        response = self.client.get(reverse('ikwen:console'))
        self.assertIn(service.id, member3.customer_on_fk_list)
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
        self.assertEqual(len(json_response), 2)
        self.assertEqual(json_response[0]['id'], '56eb6d04b37b3379b531e013')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_set_collaborator_permissions(self):
        """
        Setting collaborator's permissions clears preceding permissions and just reset them as new.
        This done to avoid to append the same permission multiple times in the permissions lists.
        Note that adding permissions to a Member automatically sets him as staff
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
        m3 = Member.objects.get(username='member3')
        obj = UserPermissionList.objects.get(user=m3)
        self.assertIn(perm3.id, obj.permission_fk_list)
        self.assertIn(perm4.id, obj.permission_fk_list)
        self.assertTrue(m3.is_staff)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_move_member_to_group(self):
        """
        Make sure the url is reachable
        """
        call_command('loaddata', 'ikwen_members.yaml', database='umbrella')
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
        m3_umbrella = Member.objects.using('umbrella').get(username='member3')
        self.assertIn('5804b37b3379b531e01eb6d1', m3_umbrella.group_fk_list)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_Community(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:community'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_Community_load_member_detail(self):
        """
        Make sure the action is working
        """
        ct = ContentType.objects.all()[0]
        Permission.objects.all().delete()
        perm1 = Permission.objects.create(codename='ik_action1', name="Can do action 1", content_type=ct)
        m3 = Member.objects.get(username='member3')
        add_permission_to_user(perm1, m3)
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:community'), {'action': 'load_member_detail', 'member_id': '56eb6d04b37b3379b531e013'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['member'])
        self.assertEqual(len(response.context['permission_list']), 1)
        self.assertIsNotNone(response.context['profiletag_list'])

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_Community_set_member_profiles(self):
        """
        Make sure the action is working
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:community'), {'action': 'set_member_profiles',
                                                                'member_id': '56eb6d04b37b3379b531e014',
                                                                'tag_ids': '58088fc0c253e5ddf0563952,58088fc0c253e5ddf0563953'})
        self.assertEqual(response.status_code, 200)
        member_profile = MemberProfile.objects.get(member='56eb6d04b37b3379b531e014')
        json_response = json.loads(response.content)
        self.assertTrue(json_response['success'])
        self.assertListEqual(member_profile.tag_list, ['women', 'kakocase'])


    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_MemberList_with_jsonp_search(self):
        """
        Make sure the url is reachable
        """
        response = self.client.get(reverse('ikwen:member_list'), {'q': 'mem', 'format': 'json'})
        json_response = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(json_response), 1)

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

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102',
                       STAFF_ROUTER=(
                               ('theming.ik_action1', 'some_view_name'),
                               ('theming.ik_action2', 'some_view_name'),
                               ('theming.ik_action3', 'ikwen:company_profile', ('ikwen-service-2',)),
                       ))
    def test_staff_router(self):
        """
        Make sure STAFF_ROUTER routes to the correct view
        """
        ct = ContentType.objects.get(name='template', app_label='theming')
        Permission.objects.all().delete()
        perm3 = Permission.objects.create(codename='ik_action3', name="Can do action 3", content_type=ct)
        m3 = Member.objects.get(username='member3')
        m3.is_staff = True
        m3.email_verified = True
        m3.save()
        add_permission_to_user(perm3, m3)
        self.client.login(username='member3', password='admin')
        response = self.client.get(reverse('ikwen:staff_router'), follow=True)
        final = response.redirect_chain[-1]
        location = final[0].replace('?splash=yes', '').strip('/').split('/')[-1]
        self.assertEqual(location, 'ikwen-service-2')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/accesscontrol/email_confirmation/')
    def test_EmailConfirmation_with_email_not_verified(self):
        """
        The EmailConfirmation sends an email verification to the user_email
        """
        Member.objects.filter(username='member2').update(email_verified=False)
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:email_confirmation'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_ConfirmEmail(self):
        """
        Hitting the correct ConfirmEmail sets member.email_verified to True
        """
        member = Member.objects.get(username='member2')
        member.email_verified = False
        member.save()
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = default_token_generator.make_token(member)
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:confirm_email', args=(uid, token)))
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(username='member2')
        self.assertTrue(member.email_verified)
