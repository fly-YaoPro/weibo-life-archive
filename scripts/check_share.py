#!/usr/bin/env python3
"""Test actual share preview/download/copy and verify the PNG uses the cited originals."""
import argparse
import base64
import io
import json
from pathlib import Path

from archive_common import save


def identity_matches(displayed, expected):
    """Compare DOM text, preserving meaningful whitespace and all characters."""
    return displayed == expected


def check(html, output, executable=None):
    from PIL import Image, ImageChops, ImageStat
    from playwright.sync_api import sync_playwright
    html, output = Path(html).resolve(), Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    errors, checks = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(**({'executable_path':str(executable)} if executable else {}))
        for width, height in [(1440,900),(390,844)]:
            context = browser.new_context(viewport={'width':width,'height':height}, accept_downloads=True,
                                          permissions=['clipboard-read','clipboard-write'])
            context.set_offline(True); page = context.new_page(); page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(html.as_uri()); page.wait_for_function('window.JournalShare && window.JournalExperience')
            if page.locator('#welcome-silent').is_visible(): page.locator('#welcome-silent').click()
            page.evaluate("JournalUI.go({view:'review',theme_id:'overview'})")
            page.wait_for_function("document.querySelector('#spread').dataset.fit==='ready'")
            profile = page.evaluate('JOURNAL_DATA.meta.profile||null')
            # Title animation uses spans, whose standalone spaces disappear from
            # inner_text although the DOM retains the exact account name.
            if profile:
                displayed_name=page.locator('.user-profile .profile-name').text_content()
                assert identity_matches(displayed_name, profile['name'])
                for key in ['followers','following','engagement']:
                    assert page.locator(f'.user-profile [data-metric="{key}"] dd').inner_text() == profile[key]['display']
            page.screenshot(path=str(output/f'{width}x{height}-profile-cover.png'))
            page.evaluate("JournalUI.switchView('future')"); assert page.locator('.plan-card').count()>0
            page.evaluate("JournalUI.switchView('future')");page.locator('#share-button').click()
            page.get_by_label('包含微博原图',exact=True).check()
            if profile:page.get_by_label('包含头像和主页资料',exact=True).check()
            page.get_by_role('button',name='生成预览',exact=True).click()
            page.wait_for_function("document.querySelector('.share-preview-image')?.naturalWidth===1080 && !document.querySelector('.share-toolbar .primary').disabled")
            layout=page.evaluate('JournalShare.lastLayout')
            kinds=[s['kind'] for s in layout['sections']]
            assert 'review' in kinds and 'posts' in kinds and 'tomorrow' in kinds
            assert ('profile' in kinds)==bool(profile)
            assert ('scene' in kinds)==page.evaluate('!!JOURNAL_DATA.story.scene')
            sources=page.evaluate('JOURNAL_DATA.records');records={r['id']:r for r in sources}
            for image in layout['imageSources']:
                if image['kind'] in {'record','video_cover'}:
                    r=records[image['record_id']];assert image['date']==r['date']
                    media=r['images'] if image['kind']=='record' else r.get('video',{}).get('covers',[])
                    assert image['path'] in {im.get('original') or im.get('large') or im['path'] for im in media}
                    assert not image['path'].startswith('decorations/')
            preview=page.locator('.share-preview');assert preview.evaluate("e=>e.scrollHeight>e.clientHeight || [...e.querySelectorAll('img')].every(i=>i.getBoundingClientRect().bottom<=e.getBoundingClientRect().bottom+2)")
            page.screenshot(path=str(output/f'{width}x{height}-preview-top.png'))
            preview.evaluate('e=>e.scrollTop=e.scrollHeight');page.screenshot(path=str(output/f'{width}x{height}-preview-bottom.png'))
            page.get_by_role('button',name='放大预览',exact=True).click();assert preview.get_attribute('class').endswith('is-zoomed')
            page.get_by_role('button',name='适合屏幕',exact=True).click()
            images=[]
            for index,element in enumerate(page.locator('.share-preview-image').all()):
                data=element.evaluate("async e=>{const blob=await(await fetch(e.src)).blob();return await new Promise(resolve=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.readAsDataURL(blob)});}")
                raw=base64.b64decode(data);path=output/f'{width}x{height}-poster-{index+1}.png';path.write_bytes(raw)
                images.append(Image.open(io.BytesIO(raw)).convert('RGB'));assert images[-1].width==1080
            assert len(images)==len(layout['parts'])
            # Pixel evidence, not just a role label: each drawn photo matches its source image.
            differences=[]
            for image in [s for s in layout['imageSources'] if s['kind'] in {'record','video_cover'}]:
                b=image['draw_bounds'];part=next(i for i,s in enumerate(layout['parts']) if s['top']<=b['y']<s['top']+s['height'])
                encoded=page.evaluate('path=>JOURNAL_ASSETS[path]',image['path']).split(',')[1]
                expected=Image.open(io.BytesIO(base64.b64decode(encoded))).convert('RGB').resize((round(b['width']),round(b['height'])),Image.Resampling.BILINEAR)
                actual=images[part].crop((round(b['x']),round(b['y']-layout['parts'][part]['top']),round(b['x'])+expected.width,round(b['y']-layout['parts'][part]['top'])+expected.height))
                margin=5;box=(margin,margin,expected.width-margin,expected.height-margin)
                difference=sum(ImageStat.Stat(ImageChops.difference(actual.crop(box),expected.crop(box))).mean)/3
                assert difference<12, f'PNG照片与原图不一致: {image["record_id"]} {difference}'
                differences.append(round(difference,3))
            with page.expect_download() as event:page.get_by_role('button',name='下载 PNG',exact=True).click()
            downloaded=output/f'{width}x{height}-download.png';event.value.save_as(downloaded)
            assert downloaded.read_bytes()==(output/f'{width}x{height}-poster-1.png').read_bytes(), '下载与预览不是同一PNG'
            page.get_by_role('button',name='复制图片',exact=True).click()
            page.wait_for_function("!document.querySelector('.share-toolbar button.quiet').disabled")
            copy_status=page.locator('.share-status').inner_text();native_copy='图片已复制' in copy_status
            assert native_copy or '没有复制成功' in copy_status or '无法复制' in copy_status
            # Verify failure handling independently without granting/altering the user's browser.
            page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async()=>{throw new DOMException('denied','NotAllowedError')}}})")
            page.get_by_role('button',name='复制图片',exact=True).click();page.wait_for_function("document.querySelector('.share-status').textContent.includes('没有复制成功')")
            assert page.get_by_role('button',name='下载 PNG',exact=True).is_enabled() and page.locator('.share-preview-image').count()
            checks.append({'viewport':[width,height],'profile_matches':bool(profile),'plans_seeded':True,'sections':kinds,
                           'original_photo_pixel_differences':differences,'preview_scroll':True,'preview_download_identical':True,
                           'source_video_covers':sum(s['kind']=='video_cover' for s in layout['imageSources']),
                           'native_clipboard_write':native_copy,'clipboard_refusal_retains_download':True,'parts':len(images)})
            context.close()
        browser.close()
    assert not errors,errors
    report={'ok':True,'checks':checks,'errors':errors,'visual_review':'Inspect the actual exported PNGs; generated image semantics remain separate.'}
    save(output/'share-report.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('html',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--browser-executable',type=Path);args=parser.parse_args()
    try:
        report=check(args.html,args.output,args.browser_executable);print(json.dumps(report,ensure_ascii=False))
    except (ValueError,OSError,AssertionError) as error:parser.exit(1,'分享检查未通过: '+str(error)+'\n')
