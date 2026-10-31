#!/usr/bin/env python3
"""Offline Weibo image-inventory gate. No network, credentials or model dependency."""
import argparse
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path
from urllib.parse import urlsplit


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def image_info(path):
    """Check raster container structure, not semantic provenance or full decoding."""
    data = path.read_bytes()
    width = height = 0
    fmt = ""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        ended = pixels = header = False
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], "big")
            tag = data[offset + 4:offset + 8]
            end = offset + 12 + size
            if end > len(data):
                raise ValueError("truncated PNG chunk")
            body = data[offset + 8:offset + 8 + size]
            crc = int.from_bytes(data[end - 4:end], "big")
            if zlib.crc32(tag + body) & 0xffffffff != crc:
                raise ValueError("PNG checksum mismatch")
            if tag == b"IHDR":
                if header or offset != 8 or len(body) != 13:
                    raise ValueError("invalid PNG header")
                width, height = struct.unpack(">II", body[:8])
                header = True
            pixels |= tag == b"IDAT" and bool(body)
            if tag == b"IEND":
                ended = size == 0 and end == len(data)
                break
            offset = end
        if not (header and pixels and ended):
            raise ValueError("incomplete PNG container")
        fmt = "png"
    elif data.startswith(b"\xff\xd8"):
        if not data.endswith(b"\xff\xd9"):
            raise ValueError("truncated JPEG")
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 0xff:
                break
            while offset < len(data) and data[offset] == 0xff:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xd9, 0xda):
                break
            if marker in (0x01, *range(0xd0, 0xd9)):
                continue
            size = int.from_bytes(data[offset:offset + 2], "big")
            if size < 2 or offset + size > len(data):
                raise ValueError("invalid JPEG segment")
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                if size < 8:
                    raise ValueError("invalid JPEG frame")
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            offset += size
        fmt = "jpeg"
    elif data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 14:
        if data[-1:] != b";" or b"," not in data[13:]:
            raise ValueError("truncated GIF")
        width, height = struct.unpack("<HH", data[6:10])
        fmt = "gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValueError("truncated WebP")
        offset = 12
        while offset + 8 <= len(data):
            tag = data[offset:offset + 4]
            size = int.from_bytes(data[offset + 4:offset + 8], "little")
            body = data[offset + 8:offset + 8 + size]
            if len(body) != size:
                raise ValueError("truncated WebP chunk")
            if tag == b"VP8X" and len(body) >= 10:
                width = int.from_bytes(body[4:7], "little") + 1
                height = int.from_bytes(body[7:10], "little") + 1
            elif tag == b"VP8 " and len(body) >= 10 and body[3:6] == b"\x9d\x01\x2a":
                width = int.from_bytes(body[6:8], "little") & 0x3fff
                height = int.from_bytes(body[8:10], "little") & 0x3fff
            elif tag == b"VP8L" and len(body) >= 5 and body[0] == 0x2f:
                bits = int.from_bytes(body[1:5], "little")
                width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
            offset += 8 + size + (size % 2)
        if offset != len(data):
            raise ValueError("invalid WebP chunks")
        fmt = "webp"
    else:
        raise ValueError("not a supported raster image (HTML, empty response or unknown format)")
    if width <= 1 or height <= 1:
        raise ValueError("missing dimensions or placeholder pixel")
    return {"format": fmt, "width": width, "height": height, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def audit(root, meta=None, records=None):
    root = Path(root).resolve()
    errors, warnings, details, cache = [], [], [], {}
    try:
        meta = load(root / "project_meta.json") if meta is None else meta
        records = load(root / "records.json") if records is None else records
        if not isinstance(meta, dict) or meta.get("platform") != "weibo" or not isinstance(records, list):
            raise ValueError("expected Weibo metadata and record array")
    except (OSError, ValueError, TypeError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "records": []}
    expected_total = saved_total = text_only = unknown = 0
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"records[{index}]: expected object")
            continue
        label = str(record.get("id") or f"records[{index}]")
        before = len(errors)
        expected, images = record.get("expected_image_count"), record.get("images")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            errors.append(label + ": expected_image_count is unknown; verify the source gallery")
            unknown += 1
            expected = None
        else:
            expected_total += expected
            text_only += expected == 0
        if record.get("image_inventory_status") != "complete":
            errors.append(label + ": image inventory not confirmed complete")
        if not isinstance(record.get("image_count_basis"), str) or not record["image_count_basis"].strip():
            errors.append(label + ": missing source/count verification basis")
        if not isinstance(images, list):
            errors.append(label + ": images must be an array")
            images = []
        if expected is not None and len(images) != expected:
            errors.append(f"{label}: source expects {expected} images, inventory contains {len(images)}")
        identifiers, slots, files, saved = set(), set(), [], 0
        for number, image in enumerate(images):
            item = f"{label}.images[{number}]"
            item_start = len(errors)
            if not isinstance(image, dict):
                errors.append(item + ": expected object")
                continue
            identity = image.get("image_id")
            if not isinstance(identity, str) or not identity or identity in identifiers:
                errors.append(item + ": missing or duplicate image_id")
            else:
                identifiers.add(identity)
            if image.get("origin") == "platform":
                try:
                    parts = urlsplit(image.get("source_url", ""))
                    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
                        raise ValueError()
                except (ValueError, TypeError):
                    errors.append(item + ": missing safe platform image URL")
            elif image.get("origin") != "user_provided" or not image.get("provided_reference"):
                errors.append(item + ": real image provenance is required")
            if image.get("download_status") != "saved":
                errors.append(item + ": image download is not complete")
            variants = {}
            for key in ("thumb_path", "large_path"):
                name = image.get(key)
                try:
                    if not isinstance(name, str) or not name or "\\" in name or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", name):
                        raise ValueError("expected project-relative local path")
                    path = (root / name).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        raise ValueError("file missing or path escapes project")
                    if path not in cache:
                        cache[path] = image_info(path)
                    variants[key] = {"path": name, **cache[path]}
                except (OSError, ValueError, OverflowError) as exc:
                    errors.append(item + "." + key + ": " + str(exc))
            if len(variants) == 2:
                hashes = tuple(variants[k]["sha256"] for k in ("thumb_path", "large_path"))
                if hashes in slots:
                    errors.append(item + ": repeated files cannot fill another image slot")
                slots.add(hashes)
                if hashes[0] == hashes[1] and not str(image.get("large_note") or "").strip():
                    errors.append(item + ": identical thumbnail/large bytes need verified best-available explanation in large_note")
                large = variants["large_path"]
                thumb = variants["thumb_path"]
                if max(large["width"], large["height"]) < max(thumb["width"], thumb["height"]):
                    errors.append(item + ": large image is smaller than thumbnail")
                if max(large["width"], large["height"]) < 600:
                    warnings.append(item + ": low resolution; verify best available source, do not upscale to simulate detail")
            if len(errors) == item_start:
                saved += 1
            files.append({"image_id": identity, "files": variants})
        saved_total += saved
        details.append({"record_id": label, "expected": expected, "enumerated": len(images),
                        "saved": saved, "complete": before == len(errors), "images": files})
    if not records:
        errors.append("No retained records to audit")
    if records and text_only == len(records):
        warnings.append("All retained records are confirmed text-only; review selection and report whether image-bearing candidates were searched")
    return {"schema_version": 1, "ok": not errors, "retained_records": len(records),
            "expected_known_images": expected_total, "saved_images": saved_total,
            "confirmed_text_only_records": text_only, "unknown_count_records": unknown,
            "errors": errors, "warnings": warnings, "records": details,
            "limits": "Container/count/path checks do not prove source truth or full image decoding; inspect actual images in the browser."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    result = audit(args.project)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
