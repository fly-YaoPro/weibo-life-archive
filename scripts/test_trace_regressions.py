"""Offline reproductions of failures from the 2026-11-02 21:43 run; synthetic data only."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from archive_common import load, save
from archive_pipeline import select, initialize, ingest
from build_journal import prepare
from collect_weibo import collect_mobile, configure_mobile
from detail_media import supplement_inventory, fetch_detail_mblog
from experience import validate_narrative
from finalize_delivery import finalize, CHECKS
from journal_run import run
from project_lock import project_lock
from story_preflight import check_story_project
from test_build_journal import fixture
from test_download_transport import FakeBu, Clock, raw_page, mblog, UID, WINDOW
from test_detail_media import FakeBu as DetailBu, detail_envelope
from test_narrative import fixture as narrative_fixture


class CollectionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'source'
        initialize(self.root, UID, 'https://weibo.com/u/'+UID, *WINDOW)
        self.clock = Clock()

    def tearDown(self): self.temp.cleanup()

    def collect(self, bu, **kwargs):
        return collect_mobile(bu, self.root, clock=self.clock.time, sleep=self.clock.sleep, **kwargs)

    def test_mixed_foreign_card_is_skipped_without_altering_raw_or_refetching_cache(self):
        raw = raw_page([mblog(1), mblog(2, uid='999'), mblog(3)])
        fake=FakeBu({1:raw});self.addCleanup(fake.cleanup)
        configure_mobile(fake,self.root)
        result=self.collect(fake,max_pages=1)
        self.assertEqual((result['status'],result['candidate_count']),('ready',2))
        self.assertEqual((self.root/'mobile-pages/000001.json').read_bytes(), raw)
        self.assertEqual(load(self.root/'mobile-state.json')['pages'][0]['skipped_foreign_cards'],
                         [{'id':'1002','author_uid':'999','reason':'foreign_author_card'}])
        self.assertNotIn('1002',{r['id'] for r in load(self.root/'candidates.json')})
        state=load(self.root/'mobile-state.json');state['next_page']=1;save(self.root/'mobile-state.json',state)
        self.assertEqual(self.collect(fake,max_pages=1)['cache_hits'],1)
        self.assertEqual(len(fake.download_calls),1)

    def test_checkpoint_survives_interruption_during_later_page(self):
        fake=FakeBu({1:raw_page([mblog(1)]),2:raw_page([mblog(2)])});self.addCleanup(fake.cleanup)
        configure_mobile(fake,self.root)
        original=fake.download
        def download(url, **kwargs):
            if url.endswith('page=2'): raise KeyboardInterrupt('simulated tool termination')
            return original(url, **kwargs)
        fake.download=download
        with self.assertRaises(KeyboardInterrupt): self.collect(fake,max_pages=2)
        self.assertEqual(load(self.root/'mobile-state.json')['next_page'],2)
        self.assertEqual(len(load(self.root/'mobile-transport.json')),1)
        fake.download=original
        self.assertEqual(self.collect(fake,max_pages=1)['candidate_count'],2)

    def test_overlapping_call_is_busy_and_does_not_download(self):
        fake=FakeBu({1:raw_page([mblog(1)])});self.addCleanup(fake.cleanup)
        configure_mobile(fake,self.root)
        with project_lock(self.root/'.mobile-collection.lock'):
            self.assertEqual(self.collect(fake,max_pages=1)['status'],'busy')
        self.assertFalse(fake.download_calls)
        self.assertEqual(self.collect(fake,max_pages=1)['status'],'ready')

    def test_ratings_mapping_and_all_unknown_ids_are_diagnosed_before_write(self):
        ingest(self.root, {'cards':[{'mblog':mblog(1)}]})
        select(self.root, {'1001':{'score':8,'reason':'已读过的测试片段'}})
        before=(self.root/'selection.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'9001.*9002'):
            select(self.root, [{'id':'9001','score':9,'reason':'test'},{'id':'9002','score':8,'reason':'test'}])
        self.assertEqual((self.root/'selection.json').read_bytes(),before)


class StoryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'source';self.root.mkdir()
        fixture(self.root)
        meta=load(self.root/'project_meta.json');meta['target']['profile_url']='https://weibo.com/u/synthetic';save(self.root/'project_meta.json',meta)
        records=load(self.root/'records.json');records[0].update(author_uid='synthetic', selected=True, url='https://example.invalid/demo-1');save(self.root/'records.json',records)

    def tearDown(self): self.temp.cleanup()

    def test_optional_supports_accept_script_differences_and_single_characters(self):
        story,rows,_=narrative_fixture();story['evidence'][0]['supports']=['薄']
        story['themes'][0].pop('evidence')
        issues=[];validate_narrative(story,rows,True,errors=issues)
        self.assertEqual(issues,[])
        self.assertFalse(validate_narrative(story,rows,True)['keyword_matching_required'])

    def test_shape_errors_are_collected_before_builder_attribute_errors(self):
        story=load(self.root/'story.json')
        story['themes'][0]['image_captions']=['wrong shape']
        story['share']={'entries':[{'source_id':['demo-1'],'text':{'bad':'type'}}]}
        story['scene']={'hotspots':[{'label':'test','target':'review'}]}
        save(self.root/'story.json',story)
        result=check_story_project(self.root);errors='\n'.join(result['errors'])
        for path in ('$.themes[0].image_captions','$.share.entries[0].source_id',
                     '$.share.entries[0].text','$.scene.hotspots[0].source_ids'):
            self.assertIn(path,errors)
        with self.assertRaisesRegex(ValueError,'image_captions'):prepare(self.root,'paper')

    def test_pending_full_text_blocks_actual_build(self):
        rows=load(self.root/'records.json');rows[0]['text_status']='pending';save(self.root/'records.json',rows)
        with self.assertRaisesRegex(ValueError,'full text pending.*demo-1'):prepare(self.root,'paper')

    def test_default_runner_embeds_music_and_preserves_it_on_repeat(self):
        with patch('urllib.request.build_opener',side_effect=AssertionError('network forbidden')):
            result=run(self.root,self.base/'runs')
        self.assertTrue(result['ok'],result)
        music=load(self.root/'story.json')['bgm'];audio=(self.root/music['path']).read_bytes()
        self.assertGreater(len(audio),1024)
        html=Path(result['artifacts'][0]['html']).read_text(encoding='utf-8')
        self.assertIn('audio/warm-lights.wav',html);self.assertIn('data:audio/',html)
        self.assertEqual(run(self.root,self.base/'runs')['music']['status'],'preserved')
        self.assertEqual((self.root/music['path']).read_bytes(),audio)

    def test_explicit_music_optout(self):
        meta=load(self.root/'project_meta.json');meta['presentation']={'bgm_enabled':False};save(self.root/'project_meta.json',meta)
        result=run(self.root,self.base/'runs')
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['music']['status'],'disabled_by_user')
        self.assertNotIn('bgm',load(self.root/'story.json'))

    def test_index_reuse_and_refresh_returns_current_file_without_overwriting_old(self):
        script=Path(__file__).parent/'story_tools.py';index=self.base/'index.json'
        args=[sys.executable,'-B',str(script),str(self.root),'index','--output',str(index)]
        first=subprocess.run(args,check=True,capture_output=True,text=True,encoding='utf-8')
        old=index.read_bytes()
        same=json.loads(subprocess.run(args,check=True,capture_output=True,text=True,encoding='utf-8').stdout)
        self.assertEqual(same['output'],str(index))
        rows=load(self.root/'records.json');rows[0]['text']+=' New source text.';save(self.root/'records.json',rows)
        changed=json.loads(subprocess.run(args,check=True,capture_output=True,text=True,encoding='utf-8').stdout)
        self.assertNotEqual(changed['output'],str(index));self.assertEqual(index.read_bytes(),old)
        self.assertIn('New source text',load(changed['output'])['records'][0]['text'])

    def test_delivery_needs_static_hash_and_host_result_but_no_browser_fields(self):
        result=run(self.root,self.base/'runs');path=Path(result['artifacts'][0]['html'])
        row={'html':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'deployment':{'status':'pending'}}
        with self.assertRaisesRegex(ValueError,'pending'):finalize(result['run_dir'],{'artifacts':[row]})
        row['deployment']={'status':'failed','reason':'synthetic host failure','evidence':'synthetic tool response'}
        row['sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'different HTML'):finalize(result['run_dir'],{'artifacts':[row]})
        row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(finalize(result['run_dir'],{'artifacts':[row]})['artifacts'][0]['type'],'html')
        row['deployment']={'status':'deployed','url':'https://example.invalid/test','evidence':'synthetic receipt','release_status':'publishing'}
        with self.assertRaisesRegex(ValueError,'finished'):finalize(result['run_dir'],{'artifacts':[row]})
        row['deployment']['release_status']='finished'
        self.assertEqual(finalize(result['run_dir'],{'artifacts':[row]})['artifacts'][0]['type'],'url')
        self.assertFalse(load(Path(result['run_dir'])/'run-report.json')['browser_interactions_verified'])
        path.write_bytes(path.read_bytes()+b'changed')
        row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'changed after'):finalize(result['run_dir'],{'artifacts':[row]})


class DetailRegressionTests(unittest.TestCase):
    def test_detail_cannot_lower_prior_photo_denominator(self):
        from detail_media import supplement_record
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);uid='1705586121';initialize(root,uid,'https://weibo.com/u/'+uid,'2016-11-02','2026-11-02')
            from archive_pipeline import normalize
            record,_=normalize(detail_envelope(5001,3)['data'],uid);save(root/'records.json',[record])
            before=(root/'records.json').read_bytes()
            fake=DetailBu({'5001':detail_envelope(5001,1)});self.addCleanup(fake.cleanup)
            with self.assertRaisesRegex(ValueError,'below prior'):supplement_record(fake,root,'5001')
            self.assertEqual((root/'records.json').read_bytes(),before)

    def test_expanded_page_text_merge_preserves_media_and_logs_evidence(self):
        from detail_media import supplement_text_from_page
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);uid='1705586121';initialize(root,uid,'https://weibo.com/u/'+uid,'2016-11-02','2026-11-02')
            from archive_pipeline import normalize
            record,_=normalize(detail_envelope(5001,1)['data'],uid);record['text_status']='pending';save(root/'records.json',[record])
            captured={**record,'text':'hello full expanded text','images':[]}
            with patch('browser_helpers.capture_detail', return_value=captured):
                with self.assertRaisesRegex(ValueError,'展开'):supplement_text_from_page(None,root,'5001',{})
                result=supplement_text_from_page(None,root,'5001',{},expanded=True)
            saved=load(root/'records.json')[0]
            self.assertEqual(saved['images'],record['images'])
            self.assertEqual(saved['text_status'],'complete')
            self.assertTrue((root/result['evidence']).is_file())

    def test_integer_detail_id_and_text_gap_auto_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);uid='1705586121'
            initialize(root,uid,'https://weibo.com/u/'+uid,'2016-11-02','2026-11-02')
            env=detail_envelope(5001,0);env['data']['id']=5001
            env['data'].pop('pics')  # explicit pic_num=0 is a real empty inventory
            fake=DetailBu({'5001':env});self.addCleanup(fake.cleanup)
            self.assertEqual(fetch_detail_mblog(fake,uid,'5001')['id'],5001)
            from archive_pipeline import normalize
            record,_=normalize(env['data'],uid);record['text_status']='pending';save(root/'records.json',[record])
            result=supplement_inventory(fake,root)
            self.assertEqual(result['processed'],1,result)
            self.assertEqual(load(root/'records.json')[0]['text_status'],'complete')

    def test_still_collapsed_detail_never_claims_full_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);uid='1705586121';initialize(root,uid,'https://weibo.com/u/'+uid,'2016-11-02','2026-11-02')
            env=detail_envelope(5001,0);env['data']['isLongText']=True
            from archive_pipeline import normalize
            record,_=normalize(env['data'],uid);save(root/'records.json',[record])
            fake=DetailBu({'5001':env});self.addCleanup(fake.cleanup)
            self.assertEqual(supplement_inventory(fake,root)['results'][0]['text_status'],'pending')
            self.assertEqual(load(root/'records.json')[0]['text_status'],'pending')


if __name__ == '__main__': unittest.main()
