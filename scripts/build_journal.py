#!/usr/bin/env python3
"""Build a new offline journal from existing normalized data. Python 3.9+, no network."""
import argparse
import hashlib
import json
import re
import shutil
import base64
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from archive_common import BEIJING, load as load_optional, project_file
from archive_pipeline import metrics as calculate_metrics
from experience import validate_experience, validate_narrative, synthetic_fixture
from runtime_contract import validate_runtime, validate_video
from audit_images import audit as audit_images


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def local_file(root, name):
    if not isinstance(name, str) or not name or re.match(r"^[a-zA-Z]+:", name) or "\\" in name:
        raise ValueError("图片必须是项目内相对路径")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("图片路径越界或文件缺失: " + name)
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        raise ValueError("证据图片只接受本地栅格图，不执行 SVG/HTML: " + name)
    return path


def day(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("原始时间缺时区")
    return dt.astimezone(timezone(timedelta(hours=8))).date().isoformat()


def normalize(root, meta, kind):
    source = load(root / ("records.json" if kind == "weibo" else "orders.json"))
    rows = []
    def saved_images(values):
        images = []
        for im in values:
            # Web 端默认展示直接使用原图（original/large），缩略图仅作最终回退，避免列表图被拉伸发虚。
            path = im.get("display_path") or im.get("original_path") or im.get("large_path") or im.get("thumb_path")
            if not path:
                continue
            fixture_image = synthetic_fixture(meta) and im.get("origin") == "synthetic_fixture" and bool(im.get("provided_reference"))
            if path.startswith("decorations/") or (im.get("origin") not in {None, "platform", "user_provided"} and not fixture_image):
                raise ValueError("微博配图/视频封面不能用生成或库存图替代")
            local_file(root, path)
            large = im.get("original_path") or im.get("large_path") or path
            local_file(root, large)
            images.append({"path": path, "large": large, "original": im.get("original_path") or large,
                           "caption": im.get("caption", ""), "origin": im.get("origin", "platform"),
                           "provided_reference": im.get("provided_reference"),
                           "source_url": im.get("source_url"), "download_status": im.get("download_status")})
            images[-1].update(image_id=im.get('image_id'), large_note=im.get('large_note'), aliases=[im[k] for k in ('thumb_path','large_path','original_path','display_path') if im.get(k)])
        return images
    for r in source:
        if kind == "weibo":
            images = saved_images(r.get("images", []))
            text = r.get("text", "")
            rows.append({"id": str(r["id"]), "date": day(r["created_at"]), "text": text,
                         "author_uid": r.get('author_uid'), "created_at": r.get('created_at'),
                         "title": r.get("title") or re.sub(r"\s+", " ", text)[:26] or "一条记录",
                         "images": images, "url": r.get("url"), "links": r.get("links", []),
                         "screenshot": r.get("screenshot"), "text_status": r.get("text_status", "unknown"),
                         "expected_image_count": r.get("expected_image_count"),
                         "image_inventory_status": r.get('image_inventory_status'),
                         "image_count_basis": r.get('image_count_basis')})
            if r.get("is_video") or r.get("video"):
                video = r.get("video")
                validate_video(r, meta)
                covers = video.get("covers")
                rows[-1].update(is_video=True, video={**video, "covers": saved_images(covers), "observed_covers": covers})
        else:
            if not r.get("is_success"):
                continue
            images = []
            items = r.get("items", [])
            for it in items:
                path = it.get("image_path")
                if path:
                    local_file(root, path)
                    images.append({"path": path, "large": path, "caption": it.get("name", "商品"), "item_id": str(it["item_id"])})
            names = [it.get("name", "商品") for it in items]
            rows.append({"id": str(r["order_id"]), "date": day(r["placed_at"]), "text": "\n".join(names),
                         "title": r.get("display_title") or " / ".join(names)[:30] or "一笔订单",
                         "images": images, "url": r.get("url"), "category": r.get("category", "未分类")})
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("来源ID重复，请先运行数据检查器")
    if not rows:
        raise ValueError("没有可用记录，不制作空手账")
    return sorted(rows, key=lambda r: (r["date"], r["id"]))


def prepare(root, skin):
    meta, story, coverage = (load(root / p) for p in ("project_meta.json", "story.json", "coverage.json"))
    kind = meta["platform"]
    if kind not in {"weibo", "taobao"} or (kind == "taobao" and skin != "collage") or (kind == "weibo" and skin == "collage"):
        raise ValueError("微博使用 paper/frosted；淘宝使用 collage")
    image_audit = audit_images(root, meta) if kind == 'weibo' else None
    if image_audit and not image_audit['ok']:
        raise ValueError('图片未齐，不能构建完成版：' + '; '.join(image_audit['errors'][:5]))
    rows = normalize(root, meta, kind)
    contract = validate_runtime(meta, rows, story, root=root)
    by_id = {r["id"]: r for r in rows}
    grounding_required = meta.get("presentation", {}).get("grounding_required", False)
    narrative = contract['narrative']
    narrative["synthetic_fixture"] = synthetic_fixture(meta)
    if synthetic_fixture(meta):
        narrative["warning"] = "合成离线功能夹具；不是真实采集、用户经历或生图质量证明"
    def refs(value):
        ids = value.get("source_ids", [])
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or any(not isinstance(i, str) or i not in by_id for i in ids):
            raise ValueError("回顾、发现与计划必须关联真实字符串来源ID")
        return ids
    overview = story.get("overview", {})
    if not overview.get("text", "").strip() or len(overview["text"]) > 200:
        raise ValueError("先完成200字以内的真实回顾，不把数据范围说明当总结")
    if not overview.get("headline", "").strip() or len(overview["headline"]) > 36:
        raise ValueError("overview.headline 需由本批数据撰写，最多36字，不硬编码通用金句")
    refs(overview)
    opening, portrait = overview.get("opening"), overview.get("portrait")
    if opening is not None and (not isinstance(opening,str) or not opening.strip() or len(opening)>100):
        raise ValueError("封面开场白需100字内的非空文字")
    if portrait is not None:
        if not isinstance(portrait,dict) or not isinstance(portrait.get("text"),str) or not portrait["text"].strip() or len(portrait["text"])>160:
            raise ValueError("封面画像需160字内的有据解析")
        refs(portrait)
        if not isinstance(portrait.get("tags",[]),list) or any(not isinstance(t,str) or len(t)>12 for t in portrait.get("tags",[])):
            raise ValueError("画像标签需简短字符串数组")
    if meta.get("presentation",{}).get("cover_required") and (not opening or not portrait):
        raise ValueError("完整封面缺开场白或有据画像，请先由Agent完成内容")
    themes = story.get("themes", [])
    if not themes:
        raise ValueError("先根据已有数据整理主题，不制作空页")
    theme_ids = set()
    for t in themes:
        refs(t)
        if not t.get("id") or t["id"] in theme_ids:
            raise ValueError("主题ID缺失或重复")
        theme_ids.add(t["id"])
        if not t.get("title") or not t.get("text") or t.get("layout", "A") not in {"A", "B", "C"}:
            raise ValueError("主题需标题、短记和 A/B/C 布局")
        excerpt = t.get("excerpt")
        if excerpt and not any(excerpt in by_id[i]["text"] for i in t["source_ids"]):
            raise ValueError("摘句不在关联原文中，不可伪造原话")
    for f in story.get("findings", []):
        refs(f)
    if kind == "taobao" and not story.get("findings"):
        raise ValueError("淘宝总览需要有来源的发现，不能只放空便签")
    for m in story.get("milestones", []):
        refs(m)
    if story.get("song"):
        refs(story["song"])
    if meta.get("presentation", {}).get("archive_view", "calendar") not in {"auto", "calendar", "timeline"}:
        raise ValueError("archive_view 只能为 auto/calendar/timeline")
    wishes = story.get("wishes", [])
    if not isinstance(wishes, list): raise ValueError("wishes需为数组")
    if meta.get("presentation", {}).get("three_wishes_required") and len(wishes) != 3:
        raise ValueError("留给明天的小事需由Agent整理为恰好3件，不能截断或自动补空项")
    share = story.get("share", {})
    if meta.get("presentation", {}).get("share_letter_required") and (not isinstance(share.get("letter_text"), str) or not share["letter_text"].strip()):
        raise ValueError("先由Agent浓缩未来来信到share.letter_text，再生成分享图")
    if share.get("letter_text") and len(share["letter_text"]) > 240:
        raise ValueError("分享图中的来信请浓缩到240字以内，保留有据温暖内容")
    if meta.get("presentation",{}).get("share_entries_required") and not share.get("entries"):
        raise ValueError("先按真实微博逐条提炼分享节点share.entries，日期和照片必须属于同一source_id")
    for entry in share.get("entries", []):
        if entry.get("source_id") not in by_id or not entry.get("title") or not entry.get("text"):
            raise ValueError("分享节点需真实source_id、标题与提炼短记")
    wish_ids = set()
    for wish in wishes:
        refs(wish)
        if not wish.get("id") or wish["id"] in wish_ids or not wish.get("title") or not wish.get("text"):
            raise ValueError("小愿望需唯一ID、标题、温暖短记和真实来源ID")
        wish_ids.add(wish["id"])
    plans = story.setdefault("plans", [])
    if not plans:
        raise ValueError("story.plans 为空：先由 Agent 从真实记录生成具体、可选的计划，再构建；来信和只读愿望不能替代可编辑计划")
    plan_ids = set()
    for p in plans:
        refs(p)
        if not p.get("id") or p["id"] in plan_ids or not p.get("title") or not p.get("reason") or not re.fullmatch(r"(?:19|20|21)\d{2}-(?:0[1-9]|1[0-2])", p.get("month", "")):
            raise ValueError("计划需唯一ID、标题、月份、依据 reason 和来源ID")
        plan_ids.add(p["id"])
    # Display image choices must actually belong to cited records, not a global unrelated gallery.
    for section in [overview] + themes:
        allowed = {alias: (r, im) for i in section["source_ids"] for r in [by_id[i]]
                   for im in r["images"] + [{**cover, "media_kind": "video-cover"} for cover in r.get("video", {}).get("covers", [])]
                   for alias in [im["path"]]+im.get("aliases",[])}
        choices = section.get("image_paths", [])
        if not choices:
            choices = list(dict.fromkeys(im["path"] for _,im in allowed.values()))[:3]
        if len(choices) != len(set(choices)):
            raise ValueError("同页图片重复")
        section["images"] = []
        for path in choices:
            if path not in allowed:
                raise ValueError("页面图片与来源ID不对应: " + str(path))
            r, im = allowed[path]
            caption = section.get("image_captions", {}).get(path) or im["caption"] or r["title"]
            section["images"].append({**im, "date": r["date"], "record_id": r["id"], "caption": caption})
    if kind == "weibo" and any(r["images"] for r in rows) and not any(s["images"] for s in [overview] + themes):
        raise ValueError("回看页面全部无图：已下载的真实配图不能全部藏到档案里")
    actual = {"start": rows[0]["date"], "end": rows[-1]["date"]}
    meta["actual_range"] = actual
    meta["plan_year"] = int(meta.get("plan_year") or datetime.now(BEIJING).year + 1)
    mode = "精选记录" if meta.get("mode") == "selected" else "已收录记录"
    scope = f'{actual["start"]} — {actual["end"]} · {len(rows)}条{mode}'
    requested = meta.get("requested_range", {})
    if requested.get("start", actual["start"]) < actual["start"]:
        scope += " · 更早范围未完整收录"
    identity = str(meta.get("project_id") or meta.get("target", {}).get("uid") or rows[0]["id"])
    project_key = hashlib.sha256((kind + ":" + identity).encode()).hexdigest()[:16]
    extra_paths = set(contract['paths'])
    # Video posters are separate evidence assets. Include them in the packed
    # resource set as well as the copied files; images remains photo-only.
    extra_paths.update(im[key] for row in rows for im in row.get("video", {}).get("covers", []) for key in ("path", "large"))
    for row in rows:
        if row.get("screenshot"):
            shot = row["screenshot"]
            if shot.get("origin") != "browser_capture" or shot.get("source_url") != row.get("url"):
                raise ValueError("截图必须来自关联原帖的浏览器捕获")
            local_file(root, shot["path"])
            extra_paths.add(shot["path"])
    report = None
    if kind == "weibo":
        candidates = load_optional(root / "candidates.json")
        if candidates is not None:
            report = calculate_metrics(meta, candidates, load_optional(root / "monthly_coverage.json", []), load(root / "records.json"))
        else:
            # Older imports do not contain a scan index: counts refer only to saved records.
            report = calculate_metrics(meta, load(root / "records.json"), [], load(root / "records.json"))
            report["basis"] = "saved_records_only"
    return {"version": 4, "project_key": project_key, "skin": skin, "meta": meta, "story": story,
            "coverage": coverage, "records": rows, "scope": scope, "metrics": report, "narrative_validation": narrative,
            "image_audit": image_audit,
            "extra_paths": sorted(extra_paths)}


def build(source, output, skin, template=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("输出与原项目必须分开，禁止嵌套或覆盖")
    if output.exists() and any(output.iterdir()):
        raise ValueError("输出目录不为空；选新目录，保留旧网页与手动计划")
    data = prepare(source, skin)  # validate before writing anything
    template = (Path(template) if template else Path(__file__).resolve().parents[1] / "assets" / "starter").resolve()
    if not template.is_dir() or output == template or output.is_relative_to(template) or template.is_relative_to(output):
        raise ValueError("模板需为独立现有目录，不能与输出目录嵌套或覆盖")
    output.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "styles.css", "app.js", "core.js", "plans.js", "fusion.css", "experience.js", "experience.css", "frosted.css", "paper.css", "reader.js", "motion.js", "motion.css", "share.js", "favicon.svg"):
        shutil.copyfile(template / filename, output / filename)
    js = "window.JOURNAL_DATA = " + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    (output / "journal-data.js").write_text(js, encoding="utf-8")
    if data.get('image_audit'):
        (output / 'image-audit.json').write_text(json.dumps(data['image_audit'], ensure_ascii=False, indent=2), encoding='utf-8')
    paths = {im[k] for r in data["records"] for im in r["images"] for k in ("path", "large")}
    paths.update(im[k] for r in data["records"] for im in r.get("video", {}).get("covers", []) for k in ("path", "large"))
    paths.update(data["extra_paths"])
    if data["meta"]["platform"]=="weibo":
        paths.update(im[k] for row in load(source/"records.json") for im in row.get("images",[]) for k in ("thumb_path","large_path","original_path","display_path") if im.get(k))
    embedded = {name: 'data:' + (mimetypes.guess_type(name)[0] or 'application/octet-stream') + ';base64,' + base64.b64encode(project_file(source,name).read_bytes()).decode('ascii') for name in paths}
    (output / 'journal-assets.js').write_text('window.JOURNAL_ASSETS=' + json.dumps(embedded,ensure_ascii=False).replace('<','\\u003c') + ';\n',encoding='utf-8')
    for name in paths:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project_file(source, name), target)
    # Keep normalized raw data, but never copy browser state/cache/credentials from an old project.
    for filename in ("project_meta.json", "coverage.json", "story.json", "records.json" if data["meta"]["platform"] == "weibo" else "orders.json"):
        shutil.copyfile(source / filename, output / filename)
    bundle = "data.js" if data["meta"]["platform"] == "weibo" else "orders.js"
    global_name = "LIFE_ARCHIVE_DATA" if data["meta"]["platform"] == "weibo" else "CONSUMPTION_JOURNAL_DATA"
    raw_key = "records" if data["meta"]["platform"] == "weibo" else "orders"
    canonical = {"meta": data["meta"], "coverage": data["coverage"], "story": data["story"], raw_key: load(source / (raw_key + ".json"))}
    canonical_js = f"window.{global_name} = " + json.dumps(canonical, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    (output / bundle).write_text(canonical_js, encoding="utf-8")
    if data.get("metrics"):
        (output / "metrics.json").write_text(json.dumps(data["metrics"], ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "exports").mkdir(exist_ok=True)
    return {"output": str(output), "records": len(data["records"]), "themes": len(data["story"]["themes"]), "plans": len(data["story"]["plans"]), "images": sum(Path(p).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"} for p in paths), "media_files": len(paths), "skin": skin}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skin", required=True, choices=["paper", "frosted", "collage"])
    parser.add_argument("--template", type=Path, help="可选现有模板目录；默认使用随技能打包的starter")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.source, args.output, args.skin, args.template), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, "未构建: " + str(error) + "\n")
