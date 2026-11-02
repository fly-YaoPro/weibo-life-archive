#!/usr/bin/env python3
"""Check the installed bundle without probing accounts, credentials or paid tools."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from archive_common import load


def inspect_bundle(root, capabilities=None):
    root = Path(root)
    manifest = load(root / "skill_manifest.json", {})
    missing, digest = [], hashlib.sha256()
    for name in sorted(manifest.get("required_files", [])):
        p = root / name
        if not p.is_file():
            missing.append(name)
        else:
            digest.update(name.encode() + b"\0" + p.read_bytes())
    if not manifest.get("version") or not manifest.get("required_files"):
        missing.append("valid skill_manifest.json")
    capabilities = capabilities or {}
    return {"ok": not missing and sys.version_info >= (3, 9), "skill_version": manifest.get("version"),
            "bundle_sha256": digest.hexdigest(), "python": sys.version.split()[0], "missing": missing,
            "capabilities": {k: capabilities.get(k, "unknown") for k in
                             ("browser", "read_image", "image_generation", "audio_generation", "file_delivery")},
            "note": "工具能力由宿主实际发现后填入；注册不代表调用成功。此检查不登录、不证明采集或视觉通过。"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--capabilities", type=Path)
    a = p.parse_args()
    result = inspect_bundle(a.skill_root, load(a.capabilities) if a.capabilities else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
