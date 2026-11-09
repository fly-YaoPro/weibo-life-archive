"""Explicit synthetic, offline photo build regressions; no platform/browser claims."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from build_journal import build, prepare
from pack_html import pack, verify_packed
from test_pipeline import png


def write(root, name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def photo_fixture(root, dates=("2024-02-29", "2023-05", "2022", None)):
    meta = {"schema_version": 1, "platform": "photos", "title": "合成测试照片回忆册",
            "fixture": {"synthetic": True, "label": "合成离线照片测试", "source": __file__},
            "timezone": "Asia/Shanghai", "mode": "selected",
            "requested_range": {"start": "2016-01-01", "end": "2026-11-09"},
            "target": {"collection_id": "synthetic-album", "collection_name": "合成相册"}}
    write(root, "project_meta.json", meta)
    write(root, "coverage.json", [])
    (root / "images").mkdir()
    (root / "decorations").mkdir()
    raw = png(4, 4)
    (root / "images/photo.png").write_bytes(raw)
    (root / "decorations/closing.png").write_bytes(raw)
    records = []
    for index, date in enumerate(dates):
        digest = hashlib.sha256(("synthetic-source-" + str(index)).encode()).hexdigest()
        rid = "photo-" + digest[:24]
        records.append({"id": rid, "source_sha256": digest, "selected": True,
                        "date": date, "created_at": None,
                        "date_precision": "unknown" if date is None else {4: "year", 7: "month", 10: "day"}[len(date)],
                        "date_basis": "unknown" if date is None else "user_manifest",
                        "date_evidence": {"kind": "unknown"} if date is None else {"kind": "user_manifest", "value": date},
                        "text": "合成测试图片说明 " + str(index), "url": None,
                        "expected_image_count": 1, "image_inventory_status": "complete", "image_count_basis": "明确合成单图",
                        "images": [{"image_id": rid, "origin": "synthetic_fixture", "provided_reference": "合成离线夹具",
                                    "thumb_path": "images/photo.png", "large_path": "images/photo.png",
                                    "download_status": "saved", "exif_stripped": True,
                                    "sha256": hashlib.sha256(raw).hexdigest()}]})
    write(root, "records.json", records)
    ids = [row["id"] for row in records]
    write(root, "story.json", {"overview": {"headline": "合成测试：一组照片", "text": "合成照片用于检查日期与图片路径。", "source_ids": ids},
                               "themes": [{"id": "album", "title": "合成相册", "text": "这一页不是任何人的经历。", "source_ids": ids, "layout": "A"}],
                               "plans": [], "wishes": [{"id": "w1", "title": "再翻一页", "text": "合成测试期待。", "source_ids": ids}],
                               "letter": {"title": "合成测试来信", "paragraphs": ["这是一份离线功能测试。"], "closing": "合成测试结束。", "source_ids": ids,
                                          "image_path": "decorations/closing.png", "image_alt": "明确合成的功能测试图"},
                               "share": {"letter_text": "合成测试来信。", "entries": [{"source_id": ids[0], "title": "合成图片", "text": "仅测试。"}]}})
    return meta, records


class PhotoFrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_partial_dates_are_preserved_without_midnight_or_first_day(self):
        photo_fixture(self.root)
        data = prepare(self.root, "paper")
        self.assertEqual([r["date"] for r in data["records"]], ["2022", "2023-05", "2024-02-29", None])
        self.assertTrue(all(r["created_at"] is None for r in data["records"]))
        self.assertEqual(data["records"][0]["date_label"], "2022年")
        self.assertEqual(data["records"][1]["date_label"], "2023年5月")
        self.assertEqual(data["records"][-1]["date_label"], "日期待确认")
        self.assertIsNone(data["records"][-1]["url"])
        self.assertNotIn("微博", data["scope"])

    def test_photo_metrics_do_not_invent_months_for_unknown_or_year_only(self):
        photo_fixture(self.root)
        metrics = prepare(self.root, "paper")["metrics"]
        self.assertEqual(metrics["basis"], "provided_photos")
        self.assertFalse(metrics["complete"])
        self.assertEqual(metrics["days"], {"2024-02-29": 1})
        self.assertEqual([m["month"] for m in metrics["monthly"]], ["2023-05", "2024-02"])
        self.assertTrue(all(m["published_count"] is None for m in metrics["monthly"]))

    def test_all_unknown_still_builds_both_styles_and_packs_real_asset(self):
        photo_fixture(self.root, (None,))
        before = (self.root / "records.json").read_bytes()
        for skin in ("paper", "frosted"):
            output = Path(self.temp.name) / skin
            result = build(self.root, output, skin)
            self.assertEqual(result["records"], 1)
            data = json.loads((output / "journal-data.js").read_text(encoding='utf-8')[len("window.JOURNAL_DATA = "):-2])
            self.assertEqual(data["meta"]["actual_range"], {"start": None, "end": None})
            self.assertEqual(data["metrics"]["days"], {})
            self.assertTrue((output / "data.js").is_file())
            self.assertFalse((output / "orders.json").exists())
            packed = Path(self.temp.name) / (skin + ".html")
            pack(output, packed)
            self.assertTrue(verify_packed(packed)["ok"])
            self.assertIn('"images/photo.png": "data:image/png;base64,', packed.read_text(encoding='utf-8'))
        self.assertEqual(before, (self.root / "records.json").read_bytes())

    def test_reading_key_is_album_stable_not_first_photo_based(self):
        photo_fixture(self.root, (None,))
        first = prepare(self.root, "paper")["project_key"]
        rows = json.loads((self.root / "records.json").read_text(encoding='utf-8'))
        digest = hashlib.sha256(b"replacement synthetic photo").hexdigest()
        rows[0]["id"] = "photo-" + digest[:24]
        rows[0]["source_sha256"] = digest
        rows[0]["images"][0]["image_id"] = rows[0]["id"]
        old = json.loads((self.root / "story.json").read_text(encoding='utf-8'))
        original_id = json.loads((self.root / "records.json").read_text(encoding='utf-8'))[0]["id"]
        write(self.root, "records.json", rows)
        (self.root / "story.json").write_text(json.dumps(old).replace(original_id, rows[0]["id"]),encoding='utf-8')
        self.assertEqual(first, prepare(self.root, "paper")["project_key"])


if __name__ == "__main__":
    unittest.main()
