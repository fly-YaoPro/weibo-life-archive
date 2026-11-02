#!/usr/bin/env python3
"""Recover known demo media into a NEW, explicitly synthetic offline fixture.

No network, account or image generation calls. This is functional test material,
not collection proof or an image-quality approval. Existing output is preserved.
"""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from archive_common import save


def create(output, demo_html):
    output, demo_html = Path(output).resolve(), Path(demo_html).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("夹具输出非空；使用新目录，保留既有验证材料")
    html = demo_html.read_text(encoding="utf-8")
    data = json.loads(re.search(r"window.JOURNAL_DATA = (.*?);\n", html).group(1))
    assets = json.loads(re.search(r"window.JOURNAL_ASSETS=(.*?);\n", html).group(1))
    # Require the known, explicitly synthetic demo rather than arbitrary HTML.
    if "合成测试代码插画" not in data.get("story", {}).get("scene", {}).get("alt", ""):
        raise ValueError("只恢复明确标注的既有合成演示，不把任意手账当测试来源")
    output.mkdir(parents=True, exist_ok=True)
    source_label = demo_html.name + " 中已标注的合成离线素材"
    def asset(old, new):
        value = assets[old]
        if ";base64," not in value:
            raise ValueError("演示资源不是内嵌base64")
        path = output / new
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(value.split(",", 1)[1], validate=True))
        return new
    def image(old, name):
        path = asset(old, "images/" + name + ".jpg")
        return {"image_id":name,"large_note":"Explicit synthetic test fixture uses one small test image for both views", "origin": "synthetic_fixture", "provided_reference": source_label,
                "download_status": "saved", "thumb_path": path, "large_path": path, "original_path": path,
                "caption": "合成演示素材，非微博历史照片"}
    keys = ["plant", "book", "road", "music", "desk", "flower"]
    terms = ["薄荷", "旧书", "小路", "曲子", "桌面", "雨后"]
    records = []
    for n, (key, term) in enumerate(zip(keys, terms)):
        row = data["records"][n]
        rid = "demo-" + key
        records.append({"id": rid, "author_uid": "demo-synthetic", "created_at": row["date"] + "T12:00:00+08:00",
                        "text": row["text"], "url": "https://example.invalid/synthetic-weibo/" + rid,
                        "selected": True, "images": [image("images/original-" + row["id"] + "-0.jpg", key)],
                        "text_status": "complete", "fixture": True, "expected_image_count": 1})
    records.append({"id": "demo-plant-next", "author_uid": "demo-synthetic", "created_at": "2024-04-20T12:00:00+08:00",
                    "text": "换季时给薄荷换了一个大一点的花盆。浇过水后，窗台又多了一点绿意。", "selected": True,
                    "url": "https://example.invalid/synthetic-weibo/demo-plant-next", "images": [], "text_status": "complete", "fixture": True})
    records.append({"id": "demo-video", "author_uid": "demo-synthetic", "created_at": "2025-07-20T12:00:00+08:00",
                    "text": "把练习曲子的片段录下来，听见了前几次没注意到的停顿。下一次想把这几个小节接得更顺。", "selected": True,
                    "url": "https://example.invalid/synthetic-weibo/demo-video", "images": [], "text_status": "complete", "fixture": True,
                    "is_video": True, "video": {"source_url": "https://example.invalid/synthetic-weibo/demo-video", "cover_status": "observed",
                                                 "covers": [image("images/original-103-0.jpg", "video-cover")]}})
    for r in records:
        r.update(expected_image_count=len(r['images']), image_inventory_status='complete', image_count_basis='Explicit synthetic fixture inventory, not a platform observation')
    evidence = [{"source_id": r["id"], "quote": r["text"].split("。")[0] + "。", "supports": [term]}
                for r, term in zip(records, terms + ["薄荷", "曲子"])]
    all_ids = [r["id"] for r in records]
    titles = ["窗台上的小变化", "旧书里留着从前的字", "灯亮时的小路", "练习慢慢有了回声", "桌面腾出一点余地", "雨后停下来看一眼"]
    texts = ["从一片新叶到换一个花盆，薄荷把两段不同日子的照料连在了一起。这样的变化很轻，回看时却能认出你的用心。",
             "重新翻开旧书，页边的字还在原处。那些曾经遥远的想法，终于变成今天可以伸手触到的一页。",
             "小路的灯亮起来时，一天也慢慢走到了尾声。那句‘今天也还不错’，为这段归途留下了安稳的落点。",
             "先把曲子从头弹到尾，再把练习录下来听一遍。完整与停顿都值得记住，它们让下一次的练习有了具体的方向。",
             "桌面整理好以后，那只杯子被留了下来。腾出的位置不必马上填满，日常也可以在一点余地里舒展开。",
             "雨后路边的花，让你想起抬头看看天空。拍下一张照片，也是给匆匆的一天留一个可以停靠的瞬间。"]
    themes = []
    for n, key in enumerate(keys):
        ids = ["demo-" + key] + (["demo-plant-next"] if key == "plant" else ["demo-video"] if key == "music" else [])
        themes.append({"id": "t-" + key, "title": titles[n], "text": texts[n], "source_ids": ids, "layout": "ABC"[n % 3],
                       "excerpt": records[n]["text"].split("。")[0] + "。", "image_paths": [records[n]["images"][0]["thumb_path"]]})
    themes[3]["image_paths"] = [records[-1]["video"]["covers"][0]["thumb_path"]]
    objects = [{"name": "窗台薄荷", "evidence": evidence[0]["quote"], "source_ids": ["demo-plant"], "placement": "窗边左下约33%/60%", "representation": "symbolic", "rationale": "合成图中植物象征测试原文的薄荷，不声称复原真实家中物件"},
               {"name": "旧书", "evidence": evidence[1]["quote"], "source_ids": ["demo-book"], "placement": "桌上中间约62%/72%", "representation": "symbolic", "rationale": "合成图中书堆呼应测试旧书片段"},
               {"name": "台灯", "evidence": evidence[2]["quote"], "source_ids": ["demo-road"], "placement": "桌右侧约83%/50%", "representation": "symbolic", "rationale": "台灯象征测试原文中路上的灯光，不推断真实台灯所有权"}]
    scene_ids = ["demo-plant", "demo-book", "demo-road"]
    story = {"evidence": evidence, "overview": {"headline": "合成演示 · 把平常的一天留在纸上", "text": "薄荷、旧书、小路、曲子、桌面和雨后的一朵花，串起了几则合成测试记录。它们没有宏大的转折，却各自留下了一个可以再次停留的瞬间。",
              "opening": "合成演示：翻开窗台的新叶、旧书的页边和一段练习曲。", "source_ids": all_ids,
              "portrait": {"title": "从测试片段里看见的日常", "text": "这些合成片段中，你留意薄荷的变化，重读旧书，也愿意为一段曲子多练习几次。记录让喜欢的事有了可以回看的位置。", "source_ids": ["demo-plant", "demo-book", "demo-music"], "tags": ["植物", "阅读", "练习"]},
              "image_paths": [records[0]["images"][0]["thumb_path"], records[1]["images"][0]["thumb_path"]]},
             "themes": themes, "plans": [], "scene": {"image_path": asset("decorations/room.png", "decorations/room.png"),
              "alt": "合成代码几何场景，仅测试交互布局，不是本轮生图或美术质量证明", "source_ids": scene_ids, "objects": objects,
              "guidance": "合成演示：窗边新叶和桌上旧书，藏着几段小日常。", "mobile_guidance": "找找新叶和旧书。",
              "hotspots": [{"id": "h-plant", "object_name": "窗台薄荷", "label": "窗台新叶", "description": "薄荷的新叶，把一次浇水留成了记号。", "source_ids": ["demo-plant"], "x": 33, "y": 59, "effect": "breeze", "target": {"view": "review", "theme_id": "t-plant"}, "image_paths": [records[0]["images"][0]["thumb_path"]]},
                           {"id": "h-book", "object_name": "旧书", "label": "页边笔记", "description": "旧书里，还留着从前写下的字。", "source_ids": ["demo-book"], "x": 62, "y": 72, "effect": "sparkle", "target": {"view": "review", "theme_id": "t-book"}},
                           {"id": "h-lamp", "object_name": "台灯", "label": "路上灯光", "description": "小路上亮起的灯，是一天结束时的落点。", "source_ids": ["demo-road"], "x": 83, "y": 50, "effect": "glow", "target": {"view": "calendar", "date": "2023-05-12"}}]},
             "letter": {"title": "给下一段日子的你", "paragraphs": ["薄荷的新叶、旧书的页边，还有灯亮时的小路，都在这里留了一小会儿。它们提醒你，平常日子也有值得收藏的细节。",
                "曲子可以慢慢练，桌面可以留一点空白，雨后也可以再抬头看一次天空。愿你给这些喜欢的事，留出舒服的时间。"],
              "closing": "愿下一次翻开时，你还能认出此刻留下的小小欢喜。", "source_ids": all_ids, "image_source_ids": scene_ids,
              "image_path": asset("decorations/letter.png", "decorations/letter.png"), "objects": [{**obj, "placement": "结尾测试图的窗边/桌面静物"} for obj in objects]},
             "wishes": [{"id": "w-plant", "title": "再看看窗台的新叶", "text": "给薄荷浇水时，也给自己留一小会儿安静。", "source_ids": ["demo-plant"]},
                        {"id": "w-book", "title": "翻一页熟悉的旧书", "text": "旧书里的字不用急着读完，一页也足够。", "source_ids": ["demo-book"]},
                        {"id": "w-music", "title": "把一小段曲子弹给自己", "text": "曲子可以慢慢练，听听这一次的变化。", "source_ids": ["demo-music"]}],
             "share": {"headline": "合成演示 · 留住日常的小变化", "text": "功能夹具，不是真实微博或用户经历", "letter_text": "愿你给薄荷、旧书和曲子留一点时间，也在雨后抬头看一看。那些轻轻的日常，值得被好好记住。",
                       "entries": [{"source_id": "demo-" + key, "title": titles[n], "text": texts[n]} for n, key in enumerate(keys)]},
             "bgm": {**data["story"]["bgm"], "path": asset("audio/warm-lights.wav", "audio/warm-lights.wav"), "reference": "既有明确合成demo中的prepare_music.py原创合成音频；非本轮采集"}}
    story["share"]["entries"][3] = {"source_id": "demo-video", "title": "听见练习里的小停顿",
                                      "text": "把练习曲子的片段录下来，才听见了之前遗漏的停顿。下一次怎么练，也因此有了更具体的方向。"}
    story['plans']=[{'id':'plan-'+str(n),'title':w['title'],'reason':w['text'],'month':'2027-0'+str(n+1),'source_ids':w['source_ids']} for n,w in enumerate(story['wishes'])]
    profile = {"uid": "demo-synthetic", "name": "合成演示 · 晴日慢慢", "source_url": "https://weibo.com/u/demo-synthetic", "captured_at": "2026-11-01T00:00:00+08:00",
               "avatar_origin": "synthetic_fixture", "provided_reference": source_label, "avatar_path": asset("profile/avatar.png", "profile/avatar.png"),
               **{key: {"display": "—", "value": None, "exact": False, "observed": False} for key in ("followers", "following", "engagement")}}
    meta = {"schema_version": 1, "platform": "weibo", "project_id": "synthetic-trace-repair", "title": "合成演示 · 日子慢慢", "mode": "selected", "timezone": "Asia/Shanghai", "plan_year": 2027,
            "target": {"uid": "demo-synthetic", "profile_url": profile["source_url"]}, "profile": profile,
            "requested_range": {"start": "2023-01-01", "end": "2025-12-31"},
            "presentation": {"grounding_required": True, "experience_required": True, "profile_required": True, "cover_required": True, "three_wishes_required": True, "share_letter_required": True, "share_entries_required": True, "archive_view": "calendar"},
            "fixture": {"synthetic": True, "label": "合成离线功能夹具，不是真实微博/头像/用户经历", "source": source_label, "no_live_collection": True, "no_new_image_generation": True}}
    coverage = [{"year": year, "status": "selected", "scanned_count": None, "saved_count": sum(r["created_at"].startswith(str(year)) for r in records),
                 "selected_count": sum(r["created_at"].startswith(str(year)) for r in records), "note": "合成测试年份，不是真实账号覆盖证明"} for year in (2023, 2024, 2025)]
    for name, value in (("project_meta.json", meta), ("records.json", records), ("story.json", story), ("coverage.json", coverage)):
        save(output / name, value)
    manifest = {"synthetic": True, "purpose": "offline functional regression; no real collection or generated-art approval", "recovered_from": str(demo_html),
                "source_sha256": hashlib.sha256(demo_html.read_bytes()).hexdigest(), "media": [{"path": str(p.relative_to(output)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.rglob("*")) if p.is_file() and p.suffix in {".jpg", ".png", ".wav"}]}
    save(output / "fixture-provenance.json", manifest)
    return {"output": str(output), "records": len(records), "themes": len(themes), "synthetic": True, "no_live_collection": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-html", type=Path, required=True, help="明确标注合成的既有v4演示HTML")
    args = parser.parse_args()
    try:
        print(json.dumps(create(args.output, args.from_html), ensure_ascii=False))
    except (ValueError, OSError, KeyError, AttributeError) as error:
        parser.exit(1, str(error) + "\n")
