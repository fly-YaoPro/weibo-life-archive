#!/usr/bin/env python3
"""CLI compile/build/budget/pack/publish/finalize; scene click QA is agent-led."""
import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
from archive_common import load, save
from prepare_music import prepare as prepare_music
from build_journal import build
from pack_html import pack
from check_project import check
from story_preflight import check_story_project


def run(source, output_root, skins=None, publish_max_mb=None, book_max_mb=24):
    source, output_root = Path(source).resolve(), Path(output_root).resolve()
    if source == output_root or source.is_relative_to(output_root) or output_root.is_relative_to(source):
        raise ValueError('Source and output root must be separate sibling trees')
    meta = load(source/'project_meta.json')
    skins = skins or [meta.get('skin', 'paper')]
    if not skins or len(skins) != len(set(skins)) or any(s not in ('paper','frosted') for s in skins):
        raise ValueError('Choose paper/frosted; request both only when explicitly needed')
    if publish_max_mb is not None and publish_max_mb <= 0: raise ValueError('Publish budget must be positive')
    stages = []
    def timed(name, fn):
        start = time.perf_counter();value=fn()
        stages.append({'stage':name,'seconds':round(time.perf_counter()-start,4)})
        return value
    presentation = meta.get('presentation', {})
    if not isinstance(presentation, dict): raise ValueError('presentation must be an object')
    enabled = presentation.get('bgm_enabled', True)
    if type(enabled) is not bool: raise ValueError('presentation.bgm_enabled must be true/false')
    story = load(source/'story.json')
    from story_tools import compile_project
    try:
        compiled = timed('compile_story', lambda:compile_project(source))
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        return {'ok':False,'status':'preflight_failed','errors':[str(exc)],'stages':stages,'artifacts':[]}
    from story_shape import shape_errors
    schema = timed('story_schema', lambda:shape_errors(compiled))
    if schema:
        return {'ok':False,'status':'preflight_failed','errors':schema,'stages':stages,'artifacts':[]}
    if compiled != story: save(source/'story.json', compiled)
    story = compiled
    if not enabled and story.get('bgm'):
        raise ValueError('bgm_enabled=false conflicts with story.bgm; explicitly remove bgm for a music-free delivery')
    music = timed('prepare_music', lambda:prepare_music(source)) if enabled else {'status':'disabled_by_user'}
    preflight = timed('story_preflight', lambda:check_story_project(source))
    if not preflight['ok']:
        return {'ok':False,'status':'preflight_failed','errors':preflight['errors'],'stages':stages,'artifacts':[]}
    folder = output_root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    artifacts = []
    report = {'ok':False,'status':'building','source':str(source),'run_dir':str(folder),'stages':stages,'artifacts':artifacts,
        'music':music,'build_ok':False,'delivery_complete':False,'live_deployment_verified':False,'browser_interactions_verified':False,'browser_qa_required':False,
        'scene_click_check':{'status':'pending_agent_check' if story.get('scene') else 'not_applicable','reference':'references/scene-hotspots.md','scope':'desktop_mobile_scene_only'},
        'download_compression':load(source/'compression-report.json'),
        'delivery':{'status':'pending','deployment_required':presentation.get('local_only') is not True,
                    'receipt_command':'finalize_delivery.py --run-dir ' + str(folder)}}
    def save_report():
        (folder/'run-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        for skin in skins:
            built, html = folder/('built-'+skin), folder/('journal-'+skin+'.html')
            timed('build_'+skin,lambda:build(source,built,skin))
            from media_budget import apply_budget
            budget=timed('media_budget_'+skin,lambda:apply_budget(built,book_max_mb))
            packed = timed('pack_'+skin,lambda:pack(built,html))
            validation = timed('packed_contract_'+skin,lambda:check(html,'weibo','final'))
            if not validation['ok']: raise ValueError('; '.join(validation['errors']))
            artifacts.append({'skin':skin,'html':packed['html'],'bytes':packed['bytes'],
                'sha256':hashlib.sha256(html.read_bytes()).hexdigest(),
                'built_dir':str(built),'publish_budget_ok':None if publish_max_mb is None else packed['bytes'] <= publish_max_mb * 1024 * 1024,
                'contract_verified':True,'browser_qa_required':False,'media_budget':budget})
            save_report()
        report['ok'] = True
        report['build_ok'] = True
        report['status'] = 'local_ready' if all(a['publish_budget_ok'] is not False for a in artifacts) else 'directory_publish_or_html_fallback_required'
        template = {'artifacts':[{'html':a['html'], 'sha256':a['sha256'],
                    'deployment':{'status':'pending','release_status':'','evidence':'','reason':'','url':''}}
                    for a in artifacts]}
        save(folder/'delivery-receipt-template.json', template)
        report['delivery']['receipt_template'] = str(folder/'delivery-receipt-template.json')
        report['next_action'] = 'Static build only. Normal CLI continues publication automatically. For an interrupted run use journal_run.py --resume-run RUN_DIR. Before handoff, perform the agent-led desktop/mobile scene click check in references/scene-hotspots.md; this CLI does not claim interaction verification.'
    except (OSError,ValueError,KeyError,TypeError) as exc:
        report['status']='local_failed';report['errors']=[str(exc)]
    save_report()
    return report


def deliver(source=None, output_root=None, skins=None, publish_max_mb=None, book_max_mb=24,
            resume_run=None, publisher=None):
    from finalize_delivery import finalize
    from publish_journal import publish
    report=load(Path(resume_run)/'run-report.json') if resume_run else run(source,output_root,skins,publish_max_mb,book_max_mb)
    if not report.get('build_ok', report.get('ok')): return report
    run_dir=Path(report['run_dir']);source=Path(report['source'])
    local_only=load(source/'project_meta.json').get('presentation',{}).get('local_only') is True
    rows=[]
    for artifact in report['artifacts']:
        deployment={'status':'local_only'} if local_only else (publisher or publish)(source,run_dir,artifact)
        rows.append({'html':artifact['html'],'sha256':artifact['sha256'],'deployment':deployment})
    if any(row['deployment']['status']=='pending' for row in rows):
        report['ok']=False;report['delivery_complete']=False;report['status']='deployment_pending'
        report['delivery'].update(status='pending',releases=[r['deployment'] for r in rows])
        save(run_dir/'run-report.json',report)
        return report
    finalize(run_dir,{'artifacts':rows})
    return load(run_dir/'run-report.json')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output-root',type=Path)
    parser.add_argument('--resume-run',type=Path,help='Resume publication of this existing build without rebuilding')
    parser.add_argument('--build-only',action='store_true',help='Explicit local static diagnostics only; not delivery completion')
    parser.add_argument('--book-max-mb',type=float,default=24,help='Whole-book media target in MiB, default 24; at most two compression passes')
    parser.add_argument('--skins',nargs='+',choices=('paper','frosted'))
    parser.add_argument('--publish-max-mb',type=float,help='Only a host-verified single-HTML limit; omit if unknown')
    args=parser.parse_args()
    if not args.resume_run and (not args.source or not args.output_root):parser.error('--source and --output-root are required unless --resume-run is used')
    if args.build_only and args.resume_run:parser.error('--build-only cannot be combined with --resume-run')
    result=run(args.source,args.output_root,args.skins,args.publish_max_mb,args.book_max_mb) if args.build_only else deliver(args.source,args.output_root,args.skins,args.publish_max_mb,args.book_max_mb,args.resume_run)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ok'] else 1


if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as exc: raise SystemExit(str(exc))
