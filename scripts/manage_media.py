#!/usr/bin/env python3
"""Resumable, bounded image downloads and registration of real browser screenshots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from archive_common import load, media_items, normalize_media_urls, project_file, repair_media_urls, save, timestamp


def image_info(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        if not data.endswith(b"\0\0\0\0IEND\xaeB`\x82"):
            raise ValueError("PNG 未下载完整")
        return "png", *struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        if not data.endswith(b";"):
            raise ValueError("GIF 未下载完整")
        return "gif", *struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if len(data) < 20 or int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValueError("WebP 未下载完整")
        from io import BytesIO
        # Pillow is optional: WebP without it is still identified, dimensions stay unknown.
        try:
            from PIL import Image
            with Image.open(BytesIO(data)) as im:
                return "webp", *im.size
        except ImportError:
            return "webp", None, None
    if data[:2] == b"\xff\xd8":
        if not data.rstrip(b"\0\r\n ").endswith(b"\xff\xd9"):
            raise ValueError("JPEG 未下载完整")
        i = 2
        while i + 4 <= len(data):
            if data[i] != 255:
                i += 1
                continue
            marker = data[i + 1]
            i += 2
            if marker in (0xD8, 0xD9) or marker == 0x00:
                continue
            length = int.from_bytes(data[i:i + 2], "big")
            if length < 2:
                break
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and i + 7 <= len(data):
                h, w = struct.unpack(">HH", data[i + 3:i + 7])
                return "jpg", w, h
            i += length
    raise ValueError("响应不是可识别图片，不能把 HTML/错误页面当下载成功")


def _adaptive_quality(quality, longest_edge):
    """按输出尺寸微调质量：大图略降、小图略保，单位面积观感接近一致。"""
    if longest_edge >= 1280:
        return max(60, quality - 2)
    if longest_edge < 800:
        return min(92, quality + 4)
    return quality


def compress_image(data, quality=72, max_dimension=1280, output_format='auto'):
    """用 Pillow 压缩图片；Pillow 不可用时返回原图。

    output_format:
      - 'jpeg'：无透明图统一输出 JPEG，兼容性最好（默认）
      - 'webp'：统一输出 WebP，同画质体积更小，需现代浏览器
      - 'auto'：有透明通道保留 WebP，其余按 jpeg 输出
    返回 (压缩后数据, 格式, 宽, 高)。格式为 'jpg'/'png'/'webp'；
    Pillow 缺失或压缩反而变大时格式为 None，调用方回退原图。
    """
    try:
        from PIL import Image, ImageOps
        from io import BytesIO
    except ImportError:
        return data, None, None, None

    with Image.open(BytesIO(data)) as im:
        original_format = (im.format or '').lower()
        im = ImageOps.exif_transpose(im)

        # 等比缩放，不放大
        if max_dimension and max(im.size) > max_dimension:
            im.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        has_alpha = im.mode in ('RGBA', 'LA', 'P') and (
            im.mode == 'P' and 'transparency' in im.info or im.mode != 'P'
        )

        q = _adaptive_quality(quality, max(im.size))
        out = BytesIO()

        use_webp = output_format == 'webp' or (output_format == 'auto' and has_alpha)
        if use_webp:
            # WebP 同时支持透明与不透明，method=6 压缩更充分
            if im.mode not in ('RGBA', 'LA', 'P'):
                im = im.convert('RGB')
            im.save(out, 'WEBP', quality=q, method=6)
            fmt = 'webp'
        elif has_alpha:
            # 指定 JPEG 但图有透明通道：保留优化后的 PNG，避免黑底/丢透明
            im.save(out, 'PNG', optimize=True)
            fmt = 'png'
        else:
            if im.mode != 'RGB':
                im = im.convert('RGB')
            im.save(out, 'JPEG', quality=q, optimize=True, progressive=True)
            fmt = 'jpg'

        compressed = out.getvalue()
        # 兜底：压缩后若比原图还大，说明原图已高度优化，直接保留原图
        if len(compressed) >= len(data):
            return data, None, None, None
        return compressed, fmt, im.width, im.height


def plan(root, single_size=False):
    root = Path(root)
    repairs = repair_media_urls(root)
    jobs = []
    records = load(root / "records.json", [])
    repaired = bool(repairs['repaired_indexes'])
    for row in records:
        for kind, index, im in list(media_items(row)):
            clean = normalize_media_urls(im)
            if clean != im:
                repaired = True
                (row['images'] if kind == 'images' else row['video']['covers'])[index] = clean
        for kind, i, im in media_items(row):
            if im.get("origin") != "platform":
                continue
            if single_size:
                # 最小化：只下一个最佳尺寸，优先 original，其次 large；统一用 large 角色承载
                url = im.get("original_url") or im.get("large_url") or im.get("thumb_url") or im.get("source_url")
                if url:
                    jobs.append({"record_id": row["id"], "media_kind": kind, "image_index": i,
                                 "role": "large", "url": url, "single_size": True})
            else:
                for role in (("thumb", "large", "original") if im.get("original_url") else ("thumb", "large")):
                    url = im.get(role + "_url") or im.get("source_url")
                    if url:
                        jobs.append({"record_id": row["id"], "media_kind": kind, "image_index": i,
                                     "role": role, "url": url})
    save(root / "media-manifest.json", {"jobs": jobs, "single_size": single_size})
    if repaired: save(root / "records.json", records)
    return {"jobs": len(jobs), "unique_urls": len({j["url"] for j in jobs}), "single_size": single_size,
            "repaired_legacy_descriptors": repaired, "repaired_ids": repairs['repaired_ids']}


class PublicImageRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443) or not (host.endswith(".sinaimg.cn") or host.endswith(".sinaimg.com")):
        raise ValueError("仅下载已核验的 HTTPS 微博图片 CDN；其他素材由宿主工具取得后本地登记")


def download(root, max_mb=512, max_file_mb=25, timeout=20, attempts=2, opener=None,
             jpeg_quality=86, max_dimension=0, output_format=None):
    root = Path(root)
    if max_mb <= 0 or max_file_mb <= 0 or attempts < 1:
        raise ValueError("下载预算与重试次数必须为正数")
    records = load(root / "records.json", [])
    by_id = {r["id"]: r for r in records}
    manifest = load(root / "media-manifest.json", {})
    jobs = manifest.get("jobs", [])
    single_size = manifest.get("single_size", False)
    def item(job):
        record = by_id[job["record_id"]]
        kind = job.get("media_kind", "images")
        if kind not in {"images", "video_covers"}: raise ValueError("unknown media kind")
        return (record["images"] if kind == "images" else record["video"]["covers"])[job["image_index"]]
    for job in jobs:
        try:
            im = item(job)
            if job["role"] not in {"thumb", "large", "original"} or im.get("origin") != "platform":
                raise ValueError("stale")
            if job.get("single_size"):
                # 单尺寸清单：URL 为该图任一可用尺寸即可
                allowed = {im.get(k) for k in ("original_url", "large_url", "thumb_url", "source_url")}
                if job["url"] not in allowed:
                    raise ValueError("stale")
            elif job["url"] != (im.get(job["role"] + "_url") or im.get("source_url")):
                raise ValueError("stale")
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("下载清单与当前记录不一致；重新运行 plan，不把旧图片关联到新记录")
    state = load(root / "media-state.json", {})
    opener = opener or urllib.request.build_opener(PublicImageRedirect())
    total = sum(p.stat().st_size for p in (root / "images").glob("*") if p.is_file())
    failures = 0
    for job in jobs:
        im = item(job)
        url = job["url"]
        digest = hashlib.sha256(url.encode()).hexdigest()
        entry = state.get(digest, {})
        cached = None
        if entry.get("path"):
            candidate = project_file(root, entry["path"], exists=False)
            if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == entry.get("sha256"):
                cached = entry
        if cached is None:
            try:
                validate_url(url)
                last = None
                for _ in range(attempts):
                    try:
                        req = urllib.request.Request(url, headers={"Referer": "https://weibo.com/", "User-Agent": "Mozilla/5.0"})
                        with opener.open(req, timeout=timeout) as response:
                            validate_url(response.geturl())
                            data = response.read(int(max_file_mb * 1024 * 1024) + 1)
                        if len(data) > max_file_mb * 1024 * 1024:
                            raise ValueError("单张图片超过预算")
                        # 先验证原始数据完整性，再压缩
                        image_info(data)
                        # Preserve platform bytes in the archive. Recompression creates
                        # separate display copies, never overwrites the archival source.
                        ext, w, h = image_info(data)
                        sha = hashlib.sha256(data).hexdigest()
                        path = root / "images" / (sha + "." + ext)
                        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                            old_size = path.stat().st_size if path.exists() else 0
                            if total + len(data) - old_size > max_mb * 1024 * 1024:
                                raise ValueError("图片总量超过预算；保留断点后调整预算，不静默丢图")
                            path.parent.mkdir(exist_ok=True)
                            part = path.with_suffix(path.suffix + ".part")
                            part.write_bytes(data)
                            os.replace(part, path)
                            total += len(data) - old_size
                        cached = {"path": path.relative_to(root).as_posix(), "sha256": sha,
                                  "bytes": len(data), "width": w, "height": h, "status": "saved"}
                        break
                    except urllib.error.HTTPError as error:
                        last = "HTTP " + str(error.code)
                        if error.code in (401, 403, 429, 432):
                            raise ValueError(last + "，停止该批下载，交由正常浏览器核验")
                    except (urllib.error.URLError, TimeoutError, OSError) as error:
                        last = type(error).__name__
                if cached is None:
                    raise ValueError(last or "下载失败")
            except (ValueError, OSError) as error:
                state[digest] = {"status": "failed", "error": str(error)}
                save(root / "media-state.json", state)
                failures += 1
                im["download_status"] = "partial" if im.get("large_path") else "failed"
                save(root / "records.json", records)
                if any(code in str(error) for code in ("HTTP 401", "HTTP 403", "HTTP 429", "HTTP 432")) or "预算" in str(error):
                    break
                continue
        state[digest] = cached
        if job.get("single_size"):
            # 单尺寸：三个路径字段统一指向同一文件，避免多尺寸冗余
            for role_key in ("thumb", "large", "original"):
                im[role_key + "_path"] = cached["path"]
                im[role_key + "_dimensions"] = {"width": cached["width"], "height": cached["height"]}
        else:
            im[job["role"] + "_path"] = cached["path"]
            im[job["role"] + "_dimensions"] = {"width": cached["width"], "height": cached["height"]}
        im["download_status"] = "saved" if im.get("large_path") else "partial"
        save(root / "records.json", records)
        save(root / "media-state.json", state)
    pending = sum(not im.get("large_path") for r in records for _, _, im in media_items(r) if im.get("origin") == "platform")
    missing_covers = sum(bool(r.get("is_video")) and not (r.get("video") or {}).get("covers") for r in records)

    pruned = stale_state = 0  # Archives and unrelated files are never auto-deleted.
    return {"ok": failures == 0 and pending == 0 and missing_covers == 0, "failed_jobs": failures,
            "pending_images": pending, "missing_video_covers": missing_covers,
            "orphan_files_removed": pruned, "stale_state_removed": stale_state, "stored_bytes": total}


def _all_image_dicts(records):
    """收集记录中所有图片/封面字典及其引用的本地路径字段。"""
    dicts = []
    for row in records:
        for im in row.get("images", []):
            dicts.append(im)
        for cover in (row.get("video") or {}).get("covers", []):
            dicts.append(cover)
    return dicts


def recompress(root, quality=84, max_dimension=1600, output_format='jpeg', single_size=False):
    """Create small display copies; archival variants and unreferenced files stay untouched."""
    root = Path(root)
    records = load(root / "records.json", [])
    count = before_bytes = after_bytes = 0
    for im in _all_image_dicts(records):
        source_rel = im.get("original_path") or im.get("large_path") or im.get("thumb_path")
        if not source_rel:
            continue
        source_file = project_file(root, source_rel)
        raw = source_file.read_bytes()
        data, ext, width, height = compress_image(raw, quality, max_dimension, output_format)
        if ext is None:
            continue
        digest = hashlib.sha256(data).hexdigest()
        relative = "display-images/" + digest + "." + ext
        target = root / relative
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            part = target.with_suffix(target.suffix + ".part")
            part.write_bytes(data)
            os.replace(part, target)
        im["display_path"] = relative
        im["display_dimensions"] = {"width": width, "height": height}
        before_bytes += len(raw)
        after_bytes += len(data)
        count += 1
    save(root / "records.json", records)
    return {"ok": True, "images_processed": count, "originals_preserved": True,
            "old_files_removed": 0, "orphan_files_removed": 0,
            "before_bytes": before_bytes, "after_bytes": after_bytes,
            "display_bytes_saved": before_bytes - after_bytes}


def register_screenshots(root, observations):
    root = Path(root)
    records = load(root / "records.json", [])
    by_id = {r["id"]: r for r in records}
    staged = []
    for obs in observations:
        rid = obs["id"]
        if rid not in by_id or obs["url"] != by_id[rid]["url"]:
            raise ValueError("截图必须关联已收录ID及其真实原文URL")
        source = project_file(root, obs["path"])
        ext, w, h = image_info(source.read_bytes())
        captured_at = timestamp(obs["captured_at"])
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        target = root / "screenshots" / (sha + "." + ext)
        staged.append((source, target, rid, {"path": target.relative_to(root).as_posix(), "origin": "browser_capture",
                                           "source_url": obs["url"], "captured_at": captured_at,
                                           "width": w, "height": h, "sha256": sha}))
    for source, target, rid, value in staged:
        target.parent.mkdir(exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        by_id[rid]["screenshot"] = value
    save(root / "records.json", records)
    return {"registered": len(staged), "note": "登记不证明截图内容正确；Agent仍须读图核对原帖"}


def save_profile_avatar(root, opener=None, timeout=20):
    """Download the exact observed profile image; no generated substitute or credentials."""
    root = Path(root); meta = load(root / "project_meta.json")
    profile = meta.get("profile", {})
    if profile.get("uid") != meta["target"]["uid"] or profile.get("avatar_origin") != "platform":
        raise ValueError("先核验并采集目标主页头像")
    url = profile.get("avatar_source_url", ""); validate_url(url)
    opener = opener or urllib.request.build_opener(PublicImageRedirect())
    request = urllib.request.Request(url, headers={"Referer": "https://weibo.com/", "User-Agent": "Mozilla/5.0"})
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl(); validate_url(final_url); data = response.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("头像超过预算；由正常浏览器图片入口保存")
    # 无签名/已失效的头像地址会被重定向到平台默认占位图，必须拦下而不是静默保存
    if final_url.rsplit("/", 1)[-1].lower().startswith("default"):
        raise ValueError("下载到平台默认占位头像（地址缺签名或已失效）；请从目标主页重新复制带 ssig&Expires 签名的 avatar_source_url")
    ext, w, h = image_info(data); digest = hashlib.sha256(data).hexdigest()
    target = root / "profile" / (digest + "." + ext); target.parent.mkdir(exist_ok=True)
    part = target.with_suffix(target.suffix + ".part"); part.write_bytes(data); os.replace(part, target)
    profile.update(avatar_path=target.relative_to(root).as_posix(), avatar_sha256=digest, avatar_dimensions={"width": w, "height": h})
    save(root / "project_meta.json", meta)
    return {"status": "saved", "path": profile["avatar_path"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--keep-sizes", action="store_true",
                        help="兼容选项；默认保留平台实际可用的多尺寸")
    plan_p.add_argument('--single-size', action='store_true', help='显式只下载一种规格；需有源端规格核对说明才能通过归档验收')
    sub.add_parser("repair-urls")
    sub.add_parser("avatar")
    down = sub.add_parser("download")
    down.add_argument("--max-mb", type=float, default=512)
    down.add_argument("--max-file-mb", type=float, default=25)
    down.add_argument("--jpeg-quality", type=int, default=84, help="保留兼容参数；下载保存源字节，展示压缩用recompress")
    down.add_argument("--max-dimension", type=int, default=0)
    down.add_argument("--format", choices=["jpeg", "webp", "auto"], default=None)
    rc = sub.add_parser("recompress", help="对已下载图片离线重新压缩，无需联网")
    rc.add_argument("--jpeg-quality", type=int, default=84)
    rc.add_argument("--max-dimension", type=int, default=1600)
    rc.add_argument("--format", choices=["jpeg", "webp", "auto"], default="jpeg")
    rc.add_argument("--keep-sizes", action="store_true",
                    help="兼容选项；原始规格始终保留，压缩仅创建display副本")
    shot = sub.add_parser("screenshots")
    shot.add_argument("--observations", type=Path, required=True)
    a = p.parse_args()
    try:
        if a.command == "repair-urls":
            result = repair_media_urls(a.project)
        elif a.command == "plan":
            result = plan(a.project, single_size=a.single_size and not a.keep_sizes)
        elif a.command == "avatar":
            result = save_profile_avatar(a.project)
        elif a.command == "download":
            result = download(a.project, a.max_mb, a.max_file_mb,
                              jpeg_quality=a.jpeg_quality, max_dimension=a.max_dimension,
                              output_format=a.format)
        elif a.command == "recompress":
            result = recompress(a.project, quality=a.jpeg_quality,
                                max_dimension=a.max_dimension, output_format=a.format,
                                single_size=False)
        else:
            result = register_screenshots(a.project, load(a.observations))
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result.get("ok", True) else 1)
    except (OSError, ValueError, KeyError, TypeError) as error:
        p.exit(1, str(error) + "\n")
