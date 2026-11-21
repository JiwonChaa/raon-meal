import unittest, datetime as dt
from reel_schedule import active_slot, eligible, KST
class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.at=dt.datetime(2026,9,21,17,tzinfo=KST)  # Monday
        self.q={'slots':{'A':'17:00'},'done':[]}
        self.item={'slot':'A','scheduled_at':self.at.isoformat()}
    def test_no_early_or_overnight_publication(self):
        for h in (0,8,12,16):self.assertIsNone(active_slot(self.at.replace(hour=h)))
        self.assertFalse(eligible(self.q,self.item,'A',self.at-dt.timedelta(seconds=1)))
    def test_exact_weekday_slot(self):
        self.assertTrue(eligible(self.q,self.item,'A',self.at))
    def test_every_weekday_open_weekend_closed(self):
        for d in range(5):self.assertEqual(active_slot(self.at+dt.timedelta(days=d)),'A')
        for d in (5,6):self.assertIsNone(active_slot(self.at+dt.timedelta(days=d)))
    def test_overdue_friday_item_waits_for_monday(self):
        fri=self.at+dt.timedelta(days=4);item=dict(self.item,scheduled_at=fri.isoformat())
        self.assertFalse(eligible(self.q,item,'A',fri+dt.timedelta(days=1)))
        self.assertFalse(eligible(self.q,item,'A',fri+dt.timedelta(days=2)))
        self.assertTrue(eligible(self.q,item,'A',fri+dt.timedelta(days=3)))
    def test_old_lunch_slot_rejected(self):
        self.assertFalse(eligible(self.q,dict(self.item,slot='B'),'B',self.at))
    def test_future_item_never_publishes_early(self):
        self.assertFalse(eligible(self.q,dict(self.item,scheduled_at=(self.at+dt.timedelta(days=1)).isoformat()),'A',self.at))
    def test_one_queue_post_per_day(self):
        for field in ('at','published_at'):
            self.q['done']=[{'slot':'A',field:self.at.isoformat()}]
            self.assertFalse(eligible(self.q,self.item,'A',self.at+dt.timedelta(hours=2)))
    def test_yesterdays_post_does_not_block(self):
        self.q['done']=[{'slot':'A','published_at':(self.at-dt.timedelta(days=1)).isoformat()}]
        self.assertTrue(eligible(self.q,self.item,'A',self.at))
    def test_timezone_conversion(self):
        self.assertTrue(eligible(self.q,self.item,'A',self.at.astimezone(dt.timezone.utc)))
    def test_bad_slot_timestamp_rejected(self):
        with self.assertRaises(RuntimeError):eligible(self.q,dict(self.item,scheduled_at=self.at.replace(hour=18).isoformat()),'A',self.at.replace(hour=18))
        with self.assertRaises(RuntimeError):eligible(self.q,dict(self.item,scheduled_at='2026-09-21T17:00:00'),'A',self.at)
if __name__=='__main__':unittest.main()
