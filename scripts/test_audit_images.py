"""Synthetic local media only. Never downloads or accesses an account."""
import copy
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from audit_images import audit, image_info
from build_journal import build, prepare
from test_build_journal import fixture, write


def png(width=80, height=60, color=128):
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xffffffff)
    pixels = (b"\0" + bytes([color]) * width) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def media(root, number=0):
    thumb, large = f"images/{number}-small.png", f"images/{number}-large.png"
    (root / "images").mkdir(exist_ok=True)
    (root / thumb).write_bytes(png(color=number + 20))
    (root / large).write_bytes(png(800, 600, number + 20))
    return {"image_id": f"synthetic-{number}", "origin": "platform", "source_url": f"https://example.org/synthetic-{number}.png",
            "thumb_path": thumb, "large_path": large, "download_status": "saved"}


class ImageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        fixture(self.root)
        self.rows = json.loads((self.root / "records.json").read_text("utf-8"))
        self.row = self.rows[0]
        self.row.update(expected_image_count=2, image_inventory_status="complete", image_count_basis="Synthetic detail pic_num=2, both image IDs enumerated", images=[media(self.root, 0), media(self.root, 1)])

    def tearDown(self):
        self.temp.cleanup()

    def result(self):
        write(self.root, "records.json", self.rows)
        return audit(self.root)

    def test_complete_two_variants(self):
        result = self.result()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["saved_images"], 2)
        self.assertEqual(result["records"][0]["images"][0]["files"]["large_path"]["width"], 800)

    def test_four_photos_cannot_satisfy_larger_inventory(self):
        self.row.update(expected_image_count=17, images=[media(self.root, i) for i in range(4)])
        result = self.result()
        self.assertFalse(result["ok"])
        self.assertEqual(result["expected_known_images"], 17)
        self.assertEqual(result["saved_images"], 4)

    def test_first_nine_are_not_whole_gallery(self):
        self.row.update(expected_image_count=18, images=[media(self.root, i) for i in range(9)])
        self.assertFalse(self.result()["ok"])

    def test_unknown_image_count_is_not_text_only(self):
        self.row.pop("expected_image_count")
        self.row["images"] = []
        result = self.result()
        self.assertFalse(result["ok"])
        self.assertEqual(result["unknown_count_records"], 1)

    def test_confirmed_text_only_is_valid(self):
        self.row.update(expected_image_count=0, images=[], image_count_basis="Synthetic detail confirms pic_num=0")
        self.assertTrue(self.result()["ok"])

    def test_unverified_inventory_rejected(self):
        self.row["image_inventory_status"] = "partial"
        self.assertFalse(self.result()["ok"])

    def test_no_source_count_basis_rejected(self):
        self.row.pop("image_count_basis")
        self.assertFalse(self.result()["ok"])

    def test_missing_variant_rejected(self):
        self.row["images"][0]["large_path"] = None
        self.assertFalse(self.result()["ok"])

    def test_remote_image_is_not_download(self):
        self.row["images"][0]["large_path"] = "https://example.org/large.jpg"
        self.assertFalse(self.result()["ok"])

    def test_failed_status_rejected_even_with_files(self):
        self.row["images"][0]["download_status"] = "failed"
        self.assertFalse(self.result()["ok"])

    def test_empty_html_and_truncated_bytes_rejected(self):
        path = self.root / self.row["images"][0]["large_path"]
        for value in (b"", b"<html>please log in</html>", png()[:-12], b"\xff\xd8broken"):
            with self.subTest(value=value[:20]):
                path.write_bytes(value)
                self.assertFalse(self.result()["ok"])

    def test_corrupt_png_crc_rejected(self):
        path = self.root / self.row["images"][0]["large_path"]
        value = bytearray(path.read_bytes())
        value[40] ^= 1
        path.write_bytes(value)
        self.assertFalse(self.result()["ok"])

    def test_repeated_files_do_not_inflate_count(self):
        second = copy.deepcopy(self.row["images"][0])
        second["image_id"] = "another-claimed-photo"
        self.row["images"][1] = second
        self.assertFalse(self.result()["ok"])

    def test_identical_variants_require_best_available_note(self):
        self.row["images"][0]["large_path"] = self.row["images"][0]["thumb_path"]
        self.assertFalse(self.result()["ok"])
        self.row["images"][0]["large_note"] = "Synthetic source only offers this small image; not an upscaled replacement"
        self.assertTrue(self.result()["ok"])

    def test_smaller_large_variant_rejected(self):
        image = self.row["images"][0]
        image["thumb_path"], image["large_path"] = image["large_path"], image["thumb_path"]
        self.assertFalse(self.result()["ok"])

    def test_path_escape_and_synthetic_provenance_rejected(self):
        self.row["images"][0].update(large_path="../outside.png", origin="ai_generated")
        self.assertFalse(self.result()["ok"])

    def test_boolean_count_rejected(self):
        self.row["expected_image_count"] = True
        self.assertFalse(self.result()["ok"])

    def test_build_enforces_gate_without_separate_check(self):
        self.row["images"] = []
        self.result()
        with self.assertRaisesRegex(ValueError, "图片未齐"):
            build(self.root, Path(self.temp.name) / "output", "paper")
        self.assertFalse((Path(self.temp.name) / "output").exists())

    def test_archive_images_cannot_all_be_hidden_from_review(self):
        self.result()
        text_record = copy.deepcopy(self.row)
        text_record.update(id="text-2", images=[], expected_image_count=0, image_count_basis="Synthetic no-image record")
        self.rows.append(text_record)
        self.result()
        story = json.loads((self.root / "story.json").read_text("utf-8"))
        for section in [story["overview"]] + story["themes"]:
            section["source_ids"] = ["text-2"]
        write(self.root, "story.json", story)
        with self.assertRaisesRegex(ValueError, "回看页面全部无图"):
            prepare(self.root, "paper")

    def test_builder_copies_all_images_not_just_displayed_ones(self):
        self.result()
        story = json.loads((self.root / "story.json").read_text("utf-8"))
        for section in [story["overview"]] + story["themes"]:
            section["image_paths"] = [self.row["images"][0]["thumb_path"]]
        write(self.root, "story.json", story)
        output = Path(self.temp.name) / "output"
        build(self.root, output, "paper")
        report = json.loads((output / "image-audit.json").read_text("utf-8"))
        self.assertEqual(report["saved_images"], 2)
        for image in self.row["images"]:
            for key in ("thumb_path", "large_path"):
                self.assertEqual((self.root / image[key]).read_bytes(), (output / image[key]).read_bytes())


if __name__ == "__main__":
    unittest.main()
