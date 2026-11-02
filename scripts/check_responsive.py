#!/usr/bin/env python3
"""Read every reading page in isolated offline browsers and check cover content at narrow sizes."""
import argparse
import json
from pathlib import Path
from archive_common import save

def check(html, output, executable=None, sizes=((1440,900),(1366,768),(900,900),(390,844),(320,640),(844,390))):
    from playwright.sync_api import sync_playwright
    html, output=Path(html).resolve(),Path(output).resolve()
    if not html.is_file(): raise ValueError('需要实际HTML文件')
    results,errors=[],[]
    with sync_playwright() as p:
        browser=p.chromium.launch(**({'executable_path':str(executable)} if executable else {}))
        for width,height in sizes:
            context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce');context.set_offline(True);page=context.new_page()
            try:
                page.goto(html.as_uri());page.wait_for_function('window.JournalUI && window.JournalMotion')
                if page.locator('#welcome').is_visible():page.locator('#welcome-silent').click()
                page.evaluate("window.JournalUI.go({view:'review',theme_id:'overview'})")
                expected=page.evaluate("({opening:window.JOURNAL_DATA.story.overview.opening||'',portrait:window.JOURNAL_DATA.story.overview.portrait?.text||''})")
                page.wait_for_function("document.querySelector('#spread').dataset.fit==='ready'")
                initial=page.locator('.reader-prose').inner_text()
                page.wait_for_timeout(300)
                assert page.locator('.reader-prose').inner_text()==initial,'首次介绍在布局刷新后改变或消失'
                if width>=700 and page.evaluate('!!JOURNAL_DATA.meta.profile'):
                    assert page.evaluate("document.querySelector('.user-profile').getBoundingClientRect().right<=document.querySelector('.reader-main-copy').getBoundingClientRect().left"),'真实用户资料没有放在左侧'
                page.screenshot(path=str(output.parent/f'{width}x{height}-review.png'))
                corpus=[];count=0
                while count<160:
                    page.wait_for_function('!window.JournalMotion.busy')
                    assert page.locator('#spread').get_attribute('data-fit')=='ready','正文未适配'
                    assert page.evaluate('document.documentElement.scrollHeight<=innerHeight+1'),'回看需要纵向滚动'
                    assert page.evaluate("[...document.querySelectorAll('#spread .book>.leaf')].every(e=>e.scrollHeight<=e.clientHeight+2&&e.scrollWidth<=e.clientWidth+2)"),'叶片内容溢出'
                    corpus.extend(page.locator('.reader-prose .lead,.cover-opening,.cover-portrait>p').all_text_contents());count+=1
                    if page.get_by_role('button',name='下一页 →',exact=True).is_disabled():break
                    page.get_by_role('button',name='下一页 →',exact=True).click()
                assert count<160,'分页未终止'
                combined=''.join(corpus)
                for key,text in expected.items():
                    if text:assert text in combined,key+'内容遗漏'
                page.evaluate("JournalUI.switchView('calendar')")
                page.locator('.publication-month').first.scroll_into_view_if_needed()
                page.locator('.publication-month').first.focus()
                assert page.locator('.publication-month').first.locator('.rhythm-tip').evaluate("e=>getComputedStyle(e).visibility==='visible'"),'记录节奏键盘提示不可见'
                page.locator('.publication-month').first.click()
                assert page.locator('#modal .record-card').count()>0,'记录节奏弹窗没有真实片段'
                assert page.locator('#calendar').is_visible(),'打开节奏弹窗跳转了视图'
                page.locator('#close-modal').click()
                assert page.evaluate("document.querySelectorAll('.publication-month').length<=new Set(JOURNAL_DATA.records.map(r=>r.date.slice(0,7))).size"),'记录节奏扩展到未采集范围'
                results.append({'viewport':[width,height],'pages':count,'cover_content_complete':True,'single_screen':True,'intro_stable':True,'profile_left':width>=700,'rhythm_modal':True})
            except Exception as e:errors.append(f'{width}x{height}: {type(e).__name__}: {e}')
            finally:context.close()
        browser.close()
    result={'ok':not errors,'checks':results,'errors':errors};save(output,result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('html',type=Path);p.add_argument('--report',type=Path,required=True);p.add_argument('--browser-executable',type=Path);a=p.parse_args()
    r=check(a.html,a.report,a.browser_executable);print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['ok'] else 1)
