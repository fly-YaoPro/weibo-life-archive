"""Mutation checks through the real source/build/packed entry points, synthetic only."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_common import load, save
from build_journal import build, prepare
from check_project import check
from pack_html import pack
from test_build_journal import fixture
from test_pipeline import png


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'source';self.root.mkdir();fixture(self.root)
        for path in ('images/photo.png','images/cover.png','profile/avatar.png','decorations/scene.png'):
            target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(png(40,30))
        meta=load(self.root/'project_meta.json');meta.update(title='合成运行时验收',fixture={'synthetic':True,'label':'合成测试','source':'explicit synthetic test fixture'})
        meta['target']['profile_url']='https://weibo.com/u/synthetic'
        meta['presentation']={k:True for k in ('grounding_required','profile_required','cover_required','experience_required','three_wishes_required','share_letter_required','share_entries_required')}
        meta['profile']={'uid':'synthetic','name':'合成演示 · 测试','source_url':'https://weibo.com/u/synthetic','captured_at':'2026-11-01T00:00:00+08:00',
            'avatar_path':'profile/avatar.png','avatar_origin':'synthetic_fixture','provided_reference':'explicit synthetic fixture',
            **{k:{'display':'—','value':None,'exact':False} for k in ('followers','following','engagement')}}
        save(self.root/'project_meta.json',meta)
        records=load(self.root/'records.json');records[0].update(url='https://example.invalid/demo-post',author_uid='synthetic',selected=True,
            expected_image_count=1,image_inventory_status='complete',image_count_basis='Synthetic fixture inventory has one photo', images=[{'image_id':'synthetic-photo','large_note':'Synthetic fixture intentionally uses the same small image for both views','origin':'synthetic_fixture','provided_reference':'explicit synthetic fixture','download_status':'saved','thumb_path':'images/photo.png','large_path':'images/photo.png'}],
            is_video=True,video={'source_url':'https://example.invalid/demo-post','cover_status':'observed','covers':[
                {'origin':'synthetic_fixture','provided_reference':'explicit synthetic fixture','download_status':'saved','thumb_path':'images/cover.png','large_path':'images/cover.png'}]})
        save(self.root/'records.json',records)
        story=load(self.root/'story.json');story['evidence']=[{'source_id':'demo-1','quote':records[0]['text'],'supports':['薄荷']}]
        story['overview'].update(headline='合成测试：薄荷',text='薄荷的合成记录。',opening='看看薄荷的新叶。',portrait={'text':'薄荷的小变化。','source_ids':['demo-1']})
        story['themes'][0].update(title='薄荷的一页',text='薄荷长出新叶，留下一个轻轻的日常记号。')
        story['plans'][0]['reason']='薄荷的片段。';story['findings'][0]['text']='薄荷的合成发现。'
        obj={'name':'薄荷','evidence':records[0]['text'],'source_ids':['demo-1'],'placement':'窗边','representation':'literal'}
        story['scene']={'image_path':'decorations/scene.png','alt':'合成测试场景','source_ids':['demo-1'],'objects':[obj],
            'hotspots':[{'id':'h'+str(n),'object_name':'薄荷','label':'薄荷'+str(n),'description':'薄荷的记号。','source_ids':['demo-1'],'x':20+n*20,'y':50,'target':{'view':'review','theme_id':'t1'}} for n in range(3)]}
        story['letter']={'title':'薄荷的新叶','paragraphs':['薄荷的记号，也留给下一段日子。'],'closing':'看看薄荷。','source_ids':['demo-1'],
            'image_path':'decorations/scene.png','image_alt':'合成测试结尾插画','image_source_ids':['demo-1'],'objects':[obj]}
        story['wishes']=[{'id':'w'+str(n),'title':'看看薄荷','text':'薄荷的新叶。','source_ids':['demo-1']} for n in range(3)]
        story['share']={'letter_text':'薄荷的一页。','entries':[{'source_id':'demo-1','title':'薄荷','text':'薄荷的新叶。'}]}
        # Valid local original audio; no network or borrowed recording.
        from prepare_music import prepare as music
        save(self.root/'story.json',story);music(self.root,offline=True)
        self.output=Path(self.temp.name)/'built';build(self.root,self.output,'paper')
        self.html=Path(self.temp.name)/'synthetic.html';pack(self.output,self.html)
        self.original=self.html.read_text();self.data=json.loads(re.search(r'window.JOURNAL_DATA = (.*?);\n',self.original).group(1))

    def tearDown(self):self.temp.cleanup()

    def mutated(self,change):
        data=copy.deepcopy(self.data);change(data)
        match=re.search(r'window.JOURNAL_DATA = (.*?);\n',self.original)
        changed=self.original[:match.start(1)]+json.dumps(data,ensure_ascii=False).replace('<','\\u003c')+self.original[match.end(1):]
        read=Path.read_text;target=self.html.resolve()
        def read_mutation(path,*args,**kwargs):return changed if path.resolve()==target else read(path,*args,**kwargs)
        with patch.object(Path,'read_text',read_mutation):return check(self.html,'weibo','final')

    def rejected(self,change):
        result=self.mutated(change);self.assertFalse(result['ok'],result)
        self.assertTrue(result['errors'],result)

    def test_baseline_source_and_real_packed_entry_pass(self):
        self.assertTrue(check(self.root,'weibo','data')['ok'])
        self.assertTrue(check(self.html,'weibo','final')['ok'])

    def test_packed_required_profile_cannot_be_removed_or_misattributed(self):
        for change in (lambda d:d['meta'].pop('profile'),lambda d:d['meta']['profile'].update(uid='other'),
                       lambda d:d['meta']['profile'].update(name=''),lambda d:d['meta']['profile'].pop('avatar_path'),
                       lambda d:d['meta']['profile'].update(avatar_path='profile/missing.png'),
                       lambda d:d['meta']['profile'].update(avatar_origin='ai_generated'),
                       lambda d:d['meta']['profile'].pop('followers'),lambda d:d['meta']['profile']['following'].update(value=-1)):
            with self.subTest(change=change):self.rejected(change)

    def test_packed_video_and_photo_source_state_cannot_be_fabricated(self):
        for change in (lambda d:d['records'][0]['video'].update(source_url='https://example.invalid/wrong'),
                       lambda d:d['records'][0]['video'].update(cover_status='nonsense'),
                       lambda d:d['records'][0]['video'].update(observed_covers=[]),
                       lambda d:d['records'][0]['video']['covers'][0].update(origin='ai_generated'),
                       lambda d:d['records'][0]['images'][0].update(origin='ai_generated'),
                       lambda d:d['records'][0]['images'][0].update(download_status='pretend'),
                       lambda d:d['records'][0]['images'][0].update(path='images/not-embedded.png')):
            with self.subTest(change=change):self.rejected(change)

    def test_source_and_packed_dates_and_author_are_preserved(self):
        self.assertEqual(self.data['records'][0]['author_uid'],'synthetic')
        self.assertEqual(self.data['records'][0]['created_at'],'2025-05-19T12:00:00+08:00')
        for change in (lambda d:d['records'][0].update(date='2000-01-01'),
                       lambda d:d['records'][0].update(date='2025-05-20'),
                       lambda d:d['records'][0].update(author_uid='another-user')):
            with self.subTest(change=change):self.rejected(change)

    def test_nonfixture_real_id_permalink_and_author_match_target(self):
        from runtime_contract import validate_runtime
        meta=copy.deepcopy(self.data['meta']);meta.pop('fixture');meta['presentation']={'grounding_required':True}
        meta['target']={'uid':'123','profile_url':'https://weibo.com/u/123'};meta.pop('profile')
        record={**self.data['records'][0],'id':'100','author_uid':'123','url':'https://weibo.com/123/1C'}
        record.pop('video');record.pop('is_video');record['images']=[];record['expected_image_count']=0
        validate_runtime(meta,[record],root=self.root)
        for changes in ({'url':'https://weibo.com/456/1C'},{'url':'https://weibo.com/123/1D'},{'author_uid':'456'},{'author_uid':None}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_runtime(meta,[{**record,**changes}],root=self.root)

    def test_packed_cover_experience_objects_and_hotspots_use_build_contracts(self):
        for change in (lambda d:d['story']['overview'].pop('opening'),lambda d:d['story']['overview'].pop('portrait'),
                       lambda d:d['story'].pop('scene'),lambda d:d['story']['letter'].pop('image_path'),
                       lambda d:d['story']['scene']['objects'][0].update(evidence='虚构的原话'),
                       lambda d:d['story']['scene']['hotspots'][0].update(object_name='未映射物件'),
                       lambda d:d['story']['scene']['hotspots'][0].update(x=150),
                       lambda d:d['story']['scene']['hotspots'][0]['target'].update(theme_id='missing'),
                       lambda d:d['story'].update(wishes=[]),lambda d:d['story']['share'].update(entries=[]),
                       lambda d:d['story']['share'].update(letter_text='')):
            with self.subTest(change=change):self.rejected(change)

    def test_unavailable_cover_keeps_observed_url_and_failed_status_without_showing_fake_image(self):
        records=load(self.root/'records.json');cover=records[0]['video']['covers'][0]
        cover.update(download_status='failed');cover.pop('thumb_path');cover.pop('large_path');save(self.root/'records.json',records)
        runtime=prepare(self.root,'paper');video=runtime['records'][0]['video']
        self.assertEqual(video['cover_status'],'observed');self.assertEqual(video['covers'],[])
        self.assertEqual(video['observed_covers'][0]['download_status'],'failed')
        output=Path(self.temp.name)/'failed-cover';build(self.root,output,'paper')
        html=Path(self.temp.name)/'failed-cover.html';pack(output,html)
        self.assertTrue(check(html,'weibo','final')['ok'])

    def test_image_only_records_have_visual_anchors_without_inventing_text(self):
        records=load(self.root/'records.json');records[0]['text']='';save(self.root/'records.json',records)
        story=load(self.root/'story.json');story['themes'][0].pop('excerpt')
        story['evidence']=[{'kind':'image','source_id':'demo-1','image_path':'images/photo.png','observation':'窗台旁有薄荷植物。','supports':['薄荷']}]
        for section in (story['scene'],story['letter']):section['objects'][0].update(evidence_kind='image',image_path='images/photo.png',evidence='窗台旁有薄荷植物。')
        save(self.root/'story.json',story)
        output=Path(self.temp.name)/'image-only';build(self.root,output,'paper')
        html=Path(self.temp.name)/'image-only.html';pack(output,html)
        self.assertTrue(check(html,'weibo','final')['ok'])
        self.assertEqual(load(output/'records.json')[0]['text'],'')
        story['evidence'][0]['image_path']='decorations/scene.png';save(self.root/'story.json',story)
        with self.assertRaisesRegex(ValueError,'缓存图片'):prepare(self.root,'paper')


if __name__=='__main__':unittest.main()
