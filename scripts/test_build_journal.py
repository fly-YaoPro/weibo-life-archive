"""Synthetic tests only; no platform/account access."""
import copy
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from build_journal import build, prepare, local_file, day


def write(root, name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture(root, kind="weibo"):
    write(root, "project_meta.json", {"schema_version": 1, "platform": kind, "title": "合成测试示例", "fixture":{"synthetic":True,"label":"合成离线测试","source":"test_build_journal.py explicit synthetic fixture"}, "mode": "selected", "timezone": "Asia/Shanghai", "requested_range": {"start": "2016-01-01", "end": "2026-10-30"}, "plan_year": 2027, "target": {"uid": "synthetic"}})
    write(root, "coverage.json", [{"year": 2025, "status": "selected", "note": "虚构测试，不是真实账号"}])
    if kind == "weibo":
        records = [{"id": "demo-1", "created_at": "2025-05-19T12:00:00+08:00", "text": "窗台的薄荷又长了一片叶子。", "images": [], "url": "", "expected_image_count":0, "image_inventory_status":"complete", "image_count_basis":"Explicit synthetic fixture contains no photos"}]
        write(root, "records.json", records)
    else:
        write(root, "orders.json", [{"order_id": "demo-1", "placed_at": "2025-05-19T12:00:00+08:00", "is_success": True, "items": [{"item_id": "item-1", "name": "虚构测试花盆", "image_path": None}]}])
    write(root, "story.json", {"overview": {"headline": "虚构测试：窗台的一片新叶", "text": "这只是用于检查页面的合成记录，不是用户经历。", "source_ids": ["demo-1"]}, "themes": [{"id": "t1", "title": "测试主题", "text": "这一页只用于功能检查。", "source_ids": ["demo-1"], "layout": "C", "excerpt": "窗台的薄荷又长了一片叶子。" if kind == "weibo" else "虚构测试花盆"}], "findings": [{"title": "测试发现", "text": "合成数据。", "source_ids": ["demo-1"]}], "plans": [{"id": "p1", "title": "整理一次已有记录", "reason": "虚构测试建议。", "month": "2027-03", "source_ids": ["demo-1"]}]})


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def mutate(self, fn):
        value = json.loads((self.root / "story.json").read_text(encoding="utf-8"))
        fn(value)
        write(self.root, "story.json", value)

    def test_both_weibo_skins_and_taobao(self):
        for skin in ("paper", "frosted"):
            result = build(self.root, Path(self.temp.name) / skin, skin)
            self.assertEqual(result["plans"], 1)
        fixture(self.root, "taobao")
        self.assertEqual(build(self.root, Path(self.temp.name) / "collage", "collage")["records"], 1)

    def test_original_is_unchanged(self):
        before = (self.root / "story.json").read_bytes()
        build(self.root, Path(self.temp.name) / "new", "paper")
        self.assertEqual((self.root / "story.json").read_bytes(), before)

    def test_empty_plan_blocked(self):
        self.mutate(lambda s: s.update(plans=[]))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

    def test_readonly_wishes_do_not_need_due_dates(self):
        self.mutate(lambda s:s.update(plans=[],wishes=[{"id":"w1","title":"再翻一页旧书","text":"给喜欢的事留一点时间。","source_ids":["demo-1"]}]))
        with self.assertRaisesRegex(ValueError,"plans"):prepare(self.root,"paper")
    def test_unknown_wish_source_is_blocked(self):
        self.mutate(lambda s:s.update(wishes=[{"id":"w1","title":"小愿望","text":"短记","source_ids":["missing"]}]))
        with self.assertRaises(ValueError):prepare(self.root,"paper")
    def test_cover_portrait_requires_real_evidence(self):
        self.mutate(lambda s:s['overview'].update(opening='开场白',portrait={'text':'有据的日常解析','source_ids':['missing']}))
        with self.assertRaises(ValueError):prepare(self.root,'paper')
    def test_required_cover_blocks_missing_editorial_content(self):
        meta=json.loads((self.root/'project_meta.json').read_text());meta['presentation']={'cover_required':True};write(self.root,'project_meta.json',meta)
        with self.assertRaises(ValueError):prepare(self.root,'paper')
        self.mutate(lambda s:s['overview'].update(opening='翻开这些日子。',portrait={'text':'这些记录里出现了窗台的新叶。','source_ids':['demo-1']}))
        self.assertTrue(prepare(self.root,'paper')['story']['overview']['portrait'])
    def test_unknown_source_blocked(self):
        self.mutate(lambda s: s["plans"][0].update(source_ids=["not-real"]))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

    def test_false_quote_blocked(self):
        self.mutate(lambda s: s["themes"][0].update(excerpt="这是凭空编写的原话"))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

    def test_duplicate_review_pages_rejected_before_any_output_written(self):
        def duplicate(story):
            theme = copy.deepcopy(story["themes"][0]); theme["id"] = "t2"
            story["themes"].append(theme)
        self.mutate(duplicate)
        output = Path(self.temp.name) / "duplicate"
        with self.assertRaisesRegex(ValueError, "摘句重复|正文重复"):
            build(self.root, output, "paper")
        self.assertFalse(output.exists())

    def test_strict_editorial_ids_alone_cannot_pass(self):
        meta = json.loads((self.root / "project_meta.json").read_text())
        meta["presentation"] = {"grounding_required": True}
        write(self.root, "project_meta.json", meta)
        with self.assertRaisesRegex(ValueError, "锚点"):
            prepare(self.root, "paper")

    def test_video_cover_remains_separate_and_is_copied(self):
        from test_pipeline import png
        (self.root / "images").mkdir()
        (self.root / "images/cover.png").write_bytes(png())
        records = json.loads((self.root / "records.json").read_text())
        records[0]['url']='https://example.invalid/synthetic-video'
        records[0].update(is_video=True, video={"source_url": records[0]["url"], "cover_status": "observed", "covers": [
            {"origin": "platform", "source_url": "https://example.org/synthetic-cover.png", "download_status": "saved", "thumb_path": "images/cover.png", "large_path": "images/cover.png"}]})
        write(self.root, "records.json", records)
        self.mutate(lambda story:story['themes'][0].update(image_paths=['images/cover.png']))
        data = prepare(self.root, "paper")
        self.assertEqual(data["records"][0]["images"], [])
        self.assertEqual(data["records"][0]["video"]["covers"][0]["path"], "images/cover.png")
        self.assertEqual(data["story"]["themes"][0]["images"][0]["media_kind"], "video-cover")
        output = Path(self.temp.name) / "video"
        build(self.root, output, "paper")
        self.assertEqual((output / "images/cover.png").read_bytes(), (self.root / "images/cover.png").read_bytes())
        from pack_html import pack, verify_packed
        packed = Path(self.temp.name) / "video.html"
        pack(output, packed)
        self.assertTrue(verify_packed(packed)["ok"])
        self.assertIn('"images/cover.png": "data:', packed.read_text())

    def test_missing_video_cover_is_honest_and_does_not_drop_post(self):
        records = json.loads((self.root / "records.json").read_text())
        records[0]['url']='https://example.invalid/synthetic-video'
        records[0].update(is_video=True, video={"source_url": records[0]["url"], "cover_status": "unavailable", "covers": []})
        write(self.root, "records.json", records)
        self.assertEqual(len(prepare(self.root, "paper")["records"]), 1)
        records[0]["video"]["source_url"] = "https://example.org/unrelated"
        write(self.root, "records.json", records)
        with self.assertRaisesRegex(ValueError, "同一原帖"):
            prepare(self.root, "paper")

    def test_template_is_exposed_in_cli_and_overlap_is_rejected(self):
        template = Path(__file__).resolve().parents[1] / "assets/starter"
        output = Path(self.temp.name) / "custom-template"
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("build_journal.py")), "--source", str(self.root), "--output", str(output), "--skin", "paper", "--template", str(template)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output / "index.html").is_file())
        with self.assertRaisesRegex(ValueError, "模板"):
            build(self.root, template / "nested-test", "paper", template)

    def test_nonempty_target_and_nested_blocked(self):
        out = Path(self.temp.name) / "new"
        out.mkdir()
        (out / "keep.txt").write_text("do not overwrite", encoding="utf-8")
        with self.assertRaises(ValueError):
            build(self.root, out, "paper")
        with self.assertRaises(ValueError):
            build(self.root, self.root / "nested", "paper")

    def test_path_escape_and_svg_blocked(self):
        for path in ("../outside.png", "https://example.com/a.jpg", "C:/secret.png", "images\\a.jpg"):
            with self.assertRaises(ValueError):
                local_file(self.root, path)
        (self.root / "a.svg").write_text("<svg/>", encoding="utf-8")
        with self.assertRaises(ValueError):
            local_file(self.root, "a.svg")

    def test_date_and_requested_range_are_not_faked(self):
        self.assertEqual(day("2025-01-01T20:00:00Z"), "2025-01-02")
        data = prepare(self.root, "paper")
        self.assertEqual(data["meta"]["actual_range"]["start"], "2025-05-19")
        self.assertIn("更早范围未完整收录", data["scope"])

    def test_js_string_is_escaped(self):
        self.mutate(lambda s: s["overview"].update(text="</script><script>alert(1)</script>"))
        out = Path(self.temp.name) / "escaped"
        build(self.root, out, "paper")
        self.assertNotIn("</script>", (out / "journal-data.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
