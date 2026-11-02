#!/usr/bin/env python3
"""Open a standalone HTML in an isolated offline browser; save actual review and flip frames.

This produces inspection evidence, not an automatic beauty score. Pillow makes optional comparison boards.
"""
import argparse
import json
from pathlib import Path
from archive_common import save


def capture(html, output, executable=None):
    from playwright.sync_api import sync_playwright
    html, output = Path(html).resolve(), Path(output).resolve()
    if not html.is_file() or html.suffix.lower() != '.html': raise ValueError('需要真实已构建HTML文件')
    output.mkdir(parents=True, exist_ok=True)
    shots, errors, style = [], [], None
    with sync_playwright() as p:
        browser=p.chromium.launch(**({'executable_path':str(executable)} if executable else {}))
        for width,height in [(1440,900),(390,844)]:
            context=browser.new_context(viewport={'width':width,'height':height});context.set_offline(True);page=context.new_page()
            page.on('pageerror',lambda e:errors.append(str(e)));page.goto(html.as_uri());page.wait_for_function('window.JournalUI && window.JournalMotion')
            style=page.evaluate('window.JOURNAL_DATA.skin')
            if page.evaluate('!!window.JOURNAL_DATA.story.scene'):
                page.locator('#welcome-silent').wait_for(state='visible');page.locator('#welcome-silent').click();page.wait_for_function("document.querySelector('#scene').dataset.ready==='true'")
            def shot(name,full=False):
                path=output/f'{width}x{height}-{name}.png';page.screenshot(path=str(path),full_page=full);shots.append(path.name)
            if page.locator('.memory-scene').count():page.wait_for_function("getComputedStyle(document.querySelector('.memory-scene')).opacity==='1'")
            shot('scene')
            for view in ['review','calendar','future']:
                page.evaluate('view=>window.JournalUI.switchView(view)',view);page.evaluate('document.fonts.ready')
                if view!='review':
                    page.evaluate("""async()=>{for(let y=0;y<document.documentElement.scrollHeight;y+=innerHeight*.7){scrollTo(0,y);await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);}scrollTo(0,0);}""")
                    page.wait_for_function("[...document.querySelectorAll('#'+document.body.dataset.view+' .scroll-reveal')].filter(e=>e.getClientRects().length&&!e.closest('details:not([open])')).every(e=>getComputedStyle(e).opacity==='1')")
                if view=='review':page.wait_for_function("document.querySelector('#spread').dataset.fit==='ready'")
                shot(view)
                if view=='calendar':
                    page.locator('.publication-month').first.scroll_into_view_if_needed();page.locator('.publication-month').first.focus();shot('record-rhythm');page.locator('.publication-month').first.click();shot('record-rhythm-modal');page.locator('#close-modal').click();
                    page.locator('.month-toolbar').scroll_into_view_if_needed();shot('year-grid');page.locator('.year-stories').evaluate('e=>e.open=true');shot('calendar-full',True)
            for layout in ['B','C']:
                theme=page.evaluate("layout=>window.JOURNAL_DATA.story.themes.find(t=>t.layout===layout)?.id",layout)
                if theme:
                    page.evaluate("id=>window.JournalUI.go({view:'review',theme_id:id})",theme)
                    page.wait_for_function("document.querySelector('#spread').dataset.fit==='ready'")
                    shot('theme-'+layout)
            page.evaluate("window.JournalUI.go({view:'review',theme_id:'overview'})");page.wait_for_function('!window.JournalMotion.busy');shot('flip-start')
            page.get_by_role('button',name='下一页 →',exact=True).click();page.locator('.page-turn-sheet').wait_for(state='attached')
            page.evaluate("const a=document.querySelector('.page-turn-sheet').getAnimations()[0];a.pause();a.currentTime=110;")
            page.evaluate("async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}");shot('flip-front');page.evaluate("document.querySelector('.page-turn-sheet').getAnimations()[0].currentTime=230")
            page.evaluate("async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}")
            assert page.locator('.page-turn-sheet').evaluate("e=>Number(getComputedStyle(e).opacity)>.98"), 'old text ghosts over the new page'
            shot('flip-middle');page.evaluate("document.querySelector('.page-turn-sheet').getAnimations()[0].currentTime=570");page.evaluate("async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}");assert page.locator('.page-turn-layer').get_attribute('data-face')=='back';shot('flip-backface');page.evaluate("document.querySelector('.page-turn-sheet').getAnimations()[0].currentTime=719");page.evaluate("async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}");shot('flip-landing');page.evaluate("document.querySelector('.page-turn-sheet')?.getAnimations()[0]?.play()")
            page.wait_for_function('!window.JournalMotion.busy');shot('flip-end')
            page.get_by_role('button',name='← 上一页',exact=True).click();page.locator('.page-turn-sheet').wait_for(state='attached')
            page.evaluate("const a=document.querySelector('.page-turn-sheet').getAnimations()[0];a.pause();a.currentTime=230;")
            assert page.locator('.page-turn-sheet').evaluate("e=>Number(getComputedStyle(e).opacity)>.98")
            shot('flip-back-middle');page.evaluate("document.querySelector('.page-turn-sheet')?.getAnimations()[0]?.play()")
            page.wait_for_function('!window.JournalMotion.busy')

            context.close()
        browser.close()
    result={'html':str(html),'style':style,'screenshots':shots,'errors':errors,'review_status':'needs_agent_visual_review'}
    save(output/'visual-capture.json',result);return result


def boards(output, style, references):
    try:
        from PIL import Image,ImageDraw
    except ImportError:return []
    output,references=Path(output),Path(references);results=[]
    mappings=[('paper-desktop.png' if style=='paper' else 'frosted-overview.png','1440x900-review.png','overview-comparison.png')]
    if style=='frosted':mappings.append(('frosted-calendar.png','1440x900-year-grid.png','calendar-material-comparison.png'))
    for reference,actual,name in mappings:
        canvas=Image.new('RGB',(1440,490),'#f2f2ec');draw=ImageDraw.Draw(canvas);draw.text((15,12),'PROJECT REFERENCE',(35,35,35));draw.text((735,12),'ACTUAL OFFLINE HTML',(35,35,35))
        for x,p in [(0,references/reference),(720,output/actual)]:
            im=Image.open(p).convert('RGB');im.thumbnail((720,450));canvas.paste(im,(x+(720-im.width)//2,35+(450-im.height)//2))
        canvas.save(output/name);results.append(name)
    strip=Image.new('RGB',(1440,330),'#f2f2ec');draw=ImageDraw.Draw(strip)
    for index,name in enumerate(['flip-start','flip-middle','flip-end']):
        im=Image.open(output/f'1440x900-{name}.png').convert('RGB');im.thumbnail((480,300));strip.paste(im,(index*480,25));draw.text((index*480+12,8),name.upper(),(35,35,35))
    strip.save(output/'flip-progression.png');results.append('flip-progression.png');return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('html',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--browser-executable',type=Path)
    p.add_argument('--reference-root',type=Path,default=Path(__file__).resolve().parents[1]/'assets/cases');a=p.parse_args()
    result=capture(a.html,a.output,a.browser_executable);result['comparison_boards']=boards(a.output,result['style'],a.reference_root);save(a.output/'visual-capture.json',result);print(json.dumps(result,ensure_ascii=False))
