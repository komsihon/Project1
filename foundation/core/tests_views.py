# -*- coding: utf-8 -*-

# LOADING FIXTURES DOES NOT WORK BECAUSE Database connection 'foundation' is never found
# tests_views.py is an equivalent of these tests run by loading data into databases manually


import json
from urllib import unquote
from urlparse import urlparse

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.template.defaultfilters import urlencode
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest
from django.utils.translation import gettext as _
from permission_backend_nonrel.models import UserPermissionList
from permission_backend_nonrel.utils import add_permission_to_user

from ikwen.foundation.core.utils import get_service_instance, add_database_to_settings

from ikwen.foundation.accesscontrol.tests_auth import wipe_test_data

from foundation.accesscontrol.backends import UMBRELLA
from ikwen.foundation.accesscontrol.models import Member, AccessRequest
from ikwen.foundation.core.models import Service, Config, ConsoleEventType, ConsoleEvent


class IkwenCoreViewsTestCase(unittest.TestCase):
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

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', CACHES=None)
    def test_list_projects(self):
        """
        Lists projects with name contains the query 'q' and return a JSON Array of objects
        """
        self.client.login(username='member3', password='admin')
        response = self.client.get(reverse('ikwen:list_projects'), {'q': 'ik'})
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(len(json_response), 2)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', CACHES=None)
    def test_Console(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:console'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', CACHES=None)
    def test_Configuration(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:configuration'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', CACHES=None)
    def test_contact(self):
        """
        Contact should render ikwen/contact.html template
        """
        response = self.client.get(reverse('ikwen:contact'))
        self.assertEqual(response.status_code, 200)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b101', CACHES=None)
    def test_service_detail_page(self):
        """
        Make sure the url is reachable
        """
        self.client.login(username='member2', password='admin')
        response = self.client.get(reverse('ikwen:service_detail', args=('56eb6d04b37b3379b531b101', )))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['service'])
