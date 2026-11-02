"""Fusion invariants: no live accounts, no network, no private artifacts."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_common import load, save
from archive_pipeline import initialize, ingest, materialize
from build_journal import prepare
from collect_weibo import configure_mobile, probe_mobile_boundary
from manage_media import download, plan, recompress
from test_pipeline import png, row
from test_build_journal import fixture


class Mobile:
    def page_info(self): return {'url':'https://m.weibo.cn/u/123'}


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)/'source'
        initialize(self.root,'123','https://weibo.com/u/123','2025-01-01','2025-12-31',mode='full')
    def tearDown(self): self.temp.cleanup()

    def test_default_modes_are_optional_and_quota_is_thirty(self):
        meta=load(self.root/'project_meta.json')
        self.assertEqual(meta['selection_policy']['yearly_limit'],30)
        self.assertFalse(meta['collection']['include_video_covers'])
        self.assertFalse(meta['presentation']['experience_required'])
        self.assertFalse(meta['presentation']['profile_required'])

    def test_default_rejects_video_but_opt_in_keeps_it(self):
        video=row('99',author_uid='123',is_video=True)
        self.assertEqual(ingest(self.root,[video])['candidate_count'],0)
        meta=load(self.root/'project_meta.json');meta['collection']['include_video_covers']=True;save(self.root/'project_meta.json',meta)
        self.assertEqual(ingest(self.root,[video])['candidate_count'],1)

    def test_missing_inventory_cannot_become_confirmed_zero(self):
        ingest(self.root,[row('100',author_uid='123')]); result=materialize(self.root)
        self.assertEqual(result['pending_details'],1)
        self.assertIsNone(load(self.root/'records.json')[0]['expected_image_count'])

    def test_materialize_preserves_verified_inventory_from_old_import(self):
        ingest(self.root,[row('100',author_uid='123')]);materialize(self.root)
        records=load(self.root/'records.json');records[0].update(expected_image_count=0,image_count_basis='Actual detail proof',image_inventory_status='complete');save(self.root/'records.json',records)
        materialize(self.root)
        self.assertEqual(load(self.root/'records.json')[0]['image_inventory_status'],'complete')
        self.assertEqual(load(self.root/'records.json')[0]['image_count_basis'],'Actual detail proof')

    def test_reconfigure_mobile_preserves_checkpoint_and_block(self):
        configure_mobile(Mobile(),self.root)
        state=load(self.root/'mobile-state.json');state.update(next_page=57,blocked='verification',pages=[{'page':56}],next_allowed_at=500);save(self.root/'mobile-state.json',state)
        before=(self.root/'mobile-state.json').read_bytes()
        result=configure_mobile(Mobile(),self.root)
        self.assertEqual(result['status'],'handoff');self.assertEqual(result['next_page'],57)
        self.assertEqual(before,(self.root/'mobile-state.json').read_bytes())

    def test_bisection_resumes_saved_bounds_not_page_one(self):
        configure_mobile(Mobile(),self.root)
        state=load(self.root/'mobile-state.json');state['boundary_probe']={'high_page':8,'lo':4,'hi':6,'notices':[]};save(self.root/'mobile-state.json',state)
        pages=[]
        def fetch(bu,config,page): pages.append(page);return ([{'id':'100'}] if page==5 else [],[],str(page))
        with patch('collect_weibo._mobile_request_page',fetch):
            result=probe_mobile_boundary(Mobile(),self.root,high_page=8,clock=lambda:1000,sleep=lambda _:None)
        self.assertEqual(result['last_page'],5);self.assertEqual(pages,[5])

    def test_bisection_rechecks_unexplained_empty_page(self):
        configure_mobile(Mobile(),self.root)
        state=load(self.root/'mobile-state.json');state['boundary_probe']={'high_page':8,'lo':4,'hi':6,'notices':[]};save(self.root/'mobile-state.json',state)
        calls=[]
        def fetch(bu,config,page):
            calls.append(page);return ([{'id':'100'}] if len(calls)==2 else [],[],str(page))
        with patch('collect_weibo._mobile_request_page',fetch):
            result=probe_mobile_boundary(Mobile(),self.root,high_page=8,clock=lambda:1000,sleep=lambda _:None)
        self.assertEqual(result['last_page'],5);self.assertEqual(calls,[5,5])

    def test_display_compression_preserves_original_and_unreferenced_files(self):
        path=self.root/'images/a.png';path.parent.mkdir();path.write_bytes(png(400,300))
        unused=self.root/'images/not-selected.png';unused.write_bytes(png(11,12))
        record=row('100',author_uid='123',expected_image_count=1,image_count_basis='Actual pic_num=1',image_inventory_status='complete',images=[{'image_id':'a','origin':'platform','source_url':'https://wx1.sinaimg.cn/a.png','thumb_path':'images/a.png','large_path':'images/a.png','download_status':'saved'}])
        save(self.root/'records.json',[record]); before=path.read_bytes(); unused_before=unused.read_bytes()
        result=recompress(self.root,quality=84,max_dimension=200)
        self.assertEqual(result['old_files_removed'],0);self.assertEqual(path.read_bytes(),before);self.assertEqual(unused.read_bytes(),unused_before)
        image=load(self.root/'records.json')[0]['images'][0]
        self.assertTrue(image['display_path'].startswith('display-images/'));self.assertTrue((self.root/image['display_path']).exists())
        self.assertEqual(image['large_path'],'images/a.png')

    def test_basic_journal_needs_no_scene_profile_music_or_wishes(self):
        fixture(self.root)
        data=prepare(self.root,'paper')
        self.assertTrue(data['story']['plans']);self.assertNotIn('scene',data['story']);self.assertNotIn('bgm',data['story'])


if __name__=='__main__':unittest.main()
