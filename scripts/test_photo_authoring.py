"""Synthetic checks for numbered reading aids; no real albums or cloud access."""
import copy
import tempfile
import unittest
from pathlib import Path

from archive_common import load, save
from check_project import check
from photo_authoring import prepare_authoring
from photo_import import import_photos
from prepare_art_direction import objects_for
from runtime_contract import validate_runtime
from story_tools import compile_draft


class PhotoAuthoringTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image, ImageDraw
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name)
        original = self.parent / 'private-input-do-not-publish'
        original.mkdir()
        for n, color in enumerate(('#6e9eae', '#d4ab7d', '#ba7a98', '#7d9a75', '#aa9dc2')):
            image = Image.new('RGB', (180 + n * 15, 140), color)
            ImageDraw.Draw(image).text((15, 40), 'SYNTHETIC ' + str(n), fill='white')
            image.save(original / ('tile-%d.jpg' % n))
        manifest = {'schema_version': 1, 'photos': [
            {'file': 'tile-0.jpg', 'date': '2021-04-12'},
            {'file': 'tile-1.jpg', 'date': '2022-06'},
            {'file': 'tile-2.jpg', 'date': '2020'},
        ]}
        self.project = self.parent / 'project'
        result = import_photos(original, self.project, manifest=manifest,
                               collection_name='合成测试素材', synthetic_fixture=True)
        self.assertTrue(result['ok'], result)

    def tearDown(self):
        self.temp.cleanup()

    def test_contact_sheets_cover_every_source_and_preserve_date_precision(self):
        from PIL import Image
        result = prepare_authoring(self.project, per_sheet=2, columns=2)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['contact_sheets']), 3)
        records = load(self.project / 'records.json')
        index = load(self.project / result['index'])
        self.assertEqual([item['source_id'] for item in index['items']], [row['id'] for row in records])
        self.assertEqual([item['number'] for item in index['items']], list(range(1, 6)))
        self.assertEqual([item['date'] for item in index['items']], [row['date'] for row in records])
        self.assertEqual(sum(len(sheet['source_ids']) for sheet in index['sheets']), len(records))
        for sheet in result['contact_sheets']:
            with Image.open(self.project / sheet) as image:
                image.load()
                self.assertEqual(image.format, 'JPEG')
                self.assertFalse(image.getexif())
        self.assertFalse(result['semantic_image_review_performed'])
        self.assertFalse(result['ready_to_publish'])

    def test_existing_observations_story_and_draft_survive_rerun(self):
        records = load(self.project / 'records.json')
        reading = load(self.project / 'photo-reading.json')
        reading['status'] = 'partially_reviewed'
        reading['items'][0].update(observation='合成图中有白色编号。', candidate_group='人工分组 A')
        save(self.project / 'photo-reading.json', reading)
        final = {'author_written': 'Do not modify this story.'}
        save(self.project / 'story.json', final)
        first = prepare_authoring(self.project)
        draft_path = self.project / first['draft']
        draft = load(draft_path)
        draft['authoring']['working_note'] = '保存人工编辑'
        save(draft_path, draft)
        second = prepare_authoring(self.project, per_sheet=2)
        updated = load(self.project / 'photo-reading.json')
        self.assertEqual(updated['status'], 'partially_reviewed')
        self.assertEqual(updated['items'][0]['observation'], '合成图中有白色编号。')
        self.assertEqual(updated['items'][0]['candidate_group'], '人工分组 A')
        self.assertEqual(updated['items'][0]['source_id'], records[0]['id'])
        self.assertEqual(load(draft_path), draft)
        self.assertEqual(load(self.project / 'story.json'), final)
        self.assertTrue(second['existing_draft_preserved'])

    def test_draft_has_correct_image_evidence_but_is_not_a_publishable_story(self):
        result = prepare_authoring(self.project)
        draft = load(self.project / result['draft'])
        meta, records = load(self.project / 'project_meta.json'), load(self.project / 'records.json')
        by_id = {row['id']: row for row in records}
        self.assertFalse(draft['authoring']['publishable'])
        self.assertEqual(draft['status'], 'draft_not_publishable')
        self.assertFalse((self.project / 'story.json').exists())
        with self.assertRaises(ValueError):
            validate_runtime(meta, records, draft, root=self.project)
        values = copy.deepcopy(draft['scene']['objects'])
        for n, obj in enumerate(values):
            self.assertEqual(obj['evidence_kind'], 'image')
            sid = obj['source_ids'][0]
            self.assertEqual(obj['image_path'], by_id[sid]['images'][0]['large_path'])
            # Test-only actual observations complete the real art-direction schema.
            obj.update(name='测试编号 %d' % n, evidence='合成测试图中有白色编号。', placement='测试画面左侧')
        validated = objects_for(values, by_id, self.project)
        self.assertEqual(len(validated), min(3, len(records)))
        self.assertEqual({ref['source_id'] for ref in draft['authoring']['source_image_map']}, set(by_id))

    def test_real_draft_compiler_accepts_image_refs_but_blank_story_still_fails(self):
        result = prepare_authoring(self.project)
        draft = load(self.project / result['draft'])
        compiled = compile_draft(self.project, draft)
        records = load(self.project / 'records.json')
        actual_paths = [row['images'][0]['large_path'] for row in records]
        self.assertEqual(compiled['overview']['image_paths'], actual_paths[:3])
        self.assertEqual(compiled['themes'][0]['image_paths'], actual_paths)
        self.assertNotIn('image_refs', compiled['overview'])
        self.assertEqual(compiled['authoring']['source_image_map'], draft['authoring']['source_image_map'])
        save(self.project / 'story.json', draft)
        rejected = check(self.project, 'photos', 'story')
        self.assertFalse(rejected['ok'], rejected)
        self.assertFalse(rejected['build_ready'])
        self.assertTrue(any('overview' in error and '需要有内容的短记' in error
                            for error in rejected['errors']), rejected)
        self.assertFalse(any('Image reference' in error for error in rejected['errors']), rejected)

    def test_authored_synthetic_story_uses_generated_references_through_story_check(self):
        from PIL import Image
        result = prepare_authoring(self.project)
        draft = load(self.project / result['draft'])
        for evidence in draft['evidence']:
            evidence['observation'] = '合成色块中有白色测试编号。'
        draft['overview'].update(headline='合成测试照片', opening='用于验证来源引用。',
                                 text='这些是带白色编号的合成色块，不是真实回忆。')
        draft['overview']['portrait'].update(title='测试说明', text='只验证照片引用，不代表用户经历。')
        draft['themes'][0].update(title='合成测试色块', text='这些照片是程序生成的测试素材。')
        # No actual generated scene exists in this test. Optional scene is omitted,
        # rather than inventing image positions to pass a check.
        draft.pop('scene')
        decoration = self.project / 'decorations' / 'synthetic-closing.png'
        decoration.parent.mkdir()
        Image.new('RGB', (40, 30), '#eee5d8').save(decoration)
        draft['letter'].update(title='测试结束', paragraphs=['等待真实素材后再写真实回忆。'],
                               closing='这只是合成测试。', image_path='decorations/synthetic-closing.png',
                               image_alt='合成测试装饰')
        draft['wishes'][0].update(title='核对来源', text='确认展示的是对应编号色块。')
        draft['share'].update(headline='合成测试照片', text='不是真实回忆', letter_text='完成来源引用测试。')
        for item in draft['share']['entries']:
            item.update(title='测试照片', text='带编号的合成色块。')
        save(self.project / 'story.json', draft)
        verdict = check(self.project, 'photos', 'story')
        self.assertTrue(verdict['ok'], verdict)

    def test_private_metadata_is_never_copied_to_helpers(self):
        marker = 'PRIVATE-SOURCE-AND-GPS-NOT-FOR-PUBLIC-0db4'
        save(self.project / '.private' / 'photo-metadata.json',
             {'source_directory': str(self.parent), 'marker': marker, 'gps': {'latitude': 31.225}})
        result = prepare_authoring(self.project)
        for relative in (result['index'], result['draft'], result['reading']):
            content = (self.project / relative).read_text('utf-8')
            self.assertNotIn(marker, content)
            self.assertNotIn(str(self.parent), content)
            self.assertNotIn('31.225', content)
            self.assertNotIn('private-input-do-not-publish', content)

    def test_tampered_bytes_fail_before_any_authoring_output(self):
        records = load(self.project / 'records.json')
        (self.project / records[0]['images'][0]['large_path']).write_bytes(b'not an image')
        before = (self.project / 'photo-reading.json').read_bytes()
        with self.assertRaises(ValueError):
            prepare_authoring(self.project)
        self.assertEqual((self.project / 'photo-reading.json').read_bytes(), before)
        self.assertFalse((self.project / 'photo-authoring-index.json').exists())
        self.assertFalse((self.project / 'story-draft.json').exists())

    def test_invalid_options_and_wrong_source_are_rejected(self):
        for options in ({'per_sheet': 0}, {'per_sheet': True}, {'per_sheet': 1000}, {'columns': 0}, {'columns': 7}):
            with self.assertRaises(ValueError):
                prepare_authoring(self.project, **options)
        meta = load(self.project / 'project_meta.json')
        meta['platform'] = 'weibo'
        save(self.project / 'project_meta.json', meta)
        with self.assertRaisesRegex(ValueError, 'platform:photos'):
            prepare_authoring(self.project)


if __name__ == '__main__':
    unittest.main()
