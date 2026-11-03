"""Orchestration tests for the self-locating one-read profile capture (reason handling + nulls)."""
import json
import tempfile
import unittest
from pathlib import Path

from archive_common import load
from archive_pipeline import initialize
from user_profile import capture_profile_auto

UID = '1705586121'
AVATAR = ('https://tvax3.sinaimg.cn/crop.0.0.1080.1080.180/001RqsRzly8ihrjs1kwd2j60u00u0n2y02.jpg'
          '?KID=imgbed,tva&Expires=1793632515&ssig=p%2FHh%2BhDAkP')


class FakeBu:
    def __init__(self, envelope):
        self.envelope = envelope
        self.calls = []

    def js(self, expression):
        self.calls.append(expression)
        return json.dumps(self.envelope)


def success_envelope(**overrides):
    base = {'success': True, 'uid': UID,
            'source_url': 'https://weibo.com/u/' + UID,
            'basis': {'target_anchor': '/u/page/follow/' + UID + '?relate=fans',
                      'header_unique': True, 'stat_format': 'value+label'},
            'name': 'GEM鄧紫棋', 'avatar_source_url': AVATAR,
            'followers': '3605.2万', 'following': '507', 'engagement': '3.96亿'}
    base.update(overrides)
    return base


class ProfileAutoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize(self.root, UID, 'https://weibo.com/u/' + UID,
                   '2016-11-02', '2026-11-02', mode='selected', title='人生手账')

    def tearDown(self):
        self.temp.cleanup()

    def _capture(self, envelope):
        return capture_profile_auto(FakeBu(envelope), self.root)

    def test_normal_success_captures_all_fields_and_basis(self):
        r = self._capture(success_envelope())
        self.assertEqual(r['status'], 'captured')
        self.assertTrue(r['selector_basis']['header_unique'])
        meta = load(self.root / 'project_meta.json')
        profile = meta['profile']
        self.assertEqual(profile['name'], 'GEM鄧紫棋')
        self.assertEqual(profile['followers']['display'], '3605.2万')
        self.assertFalse(profile['followers']['exact'])
        self.assertEqual(profile['following']['value'], 507)
        self.assertTrue(profile['following']['exact'])
        self.assertEqual(profile['engagement']['value'], 396000000)
        self.assertEqual(meta['title'], 'GEM鄧紫棋的微博人生手账')

    def test_login_required_is_reported_without_writing_profile(self):
        r = self._capture({'success': False, 'reason': 'login_required'})
        self.assertEqual(r['status'], 'login_required')
        self.assertNotIn('profile', load(self.root / 'project_meta.json'))

    def test_non_unique_root_is_reported_with_count(self):
        r = self._capture({'success': False, 'reason': 'profile_not_unique', 'count': 2})
        self.assertEqual((r['status'], r['count']), ('profile_not_unique', 2))

    def test_fields_missing_reason_is_reported(self):
        r = self._capture({'success': False, 'reason': 'profile_fields_missing'})
        self.assertEqual(r['status'], 'profile_fields_missing')

    def test_wrong_target_and_desktop_required_reasons(self):
        self.assertEqual(self._capture(
            {'success': False, 'reason': 'wrong_target'})['status'], 'wrong_target')
        self.assertEqual(self._capture(
            {'success': False, 'reason': 'desktop_required'})['status'], 'desktop_required')

    def test_missing_stat_stays_null_not_zero(self):
        r = self._capture(success_envelope(following=None))
        self.assertEqual(r['status'], 'captured')
        profile = load(self.root / 'project_meta.json')['profile']
        self.assertEqual(profile['following'],
                         {'display': '—', 'value': None, 'exact': False, 'observed': False})
        # the other two stats are still observed
        self.assertTrue(profile['followers']['observed'])
        self.assertTrue(profile['engagement']['observed'])

    def test_uid_mismatch_raises(self):
        with self.assertRaises(ValueError):
            self._capture(success_envelope(uid='999'))

    def test_wrong_source_url_raises(self):
        with self.assertRaises(ValueError):
            self._capture(success_envelope(source_url='https://weibo.com/u/999'))

    def test_missing_name_or_avatar_returns_fields_missing(self):
        self.assertEqual(self._capture(
            success_envelope(name=None))['status'], 'profile_fields_missing')
        self.assertEqual(self._capture(
            success_envelope(avatar_source_url=None))['status'], 'profile_fields_missing')


if __name__ == '__main__':
    unittest.main()
