"""Regression for observed pagination failures and standalone media delivery."""
import json
import io
import tempfile
import unittest
from pathlib import Path
from archive_pipeline import initialize
from archive_common import save,load
from collect_weibo import collect_pages,collect_snapshot,configure_desktop,page_expression
from prepare_music import prepare,validate_audio
from pack_html import pack,verify_packed
from build_journal import build
from test_build_journal import fixture

class Browser:
    def __init__(self,pages): self.pages=iter(pages);self.calls=[]
    def js(self,expression): self.calls.append(expression);return next(self.pages)

def page(rows):return {'success':True,'payload':{'ok':1,'data':{'cards':rows}}}
def record(rid):return {'mblog':{'idstr':rid,'user':{'idstr':'123'},'created_at':'2025-05-19T12:00:00+08:00','text':'test','pics':[]}}

class ReliabilityTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'source';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()
    def configured(self):
        initialize(self.root,'123','https://weibo.com/u/123','2025-01-01','2025-12-31')
        selectors={key:'#'+key for key in ['root','cards','author','text','time','permalink','images','logged_in','logged_out','original_filter']}
        configure_desktop(Browser([self.snapshot([])]),self.root,selectors)
    def snapshot(self,rows):return {'success':True,'source_url':'https://weibo.com/u/123','observed_count':len(rows),'records':rows}
    def observation(self,rid):
        from weibo_web import mid_to_bid
        return {'observed_id':rid,'author_uid':'123','is_original':True,'url':'https://weibo.com/123/'+mid_to_bid(rid),'raw_time':'2025-05-19 12:00','text':'test','images':[]}
    def test_sparse_desktop_snapshots_resume_without_mobile_api(self):
        self.configured();b=Browser([self.snapshot([self.observation('1')]),self.snapshot([self.observation('2')]),self.snapshot([self.observation('3')])])
        for now in [0,5,10]:result=collect_snapshot(b,self.root,clock=lambda:now)
        self.assertEqual(result['candidate_count'],3)
        self.assertEqual(len(load(self.root/'candidates.json')),3)
        with self.assertRaises(ValueError):page_expression('123',1)
    def test_failed_snapshot_is_latched_and_never_becomes_empty(self):
        self.configured();b=Browser([{'success':False,'reason':'site_verification_required'}]);self.assertEqual(collect_snapshot(b,self.root,clock=lambda:0)['status'],'handoff')
        self.assertEqual(collect_snapshot(b,self.root,clock=lambda:1000)['status'],'handoff');self.assertEqual(len(b.calls),1)
        self.assertTrue(load(self.root/'desktop-state.json')['blocked']);self.assertFalse((self.root/'coverage.json').exists())
    def test_empty_snapshots_require_visible_boundary_verification(self):
        self.configured();b=Browser([self.snapshot([]),self.snapshot([])])
        self.assertEqual(collect_snapshot(b,self.root,clock=lambda:0)['status'],'ready')
        self.assertEqual(collect_snapshot(b,self.root,clock=lambda:5)['status'],'verify_boundary');self.assertEqual(len(b.calls),2)
    def test_setup_and_pacing_prevent_unlogged_and_nested_requests(self):
        initialize(self.root,'123','https://weibo.com/u/123','2025-01-01','2025-12-31');b=Browser([])
        self.assertEqual(collect_pages(b,self.root)['status'],'setup_required');self.assertFalse(b.calls)
        save(self.root/'desktop-collection.json',{'uid':'123','selectors':{},'minimum_interval':4})
        save(self.root/'desktop-state.json',{'uid':'123','snapshots':[],'next_allowed_at':20})
        self.assertEqual(collect_snapshot(b,self.root,clock=lambda:10)['status'],'cooldown');self.assertFalse(b.calls)
    def test_licensed_download_is_validated_and_registered(self):
        fixture(self.root)
        class Response(io.BytesIO):
            def geturl(self):return 'https://incompetech.com/music/royalty-free/mp3-royaltyfree/Dream%20Culture.mp3'
        class Opener:
            def open(self,req,timeout):return Response(b'ID3'+b'X'*2000)
        result=prepare(self.root,opener=Opener(),source='licensed')
        self.assertEqual(result['bgm']['origin'],'licensed')
        self.assertEqual(result['bgm']['title'],'Dream Culture')
        self.assertTrue(result['bgm']['sha256'])
    def test_offline_music_and_moved_html(self):
        fixture(self.root);r=prepare(self.root,offline=True);self.assertEqual(validate_audio((self.root/r['bgm']['path']).read_bytes()),'wav')
        self.assertEqual(prepare(self.root,offline=True)['status'],'preserved')
        output=Path(self.temp.name)/'built';build(self.root,output,'paper');target=Path(self.temp.name)/'moved.html';pack(output,target)
        self.assertTrue(verify_packed(target)['ok']);self.assertIn('data:audio/',target.read_text())
        with self.assertRaises(ValueError):pack(output,target)
        with self.assertRaises(ValueError):validate_audio(b'<html>'+b'X'*2000)

if __name__=='__main__':unittest.main()
