"""Shared source/build/packed contracts, with local or embedded asset resolution."""
import base64
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from archive_common import date_key, project_file
from audit_images import audit as audit_images
from experience import RASTER, AUDIO, validate_experience, validate_narrative, synthetic_fixture, record_image_paths


def asset_checker(root=None, assets=None):
    """Check embedded resources without writing media or claiming visual proof."""
    checked = {}
    def resource(name, suffixes=None):
        if assets is None:
            return project_file(root, name, suffixes)
        path = project_file(Path('/__embedded_journal__'), name, suffixes, exists=False)
        if name not in checked:
            value = assets.get(name)
            if not isinstance(value, str) or not re.fullmatch(r'data:[^;,]+;base64,[A-Za-z0-9+/=\r\n]+', value):
                raise ValueError('内嵌资源缺失或不是base64数据: ' + str(name))
            header, encoded = value.split(',', 1)
            if path.suffix.lower() in RASTER and not header.startswith('data:image/'):
                raise ValueError('内嵌图片MIME类型不符: ' + name)
            raw = base64.b64decode(encoded, validate=True)
            if not raw:
                raise ValueError('内嵌资源为空: ' + name)
            if path.suffix.lower() in AUDIO:
                from prepare_music import validate_audio
                validate_audio(raw)
            checked[name] = path
        return checked[name]
    return resource


def validate_media(image, meta, resource=None, require_status=False):
    """Photos and posters share provenance, state and cache path checks."""
    require_status = require_status or meta.get('presentation',{}).get('grounding_required',False)
    if not isinstance(image, dict):
        raise ValueError('media: 图片需为对象')
    origin = image.get('origin')
    if origin == 'platform':
        image_url = urlsplit(image.get('source_url', ''))
        if image_url.scheme not in {'http', 'https'} or not image_url.hostname or image_url.username or image_url.password:
            raise ValueError('media: 平台图片缺真实来源URL')
    elif origin == 'user_provided' or (origin == 'synthetic_fixture' and synthetic_fixture(meta)):
        if not isinstance(image.get('provided_reference'), str) or not image['provided_reference'].strip():
            raise ValueError('media: 用户/测试图片缺来源说明')
    elif origin is not None or require_status:
        raise ValueError('media: 图片来源类型不能缺失或是生成/库存图')
    status = image.get('download_status')
    if (status is not None or require_status) and status not in {'saved','partial','failed','unavailable'}:
        raise ValueError('media: 图片下载状态无效')
    thumb = image.get('thumb_path') or image.get('path')
    large = image.get('large_path') or image.get('large')
    if status == 'saved' and (not thumb or not large):
        raise ValueError('media: saved图片缺缩略图或大图路径')
    if resource:
        for key in ('thumb_path', 'large_path', 'original_path', 'path', 'large', 'original'):
            if image.get(key):
                resource(image[key], RASTER)


def validate_video(record, meta, resource=None):
    """One video/poster contract for raw observations and normalized records."""
    if not record.get('is_video') and record.get('video') is None:
        return
    video = record.get('video')
    if record.get('is_video') is not True or not isinstance(video, dict):
        raise ValueError('video: 需要is_video:true及视频元数据对象')
    source = video.get('source_url')
    if not isinstance(source, str) or not source.strip() or source != record.get('url'):
        raise ValueError('video.source_url: 视频需绑定同一原帖URL')
    parts = urlsplit(source)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('video.source_url: 原帖URL不安全或无效')
    covers = video.get('covers')
    observations = video.get('observed_covers', covers)
    if not isinstance(covers, list) or not isinstance(observations, list) or video.get('cover_status') not in {'observed', 'unavailable'} or bool(observations) != (video['cover_status'] == 'observed'):
        raise ValueError('video.cover_status: 状态与covers数组不一致')
    for cover in observations + covers:
        validate_media(cover, meta, resource, require_status=True)
    if 'observed_covers' in video and any(cover.get('source_url') not in {c.get('source_url') for c in observations} for cover in covers):
        raise ValueError('video.covers: 显示封面不属于实际观察索引')


def validate_runtime(meta, records, story=None, root=None, assets=None):
    """Run the same essential contracts for source data, builders and one HTML."""
    if not isinstance(meta, dict) or not isinstance(records, list):
        raise ValueError('runtime: metadata需为对象，records需为数组')
    if meta.get('platform') not in {'weibo', 'taobao', 'photos'}:
        raise ValueError('runtime: 此来源暂不支持')
    if meta.get('platform') == 'photos':
        target = meta.get('target', {})
        if not isinstance(target.get('collection_id'), str) or not target['collection_id'].strip():
            raise ValueError('photos: 缺相册collection_id，不使用微博UID冒充照片来源')
    presentation = meta.get('presentation', {})
    if not isinstance(presentation, dict):
        raise ValueError('presentation需为对象')
    paths = set()
    resolve = asset_checker(root, assets)
    def resource(name, suffixes=None):
        value=resolve(name,suffixes)
        paths.add(name)
        return value
    profile_path = None
    if meta.get('platform') == 'weibo':
        from user_profile import validate_profile
        profile_path = validate_profile(root, meta, presentation.get('profile_required', False), resource_check=resource)
    normalized = []
    seen = set()
    bounds=meta.get('requested_range',{})
    start,end=date.fromisoformat(bounds['start']),date.fromisoformat(bounds['end'])
    if start>end:raise ValueError('requested_range: 开始晚于结束')
    strict_identity=meta.get('platform')=='weibo' and (presentation.get('profile_required') or presentation.get('grounding_required')) and not synthetic_fixture(meta)
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('records需为对象数组')
        rid = record.get('id', record.get('order_id'))
        if not isinstance(rid, str) or not rid.strip() or rid in seen:
            raise ValueError('records: 来源ID需非空唯一字符串')
        seen.add(rid)
        if strict_identity and not rid.isdigit():
            raise ValueError('records: 真实平台ID需数字字符串，不用摘要哈希')
        if meta.get('platform')=='weibo':
            uid=meta.get('target',{}).get('uid')
            if (record.get('author_uid') is not None or strict_identity) and record.get('author_uid')!=uid:
                raise ValueError('record.author_uid: 原帖作者与目标UID不符或缺失')
            if strict_identity:
                from weibo_web import permalink_mid
                if permalink_mid(record.get('url',''),uid)!=rid:
                    raise ValueError('record.url: 原帖永久链接与真实mid不符')
        if meta.get('platform') == 'photos':
            from photo_contract import photo_date, validate_photo_record, validate_photo_bytes
            validate_photo_record(record, meta, resource)
            image = record['images'][0]
            for image_path in {image['thumb_path'],image['large_path']}:
                if assets is not None:
                    raw = base64.b64decode(assets[image_path].split(',',1)[1],validate=True)
                else:
                    raw = resource(image_path, RASTER).read_bytes()
                validate_photo_bytes(image, raw, full_size=image_path==image['large_path'])
            when = photo_date(record)
            if when:
                from calendar import monthrange
                if len(when) == 4:
                    first, last = date(int(when), 1, 1), date(int(when), 12, 31)
                elif len(when) == 7:
                    year, month = map(int, when.split('-'))
                    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
                else:
                    first = last = date.fromisoformat(when)
                if first > end or last < start:
                    raise ValueError('record.date: 照片日期超出请求范围')
        else:
            when = record.get('date') or date_key(record.get('created_at', record.get('placed_at')))
            if not start<=date.fromisoformat(when)<=end:
                raise ValueError('record.date: 日期超出请求范围')
            original_time=record.get('created_at',record.get('placed_at'))
            if original_time and date_key(original_time)!=when:
                raise ValueError('record.date: 展示日期与原始时间不符')
        text = record.get('text', '\n'.join(i.get('name', '') for i in record.get('items', [])))
        if not isinstance(text, str):
            raise ValueError('record.text需为文字')
        normalized.append({**record, 'id': rid, 'date': when, 'text': text})
        validate_video(record, meta, resource)
        if not isinstance(record.get('images',[]),list):
            raise ValueError('record.images需为数组')
        for image in record.get('images', []):
            validate_media(image,meta,resource)
        shot = record.get('screenshot')
        if shot:
            if shot.get('origin') != 'browser_capture' or shot.get('source_url') != record.get('url'):
                raise ValueError('screenshot: 截图需对应同一原帖')
            resource(shot['path'], RASTER)
    if meta.get('platform') == 'weibo':
        image_audit = audit_images(root, meta, records, assets=assets)
        if not image_audit['ok']:
            raise ValueError('image inventory: ' + '; '.join(image_audit['errors']))
    result = {'profile_checked': meta.get('platform') == 'weibo', 'videos_checked': sum(bool(r.get('is_video')) for r in records)}
    if story is not None:
        from story_shape import shape_errors
        issues = shape_errors(story)
        if issues: raise ValueError('story schema:\n' + '\n'.join(issues))
        if presentation.get('bgm_enabled') is True and not story.get('bgm'):
            raise ValueError('story.bgm: 默认配乐缺失；运行 journal_run 或 prepare_music')
        if presentation.get('bgm_enabled') is False and story.get('bgm'):
            raise ValueError('story.bgm: 与 presentation.bgm_enabled=false 冲突')
        pending_text = [r['id'] for r in normalized if r.get('text_status') == 'pending']
        if pending_text: raise ValueError('records.text_status: full text pending for ' + ', '.join(pending_text) + '; 补全文，不按字数猜测完整')
        grounding = presentation.get('grounding_required', False)
        result['narrative'] = validate_narrative(story, normalized, grounding)
        overview = story.get('overview', {})
        if presentation.get('cover_required') and (not isinstance(overview.get('opening'), str) or not overview['opening'].strip() or not overview.get('portrait')):
            raise ValueError('cover_required: 缺开场白或有据画像')
        if presentation.get('cover_required'):
            for section,field in ((overview,'headline'),(overview,'text'),(overview,'opening'),(overview['portrait'],'text')):
                value=section.get(field)
                if not isinstance(value,str) or not value.strip():
                    raise ValueError('cover_required: 封面文字缺失')
        if presentation.get('experience_required'):
            scene = story.get('scene')
            letter = story.get('letter')
            if not scene or not letter:
                raise ValueError('experience_required: 缺首屏场景或结尾来信')
            if not scene.get('image_path'):
                raise ValueError('experience_required: 缺首屏场景生成插画')
            if not letter.get('image_path'):
                raise ValueError('experience_required: 缺结尾来信生成插画')
            if not scene['image_path'].startswith('decorations/'):
                raise ValueError('experience_required: 首屏插画需放在 decorations/ 目录')
            if not letter['image_path'].startswith('decorations/'):
                raise ValueError('experience_required: 结尾插画需放在 decorations/ 目录')
            if not 1 <= len(scene.get('hotspots', [])) <= 10:
                raise ValueError('experience_required: 场景需1—10个有据热点')
        # BGM 是可选增强项，不强制要求
        if presentation.get('three_wishes_required') and not story.get('wishes'):
            raise ValueError('three_wishes_required: 需非空有据小事，数量按内容确定')
        if presentation.get('share_letter_required') and not story.get('share', {}).get('letter_text', '').strip():
            raise ValueError('share_letter_required: 缺分享来信')
        if presentation.get('share_entries_required') and not story.get('share', {}).get('entries'):
            raise ValueError('share_entries_required: 缺真实来源分享节点')
        paths.update(validate_experience(root, story, normalized, grounding, resource_check=resource, embedded_assets=assets))
        by_id={r['id']:r for r in normalized}
        for section in [overview]+story.get('themes',[]):
            for path in section.get('image_paths',[]):
                resource(path,RASTER)
            for image in section.get('images',[]):
                if not isinstance(image,dict) or image.get('record_id') not in section['source_ids']:
                    raise ValueError('story.images: 展示图record_id不属于章节来源')
                for key in ('path','large','original'):
                    if image.get(key):
                        resource(image[key],RASTER)
        result['experience_checked'] = True
    result['paths'] = paths
    return result
