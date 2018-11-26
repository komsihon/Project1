# -*- coding: utf-8 -*-
import calendar
import json
from datetime import datetime, timedelta

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest

from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.revival.models import ProfileTag, CyclicRevival, MemberProfile
from ikwen.revival.utils import set_profile_tag_member_count
from ikwen.revival.tests_views import wipe_test_data


class RevivalUtilsTestCase(unittest.TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml', 'member_profiles.yaml']

    def setUp(self):
        self.client = Client()
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', UNIT_TESTING=True)
    def test_set_profile_tag_member_count(self):
        """
        member_count field for each ProfileTag must be set correctly
        """
        MemberProfile.objects.all().delete()
        call_command('loaddata', 'member_profiles.yaml')
        set_profile_tag_member_count()
        profile_tag1 = ProfileTag.objects.get(pk='58088fc0c253e5ddf0563951')
        profile_tag2 = ProfileTag.objects.get(pk='58088fc0c253e5ddf0563952')
        profile_tag3 = ProfileTag.objects.get(pk='58088fc0c253e5ddf0563953')
        self.assertEqual(profile_tag1.member_count, 1)
        self.assertEqual(profile_tag2.member_count, 3)
        self.assertEqual(profile_tag3.member_count, 3)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_CyclicRevival_set_next_run_date_with_days_cycle(self):
        """
        When CyclicReval is set to run based on a certain days_cycle,
        the set_next_run_date method should set the next run to today + days_cycle
        """
        revival = CyclicRevival.objects.get(pk='56eb6d04b37b3379b3e5ddf1')
        revival.set_next_run_date()
        next_run = datetime.now().date() + timedelta(days=revival.days_cycle)
        self.assertEqual(revival.next_run_on, next_run)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_CyclicRevival_set_next_run_date_with_day_of_week_list_having_a_single_day(self):
        """
        When CyclicReval is set to run based on an certain list of days of week,
        the set_next_run_date method should set the next day
        """
        now = datetime.now()
        now_date = now.date()
        today = now.weekday() + 1
        next_day = (today + 7) % 7
        day_of_week_list = [next_day]
        revival = CyclicRevival.objects.get(pk='56eb6d04b37b3379b3e5ddf2')
        revival.day_of_week_list = day_of_week_list
        revival.save()
        revival.set_next_run_date()
        diff = revival.next_run_on - now_date
        self.assertEqual(diff.days, 7)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_CyclicRevival_set_next_run_date_with_day_of_week_list_having_multiple_days(self):
        """
        When CyclicReval is set to run based on an certain list of days of week,
        the set_next_run_date method should set the next day
        """
        now = datetime.now()
        now_date = now.date()
        today = now.weekday() + 1
        next_day = (today + 4) % 7
        day_of_week_list = [today, next_day]
        revival = CyclicRevival.objects.get(pk='56eb6d04b37b3379b3e5ddf2')
        revival.day_of_week_list = day_of_week_list
        revival.save()
        revival.set_next_run_date()
        diff = revival.next_run_on - now_date
        self.assertEqual(diff.days, 4)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_CyclicRevival_set_next_run_date_with_day_of_month_list_having_a_single_day(self):
        """
        When CyclicReval is set to run based on an certain list of days of month,
        the set_next_run_date method should set the next day
        """
        now = datetime.now()
        now_date = now.date()
        today = now.day
        days_count = calendar.monthrange(now.year, now.month)[1]
        next_day = (today + days_count) % days_count
        day_of_month_list = [next_day]
        revival = CyclicRevival.objects.get(pk='56eb6d04b37b3379b3e5ddf3')
        revival.day_of_month_list = day_of_month_list
        revival.save()
        revival.set_next_run_date()
        diff = revival.next_run_on - now_date
        self.assertEqual(diff.days, days_count)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102')
    def test_CyclicRevival_set_next_run_date_with_day_of_month_list_having_multiple_days(self):
        """
        When CyclicReval is set to run based on an certain list of days of week,
        the set_next_run_date method should set the next day
        """
        now = datetime.now()
        now_date = now.date()
        today = now.day
        days_count = calendar.monthrange(now.year, now.month)[1]
        next_day = (today + 21) % days_count
        day_of_month_list = [today, next_day]
        revival = CyclicRevival.objects.get(pk='56eb6d04b37b3379b3e5ddf3')
        revival.day_of_month_list = day_of_month_list
        revival.save()
        revival.set_next_run_date()
        diff = revival.next_run_on - now_date
        self.assertEqual(diff.days, 21)
