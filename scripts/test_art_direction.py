"""Style prompts must preserve provenance and work with symbolic imagery."""
import copy
import tempfile
import unittest
from pathlib import Path

from archive_common import save
from prepare_art_direction import prepare


class ArtDirectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name)
        save(self.source / "records.json", [
            {"id": "123", "text": "今天终于发布了新的专辑，音乐陪伴那些普通的日子。"},
            {"id": "456", "text": "窗台的薄荷又长了一片叶子。"}])
        self.album = {"name": "黑胶唱片", "evidence": "发布了新的专辑", "source_ids": ["123"],
                      "placement": "书桌左前方", "representation": "symbolic", "rationale": "以唱片象征原文提及的专辑"}
        self.mint = {"name": "薄荷盆栽", "evidence": "窗台的薄荷", "source_ids": ["456"],
                     "placement": "窗边", "representation": "literal"}
        self.plan = {"space": "音乐与植物相伴的工作台", "scene_objects": [self.album, self.mint], "letter_objects": [self.album]}

    def tearDown(self):
        self.temp.cleanup()

    def test_style_lock_and_auditable_symbolic_sources(self):
        result = prepare(self.source, self.plan)
        self.assertEqual(result["status"], "prompts_prepared_not_generated")
        self.assertEqual(len(result["requests"]), 2)
        for request in result["requests"]:
            self.assertIn("手绘水彩与彩铅", request["prompt"])
            self.assertIn("不要照片写实", request["prompt"])
            self.assertNotIn("发布了新的专辑", request["prompt"])
        self.assertEqual(result["requests"][0]["source_ids"], ["123", "456"])
        self.assertEqual(self.album["name"], "黑胶唱片")

    def test_unrelated_source_and_invented_quote_rejected(self):
        for changes in ({"source_ids": ["999"]}, {"source_ids": ["456"]}, {"evidence": "用户养了一只猫"}):
            plan = copy.deepcopy(self.plan)
            plan["scene_objects"][0].update(changes)
            with self.assertRaises(ValueError):
                prepare(self.source, plan)

    def test_symbol_requires_explanation_and_shared_ending(self):
        for changes in ({"rationale": ""}, {"representation": "fiction"}):
            plan = copy.deepcopy(self.plan)
            plan["scene_objects"][0].update(changes)
            with self.assertRaises(ValueError):
                prepare(self.source, plan)
        plan = copy.deepcopy(self.plan)
        plan["letter_objects"] = [{**self.mint, "name": "独立盆栽"}]
        with self.assertRaises(ValueError):
            prepare(self.source, plan)

    def test_image_only_source_can_support_reviewed_visual_object(self):
        (self.source / "photos").mkdir()
        # The prompt builder only validates file ownership; it does not claim to inspect pixels.
        (self.source / "photos/mint.png").write_bytes(b"synthetic-test-image")
        save(self.source / "records.json", [{"id": "123", "text": "", "images": [
            {"origin": "platform", "large_path": "photos/mint.png"}]}])
        object_plan = {"name": "薄荷盆栽", "evidence_kind": "image", "evidence": "已读图：窗边有一盆绿色薄荷",
                       "image_path": "photos/mint.png", "source_ids": ["123"], "placement": "窗边",
                       "representation": "literal"}
        plan = {"space": "窗边", "scene_objects": [object_plan], "letter_objects": [object_plan]}
        self.assertEqual(prepare(self.source, plan)["requests"][0]["objects"][0]["evidence_kind"], "image")
        plan = copy.deepcopy(plan)
        plan["scene_objects"][0]["image_path"] = "decorations/scene.png"
        with self.assertRaises(ValueError):
            prepare(self.source, plan)


if __name__ == "__main__":
    unittest.main()
