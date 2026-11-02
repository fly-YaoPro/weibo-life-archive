"""Synthetic offline regression for scanning, selection, media and optional experiences."""
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import urllib.error
import wave
import zlib

from archive_common import clean_html, load, save
from archive_pipeline import ingest, initialize, materialize, metrics, select
from browser_helpers import RouteBudget, capture_detail
from build_journal import build, prepare
from manage_media import download, image_info, plan, register_screenshots
from preflight import inspect_bundle
from test_build_journal import fixture


def png(width=2, height=2):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\0" + b"\xaa\xbb\xcc" * width) * height)) + chunk(b"IEND", b"")


def row(rid="r1", day="2025-03-01", **kw):
    return {"id": rid, "author_uid": "synthetic", "created_at": day + "T12:00:00+08:00",
            "text": "合成测试记录，不是真实用户经历", "is_original": True, "images": [], **kw}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "source"
        initialize(self.root, "synthetic", "https://weibo.com/u/synthetic", "2025-01-01", "2025-12-31")
        # Explicit alternate quota and optional video mode for these legacy scenarios.
        meta = load(self.root / "project_meta.json")
        meta["selection_policy"].update(monthly_limit=2, yearly_limit=24)
        meta["collection"]["include_video_covers"] = True
        save(self.root / "project_meta.json", meta)

    def tearDown(self):
        self.tmp.cleanup()

    def test_initialize_refuses_overwrite(self):
        before = (self.root / "project_meta.json").read_bytes()
        with self.assertRaises(ValueError):
            initialize(self.root, "other", "https://example.com", "2020-01-01", "2026-01-01")
        self.assertEqual(before, (self.root / "project_meta.json").read_bytes())

    def test_filters_reposts_author_and_range_but_keeps_video(self):
        rows = [row(), row("repost", is_repost=True), row("vid", is_video=True),
                row("author", author_uid="other"), row("old", "2024-01-01")]
        result = ingest(self.root, rows)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["batch"]["repost"], 1)
        videos = [r for r in load(self.root / "candidates.json") if r.get("is_video")]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["video"]["cover_status"], "unavailable")
        self.assertEqual(videos[0]["video"]["covers"], [])

    def test_original_must_be_observed(self):
        r = row()
        r.pop("is_original")
        with self.assertRaises(ValueError):
            ingest(self.root, [r])

    def test_numeric_or_naive_ids_and_time_rejected(self):
        for bad in (row(123), row(created_at="2025-01-01T12:00:00")):
            with self.subTest(row=bad), self.assertRaises((ValueError, TypeError)):
                ingest(self.root, [bad])

    def test_platform_nested_cards_and_html_cleanup(self):
        mblog = {"id": "raw1", "user": {"idstr": "synthetic"}, "created_at": "Sat Mar 01 12:00:00 +0800 2025",
                 "text": '合成<br>正文<script>evil()</script><a href="javascript:alert(1)">无效链接</a>', "pic_num": 0}
        ingest(self.root, {"ok": 1, "data": {"cards": [{"card_group": [{"mblog": mblog}]}]}})
        r = load(self.root / "candidates.json")[0]
        self.assertEqual(r["created_at"], "2025-03-01T12:00:00+08:00")
        self.assertNotIn("evil", r["text"])
        self.assertIn("\n", r["text"])
        self.assertEqual(r["links"], [])

    def test_error_envelope_not_registered_as_empty(self):
        with self.assertRaises(ValueError):
            ingest(self.root, {"ok": 0, "data": {"cards": []}}, "2025-03", "complete", "fake")
        self.assertFalse((self.root / "monthly_coverage.json").exists())

    def test_repeated_scan_preserves_full_text(self):
        ingest(self.root, [row(text="已核验的完整合成文本", text_status="complete")])
        ingest(self.root, [row(text="短摘要", text_status="pending")])
        self.assertEqual(len(load(self.root / "candidates.json")), 1)
        self.assertEqual(load(self.root / "candidates.json")[0]["text"], "已核验的完整合成文本")

    def test_month_registration_is_explicit(self):
        ingest(self.root, [row()])
        with self.assertRaises(ValueError):
            ingest(self.root, [], "2025-03", "complete", "")
        with self.assertRaises(ValueError):
            ingest(self.root, [row()], "2025-04", "complete", "not this month")
        ingest(self.root, [], "2025-03", "complete", "合成测试已核验整月")
        self.assertEqual(load(self.root / "monthly_coverage.json")[0]["status"], "complete")

    def test_monthly_cap_and_event_dedup(self):
        ingest(self.root, [row("a"), row("b", "2025-03-02"), row("c", "2025-03-03"), row("d", "2025-04-01")])
        select(self.root, [{"id": "a", "score": 10, "reason": "合成理由", "event_key": "same"},
                           {"id": "d", "score": 9, "reason": "重复事件", "event_key": "same"},
                           {"id": "b", "score": 8, "reason": "日常"}, {"id": "c", "score": 7, "reason": "另一天"}])
        materialize(self.root)
        self.assertEqual({r["id"] for r in load(self.root / "records.json")}, {"a", "b"})

    def test_yearly_cap_does_not_backfill_unrated(self):
        ingest(self.root, [row("a"), row("b", "2025-04-01"), row("c", "2025-05-01")])
        meta = load(self.root / "project_meta.json")
        meta["selection_policy"]["yearly_limit"] = 1
        save(self.root / "project_meta.json", meta)
        select(self.root, [{"id": "b", "score": 1, "reason": "真实阅读后的合成理由"}])
        materialize(self.root)
        self.assertEqual([r["id"] for r in load(self.root / "records.json")], ["b"])

    def test_invalid_scores_rejected_before_writing(self):
        ingest(self.root, [row()])
        for rating in ({"id": "missing", "score": 1, "reason": "x"}, {"id": "r1", "score": float("nan"), "reason": "x"}, {"id": "r1", "score": 2, "reason": ""}):
            with self.assertRaises(ValueError):
                select(self.root, [rating])
        self.assertFalse((self.root / "selection.json").exists())

    def test_metrics_do_not_use_capped_selected_counts(self):
        ingest(self.root, [row("a"), row("b"), row("c")], "2025-03", "complete", "合成完整月份")
        select(self.root, [{"id": i, "score": n, "reason": "合成取舍"} for n, i in enumerate(("a", "b", "c"))])
        materialize(self.root)
        m = load(self.root / "metrics.json")
        march = m["monthly"][2]
        self.assertEqual((march["published_count"], march["saved_count"]), (3, 2))
        self.assertIsNone(m["monthly"][0]["published_count"])
        self.assertFalse(m["complete"])
        self.assertIsNone(m["reading_count"])

    def test_metrics_reject_corrupt_index_and_coverage(self):
        meta = load(self.root / "project_meta.json")
        for candidates, coverage in (([row(), row()], []), ([row()], [{"month": "2025-03", "status": "complete", "note": ""}])):
            with self.assertRaises(ValueError):
                metrics(meta, candidates, coverage, [])

    def test_full_mode_does_not_require_selection(self):
        meta = load(self.root / "project_meta.json")
        meta["mode"] = "full"
        save(self.root / "project_meta.json", meta)
        ingest(self.root, [row()])
        self.assertEqual(materialize(self.root)["saved_count"], 1)
        self.assertEqual(load(self.root / "coverage.json")[0]["status"], "partial")

    def test_screenshot_registration_and_path_escape(self):
        ingest(self.root, [row()])
        select(self.root, [{"id": "r1", "score": 1, "reason": "合成"}])
        materialize(self.root)
        path = self.root / "capture-staging" / "test.png"
        path.parent.mkdir()
        path.write_bytes(png())
        obs = {"id": "r1", "url": "https://m.weibo.cn/detail/r1", "path": "capture-staging/test.png", "captured_at": "2025-03-01T12:00:00+08:00"}
        self.assertEqual(register_screenshots(self.root, [obs])["registered"], 1)
        with self.assertRaises(ValueError):
            register_screenshots(self.root, [{**obs, "path": "../outside.png"}])
        with self.assertRaises(ValueError):
            register_screenshots(self.root, [{**obs, "url": "https://example.com/wrong"}])

    def test_supplemented_photos_keep_downloaded_files_without_losing_new_photos(self):
        first = {"origin": "platform", "source_url": "https://wx1.sinaimg.cn/first.png", "download_status": "unavailable"}
        second = {"origin": "platform", "source_url": "https://wx1.sinaimg.cn/second.png", "download_status": "unavailable"}
        ingest(self.root, [row(images=[first])])
        select(self.root, [{"id": "r1", "score": 1, "reason": "合成"}])
        materialize(self.root)
        saved = load(self.root / "records.json")
        saved[0]["images"][0].update(thumb_path="images/cached.png", large_path="images/cached.png", download_status="saved")
        save(self.root / "records.json", saved)
        ingest(self.root, [row(images=[first, second], expected_image_count=2)])
        materialize(self.root)
        images = load(self.root / "records.json")[0]["images"]
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["thumb_path"], "images/cached.png")


class MediaTests(unittest.TestCase):
    def test_content_dedup_resume_and_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 用带随机噪声的真实图片：纯色/极小图 JPEG 无收益会被最小化逻辑保留为原格式，
            # 复杂图才能验证自动 JPEG 转换路径
            from io import BytesIO
            from PIL import Image
            import random
            random.seed(1)
            sample = Image.new("RGB", (48, 48))
            sample.putdata([(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                            for _ in range(48 * 48)])
            png_buffer = BytesIO()
            sample.save(png_buffer, "PNG")
            data = png_buffer.getvalue()
            image = {"origin": "platform", "source_url": "https://wx1.sinaimg.cn/test.png", "thumb_path": None, "large_path": None}
            save(root / "records.json", [row(images=[image])])
            plan(root)

            class Response(io.BytesIO):
                def geturl(self):
                    return image["source_url"]

            class Opener:
                calls = 0
                def open(self, *args, **kw):
                    self.calls += 1
                    return Response(data)

            opener = Opener()
            self.assertTrue(download(root, opener=opener)["ok"])
            self.assertEqual(opener.calls, 1)
            self.assertEqual(len(list((root / "images").glob("*"))), 1)
            self.assertTrue(download(root, opener=opener)["ok"])
            self.assertEqual(opener.calls, 1)
            im = load(root / "records.json")[0]["images"][0]
            self.assertEqual(im["thumb_dimensions"], {"width": 48, "height": 48})
            (root / im["thumb_path"]).write_bytes(b"corrupt")
            self.assertTrue(download(root, opener=opener)["ok"])
            self.assertEqual(opener.calls, 2)
            # 图片经过自动压缩，验证恢复后的文件是有效 JPEG 而非原始字节
            recovered = (root / im["thumb_path"]).read_bytes()
            recovered_ext, rw, rh = image_info(recovered)
            self.assertEqual(recovered_ext, "png")
            self.assertEqual((rw, rh), (48, 48))

    def test_blocked_host_does_not_make_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root / "records.json", [row(images=[{"origin": "platform", "source_url": "https://127.0.0.1/private"}])])
            plan(root)
            self.assertFalse(download(root)["ok"])

    def test_auth_failure_stops_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root / "records.json", [row(images=[{"origin": "platform", "source_url": "https://wx1.sinaimg.cn/a.png"}])])
            plan(root)

            class Denied:
                calls = 0
                def open(self, *args, **kw):
                    self.calls += 1
                    raise urllib.error.HTTPError("redacted", 403, "denied", {}, None)
            opener = Denied()
            self.assertFalse(download(root, opener=opener)["ok"])
            self.assertEqual(opener.calls, 1)
            self.assertEqual(load(root / "records.json")[0]["images"][0]["download_status"], "failed")

    def test_error_html_is_not_an_image(self):
        with self.assertRaises(ValueError):
            image_info(b"<html>login</html>")
        with self.assertRaises(ValueError):
            image_info(png()[:24])

    def test_stale_download_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root / "records.json", [row(images=[{"origin": "platform", "source_url": "https://wx1.sinaimg.cn/a.png"}])])
            plan(root)
            save(root / "records.json", [row(images=[{"origin": "platform", "source_url": "https://wx1.sinaimg.cn/b.png"}])])
            with self.assertRaises(ValueError):
                download(root)


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "source"
        self.root.mkdir()
        fixture(self.root)
        (self.root / "decorations").mkdir()
        (self.root / "decorations/test.png").write_bytes(png(800, 500))
        self.story = load(self.root / "story.json")
        self.story["scene"] = {"image_path": "decorations/test.png", "alt": "合成测试场景", "source_ids": ["demo-1"], "hotspots": [{"id": "h", "label": "合成物件", "description": "用于测试", "x": 30, "y": 50, "source_ids": ["demo-1"], "target": {"view": "review", "theme_id": "t1"}}]}
        self.story["letter"] = {"title": "合成未来信", "paragraphs": ["合成测试段落"], "closing": "测试结束", "source_ids": ["demo-1"], "image_path": "decorations/test.png", "image_alt": "合成测试结尾插画"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_extras_copied_and_old_import_has_honest_stats(self):
        save(self.root / "story.json", self.story)
        out = Path(self.tmp.name) / "journal"
        build(self.root, out, "paper")
        self.assertTrue((out / "decorations/test.png").exists())
        self.assertTrue((out / "favicon.svg").exists())
        self.assertEqual(load(out / "metrics.json")["basis"], "saved_records_only")

    def test_letter_cannot_replace_editable_plans(self):
        self.story["plans"] = []
        save(self.root / "story.json", self.story)
        with self.assertRaisesRegex(ValueError, "plans"):
            prepare(self.root, "paper")

    def test_bad_hotspots_and_false_annual_year_blocked(self):
        for mutate in (lambda s: s["scene"]["hotspots"][0].update(x=101),
                       lambda s: s["scene"]["hotspots"][0]["target"].update(theme_id="missing"),
                       lambda s: s.update(annual_reviews=[{"year": 2024, "title": "假年份", "text": "测试", "source_ids": ["demo-1"]}]),
                       lambda s: s["scene"].update(image_path="images/fake-history.png")):
            story = copy.deepcopy(self.story)
            mutate(story)
            save(self.root / "story.json", story)
            with self.assertRaises(ValueError):
                prepare(self.root, "paper")

    def test_local_music_is_copied(self):
        (self.root / "audio").mkdir()
        with wave.open(str(self.root / "audio/test.wav"), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b"\0\0" * 800)
        self.story["bgm"] = {"path": "audio/test.wav", "title": "合成静音测试", "origin": "generated", "reference": "合成测试夹具"}
        save(self.root / "story.json", self.story)
        out = Path(self.tmp.name) / "audio-journal"
        build(self.root, out, "paper")
        self.assertTrue((out / "audio/test.wav").exists())

    def test_preflight_detects_missing_bundle(self):
        skill = Path(__file__).resolve().parents[1]
        self.assertTrue(inspect_bundle(skill)["ok"])
        self.assertFalse(inspect_bundle(self.root)["ok"])

    def test_route_budget_independent_and_handoff_immediate(self):
        budget = RouteBudget()
        self.assertEqual(budget.record("detail", False), "verify_once")
        self.assertEqual(budget.record("list", True), "ready")
        self.assertEqual(budget.record("detail", False), "fallback")
        self.assertEqual(budget.record("image", False, blocked=True), "handoff")

    def test_browser_helper_verifies_author(self):
        class BU:
            def js(self, expression):
                return json.dumps({"url": "https://m.weibo.cn/detail/post1", "author_url": "https://m.weibo.cn/u/synthetic", "text": "合成", "images": []})
        selectors = {k: ".test" for k in ("article", "author", "text", "images", "time")}
        self.assertEqual(capture_detail(BU(), "post1", "synthetic", "2025-01-01T12:00:00+08:00", selectors)["text_status"], "complete")
        with self.assertRaises(ValueError):
            capture_detail(BU(), "post1", "wrong", "2025-01-01T12:00:00+08:00", selectors)


class BrowserHelperTests(unittest.TestCase):
    def test_route_checkpoint_survives_fresh_processes_and_stops_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "browser-routes.json"
            calls = []

            def failed():
                calls.append("detail")
                raise TimeoutError("response body must not be stored")

            self.assertEqual(RouteBudget(state_path=checkpoint).run("detail_api", failed)["status"], "verify_once")
            self.assertEqual(RouteBudget(state_path=checkpoint).run("detail_api", failed)["status"], "fallback")
            budget = RouteBudget(state_path=checkpoint)
            self.assertEqual(budget.run("detail_api", failed)["status"], "fallback")
            self.assertEqual(calls, ["detail", "detail"])
            self.assertNotIn("response body", checkpoint.read_text())
            self.assertEqual(budget.run("list_api", lambda: ["cached list"])["value"], ["cached list"])
            budget.resume("detail_api")
            self.assertEqual(RouteBudget(state_path=checkpoint).run("detail_api", lambda: "verified")["status"], "ready")

    def test_http_denial_handoff_is_saved_without_retry(self):
        for code in (401, 403, 429, 432):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                checkpoint = Path(tmp) / "browser-routes.json"
                calls = []

                def denied():
                    calls.append(code)
                    raise urllib.error.HTTPError("private URL", code, "private body", {}, None)

                self.assertEqual(RouteBudget(state_path=checkpoint).run("detail_api", denied)["status"], "handoff")
                self.assertEqual(RouteBudget(state_path=checkpoint).run("detail_api", denied)["status"], "handoff")
                self.assertEqual(calls, [code])
                self.assertNotIn("private", checkpoint.read_text())

    def test_success_resets_consecutive_failures_and_business_errors_are_recorded(self):
        budget = RouteBudget()
        self.assertEqual(budget.record("detail_api", False, http_status=404), "verify_once")
        self.assertEqual(budget.run("detail_api", lambda: "ok")["status"], "ready")
        self.assertEqual(budget.record("detail_api", False, http_status=404), "verify_once")
        self.assertEqual(budget.record("image", False, http_status=432), "handoff")
        self.assertEqual(budget.record("list_api", False, blocked=True), "handoff")

    def test_corrupt_checkpoint_and_invalid_budget_are_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "browser-routes.json"
            for state in ([], {"detail": {"failures": -1}}, {"detail": {"failures": 2, "status": "unknown"}}):
                save(checkpoint, state)
                before = checkpoint.read_bytes()
                with self.assertRaises(ValueError):
                    RouteBudget(state_path=checkpoint)
                self.assertEqual(checkpoint.read_bytes(), before)
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                RouteBudget(limit=limit)

    def test_business_error_envelope_counts_failures_before_marking_success(self):
        budget = RouteBudget()
        calls = []

        def response():
            calls.append("detail")
            return {"ok": 0, "status": 404}

        def validate(value):
            return {"success": value["ok"] == 1, "http_status": value["status"]}

        first = budget.run("detail_api", response, validate=validate)
        self.assertEqual(first["status"], "verify_once")
        self.assertIsNone(first["value"])
        self.assertEqual(first["reason"], "HTTP 404")
        self.assertEqual(budget.run("detail_api", response, validate=validate)["status"], "fallback")
        self.assertEqual(budget.run("detail_api", response, validate=validate)["status"], "fallback")
        self.assertEqual(calls, ["detail", "detail"])
        self.assertEqual(budget.run("list_api", lambda: {"captcha": True}, validate=lambda value:
                                    {"success": False, "blocked": value["captcha"]})["status"], "handoff")

    def test_invalid_detail_input_does_not_call_browser(self):
        class BU:
            calls = 0

            def js(self, expression):
                self.calls += 1

        bu = BU()
        selectors = {k: ".verified" for k in ("article", "author", "text", "images", "time")}
        with self.assertRaises(ValueError):
            capture_detail(bu, "post1", "synthetic", "昨天", selectors)
        with self.assertRaises(ValueError):
            capture_detail(bu, "post1", "synthetic", "2025-01-01T12:00:00+08:00", {**selectors, "images": ""})
        self.assertEqual(bu.calls, 0)

    def test_detail_requires_matching_article_and_filters_image_urls(self):
        observation = {"url": "https://weibo.com/synthetic/post1", "author_url": "https://weibo.com/u/synthetic",
                       "text": "合成", "time": "昨天", "images": [
                           "https://wx1.sinaimg.cn/a.png", "https://wx1.sinaimg.cn/a.png",
                           "https://wx1.sinaimg.com/b.png", "http://wx1.sinaimg.cn/c.png",
                           "https://user:password@wx1.sinaimg.cn/d.png", "https://example.com/card.png", None]}

        class BU:
            def js(self, expression):
                return json.dumps(observation)

        selectors = {k: ".verified" for k in ("article", "author", "text", "images", "time")}
        record = capture_detail(BU(), "post1", "synthetic", "2025-01-01T12:00:00+08:00", selectors)
        self.assertEqual(len(record["images"]), 2)
        self.assertEqual(record["created_at"], "2025-01-01T12:00:00+08:00")
        for url in ("https://weibo.com/other/post1", "https://weibo.com/u/post1", "https://example.com/detail/post1"):
            observation["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                capture_detail(BU(), "post1", "synthetic", record["created_at"], selectors)


if __name__ == "__main__":
    unittest.main()
