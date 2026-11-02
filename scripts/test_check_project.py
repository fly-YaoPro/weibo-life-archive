#!/usr/bin/env python3
"""Offline synthetic-fixture regression. No logins, browsers or real user data."""
import copy
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from check_project import check,TITLES

def put(root,name,data):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

def fixture(root,kind):
    meta={'schema_version':1,'platform':kind,'title':TITLES[kind],'mode':'selected','timezone':'Asia/Shanghai','requested_range':{'start':'2026-01-01','end':'2026-12-31'}}
    if kind=='weibo':meta['target']={'uid':'sample-user','profile_url':'https://weibo.com/u/sample-user'}
    put(root,'project_meta.json',meta)
    put(root,'coverage.json',[{'year':2026,'status':'selected','scanned_count':None,'saved_count':1,'selected_count':1}])
    if kind=='weibo':
        records=[{'id':'sample-post','author_uid':'sample-user','created_at':'2026-10-01T12:00:00+08:00','text':'合成离线夹具，不是真实微博。','url':'https://weibo.com/sample-post','selected':True,'images':[], 'expected_image_count':0, 'image_inventory_status':'complete', 'image_count_basis':'Explicit synthetic fixture confirms zero photos'}]
    else:
        records=[{'order_id':'sample-order','placed_at':'2026-10-01T12:00:00+08:00','raw_status':'交易成功','is_success':True,'currency':'CNY','paid_amount':'10.00','refund_amount':None,'amount_basis':'original_paid','url':'https://buyertrade.taobao.com/','items':[{'item_id':'a','name':'合成商品A','quantity':1,'image_path':None,'image_status':'unavailable'},{'item_id':'b','name':'合成商品B','quantity':2,'image_path':None,'image_status':'unavailable'}]}]
    name='records.json' if kind=='weibo' else 'orders.json';put(root,name,records)
    return name,records

class Checks(unittest.TestCase):
    def run_case(self,kind,mutator,expected):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);name,rows=fixture(root,kind);mutator(root,name,rows);r=check(root,kind)
            self.assertEqual(r['ok'],expected,r)
    def test_weibo_valid(self):self.run_case('weibo',lambda *a:None,True)
    def test_image_only_weibo_is_valid(self):
        def mutate(r,n,x):
            x[0]['text']=''
            x[0]['images']=[{'origin':'platform','source_url':'https://example.org/fixture.jpg','download_status':'unavailable','thumb_path':None,'large_path':None}]
            put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_taobao_one_parent_many_items(self):self.run_case('taobao',lambda *a:None,True)
    def test_custom_title_allowed(self):
        def mutate(r,n,x):
            meta=json.loads((r/'project_meta.json').read_text('utf-8'))
            meta['title']='我的周末小事';put(r,'project_meta.json',meta)
        for kind in ('weibo','taobao'):
            with self.subTest(kind=kind):self.run_case(kind,mutate,True)
    def test_empty_title_rejected(self):
        def mutate(r,n,x):
            meta=json.loads((r/'project_meta.json').read_text('utf-8'))
            meta['title']='  ';put(r,'project_meta.json',meta)
        self.run_case('weibo',mutate,False)
    def test_synthetic_weibo_image_rejected(self):
        def mutate(r,n,x):
            x[0]['images']=[{'origin':'ai_generated','download_status':'unavailable','thumb_path':None,'large_path':None}];put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_synthetic_product_image_rejected(self):
        def mutate(r,n,x):x[0]['items'][0]['origin']='cartoon';put(r,n,x)
        self.run_case('taobao',mutate,False)
    def test_platform_image_origin_does_not_excuse_missing_download(self):
        def mutate(r,n,x):
            x[0]['images']=[{'origin':'platform','source_url':'https://example.org/fixture-image.jpg','download_status':'unavailable','thumb_path':None,'large_path':None}];put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_duplicate(self):self.run_case('weibo',lambda r,n,x:put(r,n,x+x),False)
    def test_numeric_id(self):
        def mutate(r,n,x):x[0]['id']=123;put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_wrong_target(self):
        def mutate(r,n,x):x[0]['author_uid']='other-user';put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_naive_date(self):
        def mutate(r,n,x):x[0]['created_at']='2026-10-01T12:00:00';put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_missing_image(self):
        def mutate(r,n,x):x[0]['images']=[{'download_status':'saved','thumb_path':'images/missing.jpg','large_path':'images/missing2.jpg'}];put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_outside_image(self):
        def mutate(r,n,x):x[0]['items'][0].update(image_status='saved',image_path='../outside.jpg');put(r,n,x)
        self.run_case('taobao',mutate,False)
    def test_non_success(self):
        def mutate(r,n,x):x[0]['raw_status']='交易关闭';put(r,n,x)
        self.run_case('taobao',mutate,False)
    def test_float_money(self):
        def mutate(r,n,x):x[0]['paid_amount']=10.0;put(r,n,x)
        self.run_case('taobao',mutate,False)
    def test_unknown_money_stays_unknown(self):
        def mutate(r,n,x):x[0]['paid_amount']=None;x[0]['amount_basis']='unknown';put(r,n,x)
        self.run_case('taobao',mutate,True)
    def test_bad_quantity(self):
        def mutate(r,n,x):x[0]['items'][0]['quantity']=0;put(r,n,x)
        self.run_case('taobao',mutate,False)
    def test_credential_file(self):
        def mutate(r,n,x):put(r,'cookies.json',{})
        self.run_case('weibo',mutate,False)
    def test_missing_final_output(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);fixture(r,'taobao');self.assertFalse(check(r,'taobao','final')['ok'])
    def test_video_without_cover_is_not_discarded(self):
        def mutate(r,n,x):
            x[0].update(text='',is_video=True,video={'source_url':x[0]['url'],'cover_status':'unavailable','covers':[]});put(r,n,x)
        self.run_case('weibo',mutate,True)
    def test_video_cover_source_and_synthetic_provenance_checked(self):
        def mutate(r,n,x):
            x[0].update(is_video=True,video={'source_url':'https://example.org/unrelated','cover_status':'observed','covers':[{'origin':'synthetic','download_status':'unavailable'}]});put(r,n,x)
        self.run_case('weibo',mutate,False)
    def test_synthetic_fixture_media_requires_explicit_title_label_and_reference(self):
        def mutate(r,n,x):
            meta=json.loads((r/'project_meta.json').read_text());meta.update(title='合成演示',fixture={'synthetic':True,'label':'合成测试','source':'existing synthetic demo'});put(r,'project_meta.json',meta)
            x[0]['images']=[{'origin':'synthetic_fixture','provided_reference':'existing explicit synthetic demo','download_status':'unavailable'}];put(r,n,x)
        self.run_case('weibo',mutate,False)
        def unlabeled(r,n,x):
            mutate(r,n,x);meta=json.loads((r/'project_meta.json').read_text());meta['title']='用户手账';put(r,'project_meta.json',meta)
        self.run_case('weibo',unlabeled,False)
    def test_final_rejects_semantic_mutations_beyond_existing_id_attributes(self):
        from build_journal import build
        from test_build_journal import fixture as build_fixture,write
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source';source.mkdir();build_fixture(source)
            # Supply the source-only metadata required by the independent checker.
            meta=json.loads((source/'project_meta.json').read_text());meta['target']['profile_url']='https://weibo.com/u/synthetic';write(source,'project_meta.json',meta)
            records=json.loads((source/'records.json').read_text());records[0].update(author_uid='synthetic',selected=True,url='https://example.invalid/demo');write(source,'records.json',records)
            output=Path(d)/'built';build(source,output,'paper')
            self.assertTrue(check(output,'weibo','final')['ok'])
            story=json.loads((output/'story.json').read_text())
            base=copy.deepcopy(story)
            js=output/'journal-data.js';original_js=js.read_text()
            runtime=json.loads(original_js.split(' = ',1)[1].rstrip(';\n'))
            runtime['story']['themes'].append({**runtime['story']['themes'][0],'id':'runtime-duplicate'})
            js.write_text('window.JOURNAL_DATA = '+json.dumps(runtime,ensure_ascii=False)+';\n')
            result=check(output,'weibo','final');self.assertFalse(result['ok'])
            self.assertTrue(any('journal-data.js' in error and '重复' in error for error in result['errors']))
            js.write_text(original_js)
            for mutation,match in ((lambda s:s['overview'].update(source_ids=[]),'来源'),
                                   (lambda s:s['themes'][0].update(excerpt='凭空编造的原话'),'摘句'),
                                   (lambda s:s.update(wishes=[{'id':'w','title':'测试','text':'测试','source_ids':['missing']}]),'来源'),
                                   (lambda s:s['themes'].append({**s['themes'][0],'id':'duplicate'}),'重复')):
                changed=copy.deepcopy(base);mutation(changed);write(output,'story.json',changed)
                result=check(output,'weibo','final');self.assertFalse(result['ok'],result)
                self.assertTrue(any(match in error for error in result['errors']),result)
            meta['presentation']={'grounding_required':True};write(output,'project_meta.json',meta)
            base['overview']['portrait']={'text':'一位有两个孩子的医生。','source_ids':['demo-1']};write(output,'story.json',base)
            result=check(output,'weibo','final');self.assertFalse(result['ok'])
            self.assertTrue(any('锚点' in error for error in result['errors']))
    def test_packed_html_checks_repetition_in_actual_embedded_data(self):
        from build_journal import build
        from pack_html import pack
        from test_build_journal import fixture as build_fixture
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source';source.mkdir();build_fixture(source)
            output=Path(d)/'built';build(source,output,'paper')
            target=Path(d)/'fixture.html';pack(output,target)
            self.assertTrue(check(target,'weibo','final')['ok'])
            html=target.read_text();import re
            match=re.search(r'window.JOURNAL_DATA = (.*?);\n',html)
            data=json.loads(match.group(1));data['story']['themes'].append({**data['story']['themes'][0],'id':'duplicate'})
            html=html[:match.start(1)]+json.dumps(data,ensure_ascii=False)+html[match.end(1):]
            target.write_text(html)
            result=check(target,'weibo','final');self.assertFalse(result['ok'],result)
            self.assertTrue(any('重复' in error for error in result['errors']))
    def test_valid_final_and_external_script_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);fixture(r,'taobao')
            story={'overview':{'text':'合成消费回看。','source_ids':['sample-order']},'themes':[]};put(r,'story.json',story)
            (r/'index.html').write_text('<link href="styles.css" rel="stylesheet"><script src="orders.js"></script><script src="app.js"></script>',encoding='utf-8')
            for n in ('styles.css','orders.js','app.js'):(r/n).write_text('/* synthetic fixture */',encoding='utf-8')
            def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
            png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1080,1440,8,0,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff'*1080)*1440))+chunk(b'IEND',b'')
            (r/'exports').mkdir();(r/'exports/share.png').write_bytes(png)
            self.assertTrue(check(r,'taobao','final')['ok'])
            (r/'index.html').write_text('<script src="https://example.org/app.js"></script>',encoding='utf-8');self.assertFalse(check(r,'taobao','final')['ok'])

if __name__=='__main__':unittest.main()
