"""Capture target profile metadata from verified desktop DOM; never reads login secrets."""
import json
import math
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from archive_common import BEIJING, identifier, load, project_file, save, timestamp


def desktop_url(url, uid=None):
    p = urlsplit(url)
    valid = p.scheme == "https" and p.hostname in {"weibo.com", "www.weibo.com"} and not p.username and not p.password and p.port in (None, 443)
    return valid and (uid is None or p.path.rstrip("/") in {"/u/" + uid, "/" + uid})


def count_value(raw):
    """Preserve the site's displayed precision: 1.2万 is rounded, not exactly 12000."""
    if raw is None or not str(raw).strip() or str(raw).strip() in {"—", "--", "暂无", "未公开", "不可见"}:
        return {"display": "—", "value": None, "exact": False, "observed": False}
    match = re.search(r"(?<![\d.-])(\d[\d,]*(?:\.\d+)?)\s*([万亿kKmM]?)", str(raw))
    if not match or len(re.findall(r"(?<![\d.-])(\d[\d,]*(?:\.\d+)?)\s*([万亿kKmM]?)",str(raw)))!=1:
        raise ValueError("主页统计没有可核验数字，不用0代替未知")
    digits, unit = match.groups()
    multiplier = {"": 1, "万": 10000, "亿": 100000000, "k": 1000, "K": 1000, "m": 1000000, "M": 1000000}[unit]
    value = Decimal(digits.replace(",", "")) * multiplier
    return {"display": digits + unit, "value": int(value) if value == value.to_integral() else float(value),
            "exact": not unit and "." not in digits, "observed": True}


def profile_expression(uid, selectors):
    if selectors.get("root", "").strip() in {"body", "html", "*"}:
        raise ValueError("主页资料必须限定目标用户信息卡，不读取全页或登录者头像")
    required = {"root", "name", "avatar", "followers", "following", "engagement", "logged_in", "logged_out"}
    if not required <= selectors.keys() or any(not isinstance(selectors[k], str) or not selectors[k].strip() for k in required):
        raise ValueError("先在单个正常网页核验profile和登录状态的选择器")
    uid = identifier(uid)
    return """(()=>{
      const s=%s,uid=%s,visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
      if(!['https://weibo.com','https://www.weibo.com'].includes(location.origin))return JSON.stringify({success:false,reason:'desktop_required'});
      if(!['/u/'+uid,'/'+uid].includes(location.pathname.replace(/\\/$/,'')))return JSON.stringify({success:false,reason:'wrong_target'});
      if(!visible(document.querySelector(s.logged_in))||visible(document.querySelector(s.logged_out)))return JSON.stringify({success:false,reason:'login_required'});
      if(s.blocked&&visible(document.querySelector(s.blocked)))return JSON.stringify({success:false,reason:'site_verification_required'});
      const roots=document.querySelectorAll(s.root);if(roots.length!==1)return JSON.stringify({success:false,reason:'profile_not_unique'});
      const root=roots[0],name=root.querySelector(s.name),avatar=root.querySelector(s.avatar);
      if(!name||!avatar)return JSON.stringify({success:false,reason:'profile_fields_missing'});
      const read=k=>root.querySelector(s[k])?.innerText||null;
      return JSON.stringify({success:true,uid,source_url:location.href,name:name.innerText.trim(),
        avatar_source_url:avatar.currentSrc||avatar.src,followers:read('followers'),following:read('following'),engagement:read('engagement')});
    })()""" % (json.dumps(selectors), json.dumps(uid))


def capture_profile(bu, root, selectors):
    root = Path(root)
    meta = load(root / "project_meta.json")
    uid = meta["target"]["uid"]
    value = bu.js(profile_expression(uid, selectors))
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, dict) or not value.get("success"):
        return {"status": value.get("reason", "invalid_snapshot") if isinstance(value, dict) else "invalid_snapshot"}
    if value.get("uid") != uid or not desktop_url(value.get("source_url", ""), uid):
        raise ValueError("主页资料与采集目标不符")
    from manage_media import validate_url
    validate_url(value["avatar_source_url"])
    old = meta.get("profile", {})
    profile = {"uid": uid, "name": value["name"], "source_url": value["source_url"],
               "captured_at": datetime.now(BEIJING).isoformat(), "avatar_origin": "platform",
               "avatar_source_url": value["avatar_source_url"],
               **{key: count_value(value.get(key)) for key in ("followers", "following", "engagement")}}
    if old.get("uid") == uid and old.get("avatar_source_url") == profile["avatar_source_url"]:
        profile["avatar_path"] = old.get("avatar_path")
    meta["profile"] = profile
    if meta.get("title") == "人生手账":
        meta["title"] = profile["name"] + "的微博人生手账"
    save(root / "project_meta.json", meta)
    return {"status": "captured", "uid": uid, "missing_counts": [k for k in ("followers", "following", "engagement") if not profile[k]["observed"]],
            "avatar_saved": bool(profile.get("avatar_path"))}


def validate_profile(root, meta, required=False, resource_check=None):
    profile = meta.get("profile")
    if not profile:
        if required:
            raise ValueError("缺少网页端主页资料；先登录并采集名称、头像、粉丝、关注与转评赞")
        return None
    if not isinstance(profile,dict):
        raise ValueError('主页资料需为对象')
    if profile.get("uid") != meta["target"]["uid"] or not desktop_url(profile.get("source_url", ""), profile["uid"]):
        raise ValueError("主页资料UID/URL与目标不匹配")
    if not isinstance(profile.get("name"), str) or not profile["name"].strip():
        raise ValueError("微博名称必须来自主页")
    timestamp(profile.get("captured_at"))
    for key in ("followers", "following", "engagement"):
        field = profile.get(key)
        if not isinstance(field, dict) or not isinstance(field.get("display"), str) or not field["display"] or type(field.get("exact")) is not bool or 'value' not in field:
            raise ValueError("主页统计需保留display/value/exact，不用收录条数替代")
        value = field.get("value")
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError("主页统计必须为非负数字或未知null")
    avatar = profile.get("avatar_path")
    if not avatar:
        if required:
            raise ValueError("微博头像尚未保存；通过正常图片入口下载，不生成头像替身")
        return None
    from experience import synthetic_fixture
    fixture_avatar = synthetic_fixture(meta) and profile.get("avatar_origin") == "synthetic_fixture" and bool(profile.get("provided_reference"))
    if profile.get("avatar_origin") not in {"platform", "user_provided"} and not fixture_avatar:
        raise ValueError("头像必须是真实主页头像或用户提供，不用生成图片")
    if profile["avatar_origin"] == "platform":
        from manage_media import validate_url
        validate_url(profile.get("avatar_source_url", ""))
    elif not profile.get("provided_reference"):
        raise ValueError("用户提供的头像需要来源说明")
    if avatar.startswith("decorations/"):
        raise ValueError("不能把生成场景或插画当微博头像")
    if resource_check:
        resource_check(avatar, {".png", ".jpg", ".jpeg", ".webp", ".avif"})
    else:
        project_file(root, avatar, {".png", ".jpg", ".jpeg", ".webp", ".avif"})
    return avatar
