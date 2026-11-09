"""Synthetic local/system export intake tests; no user's album is read."""
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from photo_import import import_photos
from photo_sources import _extract_zip, is_placeholder, prepare_photo_source


def jpeg_bytes(color='red'):
    output = io.BytesIO()
    Image.new('RGB', (32, 24), color).save(output, format='JPEG')
    return output.getvalue()


class PhotoSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / 'project'
        self.folder = self.root / 'exported'
        self.folder.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, entries, name='selected-album.zip', compression=zipfile.ZIP_STORED):
        archive = self.root / name
        with zipfile.ZipFile(archive, 'w', compression=compression) as target:
            for member, data in entries:
                if isinstance(member, str):
                    info = zipfile.ZipInfo('placeholder')
                    info.filename = member
                    info.orig_filename = member
                    info.compress_type = compression
                    member = info
                target.writestr(member, data)
        return archive

    def load(self, name):
        return json.loads((self.output / name).read_text(encoding='utf-8'))

    def test_user_selected_folder_is_read_only_and_uses_existing_contract(self):
        original = self.folder / 'IMG_20240607_120000.jpg'
        original.write_bytes(jpeg_bytes())
        before = original.read_bytes()
        result = import_photos(self.folder, self.output, synthetic_fixture=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source_kind'], 'exported_photo_folder')
        self.assertEqual(self.load('project_meta.json')['platform'], 'photos')
        self.assertEqual(self.load('records.json')[0]['date'], '2024-06-07')
        self.assertEqual(before, original.read_bytes())

    def test_exactly_empty_precreated_output_is_fresh_with_or_without_resume(self):
        (self.folder / 'one.jpg').write_bytes(jpeg_bytes())
        for resume in (False, True):
            output = self.root / ('fresh-resume' if resume else 'fresh')
            output.mkdir()
            result = import_photos(self.folder, output, resume=resume, synthetic_fixture=True)
            self.assertTrue(result['ok'])
            self.assertEqual(result['records_total'], 1)
            self.assertTrue((output / 'project_meta.json').is_file())

    def test_nonempty_output_is_not_overwritten(self):
        self.output.mkdir()
        original = self.output / 'important.txt'
        original.write_text('keep me', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            import_photos(self.folder, self.output)
        self.assertEqual(original.read_text(encoding='utf-8'), 'keep me')

    def test_photo_zip_preserves_bytes_and_stable_collection_on_resume(self):
        archive = self.archive([('selected/one.jpg', jpeg_bytes())])
        before = archive.read_bytes()
        first = import_photos(archive, self.output, synthetic_fixture=True)
        self.assertTrue(first['ok'])
        self.assertEqual(first['source_kind'], 'exported_photo_zip')
        collection = self.load('project_meta.json')['target']['collection_id']
        (self.output / 'story.json').write_text('{"manual":"keep"}', encoding='utf-8')
        second = import_photos(archive, self.output, synthetic_fixture=True, resume=True)
        self.assertTrue(second['ok'])
        self.assertEqual(second['reused_files'], 1)
        self.assertEqual(self.load('project_meta.json')['target']['collection_id'], collection)
        self.assertEqual(self.load('story.json'), {'manual': 'keep'})
        self.assertEqual(archive.read_bytes(), before)
        for public_name in ('records.json', 'photo-reading.json', 'photo-index.html', 'project_meta.json'):
            self.assertNotIn(str(archive), (self.output / public_name).read_text(encoding='utf-8'))

    def test_prepared_zip_scratch_is_removed_after_use(self):
        archive = self.archive([('one.jpg', jpeg_bytes())])
        with prepare_photo_source(archive, self.output) as selected:
            scratch = selected.root
            self.assertTrue((scratch / 'one.jpg').is_file())
        self.assertFalse(scratch.exists())

    def test_zip_resume_does_not_read_metadata_before_output_link_guards(self):
        archive = self.archive([('one.jpg', jpeg_bytes())])
        self.output.mkdir()
        prior_meta = self.output / 'project_meta.json'
        prior_meta.write_text('{"target":{"collection_id":"must-not-read"}}', encoding='utf-8')
        real_is_symlink = Path.is_symlink
        for blocked in (self.output.resolve(), prior_meta.resolve()):
            def is_link(path):
                return path == blocked or real_is_symlink(path)
            with self.subTest(blocked=blocked), patch.object(Path, 'is_symlink', is_link), patch.object(Path, 'read_text', side_effect=AssertionError('metadata read before path/link guard')):
                with self.assertRaisesRegex(ValueError, '符号链接|越界链接'):
                    import_photos(archive, self.output, resume=True)

    def test_traversal_absolute_windows_and_stream_paths_rejected_before_extract(self):
        for index, unsafe in enumerate(('../escape.jpg', '/escape.jpg', 'C:/escape.jpg', 'dir\\escape.jpg', 'one.jpg:payload', 'safe/../escape.jpg', 'safe//escape.jpg', 'NUL.jpg', 'name. /x.jpg')):
            archive = self.archive([('safe.jpg', jpeg_bytes()), (unsafe, jpeg_bytes())], name=f'unsafe-{index}.zip')
            destination = self.root / f'extract-{index}'
            destination.mkdir()
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                _extract_zip(archive, destination)
            self.assertEqual(list(destination.iterdir()), [])
        self.assertFalse((self.root / 'escape.jpg').exists())

    def test_zip_symlinks_and_special_files_are_rejected(self):
        for index, mode in enumerate((stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600)):
            info = zipfile.ZipInfo('not-a-photo.jpg')
            info.create_system = 3
            info.external_attr = mode << 16
            archive = self.archive([(info, b'outside-target')], name=f'link-{index}.zip')
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'unsafe_zip_link_or_special_file'):
                with prepare_photo_source(archive, self.output):
                    self.fail('unsafe archive was accepted')

    def test_zip_case_collisions_are_rejected(self):
        archive = self.archive([('Photo.jpg', jpeg_bytes()), ('photo.jpg', jpeg_bytes('blue'))])
        with self.assertRaisesRegex(ValueError, 'duplicate_path'):
            with prepare_photo_source(archive, self.output):
                self.fail('case-colliding archive was accepted')

    def test_zip_expansion_entry_member_total_and_ratio_limits(self):
        archive = self.archive([('one.jpg', b'x' * 1000), ('two.jpg', b'y' * 1000)], compression=zipfile.ZIP_DEFLATED)
        for index, limits in enumerate(({'max_entries': 1}, {'max_member_bytes': 100}, {'max_bytes': 1500}, {'max_ratio': 2})):
            destination = self.root / f'limited-{index}'
            destination.mkdir()
            with self.subTest(limits=limits), self.assertRaisesRegex(ValueError, 'photo_zip_limit'):
                _extract_zip(archive, destination, **limits)
            self.assertEqual(list(destination.iterdir()), [])

    def test_native_library_or_internal_path_is_rejected_without_scanning(self):
        library = self.root / 'Personal.photoslibrary'
        (library / 'originals').mkdir(parents=True)
        (library / 'originals' / 'one.jpg').write_bytes(jpeg_bytes())
        for source in (library, library / 'originals'):
            with self.subTest(source=source), patch('photo_import.os.walk', side_effect=AssertionError('must not scan library')):
                with self.assertRaisesRegex(ValueError, 'native_photo_library_requires_export'):
                    import_photos(source, self.output)
        self.assertFalse(self.output.exists())

    def test_nested_native_library_is_reported_without_descending(self):
        (self.folder / 'safe.jpg').write_bytes(jpeg_bytes())
        library = self.folder / 'other.photoslibrary'
        library.mkdir()
        (library / 'private.jpg').write_bytes(jpeg_bytes('blue'))
        result = import_photos(self.folder, self.output, synthetic_fixture=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['unique_imported'], 1)
        self.assertFalse(result['total_files_is_exact'])
        self.assertTrue(any('native_photo_library_requires_export' in entry['reason'] for entry in result['failures']))

    def test_zip_containing_native_library_is_rejected_before_scan(self):
        archive = self.archive([('Personal.photoslibrary/originals/one.jpg', jpeg_bytes())])
        with self.assertRaisesRegex(ValueError, 'native_photo_library_requires_export'):
            import_photos(archive, self.output)
        self.assertFalse(self.output.exists())

    def test_catalog_is_not_mistaken_for_an_export(self):
        catalog = self.root / 'Photos.sqlite'
        catalog.write_bytes(b'synthetic sqlite marker')
        with self.assertRaisesRegex(ValueError, 'photo_source_requires_export'):
            import_photos(catalog, self.output)

    def test_output_inside_native_library_is_rejected_before_read_or_write(self):
        library = self.root / 'Personal.photoslibrary'
        library.mkdir()
        archive = self.archive([('one.jpg', jpeg_bytes())])
        for source in (self.folder, archive):
            with self.subTest(source=source), patch('photo_import.os.walk', side_effect=AssertionError('must not scan')), patch('photo_sources._extract_zip', side_effect=AssertionError('must not extract')):
                with self.assertRaisesRegex(ValueError, 'native_photo_library_output_forbidden'):
                    import_photos(source, library / 'new-project')
        self.assertEqual(list(library.iterdir()), [])

    def test_renamed_heic_with_jpeg_bytes_imports_without_heif_plugin(self):
        original = self.folder / 'IMG_20240102_120000.HEIC'
        original.write_bytes(jpeg_bytes())
        before = original.read_bytes()
        result = import_photos(self.folder, self.output, synthetic_fixture=True)
        self.assertTrue(result['ok'])
        record = self.load('records.json')[0]
        self.assertTrue(record['images'][0]['large_path'].endswith('.jpg'))
        self.assertEqual(record['date'], '2024-01-02')
        self.assertEqual(original.read_bytes(), before)

    def test_true_unreadable_heic_reports_decoder_requirement_not_silent_skip(self):
        (self.folder / 'photo.heic').write_bytes(b'\x00\x00\x00\x18ftypheic' + b'\x00' * 32)
        with patch('PIL.Image.registered_extensions', return_value={'.jpg': 'JPEG'}):
            result = import_photos(self.folder, self.output, synthetic_fixture=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['unsupported_count'], 0)
        self.assertTrue(any('heif_decoder_unavailable' in entry['reason'] for entry in result['failures']))

    def test_known_cloud_stubs_and_empty_images_are_visible_failures(self):
        (self.folder / 'safe.jpg').write_bytes(jpeg_bytes())
        (self.folder / '.IMG_20240102.jpg.icloud').write_bytes(b'cloud stub')
        (self.folder / 'empty.jpg').write_bytes(b'')
        result = import_photos(self.folder, self.output, synthetic_fixture=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['unique_imported'], 1)
        self.assertTrue(any('cloud_placeholder_requires_download' in entry['reason'] for entry in result['failures']))
        self.assertTrue(any('empty_photo_requires_download_or_reexport' in entry['reason'] for entry in result['failures']))

    def test_windows_cloud_recall_attributes_are_detected(self):
        sample = self.folder / 'one.jpg'
        sample.write_bytes(jpeg_bytes())
        class CloudStat:
            st_file_attributes = 0x400000
        with patch.object(Path, 'stat', return_value=CloudStat()):
            self.assertTrue(is_placeholder(sample))


if __name__ == '__main__':
    unittest.main()
