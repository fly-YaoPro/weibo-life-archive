#!/usr/bin/env python3
"""Verify actual offline page turns, including the pixels shown just before landing.

Requires Playwright and Pillow. Output screenshots are evidence for visual review,
not an automatic judgement of beauty. No personal data is added to the Skill.
"""
import argparse
import io
import json
from pathlib import Path

from archive_common import save


def check(html, output, executable=None):
    from PIL import Image, ImageChops, ImageFilter, ImageStat
    from playwright.sync_api import sync_playwright

    html, output = Path(html).resolve(), Path(output).resolve()
    if not html.is_file():
        raise ValueError("需要已构建的完整 HTML")
    output.mkdir(parents=True, exist_ok=True)
    results, errors = [], []

    def difference(first, second, rectangle):
        box = tuple(round(rectangle[key]) for key in ("left", "top", "right", "bottom"))
        # Borders and transparent outer corners are not page content.
        box = (box[0] + 8, box[1] + 8, box[2] - 8, box[3] - 8)
        a, b = (Image.open(io.BytesIO(data)).convert("RGB").crop(box) for data in (first, second))
        delta = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
        edges = sum(ImageStat.Stat(ImageChops.difference(
            a.filter(ImageFilter.GaussianBlur(.6)).filter(ImageFilter.FIND_EDGES), b.filter(ImageFilter.GaussianBlur(.6)).filter(ImageFilter.FIND_EDGES))).mean) / 3
        # Subpixel GPU antialiasing differs across projected strips. A small blur
        # removes that raster noise while preserving text and photograph edges.
        return {"mean_pixel_difference": round(delta, 3), "mean_edge_difference": round(edges, 3)}

    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": str(executable)} if executable else {}))
        try:
            for width, height in [(1440, 900), (390, 844)]:
                context = browser.new_context(viewport={"width": width, "height": height})
                context.set_offline(True)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(html.as_uri())
                page.wait_for_function("window.JournalUI && window.JournalMotion")
                if page.locator("#welcome-silent").is_visible():
                    page.locator("#welcome-silent").click()
                themes = page.evaluate("['overview', ...['B','C'].map(layout=>JOURNAL_DATA.story.themes.find(t=>t.layout===layout)?.id)].filter(Boolean)")
                for case, theme in enumerate(themes):
                    page.evaluate("id=>JournalUI.go({view:'review',theme_id:id})", theme)
                    page.evaluate("document.fonts.ready")
                    page.evaluate("async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}")
                    for direction, label in [(1, "next"), (-1, "previous")]:
                        button = page.get_by_role("button", name="下一页 →" if direction > 0 else "← 上一页", exact=True)
                        if button.is_disabled():
                            continue
                        prefix = f"{width}x{height}-{case}-{label}"
                        before = page.locator(".page-counter").inner_text()
                        # Programmatic double click deliberately stresses the busy guard.
                        button.evaluate("e=>{e.click();e.click()}")
                        page.locator(".page-turn-sheet").wait_for(state="attached")
                        page.evaluate("const a=document.querySelector('.page-turn-sheet').getAnimations()[0];a.pause();a.currentTime=0")
                        assert page.locator(".page-counter").inner_text() == before, "页码提前切换"
                        destination = page.evaluate("""direction=>{
                            const book=document.querySelector('#spread').firstElementChild;
                            const leaves=[...book.querySelectorAll(':scope>.leaf')].sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left);
                            const leaf=innerWidth>=700&&leaves.length===2?leaves[direction>0?0:1]:book;
                            return leaf.getBoundingClientRect().toJSON();
                        }""", direction)
                        page.evaluate("async()=>{await Promise.all([...document.querySelectorAll('#spread img')].map(i=>i.decode().catch(()=>{})));document.querySelector('.page-turn-layer').style.visibility='hidden'}")
                        expected = page.screenshot(path=str(output / f"{prefix}-destination.png"))
                        page.evaluate("document.querySelector('.page-turn-layer').style.visibility=''")
                        phases = []
                        for time in [110, 230, 380, 719]:
                            page.evaluate("time=>document.querySelector('.page-turn-sheet').getAnimations()[0].currentTime=time", time)
                            page.evaluate("async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}")
                            state = page.evaluate("""()=>{
                                const layer=document.querySelector('.page-turn-layer'),rects=[...layer.querySelectorAll('.turn-strip')].map(e=>e.getBoundingClientRect());
                                return {face:layer.dataset.face,progress:Number(layer.dataset.progress),
                                    top:Math.min(...rects.map(r=>r.top)),bottom:Math.max(...rects.map(r=>r.bottom)),
                                    pagerBottom:document.querySelector('#pager').getBoundingClientRect().bottom,
                                    mirrored:[...layer.querySelectorAll('.turn-strip')].some(e=>new DOMMatrix(getComputedStyle(e).transform).m11<-.001)};
                            }""")
                            assert not state["mirrored"], "可见页片文字发生镜像"
                            assert state["top"] >= state["pagerBottom"] - 2, f"纸页遮住翻页控件: {prefix} {time} {state}"
                            assert state["bottom"] <= height + 2, f"纸页飞出视口: {prefix} {time} {state}"
                            actual = page.screenshot(path=str(output / f"{prefix}-{time}.png"))
                            phases.append({"time_ms": time, **state})
                        assert phases[-1]["face"] == "back", "落页前背面没有显示"
                        pixels = difference(expected, actual, destination)
                        # Edge agreement detects a missing back, wrong photograph, mirrored text,
                        # or a large alignment jump while tolerating the glass skin's solid paper.
                        assert pixels["mean_pixel_difference"] < 6 and pixels["mean_edge_difference"] < 7, f"落页前内容与新页面不一致: {prefix} {pixels}"
                        page.evaluate("document.querySelector('.page-turn-sheet').getAnimations()[0].play()")
                        page.wait_for_function("!JournalMotion.busy")
                        assert page.locator(".page-turn-layer").count() == 0, "临时翻页层未清理"
                        after = page.locator(".page-counter").inner_text()
                        assert int(after.split('/')[0]) == int(before.split('/')[0]) + direction, "连点跳过页面"
                        events = page.evaluate("JournalMotion.events.filter(e=>e.event==='flip-start'||e.event==='flip-end').slice(-2)")
                        assert [event["event"] for event in events] == ["flip-start", "flip-end"]
                        results.append({"viewport": [width, height], "theme": theme, "direction": label,
                                        "before": before, "after": after, "phases": phases, **pixels})
                page.evaluate("JournalUI.go({view:'review',theme_id:'overview'})")
                page.get_by_role("button", name="下一页 →", exact=True).click()
                page.set_viewport_size({"width": 900, "height": 900})
                page.wait_for_function("!JournalMotion.busy && document.querySelector('#spread').dataset.fit==='ready'")
                assert page.locator(".page-turn-layer").count() == 0, "改变窗口后翻页未清理"
                context.close()
            context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
            context.set_offline(True)
            page = context.new_page()
            page.goto(html.as_uri())
            page.wait_for_function("window.JournalMotion")
            if page.locator("#welcome-silent").is_visible():
                page.locator("#welcome-silent").click()
            page.evaluate("JournalUI.go({view:'review',theme_id:'overview'})")
            page.get_by_role("button", name="下一页 →", exact=True).click()
            page.wait_for_function("!JournalMotion.busy")
            assert page.locator(".page-turn-layer").count() == 0, "低动态偏好未关闭立体翻页"
            assert page.locator(".page-counter").inner_text().lstrip().startswith("02"), "低动态模式未换页"
            context.close()
        finally:
            browser.close()
    assert not errors, errors
    report = {"ok": True, "html": str(html), "turns": results, "errors": errors,
              "resize_cleanup": True, "reduced_motion": True,
              "visual_review": "Inspect the saved front, edge and back frames."}
    save(output / "flip-report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.html, args.output, args.browser_executable)
        print(json.dumps({"ok": result["ok"], "turns": len(result["turns"]),
                          "report": str(args.output / "flip-report.json")}, ensure_ascii=False))
    except (ValueError, OSError, AssertionError) as error:
        parser.exit(1, "翻页检查未通过: " + str(error) + "\n")
