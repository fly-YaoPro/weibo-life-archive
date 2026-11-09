"""Prepare numbered photo contact sheets and a source-linked, non-publishable draft.

This helper verifies existing imported photos. It neither reads images semantically,
identifies subjects, infers dates, generates illustrations, nor writes story.json.
"""
import argparse
import json
import math
import os
import tempfile
from pathlib import Path

from archive_common import load, project_file, save
from photo_contract import photo_date_label
from runtime_contract import validate_runtime


def _output(root, relative):
    """Do not follow a planted output link, even if it resolves inside the project."""
    path = project_file(root, relative, exists=False)
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('编写辅助输出不能经过符号链接: ' + relative)
    return path


def _existing_json(root, relative, default=None):
    path = _output(root, relative)
    return load(path, default)


def _contact_sheet(root, items, path, columns):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    tile_width, image_height, caption_height, gutter, header = 300, 210, 48, 12, 44
    rows = math.ceil(len(items) / columns)
    canvas = Image.new('RGB', (columns * (tile_width + gutter) + gutter,
                               rows * (image_height + caption_height + gutter) + header + gutter), '#f1f0eb')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((gutter, 14), 'PHOTO REVIEW / numbered sources / not a finished journal', fill='#30312d', font=font)
    for cell, item in enumerate(items):
        left = gutter + (cell % columns) * (tile_width + gutter)
        top = header + (cell // columns) * (image_height + caption_height + gutter)
        draw.rectangle((left, top, left + tile_width, top + image_height + caption_height), fill='white')
        with Image.open(project_file(root, item['image_path'])) as original:
            original.load()
            thumb = ImageOps.contain(original.convert('RGBA'), (tile_width - 12, image_height - 12))
            flattened = Image.new('RGB', thumb.size, 'white')
            flattened.paste(thumb, mask=thumb.getchannel('A'))
            canvas.paste(flattened, (left + (tile_width - flattened.width) // 2,
                                    top + (image_height - flattened.height) // 2))
        draw.text((left + 9, top + image_height + 5),
                  '%04d  |  %s' % (item['number'], item['date'] or 'date unknown'), fill='#30312d', font=font)
        draw.text((left + 9, top + image_height + 23), item['source_id'], fill='#4c4d48', font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.jpg', dir=path.parent)
    os.close(descriptor)
    try:
        # A freshly made RGB canvas has no original EXIF, filenames or GPS.
        canvas.save(name, format='JPEG', quality=87, optimize=True)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _draft(records, observations):
    """Fill references, not prose. Empty authored fields deliberately fail final validation."""
    ids = [row['id'] for row in records]
    refs = [{'source_id': row['id'], 'image_path': row['images'][0]['large_path']} for row in records]
    covers = refs[:3]
    objects = [{'name': '', 'evidence_kind': 'image',
                'evidence': observations.get(ref['source_id'], '') or '',
                'source_ids': [ref['source_id']], 'image_path': ref['image_path'],
                'placement': '', 'representation': 'literal'} for ref in covers]
    return {
        'status': 'draft_not_publishable',
        'authoring': {
            'publishable': False,
            'source_image_map': refs,
            'instructions': [
                '这是结构草稿，不是完成的story.json；脚本没有读懂图片。',
                '先看全部编号联系表，打开代表图/存疑图大图，在photo-reading.json里写实际观察。',
                'themes只给一个结构示例；按实际事件或阶段重组source_ids及image_paths，不按联系表页码划章节。',
                '所有空白文字由实际照片和用户提供背景填写；身份、关系、日期和地点不猜测。',
                'scene.objects示例使用仅图证据：evidence_kind=image，image_path须属于该source_ids里的每条记录；evidence写实际可见物件。',
                '首尾插画生成后填写decorations内实际路径，首图物件标定及热点坐标须按生成图实测，不预填虚构坐标。',
                '完成写作与插画后另存story.json并运行正常构建；本草稿故意留空，不能直接发布。',
            ],
        },
        'evidence': [{'kind': 'image', **ref, 'observation': observations.get(ref['source_id'], '') or ''} for ref in refs],
        'overview': {'headline': '', 'opening': '', 'text': '', 'source_ids': ids,
                     'portrait': {'title': '', 'text': '', 'tags': [], 'source_ids': ids},
                     'image_refs': [{'source_id': ref['source_id'], 'image_index': 0} for ref in covers],
                     'image_paths': [ref['image_path'] for ref in covers], 'image_captions': {}},
        'themes': [{'id': 'theme-1', 'title': '', 'text': '', 'layout': 'A',
                    'source_ids': ids,
                    'image_refs': [{'source_id': ref['source_id'], 'image_index': 0} for ref in refs],
                    'image_paths': [ref['image_path'] for ref in refs], 'image_captions': {}}],
        'scene': {'image_path': '', 'alt': '', 'source_ids': [ref['source_id'] for ref in covers],
                  'objects': objects, 'hotspots': [], 'guidance': '', 'mobile_guidance': ''},
        'letter': {'title': '', 'paragraphs': [], 'closing': '', 'source_ids': ids,
                   'image_path': '', 'image_alt': ''},
        'wishes': [{'id': 'wish-1', 'title': '', 'text': '', 'source_ids': ids}],
        'share': {'headline': '', 'text': '', 'letter_text': '',
                  'entries': [{'source_id': ref['source_id'], 'title': '', 'text': ''} for ref in covers]},
    }


def prepare_authoring(project, *, per_sheet=20, columns=4):
    """Verify -> make complete contact sheets -> preserve readings -> create draft once."""
    if type(per_sheet) is not int or not 1 <= per_sheet <= 36:
        raise ValueError('per_sheet须为1—36的整数')
    if type(columns) is not int or not 1 <= columns <= 6:
        raise ValueError('columns须为1—6的整数')
    project_path = Path(project)
    if project_path.is_symlink():
        raise ValueError('项目目录不能是符号链接')
    root = project_path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('project须为已导入的照片项目目录')
    meta = load(project_file(root, 'project_meta.json'))
    records = load(project_file(root, 'records.json'))
    if not isinstance(meta, dict) or meta.get('platform') != 'photos':
        raise ValueError('本辅助仅处理platform:photos；微博沿用原有记录工具')
    if not isinstance(records, list) or not records:
        raise ValueError('先导入至少一张可读照片')
    # Reuse the normal schema, path containment, decoded bytes, hash and EXIF checks.
    validate_runtime(meta, records, root=root)
    prior = _existing_json(root, 'photo-reading.json', {})
    if not isinstance(prior, dict) or not isinstance(prior.get('items', []), list):
        raise ValueError('已有photo-reading.json结构无效，停止覆盖')
    old_items = {}
    for item in prior.get('items', []):
        if not isinstance(item, dict) or not isinstance(item.get('source_id'), str):
            raise ValueError('已有读图记录需为带source_id的对象，停止覆盖')
        if item['source_id'] in old_items:
            raise ValueError('已有读图记录source_id重复，停止覆盖')
        old_items[item['source_id']] = item
    items, reading = [], []
    for index, record in enumerate(records):
        sheet = '.private/photo-authoring/contact-sheet-%03d.jpg' % (index // per_sheet + 1)
        ref = {'number': index + 1, 'source_id': record['id'],
               'image_path': record['images'][0]['large_path'], 'date': record.get('date'),
               'date_precision': record['date_precision'], 'date_label': photo_date_label(record),
               'contact_sheet': sheet, 'cell': index % per_sheet + 1}
        items.append(ref)
        # Keep authored observations and extra review fields; do not invent review status.
        reading.append({**old_items.get(record['id'], {}), 'source_id': ref['source_id'],
                        'image_path': ref['image_path'], 'date_label': ref['date_label'],
                        'observation': old_items.get(record['id'], {}).get('observation'),
                        'number': ref['number'], 'contact_sheet': sheet, 'cell': ref['cell']})
    sheets = [{'path': items[offset]['contact_sheet'],
               'numbers': [item['number'] for item in items[offset:offset + per_sheet]],
               'source_ids': [item['source_id'] for item in items[offset:offset + per_sheet]]}
              for offset in range(0, len(items), per_sheet)]
    # Validate every output before writing any generated helper file.
    paths = [_output(root, sheet['path']) for sheet in sheets]
    reading_path = _output(root, 'photo-reading.json')
    index_path = _output(root, 'photo-authoring-index.json')
    draft_path = _output(root, 'story-draft.json')
    for offset, path in zip(range(0, len(items), per_sheet), paths):
        _contact_sheet(root, items[offset:offset + per_sheet], path, min(columns, per_sheet))
    save(reading_path, {**prior, 'status': prior.get('status', 'awaiting_actual_image_review'), 'items': reading})
    index = {'schema_version': 1, 'status': 'awaiting_actual_image_review', 'publishable': False,
             'all_imported_photos_covered': True, 'photo_count': len(records), 'sheets': sheets, 'items': items,
             'note': '联系表和编号是读图辅助，不代表已经读图或完成故事；仅使用去EXIF的项目内副本，不读取私有元数据。'}
    save(index_path, index)
    created = not draft_path.exists()
    if created:
        observations = {item['source_id']: item.get('observation') for item in reading}
        save(draft_path, _draft(records, observations))
    return {'ok': True, 'stage': 'photo_authoring_preparation', 'photo_count': len(records),
            'contact_sheets': [sheet['path'] for sheet in sheets], 'index': 'photo-authoring-index.json',
            'reading': 'photo-reading.json', 'draft': 'story-draft.json', 'draft_created': created,
            'existing_draft_preserved': not created, 'story_json_modified': False,
            'semantic_image_review_performed': False, 'ready_to_publish': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='已导入、含records.json的照片项目目录')
    parser.add_argument('--per-sheet', type=int, default=20)
    parser.add_argument('--columns', type=int, default=4)
    args = parser.parse_args()
    try:
        result = prepare_authoring(args.source, per_sheet=args.per_sheet, columns=args.columns)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'ok': False, 'stage': 'photo_authoring_preparation', 'error': str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
