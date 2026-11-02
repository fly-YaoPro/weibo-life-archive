#!/usr/bin/env python3
"""Compare the same content in paper/frosted outputs; properties differ, source records must not."""
import argparse
import json
from pathlib import Path
from archive_common import save

def check(paper,frosted,report,executable=None):
    from playwright.sync_api import sync_playwright
    records={}
    with sync_playwright() as p:
        browser=p.chromium.launch(**({'executable_path':str(executable)} if executable else {}))
        for kind,path in [('paper',paper),('frosted',frosted)]:
            context=browser.new_context(viewport={'width':1440,'height':900});context.set_offline(True);page=context.new_page();page.goto(Path(path).resolve().as_uri());page.wait_for_function('window.JournalUI')
            if page.locator('#welcome').is_visible():page.locator('#welcome-silent').click()
            page.evaluate("window.JournalUI.go({view:'review',theme_id:'overview'})")
            data=page.evaluate("""()=>{const s=q=>getComputedStyle(document.querySelector(q));return {story:window.JOURNAL_DATA.story,rows:window.JOURNAL_DATA.records,style:window.JOURNAL_DATA.skin,properties:{background:s('body').backgroundImage,font:s('.reader-heading h1').fontFamily,frame:s('.photo-frame').borderRadius,nav:s('header button[aria-current=page]').borderRadius,book:s('.reader-book').backgroundImage,player:s('.record-player-button').backgroundImage}};}""")
            assert data['style']==kind,'风格参数错误';records[kind]=data;context.close()
        browser.close()
    same=records['paper']['story']==records['frosted']['story'] and records['paper']['rows']==records['frosted']['rows']
    changed=[key for key in records['paper']['properties'] if records['paper']['properties'][key]!=records['frosted']['properties'][key]]
    result={'ok':same and len(changed)>=5,'same_story_and_records':same,'different_properties':changed,'note':'CSS差异不是审美通过；仍须运行visual_review并实际读图'};save(report,result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('paper',type=Path);p.add_argument('frosted',type=Path);p.add_argument('--report',type=Path,required=True);p.add_argument('--browser-executable',type=Path);a=p.parse_args()
    r=check(a.paper,a.frosted,a.report,a.browser_executable);print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['ok'] else 1)
