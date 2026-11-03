"""Offline behavioral regressions for the narrow 4.2.1 changes; no real requests."""
import copy
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

from archive_common import load, save
from archive_pipeline import initialize, ingest, materialize, normalize
from audit_images import audit
from build_journal import prepare
from collect_weibo import configure_mobile, probe_mobile_boundary
from manage_media import download, plan
from test_build_journal import fixture
from test_pipeline import png


class Response(io.BytesIO):
    def __init__(self, url, body):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


def image(url):
    return {'image_id': url, 'origin': 'platform', 'source_url': url,
            'large_path': None, 'thumb_path': None, 'download_status': 'unavailable'}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def queue(self, urls):
        save(self.root / 'records.json', [{'id': str(n), 'images': [image(url)]}
             for n, url in enumerate(urls)])
        plan(self.root)

    def test_parallel_cap_unique_urls_and_only_main_thread_commits(self):
        urls = ['https://wx1.sinaimg.cn/%s.png' % n for n in range(7)]
        self.queue(urls + [urls[0]])
        lock = threading.Lock()
        barrier = threading.Barrier(3)

        class Opener:
            calls = active = peak = 0

            def open(self, req, **kwargs):
                with lock:
                    self.calls += 1
                    wave = self.calls <= 3
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                if wave:
                    barrier.wait(timeout=5)
                time.sleep(0.01)
                with lock:
                    self.active -= 1
                return Response(req.full_url, png(20, 16))

        main = threading.get_ident()
        def guarded_save(*args, **kwargs):
            self.assertEqual(threading.get_ident(), main)
            return save(*args, **kwargs)
        opener = Opener()
        with patch('manage_media.save', side_effect=guarded_save):
            result = download(self.root, workers=3, opener=opener)
        self.assertTrue(result['ok'], result)
        self.assertEqual((opener.calls, opener.peak, result['completed_jobs']), (7, 3, 8))
        self.assertEqual(len(list((self.root / 'images').glob('*'))), 1)
        for row in load(self.root / 'records.json'):
            im = row['images'][0]
            self.assertEqual(im['thumb_path'], im['large_path'])
            self.assertEqual(im['large_path'], im['original_path'])
        self.assertTrue(download(self.root, workers=3, opener=opener)['ok'])
        self.assertEqual(opener.calls, 7)

    def test_auth_failure_stops_new_work_and_resume_only_downloads_missing(self):
        urls = ['https://wx1.sinaimg.cn/%s.png' % n for n in range(15)]
        self.queue(urls)

        class Denied:
            calls = 0
            def open(self, req, **kwargs):
                self.calls += 1
                raise urllib.error.HTTPError(req.full_url, 429, 'limited', {}, None)
        opener = Denied()
        result = download(self.root, workers=3, opener=opener)
        self.assertFalse(result['ok'])
        self.assertLessEqual(opener.calls, 3)
        self.assertIn('429', result['stopped_reason'])
        self.assertEqual(len(load(self.root / 'records.json')), 15)

        class Good:
            calls = 0
            def open(self, req, **kwargs):
                self.calls += 1
                return Response(req.full_url, png())
        good = Good()
        self.assertTrue(download(self.root, workers=3, opener=good)['ok'])
        self.assertEqual(good.calls, 15)
        self.assertTrue(download(self.root, workers=1, opener=good)['ok'])
        self.assertEqual(good.calls, 15)

    def test_parallel_budget_is_global_and_success_survives_resume(self):
        urls = ['https://wx1.sinaimg.cn/%s.png' % n for n in range(6)]
        self.queue(urls)
        class Good:
            def open(self, req, **kwargs):
                n = int(req.full_url.rsplit('/', 1)[1].split('.')[0])
                return Response(req.full_url, png(10+n, 10))
        ceiling = max(len(png(10+n, 10)) for n in range(6)) + 1
        result = download(self.root, workers=3, max_mb=ceiling / 1024**2, opener=Good())
        self.assertFalse(result['ok'])
        self.assertLessEqual(sum(p.stat().st_size for p in (self.root / 'images').glob('*')), ceiling)
        self.assertEqual(sum(im['download_status'] == 'saved'
            for row in load(self.root / 'records.json') for im in row['images']), 1)
        self.assertTrue(download(self.root, workers=3, opener=Good())['ok'])

    def test_serial_and_bounded_retry_and_failure_inventory(self):
        self.queue(['https://wx1.sinaimg.cn/a.png', 'https://wx1.sinaimg.cn/b.png'])
        class Bad:
            calls = 0
            def open(self, req, **kwargs):
                self.calls += 1
                raise urllib.error.URLError('offline synthetic failure')
        opener = Bad()
        result = download(self.root, workers=1, attempts=2, opener=opener)
        self.assertFalse(result['ok'])
        self.assertEqual((opener.calls, result['failed_jobs']), (4, 2))
        self.assertEqual(len(load(self.root / 'records.json')), 2)
        for workers in (0, 7, True):
            with self.assertRaises(ValueError):
                download(self.root, workers=workers, opener=opener)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixture(self.root)
        (self.root / 'images').mkdir()
        (self.root / 'images/photo.png').write_bytes(png(40, 30))
        rows = load(self.root / 'records.json')
        rows[0].update(expected_image_count=1, image_inventory_status='complete',
            image_count_basis='Explicit synthetic inventory has one photo',
            images=[{**image('https://wx1.sinaimg.cn/photo.png'), 'download_status': 'saved',
                     'thumb_path': 'images/photo.png', 'large_path': 'images/photo.png'}])
        save(self.root / 'records.json', rows)

    def tearDown(self):
        self.temp.cleanup()

    def test_single_file_shared_by_all_sizes_is_valid(self):
        self.assertTrue(audit(self.root)['ok'])
        self.assertTrue(prepare(self.root, 'paper')['story']['overview']['images'])

    def test_count_unknown_missing_file_bad_image_duplicate_id_all_fail(self):
        original = load(self.root / 'records.json')
        for mutate in (lambda r: r[0].update(expected_image_count=None),
                       lambda r: r[0].update(expected_image_count=2),
                       lambda r: r[0].update(image_inventory_status='unknown'),
                       lambda r: r[0].update(image_count_basis=''),
                       lambda r: r[0]['images'][0].update(large_path='images/missing.png'),
                       lambda r: r[0]['images'][0].update(download_status='failed'),
                       lambda r: r[0].update(expected_image_count=2, images=r[0]['images'] * 2)):
            rows = copy.deepcopy(original)
            mutate(rows)
            save(self.root / 'records.json', rows)
            self.assertFalse(audit(self.root)['ok'])
            with self.assertRaises(ValueError):
                prepare(self.root, 'paper')
        save(self.root / 'records.json', original)
        (self.root / 'images/photo.png').write_bytes(b'<html>not a photo</html>')
        self.assertFalse(audit(self.root)['ok'])

    def test_review_cannot_hide_all_existing_photos_in_calendar(self):
        rows = load(self.root / 'records.json')
        text_only = {**rows[0], 'id': 'text-only', 'images': [], 'expected_image_count': 0}
        save(self.root / 'records.json', rows + [text_only])
        story = load(self.root / 'story.json')
        story['overview']['source_ids'] = ['text-only']
        story['themes'][0]['source_ids'] = ['text-only']
        save(self.root / 'story.json', story)
        with self.assertRaisesRegex(ValueError, '全部无图'):
            prepare(self.root, 'paper')

    def test_normalization_keeps_unknown_count_and_merges_verified_inventory(self):
        raw = {'id': '1', 'author_uid': 'synthetic', 'is_original': True,
               'text': 'synthetic', 'created_at': '2025-01-01T12:00:00+08:00', 'images': []}
        record, _ = normalize(raw, 'synthetic')
        self.assertIsNone(record['expected_image_count'])
        self.assertEqual(record['image_inventory_status'], 'unknown')
        verified, _ = normalize({**raw, 'pic_num': 0}, 'synthetic')
        self.assertEqual(verified['image_inventory_status'], 'complete')
        project = self.root / 'new'
        initialize(project, 'synthetic', 'https://weibo.com/u/synthetic', '2025-01-01', '2025-12-31', mode='full')
        ingest(project, [{**raw, 'pic_num': 0}])
        materialize(project)
        ingest(project, [raw])
        self.assertEqual(materialize(project)['pending_photo_details'], 0)


class Clock:
    def __init__(self): self.now = 0
    def time(self): return self.now
    def sleep(self, seconds): self.now += seconds


class MobileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize(self.root, '123', 'https://weibo.com/u/123', '2025-01-01', '2025-12-31')
        self.browser = type('Browser', (), {'page_info': lambda _: {'url': 'https://m.weibo.cn/u/123'}})()
        configure_mobile(self.browser, self.root)
        self.clock = Clock()

    def tearDown(self): self.temp.cleanup()

    def test_reconfigure_does_not_reset_existing_cursor_or_block(self):
        state = load(self.root / 'mobile-state.json')
        state.update(next_page=18, blocked='verification_required')
        save(self.root / 'mobile-state.json', state)
        result = configure_mobile(self.browser, self.root)
        self.assertEqual((result['status'], result['next_page']), ('handoff', 18))
        self.assertEqual(load(self.root / 'mobile-state.json'), state)

    def test_probe_timeout_resumes_bisection_without_refetching_endpoints(self):
        calls = []
        def request(browser, config, page):
            calls.append(page)
            return ([{'id': str(page)}] if page <= 9 else [], [], 'synthetic')
        with patch('collect_weibo._mobile_request_page', side_effect=request):
            result = probe_mobile_boundary(self.browser, self.root, high_page=16,
                deadline_seconds=7, clock=self.clock.time, sleep=self.clock.sleep)
            self.assertEqual(result['status'], 'cooldown')
            self.assertIsNotNone(load(self.root / 'mobile-state.json').get('boundary_probe'))
            prior = len(calls)
            result = probe_mobile_boundary(self.browser, self.root, high_page=16,
                deadline_seconds=120, clock=self.clock.time, sleep=self.clock.sleep)
        self.assertEqual(result['last_page'], 9)
        self.assertNotIn(1, calls[prior:])
        self.assertNotIn(16, calls[prior:])

    def test_transient_empty_is_rechecked_and_does_not_cut_history(self):
        calls = []
        def request(browser, config, page):
            calls.append(page)
            transient = page == 8 and calls.count(8) == 1
            return ([{'id': str(page)}] if page <= 9 and not transient else [], [], 'synthetic')
        with patch('collect_weibo._mobile_request_page', side_effect=request):
            result = probe_mobile_boundary(self.browser, self.root, high_page=16,
                deadline_seconds=120, clock=self.clock.time, sleep=self.clock.sleep)
        self.assertEqual(result['last_page'], 9)
        self.assertEqual(calls.count(8), 2)


class PackedInventoryTests(unittest.TestCase):
    def test_packed_inventory_cannot_bypass_source_gate(self):
        from test_runtime_contract import RuntimeContractTests
        case = RuntimeContractTests('test_baseline_source_and_real_packed_entry_pass')
        try:
            case.setUp()
            for mutate in (lambda d: d['records'][0].update(expected_image_count=None),
                           lambda d: d['records'][0]['images'][0].update(image_id=''),
                           lambda d: d['records'][0].update(image_inventory_status='unknown')):
                self.assertFalse(case.mutated(mutate)['ok'])
        finally:
            case.tearDown()


if __name__ == '__main__':
    unittest.main()
