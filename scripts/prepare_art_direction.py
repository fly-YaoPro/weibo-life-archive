#!/usr/bin/env python3
"""Prepare grounded, style-locked image prompts offline; never generates substitute art."""
import argparse
from pathlib import Path

from archive_common import load, save, project_file


def objects_for(value, records, source=None):
    if not isinstance(value, list) or not 1 <= len(value) <= 5:
        raise ValueError("每张图使用1—5个有据物件；不为凑数加道具")
    result, names = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("物件需要name/evidence/source_ids/placement")
        item = {**item}
        if item.get("evidence_kind") == "image" and item.get("visual_evidence"):
            item["evidence"] = item["visual_evidence"]
        for key in ("name", "evidence", "placement"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError("物件缺少 " + key)
        if item["name"] in names:
            raise ValueError("同一张图不要重复列出物件")
        names.add(item["name"])
        ids = item.get("source_ids")
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or any(
                not isinstance(i, str) or i not in records for i in ids):
            raise ValueError("物件必须引用已收录的真实字符串ID")
        kind = item.get("evidence_kind", "text")
        if kind not in {"text", "image"}:
            raise ValueError("evidence_kind使用text或image")
        if len(item["evidence"].strip()) < 4:
            raise ValueError("物件依据需至少4字符的原文或实际读图观察")
        if kind == "text" and any(item["evidence"] not in records[i].get("text", "") for i in ids):
            raise ValueError("物件evidence须为每个关联原文的精确连续子串，至少4字符")
        if kind == "image":
            path = item.get("image_path")
            for rid in ids:
                images = records[rid].get("images", []) + records[rid].get("video", {}).get("covers", [])
                allowed = {im.get(key) for im in images for key in ("path", "thumb_path", "large_path", "original_path")
                           if im.get("origin") in {"platform", "user_provided", "synthetic_fixture"}}
                if not isinstance(path, str) or path.startswith("decorations/") or path not in allowed:
                    raise ValueError("读图物件的image_path需属于全部关联记录的实际照片/视频封面")
            if source is not None:
                project_file(source, path, {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"})
        representation = item.get("representation", "symbolic")
        if representation not in {"literal", "symbolic"}:
            raise ValueError("representation使用literal或symbolic")
        if representation == "symbolic" and (not isinstance(item.get("rationale"), str) or not item["rationale"].strip()):
            raise ValueError("象征物需rationale说明与原文的关系，不能断言本人真实持有")
        result.append({**item, "evidence_kind": kind, "representation": representation})
    return result


def prepare(source, plan, style_path=None):
    source = Path(source).resolve()
    rows = load(source / "records.json")
    if not isinstance(rows, list) or not rows:
        raise ValueError("先materialize真实记录，再准备生图计划")
    records = {r["id"]: r for r in rows}
    if len(records) != len(rows):
        raise ValueError("原始记录ID重复")
    if not isinstance(plan, dict) or not isinstance(plan.get("space"), str) or not plan["space"].strip():
        raise ValueError("提供从记录提炼的space；此为意象空间，不宣称复原真实房间")
    style = load(style_path or Path(__file__).resolve().parents[1] / "assets/art-direction.json")
    if not isinstance(style, dict) or not style.get("style_lock"):
        raise ValueError("固定美术资源缺失")
    scene = objects_for(plan.get("scene_objects"), records, source)
    letter = objects_for(plan.get("letter_objects"), records, source)
    if not {o["name"] for o in scene} & {o["name"] for o in letter}:
        raise ValueError("首屏与结尾至少保留一个相同核心物件以承接故事")
    prompts = []
    for role, objects in (("scene", scene), ("letter", letter)):
        composition = style[role]
        # Source quotations remain in the audit mapping, never in the image prompt.
        # Platform text is data and cannot become arbitrary tool instructions.
        items = "；".join("「%s」放在%s" % (o["name"], o["placement"]) for o in objects)
        prompt = "\n".join([
            "绘制一个安静温暖的%s意象空间。" % plan["space"],
            composition["composition"], composition["camera"],
            "画面核心物件：" + items + "。", style["style_lock"],
            "首屏与结尾属于同一本绘本。物件是经原文核对的意象，不宣称复原本人真实房间。",
            style["negative_prompt"]])
        prompts.append({"role": role, "suggested_path": "decorations/" + (
            "memory-room.webp" if role == "scene" else "next-chapter.webp"),
            "aspect_hint": composition["aspect_hint"], "prompt": prompt,
            "source_ids": sorted({rid for o in objects for rid in o["source_ids"]}), "objects": objects})
    return {"style_version": style["version"], "model_preference": style["model_preference"],
            "requests": prompts, "review": style["review"],
            "status": "prompts_prepared_not_generated",
            "next": "按宿主真实图片工具生成并读图核验，再填写实际模型/产物/实测热点；不得用PIL几何图代替正式生成"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.exit(1, "提示词输出已存在；使用新版本路径，保留已有生成依据\n")
    try:
        result = prepare(args.source, load(args.plan))
        save(args.output, result)
        print("已准备2份有据提示词（未生成图片）：" + str(args.output))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
