"""Publish a built journal with lark-cli; checkpoint create/upload/release and resume.

Current CLI: app storage + HTML git repository + release. Older +deploy CLI is
used only when that command is actually advertised. No browser or access changes.
"""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit
from archive_common import load, project_file, save


class PublishError(RuntimeError): pass


def native_cli():
    path = shutil.which('lark-cli.exe') or shutil.which('lark-cli')
    if not path: raise PublishError('lark-cli is unavailable')
    p=Path(path)
    if os.name == 'nt' and p.suffix.lower() in {'.cmd','.ps1','.bat'}:
        binary=p.parent/'node_modules/@larksuite/cli/bin/lark-cli.exe'
        if not binary.is_file(): raise PublishError('Native lark-cli executable is unavailable')
        return str(binary)
    return str(p)


def execute(argv, cwd):
    result=subprocess.run(argv,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
    if result.returncode:
        raise PublishError((result.stderr or result.stdout or 'command failed')[-4000:])
    return result.stdout


def payload(value):
    value=value.get('data',value)
    return value if isinstance(value,dict) else {}


def https(value):
    p=urlsplit(value) if isinstance(value,str) else None
    return bool(p and p.scheme=='https' and p.netloc)


def file_url(value):
    if isinstance(value,dict):
        for key in ('url','download_url','file_url','public_url'):
            if https(value.get(key)): return value[key]
        for key in ('data','file','file_info'):
            found=file_url(value.get(key))
            if found: return found
    return None


def publish(source, run_dir, artifact, runner=execute, sleep=time.sleep, clock=time.monotonic,
            cli=None, wait_seconds=300):
    source,run_dir=Path(source).resolve(),Path(run_dir).resolve()
    built=Path(artifact['built_dir']).resolve()
    state_path=source/'deployment-state.json'
    state=load(state_path,{})
    row=state.setdefault(artifact['skin'],{'uploads':{}})
    log=run_dir/('publish-'+artifact['skin']+'.json')
    events=[]
    def record():
        save(state_path,state);save(log,events)
    def command(args,cwd=built,raw=False):
        output=runner(args,str(cwd))
        if raw: return output
        try: value=json.loads(output)
        except (ValueError,TypeError):
            value=None
            if isinstance(output,str):
                for m in re.finditer(r'(?m)^\{',output):
                    try:
                        decoded,_=json.JSONDecoder().raw_decode(output[m.start():])
                        if isinstance(decoded,dict): value=decoded
                    except ValueError: pass
            if value is None: raise PublishError('CLI did not return a JSON result')
        if not isinstance(value,dict) or value.get('ok') is False:
            raise PublishError(json.dumps(value,ensure_ascii=False)[-4000:])
        events.append({'command':args[1:3], 'result':value})
        record()
        return payload(value)
    try:
        cli=cli or native_cli()
        def apps(op,*args,cwd=built):
            return command([cli,'apps',op,'--as','user','--format','json',*args],cwd)
        if not row.get('app_id'):
            created=apps('+create','--name',load(source/'project_meta.json').get('title','微博人生手账')+' '+artifact['skin'],'--app-type','html')
            app=created.get('app',created)
            row['app_id']=app.get('app_id')
            if not isinstance(row['app_id'],str) or not row['app_id'].startswith('app_'):
                raise PublishError('create did not return an app_id')
            record()
        app_id=row['app_id']
        # A matching release resumes polling without uploading or creating again.
        if row.get('artifact_sha256') != artifact['sha256']:
            row.pop('release_id',None);row.pop('url',None)
        if not row.get('release_id'):
            help_text=runner([cli,'apps','--help'],str(built))
            if re.search(r'(?m)^\s*\+deploy\s',help_text):
                released=apps('+deploy','--app-id',app_id,'--dir',built.name,cwd=built.parent)
            else:
                repo=Path(row.get('repo',run_dir/('publish-repo-'+artifact['skin'])))
                if not (repo/'.git').is_dir():
                    apps('+init','--app-id',app_id,'--dir',repo.name,cwd=repo.parent)
                    row['repo']=str(repo);record()
                runtime=json.loads((built/'journal-data.js').read_text(encoding='utf-8').split(' = ',1)[1].rstrip(';\n'))
                paths=set(runtime.get('extra_paths',[]))
                for item in runtime['records']:
                    for im in item['images']+item.get('video',{}).get('covers',[]):
                        paths.update(im[k] for k in ('path','large','original') if im.get(k))
                paths.add('favicon.svg')
                urls={}
                upload_dir=run_dir/'upload-files';upload_dir.mkdir(exist_ok=True)
                for name in sorted(paths):
                    p=project_file(built,name);raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
                    ext=p.suffix
                    if ext.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}:
                        from manage_media import image_info
                        fmt,_,_=image_info(raw);ext='.'+fmt
                    key=digest+ext
                    if key not in row['uploads']:
                        local=upload_dir/key;local.write_bytes(raw)
                        uploaded=apps('+file-upload','--app-id',app_id,'--file',local.name,cwd=upload_dir)
                        url=file_url(uploaded)
                        if not url and isinstance(uploaded.get('path'),str):
                            url=file_url(apps('+file-get','--app-id',app_id,'--path',uploaded['path']))
                        if not url: raise PublishError('file-upload/get returned no usable HTTPS resource URL')
                        row['uploads'][key]=url;record()
                    urls[name]=row['uploads'][key]
                managed=[]
                for p in built.iterdir():
                    if p.is_file() and p.suffix in {'.html','.css','.js'}:
                        shutil.copyfile(p,repo/p.name);managed.append(p.name)
                index=(repo/'index.html').read_text(encoding='utf-8')
                index=index.replace('href="favicon.svg"','href="'+html.escape(urls['favicon.svg'],quote=True)+'"')
                index=index.replace('<script src="journal-data.js">','<script src="journal-assets.js"></script><script src="journal-data.js">')
                (repo/'index.html').write_text(index,encoding='utf-8')
                (repo/'journal-assets.js').write_text('window.JOURNAL_ASSETS='+json.dumps(urls,ensure_ascii=False).replace('<','\\u003c')+';\n',encoding='utf-8')
                managed.append('journal-assets.js')
                def git(*args): return command(['git',*args],repo,raw=True)
                git('add','--',*managed)
                if git('diff','--cached','--name-only').strip():
                    git('commit','-m','Publish generated journal '+artifact['sha256'][:12])
                try: git('push','origin','sprint/default')
                except PublishError:
                    apps('+git-credential-init','--app-id',app_id)
                    git('push','origin','sprint/default')
                released=apps('+release-create','--app-id',app_id,'--branch','sprint/default')
            row['release_id']=released.get('release_id') or released.get('release',{}).get('release_id')
            if not row['release_id']: raise PublishError('publish did not return release_id')
            row['artifact_sha256']=artifact['sha256'];record()
        deadline=clock()+wait_seconds
        while True:
            result=apps('+release-get','--app-id',app_id,'--release-id',row['release_id'])
            result=result.get('release',result)
            status=result.get('status')
            if status=='finished':
                if not https(result.get('online_url')): raise PublishError('release finished without a final HTTPS URL')
                row['url']=result['online_url'];record()
                return {'status':'deployed','release_status':'finished','url':row['url'],
                        'app_id':app_id,'release_id':row['release_id'],'evidence':str(log),
                        'visibility':'provider default; no access permissions changed'}
            if status=='failed': raise PublishError(json.dumps(result.get('error_logs') or {'status':status},ensure_ascii=False))
            if status!='publishing' or result.get('current_node_info',{}).get('current_status')=='PENDING' or clock()>=deadline:
                return {'status':'pending','release_status':status,'app_id':app_id,'release_id':row['release_id'],
                        'reason':'Waiting for release or provider approval; resume the same release.', 'evidence':str(log)}
            sleep(min(20,max(0,deadline-clock())))
    except (PublishError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        events.append({'error':str(exc)});record()
        return {'status':'unavailable' if not row.get('app_id') else 'failed','reason':str(exc),'evidence':str(log)}
