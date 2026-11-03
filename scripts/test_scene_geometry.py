"""Synthetic geometry and build tests; no real account or publication."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from archive_common import save
from calibrate_scene import calibrate
from scene_geometry import validate_bounds, validate_scene_geometry


class SceneGeometryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'source'
        (self.root/'decorations').mkdir(parents=True)
        (self.root/'decorations/scene.png').write_bytes(b'synthetic-test-image-revision-1')
        self.scene = {'image_path':'decorations/scene.png','hotspots':[
            {'id':'book','x':30,'y':50,'bounds':{'x':20,'y':30,'width':25,'height':40}},
            {'id':'cup','x':70,'y':60,'bounds':{'x':60,'y':40,'width':20,'height':30}}]}
        self.scene['calibration'] = {'image_sha256':hashlib.sha256((self.root/'decorations/scene.png').read_bytes()).hexdigest()}

    def test_valid_regions_bound_to_image(self):
        self.assertTrue(validate_scene_geometry(self.root,self.scene)['calibrated'])

    def test_image_replacement_requires_recalibration(self):
        (self.root/'decorations/scene.png').write_bytes(b'synthetic-test-image-revision-2')
        with self.assertRaisesRegex(ValueError,'指纹'): validate_scene_geometry(self.root,self.scene)

    def test_overlapping_regions_are_rejected(self):
        self.scene['hotspots'][1].update(x=40,y=50,bounds={'x':35,'y':35,'width':20,'height':30})
        with self.assertRaisesRegex(ValueError,'重叠'): validate_scene_geometry(self.root,self.scene)

    def test_bad_bounds_and_anchor_are_rejected(self):
        for b in ({'x':-1,'y':0,'width':20,'height':30},{'x':90,'y':0,'width':20,'height':30},
                  {'x':0,'y':0,'width':0,'height':30},{'x':0,'y':0,'width':float('nan'),'height':30},
                  {'x':0,'y':0,'width':True,'height':30},{'x':0,'y':0,'width':10,'height':10}):
            with self.subTest(b=b), self.assertRaises(ValueError): validate_bounds({'x':30,'y':50,'bounds':b})

    def test_legacy_points_supported_but_not_marked_calibrated(self):
        for h in self.scene['hotspots']: h.pop('bounds')
        self.scene.pop('calibration')
        self.assertFalse(validate_scene_geometry(self.root,self.scene)['calibrated'])

    def test_mixed_regions_rejected(self):
        self.scene['hotspots'][1].pop('bounds')
        with self.assertRaisesRegex(ValueError,'混用'): validate_scene_geometry(self.root,self.scene)

    def test_calibration_keeps_sources_targets_and_backup(self):
        original={'scene':copy.deepcopy(self.scene),'overview':{'text':'合成内容保持不变'}}
        for h in original['scene']['hotspots']:
            h.update(source_ids=['synthetic-'+h['id']],target={'view':'review','theme_id':h['id']})
        save(self.root/'story.json',original)
        regions={h['id']:{k:h[k] for k in ('x','y','bounds')} for h in self.scene['hotspots']}
        self.assertTrue(calibrate(self.root,regions)['calibrated'])
        updated=json.loads((self.root/'story.json').read_text(encoding='utf-8'))
        self.assertEqual(updated['scene']['hotspots'],original['scene']['hotspots'])
        self.assertEqual(updated['overview'],original['overview'])
        self.assertEqual(len(list(self.root.glob('story.before-hotspots-*.json'))),1)
        before=(self.root/'story.json').read_bytes()
        with self.assertRaises(ValueError): calibrate(self.root,{'unknown':regions['book']})
        self.assertEqual(before,(self.root/'story.json').read_bytes())

    def test_build_preserves_regions_and_rejects_stale_image(self):
        from test_build_journal import fixture
        from build_journal import build
        from PIL import Image
        fixture(self.root)
        Image.new('RGB',(160,90),'ivory').save(self.root/'decorations/scene.png')
        self.scene['calibration']['image_sha256']=hashlib.sha256((self.root/'decorations/scene.png').read_bytes()).hexdigest()
        story=json.loads((self.root/'story.json').read_text(encoding='utf-8'))
        scene=copy.deepcopy(self.scene)
        scene.update(alt='合成测试图',source_ids=['demo-1'])
        for h in scene['hotspots']: h.update(label=h['id'],description='合成小记',source_ids=['demo-1'],target={'view':'review','theme_id':'t1'})
        story['scene']=scene
        save(self.root/'story.json',story)
        out=self.root.parent/'built'
        build(self.root,out,'paper')
        data=(out/'journal-data.js').read_text(encoding='utf-8')
        self.assertIn('bounds',data)
        from pack_html import pack
        from check_project import check
        html=self.root.parent/'packed.html'
        pack(out,html)
        self.assertTrue(check(html,'weibo','final')['ok'])
        (self.root/'decorations/scene.png').write_bytes(b'changed-image')
        with self.assertRaisesRegex(ValueError,'指纹'): build(self.root,self.root.parent/'stale','paper')

    def test_controlled_compression_keeps_calibration_and_packed_contract(self):
        from PIL import Image
        from test_build_journal import fixture
        from build_journal import build
        from media_budget import apply_budget
        from pack_html import pack
        from check_project import check
        fixture(self.root)
        # Deterministic noisy pixels to force a real compression/repath branch.
        import random
        rng=random.Random(44)
        Image.frombytes('RGB',(800,450),rng.randbytes(800*450*3)).save(self.root/'decorations/scene.png')
        self.scene['calibration']['image_sha256']=hashlib.sha256((self.root/'decorations/scene.png').read_bytes()).hexdigest()
        story=json.loads((self.root/'story.json').read_text(encoding='utf-8'))
        scene=copy.deepcopy(self.scene);scene.update(alt='合成噪声测试',source_ids=['demo-1'])
        for h in scene['hotspots']:h.update(label=h['id'],description='合成小记',source_ids=['demo-1'],target={'view':'review','theme_id':'t1'})
        story['scene']=scene;save(self.root/'story.json',story)
        out=self.root.parent/'compressed';build(self.root,out,'paper')
        self.assertGreater(apply_budget(out,.2)['files_changed'],0)
        updated=json.loads((out/'story.json').read_text(encoding='utf-8'))
        self.assertEqual(updated['scene']['hotspots'],scene['hotspots'])
        self.assertEqual(updated['scene']['calibration']['source_image_sha256'],scene['calibration']['image_sha256'])
        self.assertTrue(validate_scene_geometry(out,updated['scene'])['calibrated'])
        html=self.root.parent/'compressed.html';pack(out,html)
        self.assertTrue(check(html,'weibo','final')['ok'])


if __name__ == '__main__': unittest.main()
