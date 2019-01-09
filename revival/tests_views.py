# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest

from core.utils import add_database
from echo.models import Balance
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.revival.models import ProfileTag, CyclicRevival


def wipe_test_data(alias='default'):
    """
    This test was originally built with django-nonrel 1.6 which had an error when flushing the database after
    each test. So the flush is performed manually with this custom tearDown()
    """
    import ikwen.core.models
    import ikwen.accesscontrol.models
    import ikwen.revival.models
    import permission_backend_nonrel.models
    if alias != 'default' and alias != 'umbrella':
        add_database(alias)

    Balance.objects.using('wallets').all().delete()
    Group.objects.using(alias).all().delete()
    for name in ('Application', 'Service', 'Config', 'ConsoleEventType', 'ConsoleEvent', 'Country', ):
        model = getattr(ikwen.core.models, name)
        model.objects.using(alias).all().delete()
    for name in ('Member', 'AccessRequest', ):
        model = getattr(ikwen.accesscontrol.models, name)
        model.objects.using(alias).all().delete()
    for name in ('ProfileTag', 'ObjectProfile', 'MemberProfile', 'Revival', 'CyclicRevival',
                 'Target', 'CyclicTarget', ):
        model = getattr(ikwen.revival.models, name)
        model.objects.using(alias).all().delete()
    for name in ('UserPermissionList', 'GroupPermissionList',):
        model = getattr(permission_backend_nonrel.models, name)
        model.objects.using(alias).all().delete()


# class RevivalViewsTestCase(unittest.TestCase):
#     """
#     This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
#     Thus, self.client is not automatically created and fixtures not automatically loaded. This
#     will be achieved manually by a custom implementation of setUp()
#     """
#     fixtures = ['ikwen_members.yaml', 'setup_data.yaml']
#
#     def setUp(self):
#         self.client = Client()
#         call_command('loaddata', 'ikwen_members.yaml', database=UMBRELLA)
#         call_command('loaddata', 'setup_data.yaml', database=UMBRELLA)
#         for fixture in self.fixtures:
#             call_command('loaddata', fixture)
#
#     def tearDown(self):
#         wipe_test_data()
#         wipe_test_data(UMBRELLA)
#         wipe_test_data('test_ikwen_service_2')
#
#     @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
#     def test_ProfileTagList(self):
#         """
#         Make sure the url is reachable
#         """
#         self.client.login(username='member2', password='admin')
#         response = self.client.get(reverse('revival:profiletag_list'))
#         self.assertEqual(response.status_code, 200)
#
#     @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
#     def test_ChangeProfileTag_with_no_cyclic_revival(self):
#         name = 'New Profile'
#         self.client.login(username='member2', password='admin')
#         response = self.client.post(reverse('revival:change_profiletag'), {'name': name})
#         self.assertEqual(response.status_code, 302)
#         ProfileTag.objects.get(name=name)
#
#     @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', UNIT_TESTING=True)
#     def test_ChangeProfile_with_cyclic_revival_configuration(self):
#         name = 'New Cyclic Profile'
#         week_days = '7, 1',
#         hour_of_sending = 11
#         mail_subject = "Don't forget your meal"
#         mail_content = "<p>We have your lunch ready! Awesome beef stew for 1000 FCFA only.</p>"
#         sms_text = "We have your lunch ready! Awesome beef stew for 1000 FCFA only."
#         end_on = datetime.now() + timedelta(days=30)
#         conf = {'name': name, 'set_cyclic_revival': 'on', 'frequency_type': 'week_days',
#                 'week_days': week_days, 'hour_of_sending': hour_of_sending, 'mail_subject': mail_subject,
#                 'mail_content': mail_content, 'sms_text': sms_text, 'end_on': end_on.strftime('%Y-%m-%d'),
#                 'mail_image_url': ''}
#         self.client.login(username='member2', password='admin')
#         response = self.client.post(reverse('revival:change_profiletag'), conf)
#         self.assertEqual(response.status_code, 302)
#         profile_tag = ProfileTag.objects.get(name=name)
#         revival = CyclicRevival.objects.using(UMBRELLA).get(service='56eb6d04b37b3379b531b102', profile_tag_id=profile_tag.id)
#         self.assertIsNone(revival.days_cycle)
#         self.assertEqual(revival.hour_of_sending, 11)
#         self.assertListEqual(revival.day_of_week_list, [1, 7])
#         self.assertListEqual(revival.day_of_month_list, [])
#         self.assertEqual(revival.mail_subject, mail_subject)
#         self.assertEqual(revival.mail_content, mail_content)
#         self.assertEqual(revival.sms_text, sms_text)
#         self.assertEqual(revival.end_on, end_on.date())