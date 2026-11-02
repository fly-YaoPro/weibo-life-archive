#!/usr/bin/env python3
"""Offline ingest, checkpoint, monthly selection and publication metrics. Never logs in."""
import argparse
import calendar
from collections import Counter
from datetime import datetime
import math
import re
from pathlib import Path

from archive_common import BEIJING, clean_html, date_key, identifier, load, merge_media, months, repair_media_urls, save, timestamp
from weibo_web import mid_to_bid


def initialize(root, uid, profile_url, start, end, mode="selected", title="人生手账", skin="paper"):
    root = Path(root)
    if (root / "project_meta.json").exists():
        raise ValueError("项目已存在；直接 ingest/select/materialize 续跑，不覆盖原始设置")
    list(months(start, end))
    meta = {"schema_version": 1, "platform": "weibo", "title": title, "mode": mode,
            "timezone": "Asia/Shanghai", "target": {"uid": identifier(uid), "profile_url": profile_url},
            "requested_range": {"start": start, "end": end}, "skin": skin,
            "selection_policy": {"monthly_limit": 5, "yearly_limit": 30},
            "collection": {"include_video_covers": False},
            "presentation": {"archive_view": "calendar", "experience_required": False, "cover_required": False, "profile_required": False, "grounding_required": True, "three_wishes_required": False, "share_letter_required": False, "share_entries_required": True}}
    save(root / "project_meta.json", meta)
    save(root / "progress.json", {"schema_version": 1, "target_uid": uid, "stage": "initialized"})
    return {"stage": "initialized", "requested_range": meta["requested_range"]}


def flatten(payload):
    """Accept cached desktop timeline, m.weibo cards or explicit DOM/export records."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("输入必须是记录数组或 cards/records 包装")
    if "ok" in payload and payload["ok"] != 1:
        raise ValueError("平台返回业务失败；不要将空响应登记为没有发布")
    if "records" in payload:
        return payload["records"]
    data = payload.get("data", payload)
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return data["list"]
    if "cards" not in data:
        raise ValueError("未识别的数据结构；先核验正常页面，不反复猜接口")
    out = []

    def walk(cards):
        for card in cards:
            if "mblog" in card:
                out.append(card["mblog"])
            walk(card.get("card_group", []))
    walk(data["cards"])
    return out


def observed_image_url(value):
    """Weibo image descriptors may be a URL string or an observed {url, width, height}."""
    if isinstance(value, dict): value = value.get("url")
    return value if isinstance(value, str) and value.strip() else None


def normalize(row, uid):
    author = row.get("author_uid") or row.get("user", {}).get("idstr") or row.get("user", {}).get("id")
    if str(author) != uid:
        return None, "other_author"
    # Original is verified from the platform structure or an explicit DOM observation.
    raw_platform = isinstance(row.get("user"), dict) and ("text" in row or "text_raw" in row)
    if row.get("retweeted_status") or row.get("is_repost") or row.get("is_original") is False:
        return None, "repost"
    if not raw_platform and row.get("is_original") is not True:
        raise ValueError("导入/DOM记录须显式核验 is_original:true，不能只凭作者相同")
    media = row.get("page_info") or {}
    is_video = bool(row.get("is_video") or row.get("video") or media.get("type") == "video" or media.get("object_type") == "video")
    observed_id = row.get("idstr") or row.get("id")
    if raw_platform and type(observed_id) is int: observed_id = str(observed_id)
    rid = identifier(observed_id)
    if uid.isdigit() and not rid.isdigit():
        raise ValueError("微博ID必须来自真实平台mid；摘要哈希仅可用于未识别观察，不能造原帖链接")
    if raw_platform and isinstance(row.get("text_raw"), str):
        text, links = row["text_raw"], clean_html(row.get("text", ""))[1]
    else:
        text, links = clean_html(row["text"]) if raw_platform or row.get("text_format") == "html" else (row.get("text", ""), row.get("links", []))
    images = row.get("images")
    if images is None:
        images = []
        infos = row.get("pic_infos") or {}
        for pid in row.get("pic_ids") or infos.keys():
            pic = infos.get(str(pid), {})
            source = next(((pic.get(size) or {}).get("url") for size in ("largest", "original", "large", "bmiddle", "thumbnail") if (pic.get(size) or {}).get("url")), None)
            if source:
                images.append({"origin": "platform", "source_url": source,
                               "thumb_url": (pic.get("thumbnail") or {}).get("url") or source,
                               "large_url": (pic.get("large") or pic.get("bmiddle") or {}).get("url") or source,
                               "original_url": (pic.get("largest") or pic.get("original") or {}).get("url"),
                               "thumb_path": None, "large_path": None, "download_status": "unavailable"})
        for pic in row.get("pics") or []:
            source = (pic.get("large") or {}).get("url") or pic.get("url")
            if source and not any(im.get("source_url") == source for im in images):
                images.append({"origin": "platform", "source_url": source,
                               "thumb_url": pic.get("url") or source, "large_url": source,
                               "original_url": pic.get("original_pic"),
                               "thumb_path": None, "large_path": None, "download_status": "unavailable"})
    expected = row.get("expected_image_count", row.get("pic_num", len(row["pic_ids"]) if isinstance(row.get("pic_ids"), list) else None))
    if (expected is not None and (type(expected) is not int or expected < 0)) or not isinstance(text, str) or not isinstance(images, list):
        raise ValueError("正文/图片数组/图片数量类型不正确")
    basis = row.get('image_count_basis') or ('platform pic_num=' + str(row['pic_num']) if type(row.get('pic_num')) is int else
             'platform pic_ids inventory=' + str(len(row['pic_ids'])) if isinstance(row.get('pic_ids'),list) else '')
    inventory = row.get('image_inventory_status') or ('complete' if basis and expected == len(images) else 'partial' if expected is not None else 'unknown')
    for image in images:
        if isinstance(image,dict) and not image.get('image_id'):
            image['image_id'] = str(image.get('pid') or image.get('source_url') or '')
    url = row.get("url") or ("https://weibo.com/" + uid + "/" + mid_to_bid(rid) if rid.isdigit() and uid.isdigit() else "https://m.weibo.cn/detail/" + rid)
    if uid.isdigit():
        from weibo_web import permalink_mid
        if permalink_mid(url, uid) != rid:
            raise ValueError("记录ID与原帖链接不一致")
    video = None
    if is_video:
        observed = row.get("video") or {}
        covers = observed.get("covers")
        if covers is None:
            detail = media.get("media_info") or {}
            big_info = detail.get("big_pic_info") or {}
            large = observed_image_url(big_info.get("pic_big")) or observed_image_url(big_info)
            small = observed_image_url(media.get("page_pic")) or observed_image_url(big_info.get("pic_small"))
            covers = [{"origin": "platform", "source_url": large or small,
                       "thumb_url": small or large, "large_url": large or small,
                       "thumb_path": None, "large_path": None, "download_status": "unavailable"}] if large or small else []
        if not isinstance(covers, list) or any(not isinstance(im, dict) or im.get("origin") != "platform" for im in covers):
            raise ValueError("视频封面必须是核验后的平台图片数组")
        if any(not isinstance(im.get("source_url"), str) or not im["source_url"].strip()
               or any(im.get(key) is not None and not isinstance(im[key], str) for key in ("thumb_url", "large_url", "original_url")) for im in covers):
            raise ValueError("视频封面URL必须是字符串，先提取真实描述对象的url字段")
        video = {"source_url": url, "covers": covers,
                 "cover_status": "observed" if covers else "unavailable"}
    collapsed = bool(row.get("isLongText") or row.get("is_long_text") or row.get("truncated") or row.get("text_truncated"))
    if raw_platform and re.search(r'<a\b[^>]*>\s*(?:展开全文|全文|展开)\s*</a>', row.get("text", ""), re.I):
        collapsed = True
    text_status = "pending" if collapsed else row.get("text_status") or "complete"
    record = {"id": rid, "author_uid": uid, "created_at": timestamp(row["created_at"]),
            "raw_created_at": row["created_at"], "text": text, "links": links,
            "url": url, "is_original": True, "is_video": is_video, "selected": False, "images": images,
            "text_status": text_status,
            "expected_image_count": expected, 'image_count_basis': basis, 'image_inventory_status': inventory}
    if video is not None: record["video"] = video
    return record, None


def ingest(root, payload, scan_month=None, scan_status=None, note=""):
    root = Path(root)
    meta = load(root / "project_meta.json")
    if not meta:
        raise ValueError("先 init 或提供已有 project_meta.json")
    uid, window = meta["target"]["uid"], meta["requested_range"]
    existing = {r["id"]: r for r in load(root / "candidates.json", [])}
    counts = Counter()
    incoming = []
    for row in flatten(payload):
        observed_author = row.get("author_uid") or row.get("user", {}).get("idstr") or row.get("user", {}).get("id")
        if str(observed_author) == uid and "created_at" in row and not window["start"] <= date_key(row["created_at"]) <= window["end"]:
            counts["out_of_range"] += 1
            continue
        record, reason = normalize(row, uid)
        if reason:
            counts[reason] += 1
            continue
        if record.get('is_video') and not meta.get('collection', {}).get('include_video_covers', False):
            counts['video_excluded'] += 1
            continue
        day = date_key(record["created_at"])
        if not window["start"] <= day <= window["end"]:
            counts["out_of_range"] += 1
            continue
        if scan_month and not day.startswith(scan_month):
            raise ValueError("标记整月覆盖时输入含其他月份；分开登记覆盖证据")
        old = existing.get(record["id"])
        if old:
            # A repeated list scan must not erase a previously fetched full text or local media.
            if old.get("text_status") == "complete" and record["text_status"] != "complete":
                record.update(text=old["text"], text_status="complete", links=old.get("links", []))
            record["images"] = merge_media(record["images"], old.get("images", []))
            if old.get("video"):
                record.setdefault("video", {**old["video"], "covers": []})
                record["is_video"] = True
                record["video"]["covers"] = merge_media(record["video"]["covers"], old["video"].get("covers", []))
                record["video"]["cover_status"] = "observed" if record["video"]["covers"] else "unavailable"
            known_counts=[value for value in (record['expected_image_count'],old.get('expected_image_count')) if type(value) is int]
            record['expected_image_count']=max(known_counts) if known_counts else None
            if not record.get('image_count_basis') and old.get('image_inventory_status')=='complete':
                record['image_count_basis']=old.get('image_count_basis','')
                record['image_inventory_status']='complete' if len(record['images'])==record['expected_image_count'] else 'partial'
            for field in ("screenshot", "selection_reason", "selected"):
                if field in old:
                    record[field] = old[field]
        existing[record["id"]] = record
        incoming.append(record["id"])
        counts["accepted"] += 1
    coverage = load(root / "monthly_coverage.json", [])
    if scan_month:
        if scan_month not in set(months(window["start"], window["end"])) or scan_status not in {"complete", "partial", "failed"} or not note.strip():
            raise ValueError("覆盖须指定窗口内月份、complete/partial/failed 和实际核验依据 note")
        coverage = [c for c in coverage if c["month"] != scan_month]
        coverage.append({"month": scan_month, "status": scan_status, "note": note})
    rows = sorted(existing.values(), key=lambda r: (r["created_at"], r["id"]))
    save(root / "candidates.json", rows)
    save(root / "monthly_coverage.json", sorted(coverage, key=lambda c: c["month"]))
    save(root / "progress.json", {"schema_version": 1, "target_uid": uid, "stage": "scanned",
                                 "candidate_count": len(rows), "last_batch_ids": incoming,
                                 "updated_at": datetime.now(BEIJING).isoformat()})
    return {"candidate_count": len(rows), "batch": dict(counts)}


def select(root, ratings):
    root = Path(root)
    meta, rows = load(root / "project_meta.json"), load(root / "candidates.json", [])
    by_id = {r["id"]: r for r in rows}
    policy = meta.get("selection_policy", {"monthly_limit": 5, "yearly_limit": 30})
    for key in ("monthly_limit", "yearly_limit"):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise ValueError("精选配额必须为正整数")
    ranked, seen = [], set()
    for rating in ratings:
        rid = identifier(rating.get("id"))
        score = rating.get("score")
        if rid not in by_id or rid in seen or type(score) not in (int, float) or not math.isfinite(score) or not rating.get("reason", "").strip():
            raise ValueError("评分需唯一真实ID、有限分值和人工阅读后的入选依据")
        seen.add(rid)
        ranked.append(rating)
    selected, month_counts, year_counts, events = [], Counter(), Counter(), set()
    for rating in sorted(ranked, key=lambda v: (-v["score"], by_id[v["id"]]["created_at"], v["id"])):
        row = by_id[rating["id"]]
        day = date_key(row["created_at"])
        event = rating.get("event_key")
        if month_counts[day[:7]] >= policy["monthly_limit"] or year_counts[day[:4]] >= policy["yearly_limit"] or (event and event in events):
            continue
        selected.append({"id": row["id"], "reason": rating["reason"], "score": rating["score"]})
        month_counts[day[:7]] += 1
        year_counts[day[:4]] += 1
        if event:
            events.add(event)
    result = {"policy": policy, "selected": selected, "monthly_counts": dict(month_counts),
              "rated_count": len(ranked), "candidate_count": len(rows)}
    save(root / "selection.json", result)
    return {"selected_count": len(selected), "rated_count": len(ranked), "candidate_count": len(rows)}


def metrics(meta, candidates, coverage, records):
    window = meta["requested_range"]
    valid_months = set(months(window["start"], window["end"]))
    ids = set()
    for row in candidates:
        rid = identifier(row["id"])
        if rid in ids or not window["start"] <= date_key(row["created_at"]) <= window["end"]:
            raise ValueError("扫描索引含重复ID或窗口外记录")
        if row.get("author_uid") and row["author_uid"] != meta.get("target", {}).get("uid"):
            raise ValueError("扫描索引作者与目标不匹配")
        ids.add(rid)
    if any(r["id"] not in ids for r in records):
        raise ValueError("已收录记录不在扫描索引中；先修复索引，不能发布错误统计")
    seen_months = set()
    for c in coverage:
        if c["month"] not in valid_months or c["month"] in seen_months or c["status"] not in {"complete", "partial", "failed", "unread"}:
            raise ValueError("逐月覆盖含重复、范围外月份或未知状态")
        if c["status"] == "complete" and not c.get("note", "").strip():
            raise ValueError("完整月份缺核验依据")
        seen_months.add(c["month"])
    scanned = Counter(date_key(r["created_at"])[:7] for r in candidates)
    saved = Counter(date_key(r["created_at"])[:7] for r in records)
    observed = {c["month"]: c for c in coverage}
    monthly = []
    for month in months(window["start"], window["end"]):
        state = observed.get(month, {}).get("status", "partial" if scanned[month] else "unread")
        monthly.append({"month": month, "status": state, "observed_original_count": scanned[month],
                        "published_count": scanned[month] if state == "complete" else None,
                        "saved_count": saved[month], "note": observed.get(month, {}).get("note", "")})
    days = dict(Counter(date_key(r["created_at"]) for r in candidates))
    ordered = sorted(candidates, key=lambda r: (r["created_at"], r["id"]))
    return {"schema_version": 1, "basis": "observed_original_posts", "requested_range": window,
            "observed_original_count": len(candidates), "saved_count": len(records),
            "observed_video_count": sum(bool(r.get("is_video")) for r in candidates),
            "complete": bool(monthly) and all(m["status"] == "complete" for m in monthly),
            "active_days": len(days), "days": days, "monthly": monthly,
            "first_observed_id": ordered[0]["id"] if ordered else None,
            "last_observed_id": ordered[-1]["id"] if ordered else None,
            "reading_count": None}


def materialize(root):
    root = Path(root)
    repair_media_urls(root)
    meta = load(root / "project_meta.json")
    rows = load(root / "candidates.json", [])
    selection = load(root / "selection.json", {})
    chosen = {r["id"]: r["reason"] for r in selection.get("selected", [])}
    if not set(chosen).issubset({r["id"] for r in rows}):
        raise ValueError("精选ID不在当前索引中；重新select")
    if meta["mode"] == "selected" and not chosen:
        raise ValueError("精选模式先提供评分并运行 select，不默默挑最近几条")
    old = {r["id"]: r for r in load(root / "records.json", [])}
    records = []
    for row in rows:
        if meta["mode"] == "selected" and row["id"] not in chosen:
            continue
        record = {**row, "selected": row["id"] in chosen}
        if row["id"] in chosen:
            record["selection_reason"] = chosen[row["id"]]
        prior = old.get(row["id"], {})
        # Keep downloaded files for matching images, but do not discard newly fetched extra photos.
        record["images"] = merge_media(record["images"], prior.get("images", []))
        if not record.get("image_count_basis") and prior.get("image_count_basis") and prior.get("image_inventory_status") == "complete":
            record.update(expected_image_count=prior["expected_image_count"], image_count_basis=prior["image_count_basis"],
                          image_inventory_status="complete" if len(record["images"]) == prior["expected_image_count"] else "partial")
        if record.get("video"):
            record["video"] = {**record["video"], "covers": merge_media(record["video"]["covers"], (prior.get("video") or {}).get("covers", []))}
        if prior.get("screenshot"):
            record["screenshot"] = prior["screenshot"]
        records.append(record)
    if not records:
        raise ValueError("没有可收录记录；保留断点，不生成空手账")
    report = metrics(meta, rows, load(root / "monthly_coverage.json", []), records)
    annual = []
    for year in sorted({int(m["month"][:4]) for m in report["monthly"]}):
        ms = [m for m in report["monthly"] if m["month"].startswith(str(year))]
        count = sum(m["observed_original_count"] for m in ms)
        all_read = all(m["status"] == "complete" for m in ms)
        state = "empty" if all_read and count == 0 else "complete" if all_read and meta["mode"] == "full" else "selected" if meta["mode"] == "selected" and all_read else "partial"
        annual.append({"year": year, "status": state, "scanned_count": count,
                       "saved_count": sum(m["saved_count"] for m in ms),
                       "selected_count": sum(date_key(r["created_at"]).startswith(str(year)) and r["selected"] for r in records),
                       "note": "扫描口径为可访问原创微博（含视频帖）；逐月覆盖见 metrics.json，不推断未读取部分。"})
    save(root / "records.json", records)
    save(root / "coverage.json", annual)
    save(root / "metrics.json", report)
    pending = sum(r.get("text_status") != "complete" or r.get('image_inventory_status') != 'complete' or len(r["images"]) < (r.get("expected_image_count") or 0)
                  or (r.get("is_video") and not (r.get("video") or {}).get("covers")) for r in records)
    pending_photos = sum(len(r["images"]) < (r.get("expected_image_count") or 0) for r in records)
    pending_video_covers = sum(bool(r.get("is_video")) and not (r.get("video") or {}).get("covers") for r in records)
    save(root / "progress.json", {"schema_version": 1, "target_uid": meta["target"]["uid"],
                                 "stage": "materialized", "saved_count": len(records), "pending_details": pending,
                                 "pending_photo_details": pending_photos, "pending_video_covers": pending_video_covers})
    return {"saved_count": len(records), "pending_details": pending, "pending_photo_details": pending_photos,
            "pending_video_covers": pending_video_covers, "statistics_complete": report["complete"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    for key in ("uid", "profile-url"):
        init.add_argument("--" + key, required=True)
    init.add_argument("--start")
    init.add_argument("--end")
    init.add_argument("--mode", choices=("selected", "full"), default="selected")
    init.add_argument("--skin", choices=("paper", "frosted"), default="paper")
    init.add_argument("--title", default="人生手账")
    ing = sub.add_parser("ingest")
    ing.add_argument("--input", type=Path, required=True)
    ing.add_argument("--scan-month")
    ing.add_argument("--scan-status", choices=("complete", "partial", "failed"))
    ing.add_argument("--note", default="")
    sel = sub.add_parser("select")
    sel.add_argument("--ratings", type=Path, required=True)
    sub.add_parser("materialize")
    a = p.parse_args()
    try:
        if a.command == "init":
            today = datetime.now(BEIJING).date()
            start = today.replace(year=today.year - 10, day=min(today.day, calendar.monthrange(today.year - 10, today.month)[1]))
            result = initialize(a.project, a.uid, a.profile_url, a.start or start.isoformat(), a.end or today.isoformat(), a.mode, a.title, a.skin)
        elif a.command == "ingest":
            result = ingest(a.project, load(a.input), a.scan_month, a.scan_status, a.note)
        elif a.command == "select":
            result = select(a.project, load(a.ratings))
        else:
            result = materialize(a.project)
        import json
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, TypeError, KeyError, OSError) as error:
        p.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
