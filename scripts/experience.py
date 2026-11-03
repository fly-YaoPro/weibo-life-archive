"""Offline editorial anchors and experience contracts; no claims of semantic proof."""
import re
import unicodedata
from archive_common import project_file
from scene_geometry import validate_scene_geometry

RASTER = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
AUDIO = {".wav", ".mp3", ".ogg", ".m4a"}
VIDEO = {".mp4", ".webm", ".mov", ".m4v"}


def synthetic_fixture(meta):
    value = meta.get("fixture", {})
    return (isinstance(value, dict) and value.get("synthetic") is True and
            isinstance(value.get("label"), str) and "合成" in value["label"] and
            isinstance(value.get("source"), str) and bool(value["source"].strip()) and
            "合成" in meta.get("title", ""))


def source_ids(section, by_id, field):
    ids = section.get("source_ids", [])
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in by_id for i in ids):
        raise ValueError(field + ": 需要非空、已收录字符串来源ID")
    if len(ids) != len(set(ids)):
        raise ValueError(field + ": 来源ID重复")
    return ids


def _canonical(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def _body(section):
    values = [section.get(k, "") for k in ("title", "headline", "text", "reason", "opening", "closing", "description", "letter_text")]
    values += section.get("paragraphs", [])
    return "\n".join(v for v in values if isinstance(v, str))


def record_image_paths(record):
    """Cached evidence photos/posters only; decorations/screenshots are separate."""
    return {image[key] for image in record.get('images', []) + record.get('video', {}).get('covers', [])
            if isinstance(image, dict) for key in ('path', 'large', 'original', 'thumb_path', 'large_path', 'original_path')
            if isinstance(image.get(key), str) and image[key] and not image[key].startswith(('decorations/', 'screenshots/', 'profile/'))}


def _validate_anchor(anchor, by_id, field):
    if not isinstance(anchor, dict):
        raise ValueError(field + ': 依据需为对象')
    sid = anchor.get('source_id')
    if sid not in by_id:
        raise ValueError(field + '.source_id: 依据来源ID不在记录中: ' + repr(sid))
    if anchor.get('kind', 'text') == 'image':
        quote = anchor.get('observation')
        if not isinstance(quote, str) or not quote.strip() or anchor.get('image_path') not in record_image_paths(by_id[sid]):
            raise ValueError(field + ': image依据需关联来源缓存图片及非空实际读图观察')
    else:
        quote = anchor.get('quote')
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError(field + '.quote: 连续摘录不能为空')
        if quote not in by_id[sid]['text']:
            raise ValueError(field + '.quote: 连续摘录必须是关联原文中的精确连续子串; source_id=' + sid)
    # Legacy supports metadata is accepted but never gates prose or script choices.
    return anchor


def validate_narrative(story, records, required=False, errors=None):
    """Validate source IDs and optional exact quotations; semantics stay with the author.

    ``required`` is retained for compatibility, not keyword/anchor coverage gates.
    """
    if not isinstance(story, dict):
        raise ValueError("story需为对象")
    by_id = {r["id"]: r for r in records}
    sections = []
    theme_ids = set()
    for theme in story.get('themes', []):
        tid = theme.get('id') if isinstance(theme, dict) else None
        if not isinstance(tid, str) or not tid.strip() or tid in theme_ids:
            issue = '主题ID缺失或重复'
            if errors is None: raise ValueError(issue)
            errors.append(issue)
        else:
            theme_ids.add(tid)
    overview = story.get("overview", {})
    if not isinstance(overview, dict):
        raise ValueError("overview需为对象")
    sections.append(("overview", overview, []))
    if overview.get("portrait") is not None:
        sections.append(("overview.portrait", overview["portrait"], overview.get("evidence", [])))
    for group in ("themes", "findings", "milestones", "wishes", "plans", "annual_reviews"):
        values = story.get(group, [])
        if not isinstance(values, list):
            raise ValueError(group + "需为数组")
        for n, value in enumerate(values):
            sections.append((f"{group}[{n}]", value, []))
    for name in ("letter", "song"):
        if story.get(name):
            sections.append((name, story[name], []))
    share = story.get("share", {})
    if not isinstance(share, dict) or not isinstance(share.get("entries", []), list):
        raise ValueError("share与entries类型错误")
    for n, value in enumerate(share.get("entries", [])):
        if not isinstance(value, dict):
            raise ValueError("share.entries需为对象数组")
        # Share entries have one source_id so dates and media remain indivisible.
        sections.append((f"share.entries[{n}]", {**value, "source_ids": [value.get("source_id")]}, share.get("evidence", [])))
    bank = story.get("evidence", [])
    if not isinstance(bank, list):
        raise ValueError("story.evidence需为数组")
    def checked(values, prefix):
        valid = []
        for n, anchor in enumerate(values):
            try:
                valid.append(_validate_anchor(anchor, by_id, f'{prefix}[{n}]'))
            except (ValueError, KeyError, TypeError) as exc:
                if errors is None: raise
                errors.append(str(exc))
        return valid
    # Validate the shared bank once, at its own JSON path, rather than blaming every section.
    bank = checked(bank, '$.evidence')
    anchor_count = 0
    for field, section, inherited in sections:
        try:
            if not isinstance(section, dict):
                raise ValueError(field + "需为对象")
            ids = source_ids(section, by_id, field)
            body = _body(section)
            if not body.strip():
                raise ValueError(field + ": 需要有内容的短记")
            own = section.get("evidence", [])
            if not isinstance(own, list) or not isinstance(inherited, list):
                raise ValueError(field + ".evidence需为数组")
            anchors = bank + checked(inherited, '$.' + field + '.inherited_evidence') + checked(own, '$.' + field + '.evidence')
            anchor_count += sum(a['source_id'] in ids for a in anchors)
            excerpt = section.get("excerpt")
            if excerpt and not any(excerpt in by_id[i]["text"] for i in ids):
                raise ValueError(field + ": 摘句必须来自关联原文")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if errors is None: raise
            errors.append(str(exc))
    return {"references_checked": len(sections), "anchors_checked": anchor_count,
            "grounding_required": bool(required), "repetition_checked": False, "keyword_matching_required": False,
            "semantic_review_required": False, "semantic_basis": "author_read_sources"}


def validate_experience(root, story, records, grounding_required=False, resource_check=None, errors=None, embedded_assets=None):
    by_id = {r["id"]: r for r in records}
    paths = set()
    resource = resource_check or (lambda name, suffixes: project_file(root, name, suffixes))

    def refs(section):
        return source_ids(section, by_id, "场景、热点、来信和年度回顾")

    def object_evidence(obj, field):
        kind = obj.get("evidence_kind", "text")
        if kind not in {"text", "image"}:
            raise ValueError(field + ": evidence_kind使用text或image")
        ids = [str(i) for i in obj.get("source_ids", [])]
        if kind == "image":
            image_path = obj.get("image_path")
            for sid in ids:
                allowed = record_image_paths(by_id[sid])
                if not isinstance(image_path, str) or image_path.startswith("decorations/") or image_path not in allowed:
                    raise ValueError(field + ": 读图物件的image_path需属于全部关联记录的缓存图片")
        else:
            evidence = obj.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip():
                raise ValueError(field + ": 物件摘录需为非空原文连续子串")
            # A symbolic object can combine sources; they need not share one sentence.
            if not any(evidence in by_id[sid].get("text", "") for sid in ids):
                raise ValueError(field + ": 物件摘录须来自至少一个关联原文")
            per_source = obj.get("source_evidence", {})
            if not isinstance(per_source, dict):
                raise ValueError(field + ": source_evidence需为来源ID到摘录的对象")
            for sid, quote in per_source.items():
                if sid not in ids or not isinstance(quote, str) or not quote.strip() or quote not in by_id[sid].get("text", ""):
                    raise ValueError(field + ": source_evidence摘录与关联原文不符")

    def objects(section, field, image_sources=None):
        image_sources = image_sources if image_sources is not None else section["source_ids"]
        values = section.get("objects", [])
        names, union, mapped = set(), set(), {}
        for obj in values:
            try:
                if not isinstance(obj, dict):
                    raise ValueError(field + ".objects需为对象数组")
                ids = refs(obj)
                name = obj.get("name")
                if not isinstance(name, str) or not name.strip() or name in names:
                    raise ValueError(field + ": 物件名称缺失或重复")
                object_evidence(obj, field)
                names.add(name); union.update(ids); mapped[name] = set(ids)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                if errors is None: raise
                errors.append(str(exc))
        return mapped, union

    def decoration(path):
        if not path.startswith("decorations/"):
            raise ValueError("生成场景/结尾插画单独放 decorations/，不冒充历史证据图")
        resource(path, RASTER)
        paths.add(path)

    scene = story.get("scene")
    if scene:
        try:
            refs(scene)
            if not scene.get("image_path"):
                raise ValueError("首屏场景需要生成插画")
            object_map, object_union = objects(scene, "scene", scene.get("image_source_ids"))
            has_objects = bool(scene.get("objects"))
            # When grounded objects are present, scene.source_ids must equal their union.
            if has_objects:
                declared_scene_ids = {str(i) for i in scene.get("source_ids", [])}
                if declared_scene_ids != object_union:
                    raise ValueError("scene.source_ids 必须等于全部物件来源全集，不能多报或漏报来源")
            decoration(scene["image_path"])
            validate_scene_geometry(root, scene, embedded_assets)
            if not scene.get("alt"):
                raise ValueError("场景图片需要文字说明")
            for field in ('guidance','mobile_guidance'):
                if field in scene and (not isinstance(scene[field],str) or not scene[field].strip() or '\n' in scene[field]):raise ValueError('场景引导需非空单行文字')
            seen = set()
            hotspots = scene.get("hotspots", [])
            if not 1 <= len(hotspots) <= 10:
                raise ValueError("场景保留1—10个有据热点；不为凑数量虚构物件")
            themes = {t["id"] for t in story.get("themes", [])}
            object_names = set(object_map.keys())
            record_dates = {r["id"]: r.get("date") for r in records}
            for h in hotspots:
                try:
                    refs(h)
                    object_name = h.get("object_name") or h.get("name")
                    if not h.get("id") or h["id"] in seen or not h.get("label") or not h.get("description"):
                        raise ValueError("热点需唯一ID、名称和简短说明")
                    # With grounded objects, the hotspot must point to an object that exists.
                    if has_objects and object_name not in object_names:
                        raise ValueError("热点object_name必须映射场景中实际存在的物件")
                    if not isinstance(h.get("effect", "sparkle"), str) or h.get("effect", "sparkle") not in {"sparkle", "glow", "breeze", "ripple"}:
                        raise ValueError("热点反馈使用 sparkle/glow/breeze/ripple，不执行自定义代码")
                    if h.get("image_paths") and not isinstance(h["image_paths"], list):
                        raise ValueError("热点小记配图需为列表")
                    seen.add(h["id"])
                    for axis in ("x", "y"):
                        if type(h.get(axis)) not in (int, float) or not 0 <= h[axis] <= 100:
                            raise ValueError("热点坐标使用0—100百分比")
                    target = h.get("target", {})
                    if target.get("view") not in {"review", "calendar", "stats", "future", "plans"}:
                        raise ValueError("热点目标板块不存在")
                    if target.get("theme_id") and target["theme_id"] not in themes:
                        raise ValueError("热点目标主题不存在")
                    target_date = target.get("date")
                    if target_date is not None:
                        h_sids = [str(i) for i in h.get("source_ids", [])]
                        if not any(record_dates.get(sid) == target_date for sid in h_sids):
                            raise ValueError("热点target日期需属于热点关联来源的记录日期")
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    if errors is None: raise
                    errors.append(str(exc))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if errors is None: raise
            errors.append(str(exc))
    letter = story.get("letter")
    if letter:
        try:
            refs(letter)
            if not letter.get("title") or not isinstance(letter.get("paragraphs"), list) or not letter["paragraphs"] or any(not isinstance(p, str) or not p.strip() for p in letter["paragraphs"]) or not letter.get("closing"):
                raise ValueError("未来来信需要标题、非空段落和结束语")
            if not letter.get("image_path"):
                raise ValueError("未来来信需要结尾生成插画")
            decoration(letter["image_path"])
            if not letter.get("image_alt") and not letter.get("alt"):
                raise ValueError("结尾插画需要文字说明")
            if letter.get("objects"):
                _, letter_object_union = objects(letter, "letter", letter.get("image_source_ids"))
                # image_source_ids must equal the letter objects' union and stay within the letter body sources.
                declared_image_ids = {str(i) for i in letter.get("image_source_ids", [])}
                letter_body_ids = {str(i) for i in letter.get("source_ids", [])}
                if declared_image_ids != letter_object_union or not letter_object_union <= letter_body_ids:
                    raise ValueError("letter.image_source_ids 超出结尾物件来源全集，且需属于来信正文来源")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if errors is None: raise
            errors.append(str(exc))
    for review in story.get("annual_reviews", []):
        try:
            ids = refs(review)
            if not review.get("title") or not review.get("text") or type(review.get("year")) is not int:
                raise ValueError("年度回顾需要年份、标题和正文")
            if any(int(by_id[i]["date"][:4]) != review["year"] for i in ids):
                raise ValueError("年度回顾来源年份不匹配")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if errors is None: raise
            errors.append(str(exc))
    music = story.get("bgm")
    if music:
        try:
            path = music["path"]
            resource(path, AUDIO)
            if not path.startswith("audio/") or not music.get("title") or music.get("origin") not in {"user_provided", "generated", "licensed"} or not music.get("reference"):
                raise ValueError("BGM需要 audio/ 本地音频、名称、来源类型和来源说明")
            paths.add(path)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if errors is None: raise
            errors.append(str(exc))
    return paths
