#!/usr/bin/env python3
"""Build a new offline journal from existing normalized data. Python 3.9+, no network."""
import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
    for r in source:
        if kind == "weibo":
            images = []
            for im in r.get("images", []):
                path = im.get("thumb_path") or im.get("large_path")
                if not path:
                    continue
                local_file(root, path)
                large = im.get("large_path") or path
                local_file(root, large)
                images.append({"path": path, "large": large, "caption": im.get("caption", "")})
            text = r.get("text", "")
            rows.append({"id": str(r["id"]), "date": day(r["created_at"]), "text": text,
                         "title": r.get("title") or re.sub(r"\s+", " ", text)[:26] or "一条记录",
                         "images": images, "url": r.get("url"), "links": r.get("links", [])})
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
    rows = normalize(root, meta, kind)
    by_id = {r["id"]: r for r in rows}
    def refs(value):
        ids = value.get("source_ids", [])
        if not ids or any(not isinstance(i, str) or i not in by_id for i in ids):
            raise ValueError("回顾、发现与计划必须关联真实字符串来源ID")
        return ids
    overview = story.get("overview", {})
    if not overview.get("text", "").strip() or len(overview["text"]) > 220:
        raise ValueError("先完成200字以内的真实回顾，不把数据范围说明当总结")
    if not overview.get("headline", "").strip() or len(overview["headline"]) > 36:
        raise ValueError("overview.headline 需由本批数据撰写，最多36字，不硬编码通用金句")
    refs(overview)
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
    plans = story.get("plans", [])
    if not plans:
        raise ValueError("story.plans 为空：先由 Agent 从真实记录生成3—6条建议，再构建；不交付空计划页")
    plan_ids = set()
    for p in plans:
        refs(p)
        if not p.get("id") or p["id"] in plan_ids or not p.get("title") or not p.get("reason") or not re.fullmatch(r"(?:19|20|21)\d{2}-(?:0[1-9]|1[0-2])", p.get("month", "")):
            raise ValueError("计划需唯一ID、标题、月份、依据 reason 和来源ID")
        plan_ids.add(p["id"])
    # Display image choices must actually belong to cited records, not a global unrelated gallery.
    for section in [overview] + themes:
        allowed = {im["path"]: (r, im) for i in section["source_ids"] for r in [by_id[i]] for im in r["images"]}
        choices = section.get("image_paths", [])
        if not choices:
            choices = list(allowed)[:3]
        if len(choices) != len(set(choices)):
            raise ValueError("同页图片重复")
        section["images"] = []
        for path in choices:
            if path not in allowed:
                raise ValueError("页面图片与来源ID不对应: " + str(path))
            r, im = allowed[path]
            caption = section.get("image_captions", {}).get(path) or im["caption"] or r["title"]
            section["images"].append({**im, "date": r["date"], "record_id": r["id"], "caption": caption})
    actual = {"start": rows[0]["date"], "end": rows[-1]["date"]}
    meta["actual_range"] = actual
    meta["plan_year"] = int(meta.get("plan_year") or datetime.now().year + 1)
    mode = "精选记录" if meta.get("mode") == "selected" else "已收录记录（完整性见覆盖说明）"
    scope = f'{actual["start"]} — {actual["end"]} · {len(rows)}条{mode}'
    requested = meta.get("requested_range", {})
    if requested.get("start", actual["start"]) < actual["start"]:
        scope += " · 更早范围未完整收录"
    identity = str(meta.get("project_id") or meta.get("target", {}).get("uid") or rows[0]["id"])
    project_key = hashlib.sha256((kind + ":" + identity).encode()).hexdigest()[:16]
    return {"version": 2, "project_key": project_key, "skin": skin, "meta": meta, "story": story,
            "coverage": coverage, "records": rows, "scope": scope}


def build(source, output, skin, template=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("输出与原项目必须分开，禁止嵌套或覆盖")
    if output.exists() and any(output.iterdir()):
        raise ValueError("输出目录不为空；选新目录，保留旧网页与手动计划")
    data = prepare(source, skin)  # validate before writing anything
    template = Path(template) if template else Path(__file__).resolve().parents[1] / "assets" / "starter"
    output.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "styles.css", "app.js", "core.js"):
        shutil.copyfile(template / filename, output / filename)
    js = "window.JOURNAL_DATA = " + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    (output / "journal-data.js").write_text(js, encoding="utf-8")
    paths = {im[k] for r in data["records"] for im in r["images"] for k in ("path", "large")}
    for name in paths:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_file(source, name), target)
    # Keep normalized raw data, but never copy browser state/cache/credentials from an old project.
    for filename in ("project_meta.json", "coverage.json", "story.json", "records.json" if data["meta"]["platform"] == "weibo" else "orders.json"):
        shutil.copyfile(source / filename, output / filename)
    bundle = "data.js" if data["meta"]["platform"] == "weibo" else "orders.js"
    global_name = "LIFE_ARCHIVE_DATA" if data["meta"]["platform"] == "weibo" else "CONSUMPTION_JOURNAL_DATA"
    raw_key = "records" if data["meta"]["platform"] == "weibo" else "orders"
    canonical = {"meta": data["meta"], "coverage": data["coverage"], "story": data["story"], raw_key: load(source / (raw_key + ".json"))}
    canonical_js = f"window.{global_name} = " + json.dumps(canonical, ensure_ascii=False).replace("<", "\\u003c") + ";\n"
    (output / bundle).write_text(canonical_js, encoding="utf-8")
    (output / "exports").mkdir(exist_ok=True)
    return {"output": str(output), "records": len(data["records"]), "themes": len(data["story"]["themes"]), "plans": len(data["story"]["plans"]), "images": len(paths), "skin": skin}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skin", required=True, choices=["paper", "frosted", "collage"])
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.source, args.output, args.skin), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, "未构建: " + str(error) + "\n")
