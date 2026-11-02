#!/usr/bin/env python3
"""Create and verify a reproducible Skill upload zip. Never packages user projects or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from preflight import inspect_bundle

FORBIDDEN={'.env','cookies.json','storage-state.json','login-state.json','auth.json'}
def inventory(root):
    root=Path(root).resolve();files=[]
    for name in ['SKILL.md','README.md','skill_manifest.json']:
        if (root/name).is_symlink():raise ValueError('发布入口不能是符号链接')
        if (root/name).is_file():files.append(root/name)
    for directory in ['agents','references','scripts','assets']:
        for path in (root/directory).rglob('*'):
            if '__pycache__' in path.parts or path.suffix in {'.pyc','.pyo'}:continue
            if path.is_symlink():raise ValueError('发布资源不能包含符号链接')
            if path.is_file():
                if path.name.lower() in FORBIDDEN or any(part in {'.git','node_modules','.wbprofile'} for part in path.parts):raise ValueError('发布资源中发现非Skill文件')
                files.append(path)
    return sorted(files,key=lambda p:p.relative_to(root).as_posix())

def package(root,output,report):
    root,output=Path(root).resolve(),Path(output).resolve()
    if output.exists():raise ValueError('发布包已存在，请使用新文件名')
    if output.is_relative_to(root):raise ValueError('发布包存放在Skill目录之外')
    check=inspect_bundle(root)
    if not check['ok']:raise ValueError('安装预检未通过: '+str(check['missing']))
    files=inventory(root);entries={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    manifest=json.loads((root/'skill_manifest.json').read_text(encoding='utf-8-sig'))
    if not set(manifest['required_files']).issubset(entries):raise ValueError('发布清单缺必需资源')
    for p in files:
        if p.suffix=='.md':
            for target in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8-sig')):
                if ':' not in target and not target.startswith('#') and not (p.parent/target.split('#')[0]).exists():raise ValueError('Markdown资源链接缺失: '+str(p))
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for p in files:
            name=root.name+'/'+p.relative_to(root).as_posix();info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;archive.writestr(info,p.read_bytes())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():raise ValueError('压缩包校验失败')
        actual={name.removeprefix(root.name+'/'):hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    if actual!=entries:raise ValueError('压缩包与源Skill逐文件不一致')
    result={'ok':True,'skill':root.name,'version':manifest['version'],'zip':str(output),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'file_count':len(files),'counts':{group:sum(n.startswith(group+'/') for n in entries) for group in ['references','scripts','assets']},'files':entries}
    Path(report).parent.mkdir(parents=True,exist_ok=True);Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    try:
        r=package(a.root,a.output,a.report);print(json.dumps({k:v for k,v in r.items() if k!='files'},ensure_ascii=False))
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
