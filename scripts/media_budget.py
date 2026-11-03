"""Bounded compression of built delivery copies; source files are never changed."""
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from archive_common import load, project_file, save
from manage_media import compress_image, image_info


def apply_budget(built, max_mb=24):
    built = Path(built).resolve()
    if type(max_mb) not in (int, float) or not math.isfinite(max_mb) or max_mb <= 0:
        raise ValueError('book media budget must be positive finite MiB')
    runtime = built/'journal-data.js'
    data = json.loads(runtime.read_text(encoding='utf-8').split(' = ', 1)[1].rstrip(';\n'))
    from scene_geometry import validate_scene_geometry
    if data.get('story',{}).get('scene'):
        validate_scene_geometry(built, data['story']['scene'])
    names = set(data.get('extra_paths', []))
    for row in data['records']:
        for im in row['images'] + row.get('video', {}).get('covers', []):
            names.update(im[k] for k in ('path', 'large', 'original') if im.get(k))
    files = {n:project_file(built, n) for n in names}
    raw = {n:p.read_bytes() for n,p in files.items()}
    before = sum(map(len, raw.values()))
    limit = int(max_mb*1024*1024)
    chosen, passes = {}, []
    fixed=sum(len(b) for n,b in raw.items() if not n.startswith(('images/','decorations/')))
    previous=before
    for attempt in range(2):
        if before <= limit: break
        edge=1024 if attempt==0 else max(640,min(960,int(1024*math.sqrt(max(0,limit-fixed)/max(1,previous-fixed))*0.94)//64*64))
        quality=65 if attempt==0 else 60
        def compress(item):
            name,content=item
            if name.startswith(('images/', 'decorations/')) and Path(name).suffix.lower() in {'.jpg','.jpeg','.png','.webp'}:
                out, fmt, w, h = compress_image(content, quality=quality, max_dimension=edge, output_format='jpeg')
                if fmt and len(out) < len(content): return name,(out,fmt)
            return name,None
        with ThreadPoolExecutor(max_workers=3) as pool:
            trial={name:value for name,value in pool.map(compress,raw.items()) if value is not None}
        after = sum(len(trial[n][0]) if n in trial else len(b) for n,b in raw.items())
        passes.append({'max_dimension':edge,'quality':quality,'bytes':after})
        previous=after
        chosen = trial
        if after <= limit: break
    mapping = {}
    compression_fingerprints = {}
    for name, (content, fmt) in chosen.items():
        rel = str(Path(name).parent.as_posix()) + '/' + hashlib.sha256(content).hexdigest() + '.' + fmt
        (built/rel).write_bytes(content)
        mapping[name] = rel
        compression_fingerprints[hashlib.sha256(raw[name]).hexdigest()] = hashlib.sha256(content).hexdigest()
    def rewrite(value):
        if isinstance(value, str): return mapping.get(value, value)
        if isinstance(value, list): return [rewrite(v) for v in value]
        if isinstance(value, dict):
            # Only this controlled, whole-frame compression preserves geometry.
            # Arbitrary image replacement is rejected before this step.
            if value.get('image_sha256') in compression_fingerprints:
                value = {**value, 'source_image_sha256':value['image_sha256'],
                         'image_sha256':compression_fingerprints[value['image_sha256']]}
            return {mapping.get(k,k): v if k in {'text','quote','evidence','observation','rationale','reason','title'} else rewrite(v)
                    for k,v in value.items()}
        return value
    if mapping:
        for name in ('records.json','story.json','project_meta.json'):
            save(built/name, rewrite(load(built/name)))
        for name in ('journal-data.js','data.js'):
            path=built/name
            if not path.is_file(): continue
            prefix, encoded=path.read_text(encoding='utf-8').split(' = ',1)
            value=rewrite(json.loads(encoded.rstrip(';\n')))
            path.write_text(prefix+' = '+json.dumps(value,ensure_ascii=False).replace('<','\\u003c')+';\n',encoding='utf-8')
        for old in mapping:
            if old not in mapping.values(): files[old].unlink()
    after = sum((built/n).stat().st_size for n in {mapping.get(n,n) for n in names})
    return {'target_bytes':limit,'before_bytes':before,'after_bytes':after,
            'saved_bytes':before-after,'saved_ratio':round((before-after)/before,4) if before else 0,
            'target_met':after<=limit,'files_changed':len(mapping),'passes':passes,
            'scope':'built delivery copies, including audio and decorations in budget',
            'warning':None if after<=limit else 'Target not met after two passes; all sources retained, prefer directory hosting.'}
