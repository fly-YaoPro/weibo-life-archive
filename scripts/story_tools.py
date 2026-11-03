#!/usr/bin/env python3
"""Local source index, exact quotes, missing-media queue, and deterministic draft compilation."""
import argparse
import copy
import json
import hashlib
from pathlib import Path
from archive_common import load, project_file


def write_new(path, value):
    path = Path(path)
    if path.exists(): raise ValueError('Output exists; use a new path: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def source_index(root, candidates=False):
    root = Path(root)
    records = load(root / ('candidates.json' if candidates else 'records.json'))
    if not isinstance(records, list): raise ValueError('Missing record array')
    observed = {str(r['id']): r.get('expected_image_count') for r in load(root/'candidates.json', [])
                if isinstance(r, dict) and 'id' in r and type(r.get('expected_image_count')) is int}
    indexed, pending = [], []
    for row in records:
        images = row.get('images', [])
        indexed.append({'id': row['id'], 'created_at': row['created_at'], 'text': row.get('text', ''),
            'url': row.get('url'), 'text_status': row.get('text_status'),
            'expected_image_count': row.get('expected_image_count'),
            'image_inventory_status': row.get('image_inventory_status'),
            'images': [{'image_index': n, **{k: im.get(k) for k in
                ('image_id','original_path','large_path','thumb_path','source_url','download_status')}}
                for n, im in enumerate(images)],
            'video_covers': row.get('video', {}).get('covers', [])})
        reasons = []
        if row.get('text_status') != 'complete': reasons.append('full_text')
        observed_count = observed.get(str(row['id']))
        if row.get('expected_image_count') is None or row.get('image_inventory_status') != 'complete' or row.get('expected_image_count') != len(images) or (observed_count is not None and len(images) < observed_count):
            reasons.append('source_image_inventory')
        def saved_file(im):
            try:
                return project_file(root, im.get('original_path') or im.get('large_path') or im.get('thumb_path')).is_file()
            except (ValueError, OSError, TypeError): return False
        failed = [n for n, im in enumerate(images) if im.get('download_status') != 'saved' or not saved_file(im)]
        if failed: reasons.append('photo_download')
        if row.get('is_video') and (not row.get('video', {}).get('covers') or
            any(im.get('download_status') != 'saved' for im in row['video']['covers'])):
            reasons.append('video_cover')
        if reasons: pending.append({'source_id': row['id'], 'url': row.get('url'),
            'reasons': reasons, 'expected_image_count': row.get('expected_image_count'),
            'observed_source_image_count': observed_count, 'enumerated': len(images), 'failed_image_indexes': failed})
    return {'source': {'project': str(root.resolve()), 'target_uid': load(root/'project_meta.json')['target']['uid'],
                       'file': 'candidates.json' if candidates else 'records.json',
                       'sha256': hashlib.sha256((root/('candidates.json' if candidates else 'records.json')).read_bytes()).hexdigest()},
            'records': indexed, 'pending': pending, 'record_count': len(indexed),
            'pending_records': len(pending), 'mode': 'candidates' if candidates else 'retained'}


def compile_project(root):
    root = Path(root).resolve()
    path = root/'story.json'
    if not path.is_file():
        hint = '; found nested story/story.json, move it to the project root' if (root/'story/story.json').is_file() else ''
        raise ValueError('Missing story file: ' + str(path) + hint)
    draft = load(path)
    if not isinstance(draft, dict): raise ValueError(str(path) + ': story must be an object')
    return compile_draft(root, draft)


def exact_quote(records, source_id, start, end):
    row = next((r for r in records if r['id'] == source_id), None)
    if row is None: raise ValueError('Unknown retained source ID: ' + source_id)
    text = row.get('text', '')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError('Quote span must use valid Python Unicode character offsets [start,end)')
    return text[start:end]


def compile_draft(root, draft):
    root = Path(root)
    records = load(root / 'records.json')
    by_id = {r['id']: r for r in records}
    result = copy.deepcopy(draft)
    def walk(value):
        if isinstance(value, dict):
            if 'quote_span' in value:
                span = value.pop('quote_span')
                if not isinstance(span, list) or len(span) != 2: raise ValueError('quote_span must be [start,end]')
                quote = exact_quote(records, value.get('source_id'), *span)
                if value.get('quote') is not None and value['quote'] != quote:
                    raise ValueError('Explicit quote disagrees with quote_span')
                value['quote'] = quote
            if 'image_refs' in value:
                paths = []
                ids = value.get('source_ids', [])
                for ref in value.pop('image_refs'):
                    sid, n = ref.get('source_id'), ref.get('image_index')
                    if sid not in by_id or sid not in ids or type(n) is not int or n < 0:
                        raise ValueError('Image reference must belong to the section cited sources')
                    images = by_id[sid].get('images', [])
                    if n >= len(images): raise ValueError('image_index outside source inventory')
                    im = images[n]
                    path = im.get('original_path') or im.get('large_path') or im.get('thumb_path')
                    project_file(root, path)
                    paths.append(path)
                if 'image_paths' in value and value['image_paths'] != paths:
                    raise ValueError('Explicit image_paths disagree with image_refs')
                value['image_paths'] = paths
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(result)
    for field, key in (('scene', 'source_ids'), ('letter', 'image_source_ids')):
        section = result.get(field)
        if isinstance(section, dict) and section.get('objects'):
            ids = sorted({sid for obj in section['objects'] for sid in obj.get('source_ids', [])})
            if any(sid not in by_id for sid in ids): raise ValueError('Object source ID not retained')
            section[key] = ids
            if field == 'letter':
                section['source_ids'] = list(dict.fromkeys(section.get('source_ids', []) + ids))
    scene = result.get('scene')
    if isinstance(scene, dict):
        objects = scene.get('objects', [])
        names = {o.get('name'): o for o in objects if o.get('name')}
        for n, hotspot in enumerate(scene.get('hotspots', [])):
            if not isinstance(hotspot, dict): continue
            obj = names.get(hotspot.get('object_name') or hotspot.get('name') or hotspot.get('label'))
            index = hotspot.get('object_index')
            if obj is None and type(index) is int and 0 <= index < len(objects): obj = objects[index]
            if obj:
                hotspot.setdefault('object_name', obj['name'])
                hotspot.setdefault('source_ids', list(obj.get('source_ids', [])))
                hotspot.setdefault('id', 'hotspot-' + str(n + 1))
                hotspot.setdefault('label', obj['name'])
                hotspot.setdefault('description', obj.get('rationale') or obj.get('evidence') or obj['name'])
            target = hotspot.get('target')
            if isinstance(target, str):
                target = {'view': target} if target in {'review','calendar','stats','future','plans'} else {'view':'review','theme_id':target}
            if target is None: target = {'view':'review'}
            if isinstance(target, dict):
                target = dict(target)
                if target.get('view') == 'theme': target['view'] = 'review'
                if 'theme' in target: target.setdefault('theme_id', target.pop('theme'))
                target.setdefault('view', 'review')
            hotspot['target'] = target
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    index = sub.add_parser('index'); index.add_argument('--output', type=Path, required=True);index.add_argument('--candidates', action='store_true')
    quote = sub.add_parser('quote'); quote.add_argument('--id', required=True);quote.add_argument('--start',type=int,required=True);quote.add_argument('--end',type=int,required=True)
    compile_ = sub.add_parser('compile');compile_.add_argument('--draft',type=Path,required=True);compile_.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.command == 'quote':
        print(json.dumps({'source_id':args.id,'quote':exact_quote(load(args.project/'records.json'),args.id,args.start,args.end)},ensure_ascii=False));return
    value = source_index(args.project,args.candidates) if args.command == 'index' else compile_draft(args.project,load(args.draft))
    if args.command == 'index' and args.output.exists():
        if load(args.output) != value:
            args.output = args.output.with_name(args.output.stem + '-' + value['source']['sha256'][:12] + args.output.suffix)
        if args.output.exists() and load(args.output) != value:
            raise ValueError('Conflicting index at ' + str(args.output))
    if not args.output.exists():
        write_new(args.output,value)
    elif args.command != 'index':
        raise ValueError('Output exists; use a new path: ' + str(args.output))
    print(json.dumps({'ok':True,'output':str(args.output),'records':value.get('record_count'),'pending':value.get('pending_records')},ensure_ascii=False))


if __name__ == '__main__':
    try: main()
    except (ValueError,KeyError,TypeError,OSError) as exc: raise SystemExit(str(exc))
