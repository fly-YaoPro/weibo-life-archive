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
        self.assertFalse(report["semantic_review_required"])

    def test_semantic_interpretation_is_not_claimed_by_static_checker(self):
        report=validate_narrative(self.story,self.records,True)
        self.assertFalse(report['keyword_matching_required'])
        self.assertEqual(report['semantic_basis'],'author_read_sources')

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

    def test_legacy_supports_never_gate_prose(self):
        for supports in ([], ['句号'], ['薄'], ['metadata-only']):
            self.story['evidence'][0]['supports']=supports
            self.assertFalse(validate_narrative(self.story,self.records,True)['keyword_matching_required'])

    def test_no_anchor_per_source_requirement(self):
        self.story.pop('evidence')
        for theme in self.story['themes']: theme.pop('evidence')
        self.assertEqual(validate_narrative(self.story,self.records,True)['anchors_checked'],0)

    def test_repeated_prose_is_an_editorial_choice(self):
        self.story['themes'][1]['text']=self.story['themes'][0]['text']
        self.assertFalse(validate_narrative(self.story,self.records)['repetition_checked'])

    def test_similar_text_does_not_gate_build(self):
        self.story['themes'][1]['text']=self.story['themes'][0]['text'].replace('这一则','那一则')+'。'
        self.assertFalse(validate_narrative(self.story,self.records)['repetition_checked'])

    def test_shared_source_can_have_multiple_topics_without_duplicate_anchor_metadata(self):
        self.story['themes'].append({'id':'plants-again','title':'另一视角','text':'另一段来源解读。','source_ids':['demo-a']})
        self.assertEqual(validate_narrative(self.story,self.records,True)['references_checked'],4)

    def test_distinct_passages_in_one_post_may_support_distinct_topics(self):
        self.story["themes"].append({"id": "book", "title": "重新翻开旧书", "text": "旧书的页边保留了过去的字迹；翻到这一页，也重新遇见了那时的想法。", "source_ids": ["demo-a"], "evidence": [self.book]})
        self.assertEqual(validate_narrative(self.story, self.records, True)["references_checked"], 4)

    def test_same_real_excerpt_can_appear_in_more_than_one_topic(self):
        quote=self.records[0]['text'][:13]
        self.records[1]['text']+=quote
        for theme in self.story['themes']: theme['excerpt']=quote
        validate_narrative(self.story,self.records)
        self.story['themes'][1]['excerpt']='这是伪造原话'
        self.rejected('摘句')

    def test_real_excerpt_may_be_the_page_body(self):
        self.story['themes'][0].update(text='窗台的薄荷又长了一片叶子。',excerpt='窗台的薄荷又长了一片叶子。')
        validate_narrative(self.story,self.records,True)

    def test_wishes_still_reject_unknown_source_ids(self):
        self.story['wishes']=[{'id':'w','title':'小事','text':'一段小事。','source_ids':['missing']}]
        self.rejected('来源ID')

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
