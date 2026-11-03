#!/usr/bin/env python3
"""Apply agent-reviewed image regions to story.json. Never guesses image semantics.

Regions JSON: {"hotspot-id":{"x":50,"y":60,"bounds":{"x":40,"y":45,"width":20,"height":30}}}.
Coordinates are percentages of the actual full image, not CSS pixels or prompt positions.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from archive_common import project_file, save
from scene_geometry import validate_scene_geometry


def calibrate(source, regions):
    root = Path(source).resolve()
    path = root / 'story.json'
    story = json.loads(path.read_text(encoding='utf-8'))
    updated = copy.deepcopy(story)
    scene = updated['scene']
    ids = [h['id'] for h in scene['hotspots']]
    if len(ids) != len(set(ids)) or set(ids) != set(regions):
        raise ValueError('标定表必须恰好覆盖首图全部唯一热点ID')
    for h in scene['hotspots']:
        region = regions[h['id']]
        for key in ('x', 'y', 'bounds'):
            h[key] = region[key]
    image = project_file(root, scene['image_path'], {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'})
    scene['calibration'] = {'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                            'coordinate_space': 'full-image-percent', 'method': 'agent-reviewed-object-bounds'}
    result = validate_scene_geometry(root, scene)
    # All validation precedes writes; original is backed up once for this image revision.
    backup = path.with_name('story.before-hotspots-' + result['image_sha256'][:12] + '.json')
    if not backup.exists():
        save(backup, story)
    save(path, updated)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--regions', type=Path, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(calibrate(a.source, json.loads(a.regions.read_text(encoding='utf-8'))), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as e:
        p.exit(1, str(e) + '\n')
