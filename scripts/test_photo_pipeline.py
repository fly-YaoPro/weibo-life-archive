"""Synthetic integration: actual photo intake -> normal build -> packed HTML contract."""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from archive_common import load, save
from check_project import check
from journal_run import run
from photo_import import import_photos
from runtime_contract import validate_runtime


def photo_fixture(parent, gps_fixture=False):
    """No account or network: six explicitly synthetic numbered raster test tiles."""
    from PIL import Image, ImageDraw
    parent = Path(parent)
    original = parent / 'input'
    original.mkdir(parents=True)
    colors = ['#699cae', '#d9b586', '#8d9e7b', '#bb8e99', '#b7a3c9', '#daa56b']
    for n, color in enumerate(colors):
        im = Image.new('RGB', (640, 480), color)
        draw = ImageDraw.Draw(im)
        draw.rectangle((35, 35, 605, 445), outline='white', width=5)
        draw.ellipse((150 + n * 20, 120, 350 + n * 20, 320), fill='#efe6d8')
        draw.text((65, 65), 'SYNTHETIC TEST ' + str(n + 1), fill='#222222')
        kwargs = {}
        if gps_fixture and n == 0:
            from PIL.TiffImagePlugin import IFDRational
            exif = Image.Exif()
            exif[36867] = '2021:04:12 10:00:00'
            exif[36881] = '+08:00'
            exif[272] = 'SYNTHETIC-PRIVATE-CAMERA-21b5'
            exif[34853] = {1:'N',2:(IFDRational(31),IFDRational(13),IFDRational(30)),
                           3:'E',4:(IFDRational(121),IFDRational(28),IFDRational(0))}
            kwargs['exif'] = exif
        im.save(original / ('tile-' + str(n) + '.jpg'),**kwargs)
    dates = ['2021-04-12', '2023-07-18', '2024-05', '2020', None, '2023-07-18']
    manifest = {'schema_version': 1, 'photos': [
        {'file': 'tile-' + str(n) + '.jpg', 'date': when, 'note': '合成测试色块' + str(n + 1)}
        for n, when in enumerate(dates)]}
    source = parent / 'source'
    import_photos(original, source, manifest=manifest, collection_name='合成测试相册', synthetic_fixture=True)
    decoration = source / 'decorations' / 'synthetic-closing.png'
    decoration.parent.mkdir()
    im = Image.new('RGB', (480, 240), '#eee6db')
    ImageDraw.Draw(im).text((40, 100), 'SYNTHETIC DECORATION - NOT A MEMORY', fill='#5c5470')
    im.save(decoration)
    records = load(source / 'records.json')
    ids = [r['id'] for r in records]
    image_path = lambda row: row['images'][0]['large_path']
    evidence = [{'kind': 'image', 'source_id': r['id'], 'image_path': image_path(r),
                 'observation': '合成色块图片，带数字编号和浅色圆形。'} for r in records]
    themes = [{'id': 'colors-' + str(n), 'title': '测试色块 ' + str(n + 1),
               'text': '合成测试素材：用来检查照片显示与来源跳转，不代表真实生活经历。',
               'source_ids': [r['id']], 'layout': 'ABC'[n % 3], 'image_paths': [image_path(r)]}
              for n, r in enumerate(records)]
    story = {'evidence': evidence,
             'overview': {'headline': '合成测试 · 照片回忆册', 'text': '这里只验证真实文件导入、日期精度、照片展示和分享。故事质量等待真实素材一起验证。',
                          'opening': '合成测试页面，不是真实相册。', 'source_ids': ids,
                          'portrait': {'title': '测试说明', 'text': '画面是编号色块，不是用户经历。', 'source_ids': ids},
                          'image_paths': [image_path(r) for r in records[:3]]},
             'themes': themes, 'plans': [],
             'letter': {'title': '给共同验收留一页', 'paragraphs': ['等真实照片准备好，再一起核对叙事是否贴合。'],
                        'closing': '合成测试到这里。', 'source_ids': ids,
                        'image_path':'decorations/synthetic-closing.png', 'image_alt':'合成测试装饰，不是回忆照片'},
             'wishes': [{'id': 'w-review', 'title': '核对照片日期', 'text': '确认未知日期没有被补造成某一天。', 'source_ids': ids}],
             'share': {'headline': '合成测试 · 六张照片', 'text': '功能测试，不是真实用户回忆',
                       'letter_text': '等真实素材准备好后，再共同验收内容。',
                       'entries': [{'source_id': r['id'], 'title': '测试照片', 'text': r['text']} for r in records]}}
    save(source / 'story.json', story)
    return source


class PhotoPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name)
        self.source = photo_fixture(self.parent)

    def tearDown(self):
        self.temp.cleanup()

    def test_local_photos_build_and_pack_without_uid_or_fake_dates(self):
        data = check(self.source, 'photos', 'data')
        self.assertTrue(data['ok'], data)
        preflight = check(self.source, 'photos', 'story')
        self.assertTrue(preflight['ok'], preflight)
        result = run(self.source, self.parent / 'runs')
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['live_deployment_verified'])
        self.assertFalse(result['delivery_complete'])
        html = Path(result['artifacts'][0]['html'])
        final = check(html, 'photos', 'final')
        self.assertTrue(final['ok'], final)
        text = html.read_text('utf-8')
        packed = json.loads(re.search(r'window.JOURNAL_DATA = (.*?);\n', text).group(1))
        self.assertEqual(packed['meta']['platform'], 'photos')
        self.assertEqual(len(packed['records']), 6)
        self.assertEqual({r['date'] for r in packed['records']}, {'2021-04-12', '2023-07-18', '2024-05', '2020', None})
        self.assertTrue(all(r.get('author_uid') is None and not r.get('url') for r in packed['records']))
        self.assertNotIn(str((self.parent / 'input').resolve()), text)
        assets = json.loads(re.search(r'window.JOURNAL_ASSETS=(.*?);\n', text).group(1))
        self.assertTrue(all(r['images'][0]['path'] in assets for r in packed['records']))

    def test_unknown_and_partial_dates_are_not_padded_by_validation(self):
        meta, records = load(self.source / 'project_meta.json'), load(self.source / 'records.json')
        validate_runtime(meta, records, root=self.source)
        unknown = next(r for r in records if r['date'] is None)
        bad = copy.deepcopy(unknown)
        bad['date'] = '2023-01-01'
        with self.assertRaises(ValueError):
            validate_runtime(meta, [bad], root=self.source)

    def test_missing_photo_or_wrong_platform_still_blocks(self):
        meta, records = load(self.source / 'project_meta.json'), load(self.source / 'records.json')
        with self.assertRaises(ValueError):
            validate_runtime({**meta, 'platform': 'baidu_netdisk'}, records, root=self.source)
        bad = copy.deepcopy(records[0])
        bad['images'][0]['large_path'] = 'images/missing.jpg'
        with self.assertRaises(ValueError):
            validate_runtime(meta, [bad], root=self.source)

    def test_unknown_date_cannot_be_assigned_to_annual_review(self):
        meta, records, story = (load(self.source / p) for p in ('project_meta.json','records.json','story.json'))
        unknown = next(r for r in records if r['date'] is None)
        story['annual_reviews'] = [{'year':2023,'title':'错误归年','text':'不应通过','source_ids':[unknown['id']]}]
        with self.assertRaisesRegex(ValueError,'来源日期未知'):
            validate_runtime(meta, records, story, root=self.source)

    def test_tampered_photo_bytes_block_data_and_build(self):
        records = load(self.source / 'records.json')
        (self.source / records[0]['images'][0]['large_path']).write_bytes(b'not a photograph')
        self.assertFalse(check(self.source,'photos','data')['ok'])
        self.assertFalse(run(self.source,self.parent/'runs')['ok'])

    def test_exif_reintroduction_is_rejected_even_with_matching_hash(self):
        from PIL import Image
        records, meta = load(self.source/'records.json'), load(self.source/'project_meta.json')
        image = records[0]['images'][0]
        path = self.source/image['large_path']
        with Image.open(path) as opened:
            pixels = opened.copy()
        exif = Image.Exif()
        exif[306] = '2023:01:01 00:00:00'
        pixels.save(path,exif=exif)
        image['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'仍带EXIF'):
            validate_runtime(meta,records,root=self.source)

    def test_packed_image_tampering_is_rejected(self):
        import base64
        result = run(self.source,self.parent/'runs')
        self.assertTrue(result['ok'],result)
        path = Path(result['artifacts'][0]['html'])
        text = path.read_text('utf-8')
        match = re.search(r'window.JOURNAL_ASSETS=(.*?);\n',text)
        assets = json.loads(match.group(1))
        photo = load(self.source/'records.json')[0]['images'][0]['large_path']
        assets[photo] = 'data:image/jpeg;base64,'+base64.b64encode(b'not a photograph').decode()
        modified = self.parent/'tampered.html'
        modified.write_text(text[:match.start(1)]+json.dumps(assets)+text[match.end(1):],encoding='utf-8')
        self.assertFalse(check(modified,'photos','final')['ok'])

    def test_private_metadata_and_event_drafts_stay_out_of_delivery(self):
        marker = 'PRIVATE-PHOTO-ANALYSIS-ONLY-2c8e7'
        save(self.source/'.private'/'photo-metadata.json',{'never_publish':True,'marker':marker,'gps':{'latitude':12.34567,'longitude':23.45678}})
        save(self.source/'.private'/'photo-analysis.json',{'marker':marker,'candidate_event':'仅供确认的事件草稿'})
        result = run(self.source,self.parent/'runs')
        self.assertTrue(result['ok'],result)
        artifact = result['artifacts'][0]
        html = Path(artifact['html']).read_text('utf-8')
        self.assertNotIn(marker,html)
        self.assertNotIn('12.34567',html)
        built = Path(artifact['built_dir'])
        self.assertFalse((built/'.private').exists())
        self.assertFalse((built/'photo-metadata.json').exists())
        self.assertFalse((built/'photo-analysis.json').exists())

    def test_real_gps_exif_import_stays_private_through_pack(self):
        source = photo_fixture(self.parent/'gps-case',gps_fixture=True)
        private = load(source/'.private'/'photo-metadata.json')
        located = [item for item in private['photos'] if item['gps']['status']=='valid']
        self.assertEqual(len(located),1)
        self.assertAlmostEqual(located[0]['gps']['latitude'],31.225)
        self.assertEqual(located[0]['capture_time']['created_at'],'2021-04-12T10:00:00+08:00')
        result = run(source,self.parent/'gps-runs')
        self.assertTrue(result['ok'],result)
        artifact = result['artifacts'][0]
        self.assertTrue(check(Path(artifact['html']),'photos','final')['ok'])
        html = Path(artifact['html']).read_text('utf-8')
        for value in ('31.225','121.466666','SYNTHETIC-PRIVATE-CAMERA-21b5','GPSInfo'):
            self.assertNotIn(value,html)
        self.assertFalse((Path(artifact['built_dir'])/'.private').exists())


if __name__ == '__main__':
    unittest.main()
