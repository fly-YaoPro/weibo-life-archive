#!/usr/bin/env python3
"""Pack a built journal into one offline HTML; media is embedded once and resolved at runtime."""
import argparse
import base64
import json
import mimetypes
from pathlib import Path
import re
from archive_common import project_file


def pack(root, output, max_mb=160):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError('目标HTML已存在，使用新文件名，保留旧版本')
    if max_mb <= 0: raise ValueError('文件预算必须为正数')
    text = (root / 'journal-data.js').read_text(encoding='utf-8')
    data = json.loads(text.split(' = ', 1)[1].rstrip(';\n'))
    assets = {}
    paths = set(data.get('extra_paths', []))
    for r in data['records']:
        for im in r['images']: paths.update([im['path'], im['large']])
    for name in sorted(paths):
        p = project_file(root, name)
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        assets[name] = 'data:' + mime + ';base64,' + base64.b64encode(p.read_bytes()).decode('ascii')
    html = (root / 'index.html').read_text(encoding='utf-8')
    def stylesheet(m):
        return '<style>\n' + project_file(root, m[1]).read_text(encoding='utf-8') + '\n</style>'
    html = re.sub(r'<link rel="stylesheet" href="([^"]+)">', stylesheet, html)
    favicon = base64.b64encode((root / 'favicon.svg').read_bytes()).decode()
    html = html.replace('href="favicon.svg"', 'href="data:image/svg+xml;base64,' + favicon + '"')
    embedded = 'window.JOURNAL_ASSETS=' + json.dumps(assets, ensure_ascii=False).replace('<', '\\u003c') + ';\n'
    html = html.replace('<script src="journal-data.js"></script>', '<script>\n' + embedded + text + '\n</script>')
    def script(m):
        if m[1]=='journal-assets.js':return ''  # Media has already been embedded once above.
        code = project_file(root, m[1]).read_text(encoding='utf-8')
        if re.search(r'</script', code, re.I): raise ValueError('脚本包含需转义的关闭标签')
        return '<script>\n' + code + '\n</script>'
    html = re.sub(r'<script src="([^"]+)"></script>', script, html)
    if len(html.encode()) > max_mb * 1024 * 1024:
        raise ValueError('单文件超过预算；压缩真实图片/音频后重新构建，不静默丢图')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')
    return {'html': str(output), 'bytes': output.stat().st_size, 'embedded_assets': len(assets)}


def verify_packed(path):
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self): super().__init__(); self.external=[]
        def handle_starttag(self, tag, attrs):
            a=dict(attrs)
            value=a.get('src') if tag in ('script','img','audio') else a.get('href') if tag=='link' else None
            if value and not value.startswith('data:'): self.external.append(value)
    html=Path(path).read_text(encoding='utf-8');p=Links();p.feed(html);errors=[]
    if p.external: errors.append('HTML仍有外部资源: '+str(p.external))
    try:
        a=re.search(r'window.JOURNAL_ASSETS=(.*?);\n',html).group(1)
        d=re.search(r'window.JOURNAL_DATA = (.*?);\n',html).group(1)
        assets,data=json.loads(a),json.loads(d)
        paths=set(data.get('extra_paths',[]))
        for row in data['records']:
            for im in row['images']:paths.update([im['path'],im['large']])
        if not paths.issubset(assets): errors.append('内嵌资源缺失')
        if data['meta']['platform']!='weibo': errors.append('平台不是微博')
        if data['story'].get('bgm'):
            from prepare_music import validate_audio
            validate_audio(base64.b64decode(assets[data['story']['bgm']['path']].split(',',1)[1],validate=True))
        return {'ok':not errors,'kind':'weibo','stage':'single_html','records':len(data['records']),
                'embedded_assets':len(assets),'errors':errors,
                'warnings':['静态检查不证明视觉、交互或采集全量；单文件仍需禁网浏览器验收']}
    except (ValueError,KeyError,AttributeError) as e:
        return {'ok':False,'errors':['内嵌数据不完整: '+str(e)]}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('project', type=Path)
    p.add_argument('--output', type=Path, required=True);p.add_argument('--max-mb', type=float, default=160);a=p.parse_args()
    try: print(json.dumps(pack(a.project,a.output,a.max_mb),ensure_ascii=False))
    except (ValueError,OSError,KeyError) as e:p.exit(1,str(e)+'\n')
