#!/usr/bin/env python3
"""Read-only, offline checks for archive projects. Python 3 standard library only."""
import argparse
import json
import re
import struct
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from audit_images import audit as audit_images

TITLES={'weibo':'人生手账','taobao':'消费手账'}
STATUSES={'complete','partial','selected','unread','failed','empty'}
FORBIDDEN_KEYS={'cookie','cookies','access_token','refresh_token','password','authorization','storage_state'}

def check(root,kind,stage='data'):
    root=Path(root).resolve(); errors=[]; warnings=[]
    def err(msg):errors.append(msg)
    def load(name):
        path=root/name
        try:return json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError) as e:err(f'{name}: cannot read valid JSON ({type(e).__name__})');return None
    def text(value,field):
        if not isinstance(value,str) or not value.strip():err(f'{field}: expected nonempty string');return False
        return True
    def local(value,field,required=False):
        if value is None:
            if required:err(f'{field}: missing local path')
            return
        if not isinstance(value,str) or not value or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',value) or value.startswith(('/', '\\')):
            err(f'{field}: expected project-relative file path');return
        path=(root/value.replace('\\','/')).resolve()
        if not path.is_relative_to(root):err(f'{field}: path leaves project');return
        if not path.is_file():err(f'{field}: local file is missing')
    def url(value,field):
        if not isinstance(value,str):err(f'{field}: expected URL');return
        parts=urlsplit(value)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:err(f'{field}: unsafe or invalid source URL')
    def private_keys(value,where):
        if isinstance(value,dict):
            for key,v in value.items():
                if str(key).lower() in FORBIDDEN_KEYS:err(f'{where}: credential-like key present')
                private_keys(v,where)
        elif isinstance(value,list):
            for v in value:private_keys(v,where)
    def evidence_image(value,field):
        origin=value.get('origin')
        if origin is None:
            warnings.append(field+': image provenance missing; verify real source manually')
        elif origin=='platform':
            url(value.get('source_url'),field+'.source_url')
        elif origin=='user_provided':
            text(value.get('provided_reference'),field+'.provided_reference')
        else:
            err(field+': evidence image must be platform or authorized real user-provided media, not synthetic/stock')
    meta=load('project_meta.json');coverage=load('coverage.json')
    records=load('records.json' if kind=='weibo' else 'orders.json')
    for name,value in [('project_meta',meta),('coverage',coverage),('data',records)]:private_keys(value,name)
    if not isinstance(meta,dict):err('project_meta.json: expected object');meta={}
    if meta.get('platform')!=kind:err('project_meta.platform: does not match requested kind')
    text(meta.get('title'),'project_meta.title')
    if meta.get('mode') not in ('full','selected'):err('project_meta.mode: expected full or selected')
    if meta.get('timezone')!='Asia/Shanghai':err('project_meta.timezone: expected Asia/Shanghai')
    bounds=meta.get('requested_range',{})
    try:
        begin=date.fromisoformat(bounds['start']);end=date.fromisoformat(bounds['end'])
        if begin>end:err('requested_range: reversed dates')
    except (ValueError,KeyError,TypeError):err('requested_range: invalid date bounds');begin=end=None
    target=meta.get('target',{})
    if kind=='weibo':
        text(target.get('uid'),'target.uid');url(target.get('profile_url'),'target.profile_url')
    if not isinstance(coverage,list):err('coverage.json: expected array');coverage=[]
    years=set()
    for i,c in enumerate(coverage):
        field=f'coverage[{i}]'
        if not isinstance(c,dict):err(field+': expected object');continue
        if not isinstance(c.get('year'),int) or isinstance(c.get('year'),bool):err(field+': year must be integer')
        elif c['year'] in years:err(field+': duplicate year')
        else:years.add(c['year'])
        if c.get('status') not in STATUSES:err(field+': unknown coverage status')
        for key in ('scanned_count','saved_count','selected_count'):
            v=c.get(key)
            if v is not None and (not isinstance(v,int) or isinstance(v,bool) or v<0):err(field+'.'+key+': count must be nonnegative integer or null')
        if c.get('status')=='empty' and c.get('saved_count')!=0:err(field+': empty must have confirmed zero saved_count')
    if not coverage:warnings.append('No per-year coverage has been recorded')
    if not isinstance(records,list):err('data JSON: expected array');records=[]
    seen=set();image_count=0;unknown_amounts=0
    def timestamp(value,field):
        try:
            dt=datetime.fromisoformat(value.replace('Z','+00:00'))
            if dt.tzinfo is None:err(field+': timezone is missing');return
            day=dt.astimezone(timezone(timedelta(hours=8))).date()
            if begin and not begin<=day<=end:err(field+': outside requested date window')
        except (AttributeError,ValueError,TypeError):err(field+': invalid ISO timestamp')
    def amount(value,field):
        if value is None:return
        if not isinstance(value,str):err(field+': use decimal string or null, not float');return
        try:
            d=Decimal(value)
            if not d.is_finite() or d<0:err(field+': invalid monetary amount')
        except InvalidOperation:err(field+': invalid decimal amount')
    for i,r in enumerate(records):
        field=f'data[{i}]'
        if not isinstance(r,dict):err(field+': expected object');continue
        key='id' if kind=='weibo' else 'order_id';rid=r.get(key)
        if text(rid,field+'.'+key):
            if rid in seen:err(field+': duplicate source ID')
            seen.add(rid)
        timestamp(r.get('created_at' if kind=='weibo' else 'placed_at'),field+'.date')
        url(r.get('url'),field+'.url')
        if kind=='weibo':
            text(r.get('text'),field+'.text')
            if r.get('author_uid')!=target.get('uid'):err(field+': author UID differs from target')
            if not isinstance(r.get('selected'),bool):err(field+': selected must be boolean')
            images=r.get('images')
            if not isinstance(images,list):err(field+'.images: expected array');continue
            for j,img in enumerate(images):
                if not isinstance(img,dict):err(field+'.images: expected objects');continue
                evidence_image(img,field+f'.images[{j}]')
                if img.get('download_status') not in ('saved','partial','failed','unavailable'):err(field+'.images: unknown image status')
                for k in ('thumb_path','large_path'):
                    local(img.get(k),field+f'.images[{j}].'+k,required=img.get('download_status')=='saved')
                image_count+=1
        else:
            if r.get('is_success') is not True:err(field+': non-success order in included data')
            if any(s in str(r.get('raw_status','')) for s in ('交易关闭','已取消','待付款','未付款')):err(field+': raw status contradicts included success')
            text(r.get('raw_status'),field+'.raw_status');text(r.get('currency'),field+'.currency')
            amount(r.get('paid_amount'),field+'.paid_amount');amount(r.get('refund_amount'),field+'.refund_amount')
            if r.get('paid_amount') is None:unknown_amounts+=1
            if r.get('amount_basis') not in ('original_paid','net_after_refund','unknown'):err(field+': unknown amount_basis')
            items=r.get('items')
            if not isinstance(items,list) or not items:err(field+'.items: expected nonempty array');continue
            item_ids=set()
            for j,item in enumerate(items):
                if not isinstance(item,dict):err(field+'.items: expected objects');continue
                if item.get('image_path') is not None or item.get('origin') is not None:
                    evidence_image(item,field+f'.items[{j}]')
                iid=item.get('item_id')
                if text(iid,field+f'.items[{j}].item_id'):
                    if iid in item_ids:err(field+': repeated item_id within order')
                    item_ids.add(iid)
                text(item.get('name'),field+f'.items[{j}].name')
                qty=item.get('quantity')
                if not isinstance(qty,int) or isinstance(qty,bool) or qty<1:err(field+'.items: quantity must be positive integer')
                if item.get('image_status') not in ('saved','failed','unavailable'):err(field+'.items: unknown image status')
                local(item.get('image_path'),field+f'.items[{j}].image_path',required=item.get('image_status')=='saved')
                image_count+=1
    if meta.get('mode')=='full':warnings.append('Full is the requested mode; completion still requires coverage/source verification')
    if unknown_amounts:warnings.append(f'{unknown_amounts} orders have unknown paid amount; do not treat as zero')
    image_audit=None
    if kind=='weibo':
        image_audit=audit_images(root,meta,records)
        errors.extend('image audit: '+message for message in image_audit['errors'])
        warnings.extend('image audit: '+message for message in image_audit['warnings'])
    if stage=='final':
        story=load('story.json');private_keys(story,'story')
        if not isinstance(story,dict):err('story.json: expected object');story={}
        overview=story.get('overview',{})
        if not isinstance(overview,dict):overview={};err('story.overview: expected object')
        if len(str(overview.get('text','')))>200:err('story.overview: exceeds 200 characters')
        themes=story.get('themes',[])
        if not isinstance(themes,list):themes=[];err('story.themes: expected array')
        sources=[overview]+themes
        if kind=='weibo' and isinstance(story.get('song'),dict):sources.append(story['song'])
        for i,s in enumerate(sources):
            if not isinstance(s,dict):err('story entry: expected object');continue
            refs=s.get('source_ids',[])
            if not isinstance(refs,list) or any(not isinstance(x,str) or x not in seen for x in refs):err(f'story entry {i}: source IDs absent from data')
            for j,img in enumerate(s.get('image_paths',[])):local(img,f'story entry {i} image {j}',required=True)
        datajs='data.js' if kind=='weibo' else 'orders.js'
        for name in ('index.html','styles.css','app.js',datajs):local(name,name,required=True)
        html=(root/'index.html').read_text('utf-8') if (root/'index.html').is_file() else ''
        for tag,attr in (('script','src'),('link','href'),('img','src')):
            for match in re.finditer(r'<'+tag+r'\b[^>]*\b'+attr+r'\s*=\s*[\"\']([^\"\']+)',html,re.I):
                value=match.group(1)
                if value.startswith('data:') and tag=='img':continue
                if value.startswith('#'):continue
                local(value.split('#')[0].split('?')[0],f'index.html {tag} {attr}',required=True)
        for css in root.glob('*.css'):
            if re.search(r'url\(\s*[\"\']?(?:https?:)?//',css.read_text('utf-8'),re.I):err('CSS references external resource; offline asset needed')
        pngs=list((root/'exports').glob('*.png')) if (root/'exports').is_dir() else []
        dimensions=[]
        for p in pngs:
            header=p.read_bytes()[:24]
            if header[:8]==b'\x89PNG\r\n\x1a\n' and len(header)==24:dimensions.append(struct.unpack('>II',header[16:24]))
        if (1080,1440) not in dimensions:err('exports: no 1080x1440 PNG found; actually export and inspect share image')
        warnings.append('Static checks do not prove JS data parity, rendering, interactions, backup merge or file:// behavior')
    for p in root.rglob('*'):
        if p.name.lower() in ('.env','.wbprofile','storage-state.json','cookies.json','login-state.json'):
            err('Credential/profile-like file or directory present in deliverable');break
    return {'ok':not errors,'kind':kind,'stage':stage,'records':len(records),'unique_source_ids':len(seen),'images':image_count,'image_audit':image_audit,'errors':errors,'warnings':warnings}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project',type=Path);p.add_argument('--kind',choices=tuple(TITLES),required=True);p.add_argument('--stage',choices=('data','final'),default='data')
    a=p.parse_args();result=check(a.project,a.kind,a.stage)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
