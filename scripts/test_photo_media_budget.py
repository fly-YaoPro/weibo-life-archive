"""Actual synthetic photo import/build/compression, with delivery-byte integrity checks."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from archive_common import load, save
from build_journal import build
from media_budget import apply_budget
from pack_html import pack, verify_packed
from photo_import import import_photos
from runtime_contract import validate_runtime


def runtime(path):
    return json.loads(path.read_text(encoding='utf-8').split(' = ', 1)[1].rstrip(';\n'))


class PhotoMediaBudgetTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image, ImageDraw
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.originals = self.parent / 'input'
        self.originals.mkdir()
        self.source = self.parent / 'source'
        image = Image.new('RGB', (1800, 1200), '#a6b3ca')
        draw = ImageDraw.Draw(image)
        for n in range(0, 1800, 9):
            color = (n % 255, (n * 13) % 255, (n * 29) % 255)
            draw.line((n, 0, 1800 - n, 1199), fill=color, width=3)
        exif = Image.Exif()
        exif[36867] = '2023:06:12 10:20:30'
        exif[270] = 'synthetic private metadata - must not be delivered'
        image.save(self.originals / 'synthetic-large.jpg', quality=97, exif=exif)
        self.original_bytes = (self.originals / 'synthetic-large.jpg').read_bytes()
        receipt = import_photos(self.originals, self.source, collection_name='合成压缩回归相册', synthetic_fixture=True)
        self.assertTrue(receipt['ok'], receipt)
        self.raw_record = load(self.source / 'records.json')[0]
        ids = [self.raw_record['id']]
        path = self.raw_record['images'][0]['large_path']
        story = {'overview': {'headline': '合成照片压缩测试', 'text': '这里只检查图片路径与字节校验。', 'source_ids': ids, 'image_paths': [path]},
                 'themes': [{'id': 'photo-test', 'title': '合成线条', 'text': '图中是明确的合成线条，不是真实回忆。',
                             'source_ids': ids, 'layout': 'A', 'image_paths': [path]}],
                 'plans': [], 'wishes': [{'id': 'w1', 'title': '共同核对', 'text': '等待真实素材做内容验收。', 'source_ids': ids}],
                 'share': {'letter_text': '这只是离线回归测试。', 'entries': [{'source_id': ids[0], 'title': '合成图片', 'text': '合成测试。'}]}}
        save(self.source / 'story.json', story)
        self.source_before = {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}

    def assert_delivery_image(self, built, record):
        from PIL import Image
        self.assertEqual(record['source_sha256'], self.raw_record['source_sha256'])
        self.assertEqual(record['id'], self.raw_record['id'])
        image = record['images'][0]
        expected_paths = {image[k] for k in ('thumb_path', 'large_path', 'path', 'large', 'original_path', 'original') if image.get(k)}
        self.assertEqual(len(expected_paths), 1)
        for path in expected_paths:
            raw = (built / path).read_bytes()
            self.assertEqual(image['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertTrue(image['exif_stripped'])
            with Image.open(built / path) as im:
                im.load()
                self.assertEqual((image['width'], image['height']), im.size)
                self.assertLess(im.width, self.raw_record['images'][0]['width'])
                self.assertEqual(dict(im.getexif()), {})
        self.assertNotEqual(image['sha256'], self.raw_record['images'][0]['sha256'])

    def test_compression_updates_every_photo_copy_and_keeps_source_identity(self):
        built = self.parent / 'built'
        build(self.source, built, 'paper')
        result = apply_budget(built, .025)
        self.assertGreater(result['files_changed'], 0, result)
        raw_records = load(built / 'records.json')
        normalized = runtime(built / 'journal-data.js')
        canonical = runtime(built / 'data.js')
        for record in (raw_records[0], normalized['records'][0], canonical['records'][0]):
            self.assert_delivery_image(built, record)
        validate_runtime(normalized['meta'], raw_records, load(built / 'story.json'), root=built)
        validate_runtime(normalized['meta'], normalized['records'], normalized['story'], root=built)
        validate_runtime(canonical['meta'], canonical['records'], canonical['story'], root=built)
        for image in normalized['story']['overview']['images']:
            self.assertEqual(image['sha256'], normalized['records'][0]['images'][0]['sha256'])
            self.assertEqual(image['width'], normalized['records'][0]['images'][0]['width'])
        packed = self.parent / 'packed.html'
        pack(built, packed)
        self.assertTrue(verify_packed(packed)['ok'])
        self.assertEqual((self.originals / 'synthetic-large.jpg').read_bytes(), self.original_bytes)
        self.assertEqual({p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}, self.source_before)

    def test_no_compression_leaves_delivery_and_source_hashes_unchanged(self):
        built = self.parent / 'uncompressed'
        build(self.source, built, 'frosted')
        before = load(built / 'records.json')
        result = apply_budget(built, 24)
        self.assertEqual(result['files_changed'], 0)
        self.assertEqual(load(built / 'records.json'), before)
        self.assertEqual(before[0]['images'][0]['sha256'], self.raw_record['images'][0]['sha256'])


if __name__ == '__main__':
    unittest.main()
