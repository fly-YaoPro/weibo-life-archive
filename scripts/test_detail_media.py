"""Offline tests for detail-based >9-image supplement and external cover registration."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from archive_common import load
from archive_pipeline import initialize, normalize
from detail_media import (
    fetch_detail_mblog, supplement_record, supplement_inventory,
    register_external_cover, _ids_needing_supplement,
)

UID = '1705586121'


def detail_envelope(record_id, n, uid=UID, date='Sun May 26 01:51:32 +0800 2024', ok=1):
    pics = []
    for k in range(n):
        pid = 'pid%s_%d' % (record_id, k)
        pics.append({'pid': pid,
                     'url': 'https://wx1.sinaimg.cn/orj360/%s.jpg' % pid,
                     'large': {'url': 'https://wx1.sinaimg.cn/mw2000/%s.jpg' % pid,
                               'geo': {'width': '1080', 'height': '1620'}}})
    data = {'id': str(record_id), 'mid': str(record_id), 'created_at': date,
            'user': {'id': int(uid)}, 'text': 'hello', 'pics': pics,
            'pic_num': n, 'pic_ids': [p['pid'] for p in pics]}
    return {'ok': ok, 'data': data}


class FakeBu:
    def __init__(self, envelopes):
        self.envelopes = envelopes
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []

    def cleanup(self):
        self.tmp.cleanup()

    def download(self, url, filename=None, timeout=30):
        self.calls.append(url)
        rid = url.split('id=')[1]
        env = self.envelopes[rid]
        data = json.dumps(env).encode('utf-8')
        path = Path(self.tmp.name) / (filename or 'd.json')
        path.write_bytes(data)
        return {'path': str(path), 'bytes': len(data), 'source': 'direct'}


def seed_truncated_record(root, record_id, n_kept=9):
    """Create a retained record that has been wrongly truncated to 9 images."""
    env = detail_envelope(record_id, 15)
    full, _ = normalize(env['data'], UID)
    full['images'] = full['images'][:n_kept]
    full['expected_image_count'] = n_kept
    full['image_inventory_status'] = 'complete'
    records = load(root / 'records.json', [])
    records.append(full)
    from archive_common import save
    save(root / 'records.json', records)
    # candidate keeps the true source count
    cands = load(root / 'candidates.json', [])
    cands.append({'id': str(record_id), 'expected_image_count': 15})
    save(root / 'candidates.json', cands)


class DetailMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize(self.root, UID, 'https://weibo.com/u/' + UID,
                   '2016-11-02', '2026-11-02', mode='selected')

    def tearDown(self):
        self.temp.cleanup()

    def _fake(self, rid, **env_over):
        env = detail_envelope(rid, 15)
        if 'uid' in env_over:
            env['data']['user']['id'] = int(env_over.pop('uid'))
        env.update(env_over)
        return FakeBu({str(rid): env})

    def test_fetch_rejects_business_error_other_author_bad_id_missing_parts(self):
        rid = 5001
        with self.assertRaises(ValueError):
            fetch_detail_mblog(self._fake(rid, ok=0), UID, rid)
        with self.assertRaises(ValueError):
            fetch_detail_mblog(self._fake(rid, uid='999'), UID, rid)
        bad = self._fake(rid)
        bad.envelopes[str(rid)]['data']['id'] = '9999'
        with self.assertRaises(ValueError):
            fetch_detail_mblog(bad, UID, rid)
        nodate = self._fake(rid)
        nodate.envelopes[str(rid)]['data']['created_at'] = None
        with self.assertRaises(ValueError):
            fetch_detail_mblog(nodate, UID, rid)
        nopics = self._fake(rid)
        nopics.envelopes[str(rid)]['data']['pics'] = None
        with self.assertRaises(ValueError):
            fetch_detail_mblog(nopics, UID, rid)

    def test_supplement_restores_denominator_and_reuses_saved(self):
        rid = 5001
        seed_truncated_record(self.root, rid)
        # mark the 9 existing images as already saved with a local file
        records = load(self.root / 'records.json')
        rec = next(r for r in records if r['id'] == str(rid))
        for n, im in enumerate(rec['images']):
            im['large_path'] = 'images/old%d.jpg' % n
            im['download_status'] = 'saved'
        from archive_common import save
        save(self.root / 'records.json', records)
        r = supplement_record(self._fake(rid), self.root, rid)
        self.assertEqual((r['expected'], r['enumerated']), (15, 15))
        self.assertEqual((r['reused_saved'], r['new_positions']), (9, 6))
        final = load(self.root / 'records.json')[0]
        self.assertEqual(final['expected_image_count'], 15)
        self.assertEqual(final['image_inventory_status'], 'complete')
        self.assertTrue(final['image_count_basis'].endswith('detail/statuses.show'))

    def test_auto_detect_and_batch_supplement(self):
        seed_truncated_record(self.root, 6001)
        seed_truncated_record(self.root, 6002)
        self.assertEqual(_ids_needing_supplement(self.root), ['6001', '6002'])
        fake = FakeBu({'6001': detail_envelope(6001, 15),
                       '6002': detail_envelope(6002, 15)})
        r = supplement_inventory(fake, self.root)
        self.assertEqual(r['processed'], 2)
        self.assertEqual(r['total_expected'], 30)
        # no local files were pre-saved in this batch, so every position counts as new
        self.assertEqual(r['total_new_positions'], 30)

    def test_register_external_cover_validates_and_saves(self):
        rid = 7001
        seed_truncated_record(self.root, rid)
        records = load(self.root / 'records.json')
        rec = next(r for r in records if r['id'] == str(rid))
        rec['is_video'] = True
        rec['video'] = {'covers': [{'origin': 'platform',
                                    'source_url': 'https://vthumb.ykimg.com/x',
                                    'download_status': 'failed'}]}
        from archive_common import save
        save(self.root / 'records.json', records)
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (220, 125), (10, 20, 30)).save(buf, 'JPEG')
        cover = Path(self.temp.name) / 'ext.jpg'
        cover.write_bytes(buf.getvalue())
        r = register_external_cover(self.root, rid, cover)
        self.assertEqual((r['width'], r['height']), (220, 125))
        saved_cover = load(self.root / 'records.json')[0]['video']['covers'][0]
        self.assertEqual(saved_cover['download_status'], 'saved')
        self.assertTrue((self.root / saved_cover['large_path']).is_file())

    def test_register_external_cover_rejects_non_image(self):
        rid = 7002
        seed_truncated_record(self.root, rid)
        records = load(self.root / 'records.json')
        rec = next(r for r in records if r['id'] == str(rid))
        rec['is_video'] = True
        rec['video'] = {'covers': [{'source_url': 'https://x/y', 'download_status': 'failed'}]}
        from archive_common import save
        save(self.root / 'records.json', records)
        bad = Path(self.temp.name) / 'bad.jpg'
        bad.write_text('<html>error</html>', encoding='utf-8')
        with self.assertRaises(ValueError):
            register_external_cover(self.root, rid, bad)


if __name__ == '__main__':
    unittest.main()
