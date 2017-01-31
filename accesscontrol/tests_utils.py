# # -*- coding: utf-8 -*-
#
# import json
# from django.contrib.auth.models import Group, Permission
# from django.contrib.contenttypes.models import ContentType
# from django.core.management import call_command
# from django.core.urlresolvers import reverse
# from django.test.client import Client
# from django.test.utils import override_settings
# from django.utils import unittest
# from permission_backend_nonrel.models import UserPermissionList
# from permission_backend_nonrel.utils import add_permission_to_user
#
# from ikwen.core.utils import add_database_to_settings
#
# from ikwen.accesscontrol.tests_auth import wipe_test_data
# from ikwen.accesscontrol.models import Member, AccessRequest
# from ikwen.core.models import Service, ConsoleEventType, ConsoleEvent
#
#
# class IkwenAccessControlTestCase(unittest.TestCase):
#     """
#     This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
#     Thus, self.client is not automatically created and fixtures not automatically loaded. This
#     will be achieved manually by a custom implementation of setUp()
#     """
#     fixtures = ['ikwen_members.yaml', 'setup_data.yaml']
#
#     def setUp(self):
#         self.client = Client()
#         for fixture in self.fixtures:
#             call_command('loaddata', fixture)
#
#     def tearDown(self):
#         wipe_test_data()
#
#     @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101',
#                        EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
#                        EMAIL_FILE_PATH='test_emails/accesscontrol/')
#     def test_append_auth_tokens(self):
#         """
#         Requesting access must create an AccessRequest object and the corresponding ConsoleEvent.
#         The IAO of the service for which collaboration was requested must see that on his console.
#         """
#
#
#     @override_settings(PROJECT_URL='http://www.ikwen.com',
#                        DEBUG=False)
#     def test_ikwenize(self):
#         """
#         Granting access to collaborator adds him in the local database and
#         create the corresponding UserPermissionList object with the right group
#         """
#