"""Offline packing preserves UTF-8 text independently of the system locale."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pack_html


class NonUtf8LocalePath(type(Path())):
    """A module-local path double; never changes Python's global I/O locale."""

    def read_text(self, encoding=None, errors=None):
        if encoding is None:
            raise UnicodeDecodeError('cp1252', b'\x81', 0, 1,
                                     'synthetic non-UTF-8 locale; explicit encoding required')
        return super().read_text(encoding=encoding, errors=errors)


class PackEncodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / '相册框架'
        self.project.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, encoding='utf-8'):
        data = {'meta': {'platform': 'photos'}, 'story': {'title': '窗边的日常'},
                'records': [{'id': 'fixture', 'text': '生日、旅行与小猫', 'images': []}],
                'extra_paths': []}
        (self.project / 'journal-data.js').write_text(
            'window.JOURNAL_DATA = ' + json.dumps(data, ensure_ascii=False) + ';\n',
            encoding=encoding)
        (self.project / 'index.html').write_text(
            '<!doctype html><meta charset="utf-8"><title>照片回看</title>'
            '<link rel="icon" href="favicon.svg">'
            '<link rel="stylesheet" href="styles.css">'
            '<h1>我们的普通一天</h1>'
            '<script src="journal-data.js"></script>'
            '<script src="app.js"></script>', encoding=encoding)
        (self.project / 'styles.css').write_text(
            '/* 纸张与留白 */\nbody{font-family:system-ui}', encoding=encoding)
        (self.project / 'app.js').write_text(
            'window.PHOTO_LABEL="日期待确认";', encoding=encoding)
        (self.project / 'favicon.svg').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding='utf-8')

    def locale_patch(self):
        real_project_file = pack_html.project_file
        # Only pack_html's constructors/resource resolver use the test double.
        # pathlib, tempfile, test fixture writes and other modules stay intact.
        return (patch.object(pack_html, 'Path', NonUtf8LocalePath),
                patch.object(pack_html, 'project_file',
                             side_effect=lambda root, name: NonUtf8LocalePath(real_project_file(root, name))))

    def test_pack_and_verify_ignore_non_utf8_system_locale(self):
        for encoding in ('utf-8', 'utf-8-sig'):
            with self.subTest(encoding=encoding):
                self.fixture(encoding)
                output = self.root / ('手帐-' + encoding + '.html')
                path_patch, resource_patch = self.locale_patch()
                with path_patch, resource_patch:
                    estimate = pack_html.estimate(self.project)
                    receipt = pack_html.pack(self.project, output)
                    checked = pack_html.verify_packed(output)
                packed = output.read_text(encoding='utf-8')
                self.assertTrue(estimate['ok'])
                self.assertTrue(checked['ok'])
                self.assertEqual(checked['records'], 1)
                self.assertEqual(receipt['bytes'], estimate['bytes'])
                for expected in ('照片回看', '我们的普通一天', '窗边的日常',
                                 '生日、旅行与小猫', '纸张与留白', '日期待确认'):
                    self.assertIn(expected, packed)
                self.assertNotIn('\ufeff', packed)

    def test_verify_accepts_bom_without_using_locale_defaults(self):
        self.fixture()
        output = self.root / 'packed.html'
        pack_html.pack(self.project, output)
        output.write_bytes(b'\xef\xbb\xbf' + output.read_bytes())
        path_patch, resource_patch = self.locale_patch()
        with path_patch, resource_patch:
            checked = pack_html.verify_packed(output)
        self.assertTrue(checked['ok'])


if __name__ == '__main__':
    unittest.main()
