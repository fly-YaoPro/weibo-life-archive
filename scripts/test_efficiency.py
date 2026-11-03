"""Offline behavioral checks for 4.2.3; no live Harness/Weibo/hosting claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from archive_common import load, save
from audit_images import audit
from build_journal import build, prepare
from check_project import check
from check_story import check_story
from experience import validate_narrative
from journal_run import run
from pack_html import estimate, pack
from story_preflight import check_story_project
from story_tools import compile_draft, exact_quote, source_index
from test_build_journal import fixture
from test_pipeline import png


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name);self.root=self.base/'source';self.root.mkdir()
        fixture(self.root)
        meta=load(self.root/'project_meta.json');meta['target']['profile_url']='https://weibo.com/u/synthetic';save(self.root/'project_meta.json',meta)
        rows=load(self.root/'records.json');rows[0].update(author_uid='synthetic',selected=True,url='https://example.invalid/demo-1');save(self.root/'records.json',rows)

    def tearDown(self): self.temp.cleanup()

    def photo(self):
        (self.root/'images').mkdir(exist_ok=True)
        (self.root/'images/real.png').write_bytes(png(20,20))
        rows=load(self.root/'records.json')
        rows[0].update(expected_image_count=1,image_count_basis='Explicit synthetic fixture has one photo',
            image_inventory_status='complete',text_status='complete',images=[{'image_id':'photo-1',
            'origin':'user_provided','provided_reference':'Explicit synthetic test fixture',
            'download_status':'saved','thumb_path':'images/real.png','large_path':'images/real.png'}])
        save(self.root/'records.json',rows)
        return rows

    def test_full_preflight_collects_independent_errors_without_mutation(self):
        story=load(self.root/'story.json')
        story['overview']['source_ids']=['missing-overview']
        story['themes'][0]['excerpt']='not an original quotation'
        story['themes'][0]['image_paths']=['images/missing.png']
        story['plans'][0]['source_ids']=['missing-plan']
        story['letter']={'source_ids':['demo-1'],'paragraphs':[],'closing':'','title':''}
        save(self.root/'story.json',story)
        before={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result=check_story_project(self.root)
        self.assertFalse(result['ok']);self.assertFalse(result['build_ready'])
        errors='\n'.join(result['errors'])
        for field in ('overview','themes[0]','plans[0]','未来来信'): self.assertIn(field,errors)
        self.assertEqual(check(self.root,'weibo','story')['errors'],result['errors'])
        self.assertEqual(check_story(self.root)[0],result['errors'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_collector_does_not_weaken_normal_builder_or_grounding(self):
        from test_narrative import fixture as editorial_fixture
        story,rows,_=editorial_fixture()
        story['overview'].update(headline='Synthetic summary',text='This has no source term.')
        story['themes'][0]['source_ids']=['missing']
        issues=[];validate_narrative(story,rows,True,errors=issues)
        self.assertEqual(len(issues),1)
        with self.assertRaises(ValueError):validate_narrative(story,rows,True)

    def test_share_entry_uses_singular_source_id_as_in_runtime_contract(self):
        story=load(self.root/'story.json')
        story['share']={'entries':[{'source_id':'demo-1','source_ids':[], 'title':'片段','text':'来自原帖的一页。'}]}
        save(self.root/'story.json',story)
        result=check_story_project(self.root)
        self.assertTrue(result['ok'],result)

    def test_quote_compilation_preserves_newlines_and_traditional_characters(self):
        rows=self.photo();rows[0]['text']='前言\n句號：舊書。\n結尾';save(self.root/'records.json',rows)
        draft={'evidence':[{'source_id':'demo-1','quote_span':[3,10],'supports':['句號']}],
            'overview':{'source_ids':['demo-1'],'image_refs':[{'source_id':'demo-1','image_index':0}]},
            'scene':{'objects':[{'source_ids':['demo-1']}]},
            'letter':{'source_ids':['demo-1'],'objects':[{'source_ids':['demo-1']}]}}
        original=copy.deepcopy(draft)
        output=compile_draft(self.root,draft)
        self.assertEqual(output['evidence'][0]['quote'],rows[0]['text'][3:10])
        self.assertEqual(output['overview']['image_paths'],['images/real.png'])
        self.assertEqual(output['scene']['source_ids'],['demo-1'])
        self.assertEqual(output['letter']['image_source_ids'],['demo-1'])
        self.assertEqual(draft,original)
        with self.assertRaises(ValueError):exact_quote(rows,'demo-1',0,999)

    def test_compilation_rejects_wrong_owner_and_conflicting_explicit_data(self):
        self.photo()
        with self.assertRaisesRegex(ValueError,'cited'):
            compile_draft(self.root,{'overview':{'source_ids':['other'],'image_refs':[{'source_id':'demo-1','image_index':0}]}})
        with self.assertRaisesRegex(ValueError,'disagrees'):
            compile_draft(self.root,{'evidence':[{'source_id':'demo-1','quote':'fake','quote_span':[0,4]}]})
        output=compile_draft(self.root,{'scene':{'source_ids':['other'],'objects':[{'source_ids':['demo-1']}]}})
        self.assertEqual(output['scene']['source_ids'], ['demo-1'])

    def test_lowered_photo_denominator_is_detected_against_candidate_evidence(self):
        rows=self.photo()
        save(self.root/'candidates.json',[{**rows[0],'expected_image_count':15}])
        result=audit(self.root)
        self.assertFalse(result['ok']);self.assertIn('below observed source count','\n'.join(result['errors']))
        queue=source_index(self.root)['pending']
        self.assertIn('source_image_inventory',queue[0]['reasons'])
        self.assertEqual(queue[0]['observed_source_image_count'],15)
        with self.assertRaises(ValueError):prepare(self.root,'paper')
        self.assertEqual(load(self.root/'records.json')[0]['expected_image_count'],1)

    def test_index_reports_only_actual_missing_items(self):
        rows=self.photo()
        self.assertEqual(source_index(self.root)['pending'],[])
        rows[0]['images'][0]['download_status']='failed';save(self.root/'records.json',rows)
        pending=source_index(self.root)['pending'][0]
        self.assertEqual(pending['failed_image_indexes'],[0])
        self.assertIn('photo_download',pending['reasons'])

    def test_exact_size_estimate_matches_written_utf8_html(self):
        built=self.base/'built';build(self.root,built,'paper')
        before={p.relative_to(built):p.stat().st_size for p in built.rglob('*') if p.is_file()}
        result=estimate(built)
        self.assertEqual(before,{p.relative_to(built):p.stat().st_size for p in built.rglob('*') if p.is_file()})
        packed=pack(built,self.base/'new.html')
        self.assertEqual(result['bytes'],packed['bytes'])
        self.assertFalse(estimate(built,max_mb=0.00001)['ok'])

    def test_runner_defaults_to_one_skin_preserves_old_outputs_and_marks_qa_pending(self):
        first=run(self.root,self.base/'runs')
        self.assertTrue(first['ok'],first)
        self.assertEqual([a['skin'] for a in first['artifacts']],['paper'])
        self.assertFalse(first['live_deployment_verified']);self.assertFalse(first['browser_interactions_verified'])
        old=Path(first['artifacts'][0]['html']).read_bytes()
        second=run(self.root,self.base/'runs',publish_max_mb=0.00001)
        self.assertTrue(second['ok'],second)
        self.assertNotEqual(first['run_dir'],second['run_dir'])
        self.assertEqual(second['status'],'directory_publish_or_html_fallback_required')
        self.assertEqual(Path(first['artifacts'][0]['html']).read_bytes(),old)
        self.assertTrue(Path(second['artifacts'][0]['html']).is_file())
        self.assertTrue(all('seconds' in s for s in second['stages']))

    def test_runner_blocks_bad_story_before_writing_output(self):
        story=load(self.root/'story.json');story['overview']['source_ids']=['missing'];save(self.root/'story.json',story)
        result=run(self.root,self.base/'runs')
        self.assertFalse(result['ok']);self.assertEqual(result['status'],'preflight_failed')
        self.assertFalse((self.base/'runs').exists())

    def test_runner_builds_both_skins_only_when_requested(self):
        result=run(self.root,self.base/'runs',skins=['paper','frosted'])
        self.assertTrue(result['ok'],result)
        self.assertEqual([a['skin'] for a in result['artifacts']],['paper','frosted'])


if __name__=='__main__': unittest.main()
