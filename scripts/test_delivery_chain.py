"""Offline execution-chain tests: fake hosting, real build/pack/budget, no browsers."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from archive_common import load, save
from check_project import check
from journal_run import run, deliver
from publish_journal import publish
from story_preflight import check_story_project
from prepare_art_direction import prepare as art_prepare
from test_build_journal import fixture
from manage_media import download, plan, compression_summary
from test_incremental import Response, image


class Host:
    def __init__(self,legacy=False,status='finished',failure=None):
        self.calls=[];self.legacy=legacy;self.status=status;self.failure=failure
    def __call__(self,args,cwd):
        self.calls.append((args,cwd))
        if args[0]=='git': return 'index.html\n' if 'diff' in args else ''
        op=args[2]
        if op=='--help':return '  +deploy   Upload static directory\n' if self.legacy else '  +init   Init\n'
        if self.failure==op:raise OSError('synthetic hosting failure at '+op)
        if op=='+create': data={'app':{'app_id':'app_synthetic'}}
        elif op=='+init':
            (Path(cwd)/args[args.index('--dir')+1]/'.git').mkdir(parents=True)
            data={}
        elif op=='+file-upload':data={'url':'https://example.invalid/assets/'+args[args.index('--file')+1]}
        elif op in {'+deploy','+release-create'}:data={'release_id':'release_synthetic','status':'publishing'}
        elif op=='+release-get':
            data={'release':{'release_id':'release_synthetic','status':self.status,
                             'online_url':'https://example.invalid/published'}}
            if self.status=='pending':data['release']['current_node_info']={'current_status':'PENDING'}
        else:data={}
        return json.dumps({'ok':True,'data':data})


class DeliveryChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'source';self.root.mkdir();fixture(self.root)
        meta=load(self.root/'project_meta.json');meta['target']['profile_url']='https://weibo.com/u/synthetic';save(self.root/'project_meta.json',meta)
        rows=load(self.root/'records.json');rows[0].update(author_uid='synthetic',selected=True,url='https://example.invalid/synthetic-post');save(self.root/'records.json',rows)

    def publisher(self,host):
        return lambda source,folder,artifact:publish(source,folder,artifact,runner=host,cli='fake-lark',sleep=lambda _:None,wait_seconds=0)

    def test_current_cli_build_upload_push_poll_and_finalize_are_one_chain(self):
        host=Host()
        result=deliver(self.root,self.base/'runs',publisher=self.publisher(host))
        self.assertTrue(result['ok'],result);self.assertTrue(result['delivery_complete'])
        self.assertEqual(result['delivery']['artifacts'][0]['type'],'url')
        ops=[a[0][2] for a in host.calls if a[0][0]=='fake-lark']
        for op in ('+create','+init','+file-upload','+release-create','+release-get'):self.assertIn(op,ops)
        self.assertFalse(result['browser_interactions_verified'])
        state=load(self.root/'deployment-state.json')['paper'];repo=Path(state['repo'])
        assets=(repo/'journal-assets.js').read_text(encoding='utf-8')
        self.assertIn('https://example.invalid/assets/',assets);self.assertNotIn('base64,',assets)
        self.assertFalse((repo/'audio').exists());self.assertFalse((repo/'records.json').exists())
        self.assertTrue(any('push' in a for a,_ in host.calls))
        self.assertIsNone(result['artifacts'][0]['publish_budget_ok'])

    def test_older_directory_deploy_cli_is_used_only_if_available(self):
        host=Host(legacy=True)
        result=deliver(self.root,self.base/'runs',publisher=self.publisher(host))
        self.assertTrue(result['delivery_complete'])
        args=next(a for a,_ in host.calls if '+deploy' in a)
        self.assertIn('--dir',args)
        self.assertFalse(any('+init' in a for a,_ in host.calls))

    def test_pending_release_never_completes_and_resume_never_creates_again(self):
        host=Host(status='pending')
        first=deliver(self.root,self.base/'runs',publisher=self.publisher(host))
        self.assertFalse(first['ok']);self.assertFalse(first['delivery_complete'])
        self.assertEqual(first['status'],'deployment_pending')
        self.assertFalse((Path(first['run_dir'])/'delivery-receipt.json').exists())
        before=len(host.calls);host.status='finished'
        resumed=deliver(resume_run=first['run_dir'],publisher=self.publisher(host))
        self.assertTrue(resumed['delivery_complete'])
        self.assertEqual([a[2] for a,_ in host.calls[before:]],['+release-get'])

    def test_real_host_failure_generates_recorded_html_fallback(self):
        host=Host(failure='+file-upload')
        result=deliver(self.root,self.base/'runs',publisher=self.publisher(host))
        self.assertTrue(result['delivery_complete']);self.assertFalse(result['live_deployment_verified'])
        item=result['delivery']['artifacts'][0]
        self.assertEqual(item['type'],'html');self.assertIn('synthetic hosting failure',item['reason'])
        self.assertTrue((Path(result['run_dir'])/'publish-paper.json').is_file())

    def test_explicit_local_only_never_calls_publisher(self):
        meta=load(self.root/'project_meta.json');meta['presentation']={'local_only':True};save(self.root/'project_meta.json',meta)
        def forbidden(*a):raise AssertionError('hosting must not be called')
        result=deliver(self.root,self.base/'runs',publisher=forbidden)
        self.assertTrue(result['delivery_complete'])
        self.assertEqual(result['delivery']['artifacts'][0]['reason'],'user_requested_local_only')

    def test_budget_changes_only_delivery_copies_and_updates_all_references(self):
        meta=load(self.root/'project_meta.json');meta['presentation']={'bgm_enabled':False};save(self.root/'project_meta.json',meta)
        folder=self.root/'images';folder.mkdir();path=folder/'original.jpg'
        Image.effect_noise((2000,1600),70).convert('RGB').save(path,'JPEG',quality=95)
        original=path.read_bytes()
        rows=load(self.root/'records.json');rows[0].update(expected_image_count=1,image_inventory_status='complete',
            image_count_basis='Explicit synthetic inventory',images=[{'image_id':'synthetic','origin':'user_provided',
            'provided_reference':'explicit synthetic test','download_status':'saved','thumb_path':'images/original.jpg','large_path':'images/original.jpg'}])
        save(self.root/'records.json',rows)
        story=load(self.root/'story.json');story['overview'].update(image_paths=['images/original.jpg'],image_captions={'images/original.jpg':'合成图'});save(self.root/'story.json',story)
        result=run(self.root,self.base/'runs',book_max_mb=0.3)
        self.assertTrue(result['ok'],result)
        budget=result['artifacts'][0]['media_budget']
        self.assertTrue(budget['target_met'],budget);self.assertGreater(budget['saved_bytes'],0)
        self.assertLessEqual(len(budget['passes']),2)
        self.assertEqual(path.read_bytes(),original)
        built=Path(result['artifacts'][0]['built_dir']);new=load(built/'records.json')[0]['images'][0]['large_path']
        self.assertNotEqual(new,'images/original.jpg')
        self.assertEqual(load(built/'story.json')['overview']['image_paths'],[new])
        self.assertTrue(check(built,'weibo','final')['ok'])
        self.assertTrue(check(result['artifacts'][0]['html'],'weibo','final')['ok'])

    def test_missing_story_reports_exact_expected_path(self):
        nested=self.root/'story';nested.mkdir();(self.root/'story.json').rename(nested/'story.json')
        result=run(self.root,self.base/'runs')
        self.assertFalse(result['ok']);self.assertIn(str(self.root/'story.json'),result['errors'][0])
        self.assertIn('nested',result['errors'][0])

    def test_diagnostic_compiles_shorthand_without_mutating_source(self):
        story=load(self.root/'story.json');story['themes'][0]['excerpt']='窗台的薄荷又长了一片叶子。'
        (self.root/'decorations').mkdir()
        Image.new('RGB',(32,24),'white').save(self.root/'decorations/scene.png')
        story['scene']={'image_path':'decorations/scene.png','alt':'合成场景',
            'objects':[{'name':'薄荷','source_ids':['demo-1'],'evidence':'薄荷','placement':'窗边'}],
            'hotspots':[{'object_index':0,'x':30,'y':40,'target':'t1'}]}
        save(self.root/'story.json',story)
        before=(self.root/'story.json').read_bytes()
        result=check_story_project(self.root)
        self.assertTrue(result['ok'],result)
        self.assertEqual((self.root/'story.json').read_bytes(),before)

    def test_download_compression_statistics_survive_url_cache_reuse(self):
        save(self.root/'records.json',[{'id':'1','images':[image('https://wx1.sinaimg.cn/synthetic.jpg')]}])
        plan(self.root)
        buffer=io.BytesIO();Image.effect_noise((1800,1400),60).convert('RGB').save(buffer,'JPEG',quality=95)
        content=buffer.getvalue()
        class Opener:
            calls=0
            def open(self,req,**kwargs):self.calls+=1;return Response(req.full_url,content)
        opener=Opener()
        first=download(self.root,opener=opener)
        self.assertTrue(first['ok']);stats=first['compression']
        self.assertEqual(stats['known_before_bytes'],len(content));self.assertGreater(stats['saved_bytes'],0)
        second=download(self.root,opener=opener)
        self.assertEqual(second['compression'],stats);self.assertEqual(opener.calls,1)
        self.assertEqual(compression_summary({'old':{'status':'saved','bytes':100}})['unknown_original_urls'],1)

    def test_short_exact_art_evidence_and_different_object_names_are_allowed(self):
        records=load(self.root/'records.json');records[0]['text']+=' 我见过光。';save(self.root/'records.json',records)
        obj={'name':'窗光','source_ids':['demo-1'],'evidence':'见过光','placement':'窗边'}
        plan={'space':'合成工作台','scene_objects':[obj],'letter_objects':[{**obj,'name':'柔光'}]}
        prepared=art_prepare(self.root,plan)
        self.assertEqual(prepared['requests'][0]['objects'][0]['representation'],'symbolic')
        self.assertEqual(len(prepared['requests']),2)

    def test_budget_does_not_drop_assets_when_immutable_audio_exceeds_target(self):
        result=run(self.root,self.base/'runs',book_max_mb=0.0001)
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['artifacts'][0]['media_budget']['target_met'])
        self.assertTrue((Path(result['artifacts'][0]['built_dir'])/'audio/warm-lights.wav').is_file())


if __name__=='__main__':unittest.main()
