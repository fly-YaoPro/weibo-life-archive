#!/usr/bin/env python3
"""Supplement >9-image retained posts through the normal detail API (statuses/show).

The mobile list API truncates ``pics`` to 9 even though ``pic_num`` is the true total.
This module fetches the full detail mblog, enumerates every real source image, merges the
complete inventory without lowering the denominator, and carries over already-saved files so
``manage_media`` only downloads the missing positions. It never fabricates image ids or zeros.
"""
import argparse
import hashlib
import json
from pathlib import Path

from archive_common import identifier, load, save, BEIJING, clean_html
from datetime import datetime
from archive_pipeline import normalize

# Path keys that prove an image already has a usable local file.
_PATH_KEYS = ("thumb_path", "large_path", "original_path")
_CARRY_KEYS = _PATH_KEYS + ("thumb_dimensions", "large_dimensions", "download_status")


def detail_show_url(source_id):
    return "https://m.weibo.cn/statuses/show?id=" + identifier(source_id)


def fetch_detail_mblog(bu, uid, source_id):
    """Download and strictly validate one full detail mblog; reject login/error/other-author/truncation."""
    source_id = identifier(str(source_id))
    receipt = bu.download(detail_show_url(source_id),
                          filename="detail-%s.json" % source_id, timeout=30)
    raw = Path(receipt["path"]).read_bytes()
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid_or_truncated_json: detail response is not parseable JSON")
    if not isinstance(envelope, dict):
        raise ValueError("invalid_snapshot: detail envelope is not an object")
    if envelope.get("ok") != 1 or not isinstance(envelope.get("data"), dict):
        raise ValueError("business_error_or_verification: detail ok!=1")
    mblog = envelope["data"]
    if str(mblog.get("user", {}).get("id")) != identifier(uid):
        raise ValueError("other_author: detail user does not match target uid")
    if identifier(str(mblog.get("idstr") or mblog.get("id") or "")) != source_id:
        raise ValueError("detail id mismatch: %s != %s" % (mblog.get("id"), source_id))
    if not mblog.get("created_at"):
        raise ValueError("detail missing created_at; do not invent a date")
    if "pics" not in mblog and mblog.get("pic_num") == 0:
        mblog["pics"] = []
    if not isinstance(mblog.get("pics"), list):
        raise ValueError("detail missing pics inventory")
    return mblog


def _carry_over(new_images, old_images):
    """Preserve local files/state for images already present, keyed by the real source URL."""
    old_by_url = {im.get("source_url"): im for im in old_images if isinstance(im, dict)}
    reused = 0
    for im in new_images:
        prior = old_by_url.get(im.get("source_url"))
        if not prior:
            continue
        has_file = any(prior.get(k) for k in _PATH_KEYS)
        for key in _CARRY_KEYS:
            if prior.get(key) is not None:
                im[key] = prior[key]
        if has_file:
            reused += 1
    return reused


def fetch_extended_text(bu, root, source_id):
    """Fetch full text for the same ID verified by statuses/show; preserve raw bytes."""
    source_id = identifier(str(source_id))
    url = 'https://m.weibo.cn/statuses/extend?id=' + source_id
    receipt = bu.download(url, filename='extend-%s.json' % source_id, timeout=30)
    raw = Path(receipt['path']).read_bytes()
    try:
        envelope = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('invalid_or_truncated_json: extend response is not JSON')
    if not isinstance(envelope, dict) or envelope.get('ok') != 1 or not isinstance(envelope.get('data'), dict):
        raise ValueError('business_error_or_verification: extend ok!=1')
    data = envelope['data']
    returned_id = data.get('idstr') or data.get('id') or data.get('mid')
    if returned_id is not None and str(returned_id) != source_id:
        raise ValueError('extend id mismatch')
    html = data.get('longTextContent')
    if not isinstance(html, str) or not html.strip():
        raise ValueError('extend missing longTextContent; keep full text pending')
    text, links = clean_html(html)
    import re
    if not text.strip() or re.search(r'(展开全文|全文|展开)\s*$', text):
        raise ValueError('extend text is empty or still collapsed; keep pending')
    digest = hashlib.sha256(raw).hexdigest()
    evidence = 'detail-text/' + source_id + '-' + digest[:16] + '.json'
    destination = Path(root)/evidence
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists(): destination.write_bytes(raw)
    return text, links, evidence


def supplement_record(bu, root, source_id):
    """Replace one record's truncated 9-image list with the verified complete detail inventory."""
    root = Path(root)
    source_id = identifier(str(source_id))
    meta = load(root / "project_meta.json")
    uid = meta["target"]["uid"]
    records = load(root / "records.json")
    record = next((r for r in records if identifier(r["id"]) == source_id), None)
    if record is None:
        raise ValueError("retained id not found in records.json: " + source_id)

    detail = fetch_detail_mblog(bu, uid, source_id)
    full, reason = normalize(detail, uid)
    if full is None:
        raise ValueError("detail normalize rejected: " + str(reason))

    new_images = full["images"]
    expected = full["expected_image_count"]
    if type(expected) is not int or expected != len(new_images):
        raise ValueError("detail enumeration %s != expected %r; keep gap rather than force"
                         % (len(new_images), expected))
    observed = [record.get('expected_image_count'), len(record.get('images', []))]
    observed += [c.get('expected_image_count') for c in load(root/'candidates.json', [])
                 if str(c.get('id')) == source_id]
    floor = max([v for v in observed if type(v) is int] or [0])
    if expected < floor:
        raise ValueError('detail source count below prior observed inventory; preserve records and investigate')
    reused = _carry_over(new_images, record.get("images", []))

    # A detail response may also resolve a collapsed list text. Never assume length proves completion.
    text_error = None
    if full['text_status'] == 'pending':
        try:
            text, links, evidence = fetch_extended_text(bu, root, source_id)
            record.update(text=text, links=links, text_status='complete', text_basis=evidence)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            text_error = str(exc)
    elif full['text_status'] == 'complete':
        record.update(text=full['text'], links=full['links'], text_status='complete',
                      text_basis='verified same-ID statuses/show response without collapse marker')
    record["images"] = new_images
    record["expected_image_count"] = expected
    record["image_count_basis"] = (full.get("image_count_basis") or "") + " + detail/statuses.show"
    record["image_inventory_status"] = "complete"
    save(root / "records.json", records)
    return {"source_id": source_id, "expected": expected,
            "enumerated": len(new_images), "reused_saved": reused,
            "new_positions": len(new_images) - reused, "text_status": record.get("text_status"),
            "text_error": text_error}


def _ids_needing_supplement(root):
    """Records whose retained inventory is below the observed candidate source count."""
    root = Path(root)
    observed = {str(c.get("id")): c.get("expected_image_count")
                for c in load(root / "candidates.json", [])
                if isinstance(c.get("expected_image_count"), int)}
    ids = []
    for r in load(root / "records.json", []):
        rid = str(r["id"])
        true_count = observed.get(rid)
        if r.get("text_status") == "pending" or (isinstance(true_count, int) and len(r.get("images", [])) < true_count):
            ids.append(rid)
    return ids


def supplement_text_from_page(bu, root, source_id, selectors, *, expanded=False):
    """Merge a caller-verified expanded normal detail page without replacing photo inventory.

    The caller opens /detail/<mid>, verifies the selectors once and expands the text.
    No text length or isLongText flag is used as evidence of completeness.
    """
    if expanded is not True:
        raise ValueError('先在正常详情页确认正文已展开，再传 expanded=True')
    from browser_helpers import capture_detail
    import re
    root = Path(root); source_id = identifier(str(source_id))
    records = load(root/'records.json')
    record = next((r for r in records if r['id'] == source_id), None)
    if record is None: raise ValueError('retained id not found: ' + source_id)
    uid = load(root/'project_meta.json')['target']['uid']
    observed = capture_detail(bu, source_id, uid, record['created_at'], selectors)
    if not observed['text'].strip() or re.search(r'(展开全文|全文|展开)\s*$', observed['text']):
        raise ValueError('详情正文为空或仍含展开标记；保留 pending')
    digest = hashlib.sha256(observed['text'].encode('utf-8')).hexdigest()
    evidence = 'detail-text/' + source_id + '-' + digest[:16] + '.json'
    snapshot = {**observed, 'expanded_observed':True, 'selectors':selectors,
                'captured_at':datetime.now(BEIJING).isoformat(), 'text_sha256':digest}
    if not (root/evidence).exists(): save(root/evidence, snapshot)
    record.update(text=observed['text'], text_status='complete', text_basis=evidence)
    save(root/'records.json', records)
    return {'source_id':source_id, 'text_status':'complete', 'evidence':evidence,
            'images_preserved':len(record.get('images', []))}


def supplement_inventory(bu, root, ids=None):
    """Batch-supplement explicit ids (or auto-detect every below-denominator retained record)."""
    root = Path(root)
    ids = [identifier(str(i)) for i in ids] if ids else _ids_needing_supplement(root)
    results, errors = [], []
    for sid in ids:
        try:
            result = supplement_record(bu, root, sid)
            results.append(result)
            if result.get('text_error'):
                errors.append({'source_id': sid, 'error': result['text_error']})
                if any(k in result['text_error'] for k in ('login', 'verification', 'business_error')):
                    break
        except (ValueError, KeyError, TypeError, OSError) as exc:
            # stop on auth/verification; record other failures without lowering any count
            errors.append({"source_id": sid, "error": str(exc)})
            if any(k in str(exc) for k in ("login", "verification", "business_error")):
                break
    return {"processed": len(results), "errors": errors, "results": results,
            "total_expected": sum(r["expected"] for r in results),
            "total_new_positions": sum(r["new_positions"] for r in results)}


def register_external_cover(root, source_id, local_path):
    """Register a browser-fetched non-sinaimg video cover after validating it is a real image."""
    root = Path(root)
    source_id = identifier(str(source_id))
    records = load(root / "records.json")
    record = next((r for r in records if identifier(r["id"]) == source_id), None)
    if record is None:
        raise ValueError("retained id not found: " + source_id)
    covers = (record.get("video") or {}).get("covers")
    if not covers:
        raise ValueError("record has no video covers")
    data = Path(local_path).read_bytes()
    from manage_media import image_info
    ext, width, height = image_info(data)  # raises on HTML/error/partial files
    digest = hashlib.sha256(data).hexdigest()
    target = root / "images" / (digest + "." + ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    rel = target.relative_to(root).as_posix()
    for im in covers:
        im["thumb_path"] = im["large_path"] = rel
        im["thumb_dimensions"] = im["large_dimensions"] = {"width": width, "height": height}
        im["download_status"] = "saved"
    save(root / "records.json", records)
    return {"source_id": source_id, "path": rel, "width": width, "height": height}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--ids", nargs="*", help="retained source ids; default auto-detect all gaps")
    args = parser.parse_args()
    # The native browser object is injected by the harness; import the same module the cell uses.
    import aha_browser_use as bu
    print(json.dumps(supplement_inventory(bu, args.project, args.ids), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise SystemExit(str(exc))
