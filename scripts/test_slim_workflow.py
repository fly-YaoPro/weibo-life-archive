"""4.4.0 behavior regressions using synthetic sources, fake transport and no browsers."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from archive_common import load, save
from archive_pipeline import initialize, normalize
from collect_weibo import collect_mobile, configure_mobile
from detail_media import supplement_inventory
from experience import validate_narrative
from finalize_delivery import finalize, make_receipt
from journal_run import run
from prepare_art_direction import objects_for
from story_tools import compile_draft
from test_download_transport import FakeBu, Clock, raw_page, mblog, UID, WINDOW
from test_detail_media import detail_envelope
import test_runtime_contract as runtime_fixture


class SlimPipelineTests(unittest.TestCase):
    def setUp(self):
        self.case = runtime_fixture.RuntimeContractTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.root = self.case.root
        self.base = self.root.parent

    def mutate(self, fn):
        story=load(self.root/'story.json'); fn(story); save(self.root/'story.json',story)

    def test_mixed_scripts_long_fields_and_one_wish_pass_both_skins_without_browser(self):
        rows=load(self.root/'records.json');rows[0]['text']+=' 這是句號，也是新開始。';save(self.root/'records.json',rows)
        def change(story):
            story['evidence']=[{'source_id':'demo-1','quote':'這是句號，也是新開始。'}]
            story['overview'].update(headline='完整标题'*12,text='这是句号，也是新开始。'*30,opening='开场白。'*40)
            story['overview']['portrait']['text']='这些记录中的日常。'*30
            story['share']['letter_text']='一段未来来信。'*50
            story['wishes']=story['wishes'][:1]
            for section in story['themes']:section.pop('evidence',None)
        self.mutate(change)
        with patch.dict(sys.modules, {'playwright':None}), patch('webbrowser.open',side_effect=AssertionError('browser forbidden')):
            result=run(self.root,self.base/'runs',skins=['paper','frosted'])
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(result['artifacts']),2)
        self.assertTrue(all(a['contract_verified'] and not a['browser_qa_required'] for a in result['artifacts']))
        self.assertFalse(result['browser_interactions_verified'])
        self.assertEqual(load(self.root/'story.json')['overview']['text'],'这是句号，也是新开始。'*30)

    def test_no_evidence_bank_or_copied_anchors_needed(self):
        def change(s):
            s.pop('evidence',None)
            for t in s['themes']:t.pop('evidence',None)
        self.mutate(change)
        result=run(self.root,self.base/'runs')
        self.assertTrue(result['ok'],result)

    def test_compilation_derives_hotspots_and_letter_sources_before_shape_validation(self):
        def change(s):
            s['scene'].pop('source_ids')
            s['scene']['hotspots']=[{'object_index':0,'x':40,'y':50,'target':'t1'}]
            s['letter'].pop('image_source_ids')
        self.mutate(change)
        result=run(self.root,self.base/'runs')
        self.assertTrue(result['ok'],result)
        s=load(self.root/'story.json');h=s['scene']['hotspots'][0]
        self.assertEqual(h['target'],{'view':'review','theme_id':'t1'})
        self.assertEqual(h['source_ids'],['demo-1'])
        self.assertEqual(h['object_name'],'薄荷')
        self.assertEqual(s['letter']['image_source_ids'],['demo-1'])

    def test_bad_quote_and_bad_navigation_still_block_before_artifacts(self):
        original=load(self.root/'story.json')
        for mutate in (lambda s:s['evidence'][0].update(quote='伪造原话'),
                       lambda s:s['scene']['hotspots'][0].update(target='missing-theme')):
            s=copy.deepcopy(original);mutate(s);save(self.root/'story.json',s)
            result=run(self.root,self.base/'runs')
            self.assertFalse(result['ok'],result)
            self.assertEqual(result['artifacts'],[])
        self.assertFalse((self.base/'runs').exists())

    def test_local_delivery_cli_requires_no_qa_or_receipt_file(self):
        meta=load(self.root/'project_meta.json');meta['presentation']['local_only']=True;save(self.root/'project_meta.json',meta)
        result=run(self.root,self.base/'runs');self.assertTrue(result['ok'],result)
        args=[sys.executable,'-B',str(Path(__file__).with_name('finalize_delivery.py')),
              '--run-dir',result['run_dir'],'--status','local_only']
        proc=subprocess.run(args,check=True,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(json.loads(proc.stdout)['status'],'complete')
        report=load(Path(result['run_dir'])/'run-report.json')
        self.assertFalse(report['browser_interactions_verified'])
        self.assertEqual(report['delivery']['browser_qa'],'not_requested')
        template=load(Path(result['run_dir'])/'delivery-receipt-template.json')
        self.assertNotIn('browser_qa',template['artifacts'][0])
        self.assertNotIn('online_qa',template['artifacts'][0]['deployment'])

    def test_finished_host_receipt_completes_without_opening_url(self):
        result=run(self.root,self.base/'runs')
        receipt=make_receipt(result['run_dir'],'deployed','https://example.invalid/synthetic','finished','synthetic hosting response')
        with patch('webbrowser.open',side_effect=AssertionError('browser forbidden')):
            delivery=finalize(result['run_dir'],receipt)
        self.assertEqual(delivery['verification_basis'],'static_contract_and_hosting_tool')
        self.assertEqual(delivery['artifacts'][0]['value'],'https://example.invalid/synthetic')
        self.assertFalse(load(Path(result['run_dir'])/'run-report.json')['browser_interactions_verified'])

    def test_compiler_does_not_rewrite_original_quotes(self):
        records=load(self.root/'records.json');records[0]['text']+='\n繁體句號。';save(self.root/'records.json',records)
        start=records[0]['text'].index('繁體')
        out=compile_draft(self.root,{'evidence':[{'source_id':'demo-1','quote_span':[start,start+5]}]})
        self.assertEqual(out['evidence'][0]['quote'],'繁體句號。')
        self.assertNotIn('supports',out['evidence'][0])


class SlimEditorialTests(unittest.TestCase):
    def test_multisource_object_does_not_require_identical_evidence_in_all_posts(self):
        rows={'a':{'text':'窗台有一盆薄荷。'},'b':{'text':'窗边放着一本旧书。'}}
        obj={'name':'窗边静物','evidence':'一盆薄荷','source_ids':['a','b'],'placement':'窗边',
             'representation':'symbolic','rationale':'组合两条记录中的意象',
             'source_evidence':{'a':'一盆薄荷','b':'一本旧书'}}
        self.assertEqual(objects_for([obj],rows)[0]['source_ids'],['a','b'])
        obj['source_evidence']['b']='伪造原话'
        with self.assertRaisesRegex(ValueError,'source_evidence'):objects_for([obj],rows)

    def test_traditional_quote_with_simplified_prose_needs_no_support_terms(self):
        rows=[{'id':'a','text':'緣份讓我們相遇亂世以外。'}]
        story={'overview':{'text':'缘分让我们相遇。','source_ids':['a']},
               'themes':[{'id':'t','title':'乱世以外','text':'回望相遇的日子。','source_ids':['a']}],
               'evidence':[{'source_id':'a','quote':rows[0]['text']}]}
        self.assertFalse(validate_narrative(story,rows,True)['keyword_matching_required'])


class SlimCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);initialize(self.root,UID,'https://weibo.com/u/'+UID,*WINDOW)

    def test_two_second_default_and_larger_deadline_bounded_batches(self):
        fake=FakeBu({n:raw_page([mblog(n)]) for n in range(1,12)});self.addCleanup(fake.cleanup)
        configure_mobile(fake,self.root)
        self.assertEqual(load(self.root/'mobile-collection.json')['minimum_interval'],2)
        clock=Clock()
        result=collect_mobile(fake,self.root,max_pages=11,deadline_seconds=60,clock=clock.time,sleep=clock.sleep)
        self.assertEqual(result['processed_pages'],11,result)
        self.assertEqual(result['oldest'],'2025-01-01')
        self.assertEqual(result['newest'],'2025-01-01')
        self.assertEqual(clock.now,20)

    def test_intervals_below_four_are_configurable_invalid_numbers_rejected(self):
        fake=FakeBu();self.addCleanup(fake.cleanup)
        for invalid in (-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):configure_mobile(fake,self.root,minimum_interval=invalid)
        configure_mobile(fake,self.root,minimum_interval=0.5)
        self.assertEqual(load(self.root/'mobile-collection.json')['minimum_interval'],0.5)

    def test_pending_cooldown_does_not_sleep_past_batch_deadline(self):
        fake=FakeBu({1:raw_page([mblog(1)])});self.addCleanup(fake.cleanup)
        configure_mobile(fake,self.root)
        state=load(self.root/'mobile-state.json');state['next_allowed_at']=45;save(self.root/'mobile-state.json',state)
        clock=Clock()
        result=collect_mobile(fake,self.root,max_pages=30,deadline_seconds=5,clock=clock.time,sleep=clock.sleep)
        self.assertEqual(result['status'],'cooldown')
        self.assertEqual(clock.now,0)
        self.assertEqual(fake.download_calls,[])

    def test_progress_dates_distinguish_pinned_posts_from_ordinary_posts(self):
        fake=FakeBu({1:raw_page([mblog(1,date='2010-01-01T12:00:00+08:00',top=True),
                                mblog(2,date='2025-06-01T12:00:00+08:00')])});self.addCleanup(fake.cleanup)
        configure_mobile(fake,self.root)
        clock=Clock()
        result=collect_mobile(fake,self.root,max_pages=1,clock=clock.time,sleep=clock.sleep)
        self.assertEqual(result['oldest'],'2010-01-01')
        self.assertEqual(result['last_pages'][0]['ordinary_oldest'],'2025-06-01')


class ExtendBu:
    def __init__(self,root,env,extended):self.root=root;self.env=env;self.extended=extended;self.calls=[]
    def download(self,url,filename=None,timeout=30):
        self.calls.append(url)
        data=self.extended if '/extend?' in url else self.env
        path=self.root/filename;path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        return {'path':str(path)}


class ExtendedTextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);uid='1705586121'
        initialize(self.root,uid,'https://weibo.com/u/'+uid,'2016-11-02','2026-11-02')
        self.env=detail_envelope(5001,1);self.env['data']['isLongText']=True
        self.record,_=normalize(self.env['data'],uid);save(self.root/'records.json',[self.record])

    def test_pending_text_extended_in_same_inventory_call_and_evidence_saved(self):
        fake=ExtendBu(self.root,self.env,{'ok':1,'data':{'longTextContent':'完整繁體句號。<br/>第二行 &amp; 後續。'}})
        result=supplement_inventory(fake,self.root)
        self.assertEqual(result['errors'],[])
        row=load(self.root/'records.json')[0]
        self.assertEqual(row['text'],'完整繁體句號。\n第二行 & 後續。')
        self.assertEqual(row['text_status'],'complete')
        evidence=load(self.root/row['text_basis'])
        self.assertIn('longTextContent',evidence['data'])
        self.assertEqual(len(fake.calls),2)
        self.assertEqual(len(row['images']),1)

    def test_extend_failure_keeps_pending_and_completed_media(self):
        for data in ({'ok':0},{'ok':1,'data':{}},{'ok':1,'data':{'id':'other','longTextContent':'正文'}}):
            with self.subTest(data=data):
                save(self.root/'records.json',[self.record])
                result=supplement_inventory(ExtendBu(self.root,self.env,data),self.root)
                self.assertTrue(result['errors'])
                row=load(self.root/'records.json')[0]
                self.assertEqual(row['text_status'],'pending')
                self.assertEqual(row['text'],self.record['text'])
                self.assertEqual(row['image_inventory_status'],'complete')


if __name__ == '__main__':unittest.main()
