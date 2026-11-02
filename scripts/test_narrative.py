"""Meaningful editorial mutation tests. Every record is explicitly synthetic."""
import copy
import unittest
import tempfile
from pathlib import Path
from experience import validate_narrative, validate_experience


def fixture():
    records = [{"id": "demo-a", "date": "2025-05-19", "text": "窗台的薄荷又长了一片叶子。每次浇水，都像给普通的一天打了一个小小的记号。周末把旧书重新翻开，页边还有从前写下的字。"},
               {"id": "demo-b", "date": "2025-06-19", "text": "练习了一小段曲子，还是会弹错，但终于可以从头慢慢弹到尾。"}]
    mint = {"source_id": "demo-a", "quote": "窗台的薄荷又长了一片叶子。", "supports": ["薄荷", "窗台"]}
    book = {"source_id": "demo-a", "quote": "周末把旧书重新翻开，页边还有从前写下的字。", "supports": ["旧书", "页边"]}
    music = {"source_id": "demo-b", "quote": records[1]["text"], "supports": ["练习", "曲子"]}
    story = {"overview": {"headline": "合成夹具：窗台与练习", "text": "薄荷和练习曲子是两则虚构测试片段。", "source_ids": ["demo-a", "demo-b"]},
             "themes": [{"id": "plants", "title": "窗台的小变化", "text": "为薄荷浇水时，你留意到了那一片新叶。这一则片段很轻，却把日常留在了纸上。", "source_ids": ["demo-a"], "evidence": [mint]},
                        {"id": "music", "title": "慢慢练习", "text": "从会弹错到完整弹完一段曲子，练习也有了可以记住的小进展。", "source_ids": ["demo-b"], "evidence": [music]}],
             "evidence": [mint, music], "plans": []}
    return story, records, book


class NarrativeTests(unittest.TestCase):
    def setUp(self):
        self.story, self.records, self.book = fixture()

    def rejected(self, expected):
        with self.assertRaisesRegex(ValueError, expected):
            validate_narrative(self.story, self.records, True)

    def test_shared_bank_supports_real_source_scoped_share_without_duplicate_metadata(self):
        self.story["share"] = {"entries": [{"source_id": "demo-a", "title": "窗台", "text": "薄荷添了一片叶子。"}]}
        report = validate_narrative(self.story, self.records, True)
        self.assertEqual(report["references_checked"], 4)
        self.assertTrue(report["semantic_review_required"])

    def test_existing_ids_do_not_prove_unsupported_personality_claims(self):
        self.story["overview"]["portrait"] = {"text": "你是一位有两个孩子的医生。", "source_ids": ["demo-a"]}
        self.rejected("缺少与章节内容相连")

    def test_missing_and_duplicate_source_ids_blocked_even_for_legacy(self):
        for ids in ([], ["missing"], ["demo-a", "demo-a"], "demo-a"):
            with self.subTest(ids=ids):
                story = copy.deepcopy(self.story)
                story["themes"][0]["source_ids"] = ids
                with self.assertRaises(ValueError):
                    validate_narrative(story, self.records)

    def test_false_anchor_cannot_be_added_to_valid_ids(self):
        self.story["evidence"][0]["quote"] = "不存在的薄荷原话"
        self.rejected("连续摘录")

    def test_keyword_cannot_assert_fact_absent_from_quote(self):
        self.story["evidence"][0]["supports"] = ["医生"]
        self.rejected("具体关键词")

    def test_one_anchor_must_not_silently_support_another_source(self):
        self.story["overview"]["source_ids"] = ["demo-a", "demo-b"]
        self.story["overview"]["headline"] = "窗台"
        self.story["overview"]["text"] = "窗台的薄荷长出了新叶。"
        self.rejected("缺少与章节内容相连")

    def test_repeated_review_text_blocked_without_strict_mode(self):
        self.story["themes"][1]["text"] = self.story["themes"][0]["text"]
        with self.assertRaisesRegex(ValueError, "正文重复"):
            validate_narrative(self.story, self.records)

    def test_cosmetic_text_changes_do_not_create_a_new_page(self):
        self.story["themes"][1]["text"] = self.story["themes"][0]["text"].replace("这一则", "那一则") + "。"
        with self.assertRaisesRegex(ValueError, "高度相似"):
            validate_narrative(self.story, self.records)

    def test_different_rewrites_of_same_anchor_do_not_fill_three_pages(self):
        self.story["themes"].append({"id": "plants-again", "title": "把薄荷留在心里", "text": "愿意对薄荷保持一点耐心，也能让你在忙碌时找到一处落脚的地方。", "source_ids": ["demo-a"]})
        self.rejected("同一组原文锚点")

    def test_distinct_passages_in_one_post_may_support_distinct_topics(self):
        self.story["themes"].append({"id": "book", "title": "重新翻开旧书", "text": "旧书的页边保留了过去的字迹；翻到这一页，也重新遇见了那时的想法。", "source_ids": ["demo-a"], "evidence": [self.book]})
        self.assertEqual(validate_narrative(self.story, self.records, True)["references_checked"], 4)

    def test_duplicate_excerpts_from_different_records_are_rejected(self):
        quote = "窗台的薄荷又长了一片叶子。"
        self.records[1]["text"] += quote
        for theme in self.story["themes"]:
            theme["excerpt"] = quote
        with self.assertRaisesRegex(ValueError, "摘句重复"):
            validate_narrative(self.story, self.records)

    def test_excerpt_is_not_repeated_as_same_page_body(self):
        self.story["themes"][0].update(text="窗台的薄荷又长了一片叶子。", excerpt="窗台的薄荷又长了一片叶子。")
        self.rejected("正文与摘句重复")

    def test_wishes_are_also_checked_for_unrelated_ids(self):
        self.story["wishes"] = [{"id": "w", "title": "去看雪山", "text": "计划登上珠峰。", "source_ids": ["demo-a"]}]
        self.rejected("缺少与章节内容相连")

    def test_generated_objects_require_exact_sources_but_symbolic_names_are_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'decorations').mkdir();(root/'decorations/test.png').write_bytes(b'fixture image placeholder; not actual art')
            self.story['scene']={'image_path':'decorations/test.png','alt':'synthetic test', 'source_ids':['demo-a'],
                'objects':[{'name':'记忆书签','source_ids':['demo-a'],'evidence':self.book['quote'],'representation':'symbolic','rationale':'书签象征原文中的旧书，不断言现实所有权','placement':'桌中央'}],
                'hotspots':[{'id':'bookmark','object_name':'记忆书签','label':'旧书','description':'旧书的一页','source_ids':['demo-a'],'x':50,'y':50,'target':{'view':'review','theme_id':'plants'}}]}
            validate_experience(root,self.story,self.records,True)
            literal=copy.deepcopy(self.story);literal['scene']['objects'][0]['representation']='literal';literal['scene']['objects'][0].pop('rationale')
            validate_experience(root,literal,self.records,True)
            for mutation,match in ((lambda s:s['scene']['objects'][0].update(evidence='不存在的旧书原话'),'摘录'),
                                   (lambda s:s['scene']['objects'][0].update(source_ids=['demo-a','demo-b']),'摘录'),
                                   (lambda s:s['scene']['hotspots'][0].update(object_name='无依据照片'),'object_name'),
                                   (lambda s:s['scene']['hotspots'][0]['target'].update(date='2025-06-19'),'日期需属于'),
                                   (lambda s:s['scene'].update(source_ids=['demo-a','demo-b']),'来源全集')):
                story=copy.deepcopy(self.story);mutation(story)
                with self.assertRaisesRegex(ValueError,match):validate_experience(root,story,self.records,True)

    def test_letter_illustration_sources_are_independent_subset_of_letter(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'decorations').mkdir();(root/'decorations/test.png').write_bytes(b'synthetic placeholder')
            self.story['letter']={'title':'合成测试来信','paragraphs':['薄荷和曲子的片段。'],'closing':'测试结束','source_ids':['demo-a','demo-b'],
                'image_source_ids':['demo-a'],'image_path':'decorations/test.png','image_alt':'合成测试结尾插画',
                'objects':[{'name':'薄荷','evidence':'窗台的薄荷又长了一片叶子。','source_ids':['demo-a'],'representation':'symbolic','rationale':'测试植物意象','placement':'桌左侧'}]}
            validate_experience(root,self.story,self.records,True)
            self.story['letter']['image_source_ids']=['demo-b']
            with self.assertRaisesRegex(ValueError,'超出'):validate_experience(root,self.story,self.records,True)


if __name__ == "__main__":
    unittest.main()
