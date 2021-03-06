from datetime import timedelta
from django.utils import unittest, timezone
from django.db import models
from djangotoolbox.fields import ListField
from ikwen.core.utils import set_counters

from ikwen.core.utils import increment_history_field, calculate_watch_info, rank_watch_objects, \
    group_history_value_list


class WatchObject(models.Model):
    val1_history = models.CharField(max_length=20)
    val2_history = ListField()
    total_val1 = models.IntegerField(default=0)
    total_val2 = models.IntegerField(default=0)

    class Meta:
        app_label = 'core'


def init_watch_object():
    watch_object = WatchObject()
    watch_object.val1_history = '18,9,57,23,46'
    watch_object.val2_history = [18, 9, 57, 23, 46]
    return watch_object


class CoreUtilsTestCase(unittest.TestCase):
    """
    This test derives django.utils.unittest.TestCate rather than the default django.test.TestCase.
    Thus, self.client is not automatically created and fixtures not automatically loaded. This
    will be achieved manually by a custom implementation of setUp()
    """
    # fixtures = ['kc_setup_data.yaml', 'kc_members.yaml', 'kc_profiles.yaml']
    #
    # def setUp(self):
    #     self.client = Client()
    #     for fixture in self.fixtures:
    #         call_command('loaddata', fixture)
    #
    # def tearDown(self):
    #     wipe_test_data()

    def test_increment_history_field(self):
        """
        Last element of the report fields are incremented by the number passed as parameter
        """
        watch_object = init_watch_object()
        increment_history_field(watch_object, 'val1_history', 10)
        increment_history_field(watch_object, 'val2_history', 10)
        self.assertEqual(watch_object.val1_history, '18,9,57,23,56.0')
        self.assertListEqual(watch_object.val2_history, [18, 9, 57, 23, 56])
        self.assertEqual(watch_object.total_val1, 10)
        self.assertEqual(watch_object.total_val2, 10)

    def test_calculate_watch_info_with_less_history_values_than_period(self):
        watch_object = init_watch_object()
        watch_info0 = calculate_watch_info(watch_object.val2_history)
        watch_info1 = calculate_watch_info(watch_object.val2_history, duration=1)
        watch_info7 = calculate_watch_info(watch_object.val2_history, duration=7)
        watch_info28 = calculate_watch_info(watch_object.val2_history, duration=28)

        self.assertDictEqual(watch_info0, {'total': 46, 'change': None, 'change_rate': None})
        self.assertDictEqual(watch_info1, {'total': 23, 'change': None, 'change_rate': None})
        self.assertDictEqual(watch_info7, {'total': 107, 'change': None, 'change_rate': None})
        self.assertDictEqual(watch_info28, {'total': 107, 'change': None, 'change_rate': None})

    def test_calculate_watch_info_with_sufficient_history_values(self):
        watch_object = init_watch_object()
        watch_object.val2_history = list(range(57))
        watch_info0 = calculate_watch_info(watch_object.val2_history)
        watch_info1 = calculate_watch_info(watch_object.val2_history, duration=1)
        watch_info7 = calculate_watch_info(watch_object.val2_history, duration=7)
        watch_info28 = calculate_watch_info(watch_object.val2_history, duration=28)

        t0_28 = sum(range(28))
        t28_56 = sum(range(28, 56))
        self.assertDictEqual(watch_info0, {'total': 56, 'change': None, 'change_rate': None})
        self.assertDictEqual(watch_info1, {'total': 55, 'change': 55 - 48, 'change_rate': (55 - 48)/48.0 * 100})
        self.assertDictEqual(watch_info7, {'total': 364, 'change': 364 - 315, 'change_rate': (364 - 315)/315.0 * 100})
        self.assertDictEqual(watch_info28, {'total': t28_56, 'change': t28_56 - t0_28, 'change_rate': float(t28_56 - t0_28) / t0_28 * 100})

    def test_calculate_rank_watch_objects(self):
        wo1 = WatchObject()
        wo1.val2_history = list(range(57))
        wo2 = WatchObject()
        wo2.val2_history = list(range(56, -1, -1))
        wo3 = WatchObject()
        wo3.val2_history = list(range(0, 110, 2))

        l = [wo1, wo2, wo3]
        ranked_watch_objects0 = rank_watch_objects(l, 'val2_history')
        ranked_watch_objects1 = rank_watch_objects(l, 'val2_history', 1)
        ranked_watch_objects7 = rank_watch_objects(l, 'val2_history', 7)
        ranked_watch_objects28 = rank_watch_objects(l, 'val2_history', 28)

        self.assertListEqual([wo3, wo1, wo2], ranked_watch_objects0)
        self.assertListEqual([wo3, wo1, wo2], ranked_watch_objects1)
        self.assertListEqual([wo3, wo1, wo2], ranked_watch_objects7)
        self.assertListEqual([wo3, wo1, wo2], ranked_watch_objects28)

    def test_set_counters(self):
        watch_object = init_watch_object()
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        watch_object.counters_reset_on = now
        set_counters(watch_object)
        self.assertEqual(watch_object.val1_history, '18,9,57,23,46')
        self.assertListEqual(watch_object.val2_history, [18, 9, 57, 23, 46])
        watch_object.counters_reset_on = yesterday
        set_counters(watch_object)
        self.assertEqual(watch_object.val1_history, '18,9,57,23,46,0')
        self.assertListEqual(watch_object.val2_history, [18, 9, 57, 23, 46, 0])

    # def test_group_history_value_list(self):
    #     watch_object = init_watch_object()
    #     watch_object.val2_history = list(range(57))
    #     grouped_monthly = group_history_value_list(watch_object.val2_history)
    #     grouped_weekly = group_history_value_list(watch_object.val2_history, group_unit='week')
    #
    #     # monthly = [1, sum(range(1, 29)), sum(range(29, 57))]
    #     weekly = [0, sum(range(1, 8)), sum(range(8, 15)), sum(range(15, 22)), sum(range(22, 29)),
    #                sum(range(29, 36)), sum(range(36, 43)), sum(range(43, 50)), sum(range(50, 57))]
    #
    #     # self.assertListEqual(grouped_monthly, monthly)
    #     self.assertListEqual(grouped_weekly, weekly)

