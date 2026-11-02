#!/usr/bin/env python3
"""Batch-check story.json for source_ids and image_paths consistency.

Returns ALL issues at once (not just the first failure) so fixes can be batched.
Checks:
  1. Every source_id in story.json exists in records.json
  2. Every image_path in story themes belongs to one of that theme's source_ids
  3. Every image_path actually exists on disk
  4. evidence quotes match record text (basic substring check)
"""
import argparse
import json
from pathlib import Path
from collections import defaultdict


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as e:
        return None, str(e)


def collect_records_index(records):
    """Build index: record_id -> {text, image_paths, video_cover_paths}"""
    index = {}
    for r in records:
        rid = r.get('id')
        if not rid:
            continue
        imgs = set()
        for img in r.get('images', []):
            for k in ('original_path', 'large_path', 'thumb_path'):
                p = img.get(k)
                if p:
                    imgs.add(p)
        covers = set()
        for c in r.get('video', {}).get('covers', []):
            for k in ('original_path', 'large_path', 'thumb_path'):
                p = c.get(k)
                if p:
                    covers.add(p)
        index[str(rid)] = {
            'text': r.get('text', '') or '',
            'image_paths': imgs,
            'cover_paths': covers,
            'all_paths': imgs | covers,
        }
    return index


def find_all_source_ids(obj, path='$'):
    """Recursively find all source_ids lists and their locations."""
    findings = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'source_ids' and isinstance(v, list):
                findings.append((path + '.source_ids', v))
            else:
                findings.extend(find_all_source_ids(v, f'{path}.{k}'))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            findings.extend(find_all_source_ids(item, f'{path}[{i}]'))
    return findings


def find_all_image_paths(obj, path='$'):
    """Recursively find all image_paths lists and their locations."""
    findings = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'image_paths' and isinstance(v, list):
                findings.append((path + '.image_paths', v))
            else:
                findings.extend(find_all_image_paths(v, f'{path}.{k}'))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            findings.extend(find_all_image_paths(item, f'{path}[{i}]'))
    return findings


def check_story(root: Path):
    errors = []
    warnings = []

    records = load_json(root / 'records.json')
    story = load_json(root / 'story.json')

    if records is None:
        errors.append('records.json: cannot load')
        return errors, warnings
    if story is None:
        errors.append('story.json: cannot load')
        return errors, warnings

    record_index = collect_records_index(records)
    valid_ids = set(record_index.keys())

    # ---- 1. Check all source_ids exist in records ----
    all_sid_locations = find_all_source_ids(story)
    invalid_sids = []
    for loc, sids in all_sid_locations:
        for sid in sids:
            if str(sid) not in valid_ids:
                invalid_sids.append({'location': loc, 'source_id': sid})

    if invalid_sids:
        errors.append({
            'type': 'invalid_source_ids',
            'message': f'{len(invalid_sids)} source_id(s) not found in records.json',
            'items': invalid_sids,
        })

    # ---- 2. Check theme image_paths belong to theme source_ids ----
    themes = story.get('themes', [])
    theme_img_issues = []
    for t in themes:
        tid = t.get('id', '?')
        t_sids = {str(s) for s in t.get('source_ids', [])}
        # gather all valid paths from this theme's records
        valid_theme_paths = set()
        for sid in t_sids:
            if sid in record_index:
                valid_theme_paths |= record_index[sid]['all_paths']
        for img_path in t.get('image_paths', []):
            if img_path not in valid_theme_paths:
                # find which record actually owns this path
                owner = None
                for rid, rdata in record_index.items():
                    if img_path in rdata['all_paths']:
                        owner = rid
                        break
                theme_img_issues.append({
                    'theme_id': tid,
                    'image_path': img_path,
                    'theme_source_ids': sorted(t_sids),
                    'actual_owner': owner,
                })

    if theme_img_issues:
        errors.append({
            'type': 'theme_image_path_mismatch',
            'message': f'{len(theme_img_issues)} theme image_path(s) do not belong to theme source_ids',
            'items': theme_img_issues,
        })

    # ---- 3. Check all image_paths exist on disk ----
    all_img_locations = find_all_image_paths(story)
    missing_files = []
    for loc, paths in all_img_locations:
        for p in paths:
            if not (root / p).is_file():
                missing_files.append({'location': loc, 'path': p})

    if missing_files:
        errors.append({
            'type': 'missing_image_files',
            'message': f'{len(missing_files)} image file(s) not found on disk',
            'items': missing_files,
        })

    # ---- 4. Check evidence quotes match record text ----
    evidence = story.get('evidence', [])
    evidence_issues = []
    for i, ev in enumerate(evidence):
        sid = str(ev.get('source_id', ''))
        quote = ev.get('quote', '')
        if sid not in record_index:
            continue  # already reported above
        text = record_index[sid]['text']
        if quote and quote not in text:
            # try whitespace-normalized match
            norm_text = ' '.join(text.split())
            norm_quote = ' '.join(quote.split())
            if norm_quote not in norm_text:
                evidence_issues.append({
                    'index': i,
                    'source_id': sid,
                    'quote': quote[:60] + ('...' if len(quote) > 60 else ''),
                    'issue': 'quote not found in record text',
                })

    if evidence_issues:
        errors.append({
            'type': 'evidence_quote_mismatch',
            'message': f'{len(evidence_issues)} evidence quote(s) not matching record text',
            'items': evidence_issues,
        })

    # ---- 5. Check scene/letter image_paths exist and are in decorations/ ----
    scene = story.get('scene', {})
    if scene:
        scene_img = scene.get('image_path', '')
        if scene_img:
            if not scene_img.startswith('decorations/'):
                warnings.append(f'scene.image_path: expected decorations/ prefix, got {scene_img}')
            if not (root / scene_img).is_file():
                missing_files.append({'location': '$.scene.image_path', 'path': scene_img})

    letter = story.get('letter', {})
    if letter:
        letter_img = letter.get('image_path', '')
        if letter_img:
            if not letter_img.startswith('decorations/'):
                warnings.append(f'letter.image_path: expected decorations/ prefix, got {letter_img}')
            if not (root / letter_img).is_file():
                missing_files.append({'location': '$.letter.image_path', 'path': letter_img})

    return errors, warnings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path, help='project source directory')
    p.add_argument('--json', action='store_true', help='output raw JSON')
    args = p.parse_args()

    errors, warnings = check_story(args.root.resolve())

    result = {
        'ok': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
        'summary': {
            'error_groups': len(errors),
            'warning_count': len(warnings),
        }
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Story check: {'PASS' if result['ok'] else 'FAIL'}")
        print(f"  Error groups: {len(errors)}")
        print(f"  Warnings: {len(warnings)}")
        print()
        for i, err in enumerate(errors, 1):
            print(f"[{i}] {err['type']}: {err['message']}")
            for item in err['items'][:10]:
                print(f"    - {item}")
            if len(err['items']) > 10:
                print(f"    ... and {len(err['items']) - 10} more")
            print()
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"  ! {w}")

    raise SystemExit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
