#!/usr/bin/env python3
"""Inspect the real offline scene, its text and every object at six viewport sizes.

The screenshots need an agent's visual review. A pass proves geometry and actions,
not the quality or semantic accuracy of the generated background.
"""
import argparse
import json
from pathlib import Path

from archive_common import save


def check(html, output, executable=None):
    from playwright.sync_api import sync_playwright
    html, output = Path(html).resolve(), Path(output).resolve()
    if not html.is_file():
        raise ValueError("需要已构建的完整HTML")
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": str(executable)} if executable else {}))
        try:
            for width, height in [(1440, 900), (1920, 1080), (900, 900), (390, 844), (320, 640), (844, 390)]:
                context = browser.new_context(viewport={"width": width, "height": height}, has_touch=width < 650)
                context.set_offline(True)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(html.as_uri())
                page.wait_for_function("window.JournalExperience && document.querySelector('#scene').dataset.ready==='true'")
                if page.locator("#welcome-silent").is_visible():
                    page.locator("#welcome-silent").click()
                page.evaluate("document.fonts.ready")
                page.wait_for_function("getComputedStyle(document.querySelector('.memory-scene')).opacity==='1'")
                scene = page.evaluate("""()=>{
                    const picture=document.querySelector('.scene-background').getBoundingClientRect(),guide=document.querySelector('.scene-guide');
                    const range=document.createRange();range.selectNodeContents(guide);
                    const lines=[...range.getClientRects()].filter(r=>r.width>1),r=guide.getBoundingClientRect();
                    return {picture:picture.toJSON(),guide:r.toJSON(),lines:lines.length,
                        guideFits:guide.scrollWidth<=guide.clientWidth+1,guideBackground:getComputedStyle(guide).backgroundColor,
                        headerHidden:getComputedStyle(document.querySelector('.site-header')).visibility==='hidden',
                        musicPaused:document.querySelector('audio')?.paused!==false,
                        documentFits:document.documentElement.scrollWidth<=innerWidth+1};
                }""")
                assert scene["headerHidden"], "首页导航盖住场景"
                assert scene["documentFits"], "整个文档产生横向溢出"
                assert scene["musicPaused"], "首次进入自动开音乐"
                assert scene["lines"] == 1 and scene["guideFits"], "顶部提示换行或裁字"
                assert scene["guideBackground"] in {"rgba(0, 0, 0, 0)", "transparent"}, "提示变成大背景卡片"
                picture = scene["picture"]
                assert picture["left"] >= 0 and picture["top"] >= 0 and picture["right"] <= width and picture["bottom"] <= height, "完整原图没有留在视口内"
                assert page.locator("#scene").get_attribute("data-fit") == "contain", "封面没有使用完整构图"
                for spot in page.locator(".scene-hotspot").all():
                    r=spot.bounding_box()
                    assert r and r["x"]>=0 and r["y"]>=0 and r["x"]+r["width"]<=width and r["y"]+r["height"]<=height, "初始场景热点超出屏幕"
                page.screenshot(path=str(output / f"{width}x{height}-scene.png"))
                hotspots = page.evaluate("JOURNAL_DATA.story.scene.hotspots")
                assert len(hotspots) >= 3, "完整场景缺少关键物件"
                for index, hotspot in enumerate(hotspots):
                    toggle = page.locator(".scene-find-toggle")
                    if toggle.get_attribute("aria-expanded") == "false":
                        toggle.click()
                    directory = page.locator(".scene-directory")
                    directory.get_by_role("button", name=hotspot["label"], exact=True).click()
                    page.locator(".scene-insight").wait_for(state="visible")
                    page.wait_for_function("getComputedStyle(document.querySelector('.scene-insight')).opacity==='1'")
                    point = page.evaluate("""id=>{
                        const spot=[...document.querySelectorAll('.scene-hotspot')].find(s=>s.dataset.hotspotId===id),r=spot.getBoundingClientRect();
                        const world=document.querySelector('.scene-world').getBoundingClientRect(),h=JOURNAL_DATA.story.scene.hotspots.find(h=>h.id===id);
                        const box=document.querySelector('.scene-insight').getBoundingClientRect();
                        return {x:r.left+r.width/2,y:r.top+r.height/2,expectedX:world.left+world.width*h.x/100,
                            expectedY:world.top+world.height*h.y/100,box:box.toJSON(),label:spot.getAttribute('aria-label'),
                            described:document.querySelector('.scene-insight .insight-copy').textContent,
                            found:spot.classList.contains('is-found')};
                    }""", hotspot["id"])
                    assert abs(point["x"] - point["expectedX"]) < 2 and abs(point["y"] - point["expectedY"]) < 2, "热点与图片坐标脱离"
                    assert 0 <= point["x"] <= width, f"目录没有把物件移入视口: {width}x{height} {hotspot['id']} {point}"
                    assert point["described"] == hotspot["description"] and point["found"], "小记与被点击物件不对应"
                    box = point["box"]
                    assert box["left"] >= 0 and box["top"] >= 0 and box["right"] <= width + 1 and box["bottom"] <= height + 1, "小记超出屏幕"
                    page.screenshot(path=str(output / f"{width}x{height}-object-{index}.png"))
                    page.keyboard.press("Escape")
                    assert page.locator(".scene-insight").count() == 0, "Escape未返回场景"
                    assert page.evaluate("document.activeElement.dataset.hotspotId") == hotspot["id"], "焦点没有回到物件"
                    if width >= 650:
                        spot = page.locator(".scene-hotspot").nth(index)
                        spot.hover()
                        page.wait_for_function("id=>getComputedStyle([...document.querySelectorAll('.scene-hotspot')].find(s=>s.dataset.hotspotId===id).querySelector('.hotspot-label')).opacity==='1'", arg=hotspot["id"])
                        assert spot.locator(".hotspot-label").inner_text() == hotspot["label"]
                assert page.evaluate("document.querySelector('audio')?.paused!==false"), "探索物件自动开音乐"
                if width >= 650:
                    page.mouse.move(width*.25,height*.35)
                    page.wait_for_function("document.querySelector('.scene-cursor-glow').dataset.active==='true'")
                    assert page.locator('.scene-world').evaluate("e=>e.style.getPropertyValue('--look-x')!==''"), '指针视差没有响应'
                checks.append({"viewport": [width, height], "cover": True, "single_line_guide": True,
                               "objects": len(hotspots), "all_objects_visible_without_pan": True, "anchored_notes": True,
                               "keyboard_return": True, "music_default_off": True, "pointer_focus": width >= 650})
                context.close()
            context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
            context.set_offline(True)
            page = context.new_page()
            page.goto(html.as_uri())
            page.wait_for_function("window.JournalExperience")
            if page.locator("#welcome-silent").is_visible():
                page.locator("#welcome-silent").click()
            assert page.locator(".scene-world").evaluate("e=>getComputedStyle(e).transform==='none'"), "低动态设置没有关闭视线漂移"
            page.mouse.move(200,200)
            assert page.locator('.scene-cursor-glow').evaluate("e=>getComputedStyle(e).display==='none'"), '低动态仍出现跟随光斑'
            context.close()
        finally:
            browser.close()
    assert not errors, errors
    result = {"ok": True, "html": str(html), "checks": checks, "errors": errors,
              "reduced_motion": True, "visual_review": "Inspect scene and object screenshots; generated image semantics are separate."}
    save(output / "homepage-report.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    try:
        report = check(args.html, args.output, args.browser_executable)
        print(json.dumps({"ok": True, "viewports": len(report["checks"]), "report": str(args.output / "homepage-report.json")}, ensure_ascii=False))
    except (ValueError, OSError, AssertionError) as error:
        parser.exit(1, "首页检查未通过: " + str(error) + "\n")
