"""Shared, offline archive primitives. Python 3.9+, no third-party packages."""
import json
import hashlib
from copy import deepcopy
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

BEIJING = timezone(timedelta(hours=8))


def load(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def save(path, value):
    """Replace one JSON checkpoint atomically, including on interrupted runs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def identifier(value):
    # Never turn a platform's 64-bit IDs into JavaScript numbers.
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ID 必须是非空字符串；导出时不要先转浮点数")
    return value


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("时间必须包含年份及明确时区")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    if dt.tzinfo is None:
        raise ValueError("时间缺时区；不要猜测相对日期")
    return dt.astimezone(BEIJING).isoformat()


def date_key(value):
    return timestamp(value)[:10]


def months(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("开始日期晚于结束日期")
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        yield "%04d-%02d" % (y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def project_file(root, name, suffixes=None, exists=True):
    if not isinstance(name, str) or not name or "\\" in name or re.match(r"^[a-zA-Z]+:", name):
        raise ValueError("资源必须使用项目内相对路径")
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or (exists and not path.is_file()):
        raise ValueError("资源越界或缺失: " + name)
    if suffixes and path.suffix.lower() not in suffixes:
        raise ValueError("不支持的资源格式: " + name)
    return path


class SafeText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.hidden = [], [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.hidden += 1
        if self.hidden:
            return
        if tag in ("br", "p", "div", "li"):
            self.parts.append("\n")
        if tag == "a" and urlsplit(attrs.get("href", "")).scheme in ("http", "https"):
            self.links.append({"label": attrs.get("title") or "正文链接", "href": attrs["href"]})
        if tag == "img" and attrs.get("alt"):
            self.parts.append(attrs["alt"])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in ("p", "div", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_html(value):
    parser = SafeText()
    parser.feed(value)
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
    return text, parser.links


def media_items(record):
    """Photos and explicitly labelled video covers share the image download contract."""
    for index, image in enumerate(record.get("images", [])):
        yield "images", index, image
    for index, image in enumerate((record.get("video") or {}).get("covers", [])):
        yield "video_covers", index, image


def normalize_media_urls(image):
    """Repair legacy observed URL descriptors without guessing a replacement image."""
    image = dict(image)
    for field in ("source_url", "thumb_url", "large_url", "original_url"):
        value = image.get(field)
        if isinstance(value, dict):
            if not isinstance(value.get("url"), str) or not value["url"].strip():
                raise ValueError("旧图片描述对象缺真实url字段；正常原帖核验后补齐")
            image.setdefault("legacy_url_descriptors", {})[field] = value
            image[field] = value["url"]
    return image


def repair_media_urls(root):
    """Atomically repair known legacy URL descriptors, backing up original indexes first."""
    root = Path(root); staged, changes = [], []
    for name in ('candidates.json', 'records.json'):
        path = root / name
        original = load(path)
        if original is None: continue
        updated = deepcopy(original); repaired = []
        for record in updated:
            for kind, index, image in list(media_items(record)):
                fields = [field for field in ('source_url', 'thumb_url', 'large_url', 'original_url') if isinstance(image.get(field), dict)]
                if not fields: continue
                clean = normalize_media_urls(image)
                (record['images'] if kind == 'images' else record['video']['covers'])[index] = clean
                repaired.append({'record_id': record['id'], 'media_kind': kind, 'image_index': index, 'fields': fields})
        if repaired:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            backup = 'media-url-repairs/' + name.removesuffix('.json') + '-' + digest + '.json'
            staged.append((path, original, updated, backup, repaired))
    # Validate every descriptor before altering either index.
    for path, original, updated, backup, repaired in staged:
        if not (root / backup).exists(): save(root / backup, original)
        save(path, updated)
        changes.append({'source_file': path.name, 'backup_path': backup, 'changes': repaired})
    if changes:
        log = load(root / 'media-url-repair-log.json', [])
        log.append({'repaired_at': datetime.now(BEIJING).isoformat(), 'indexes': changes})
        save(root / 'media-url-repair-log.json', log)
    return {'repaired_indexes': len(changes), 'repaired_ids': sorted({item['record_id'] for entry in changes for item in entry['changes']})}


def merge_media(incoming, prior):
    """Union observed URLs while keeping local files only for the same source image."""
    incoming = [normalize_media_urls(image) for image in incoming]
    prior = [normalize_media_urls(image) for image in prior]
    key = lambda image: image.get("source_url") or image.get("provided_reference")
    old = {key(image): image for image in prior}
    result, seen = [], set()
    for image in incoming:
        identity = key(image)
        local = {k: v for k, v in old.get(identity, {}).items()
                 if k.endswith("_path") or k.endswith("_dimensions") or k == "download_status"}
        provenance = old.get(identity, {}).get("legacy_url_descriptors")
        if provenance:
            image["legacy_url_descriptors"] = {**provenance, **image.get("legacy_url_descriptors", {})}
        result.append({**image, **local}); seen.add(identity)
    result.extend(image for image in prior if key(image) not in seen)
    return result
