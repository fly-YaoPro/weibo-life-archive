#!/usr/bin/env python3
"""Select a curated licensed instrumental, cache/validate audio, or synthesize an offline fallback."""
import argparse
import array
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request
from urllib.parse import urlsplit
import wave
from archive_common import load, save, project_file

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def validate_audio(data):
    if len(data) < 1024 or len(data) > 24 * 1024 * 1024:
        raise ValueError('音频大小不正确')
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        with wave.open(io.BytesIO(data)) as w:
            if w.getnframes() < w.getframerate() or w.getnchannels() not in (1, 2):
                raise ValueError('WAV无有效音频帧')
            w.readframes(w.getnframes())
        return 'wav'
    if data[:3] == b'ID3' or (data[0] == 255 and data[1] & 0xe0 == 0xe0):
        # Structural signature only; browser loadedmetadata/playback still required.
        return 'mp3'
    raise ValueError('返回的是错误页或未支持的音频格式')


class MusicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https' or urlsplit(newurl).hostname != 'incompetech.com':
            raise ValueError('配乐下载重定向离开已核验作者站')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def synthesize(path, mood='gentle'):
    """Original 32-second looping pentatonic bell/pad, standard library only."""
    rate, seconds = 22050, 32
    samples = array.array('h')
    progression = [(48, 55, 60), (45, 52, 57), (41, 48, 53), (43, 50, 55)]
    melody = [72, 76, 79, 76, 74, 72, 69, 67, 72, 74, 76, 79, 76, 74, 72, 67]
    freq = lambda note: 440 * 2 ** ((note - 69) / 12)
    for i in range(rate * seconds):
        t = i / rate
        chord = progression[int(t // 8) % 4]
        pad = sum(math.sin(2 * math.pi * freq(n) * t) for n in chord) * .055
        age = t % 2
        note = melody[int(t // 2)] + (0 if mood == 'bright' else -12)
        f = freq(note)
        bell = (math.sin(2 * math.pi * f * age) + .25 * math.sin(2 * math.pi * f * 2 * age)) * math.exp(-age * 2) * min(1, age * 30) * .16
        fade = min(1, t / 1.2, (seconds - t) / 1.5)
        samples.append(int(max(-1, min(1, (pad + bell) * fade)) * 32767))
    if sys.byteorder != 'little': samples.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, rate, 0, 'NONE', 'not compressed')); w.writeframes(samples.tobytes())


def prepare(root, mood='gentle', offline=False, opener=None, source='original', replace=False):
    root = Path(root)
    story = load(root / 'story.json')
    if source not in {'original','licensed'}: raise ValueError('配乐来源只能为 original/licensed')
    if story.get('bgm') and not replace:
        data = project_file(root, story['bgm']['path']).read_bytes(); validate_audio(data)
        if story['bgm'].get('sha256') and hashlib.sha256(data).hexdigest() != story['bgm']['sha256']:
            raise ValueError('已有音乐哈希不符，先核验，不覆盖')
        return {'status': 'preserved', 'bgm': story['bgm']}
    tracks = load(ASSETS / 'music-catalog.json')['tracks']
    ranked = sorted(tracks, key=lambda t: (mood not in t['moods'], t['id']))
    audio = root / 'audio'; audio.mkdir(exist_ok=True)
    chosen, reason = None, 'original_selected' if source=='original' else 'offline_requested' if offline else ''
    if not offline and source == 'licensed':
        opener = opener or urllib.request.build_opener(MusicRedirect())
        for track in ranked:
            try:
                req = urllib.request.Request(track['url'], headers={'User-Agent': 'WeiboJournal/3.0'})
                with opener.open(req, timeout=12) as response:
                    final = urlsplit(response.geturl())
                    if final.scheme != 'https' or final.hostname != 'incompetech.com': raise ValueError('下载源不符')
                    chunks, size, deadline = [], 0, time.monotonic() + 12
                    while True:
                        if time.monotonic() > deadline: raise TimeoutError('配乐读取超过时间预算')
                        chunk = response.read1(65536) if hasattr(response, 'read1') else response.read(65536)
                        if not chunk: break
                        chunks.append(chunk); size += len(chunk)
                        if size > 24 * 1024 * 1024: raise ValueError('音频超过预算')
                    data = b''.join(chunks)
                ext = validate_audio(data)
                path = audio / (track['id'] + '.' + ext)
                part = path.with_suffix('.part'); part.write_bytes(data); os.replace(part, path)
                chosen = {'path': path.relative_to(root).as_posix(), 'title': track['title'], 'artist': track['artist'],
                          'origin': 'licensed', 'reference': track['reference'], 'license_url': track['license_url'],
                          'attribution': f"{track['title']} — {track['artist']} (incompetech.com), {track['license']}",
                          'match_reason': track['description'], 'mood': mood}
                break
            except (OSError, ValueError) as e:
                reason = type(e).__name__
    if not chosen:
        path = audio / 'warm-lights.wav'
        preset = ASSETS / 'audio' / 'warm-lights.wav'
        if preset.is_file():
            shutil.copyfile(preset, path)
        else:
            synthesize(path, mood)
        chosen = {'path': 'audio/warm-lights.wav', 'title': '窗边的灯', 'origin': 'generated',
                  'reference': 'assets/audio/warm-lights.wav preset (pentatonic bell/pad v1)', 'mood': mood,
                  'match_reason': '温和五声音阶与轻钟声，供安静翻阅', 'fallback_reason': reason}
    if source=='original':chosen['selection_reason']=chosen.pop('fallback_reason')
    data = (root / chosen['path']).read_bytes(); validate_audio(data)
    chosen.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    story['bgm'] = chosen; save(root / 'story.json', story)
    return {'status': 'ready', 'bgm': chosen}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('project', type=Path)
    p.add_argument('--mood', choices=['gentle', 'reflective', 'bright'], default='gentle')
    p.add_argument('--offline', action='store_true');p.add_argument('--source',choices=['original','licensed'],default='original');p.add_argument('--replace',action='store_true',help='Explicitly replace existing music; source files are retained');a=p.parse_args()
    try: print(json.dumps(prepare(a.project, a.mood, a.offline, source=a.source, replace=a.replace), ensure_ascii=False))
    except (ValueError, OSError, KeyError) as e: p.exit(1, str(e)+'\n')
