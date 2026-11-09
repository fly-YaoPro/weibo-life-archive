"""Read-only full story preflight, reusing the actual build/runtime validators."""
from pathlib import Path
from archive_common import date_key, load, project_file
from experience import validate_narrative, validate_experience, record_image_paths


def check_story_project(root, kind='weibo'):
    from check_project import check
    from build_journal import prepare
    root = Path(root).resolve()
    data = check(root, kind, 'data')
    errors, warnings = list(data['errors']), list(data['warnings'])
    try:
        meta = load(root / 'project_meta.json')
        records = load(root / ('records.json' if kind in {'weibo','photos'} else 'orders.json'))
        from story_tools import compile_project
        story = compile_project(root)
        if not isinstance(story, dict) or not isinstance(records, list):
            raise ValueError('story must be an object and records must be an array')
        from photo_contract import photo_date
        rows = [{**r, 'id': r.get('id', r.get('order_id')),
                 'date': photo_date(r) if kind=='photos' else date_key(r.get('created_at', r.get('placed_at'))),
                 'text': r.get('text', '\n'.join(i.get('name', '') for i in r.get('items', [])))}
                for r in records if isinstance(r, dict)]
        from story_shape import shape_errors
        schema = shape_errors(story)
        if schema:
            return {**data, 'ok': False, 'stage': 'story', 'errors': list(dict.fromkeys(errors + schema)),
                    'build_ready': False, 'note': 'Fix all listed field shapes, then rerun the full preflight.'}
        by_id = {r['id']: r for r in rows}
        def walk(value, field='$'):
            if isinstance(value, dict):
                ids = value.get('source_ids')
                if field.startswith('$.share.entries[') and 'source_id' in value:
                    ids = [value['source_id']]
                if ids is not None and (not isinstance(ids, list) or not ids or
                    any(not isinstance(i, str) or i not in by_id for i in ids) or
                    len(ids) != len(set(ids))):
                    errors.append(field + '.source_ids: nonempty, unique retained source IDs required')
                sid, quote = value.get('source_id'), value.get('quote')
                if quote is not None and (sid not in by_id or not isinstance(quote, str) or
                                         not quote or quote not in by_id[sid]['text']):
                    errors.append(field + '.quote: exact contiguous original text required (including whitespace and script)')
                if isinstance(ids, list) and all(isinstance(i, str) and i in by_id for i in ids):
                    allowed = set().union(*(record_image_paths(by_id[i]) for i in ids)) if ids else set()
                    for path in value.get('image_paths', []) if isinstance(value.get('image_paths', []), list) else []:
                        if path not in allowed:
                            owners = [rid for rid, row in by_id.items() if path in record_image_paths(row)]
                            errors.append(field + '.image_paths: image not owned by cited sources: ' + str(path) +
                                          '; cited=' + repr(ids) + '; actual_owners=' + repr(owners) +
                                          '; use image_refs from the current retained index')
                for key, child in value.items():
                    if key in ('image_path', 'image_paths'):
                        paths = child if isinstance(child, list) else [child]
                        for path in paths:
                            try: project_file(root, path)
                            except (ValueError, OSError, TypeError) as exc:
                                errors.append(field + '.' + key + ': ' + str(exc))
                    walk(child, field + '.' + key)
            elif isinstance(value, list):
                for n, child in enumerate(value): walk(child, f'{field}[{n}]')
        walk(story)
        required = meta.get('presentation', {})
        if required.get('experience_required'):
            for field in ('scene', 'letter'):
                value = story.get(field)
                if not isinstance(value, dict) or not value.get('image_path'):
                    errors.append(field + '.image_path: required generated illustration is missing')
        if required.get('cover_required'):
            overview = story.get('overview', {})
            for field in ('opening', 'portrait'):
                if not isinstance(overview, dict) or not overview.get(field):
                    errors.append('overview.' + field + ': required cover content is missing')
        if required.get('three_wishes_required') and not story.get('wishes'):
            errors.append('wishes: nonempty grounded read-only wishes required')
        for validator in (
            lambda: validate_narrative(story, rows, required.get('grounding_required', False), errors=errors),
            lambda: validate_experience(root, story, rows, required.get('grounding_required', False), errors=errors),
        ):
            try: validator()
            except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
                errors.append(str(exc))
        try:
            prepare(root, meta.get('skin', 'paper') if kind in {'weibo','photos'} else 'collage', story=story, pending_music=True)
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
            errors.append(str(exc))
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        errors.append(str(exc))
    errors = list(dict.fromkeys(errors))
    return {**data, 'ok': not errors, 'stage': 'story', 'errors': errors,
            'warnings': list(dict.fromkeys(warnings)), 'build_ready': not errors,
            'note': 'Independent section errors use build rules. Dependent errors may surface after structural fixes; this is static validation. Perform the separate bounded scene click check; no full-site browser suite is required.'}
