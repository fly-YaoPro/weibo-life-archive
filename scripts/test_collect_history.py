"""Regression for bounded desktop history traversal, evidence and labelled video media."""
import io
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archive_common import load, save
from archive_pipeline import ingest, initialize, materialize
from collect_weibo import collect_history, configure_history, confirm_history_end, resolve_history_observations, resume_history_after_verification, verify_history_pins
from manage_media import download, plan
from test_pipeline import png
from weibo_web import mid_to_bid, timeline_payload, timeline_request

UID = '1705586121'
REQUEST = '/ajax/statuses/mymblog?uid=' + UID + '&page=1&feature=0&count=20'
SELECTORS = {key: '#' + key for key in ('root', 'cards', 'author', 'text', 'time', 'permalink', 'images', 'logged_in', 'logged_out', 'original_filter')}


def post(rid, created='2025-06-01T12:00:00+08:00', **fields):
    return {'id': int(rid), 'idstr': str(rid), 'user': {'idstr': UID}, 'created_at': created,
            'text': '<p>真实字段的合成正文</p>', 'text_raw': '真实字段的合成正文', **fields}


class Clock:
    def __init__(self): self.now = 100
    def time(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Browser:
    def __init__(self, pages): self.pages = iter(pages); self.calls = []
    def js(self, expression):
        self.calls.append(expression)
        if 'XMLHttpRequest' not in expression:
            return {'success': True, 'source_url': 'https://weibo.com/u/' + UID, 'records': [], 'observed_count': 0}
        import re
        request = json.loads(re.search(r'const requestPath=(".*?"),x=', expression).group(1))
        payload = next(self.pages)
        if isinstance(payload, Exception): raise payload
        if isinstance(payload, dict) and 'http_status' in payload: return payload
        return {'success': True, 'source_url': 'https://weibo.com/u/' + UID,
                'http_status': 200, 'request_path': request, 'body': json.dumps(payload)}


def page(rows, cursor): return {'ok': 1, 'data': {'list': rows, 'since_id': cursor, 'total': 6160}}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.root = Path(self.temporary.name)
        initialize(self.root, UID, 'https://weibo.com/u/' + UID, '2025-01-01', '2025-12-31', mode='full')
        meta = load(self.root / 'project_meta.json'); meta['collection']['include_video_covers'] = True
        save(self.root / 'project_meta.json', meta)
        self.clock = Clock()
        self.assertEqual(configure_history(Browser([]), self.root, SELECTORS, REQUEST)['status'], 'configured')
    def tearDown(self): self.temporary.cleanup()
    def collect(self, browser, **kw):
        return collect_history(browser, self.root, clock=self.clock.time, sleep=self.clock.sleep, **kw)

    def test_pinned_old_post_does_not_end_history_or_fill_unread_months(self):
        browser = Browser([page([post(100, '2010-01-01T12:00:00+08:00', isTop=True), post(99)], 12345678901234567890)])
        result = self.collect(browser, max_pages=1)
        self.assertEqual(result['status'], 'ready')
        state = load(self.root / 'history-state.json')
        self.assertEqual(state['since_id'], '12345678901234567890')
        self.assertEqual(state['boundary_streak'], 0)
        coverage = load(self.root / 'monthly_coverage.json')
        self.assertEqual([(r['month'], r['status']) for r in coverage], [('2025-06', 'partial')])
        self.assertEqual(state['pages'][0]['oldest'], '2010-01-01')
        self.assertTrue(state['pages'][0]['chronology_verified'])

    def test_two_ordered_boundary_pages_resume_without_duplicate_network_calls(self):
        first = Browser([page([post(300, '2025-12-01T12:00:00+08:00'), post(299, '2024-12-30T12:00:00+08:00')], '9007199254740993123')])
        self.assertEqual(self.collect(first, max_pages=1)['status'], 'ready')
        self.assertEqual(load(self.root / 'history-state.json')['boundary_streak'], 1)
        second = Browser([page([post(298, '2024-12-29T12:00:00+08:00'), post(297, '2024-11-01T12:00:00+08:00')], '123')])
        self.assertEqual(self.collect(second, max_pages=1)['status'], 'complete')
        self.assertIn('since_id=9007199254740993123', second.calls[0])
        self.assertEqual(len(first.calls) + len(second.calls), 2)
        self.assertEqual(self.collect(Browser([]))['status'], 'complete')
        self.assertTrue(all(c['status'] == 'complete' and c['evidence']['boundary_confirmed'] for c in load(self.root / 'monthly_coverage.json')))
        self.assertEqual(len(load(self.root / 'candidates.json')), 1)

    def test_unlabelled_old_prefix_is_retained_pending_normal_pin_evidence(self):
        result = self.collect(Browser([page([post(100, '2010-01-01T12:00:00+08:00'), post(99)], '1')]), max_pages=1)
        self.assertEqual(result['status'], 'ready')
        state = load(self.root / 'history-state.json')
        self.assertEqual(state['order_exceptions'][0]['id'], '100')
        self.assertFalse(state['order_exceptions'][0]['verified_as_pin'])
        self.assertEqual(state['oldest_ordinary_at'], '2025-06-01T12:00:00+08:00')
        self.assertFalse(any(c['status'] == 'complete' for c in load(self.root / 'monthly_coverage.json')))

    def test_real_first_page_prefix_does_not_block_later_history_and_needs_pin_verification(self):
        rows = [post('5186829667533470', 'Thu Jul 10 12:00:22 +0800 2025'),
                post('5176682719218571', 'Thu Jun 12 12:00:01 +0800 2025'),
                post('5360383188796715', 'Sun Nov 01 10:00:06 +0800 2026'),
                post('5360081597368030', 'Sat Oct 31 14:01:41 +0800 2026')]
        self.assertEqual(self.collect(Browser([page(rows, '5336556350735531kp2')]), max_pages=1)['status'], 'ready')
        state = load(self.root / 'history-state.json')
        self.assertEqual(len(state['order_exceptions']), 2)
        self.assertEqual(state['oldest_ordinary_at'], '2026-10-31T14:01:41+08:00')
        # The old prefix stays in candidates if it falls in the requested period.
        self.assertEqual(len(load(self.root / 'candidates.json')), 2)
        second = [post('5336556350735531', 'Thu Aug 27 16:00:45 +0800 2026'),
                  post('4000000000000001', 'Tue Dec 31 12:00:00 +0800 2024')]
        self.assertEqual(self.collect(Browser([page(second, '5294618670793938kp3')]), max_pages=1)['status'], 'ready')
        self.assertEqual(self.collect(Browser([page([post('4000000000000000', 'Mon Dec 30 12:00:00 +0800 2024')], '5280000000000000kp4')]), max_pages=1)['status'], 'verify_order')
        self.assertFalse(any(c['status'] == 'complete' for c in load(self.root / 'monthly_coverage.json')))
        class PinsBrowser:
            def js(self, expression):
                return {'success': True, 'source_url': 'https://weibo.com/u/' + UID,
                        'pinned_urls': ['https://weibo.com/' + UID + '/' + mid_to_bid(row['idstr']) for row in rows[:2]]}
        result = verify_history_pins(PinsBrowser(), self.root, {'pinned_cards': '.observed-pin-card', 'permalink': '.observed-post-link'})
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(all(c['status'] == 'complete' for c in load(self.root / 'monthly_coverage.json')))
        state = load(self.root / 'history-state.json')
        self.assertTrue(all(item['verified_as_pin'] for item in state['order_exceptions']))
        self.assertEqual(len(state['pin_verifications'][0]['pinned_urls']), 2)

    def test_unexpected_middle_order_violation_still_blocks_coverage(self):
        rows = [post(100, '2025-06-01T12:00:00+08:00'), post(99, '2024-01-01T12:00:00+08:00'), post(98, '2025-05-01T12:00:00+08:00')]
        result = self.collect(Browser([page(rows, 'cursor')]))
        self.assertEqual((result['status'], result['reason']), ('handoff', 'non_monotonic_timeline'))

    def test_pin_verification_rebuilds_previously_blocked_cached_page_and_resumes(self):
        self.assertEqual(self.collect(Browser([page([post(100)], 'cursor-1')]), max_pages=1)['status'], 'ready')
        mixed = [post(20, '2010-01-01T12:00:00+08:00'), post(99, '2025-05-01T12:00:00+08:00')]
        self.assertEqual(self.collect(Browser([page(mixed, 'cursor-2')]), max_pages=1)['status'], 'handoff')
        cache = self.root / 'history-pages/000002.json'; raw_before = cache.read_bytes()
        class PinsBrowser:
            def js(self, expression):
                return {'success': True, 'source_url': 'https://weibo.com/u/' + UID,
                        'pinned_urls': ['https://weibo.com/' + UID + '/' + mid_to_bid('20')]}
        result = verify_history_pins(PinsBrowser(), self.root, {'pinned_cards': '.actual-pin', 'permalink': '.post-link'})
        self.assertEqual(result['status'], 'verified')
        state = load(self.root / 'history-state.json')
        self.assertNotIn('blocked', state)
        self.assertEqual(state['oldest_ordinary_at'], '2025-05-01T12:00:00+08:00')
        self.assertEqual(state['pages'][1]['order_revisions'][0]['previous']['chronology_verified'], False)
        self.assertEqual(state['resolved_blocks'][0]['reason'], 'non_monotonic_timeline')
        self.assertEqual(cache.read_bytes(), raw_before)
        self.clock.now = state['next_allowed_at']
        result = self.collect(Browser([page([post(98, '2025-04-01T12:00:00+08:00')], 'cursor-3')]), max_pages=1)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['next_page'], 4)

    def test_empty_page_and_repeated_cursor_are_not_complete(self):
        self.assertEqual(self.collect(Browser([page([], '')]))['status'], 'verify_boundary')
        self.assertEqual(load(self.root / 'monthly_coverage.json'), [])
        (self.root / 'history-state.json').unlink()
        self.assertEqual(self.collect(Browser([page([post(100)], 'cursor')]), max_pages=1)['status'], 'ready')
        result = self.collect(Browser([page([post(99, '2025-05-01T12:00:00+08:00')], 'cursor')]), max_pages=1)
        self.assertEqual((result['status'], result['reason']), ('handoff', 'repeated_cursor'))

    def test_history_gate_only_needs_login_and_target_feed_and_boundary_retry_is_bounded(self):
        minimal = {key: SELECTORS[key] for key in ('root', 'logged_in', 'logged_out')}
        self.assertEqual(configure_history(Browser([]), self.root, minimal, REQUEST)['status'], 'configured')
        self.assertEqual(self.collect(Browser([page([], '')]))['status'], 'verify_boundary')
        self.assertEqual(resume_history_after_verification(Browser([]), self.root)['status'], 'verify_boundary')
        self.assertEqual(resume_history_after_verification(Browser([]), self.root, retry_boundary=True)['status'], 'verified')
        state = load(self.root / 'history-state.json')
        self.assertEqual((state['page'], state['since_id'], state['boundary_retries']), (1, None, 1))
        self.clock.now = state['next_allowed_at']
        retry = Browser([page([], '')])
        result = self.collect(retry)
        self.assertEqual((result['status'], result['processed_pages']), ('verify_boundary', 1))
        self.assertTrue((self.root / 'history-pages/000001.json').exists())
        self.assertTrue((self.root / 'history-pages/000001-attempt01.json').exists())
        self.assertEqual(resume_history_after_verification(Browser([]), self.root, retry_boundary=True)['status'], 'verify_boundary')
        self.assertEqual(len(load(self.root / 'history-state.json')['pages']), 2)

    def test_visible_site_end_confirmation_requires_actual_marker_and_keeps_evidence(self):
        self.assertEqual(self.collect(Browser([page([], '')]))['status'], 'verify_boundary')
        self.assertEqual(confirm_history_end(Browser([]), self.root, '核验正常页面结束提示')['status'], 'verify_boundary')
        config = load(self.root / 'history-collection.json'); config['selectors']['end_marker'] = '#actual-end'; save(self.root / 'history-collection.json', config)
        self.assertEqual(confirm_history_end(Browser([]), self.root, '核验正常页面结束提示')['status'], 'verify_boundary')
        class EndBrowser:
            def js(self, expression):
                return {'success': True, 'source_url': 'https://weibo.com/u/' + UID, 'end_visible': True}
        self.assertEqual(confirm_history_end(EndBrowser(), self.root, '实际页面显示没有更多微博')['status'], 'complete')
        state = load(self.root / 'history-state.json')
        self.assertEqual(state['end_verification']['selector'], '#actual-end')
        self.assertTrue(all(c['status'] == 'complete' for c in load(self.root / 'monthly_coverage.json')))
        self.assertEqual(self.collect(Browser([]))['status'], 'complete')

    def test_empty_page_retry_may_repeat_uncommitted_response_cursor_and_continue(self):
        self.assertEqual(self.collect(Browser([page([post(100)], 'cursor-1')]), max_pages=1)['status'], 'ready')
        self.assertEqual(self.collect(Browser([page([], 'cursor-2')]), max_pages=1)['status'], 'verify_boundary')
        self.assertEqual(resume_history_after_verification(Browser([]), self.root, retry_boundary=True)['status'], 'verified')
        self.clock.now = load(self.root / 'history-state.json')['next_allowed_at']
        retry = Browser([page([post(99, '2025-05-01T12:00:00+08:00')], 'cursor-2')])
        result = self.collect(retry)
        self.assertEqual(result['status'], 'ready')
        state = load(self.root / 'history-state.json')
        self.assertEqual((state['page'], state['since_id']), (3, 'cursor-2'))
        self.assertEqual(len(state['pages']), 3)
        self.assertNotIn('blocked', state)
        self.assertTrue((self.root / 'history-pages/000002.json').exists())
        self.assertTrue((self.root / 'history-pages/000002-attempt01.json').exists())

    def test_auth_failure_stops_across_fresh_calls_and_never_saves_private_body(self):
        browser = Browser([{'success': False, 'http_status': 403, 'body': 'PRIVATE COOKIE CHALLENGE'}])
        self.assertEqual(self.collect(browser)['status'], 'handoff')
        untouched = Browser([])
        self.assertEqual(self.collect(untouched)['status'], 'handoff'); self.assertEqual(untouched.calls, [])
        self.assertFalse((self.root / 'history-pages').exists())
        self.assertNotIn('PRIVATE', (self.root / 'history-state.json').read_text())
        self.assertEqual(resume_history_after_verification(Browser([]), self.root)['status'], 'verified')

    def test_failed_ingest_replays_saved_response_without_request(self):
        browser = Browser([page([post(100)], 'next')])
        with patch('collect_weibo.ingest', side_effect=OSError('interrupted')):
            self.assertEqual(self.collect(browser, max_pages=1)['status'], 'verify_once')
        state = load(self.root / 'history-state.json')
        self.assertIn('pending_page', state)
        self.clock.sleep(45)
        replay = Browser([])
        self.assertEqual(self.collect(replay, max_pages=1)['added'], 1)
        self.assertEqual(replay.calls, [])
        self.assertEqual(len(load(self.root / 'candidates.json')), 1)

    def test_malformed_api_dates_resolve_from_normal_details_and_replay_across_processes(self):
        self.assertEqual(self.collect(Browser([page([post(100)], 'cursor-1')]), max_pages=1)['status'], 'ready')
        missing = post(99); missing.pop('created_at')
        invalid = post(98, '昨天')
        result = self.collect(Browser([page([missing, invalid], 'cursor-2')]), max_pages=1)
        self.assertEqual((result['status'], result['reason']), ('handoff', 'invalid_page_requires_detail_verification'))
        raw = self.root / 'history-pages/000002.json'; original_bytes = raw.read_bytes()
        original_state = load(self.root / 'history-state.json')
        observations = [{'id': rid, 'author_uid': UID, 'created_at': created,
                         'source_url': 'https://weibo.com/' + UID + '/' + mid_to_bid(rid),
                         'captured_at': '2026-11-01T12:00:00+08:00'}
                        for rid, created in [('99', '2025-05-01T12:00:00+08:00'), ('98', '2025-04-01T12:00:00+08:00')]]
        # Register evidence in a fresh interpreter, then replay in a second one.
        script = 'import json,sys;from collect_weibo import resolve_history_observations;print(json.dumps(resolve_history_observations(sys.argv[1],json.loads(sys.argv[2]))))'
        repaired = subprocess.run([sys.executable, '-c', script, str(self.root), json.dumps(observations)], cwd=Path(__file__).parent, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(repaired.stdout)['status'], 'replay_ready')
        ledger = load(self.root / 'history-detail-overrides.json')
        self.assertEqual([entry['reason'] for entry in ledger['observations']], ['missing_created_at', 'invalid_created_at'])
        self.assertEqual(load(self.root / 'history-state.json')['pending_page']['sha256'], original_state['pending_page']['sha256'])
        self.assertEqual(raw.read_bytes(), original_bytes)
        replay_script = '''import json,sys
from pathlib import Path
from archive_common import load
from collect_weibo import collect_history
class Browser:
 def js(self,expression): raise AssertionError('cached repair must not request the API again')
root=Path(sys.argv[1]);clock=lambda:float(load(root/'history-state.json')['next_allowed_at'])+1
print(json.dumps(collect_history(Browser(),root,max_pages=1,clock=clock,sleep=lambda seconds:None)))
'''
        replayed = subprocess.run([sys.executable, '-c', replay_script, str(self.root)], cwd=Path(__file__).parent, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(replayed.stdout)['status'], 'ready')
        state = load(self.root / 'history-state.json')
        self.assertEqual((state['page'], state['since_id']), (3, 'cursor-2'))
        self.assertEqual(state['pages'][1]['detail_override_ids'], ['99', '98'])
        self.assertNotIn('blocked', state); self.assertNotIn('pending_page', state)
        self.assertEqual(raw.read_bytes(), original_bytes)
        records = {record['id']: record for record in load(self.root / 'candidates.json')}
        self.assertEqual(records['99']['created_at'], observations[0]['created_at'])
        self.assertEqual(records['98']['created_at'], observations[1]['created_at'])
        # Pin verification later replays chronology from the same original + override ledger.
        class PinsBrowser:
            def js(self, expression): return {'success': True, 'source_url': 'https://weibo.com/u/' + UID, 'pinned_urls': []}
        self.assertEqual(verify_history_pins(PinsBrowser(), self.root, {'pinned_cards': '.pin', 'permalink': '.link'})['status'], 'verified')
        self.assertEqual(raw.read_bytes(), original_bytes)

    def test_detail_date_repair_rejects_wrong_identity_url_dates_and_complete_original(self):
        missing = post(100); missing.pop('created_at')
        result = self.collect(Browser([page([missing, post(99)], 'cursor')]), max_pages=1)
        self.assertEqual(result['status'], 'handoff')
        observation = {'id': '100', 'author_uid': UID, 'created_at': '2025-07-01T12:00:00+08:00',
                       'source_url': 'https://weibo.com/' + UID + '/' + mid_to_bid('100'),
                       'captured_at': '2026-11-01T12:00:00+08:00'}
        state_before = (self.root / 'history-state.json').read_bytes()
        raw_before = (self.root / 'history-pages/000001.json').read_bytes()
        bad = [{**observation, 'author_uid': 'other'}, {**observation, 'id': '101'},
               {**observation, 'source_url': 'https://weibo.com/' + UID + '/' + mid_to_bid('101')},
               {**observation, 'source_url': 'https://weibo.com/123/' + mid_to_bid('100')},
               {**observation, 'source_url': 'https://weibo.com/u/' + UID},
               {**observation, 'created_at': '昨天'}, {**observation, 'captured_at': '2026-11-01T12:00:00'},
               {**observation, 'id': '99', 'source_url': 'https://weibo.com/' + UID + '/' + mid_to_bid('99')}]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError): resolve_history_observations(self.root, [item])
        with self.assertRaises(ValueError): resolve_history_observations(self.root, [observation, observation])
        with self.assertRaises(ValueError): resolve_history_observations(self.root, [observation] * 26)
        self.assertFalse((self.root / 'history-detail-overrides.json').exists())
        self.assertEqual((self.root / 'history-state.json').read_bytes(), state_before)
        self.assertEqual((self.root / 'history-pages/000001.json').read_bytes(), raw_before)

    def test_partial_date_repair_keeps_block_until_all_missing_dates_are_observed(self):
        one, two = post(100), post(99)
        one.pop('created_at'); two['created_at'] = None
        self.assertEqual(self.collect(Browser([page([one, two], 'cursor')]), max_pages=1)['status'], 'handoff')
        def evidence(rid, created):
            return {'id': rid, 'author_uid': UID, 'created_at': created, 'source_url': 'https://weibo.com/' + UID + '/' + mid_to_bid(rid), 'captured_at': '2026-11-01T12:00:00+08:00'}
        result = resolve_history_observations(self.root, [evidence('100', '2025-06-01T12:00:00+08:00')])
        self.assertEqual((result['status'], result['remaining_invalid_times']), ('resolve_pending', 1))
        self.assertIn('blocked', load(self.root / 'history-state.json'))
        result = resolve_history_observations(self.root, [evidence('99', '2025-05-01T12:00:00+08:00')])
        self.assertEqual(result['status'], 'replay_ready')
        self.assertEqual(len(load(self.root / 'history-detail-overrides.json')['observations']), 2)

    def test_interruption_after_ingest_does_not_commit_partial_page_summary(self):
        browser = Browser([page([post(100)], 'next')])
        import collect_weibo
        original = collect_weibo.save
        def interrupted(path, value):
            if Path(path).name == 'monthly_coverage.json': raise OSError('disk interrupted')
            return original(path, value)
        with patch('collect_weibo.save', side_effect=interrupted):
            self.assertEqual(self.collect(browser, max_pages=1)['status'], 'verify_once')
        state = load(self.root / 'history-state.json')
        self.assertEqual((state['page'], state['pages']), (1, []))
        self.assertEqual(len(load(self.root / 'candidates.json')), 1)
        self.clock.sleep(45)
        replay = Browser([])
        self.assertEqual(self.collect(replay, max_pages=1)['status'], 'ready')
        self.assertEqual(replay.calls, [])
        self.assertEqual(len(load(self.root / 'history-state.json')['pages']), 1)

    def test_batch_and_deadline_budget_allow_large_history_over_many_calls(self):
        for number in range(40):
            # Two records per page, stable time ordering across batches; repeated observation dedups.
            rid = 10000 - number * 2
            day = 28 - number // 2
            stamp = '2025-06-%02dT%02d:00:00+08:00' % (day, 12 if number % 2 == 0 else 10)
            browser = Browser([page([post(rid, stamp), post(rid - 1, stamp)], str(number + 1))])
            self.assertEqual(self.collect(browser, max_pages=1)['status'], 'ready')
        self.assertEqual(len(load(self.root / 'history-state.json')['pages']), 40)
        self.assertEqual(len(load(self.root / 'candidates.json')), 80)
        pending = Browser([page([post(9000, '2025-05-01T12:00:00+08:00')], '41')])
        # Persistent 4-second interval would exceed this batch deadline, so make no request.
        self.assertEqual(self.collect(pending, deadline_seconds=1)['status'], 'cooldown')
        self.assertEqual(pending.calls, [])
        for count in (0, 6, 100, True):
            with self.assertRaises(ValueError): self.collect(Browser([]), max_pages=count)

    def test_raw_json_identity_and_cursor_precision(self):
        path = timeline_request(UID, REQUEST)
        body = '{"ok":1,"data":{"list":[{"id":12345678901234567890}],"since_id":98765432109876543210}}'
        payload, reason = timeline_payload({'success': True, 'http_status': 200, 'source_url': 'https://weibo.com/u/' + UID, 'request_path': path, 'body': body}, UID, path)
        self.assertIsNone(reason)
        self.assertEqual(payload['data']['list'][0]['idstr'], '12345678901234567890')
        self.assertEqual(payload['data']['since_id'], '98765432109876543210')
        for request in (REQUEST.replace('feature=0', 'feature=1'), REQUEST.replace('page=1', 'page=4'), 'https://weibo.com' + REQUEST):
            with self.assertRaises(ValueError): timeline_request(UID, request)

    def test_trace_data_envelope_without_ok_accepts_only_valid_schema(self):
        path = timeline_request(UID, REQUEST)
        response = {'success': True, 'http_status': 200, 'source_url': 'https://weibo.com/u/' + UID, 'request_path': path}
        payload = {'data': {'list': [post('5186829667533470')], 'since_id': '5336556350735531kp2', 'total': 6160}}
        decoded, reason = timeline_payload({**response, 'body': json.dumps(payload)}, UID, path)
        self.assertIsNone(reason); self.assertEqual(decoded['data']['since_id'], '5336556350735531kp2')
        for value in ({'data': {'list': []}}, {**payload, 'ok': 0}, {**payload, 'error': 'login_required'}):
            with self.subTest(value=value):
                decoded, reason = timeline_payload({**response, 'body': json.dumps(value)}, UID, path)
                self.assertIsNone(decoded); self.assertIsNotNone(reason)

    def test_video_cover_extraction_download_resume_and_third_party_failure_preserve_record(self):
        row = post(12345678901234567890, page_info={'type': 'video', 'page_pic': 'https://wx1.sinaimg.cn/cover.png', 'media_info': {'big_pic_info': {'pic_big': 'https://wx1.sinaimg.cn/cover-big.png'}}})
        ingest(self.root, {'ok': 1, 'data': {'list': [row]}})
        record = load(self.root / 'candidates.json')[0]
        self.assertEqual(record['id'], '12345678901234567890')
        self.assertEqual(record['url'], 'https://weibo.com/' + UID + '/' + mid_to_bid(record['id']))
        self.assertTrue(record['is_video']); self.assertEqual(record['images'], [])
        self.assertEqual(record['video']['covers'][0]['large_url'], 'https://wx1.sinaimg.cn/cover-big.png')
        materialize(self.root); self.assertEqual(plan(self.root)['jobs'], 2)  # Keep both observed archive variants.
        class Response(io.BytesIO):
            def geturl(self): return 'https://wx1.sinaimg.cn/cover.png'
        class Opener:
            calls = 0
            def open(self, *a, **kw): self.calls += 1; return Response(png())
        opener = Opener(); self.assertTrue(download(self.root, opener=opener)['ok'])
        calls = opener.calls; ingest(self.root, [row]); materialize(self.root)
        self.assertTrue(download(self.root, opener=opener)['ok']); self.assertEqual(opener.calls, calls)
        cover = load(self.root / 'records.json')[0]['video']['covers'][0]
        self.assertEqual(cover['download_status'], 'saved')
        (self.root / cover['thumb_path']).write_bytes(b'corrupt')
        self.assertTrue(download(self.root, opener=opener)['ok']); self.assertGreater(opener.calls, calls)
        ingest(self.root, [post(12345678901234567889, page_info={'type': 'video', 'page_pic': 'https://miaopai.com/observed.jpg'})])
        materialize(self.root); plan(self.root)
        self.assertFalse(download(self.root, opener=opener)['ok'])
        records = load(self.root / 'records.json'); self.assertEqual(len(records), 2)
        third_party = next(r for r in records if r['id'] == '12345678901234567889')
        self.assertEqual(third_party['video']['covers'][0]['download_status'], 'failed')
        self.assertEqual(third_party['video']['covers'][0]['source_url'], 'https://miaopai.com/observed.jpg')

    def test_real_nested_big_pic_schema_and_fallbacks_materialize_without_dict_urls(self):
        big = 'https://wx4.sinaimg.cn/orj1080/001RqsRzgy1iik8eg70ntj619d0pib2902.jpg'
        small = 'https://wx4.sinaimg.cn/orj480/001RqsRzgy1iik8eg70ntj619d0pib2902.jpg'
        thumbnail = 'https://wx4.sinaimg.cn/or180/001RqsRzgy1iik8eg70ntj619d0pib2902.jpg'
        variants = [
            {'pic_big': {'height': 918, 'url': big, 'width': 1633}, 'pic_small': {'height': 150, 'url': thumbnail, 'width': 267}},
            {'pic_big': big}, {'url': big}, {'pic_big': {'width': 1633}},
            {'pic_big': {'url': 123}, 'pic_small': {'url': thumbnail}},
        ]
        for number, info in enumerate(variants):
            with self.subTest(info=info):
                media = {'object_type': 'video', 'page_pic': {'url': small}, 'media_info': {'big_pic_info': info}}
                if number == 4: media['page_pic'] = {'height': 480}
                row = post(5186829667533470 - number, page_info=media)
                ingest(self.root, [row]); materialize(self.root)
                record = next(r for r in load(self.root / 'records.json') if r['id'] == row['idstr'])
                cover = record['video']['covers'][0]
                self.assertEqual(cover['source_url'], big if number < 3 else small if number == 3 else thumbnail)
                self.assertIsInstance(cover['large_url'], str)
                self.assertIsInstance(cover['thumb_url'], str)
        manifest = plan(self.root)
        self.assertEqual(manifest['jobs'], 10)  # Both observed variants are retained by default.
        self.assertTrue(all(isinstance(job['url'], str) for job in load(self.root / 'media-manifest.json')['jobs']))
        malformed = post(5186829667533460, is_video=True, video={'covers': [{'origin': 'platform', 'source_url': {'url': big}}]})
        with self.assertRaisesRegex(ValueError, 'URL必须是字符串'): ingest(self.root, [malformed])

    def test_missing_photo_metadata_and_collapsed_text_stay_pending(self):
        photos = {str(index): {'large': {'url': 'https://wx1.sinaimg.cn/%d.jpg' % index}} for index in range(9)}
        ingest(self.root, [post(100, pic_ids=[str(index) for index in range(12)], pic_infos=photos),
                           post(99, text='摘要<a href="/detail/99">展开全文</a>'),
                           post(98, textLength=9999),
                           post(97, page_info={'object_type': 'video'})])
        result = materialize(self.root)
        records = {r['id']: r for r in load(self.root / 'records.json')}
        self.assertEqual(records['100']['expected_image_count'], 12)
        self.assertEqual(len(records['100']['images']), 9)
        self.assertEqual(records['99']['text_status'], 'pending')
        self.assertEqual(records['98']['text_status'], 'complete')
        self.assertEqual((result['pending_details'], result['pending_photo_details'], result['pending_video_covers']), (4, 1, 1))  # The fourth record has an unknown source photo count, so remains pending.

    def test_window_filter_precedes_irrelevant_media_normalization(self):
        malformed_media = {'video': {'covers': [{'origin': 'platform', 'source_url': {'url': 'bad'}}]}}
        result = ingest(self.root, [post(100, '2010-01-01T12:00:00+08:00', **malformed_media), post(99)])
        self.assertEqual(result['candidate_count'], 1)
        self.assertEqual(result['batch']['out_of_range'], 1)

    def test_legacy_checkpoint_nested_cover_urls_repair_without_losing_source_or_local_files(self):
        big = 'https://wx4.sinaimg.cn/cover.jpg'
        row = post(100, page_info={'object_type': 'video', 'page_pic': big})
        ingest(self.root, [row]); materialize(self.root)
        candidates = load(self.root / 'candidates.json')
        legacy = candidates[0]['video']['covers'][0]
        descriptor = {'url': big, 'width': 1920, 'height': 1080}
        legacy.update(source_url=descriptor, large_url=descriptor, thumb_path='images/existing.jpg', large_path='images/existing.jpg', download_status='saved')
        save(self.root / 'candidates.json', candidates)
        save(self.root / 'records.json', candidates)
        self.assertEqual(materialize(self.root)['saved_count'], 1)
        repairs = load(self.root / 'media-url-repair-log.json')[-1]['indexes']
        self.assertEqual({entry['source_file'] for entry in repairs}, {'candidates.json', 'records.json'})
        self.assertTrue(all(entry['changes'][0]['record_id'] == '100' for entry in repairs))
        self.assertEqual(load(self.root / repairs[0]['backup_path'])[0]['video']['covers'][0]['source_url'], descriptor)
        record = load(self.root / 'records.json')[0]
        cover = record['video']['covers'][0]
        self.assertEqual(cover['source_url'], big)
        self.assertEqual(cover['legacy_url_descriptors']['source_url'], descriptor)
        self.assertEqual(cover['thumb_path'], 'images/existing.jpg')
        self.assertEqual(plan(self.root)['unique_urls'], 1)
        # A normal detail reimport also repairs the old candidate's merge identity.
        ingest(self.root, [row])
        self.assertEqual(load(self.root / 'candidates.json')[0]['video']['covers'][0]['source_url'], big)
        # Direct plan can repair old records even before a materialize invocation.
        save(self.root / 'records.json', candidates)
        self.assertTrue(plan(self.root)['repaired_legacy_descriptors'])
        self.assertEqual(load(self.root / 'records.json')[0]['video']['covers'][0]['source_url'], big)


if __name__ == '__main__': unittest.main()
