"""Read-only local photo intake; exports EXIF-free copies and an auditable manifest.

No cloud login/crawl is implemented here. Run only on a user-prepared local folder.
"""
import argparse
import calendar
import hashlib
import html
import json
import math
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from photo_contract import RASTER, filename_date, photo_date, photo_date_label, validate_photo_record


def _pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise RuntimeError('照片导入需要Pillow；请在允许的运行环境中安装后重试。不会自动pip安装。') from None
    return Image, ImageOps


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value or ':' in value:
        raise ValueError('清单file必须是素材目录内相对路径（使用/）')
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or '..' in path.parts or value in {'.', ''}:
        raise ValueError('清单file路径越界')
    return path.as_posix()


def _manifest(value):
    if value is None:
        return {}
    if isinstance(value, (str, Path)):
        value = json.loads(Path(value).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('photos'), list):
        raise ValueError('照片清单需为{schema_version:1,photos:[{file,date,note,people}]}')
    result = {}
    for item in value['photos']:
        if not isinstance(item, dict):
            raise ValueError('照片清单photos需为对象数组')
        name = _relative(item.get('file'))
        if name in result:
            raise ValueError('清单file重复: ' + name)
        if 'note' in item and not isinstance(item['note'], str):
            raise ValueError('清单note需为文字: ' + name)
        if 'people' in item and (not isinstance(item['people'], list) or any(not isinstance(person, str) for person in item['people'])):
            raise ValueError('清单people需为用户提供的文字数组: ' + name)
        if 'date' in item:
            _date_from_manifest(item)
        if item.get('created_at') and not item.get('date'):
            raise ValueError('created_at必须同时提供date: ' + name)
        result[name] = item
    return result


def _date_from_manifest(item):
    value = item.get('date')
    precision = {4: 'year', 7: 'month', 10: 'day'}.get(len(value), 'invalid') if isinstance(value, str) else 'unknown'
    photo_date({'date': value, 'date_precision': precision})
    if value is None:
        if item.get('created_at'):
            raise ValueError('未知日期不能有精确时间')
        return None, 'unknown', 'unknown', {'kind': 'unknown', 'user_explicit_unknown': True}, None
    evidence = {'kind': 'user_manifest', 'value': value}
    created = item.get('created_at')
    if created is not None:
        try:
            parsed = datetime.fromisoformat(created.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            raise ValueError('清单created_at需为真实带时区时间') from None
        if parsed.tzinfo is None or precision != 'day' or parsed.date().isoformat() != value:
            raise ValueError('清单created_at缺时区或与date不符')
        evidence['created_at'] = created
    return value, precision, 'user_manifest', evidence, created


def _date_fields(item, exif, filename):
    if 'date' in item:
        return _date_from_manifest(item)
    captured = _capture_metadata(exif)
    if captured['status'] == 'valid':
        evidence = {'kind': 'exif', 'tag': 'DateTimeOriginal', 'value': captured['raw_value']}
        if captured['offset']['status'] == 'valid':
            evidence['offset'] = captured['offset']['value']
        return captured['date'], 'day', 'exif', evidence, captured['created_at']
    # Only unmistakable date-shaped prefixes. Arbitrary IDs and filesystem dates are ignored.
    stem = Path(filename).stem
    value = filename_date(filename)
    if value:
        precision = 'day' if len(value) == 10 else 'month'
        return value, precision, 'filename', {'kind': 'filename', 'value': stem, 'filename': Path(filename).name, 'parsed_date': value}, None
    return None, 'unknown', 'unknown', {'kind': 'unknown'}, None


def _safe_files(source):
    """Do not follow symlinks, including directory links. Return visible scan failures."""
    files, rejected = [], []
    def walk_error(error):
        failed_path = Path(error.filename) if error.filename else source
        if not failed_path.is_absolute():
            failed_path = source / failed_path
        try:
            relative = failed_path.relative_to(source).as_posix()
        except ValueError:
            relative = failed_path.name
        rejected.append({'file': relative, 'reason': 'walk_error: ' + type(error).__name__ + ': ' + str(error), 'kind': 'unreadable_directory'})
    for current, dirs, names in os.walk(source, followlinks=False, onerror=walk_error):
        base = Path(current)
        for name in list(dirs):
            candidate = base / name
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(source):
                dirs.remove(name)
                rejected.append({'file': candidate.relative_to(source).as_posix(), 'reason': 'unsafe_directory_link'})
        for name in names:
            candidate = base / name
            rel = candidate.relative_to(source).as_posix()
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(source):
                rejected.append({'file': rel, 'reason': 'unsafe_file_link'})
            else:
                files.append((rel, candidate))
    return sorted(files), rejected


def _date_interval(value):
    """A partial date spans its period; these bounds never replace a record date."""
    if value is None:
        return None
    parts = [int(part) for part in value.split('-')]
    if len(parts) == 1:
        return date(parts[0], 1, 1), date(parts[0], 12, 31)
    if len(parts) == 2:
        return date(*parts, 1), date(*parts, calendar.monthrange(*parts)[1])
    exact = date(*parts)
    return exact, exact


def _clean_image(path):
    Image, ImageOps = _pillow()
    with Image.open(path) as image:
        if getattr(image, 'n_frames', 1) != 1:
            raise ValueError('multiframe_image_not_imported: 请提供单帧照片，不静默丢帧')
        image.load()  # Decode completely; verify header alone does not prove a readable image.
        try:
            raw_exif = image.getexif()
            exif = dict(raw_exif)
        except (OSError, ValueError, TypeError, SyntaxError) as error:
            raw_exif = None
            exif = {'_exif_read_error': type(error).__name__}
        # Some cameras put DateTimeOriginal in the Exif sub-IFD.
        if raw_exif is not None:
            try:
                exif.update(raw_exif.get_ifd(34665))
            except (KeyError, AttributeError, TypeError, ValueError, OSError):
                exif['_capture_ifd_read_error'] = True
            if 34853 in exif:
                try:
                    exif[34853] = dict(raw_exif.get_ifd(34853))
                except (KeyError, AttributeError, TypeError, ValueError, OSError):
                    exif['_gps_read_error'] = True
        transposed = ImageOps.exif_transpose(image) if raw_exif is not None else image.copy()
        alpha = transposed.mode in {'RGBA', 'LA'} or 'transparency' in transposed.info
        mode = 'RGBA' if alpha else 'RGB'
        converted = transposed.convert(mode)
        clean = Image.new(mode, converted.size)
        clean.paste(converted)
        return clean, exif


def _exif_text(value):
    if isinstance(value, bytes):
        return value.decode('ascii', errors='replace').rstrip('\x00')
    return str(value).rstrip('\x00') if value is not None else None


def _capture_metadata(exif):
    """Real EXIF values, not inferred dates. This object is PRIVATE, never rendered."""
    raw = _exif_text(exif.get(36867))
    raw_offset = _exif_text(exif.get(36881))
    offset_status = 'missing' if 36881 not in exif else 'invalid'
    offset = None
    if raw_offset and re.fullmatch(r'[+-](?:0\d|1[0-3]):[0-5]\d|[+-]14:00', raw_offset):
        offset_status, offset = 'valid', raw_offset
    result = {'status': 'missing' if 36867 not in exif else 'invalid', 'raw_value': raw,
              'local_datetime': None, 'date': None,
              'offset': {'status': offset_status, 'raw_value': raw_offset, 'value': offset},
              'created_at': None, 'source': 'EXIF.DateTimeOriginal'}
    if '_exif_read_error' in exif or (36867 not in exif and exif.get('_capture_ifd_read_error')):
        result['status'] = 'invalid'
        result['reason'] = 'exif_ifd_unreadable'
        return result
    if raw:
        try:
            observed = datetime.strptime(raw, '%Y:%m:%d %H:%M:%S')
        except ValueError:
            result['reason'] = 'invalid_DateTimeOriginal'
        else:
            result.update(status='valid', local_datetime=observed.isoformat(), date=observed.date().isoformat(),
                          created_at=observed.isoformat() + offset if offset else None)
    elif 36867 in exif:
        result['reason'] = 'empty_DateTimeOriginal'
    return result


def _gps_coordinate(values, reference, maximum):
    reference = _exif_text(reference)
    expected_refs = {'N', 'S'} if maximum == 90 else {'E', 'W'}
    if reference not in expected_refs or not isinstance(values, (tuple, list)) or len(values) != 3:
        raise ValueError('missing_or_invalid_GPS_coordinate')
    converted = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError('invalid_GPS_number')
        try:
            number = float(value)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            raise ValueError('invalid_GPS_number') from None
        if not math.isfinite(number):
            raise ValueError('nonfinite_GPS_number')
        converted.append(number)
    degree, minute, second = converted
    if not 0 <= degree <= maximum or not 0 <= minute < 60 or not 0 <= second < 60 or (degree == maximum and (minute or second)):
        raise ValueError('GPS_coordinate_out_of_range')
    result = degree + minute / 60 + second / 3600
    return -result if reference in {'S', 'W'} else result


def _gps_metadata(exif):
    result = {'status': 'missing', 'latitude': None, 'longitude': None, 'source': 'EXIF.GPSInfo', 'reason': None}
    if exif.get('_gps_read_error') or '_exif_read_error' in exif:
        return {**result, 'status': 'invalid', 'reason': 'GPS_IFD_unreadable'}
    if 34853 not in exif:
        return result
    gps = exif[34853]
    if not isinstance(gps, dict) or not gps:
        return {**result, 'status': 'invalid', 'reason': 'empty_or_invalid_GPS_IFD'}
    try:
        latitude = _gps_coordinate(gps.get(2), gps.get(1), 90)
        longitude = _gps_coordinate(gps.get(4), gps.get(3), 180)
    except ValueError as error:
        return {**result, 'status': 'invalid', 'reason': str(error)}
    return {**result, 'status': 'valid', 'latitude': latitude, 'longitude': longitude}


def _metadata_entry(rid, digest, exif, relative_file):
    return {'source_id': rid, 'source_sha256': digest, 'source_files': [relative_file],
            'exif_status': 'invalid' if '_exif_read_error' in exif else ('present' if exif else 'missing'),
            'capture_time': _capture_metadata(exif), 'gps': _gps_metadata(exif)}


def _unavailable_metadata(record):
    return {'source_id': record['id'], 'source_sha256': record['source_sha256'], 'source_files': [],
            'exif_status': 'unavailable', 'reason': 'prior_project_without_original_metadata; do_not_infer_from_sanitized_copy',
            'capture_time': {'status': 'unavailable', 'raw_value': None, 'local_datetime': None, 'date': None,
                             'offset': {'status': 'unavailable', 'raw_value': None, 'value': None}, 'created_at': None,
                             'source': 'EXIF.DateTimeOriginal'},
            'gps': {'status': 'unavailable', 'latitude': None, 'longitude': None, 'source': 'EXIF.GPSInfo', 'reason': None}}


def _difference_hash(image):
    # Candidate grouping only; a matching hash NEVER deletes a photo.
    small = image.convert('L').resize((9, 8))
    pixels = list(small.get_flattened_data() if hasattr(small, 'get_flattened_data') else small.getdata())
    result = 0
    for y in range(8):
        for x in range(8):
            result = (result << 1) | (pixels[y * 9 + x] > pixels[y * 9 + x + 1])
    return result


def _readme_index(records, output):
    rows = []
    for record in records:
        path = html.escape(record['images'][0]['thumb_path'], quote=True)
        rows.append('<article><img loading="lazy" src="' + path + '"><b>' + html.escape(record['id']) + '</b><p>' + html.escape(photo_date_label(record)) + '</p><p>' + html.escape(record.get('text', '')) + '</p></article>')
    content = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>照片读图索引（非最终回忆册）</title><style>body{font:15px system-ui;margin:24px;background:#faf8f1;color:#32302b}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:18px}article{background:white;padding:12px;border:1px solid #ddd;border-radius:12px}img{width:100%;height:190px;object-fit:contain}b{display:block;font-size:11px;overflow-wrap:anywhere}p{white-space:pre-wrap}</style><h1>照片读图索引</h1><p>仅供逐图观察。未自动识别身份、关系或编写人生故事；日期未知保持待确认。</p><main>' + ''.join(rows) + '</main></html>'
    (output / 'photo-index.html').write_text(content, encoding='utf-8')


def import_photos(source, output, manifest=None, collection_id=None, collection_name=None, synthetic_fixture=False, resume=False, requested_start=None, requested_end=None):
    """Import to a new project, or transactionally resume while preserving manual story.

    Resume keeps a recoverable sibling snapshot. Return a receipt, not a completion claim.
    """
    _pillow()
    if Path(source).is_symlink():
        raise ValueError('source不能是符号链接目录')
    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    if not source.is_dir() or Path(source).is_symlink():
        raise ValueError('source须为用户准备的本地照片目录')
    output_parent = output.parent.resolve(strict=True)
    output = output_parent / output.name
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('source与output必须分离，不能互相包含')
    if output.is_symlink():
        raise ValueError('output不能是符号链接')
    if output.exists() and not resume:
        raise FileExistsError('输出目录已存在；请选择新目录或明确--resume，不覆盖现有故事')
    items = _manifest(manifest)
    existing_meta = {}
    previous_by_hash = {}
    metadata_by_id = {}
    if output.exists():
        if not output.is_dir():
            raise ValueError('已有output不是目录')
        for child in output.rglob('*'):
            if child.is_symlink() or not child.resolve().is_relative_to(output.resolve()):
                raise ValueError('已有output存在越界链接，停止复用')
        existing_meta = json.loads((output / 'project_meta.json').read_text(encoding='utf-8'))
        if existing_meta.get('platform') != 'photos':
            raise ValueError('resume只能复用photos项目')
        previous = json.loads((output / 'records.json').read_text(encoding='utf-8'))
        seen_previous = set()
        for record in previous:
            validate_photo_record(record, existing_meta)
            if record['id'] in seen_previous:
                raise ValueError('已有项目照片ID重复，停止复用')
            seen_previous.add(record['id'])
        previous_by_hash = {record['source_sha256']: record for record in previous}
        metadata_path = output / '.private' / 'photo-metadata.json'
        if metadata_path.exists():
            prior_metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            if prior_metadata.get('schema_version') != 1 or not isinstance(prior_metadata.get('photos'), list):
                raise ValueError('已有私有照片元数据格式无效，停止覆盖')
            for entry in prior_metadata['photos']:
                if not isinstance(entry, dict) or not isinstance(entry.get('source_id'), str):
                    raise ValueError('已有私有照片元数据缺source_id')
                previous_record = previous_by_hash.get(entry.get('source_sha256'))
                if previous_record and previous_record['id'] == entry['source_id']:
                    metadata_by_id[entry['source_id']] = entry
    target = existing_meta.get('target', {})
    collection_id = collection_id or target.get('collection_id') or 'collection-' + _sha(str(source).encode())[:16]
    collection_name = collection_name or target.get('collection_name') or '照片回忆册'
    if target and target.get('collection_id') != collection_id:
        raise ValueError('resume不能更换相册collection_id')
    prior_explicit = existing_meta.get('photo_import', {}).get('requested_range_explicit', {})
    explicit_start = requested_start is not None or prior_explicit.get('start') is True
    explicit_end = requested_end is not None or prior_explicit.get('end') is True
    # Photos describe the user's chosen album/event, not a default decade.
    # Existing explicit bounds survive resume; automatic bounds are recalculated
    # from ALL retained and newly imported photos after this scan.
    requested_start = (requested_start or existing_meta.get('requested_range', {}).get('start')) if explicit_start else date.min.isoformat()
    requested_end = (requested_end or existing_meta.get('requested_range', {}).get('end')) if explicit_end else date.max.isoformat()
    if date.fromisoformat(requested_start) > date.fromisoformat(requested_end):
        raise ValueError('requested_range起点晚于终点')
    meta = {**existing_meta, 'schema_version': 1, 'platform': 'photos', 'title': collection_name, 'mode': 'selected', 'timezone': 'Asia/Shanghai',
            'requested_range': {'start': requested_start, 'end': requested_end},
            'target': {'collection_id': collection_id, 'collection_name': collection_name},
            'presentation': {**existing_meta.get('presentation', {}), 'grounding_required': True},
            'photo_import': {'version': 1, 'cloud_acquisition_verified': False, 'date_policy': 'EXIF DateTimeOriginal / user manifest / explicit filename; never mtime or upload date',
                             'requested_range_explicit': {'start': explicit_start, 'end': explicit_end},
                             'range_policy': 'automatic bounds use the actual known photo-date span, without a decade quota; explicit user bounds stay unchanged; partial record dates stay partial; unknown dates have only an unrestricted technical guard'}}
    if synthetic_fixture:
        meta['fixture'] = {'synthetic': True, 'label': '明确合成照片导入测试，不是真实回忆', 'source': 'explicit synthetic test fixture'}
    elif existing_meta.get('fixture'):
        raise ValueError('合成测试项目不可无标记改作真实素材')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.import-', dir=output_parent))
    committed = False
    try:
        if output.exists():
            shutil.copytree(output, stage, dirs_exist_ok=True)
        image_dir = stage / 'images' / 'photos'
        image_dir.mkdir(parents=True, exist_ok=True)
        files, failures = _safe_files(source)
        scan_failures = list(failures)
        supported = sorted([(rel, path) for rel, path in files if path.suffix.lower() in RASTER], key=lambda pair: (pair[0] not in items, pair[0]))
        unsupported = [rel for rel, path in files if path.suffix.lower() not in RASTER]
        missing = sorted(set(items) - {rel for rel, _ in files})
        failures.extend({'file': rel, 'reason': 'manifest_file_missing'} for rel in missing)
        records, hashes, audit, similar = [], {}, [], []
        duplicates, reused = [], 0
        for rel, path in supported:
            try:
                raw = path.read_bytes()
                digest = _sha(raw)
                item = items.get(rel, {})
                clean, exif = _clean_image(path)
                when, precision, basis, evidence, created = _date_fields(item, exif, rel)
                if digest in hashes:
                    original = hashes[digest]
                    duplicates.append({'file': rel, 'record_id': original['id'], 'sha256': digest})
                    audit.append({'file': rel, 'source_sha256': digest, 'record_id': original['id'], 'status': 'exact_duplicate'})
                    private_entry = metadata_by_id.get(original['id'])
                    if private_entry and rel not in private_entry['source_files']:
                        private_entry['source_files'].append(rel)
                    if when and original.get('date') and when != original['date']:
                        failures.append({'file': rel, 'reason': 'duplicate_date_conflict', 'record_id': original['id']})
                    elif when and not original.get('date') and not original['date_evidence'].get('user_explicit_unknown'):
                        original.update(date=when, date_precision=precision, date_basis=basis, date_evidence=evidence, created_at=created)
                    continue
                rid = 'photo-' + digest[:24]
                extension = '.png' if clean.mode == 'RGBA' else '.jpg'
                local = 'images/photos/' + rid + extension
                target_path = stage / local
                prior = previous_by_hash.get(digest)
                if prior:
                    if 'date' not in item:
                        when, precision, basis, evidence, created = (prior.get(key) for key in ('date', 'date_precision', 'date_basis', 'date_evidence', 'created_at'))
                    if 'note' not in item:
                        item = {**item, 'note': prior.get('text', '')}
                    if 'people' not in item:
                        item = {**item, 'people': prior.get('people', [])}
                if prior and (stage / prior['images'][0]['large_path']).is_file() and _sha((stage / prior['images'][0]['large_path']).read_bytes()) == prior['images'][0].get('sha256'):
                    local = prior['images'][0]['large_path']
                    target_path = stage / local
                    reused += 1
                else:
                    clean.save(target_path, format='PNG' if extension == '.png' else 'JPEG', **({'quality': 92, 'optimize': True} if extension == '.jpg' else {}))
                exported = _sha(target_path.read_bytes())
                record = {'id': rid, 'source_sha256': digest, 'date': when, 'date_precision': precision, 'date_basis': basis, 'date_evidence': evidence,
                          'created_at': created, 'selected': True, 'text': item.get('note', ''), 'people': item.get('people', []),
                          'expected_image_count': 1, 'image_count_basis': 'one fully decoded local source photo', 'image_inventory_status': 'complete',
                          'images': [{'image_id': rid, 'origin': 'synthetic_fixture' if synthetic_fixture else 'user_provided',
                                      'provided_reference': '用户准备的本地照片；来源编号 ' + rid, 'thumb_path': local, 'large_path': local,
                                      'download_status': 'saved', 'sha256': exported, 'width': clean.width, 'height': clean.height, 'exif_stripped': True}]}
                validate_photo_record(record, meta)
                records.append(record)
                hashes[digest] = record
                private_entry = _metadata_entry(rid, digest, exif, rel)
                prior_metadata = metadata_by_id.get(rid)
                if prior_metadata:
                    private_entry['source_files'] = sorted(set(prior_metadata.get('source_files', []) + [rel]))
                metadata_by_id[rid] = private_entry
                audit.append({'file': rel, 'source_sha256': digest, 'record_id': rid, 'status': 'imported', 'source_absolute_path': str(path), 'delivery_path': local})
                similar.append((rid, _difference_hash(clean), clean.width / clean.height))
            except Exception as error:
                failures.append({'file': rel, 'reason': type(error).__name__ + ': ' + str(error)})
        groups = []
        for index, (rid, dhash, ratio) in enumerate(similar):
            for other, other_hash, other_ratio in similar[:index]:
                if abs(ratio - other_ratio) <= .08 and bin(dhash ^ other_hash).count('1') <= 3:
                    groups.append({'record_ids': [other, rid], 'method': 'dhash_candidate_only', 'automatic_deletion': False})
        # Reuse all previously imported records if files are absent in a later scan. Never silently prune a user's archive.
        retained = []
        for digest, prior in previous_by_hash.items():
            if digest not in hashes:
                validate_photo_record(prior, meta)
                # Upgrade legacy private path labels without changing source/image identity.
                prior['images'][0]['provided_reference'] = '用户准备的本地照片；来源编号 ' + prior['id']
                records.append(prior)
                retained.append(prior['id'])
                metadata_by_id.setdefault(prior['id'], _unavailable_metadata(prior))
        known = [record['date'] for record in records if record['date']]
        intervals = [(record['id'], _date_interval(record['date'])) for record in records if record['date']]
        start_bound, end_bound = date.fromisoformat(requested_start), date.fromisoformat(requested_end)
        if intervals and not explicit_start:
            start_bound = min(interval[0] for _, interval in intervals)
        if intervals and not explicit_end:
            end_bound = max(interval[1] for _, interval in intervals)
        # A one-sided user bound can exclude every known photo. Keep that bound,
        # retain the records, and report the conflict rather than making a
        # reversed range or silently throwing the photos away.
        if start_bound > end_bound:
            if explicit_start and not explicit_end:
                end_bound = start_bound
            elif explicit_end and not explicit_start:
                start_bound = end_bound
        meta['requested_range'] = {'start': start_bound.isoformat(), 'end': end_bound.isoformat()}
        meta['time_scope'] = {
            'status': 'observed' if intervals else 'unknown',
            'range_mode': 'user_requested' if explicit_start or explicit_end else ('observed_span' if intervals else 'unrestricted'),
            'selection_basis': 'user_prepared_local_folder',
            'observed_range': {'start': min(known), 'end': max(known)} if known else None,
            'internal_bounds_only': not bool(intervals),
            'note': '按用户选定相册、人物/宠物或事件的实际照片跨度制作；未知日期不编年份。requested_range仅为内部校验边界，不冒充拍摄范围。'}
        out_of_range = [rid for rid, interval in intervals if interval[1] < start_bound or interval[0] > end_bound]
        failures.extend({'file': None, 'record_id': rid, 'reason': 'photo_date_outside_explicit_range: 保留照片及用户范围，请确认后再成册'} for rid in out_of_range)
        if not records:
            failures.append({'file': None, 'reason': 'no_readable_photos: 未导入任何可读照片，不能进入成册交付'})
        status = 'partial' if failures else 'selected'
        coverage = {'status': status, 'scope': 'user_prepared_local_folder_only', 'complete': False, 'requested_range': meta['requested_range'],
                    'observed_date_range': {'start': min(known) if known else None, 'end': max(known) if known else None},
                    'unknown_date_count': sum(record['date'] is None for record in records),
                    'partial_date_count': sum(record['date_precision'] in {'year', 'month'} for record in records),
                    'time_scope': meta['time_scope'],
                    'note': '只证明本次提供的本地素材导入情况，不证明网盘或历史照片齐全；按用户选择的照片自然跨度制作，日期不明或精度不足不补造月日。'}
        receipt = {'ok': not failures, 'stage': 'local_photo_import', 'cloud_acquisition_verified': False, 'finished_at': datetime.now(timezone.utc).isoformat(),
                   'total_files': len(files) + len(scan_failures),
                   'total_files_is_exact': not scan_failures,
                   'unreadable_paths': [failure['file'] for failure in scan_failures if failure.get('kind') == 'unreadable_directory'],
                   'file_count_note': '扫描失败路径各计1项下界，无法知道被拒目录内的实际文件数' if scan_failures else '本次目录扫描中实际观察到的文件数',
                   'supported_images': len(supported), 'unique_imported': len(hashes), 'exact_duplicate_count': len(duplicates),
                   'failed_count': len(failures), 'unsupported_count': len(unsupported), 'records_total': len(records), 'reused_files': reused,
                   'retained_previous_record_ids': retained, 'duplicates': duplicates, 'failures': failures, 'unsupported': unsupported,
                   'near_duplicate_candidates': groups, 'source_images_modified': False, 'manual_story_preserved': (stage / 'story.json').exists(),
                   'out_of_requested_range_ids': out_of_range, 'story_ready': False}
        _json(stage / 'project_meta.json', meta)
        _json(stage / 'coverage.json', coverage)
        _json(stage / 'records.json', records)
        _json(stage / 'photo-import-receipt.json', receipt)
        _json(stage / '.private' / 'import-audit.json', {'source_directory': str(source), 'files': audit, 'never_publish': True})
        _json(stage / '.private' / 'photo-metadata.json', {'schema_version': 1, 'never_publish': True,
              'policy': 'Private local metadata clues only. No reverse geocoding, identity guessing, or device profiling. Do not render or upload GPS/source paths. EXIF-free copies remain separate.',
              'photos': [metadata_by_id.get(record['id'], _unavailable_metadata(record)) for record in records]})
        reading_file = stage / 'photo-reading.json'
        prior_reading = json.loads(reading_file.read_text(encoding='utf-8')) if reading_file.exists() else {}
        observations = {item.get('source_id'): item for item in prior_reading.get('items', [])}
        _json(reading_file, {'status': prior_reading.get('status', 'awaiting_actual_image_review'), 'items': [{**observations.get(record['id'], {}), 'source_id': record['id'], 'image_path': record['images'][0]['large_path'], 'observation': observations.get(record['id'], {}).get('observation'), 'user_note': record['text'], 'date_label': photo_date_label(record)} for record in records]})
        # A separate scaffold, not story.json: a skeleton must not masquerade as an authored final narrative.
        if not (stage / 'story-scaffold.json').exists():
            _json(stage / 'story-scaffold.json', {'status': 'awaiting_image_review_and_user_context', 'overview': {'headline': '', 'text': '', 'opening': ''}, 'themes': [], 'wishes': [], 'source_ids': [record['id'] for record in records], 'instructions': '逐图读图后以实际观察和用户备注写作。未知人物关系、地点和事件不猜测。此文件不是完成的story.json。'})
        _readme_index(records, stage)
        backup = None
        if output.exists():
            backup = output.with_name(output.name + '.previous-' + datetime.now().strftime('%Y%m%dT%H%M%S%f'))
            output.rename(backup)
        try:
            stage.rename(output)
        except BaseException:
            if backup and not output.exists():
                backup.rename(output)
            raise
        committed = True
        return {**receipt, 'output': str(output), 'previous_snapshot': str(backup) if backup else None}
    finally:
        if not committed and stage.exists():
            # Only the freshly allocated staging directory is discarded; source/output are untouched.
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest')
    parser.add_argument('--collection-id')
    parser.add_argument('--collection-name')
    parser.add_argument('--requested-start')
    parser.add_argument('--requested-end')
    parser.add_argument('--synthetic-fixture', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = vars(parser.parse_args())
    try:
        receipt = import_photos(**args)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if receipt['ok'] else 2
    except Exception as error:
        print(json.dumps({'ok': False, 'stage': 'local_photo_import', 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
