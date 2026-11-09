"""Synthetic-only photo intake tests. Never contacts or logs into a cloud service."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

try:
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational
except ImportError:
    Image = None

from photo_contract import photo_date, photo_date_label, validate_photo_record
from photo_import import import_photos


@unittest.skipIf(Image is None, 'Pillow not installed; never install it silently')
class PhotoImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # macOS may expose /var/... while resolve() uses /private/var/....
        # Match the importer's canonical paths in filesystem mocks; do not make
        # a security assertion depend on the spelling returned by tempfile.
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'synthetic-photos'
        self.source.mkdir()
        self.output = self.root / 'project'

    def tearDown(self):
        self.temp.cleanup()

    def photo(self, name, color='red', exif=None):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new('RGB', (80, 60), color)
        if exif:
            image.save(path, exif=exif)
        else:
            image.save(path)
        return path

    def run_import(self, **kwargs):
        return import_photos(self.source, self.output, collection_id='synthetic-album', collection_name='合成测试相册', synthetic_fixture=True, **kwargs)

    def load(self, name):
        return json.loads((self.output / name).read_text(encoding='utf-8'))

    def test_partial_and_unknown_dates_never_pad_days_or_use_mtime(self):
        self.photo('no-date.jpg')
        self.photo('year.jpg', 'blue')
        self.photo('month.jpg', 'green')
        os.utime(self.source / 'no-date.jpg', (1700000000, 1700000000))
        manifest = {'schema_version': 1, 'photos': [{'file': 'year.jpg', 'date': '2020', 'note': '用户补充'}, {'file': 'month.jpg', 'date': '2021-08'}]}
        receipt = self.run_import(manifest=manifest)
        self.assertTrue(receipt['ok'])
        records = self.load('records.json')
        self.assertEqual({record['date_precision'] for record in records}, {'unknown', 'year', 'month'})
        self.assertEqual({record['date'] for record in records}, {None, '2020', '2021-08'})
        self.assertTrue(all(record['created_at'] is None for record in records))
        self.assertEqual({photo_date_label(record) for record in records}, {'日期待确认', '2020年', '2021年8月'})

    def test_exif_stripped_original_untouched_and_real_offset_only(self):
        exif = Image.Exif()
        exif[36867] = '2024:06:07 12:13:14'
        exif[36881] = '+08:00'
        exif[270] = 'synthetic private note'
        path = self.photo('private.jpg', exif=exif)
        original = path.read_bytes()
        self.run_import()
        record = self.load('records.json')[0]
        self.assertEqual(record['date'], '2024-06-07')
        self.assertEqual(record['created_at'], '2024-06-07T12:13:14+08:00')
        self.assertEqual(path.read_bytes(), original)
        with Image.open(self.output / record['images'][0]['large_path']) as image:
            self.assertEqual(dict(image.getexif()), {})
        self.assertEqual(record['images'][0]['sha256'], hashlib.sha256((self.output / record['images'][0]['large_path']).read_bytes()).hexdigest())

    def test_exif_without_offset_has_day_but_no_invented_timestamp(self):
        exif = Image.Exif()
        exif[36867] = '2024:06:07 12:13:14'
        self.photo('photo.jpg', exif=exif)
        self.run_import()
        record = self.load('records.json')[0]
        self.assertEqual(record['date'], '2024-06-07')
        self.assertIsNone(record['created_at'])

    def test_exact_duplicate_and_corrupt_image_are_accounted(self):
        path = self.photo('one.jpg')
        (self.source / 'copy.jpg').write_bytes(path.read_bytes())
        (self.source / 'broken.jpg').write_bytes(b'not an image')
        (self.source / 'notes.txt').write_text('synthetic unrelated file', encoding='utf-8')
        receipt = self.run_import()
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['total_files'], 4)
        self.assertEqual(receipt['supported_images'], 3)
        self.assertEqual(receipt['unique_imported'], 1)
        self.assertEqual(receipt['exact_duplicate_count'], 1)
        self.assertEqual(receipt['failed_count'], 1)
        self.assertEqual(receipt['unsupported_count'], 1)
        self.assertEqual(len(self.load('records.json')), 1)
        self.assertEqual(self.load('coverage.json')['status'], 'partial')

    def test_near_duplicates_group_but_never_drop(self):
        self.photo('red.jpg', 'red')
        self.photo('blue.jpg', 'blue')
        receipt = self.run_import()
        self.assertEqual(receipt['unique_imported'], 2)
        self.assertTrue(receipt['near_duplicate_candidates'])
        self.assertFalse(receipt['near_duplicate_candidates'][0]['automatic_deletion'])

    def test_manifest_traversal_and_absolute_paths_are_rejected(self):
        self.photo('one.jpg')
        for name in ('../private.jpg', '/private.jpg', 'C:/private.jpg', 'sub\\private.jpg'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_import(manifest={'schema_version': 1, 'photos': [{'file': name, 'date': '2024'}]})
        self.assertFalse(self.output.exists())

    def test_contract_rejects_misleading_time_and_origin(self):
        self.photo('one.jpg')
        self.run_import()
        record = self.load('records.json')[0]
        meta = self.load('project_meta.json')
        for mutate in (lambda r: r.update(created_at='2024-01-01T00:00:00+08:00'),
                       lambda r: r.update(id='invented'),
                       lambda r: r['images'][0].update(large_path='../private.png'),
                       lambda r: r['images'][0].update(origin='ai_generated'),
                       lambda r: r.update(date='2024-01-01', date_precision='year'),
                       lambda r: r.update(url='https://weibo.com/123/456')):
            changed = copy.deepcopy(record)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                validate_photo_record(changed, meta)

    def test_symlink_escape_is_reported_not_read(self):
        self.photo('one.jpg')
        external = self.root / 'external.jpg'
        Image.new('RGB', (20, 20), 'blue').save(external)
        try:
            (self.source / 'escape.jpg').symlink_to(external)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        receipt = self.run_import()
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['unique_imported'], 1)
        self.assertTrue(any(failure['reason'] == 'unsafe_file_link' for failure in receipt['failures']))

    def test_simulated_symlink_escape_is_reported_on_every_platform(self):
        self.photo('safe.jpg')
        blocked = self.photo('escape.jpg', 'blue').resolve()
        real_is_symlink = Path.is_symlink
        def is_symlink(path):
            return path == blocked or real_is_symlink(path)
        with patch.object(Path, 'is_symlink', is_symlink):
            receipt = self.run_import()
        self.assertEqual(receipt['unique_imported'], 1)
        self.assertEqual(receipt['failed_count'], 1)
        self.assertEqual(receipt['failures'][0]['reason'], 'unsafe_file_link')

    def test_second_run_preserves_manual_story_and_reuses_images(self):
        self.photo('one.jpg')
        self.run_import()
        story = '{"overview":{"text":"人工写的内容，不可重写"}}'
        (self.output / 'story.json').write_text(story, encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.run_import()
        receipt = self.run_import(resume=True)
        self.assertTrue(receipt['manual_story_preserved'])
        self.assertEqual(receipt['reused_files'], 1)
        self.assertEqual((self.output / 'story.json').read_text(encoding='utf-8'), story)
        self.assertTrue(Path(receipt['previous_snapshot']).is_dir())
        self.assertEqual((Path(receipt['previous_snapshot']) / 'story.json').read_text(encoding='utf-8'), story)

    def test_resume_preserves_manual_reading_observation_and_user_notes(self):
        self.photo('one.jpg')
        self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'one.jpg', 'date': '2020', 'note': '用户提供的地点备注', 'people': ['朋友甲']}]})
        reading = self.load('photo-reading.json')
        reading['items'][0]['observation'] = '人工已读图：红色测试色块'
        (self.output / 'photo-reading.json').write_text(json.dumps(reading, ensure_ascii=False), encoding='utf-8')
        self.run_import(resume=True)
        record = self.load('records.json')[0]
        self.assertEqual(record['date'], '2020')
        self.assertEqual(record['text'], '用户提供的地点备注')
        self.assertEqual(record['people'], ['朋友甲'])
        self.assertEqual(self.load('photo-reading.json')['items'][0]['observation'], '人工已读图：红色测试色块')

    def test_removed_source_file_is_not_silently_pruned_on_resume(self):
        self.photo('one.jpg')
        self.run_import()
        (self.source / 'one.jpg').rename(self.root / 'moved.jpg')
        receipt = self.run_import(resume=True)
        self.assertEqual(receipt['records_total'], 1)
        self.assertEqual(len(receipt['retained_previous_record_ids']), 1)

    def test_filename_date_is_labeled_inferred_not_timestamp(self):
        self.photo('IMG_20240304_123456.jpg')
        self.run_import()
        record = self.load('records.json')[0]
        self.assertEqual(record['date'], '2024-03-04')
        self.assertEqual(record['date_basis'], 'filename')
        self.assertIsNone(record['created_at'])

    def test_user_explicit_unknown_overrides_filename(self):
        self.photo('IMG_20240304_123456.jpg')
        self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'IMG_20240304_123456.jpg', 'date': None}]})
        self.assertIsNone(self.load('records.json')[0]['date'])

    def test_missing_manifest_file_and_multiframe_are_reported(self):
        first = Image.new('RGB', (30, 20), 'red')
        second = Image.new('RGB', (30, 20), 'blue')
        first.save(self.source / 'animated.gif', save_all=True, append_images=[second])
        receipt = self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'missing.jpg', 'date': '2020'}]})
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['failed_count'], 3)
        self.assertEqual(receipt['unique_imported'], 0)
        self.assertTrue(any('multiframe' in failure['reason'] for failure in receipt['failures']))

    def test_duplicate_prefers_user_manifest_then_conflict_is_visible(self):
        path = self.photo('first.jpg')
        (self.source / 'second.jpg').write_bytes(path.read_bytes())
        receipt = self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'first.jpg', 'date': '2020'}, {'file': 'second.jpg', 'date': '2021'}]})
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['exact_duplicate_count'], 1)
        self.assertEqual(receipt['failures'][0]['reason'], 'duplicate_date_conflict')

    def test_filename_evidence_cannot_claim_unrelated_date(self):
        self.photo('IMG_20240304_123456.jpg')
        self.run_import()
        record = self.load('records.json')[0]
        record.update(date='2025-01-01')
        record['date_evidence']['parsed_date'] = '2025-01-01'
        with self.assertRaises(ValueError):
            validate_photo_record(record, self.load('project_meta.json'))

    def test_empty_folder_is_not_claimed_ready(self):
        receipt = self.run_import()
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['records_total'], 0)
        self.assertFalse(receipt['story_ready'])
        self.assertTrue(any('no_readable_photos' in failure['reason'] for failure in receipt['failures']))

    def test_permission_denied_directory_is_counted_and_blocks_ok(self):
        self.photo('safe.jpg')
        self.photo('blocked/hidden.jpg', 'blue')
        denied = (self.source / 'blocked').resolve()
        original_scandir = os.scandir
        def guarded_scandir(path):
            if Path(path) == denied:
                raise PermissionError(13, 'synthetic denied directory', str(path))
            return original_scandir(path)
        with patch('photo_import.os.scandir', side_effect=guarded_scandir):
            receipt = self.run_import()
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['total_files'], 2)
        self.assertFalse(receipt['total_files_is_exact'])
        self.assertEqual(receipt['unreadable_paths'], ['blocked'])
        self.assertEqual(receipt['unique_imported'], 1)
        self.assertEqual(receipt['failed_count'], 1)
        self.assertTrue(any('PermissionError' in item['reason'] for item in receipt['failures']))
        self.assertEqual(self.load('coverage.json')['status'], 'partial')

    def test_security_mocks_use_canonical_targets_for_aliased_source(self):
        self.photo('safe.jpg')
        blocked = self.photo('escape.jpg', 'blue').resolve()
        self.photo('blocked/hidden.jpg', 'green')
        denied = (self.source / 'blocked').resolve()
        # A portable lexical alias exercises the same source normalization as
        # macOS /var -> /private/var without needing symlink privileges.
        alias_parent = self.root / 'alias-parent'
        alias_parent.mkdir()
        self.source = alias_parent / '..' / self.source.name
        self.assertNotEqual(self.source, self.source.resolve())
        real_is_symlink = Path.is_symlink
        original_scandir = os.scandir

        def is_symlink(path):
            return path == blocked or real_is_symlink(path)

        def guarded_scandir(path):
            if Path(path) == denied:
                raise PermissionError(13, 'synthetic denied directory', str(path))
            return original_scandir(path)

        with patch.object(Path, 'is_symlink', is_symlink), patch('photo_import.os.scandir', side_effect=guarded_scandir):
            receipt = self.run_import()
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['unique_imported'], 1)
        self.assertEqual(receipt['failed_count'], 2)
        self.assertFalse(receipt['total_files_is_exact'])
        self.assertEqual(receipt['unreadable_paths'], ['blocked'])
        reasons = [failure['reason'] for failure in receipt['failures']]
        self.assertIn('unsafe_file_link', reasons)
        self.assertTrue(any('PermissionError' in reason for reason in reasons))
        self.assertEqual(len(self.load('records.json')), 1)
        self.assertEqual(self.load('coverage.json')['status'], 'partial')

    def test_default_range_uses_old_photo_actual_year_without_adding_a_decade(self):
        self.photo('old.jpg')
        self.photo('unknown.jpg', 'blue')
        receipt = self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'old.jpg', 'date': '2010'}]})
        self.assertTrue(receipt['ok'])
        meta = self.load('project_meta.json')
        self.assertEqual(meta['requested_range']['start'], '2010-01-01')
        self.assertEqual(meta['requested_range']['end'], '2010-12-31')
        self.assertEqual(meta['time_scope']['range_mode'], 'observed_span')
        records = self.load('records.json')
        self.assertEqual({record['date'] for record in records}, {'2010', None})
        self.assertTrue(all(record['created_at'] is None for record in records))

    def test_automatic_range_widens_for_retained_records_and_month_precision(self):
        self.photo('old.jpg')
        self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'old.jpg', 'date': '2010-04'}]})
        (self.source / 'old.jpg').rename(self.root / 'retained.jpg')
        receipt = self.run_import(resume=True)
        self.assertTrue(receipt['ok'])
        self.assertEqual(self.load('project_meta.json')['requested_range']['start'], '2010-04-01')
        self.assertEqual(self.load('project_meta.json')['requested_range']['end'], '2010-04-30')
        self.assertEqual(self.load('records.json')[0]['date'], '2010-04')

    def test_explicit_range_is_preserved_and_outside_photo_not_silently_removed(self):
        self.photo('old.jpg')
        receipt = self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'old.jpg', 'date': '2010-04'}]}, requested_start='2020-01-01', requested_end='2025-12-31')
        self.assertFalse(receipt['ok'])
        self.assertEqual(self.load('project_meta.json')['requested_range'], {'start': '2020-01-01', 'end': '2025-12-31'})
        self.assertEqual(len(self.load('records.json')), 1)
        self.assertEqual(self.load('records.json')[0]['date'], '2010-04')
        self.assertEqual(receipt['out_of_requested_range_ids'], [self.load('records.json')[0]['id']])

    def test_missing_explicit_end_can_expand_without_overriding_explicit_start(self):
        self.photo('future.jpg')
        receipt = self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'future.jpg', 'date': '2040-09'}]}, requested_start='2000-01-01')
        self.assertTrue(receipt['ok'])
        self.assertEqual(self.load('project_meta.json')['requested_range'], {'start': '2000-01-01', 'end': '2040-09-30'})
        self.assertEqual(self.load('records.json')[0]['date'], '2040-09')

    def test_resume_automatic_range_ignores_old_default_window(self):
        self.photo('one.jpg')
        self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'one.jpg', 'date': '2024-02'}]})
        meta = self.load('project_meta.json')
        meta['requested_range'] = {'start': '2025-01-01', 'end': '2025-12-31'}
        (self.output / 'project_meta.json').write_text(json.dumps(meta), encoding='utf-8')
        self.run_import(resume=True)
        updated = self.load('project_meta.json')['requested_range']
        self.assertEqual(updated, {'start': '2024-02-01', 'end': '2024-02-29'})

    def test_single_day_photo_does_not_create_a_ten_year_scope(self):
        self.photo('one-day.jpg')
        receipt = self.run_import(manifest={'schema_version': 1, 'photos': [{'file': 'one-day.jpg', 'date': '2024-06-07'}]})
        self.assertTrue(receipt['ok'])
        meta = self.load('project_meta.json')
        self.assertEqual(meta['requested_range'], {'start': '2024-06-07', 'end': '2024-06-07'})
        self.assertEqual(meta['time_scope']['observed_range'], {'start': '2024-06-07', 'end': '2024-06-07'})

    def test_all_unknown_dates_have_unrestricted_guard_not_a_fabricated_shooting_range(self):
        self.photo('unknown.jpg')
        receipt = self.run_import()
        self.assertTrue(receipt['ok'])
        meta = self.load('project_meta.json')
        self.assertEqual(meta['time_scope']['status'], 'unknown')
        self.assertEqual(meta['time_scope']['range_mode'], 'unrestricted')
        self.assertTrue(meta['time_scope']['internal_bounds_only'])
        self.assertIsNone(meta['time_scope']['observed_range'])
        self.assertEqual(meta['requested_range'], {'start': '0001-01-01', 'end': '9999-12-31'})
        self.assertEqual(self.load('coverage.json')['observed_date_range'], {'start': None, 'end': None})
        self.assertIsNone(self.load('records.json')[0]['date'])
        index = (self.output / 'photo-index.html').read_text(encoding='utf-8')
        self.assertIn('日期待确认', index)
        for forbidden in ('十年', '0001', '9999', date.today().isoformat()):
            self.assertNotIn(forbidden, index)

    def test_user_selected_reference_album_is_not_filtered_by_year(self):
        self.photo('selected-cat-old.jpg')
        self.photo('selected-cat-new.jpg', 'blue')
        # The caller/user chooses the album. A file outside that local selection
        # is not scanned, and no face or pet identification is invented here.
        Image.new('RGB', (40, 40), 'green').save(self.root / 'not-selected.jpg')
        receipt = self.run_import(manifest={'schema_version': 1, 'photos': [
            {'file': 'selected-cat-old.jpg', 'date': '2002', 'note': '用户选定的同一只猫参考相册'},
            {'file': 'selected-cat-new.jpg', 'date': '2026-11-01', 'note': '用户选定的同一只猫参考相册'}]})
        self.assertTrue(receipt['ok'])
        self.assertEqual(receipt['unique_imported'], 2)
        self.assertEqual({record['date'] for record in self.load('records.json')}, {'2002', '2026-11-01'})
        self.assertEqual(self.load('project_meta.json')['requested_range'], {'start': '2002-01-01', 'end': '2026-11-01'})

    def gps_exif(self, latitude=(31, 13, 30), longitude=(121, 28, 0), lat_ref='N', lon_ref='E'):
        exif = Image.Exif()
        exif[36867] = '2024:06:07 12:13:14'
        exif[36881] = '+08:00'
        exif[271] = 'SYNTHETIC CAMERA BRAND'
        exif[272] = 'PRIVATE DEVICE MODEL'
        exif[34853] = {1: lat_ref, 2: tuple(IFDRational(part, 1) for part in latitude),
                       3: lon_ref, 4: tuple(IFDRational(part, 1) for part in longitude)}
        return exif

    def test_real_gps_exif_is_private_and_delivery_is_clean(self):
        original = self.photo('private-folder/gps-photo.jpg', exif=self.gps_exif())
        before = original.read_bytes()
        receipt = self.run_import()
        self.assertTrue(receipt['ok'])
        records = self.load('records.json')
        private = self.load('.private/photo-metadata.json')
        self.assertTrue(private['never_publish'])
        metadata = private['photos'][0]
        self.assertEqual(metadata['source_id'], records[0]['id'])
        self.assertEqual(metadata['exif_status'], 'present')
        self.assertEqual(metadata['capture_time']['status'], 'valid')
        self.assertEqual(metadata['capture_time']['raw_value'], '2024:06:07 12:13:14')
        self.assertEqual(metadata['capture_time']['created_at'], '2024-06-07T12:13:14+08:00')
        self.assertEqual(metadata['capture_time']['offset']['status'], 'valid')
        self.assertEqual(metadata['gps']['status'], 'valid')
        self.assertAlmostEqual(metadata['gps']['latitude'], 31.225)
        self.assertAlmostEqual(metadata['gps']['longitude'], 121.46666666666667)
        for path in ('records.json', 'photo-reading.json', 'photo-index.html'):
            public_text = (self.output / path).read_text(encoding='utf-8')
            for prohibited in ('latitude', 'longitude', 'GPSInfo', '31.225', '121.466', 'PRIVATE DEVICE MODEL', 'SYNTHETIC CAMERA BRAND', 'private-folder', str(self.source)):
                self.assertNotIn(prohibited, public_text)
        with Image.open(self.output / records[0]['images'][0]['large_path']) as delivered:
            self.assertEqual(dict(delivered.getexif()), {})
        self.assertEqual(original.read_bytes(), before)

    def test_gps_direction_south_and_west_are_respected(self):
        self.photo('gps.jpg', exif=self.gps_exif(lat_ref='S', lon_ref='W'))
        self.run_import()
        gps = self.load('.private/photo-metadata.json')['photos'][0]['gps']
        self.assertEqual(gps['status'], 'valid')
        self.assertLess(gps['latitude'], 0)
        self.assertLess(gps['longitude'], 0)

    def test_missing_and_invalid_gps_and_time_remain_distinct(self):
        self.photo('missing.jpg')
        bad = self.gps_exif(latitude=(95, 0, 0))
        bad[36867] = 'not-a-capture-time'
        bad[36881] = '+99:88'
        self.photo('bad.jpg', 'blue', exif=bad)
        receipt = self.run_import()
        self.assertTrue(receipt['ok'])
        by_file = {entry['source_files'][0]: entry for entry in self.load('.private/photo-metadata.json')['photos']}
        missing = by_file['missing.jpg']
        self.assertEqual(missing['exif_status'], 'missing')
        self.assertEqual(missing['capture_time']['status'], 'missing')
        self.assertEqual(missing['gps']['status'], 'missing')
        invalid = by_file['bad.jpg']
        self.assertEqual(invalid['capture_time']['status'], 'invalid')
        self.assertEqual(invalid['capture_time']['offset']['status'], 'invalid')
        self.assertEqual(invalid['gps']['status'], 'invalid')
        self.assertIsNone(invalid['gps']['latitude'])
        self.assertIsNone(invalid['gps']['longitude'])
        self.assertTrue(all(record['date'] is None for record in self.load('records.json')))
        self.assertTrue(all(record['created_at'] is None for record in self.load('records.json')))

    def test_private_metadata_survives_resume_and_duplicate_aliases_bind_one_record(self):
        original = self.photo('gps.jpg', exif=self.gps_exif())
        (self.source / 'same-photo.jpg').write_bytes(original.read_bytes())
        self.run_import()
        first = self.load('.private/photo-metadata.json')['photos']
        self.assertEqual(len(first), 1)
        self.assertEqual(set(first[0]['source_files']), {'gps.jpg', 'same-photo.jpg'})
        original.rename(self.root / 'moved-one.jpg')
        (self.source / 'same-photo.jpg').rename(self.root / 'moved-two.jpg')
        self.run_import(resume=True)
        self.assertEqual(self.load('.private/photo-metadata.json')['photos'], first)

    def test_pre_metadata_project_is_not_falsely_marked_as_exif_missing(self):
        original = self.photo('gps.jpg', exif=self.gps_exif())
        self.run_import()
        (self.output / '.private' / 'photo-metadata.json').rename(self.root / 'saved-private-index.json')
        original.rename(self.root / 'removed.jpg')
        self.run_import(resume=True)
        metadata = self.load('.private/photo-metadata.json')['photos'][0]
        self.assertEqual(metadata['exif_status'], 'unavailable')
        self.assertEqual(metadata['capture_time']['status'], 'unavailable')
        self.assertEqual(metadata['gps']['status'], 'unavailable')
        self.assertIsNone(metadata['gps']['latitude'])


class DateContractTests(unittest.TestCase):
    def test_partial_date_validation(self):
        for value, precision in ((None, 'unknown'), ('2020', 'year'), ('2024-02', 'month'), ('2024-02-29', 'day')):
            self.assertEqual(photo_date({'date': value, 'date_precision': precision}), value)
        for value, precision in (('2023-02-29', 'day'), ('2024-13', 'month'), ('2024', 'day'), (None, 'year')):
            with self.assertRaises(ValueError):
                photo_date({'date': value, 'date_precision': precision})


if __name__ == '__main__':
    unittest.main()
