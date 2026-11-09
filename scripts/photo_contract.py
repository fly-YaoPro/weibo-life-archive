"""Local-photo contract. Unknown dates stay unknown; no platform identity is invented."""
import re
import hashlib
import io
from datetime import date, datetime
from pathlib import PurePosixPath, PureWindowsPath

RASTER = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff'}
PRECISIONS = {'day': 10, 'month': 7, 'year': 4}
BASES = {'exif', 'user_manifest', 'filename', 'unknown'}


def validate_photo_bytes(image, raw, *, full_size=True):
    """Check delivered bytes, not only an asserted saved/hash/EXIF flag."""
    try:
        from PIL import Image
    except ImportError:
        raise ValueError('照片验收需要Pillow；未验真实图片，不声明通过') from None
    if full_size and hashlib.sha256(raw).hexdigest() != image.get('sha256'):
        raise ValueError('photo.images: 图片真实SHA256与清单不符')
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            if getattr(decoded, 'n_frames', 1) != 1:
                raise ValueError('交付照片不能是未处理的多帧图片')
            decoded.load()
            if decoded.getexif() or decoded.info.get('exif'):
                raise ValueError('交付照片仍带EXIF，需重新生成去元数据副本')
            if full_size:
                for key, actual in (('width',decoded.width),('height',decoded.height)):
                    if image.get(key) is not None and image[key] != actual:
                        raise ValueError('图片实际尺寸与清单不符')
    except (OSError, SyntaxError, ValueError) as error:
        raise ValueError('photo.images: 图片不可安全解码或元数据无效: '+str(error)) from error


def photo_date(record):
    """Return validated YYYY-MM-DD / YYYY-MM / YYYY, or None, never pad a date."""
    value = record.get('date')
    precision = record.get('date_precision')
    if value is None:
        if precision != 'unknown':
            raise ValueError('photo.date_precision: 未知日期必须为unknown')
        return None
    if not isinstance(value, str) or precision not in PRECISIONS or len(value) != PRECISIONS[precision]:
        raise ValueError('photo.date/date_precision: 日期与精度不符')
    if not re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', value):
        raise ValueError('photo.date: 只允许YYYY、YYYY-MM或YYYY-MM-DD')
    parts = [int(part) for part in value.split('-')]
    try:
        date(*parts, *([1] * (3 - len(parts))))
    except (ValueError, TypeError):
        raise ValueError('photo.date: 日期无效') from None
    return value


def photo_date_label(record):
    value = photo_date(record)
    if value is None:
        return '日期待确认'
    parts = value.split('-')
    return parts[0] + '年' + (str(int(parts[1])) + '月' if len(parts) > 1 else '') + (str(int(parts[2])) + '日' if len(parts) > 2 else '')


def filename_date(filename):
    """Interpret only a date-shaped filename prefix, not arbitrary IDs or OS times."""
    stem = PurePosixPath(str(filename).replace('\\', '/')).stem
    match = re.match(r'^(?:IMG[_-]|DSC[_-])?(\d{4})-(\d{2})(?:-(\d{2}))?(?:$|[_ .-])', stem, re.I)
    if match:
        value = '-'.join(part for part in match.groups() if part)
    else:
        match = re.match(r'^(?:IMG[_-]|DSC[_-])(\d{4})(\d{2})(\d{2})(?:$|[_ .-])', stem, re.I)
        value = '-'.join(match.groups()) if match else None
    if value:
        try:
            photo_date({'date': value, 'date_precision': 'day' if len(value) == 10 else 'month'})
            return value
        except ValueError:
            pass
    return None


def _safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('photo.images: 图片必须是项目内相对路径')
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or '..' in path.parts or ':' in value or path.suffix.lower() not in RASTER:
        raise ValueError('photo.images: 图片路径越界或不是栅格图片')
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('photo.created_at: 真实时间戳必须带时区')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('photo.created_at: 时间戳无效') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('photo.created_at: 不得给无时区拍摄时间补造时区')
    return parsed


def validate_photo_record(record, meta, resource=None):
    """Validate a single source/packed photo record, optionally resolving its assets."""
    if meta.get('platform') != 'photos' or not isinstance(meta.get('target'), dict):
        raise ValueError('photo.meta: platform须为photos且target为相册对象')
    for key in ('collection_id', 'collection_name'):
        if not isinstance(meta['target'].get(key), str) or not meta['target'][key].strip():
            raise ValueError('photo.target: 缺' + key)
    if any(meta['target'].get(key) for key in ('uid', 'profile_url')) or record.get('author_uid') or record.get('url'):
        raise ValueError('photo.identity: 本地照片不冒充微博账号或原帖')
    digest = record.get('source_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest) or record.get('id') != 'photo-' + digest[:24]:
        raise ValueError('photo.id: ID必须来自完整源文件SHA256的稳定前24位')
    if record.get('selected') is not True:
        raise ValueError('photo.selected: 导入照片必须明确入选')
    value = photo_date(record)
    basis = record.get('date_basis')
    evidence = record.get('date_evidence')
    if basis not in BASES or not isinstance(evidence, dict) or evidence.get('kind') != basis:
        raise ValueError('photo.date_evidence: 日期依据与证据不符')
    if value is None:
        if basis != 'unknown':
            raise ValueError('photo.date_basis: 未知日期不能声称已有拍摄日期依据')
    else:
        if basis == 'unknown' or not isinstance(evidence.get('value'), str) or not evidence['value'].strip():
            raise ValueError('photo.date_evidence: 已知日期缺原始证据')
        if basis == 'user_manifest' and evidence.get('value') != value:
            raise ValueError('photo.date_evidence: 用户日期与清单不一致')
        if basis == 'exif':
            if record['date_precision'] != 'day' or evidence.get('tag') != 'DateTimeOriginal':
                raise ValueError('photo.date_evidence: EXIF只接受DateTimeOriginal拍摄日期')
            try:
                observed = datetime.strptime(evidence['value'], '%Y:%m:%d %H:%M:%S')
            except ValueError:
                raise ValueError('photo.date_evidence: EXIF日期无效') from None
            if observed.date().isoformat() != value:
                raise ValueError('photo.date_evidence: EXIF与展示日期不符')
        if basis == 'filename':
            if not isinstance(evidence.get('filename'), str) or not evidence['filename'] or value != evidence.get('parsed_date') or value != filename_date(evidence['filename']):
                raise ValueError('photo.date_evidence: 文件名日期缺原始文件名/解析证据')
    created = record.get('created_at')
    if created is not None:
        observed = _timestamp(created)
        if record['date_precision'] != 'day' or observed.date().isoformat() != value:
            raise ValueError('photo.created_at: 时间与日期精度/日期不符')
        if basis == 'user_manifest':
            if evidence.get('created_at') != created:
                raise ValueError('photo.created_at: 清单缺原始带时区时间')
        elif basis == 'exif':
            offset = evidence.get('offset')
            expected = datetime.strptime(evidence['value'], '%Y:%m:%d %H:%M:%S').isoformat() + str(offset or '')
            if not re.fullmatch(r'[+-]\d{2}:\d{2}', str(offset)) or expected != created:
                raise ValueError('photo.created_at: EXIF未给出相应真实时区')
        else:
            raise ValueError('photo.created_at: 文件名/未知来源不伪造精确时间')
    if not isinstance(record.get('text', ''), str) or record.get('expected_image_count') != 1 or record.get('image_inventory_status') != 'complete':
        raise ValueError('photo.inventory: 每条照片应有明确的单张完整盘点')
    images = record.get('images')
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError('photo.images: 每条仅对应一张源照片')
    image = images[0]
    synthetic = meta.get('fixture', {}).get('synthetic') is True
    origin = image.get('origin')
    if origin != 'user_provided' and not (origin == 'synthetic_fixture' and synthetic):
        raise ValueError('photo.images.origin: 只接受用户照片或明确合成测试图')
    if not isinstance(image.get('provided_reference'), str) or not image['provided_reference'].strip() or image.get('source_url'):
        raise ValueError('photo.images: 缺本地素材来源或伪造平台来源')
    if image.get('download_status') != 'saved' or image.get('image_id') != record['id']:
        raise ValueError('photo.images: 单图ID或保存状态不符')
    paths = {image.get('thumb_path'), image.get('large_path')}
    for path in paths:
        _safe_path(path)
        if resource:
            resource(path, RASTER)
    if image.get('exif_stripped') is not True:
        raise ValueError('photo.images: 交付图片须明确移除EXIF')
    if not isinstance(image.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', image['sha256']):
        raise ValueError('photo.images: 缺交付图片SHA256')
    return record
