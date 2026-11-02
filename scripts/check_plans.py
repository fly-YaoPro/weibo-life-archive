"""Exercise editing/import/delete/restore in an isolated offline browser, never external tasks."""
import argparse
import json
from pathlib import Path
from archive_common import save


def check(html,output,executable=None):
    from playwright.sync_api import sync_playwright
    html,output=Path(html).resolve(),Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(**({'executable_path':str(executable)} if executable else {}))
        context=browser.new_context(viewport={'width':390,'height':844},accept_downloads=True,reduced_motion='reduce')
        context.set_offline(True);page=context.new_page();page.goto(html.as_uri())
        page.wait_for_function('window.JournalPlans')
        if page.locator('#welcome-silent').is_visible():page.locator('#welcome-silent').click()
        page.evaluate("JournalUI.switchView('future')")
        plans=page.evaluate('JournalPlans.snapshot()');assert plans
        first=plans[0];card=page.locator('.plan-card').filter(has_text=first['title']).first
        card.get_by_role('button',name='标记完成',exact=True).click()
        card.get_by_role('button',name='编辑',exact=True).click()
        page.get_by_label('要做什么',exact=True).fill('离线验收：手动修改保留')
        page.get_by_label('给自己留句话',exact=True).fill('手动便签')
        page.get_by_role('button',name='保存',exact=True).click();page.reload();page.wait_for_function('window.JournalPlans')
        actual=page.evaluate('JournalPlans.snapshot()');assert actual[0]['done'] and actual[0]['title']=='离线验收：手动修改保留'
        page.evaluate("JournalUI.switchView('future')")
        incoming=[{**first,'title':'不可覆盖手动修改','done':False}, {'id':'test-import','title':'离线验收：新增建议','month':'2027-09','done':False,'source_ids':[]}]
        data={'project_key':page.evaluate('JOURNAL_DATA.project_key'),'plans':incoming}
        page.locator('#import-plans').set_input_files({'name':'test.json','mimeType':'application/json','buffer':json.dumps(data,ensure_ascii=False).encode('utf-8')})
        page.get_by_role('button',name='确认合并',exact=True).click()
        actual=page.evaluate('JournalPlans.snapshot()');assert len(actual)==len(plans)+1 and actual[0]['title']=='离线验收：手动修改保留'
        page.locator('.plan-card').filter(has_text='离线验收：新增建议').get_by_role('button',name='删除',exact=True).click()
        page.get_by_role('button',name='确认删除',exact=True).click();assert len(page.evaluate('JournalPlans.snapshot()'))==len(plans)
        page.locator('#restore-plans').click();page.get_by_role('button',name='确认恢复',exact=True).click()
        assert len(page.evaluate('JournalPlans.snapshot()'))==len(plans)+1
        with page.expect_download() as event:page.locator('#export-plans').click()
        backup=output/'plans.json';event.value.save_as(backup)
        assert json.loads(backup.read_text(encoding='utf-8'))['plans']==page.evaluate('JournalPlans.snapshot()')
        # An intentional empty list must survive reload, not resurrect default suggestions.
        page.evaluate("localStorage.setItem('journal-reading:'+JOURNAL_DATA.project_key+':plans','[]')")
        page.reload();page.wait_for_function('window.JournalPlans');assert page.evaluate('JournalPlans.snapshot()')==[]
        page.evaluate("JournalUI.switchView('future')");assert '暂时没有计划' in page.locator('#plan-list').inner_text()
        page.locator('#share-button').click();page.get_by_role('button',name='生成预览',exact=True).click()
        page.wait_for_function("document.querySelector('.share-preview-image')?.naturalWidth===1080")
        page.screenshot(path=str(output/'empty-plan-share.png'))
        context.close();browser.close()
    result={'ok':True,'checks':['edit_and_done_persist','import_preserves_manual_values','delete_backed_up','restore','export_matches_current','intentional_empty_persists','empty_plan_share_works'],'external_tasks_created':0}
    save(output/'plans-report.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('html',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--browser-executable',type=Path);a=p.parse_args()
    print(json.dumps(check(a.html,a.output,a.browser_executable),ensure_ascii=False))
