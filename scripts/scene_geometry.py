"""Image-bound hotspot calibration. No browser, network or account access."""
import hashlib
import base64
import math
from archive_common import project_file


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_bounds(hotspot):
    b = hotspot.get('bounds')
    if not isinstance(b, dict) or any(not finite_number(b.get(k)) for k in ('x', 'y', 'width', 'height')):
        raise ValueError('热点bounds需为有限数值{x,y,width,height}，单位为原图百分比')
    x, y, w, h = (b[k] for k in ('x', 'y', 'width', 'height'))
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 100 or y+h > 100:
        raise ValueError('热点bounds超出原图或面积为零')
    if any(not finite_number(hotspot.get(k)) for k in ('x', 'y')) or not (x <= hotspot['x'] <= x+w and y <= hotspot['y'] <= y+h):
        raise ValueError('热点光标锚点必须落在自身物件bounds内')
    return b


def validate_scene_geometry(root, scene, embedded_assets=None):
    hotspots = scene.get('hotspots', [])
    calibrated = [h for h in hotspots if 'bounds' in h]
    if not calibrated:
        if scene.get('calibration'):
            raise ValueError('标定信息存在但缺少物件bounds')
        return {'calibrated': False, 'legacy_points': len(hotspots)}
    if len(calibrated) != len(hotspots):
        raise ValueError('同一首图不能混用物件区域与未标定点；请全部看图标定')
    if embedded_assets is None:
        image = project_file(root, scene['image_path'], {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'})
        raw = image.read_bytes()
    else:
        value = embedded_assets.get(scene['image_path'])
        if not isinstance(value, str) or ';base64,' not in value:
            raise ValueError('首图内嵌资源缺失，不能校验标定指纹')
        raw = base64.b64decode(value.split(',',1)[1], validate=True)
    stamp = scene.get('calibration', {})
    digest = hashlib.sha256(raw).hexdigest()
    if not isinstance(stamp, dict) or stamp.get('image_sha256') != digest:
        raise ValueError('首图已改变或缺少标定指纹：须重新看图定位物件，不能沿用旧坐标')
    for i, h in enumerate(calibrated):
        a = validate_bounds(h)
        for other in calibrated[:i]:
            b = other['bounds']
            if min(a['x']+a['width'], b['x']+b['width']) > max(a['x'], b['x']) and min(a['y']+a['height'], b['y']+b['height']) > max(a['y'], b['y']):
                raise ValueError('物件点击区域重叠，需缩到各自可见轮廓内：' + str(other.get('id')) + '/' + str(h.get('id')))
    return {'calibrated': True, 'regions': len(calibrated), 'image_sha256': digest}
