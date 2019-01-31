# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from django.core.management import call_command
from django.test.client import Client
from django.test.utils import override_settings
from django.utils import unittest

from echo.models import Balance
from ikwen.core.utils import add_database
from ikwen.accesscontrol.backends import UMBRELLA
from ikwen.accesscontrol.models import Member
from ikwen.revival.models import Target, Revival, MemberProfile
from ikwen.revival.tests_views import wipe_test_data
from ikwen.revival.smart_revival_crons import notify_profiles, notify_profiles_retro
from ikwen.rewarding.utils import REFERRAL
from revival.smart_revival_crons import rerun_complete_revivals


class RevivalViewsTestCase(unittest.TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    fixtures = ['ikwen_members.yaml', 'setup_data.yaml']

    def setUp(self):
        self.client = Client()
        call_command('loaddata', 'ikwen_members.yaml', database=UMBRELLA)
        call_command('loaddata', 'setup_data.yaml', database=UMBRELLA)
        call_command('loaddata', 'revivals.yaml', database=UMBRELLA)
        for fixture in self.fixtures:
            call_command('loaddata', fixture)

    def tearDown(self):
        wipe_test_data()
        wipe_test_data(UMBRELLA)
        wipe_test_data('test_ikwen_service_2')

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', UNIT_TESTING=True)
    def test_notify_profiles_with_member_having_joined_less_than_seven_hours_ago(self):
        """
        Smart revival sends message at minimum 7 hours after
        Member joins the platform. This test is supposed to invoke
        revival with ID 58eb3eb637b33795ddfd04b1
        """
        db = 'test_ikwen_service_2'
        add_database(db)
        for fixture in self.fixtures:
            call_command('loaddata', fixture, database=db)
        call_command('loaddata', 'member_profiles.yaml', database=db)
        call_command('loaddata', 'revivals.yaml', database=db)
        Balance.objects.using('wallets').get_or_create(service_id='56eb6d04b37b3379b531b102', mail_count=1000)
        notify_profiles()
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b1').all().count()
        self.assertEqual(target_count, 0)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/revival/tsunami', UNIT_TESTING=True)
    def test_notify_profiles_with_tsunami_prospects_as_targets(self):
        """
        All member having 'kakocase' in their Profile should be target for this revival. Actually 3 of them
        """
        db = 'test_ikwen_service_2'
        add_database(db)
        for fixture in self.fixtures:
            call_command('loaddata', fixture, database=db)
        call_command('loaddata', 'member_profiles.yaml', database=db)
        call_command('loaddata', 'revivals.yaml', database=db)
        Balance.objects.using('wallets').get_or_create(service_id='56eb6d04b37b3379b531b102', mail_count=1000)
        seven_hours_ago = datetime.now() - timedelta(hours=7)
        Member.objects.using(db).all().update(date_joined=seven_hours_ago)
        Revival.objects.exclude(pk='58eb3eb637b33795ddfd04b1').update(is_active=False)
        notify_profiles()
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b1').filter(revival_count=1).count()
        self.assertEqual(target_count, 3)
        balance = Balance.objects.using('wallets').get(service_id='56eb6d04b37b3379b531b102')
        self.assertEqual(balance.mail_count, 997)
        revival = Revival.objects.get(pk='58eb3eb637b33795ddfd04b1')
        self.assertEqual(revival.progress, 3)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/revival/tsunami', UNIT_TESTING=True)
    def test_notify_profiles_with_suggest_create_account(self):
        """
        All member having 'kakocase' in their Profile should be target for this revival. Actually 3 of them
        """
        db = 'test_ikwen_service_2'
        add_database(db)
        for fixture in self.fixtures:
            call_command('loaddata', fixture, database=db)
        call_command('loaddata', 'member_profiles.yaml', database=db)
        call_command('loaddata', 'revivals.yaml', database=db)
        Balance.objects.using('wallets').get_or_create(service_id='56eb6d04b37b3379b531b102', mail_count=1000)
        seven_hours_ago = datetime.now() - timedelta(hours=7)
        Member.objects.using(db).all().update(date_joined=seven_hours_ago)
        Member.objects.using(db).filter(username='member4').update(is_ghost=True)
        notify_profiles()
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b1').all().count()
        self.assertEqual(target_count, 3)
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b2').all().count()
        self.assertEqual(target_count, 1)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/revival/tsunami', UNIT_TESTING=True)
    def test_notify_profiles_retro_with_suggest_referral(self):
        """
        Member newly having a tag in revival should be notified
        even if the revival for this tag has already been run before.
        """
        db = 'test_ikwen_service_2'
        add_database(db)
        for fixture in self.fixtures:
            call_command('loaddata', fixture, database=db)
        call_command('loaddata', 'member_profiles.yaml', database=db)
        call_command('loaddata', 'revivals.yaml', database=db)
        Balance.objects.using('wallets').get_or_create(service_id='56eb6d04b37b3379b531b102', mail_count=1000)
        seven_hours_ago = datetime.now() - timedelta(hours=7)
        Member.objects.using(db).all().update(date_joined=seven_hours_ago, is_ghost=True)

        Revival.objects.exclude(pk='58eb3eb637b33795ddfd04b3').update(is_active=False)
        notify_profiles()
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b3').all().count()
        self.assertEqual(target_count, 1)

        for member_profile in MemberProfile.objects.using(db).exclude(member='56eb6d04b37b3379b531e011'):
            member_profile.tag_fk_list.append('58088fc0c253e5ddf0563955')
            member_profile.save()

        notify_profiles_retro()
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b3').all().count()
        self.assertEqual(target_count, 4)

        balance = Balance.objects.using('wallets').get(service_id='56eb6d04b37b3379b531b102')
        self.assertEqual(balance.mail_count, 996)

    @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102',
                       EMAIL_BACKEND='django.core.mail.backends.filebased.EmailBackend',
                       EMAIL_FILE_PATH='test_emails/revival/tsunami', UNIT_TESTING=True)
    def test_rerun_complete_revivals_with_suggest_referral(self):
        """
        Re-running complete revivals resends notififications to members
        that have been hit before. The revival is re-run after a minimum of 3 days
        """
        db = 'test_ikwen_service_2'
        add_database(db)
        for fixture in self.fixtures:
            call_command('loaddata', fixture, database=db)
        call_command('loaddata', 'member_profiles.yaml', database=db)
        call_command('loaddata', 'revivals.yaml', database=db)
        Balance.objects.using('wallets').get_or_create(service_id='56eb6d04b37b3379b531b102', mail_count=1000)
        now = datetime.now()
        seven_hours_ago = now - timedelta(hours=7)
        Member.objects.using(db).all().update(date_joined=seven_hours_ago, is_ghost=True)

        Revival.objects.filter(pk__in=['58eb3eb637b33795ddfd04b1', '58eb3eb637b33795ddfd04b2']).update(is_active=False)

        for member_profile in MemberProfile.objects.using(db).exclude(member='56eb6d04b37b3379b531e011'):
            member_profile.tag_fk_list.append('58088fc0c253e5ddf0563955')
            member_profile.save()

        notify_profiles()
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b3').all().count()
        self.assertEqual(target_count, 4)

        three_days_ago = now - timedelta(days=3)
        Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b3').update(revived_on=three_days_ago)
        rerun_complete_revivals()
        target_count = Target.objects.using(db).filter(revival='58eb3eb637b33795ddfd04b3').filter(revival_count=2).count()
        self.assertEqual(target_count, 4)

        balance = Balance.objects.using('wallets').get(service_id='56eb6d04b37b3379b531b102')
        self.assertEqual(balance.mail_count, 992)


    # @override_settings(IKWEN_SERVICE_ID='56eb6d04b37b3379b531b102', UNIT_TESTING=True)
    # def test_notify_profiles_with_tsunami_prospects_as_targets(self):
    #     name = 'New Cyclic Profile'
    #     week_days = '7, 1',
    #     hour_of_sending = 11
    #     mail_subject = "Don't forget your meal"
    #     mail_content = "<p>We have your lunch ready! Awesome beef stew for 1000 FCFA only.</p>"
    #     sms_text = "We have your lunch ready! Awesome beef stew for 1000 FCFA only."
    #     end_on = datetime.now() + timedelta(days=30)
    #     conf = {'name': name, 'set_cyclic_revival': 'on', 'frequency_type': 'week_days',
    #             'week_days': week_days, 'hour_of_sending': hour_of_sending, 'mail_subject': mail_subject,
    #             'mail_content': mail_content, 'sms_text': sms_text, 'end_on': end_on.strftime('%Y-%m-%d'),
    #             'mail_image_url': ''}
    #     self.client.login(username='member2', password='admin')
    #     response = self.client.post(reverse('revival:change_profiletag'), conf)
    #     self.assertEqual(response.status_code, 302)
    #     profile_tag = ProfileTag.objects.get(name=name)
    #     revival = CyclicRevival.objects.using(UMBRELLA).get(service='56eb6d04b37b3379b531b102', profile_tag_id=profile_tag.id)
    #     self.assertIsNone(revival.days_cycle)
    #     self.assertEqual(revival.hour_of_sending, 11)
    #     self.assertListEqual(revival.day_of_week_list, [1, 7])
    #     self.assertListEqual(revival.day_of_month_list, [])
    #     self.assertEqual(revival.mail_subject, mail_subject)
    #     self.assertEqual(revival.mail_content, mail_content)
    #     self.assertEqual(revival.sms_text, sms_text)
    #     self.assertEqual(revival.end_on, end_on.date())