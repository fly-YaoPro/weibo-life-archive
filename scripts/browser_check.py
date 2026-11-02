#!/usr/bin/env python3
"""Optional Playwright acceptance runner: isolated profile, offline file://, real PNG export.

Install Playwright and its Chromium in the execution environment, not in the Skill bundle.
This tests behavior/layout bounds, not the truth of source data or artistic quality.
"""
import argparse
import json
from pathlib import Path

from archive_common import load, save


def verify(project, report_dir, executable=None):
    from playwright.sync_api import sync_playwright
    project, report_dir = Path(project).resolve(), Path(report_dir).resolve()
    if project == report_dir:
        raise ValueError("测试输出使用独立子目录，不覆盖交付文件")
    report_dir.mkdir(parents=True, exist_ok=True)
    checks, errors, screenshots = [], [], []
    url = (project if project.is_file() else project / "index.html").as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**({"executable_path": str(executable)} if executable else {}))
        for width, height in ((1440, 900), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True)
            context.set_offline(True)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(url)
                page.wait_for_function("window.JournalUI && window.JournalMotion")
                assert page.evaluate("!document.querySelector('audio') || document.querySelector('audio').paused"), "BGM must start paused"
                if page.locator('#scene').count() and page.evaluate('!!window.JOURNAL_DATA.story.scene'):
                    page.wait_for_function("document.querySelector('#scene').dataset.ready==='true'")
                    page.locator('#welcome').wait_for(state='visible')
                    page.screenshot(path=str(report_dir/f"{width}x{height}-welcome.png"))
                    page.locator('#welcome-silent').click()
                    page.wait_for_function("getComputedStyle(document.querySelector('.memory-scene')).opacity==='1'")
                    assert page.locator('#scene').bounding_box()['height']>=height-1
                assert page.locator('.scene-guide').count()==(1 if page.evaluate('!!window.JOURNAL_DATA.story.scene') else 0)
                views = page.locator("header button[data-view]:not([hidden])").evaluate_all("els=>els.map(e=>e.dataset.view)")
                for view in views:
                    page.evaluate('view=>window.JournalUI.switchView(view)',view)
                    page.locator("#" + view).wait_for(state="visible")
                    page.evaluate("document.fonts.ready")
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), f"horizontal overflow: {view}"
                    issues = page.evaluate("""()=>Array.from(document.querySelectorAll('h1,h2,h3,.brand')).filter(el=>el.getClientRects().length&&!el.closest('details:not([open])')).flatMap(el=>{
                        const bad=[];if(el.scrollWidth>el.clientWidth+2)bad.push('overflow: '+el.textContent);
                        const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),rows=[];const tolerance=(parseFloat(getComputedStyle(el).lineHeight)||24)*.45;let text,total=0;
                        while(text=walker.nextNode()){for(let i=0;i<text.length;i++){if(!text.textContent[i].trim())continue;const r=document.createRange();r.setStart(text,i);r.setEnd(text,i+1);const box=r.getBoundingClientRect();const y=box.top;let row=rows.find(row=>Math.abs(row.y-y)<tolerance);if(!row){row={y,count:0};rows.push(row);}row.count++;total++;}}
                        const counts=rows.sort((a,b)=>a.y-b.y).map(row=>row.count);
                        if(total>6&&counts.length>1&&counts.at(-1)<=2)bad.push('orphan title: '+el.textContent);
                        return bad;
                    })""")
                    assert not issues, str(issues)
                    if view in ('calendar','future'):
                        page.evaluate("""async()=>{for(let y=0;y<document.documentElement.scrollHeight;y+=innerHeight*.7){scrollTo(0,y);await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);}scrollTo(0,0);}""")
                        page.wait_for_function("Array.from(document.querySelectorAll('#'+document.body.dataset.view+' .scroll-reveal')).filter(el=>el.getClientRects().length&&!el.closest('details:not([open])')).every(el=>getComputedStyle(el).opacity==='1')")
                    name = f"{width}x{height}-{view}.png"
                    page.screenshot(path=str(report_dir / name), full_page=True)
                    screenshots.append(name)
                checks.append({"viewport": [width, height], "fullscreen_scene_and_silent_entry": True, "offline_file_views": views, "no_horizontal_overflow": True, "music_default_paused": True})
                if "scene" in views:
                    page.locator('button[data-view="scene"]').click()
                    page.locator(".scene-hotspot").first.click()
                    page.get_by_role("button", name="翻到这段记忆", exact=True).click()
                    page.wait_for_function("!window.JournalMotion.busy && document.body.dataset.view!=='scene'")
                    assert not page.locator('.scene-insight').is_visible()
                    checks[-1]["scene_hotspot_navigation"] = True
                if page.locator("#music-control").is_visible():
                    page.evaluate("window.JournalExperience.setMusic(false)")
                    page.locator(".record-player-button").click()
                    page.wait_for_function("!document.querySelector('audio').paused")
                    page.locator(".record-player-button").click()
                    assert page.evaluate("document.querySelector('audio').paused")
                    checks[-1]["music_click_play_pause"] = True
                search_record = page.evaluate("window.JOURNAL_DATA.records.find(r=>r.text.trim().length>=4)")
                if search_record:
                    page.locator('button[data-view="calendar"]').click()
                    page.locator("#search").fill(search_record["text"].strip()[:6])
                    assert page.locator("#search-results .record-card").count() > 0
                    page.get_by_role("button", name="定位这一天", exact=True).first.click()
                    assert page.locator("#day-detail .record-card").count() > 0
                    checks[-1]["global_search_day_navigation"] = True
                page.locator('button[data-view="calendar"]').click()
                expected_months=page.evaluate("()=>{const year=document.querySelector('#year').value,months=new Set(JOURNAL_DATA.records.filter(r=>r.date.startsWith(year)).map(r=>r.date.slice(5,7)));return months.size>0&&months.size<6?months.size:12;}")
                assert page.locator('.year-month').count() == expected_months, 'year grid does not follow the collected months'
                year = int(page.locator('#year').input_value())
                if page.locator('#previous-year').is_enabled():
                    page.locator('#previous-year').click()
                    known_years=page.locator('#year option').evaluate_all('els=>els.map(e=>Number(e.value))')
                    assert int(page.locator('#year').input_value()) == known_years[known_years.index(year)-1], 'year navigation did not skip unsampled years'
                    page.locator('#next-year').click()
                assert page.evaluate("getComputedStyle(document.querySelector('.site-header')).position === 'fixed'")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                assert page.locator('.site-header').bounding_box()['y'] == 0
                checks[-1]["year_grid_and_fixed_header"] = True
                assert page.locator('header button[data-view=stats]').count()==0
                assert page.locator('#calendar>#stats').count()==1
                checks[-1]['archive_summary_merged_into_calendar']=True
                # Plans are seeded from records and remain editable after reload.
                page.locator('button[data-view="future"]').click()
                assert page.locator('#add-plan,#export-plans,#import-plans,#restore-plans,#storage-note').count()==5
                assert page.locator('.plan-card').count()>0
                page.locator('.plan-card .plan-actions').first.get_by_role('button',name='编辑',exact=True).click()
                page.get_by_label('要做什么',exact=True).fill('合成验收：保留手动修改')
                page.get_by_role('button',name='保存',exact=True).click()
                page.reload(); page.wait_for_function('window.JournalPlans')
                page.evaluate("JournalUI.switchView('future')")
                assert '合成验收：保留手动修改' in page.locator('#plan-list').inner_text()
                with page.expect_download() as exported:
                    page.locator('#export-plans').click()
                exported.value.save_as(report_dir/f'{width}-plans.json')
                checks[-1]["editable_plan_persists_and_exports"] = True
                page.locator('button[data-view="review"]').click()
                page.wait_for_function('!window.JournalMotion.busy')
                page.evaluate("window.JournalUI.go({view:'review',theme_id:'overview'})")
                source_ids=page.evaluate('JOURNAL_DATA.story.overview.source_ids')
                before_view=page.locator('body').get_attribute('data-view')
                group=page.locator('#spread .source-chips button').filter(has_text='翻开这')
                if group.count():
                    group.first.click()
                    assert page.locator('#modal .record-card').count()==len(set(source_ids)), 'source modal omitted records'
                    assert page.locator('body').get_attribute('data-view')==before_view, 'opening source records left the reading page'
                    assert all(page.locator(f'#modal .record-card[data-record-id="{rid}"]>p').count()>0 for rid in source_ids), 'source modal omitted text'
                    photo_button=page.locator('#modal .record-card .photo-open')
                    if photo_button.count():
                        target=photo_button.last
                        # 多图折叠在 <details> 内，先展开其所在 details，否则按钮永远不可见
                        target.evaluate('b=>{let d=b.closest("details"); if(d) d.open=true;}')
                        target.scroll_into_view_if_needed()
                        prior_scroll=page.locator('#modal').evaluate('e=>e.scrollTop')
                        target.click()
                        assert page.locator('#modal .photo-viewer').count()==1, 'source image did not enlarge'
                        page.keyboard.press('Escape')
                        page.wait_for_function("document.querySelector('#modal-content .memory-dialog')!==null")
                        page.wait_for_function('v=>Math.abs(document.querySelector("#modal").scrollTop-v)<=2',arg=prior_scroll)
                        assert page.locator('#modal .record-card').count()==len(set(source_ids)), 'return from image lost the source list'
                        checks[-1]['source_image_returns_to_same_modal_scroll']=True
                    page.locator('#close-modal').click()
                    checks[-1]['source_records_open_in_modal']=True
                page_count=int(page.locator('.page-counter').inner_text().split('/')[1])
                for index in range(160):
                    assert page.evaluate("document.documentElement.scrollHeight<=innerHeight+1"), 'reading requires vertical scroll'
                    assert page.locator('#spread').get_attribute('data-fit')=='ready', 'reading prose clipped'
                    rect=page.locator('.reader-book').bounding_box()
                    assert rect['y']>=0 and rect['y']+rect['height']<=height+1, 'reading book outside viewport'
                    if page.get_by_role('button',name='下一页 →',exact=True).is_enabled():
                        page.get_by_role('button',name='下一页 →',exact=True).click()
                        page.wait_for_function('!window.JournalMotion.busy')
                    else:break
                else:raise AssertionError('reading pagination did not terminate')
                checks[-1]['all_reading_pages_fit_viewport']=True
                if page.get_by_role('button',name='← 上一页',exact=True).is_enabled():
                    page.get_by_role('button',name='← 上一页',exact=True).click()
                    page.wait_for_function('!window.JournalMotion.busy')
                assert page.evaluate("window.JournalMotion.events.some(e=>e.event==='sound-end'&&e.kind==='page')")
                checks[-1]['page_turn_animation_and_sound']=True
                page.locator('button[data-view="calendar"]').click()
                framed=page.locator('#calendar .month-photo img')
                if framed.count():
                    assert framed.first.evaluate("el=>getComputedStyle(el).objectFit==='contain'")
                    for im in framed.all():
                        assert im.evaluate("e=>getComputedStyle(e).objectFit==='contain'")
                        expected=im.evaluate("e=>e.naturalWidth/e.naturalHeight<.87?.75:e.naturalWidth/e.naturalHeight<1.15?1:4/3")
                        rect=im.bounding_box(); assert abs(rect['width']/rect['height']-expected)<.08, 'month photo aspect ratio'
                for view in ['review','calendar','future']:
                    page.locator(f'button[data-view="{view}"]').click()
                    assert page.evaluate("Array.from(document.querySelectorAll('#'+document.body.dataset.view+' img')).every(im=>!!im.closest('.photo-frame')||(im.matches('.profile-avatar')&&!!im.closest('.user-profile')))"), 'unframed photo'
                checks[-1]["photo_frames_and_uncropped_month_photos"] = True
                page.locator("#share-button").click()
                page.get_by_label('包含微博原图',exact=True).check()
                page.get_by_role('button',name='生成预览',exact=True).click()
                page.get_by_role("button",name="下载 PNG",exact=True).wait_for(state="visible")
                page.wait_for_function("!document.querySelector('.share-toolbar .primary').disabled")
                assert page.locator(".share-preview-image").count()>0
                assert page.locator(".share-preview").evaluate("e=>e.scrollHeight>e.clientHeight || [...e.querySelectorAll('img')].every(i=>i.getBoundingClientRect().bottom<=e.getBoundingClientRect().bottom+2)"), "share preview neither fits nor scrolls"
                assert page.get_by_role("button",name="复制图片",exact=True).is_enabled()
                with page.expect_download() as event:
                    page.get_by_role("button", name="下载 PNG", exact=True).click()
                target = report_dir / "exports" / "十年回看_1080.png"
                target.parent.mkdir(exist_ok=True)
                event.value.save_as(target)
                from manage_media import image_info
                assert image_info(target.read_bytes())[1] == 1080 and image_info(target.read_bytes())[2] > 1440
                assert page.locator("#modal").is_visible()
                page.locator("#close-modal").click()
                checks[-1]["share_png_1080_dynamic_height"] = True
                page.evaluate("JournalUI.switchView('review')")
                assert page.locator('#scope-note').inner_text().startswith(page.evaluate('JOURNAL_DATA.scope'))
                checks[-1]["actual_scope_and_selection_label_preserved"] = True
                if "scene" in views:
                    page.locator('header button[data-view="scene"]').click()
                    player=page.locator('.record-player-button').bounding_box()
                    assert player['y']>=0 and player['y']+player['height']<=height+1, 'player outside viewport: '+str(player)
                    page.evaluate("sessionStorage.removeItem('journal-welcome:'+window.JOURNAL_DATA.project_key)")
                    page.goto(url)
                    page.locator('#welcome').wait_for(state='visible')
                    page.locator('#welcome-music').click()
                    page.locator('#welcome').wait_for(state='hidden')
                    page.wait_for_function("!document.querySelector('audio').paused && document.querySelector('audio').duration>0")
                    page.reload()
                    page.wait_for_function("document.querySelector('#scene').dataset.ready==='true'")
                    assert not page.locator('#welcome').is_visible(), 'entry guide repeated after choosing music'
                    checks[-1]["music_entry_choice_and_no_repeat_guide"] = True
                if 'scene' in views:
                    page.locator('#welcome').wait_for(state='hidden')
                    page.evaluate("window.__entryFrames=[];function auditEntry(){const spread=document.querySelector('#spread');if(document.body.dataset.view==='review'&&!document.querySelector('.time-portal'))window.__entryFrames.push(Number(getComputedStyle(spread).opacity));if(window.__entryFrames.length<40)requestAnimationFrame(auditEntry);}requestAnimationFrame(auditEntry);")
                    page.locator('.scene-footer .primary').click()
                    page.wait_for_selector('.time-portal')
                    assert page.evaluate("document.querySelector('audio').paused"), 'music overlaps the portal sound'
                    page.wait_for_function("!window.JournalMotion.busy && document.body.dataset.view==='review'")
                    page.wait_for_function("window.JournalMotion.events.some(e=>e.event==='music-start'&&e.kind==='portal')")
                    order=page.evaluate("()=>{const events=window.JournalMotion.events;return {end:events.find(e=>e.event==='sound-end'&&e.kind==='portal').time,music:events.find(e=>e.event==='music-start'&&e.kind==='portal').time};}")
                    assert order['music']>=order['end'], 'entry music starts before the sound finishes'
                    page.wait_for_function('window.__entryFrames.length>=10')
                    assert page.evaluate('Math.min(...window.__entryFrames)>=.99'), 'introduction flashes away after the portal clears'
                    checks[-1]['portal_sound_before_music']=True
                    checks[-1]['introduction_stays_visible_after_entry']=True
                broken = page.evaluate("Array.from(document.images).filter(i=>i.complete&&!i.naturalWidth).length")
                assert broken == 0, "broken local images"
            except Exception as error:
                import traceback
                errors.append(f"{width}x{height}: {type(error).__name__}: {error}\n{traceback.format_exc()}")
            finally:
                context.close()
        browser.close()
    result = {"ok": not errors, "checks": checks, "errors": errors, "screenshots": screenshots,
              "not_tested": ["真实账号采集", "来源语义与图片内容", "视觉美感", "真实手机", "音频实际听感"]}
    save(report_dir / "browser-report.json", result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project", type=Path)
    p.add_argument("--report-dir", type=Path)
    p.add_argument("--browser-executable", type=Path, help="Optional existing Chromium/Chrome executable")
    a = p.parse_args()
    try:
        result = verify(a.project, a.report_dir or (a.project.parent / (a.project.stem + "-checks") if a.project.is_file() else a.project / "test-screenshots"), a.browser_executable)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    except ImportError:
        p.exit(2, "未测试：运行环境缺少 Playwright；可使用宿主 browser_use 按验收参考实测，不能报通过。\n")
    except Exception as error:
        result = {"ok": False, "checks": [], "errors": [type(error).__name__ + ": " + str(error)],
                  "not_tested": ["浏览器未能正常启动/执行，不能视为验收通过"]}
        save((a.report_dir or (a.project.parent / (a.project.stem + "-checks") if a.project.is_file() else a.project / "test-screenshots")) / "browser-report.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(1)
