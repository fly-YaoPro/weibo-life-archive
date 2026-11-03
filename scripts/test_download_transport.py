"""Live-channel failure-stop and provenance tests for the bu.download mobile transport."""
import json
import tempfile
import unittest
from pathlib import Path

from archive_common import load, save
from archive_pipeline import initialize, ingest
from collect_weibo import (
    MOBILE_TRANSPORTS, TRANSPORT_DOWNLOAD, TRANSPORT_SYNC_XHR,
    collect_mobile, configure_mobile, set_mobile_transport,
)

UID = '123'
WINDOW = ('2025-01-01', '2025-12-31')


def mblog(i, uid=UID, date='Mon Jan 01 12:00:00 +0800 2025', text='t', pics=None, top=False):
    m = {'id': 1000 + i, 'mid': 1000 + i, 'bid': 'B%d' % i,
         'created_at': date, 'user': {'id': int(uid)}, 'text': text,
         'pics': pics or []}
    if top:
        m['isTop'] = 1
        m['title'] = {'text': '置顶'}
    return m


def raw_page(mblogs, ok=1):
    return json.dumps({'ok': ok, 'data': {'cards': [
        {'card_type': 9, 'mblog': m} for m in mblogs]}}).encode('utf-8')


class FakeBu:
    """Simulates the native direct-download channel without touching a real browser."""

    def __init__(self, pages=None, raise_on_download=None):
        self.pages = pages or {}          # page -> bytes
        self.raise_on_download = raise_on_download
        self.download_calls = []
        self._tmp = tempfile.TemporaryDirectory()
        self.download_dir = Path(self._tmp.name)

    def cleanup(self):
        self._tmp.cleanup()

    def page_info(self):
        return {'url': 'https://m.weibo.cn/u/' + UID}

    def download(self, url, filename=None, timeout=30.0):
        self.download_calls.append((url, filename))
        if self.raise_on_download is not None:
            raise self.raise_on_download
        page = int(url.split('page=')[1])
        data = self.pages[page]
        path = self.download_dir / (filename or 'f.json')
        path.write_bytes(data)
        return {'state': 'completed', 'path': str(path), 'filename': filename,
                'bytes': len(data), 'source': 'direct', 'guid': 'g', 'url': url}

    def js(self, expression):
        # Legacy sync-XHR channel: echo a valid envelope around page-1 body.
        from weibo_web import mobile_container_path
        body = self.pages[1].decode('utf-8')
        return json.dumps({'success': True, 'http_status': 200,
                           'source_url': 'https://m.weibo.cn/u/' + UID,
                           'request_path': mobile_container_path(UID, 1), 'body': body})


class Clock:
    def __init__(self):
        self.now = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DownloadTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = Clock()
        initialize(self.root, UID, 'https://weibo.com/u/' + UID,
                   WINDOW[0], WINDOW[1], mode='selected')

    def tearDown(self):
        self.temp.cleanup()

    def _collect(self, fake, **kwargs):
        return collect_mobile(fake, self.root, clock=self.clock.time,
                              sleep=self.clock.sleep, **kwargs)

    def _configure(self, fake):
        r = configure_mobile(fake, self.root, transport=TRANSPORT_DOWNLOAD)
        self.assertEqual(r['status'], 'configured')

    def test_html_login_page_blocks_immediately(self):
        fake = FakeBu({1: b'<html><body>login</body></html>'})
        self._configure(fake)
        r = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual((r['status'], r['reason']), ('handoff', 'login_or_html_page'))
        self.assertTrue(load(self.root / 'mobile-state.json')['blocked'])
        # blocked state is sticky: a later call does not re-hit the network.
        calls = len(fake.download_calls)
        r2 = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r2['status'], 'handoff')
        self.assertEqual(len(fake.download_calls), calls)
        fake.cleanup()

    def test_business_error_blocks_immediately(self):
        fake = FakeBu({1: json.dumps({'ok': 0, 'msg': 'denied'}).encode()})
        self._configure(fake)
        r = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r['status'], 'handoff')
        self.assertEqual(r['reason'], 'business_error_or_verification')
        fake.cleanup()

    def test_truncated_json_blocks_immediately(self):
        fake = FakeBu({1: b'{"ok":1,"data":{"cards":['})
        self._configure(fake)
        r = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual((r['status'], r['reason']),
                         ('handoff', 'invalid_or_truncated_json'))
        fake.cleanup()

    def test_other_author_gets_one_recheck_then_blocks(self):
        fake = FakeBu({1: raw_page([mblog(1, uid='999')])})
        self._configure(fake)
        r1 = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r1['status'], 'verify_once')
        self.assertFalse(load(self.root / 'mobile-state.json').get('blocked'))
        r2 = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual((r2['status'], r2['reason']), ('handoff', 'other_author'))
        fake.cleanup()

    def test_tool_timeout_hard_stops_without_retry(self):
        class ToolError(Exception):
            pass
        fake = FakeBu(raise_on_download=ToolError('BU_DOWNLOAD_TIMEOUT'))
        self._configure(fake)
        r = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r['status'], 'handoff')
        self.assertTrue(r['reason'].startswith('tool_timeout:'))
        self.assertEqual(len(fake.download_calls), 1)  # no blind retry of the same route
        self.assertEqual(load(self.root / 'mobile-state.json')['next_page'], 1)
        fake.cleanup()

    def test_empty_page_advances_without_fabricating_records(self):
        fake = FakeBu({1: raw_page([]), 2: raw_page([mblog(2)])})
        self._configure(fake)
        r = self._collect(fake, max_pages=2, deadline_seconds=60)
        self.assertEqual(r['status'], 'ready')
        self.assertEqual(r['processed_pages'], 2)
        self.assertEqual(r['candidate_count'], 1)  # empty page added nothing
        self.assertEqual(r['next_page'], 3)
        fake.cleanup()

    def test_duplicate_and_pinned_posts_are_deduped(self):
        pinned = mblog(1, date='Thu Jul 10 12:00:00 +0800 2025', top=True)
        fake = FakeBu({1: raw_page([pinned, mblog(2)]),
                       2: raw_page([pinned, mblog(3)])})
        self._configure(fake)
        r1 = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r1['candidate_count'], 2)
        r2 = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r2['added'], 1)  # only mblog3 new; pinned re-seen and deduped
        self.assertEqual(r2['candidate_count'], 3)
        ids = [c['id'] for c in load(self.root / 'candidates.json')]
        self.assertEqual(len(ids), len(set(ids)))
        fake.cleanup()

    def test_truncated_cache_is_refetched_not_trusted(self):
        bad_cache = self.root / 'mobile-pages' / '000001.json'
        bad_cache.parent.mkdir(parents=True, exist_ok=True)
        bad_cache.write_text('{"ok":1,"data":{"cards":[', encoding='utf-8')
        fake = FakeBu({1: raw_page([mblog(1)])})
        self._configure(fake)
        r = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r['status'], 'ready')
        self.assertEqual(r['cache_hits'], 0)  # bad cache could not be a hit
        self.assertEqual(json.loads(bad_cache.read_text())['ok'], 1)
        fake.cleanup()

    def test_valid_cache_is_a_network_free_hit(self):
        fake = FakeBu({1: raw_page([mblog(1)])})
        self._configure(fake)
        self._collect(fake, max_pages=1, deadline_seconds=60)
        calls = len(fake.download_calls)
        # reset cursor to page 1 in a fresh "process"
        state = load(self.root / 'mobile-state.json')
        state['next_page'] = 1
        save(self.root / 'mobile-state.json', state)
        r = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual(r['cache_hits'], 1)
        self.assertEqual(len(fake.download_calls), calls)
        fake.cleanup()

    def test_transport_switch_persists_and_validates(self):
        fake = FakeBu({1: raw_page([mblog(1)])})
        self._configure(fake)
        self.assertEqual(set_mobile_transport(self.root, TRANSPORT_SYNC_XHR)['transport'],
                         TRANSPORT_SYNC_XHR)
        self.assertEqual(load(self.root / 'mobile-collection.json')['transport'],
                         TRANSPORT_SYNC_XHR)
        with self.assertRaises(ValueError):
            set_mobile_transport(self.root, 'websocket')
        fake.cleanup()

    def test_legacy_sync_xhr_channel_still_works(self):
        fake = FakeBu({1: raw_page([mblog(1)])})
        configure_mobile(fake, self.root, transport=TRANSPORT_SYNC_XHR)
        r = self._collect(fake, max_pages=1, deadline_seconds=60)
        self.assertEqual((r['status'], r['transport']), ('ready', TRANSPORT_SYNC_XHR))
        self.assertEqual(r['candidate_count'], 1)
        # legacy envelope cache is still written and re-ingestable
        cache = load(self.root / 'mobile-pages' / '000001.json')
        self.assertIn('cards', cache)
        fake.cleanup()


if __name__ == '__main__':
    unittest.main()
