"""Regression for real post identity, date precision, profile counts and pending observations."""
import tempfile
import unittest
from pathlib import Path

from archive_common import load, save
from archive_pipeline import initialize
from collect_weibo import collect_snapshot, configure_desktop, resolve_observations
from user_profile import count_value, profile_expression
from weibo_web import full_time, mid_to_bid, permalink_mid


class Browser:
    def __init__(self, values): self.values = iter(values); self.calls = []
    def js(self, expression): self.calls.append(expression); return next(self.values)


class WebTests(unittest.TestCase):
    def test_real_64bit_permalink_roundtrip(self):
        for mid in ['1', '1234567', '5347170901296788', '5357707697326235']:
            self.assertEqual(permalink_mid('https://weibo.com/123/' + mid_to_bid(mid), '123'), mid)
        with self.assertRaises(ValueError): permalink_mid('https://weibo.com/456/' + mid_to_bid('5347170901296788'), '123')
        with self.assertRaises(ValueError): permalink_mid('https://weibo.com/u/123', '123')
    def test_older_dates_are_not_assigned_to_current_year(self):
        now = '2026-11-01T12:00:00+08:00'
        self.assertEqual(full_time('2023-05-19 14:32', now), '2023-05-19T14:32:00+08:00')
        self.assertEqual(full_time('2小时前', now), '2026-11-01T10:00:00+08:00')
        self.assertEqual(full_time('2025-05-19T20:00:00Z', now), '2025-05-20T04:00:00+08:00')
        with self.assertRaises(ValueError): full_time('10-25 00:48', now)
    def test_profile_precision_and_unknown_are_preserved(self):
        self.assertEqual(count_value('粉丝 1.2万'), {'display':'1.2万','value':12000,'exact':False,'observed':True})
        self.assertEqual(count_value('0')['value'], 0)
        self.assertTrue(count_value('1,234')['exact'])
        self.assertIsNone(count_value(None)['value'])
        with self.assertRaises(ValueError): count_value('粉丝123关注456')
    def test_profile_is_scoped_to_target_not_login_avatar(self):
        selectors = {k:'#'+k for k in ['root','name','avatar','followers','following','engagement','logged_in','logged_out']}
        with self.assertRaises(ValueError): profile_expression('123',{**selectors,'root':'body'})
    def test_unidentified_posts_wait_for_real_permalink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize(root,'123','https://weibo.com/u/123','2025-01-01','2025-12-31')
            selectors = {k:'#'+k for k in ['root','cards','author','text','time','permalink','images','logged_in','logged_out','original_filter']}
            empty = {'success':True,'source_url':'https://weibo.com/u/123','records':[],'observed_count':0}
            configure_desktop(Browser([empty]),root,selectors)
            obs = {'author_uid':'123','is_original':True,'url':None,'raw_time':'2025-05-19 12:00','text':'夹具记录','images':[]}
            result = collect_snapshot(Browser([{**empty,'records':[obs],'observed_count':1}]),root,clock=lambda:0)
            self.assertEqual(result['status'],'resolve_pending');self.assertEqual(result['candidate_count'],0)
            pending = load(root/'pending-observations.json')[0]
            record = {'id':'12345','url':'https://weibo.com/123/'+mid_to_bid('12345'),'author_uid':'123','is_original':True,'created_at':'2025-05-19T12:00:00+08:00','text':'夹具记录','images':[]}
            with self.assertRaises(ValueError): resolve_observations(root,[{'observation_key':pending['observation_key'],'record':{**record,'id':'sha-fake'}}])
            self.assertEqual(len(load(root/'pending-observations.json')),1)
            self.assertEqual(resolve_observations(root,[{'observation_key':pending['observation_key'],'record':record}])['resolved'],1)
            self.assertEqual(load(root/'pending-observations.json'),[])


if __name__ == '__main__': unittest.main()
