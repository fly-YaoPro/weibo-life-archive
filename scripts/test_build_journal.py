"""Synthetic tests only; no platform/account access."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from build_journal import build, prepare, local_file, day


def write(root, name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture(root, kind="weibo"):
    write(root, "project_meta.json", {"schema_version": 1, "platform": kind, "title": "虚构测试示例", "mode": "selected", "timezone": "Asia/Shanghai", "requested_range": {"start": "2016-01-01", "end": "2026-10-30"}, "plan_year": 2027, "target": {"uid": "synthetic"}})
    write(root, "coverage.json", [{"year": 2025, "status": "selected", "note": "虚构测试，不是真实账号"}])
    if kind == "weibo":
        records = [{"id": "demo-1", "created_at": "2025-05-19T12:00:00+08:00", "text": "窗台的薄荷又长了一片叶子。", "images": [], "url": "", "expected_image_count": 0, "image_inventory_status": "complete", "image_count_basis": "synthetic fixture confirms no pictures"}]
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

    def test_unknown_source_blocked(self):
        self.mutate(lambda s: s["plans"][0].update(source_ids=["not-real"]))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

    def test_false_quote_blocked(self):
        self.mutate(lambda s: s["themes"][0].update(excerpt="这是凭空编写的原话"))
        with self.assertRaises(ValueError):
            prepare(self.root, "paper")

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
