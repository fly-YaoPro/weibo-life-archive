"""Verified desktop observations and same-origin requests; never exports credentials."""
import json
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

from archive_common import BEIJING, timestamp

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def mid_to_bid(mid):
    if not isinstance(mid, str) or not mid.isdigit():
        raise ValueError("微博mid必须是真实数字字符串")
    groups = []
    for end in range(len(mid), 0, -7):
        value = int(mid[max(0, end - 7):end]); text = ""
        while value:
            value, remainder = divmod(value, 62); text = ALPHABET[remainder] + text
        groups.append((text or "0").zfill(4) if end > 7 else text or "0")
    return "".join(reversed(groups))


def permalink_mid(url, uid):
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in {"weibo.com", "www.weibo.com"} or p.username or p.password or p.port not in (None, 443):
        raise ValueError("必须是正常微博网页端原帖链接")
    match = re.fullmatch(r"/" + re.escape(uid) + r"/([0-9A-Za-z]+)(?:/)?", p.path)
    if not match:
        raise ValueError("原帖链接与目标UID不符，不用主页/摘要哈希代替微博id")
    bid = match.group(1); parts = []
    for end in range(len(bid), 0, -4):
        value = 0
        for char in bid[max(0, end - 4):end]:
            value = value * 62 + ALPHABET.index(char)
        parts.append(str(value).zfill(7) if end > 4 else str(value))
    mid = str(int("".join(reversed(parts))))
    if mid_to_bid(mid) != bid:
        raise ValueError("原帖链接无法无损转换为真实微博id")
    return mid


def full_time(raw, observed_at):
    raw = (raw or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T",raw):
        try:return timestamp(raw)
        except ValueError:pass
    observed = datetime.fromisoformat(timestamp(observed_at))
    relative = re.fullmatch(r"(\d+)\s*(秒|分钟|小时)前", raw)
    if relative:
        amount, unit = relative.groups()
        return (observed - timedelta(seconds=int(amount) * {"秒": 1, "分钟": 60, "小时": 3600}[unit])).isoformat()
    if raw == "刚刚":
        return observed.isoformat()
    match = re.fullmatch(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})(?:日)?(?:\s+|T)(\d{1,2}):(\d{2})(?::(\d{2}))?", raw)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=BEIJING).isoformat()
    # A month/day alone does not identify the year; get the actual tooltip/detail.
    if re.match(r"^\d{4}-\d{2}-\d{2}T", raw):
        try:
            return timestamp(raw)
        except ValueError:
            pass
    raise ValueError("缺完整年份/时间；悬停或打开原帖读取，不能全部补成当前年")


def desktop_expression(uid, selectors):
    required = {"root", "cards", "author", "text", "time", "permalink", "images", "logged_in", "logged_out", "original_filter"}
    if not required <= selectors.keys() or any(not isinstance(selectors[k], str) or not selectors[k].strip() for k in required):
        raise ValueError("先在已登录的单个正常原创列表核验桌面DOM选择器")
    return """(()=>{
      const uid=%s,s=%s,visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
      if(!['https://weibo.com','https://www.weibo.com'].includes(location.origin))return JSON.stringify({success:false,reason:'desktop_required'});
      if(!['/u/'+uid,'/'+uid].includes(location.pathname.replace(/\\/$/,'')))return JSON.stringify({success:false,reason:'wrong_target'});
      if(!visible(document.querySelector(s.logged_in))||visible(document.querySelector(s.logged_out)))return JSON.stringify({success:false,reason:'login_required'});
      if(s.blocked&&visible(document.querySelector(s.blocked)))return JSON.stringify({success:false,reason:'site_verification_required'});
      if(!document.querySelector(s.original_filter))return JSON.stringify({success:false,reason:'original_filter_required'});
      const roots=document.querySelectorAll(s.root);if(roots.length!==1)return JSON.stringify({success:false,reason:'feed_not_unique'});
      const visibleCards=[...roots[0].querySelectorAll(s.cards)].filter(card=>{const r=card.getBoundingClientRect();return r.height>0&&r.bottom>=-innerHeight&&r.top<=innerHeight*2;}).slice(0,25);
      const records=visibleCards.map(card=>{
        const author=card.querySelector(s.author),link=card.querySelector(s.permalink),time=card.querySelector(s.time),copy=card.querySelector(s.text);
        const authorUrl=author?.href||'',m=authorUrl.match(/\\/(?:u\\/)?(\\d+)(?:[/?#]|$)/),postUrl=link?.href||'',owner=postUrl.match(/^https:\\/\\/(?:www\\.)?weibo\\.com\\/(\\d+)\\/[0-9A-Za-z]+/);
        const videoNode=s.video?card.querySelector(s.video):null;
        const originals=s.original_images?[...card.querySelectorAll(s.original_images)].map(e=>e.href||e.currentSrc||e.src):[];
        const images=[...card.querySelectorAll(s.images)].filter(e=>!videoNode?.contains(e)).map((e,i)=>({origin:'platform',thumb_url:e.currentSrc||e.src,
          source_url:originals[i]||e.currentSrc||e.src,large_url:originals[i]||e.currentSrc||e.src,
          original_url:originals[i]||null,thumb_path:null,large_path:null,download_status:'unavailable'}));
        const coverNode=videoNode&&(s.video_cover?videoNode.querySelector(s.video_cover):videoNode.querySelector('img'));
        const coverUrl=coverNode?.currentSrc||coverNode?.src||videoNode?.poster||null;
        const video=videoNode?{source_url:postUrl,cover_status:coverUrl?'observed':'unavailable',covers:coverUrl?[{origin:'platform',source_url:coverUrl,thumb_url:coverUrl,large_url:coverUrl,thumb_path:null,large_path:null,download_status:'unavailable'}]:[]}:null;
        return {observed_id:card.getAttribute('data-mid')||card.getAttribute('mid')||null,
          author_uid:m?.[1]||owner?.[1]||null,is_original:!(s.repost&&card.querySelector(s.repost)),is_video:!!(s.video&&card.querySelector(s.video)),
          raw_time:time?.dateTime||time?.getAttribute('datetime')||time?.getAttribute('title')||time?.innerText||'',
          text:copy?.innerText||'',text_status:s.more_text?(card.querySelector(s.more_text)?'pending':'complete'):'unknown',
          url:link?.href||null,images,video};
      });
      return JSON.stringify({success:true,source_url:location.href,records,observed_count:records.length,
        end_visible:!!(s.end_marker&&visible(document.querySelector(s.end_marker)))});
    })()""" % (json.dumps(uid), json.dumps(selectors))


def timeline_request(uid, observed_request, page=1, since_id=None):
    """Only reproduce an observed desktop timeline route; never guess alternate APIs."""
    p = urlsplit(observed_request)
    if p.scheme or p.netloc or p.fragment or p.path != "/ajax/statuses/mymblog":
        raise ValueError("先观察正常网页的同源 /ajax/statuses/mymblog 请求")
    query = parse_qs(p.query, keep_blank_values=True)
    if not {"uid", "page", "feature", "count"} <= query.keys() or set(query) - {"uid", "page", "feature", "count", "since_id"}:
        raise ValueError("请求须包含已观察的 uid/page/feature/count；不扩展未核验参数")
    if any(len(values) != 1 for values in query.values()) or query["uid"] != [uid] or query["feature"] != ["0"]:
        raise ValueError("使用已验证的 feature=0 普通时间线，本地核验并过滤转发")
    if query["page"] != ["1"] or query.get("since_id", [""])[0] not in ("", "0"):
        raise ValueError("完整历史断点须从第1页开始；中间页不能证明此前范围覆盖")
    if not query["count"][0].isdigit() or not 1 <= int(query["count"][0]) <= 100:
        raise ValueError("使用已观察的合理分页大小")
    if type(page) is not int or page < 1 or (since_id is not None and (not isinstance(since_id, str) or not since_id)):
        raise ValueError("page为正整数，游标必须使用无损字符串")
    params = {key: values[0] for key, values in query.items() if key != "since_id"}
    params["page"] = str(page)
    if since_id is not None: params["since_id"] = since_id
    return p.path + "?" + urlencode(params)


def timeline_expression(uid, selectors, request_path):
    """One request per host call. Return responseText to keep IDs out of JS Number."""
    # Reuse the observed login, target, feed and site-verification gate before each request.
    gate = history_gate_expression(uid, selectors)
    return """(()=>{
      const gate=JSON.parse(%s);if(!gate.success)return JSON.stringify(gate);
      const requestPath=%s,x=new XMLHttpRequest();
      try{x.open('GET',requestPath,false);x.withCredentials=true;x.send();}
      catch(e){return JSON.stringify({success:false,reason:'request_failed'});}
      return JSON.stringify({success:x.status===200,http_status:x.status,source_url:location.href,
        request_path:requestPath,body:x.status===200?x.responseText:null});
    })()""" % (gate, json.dumps(request_path))


def history_gate_expression(uid, selectors):
    """A timeline request needs a target feed and login gate, not every card selector."""
    required = {'root', 'logged_in', 'logged_out'}
    if not required <= selectors.keys() or any(not isinstance(selectors[key], str) or not selectors[key].strip() for key in required):
        raise ValueError('先核验目标微博流 root、logged_in、logged_out；可带 blocked/end_marker')
    if selectors['root'].strip().lower() in {'body', 'html', '*'}:
        raise ValueError('root须为目标微博流，不使用全页选择器')
    return """(()=>{
      const uid=%s,s=%s,visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
      if(!['https://weibo.com','https://www.weibo.com'].includes(location.origin))return JSON.stringify({success:false,reason:'desktop_required'});
      if(!['/u/'+uid,'/'+uid].includes(location.pathname.replace(/\\/$/,'')))return JSON.stringify({success:false,reason:'wrong_target'});
      if(!visible(document.querySelector(s.logged_in))||visible(document.querySelector(s.logged_out)))return JSON.stringify({success:false,reason:'login_required'});
      if(s.blocked&&visible(document.querySelector(s.blocked)))return JSON.stringify({success:false,reason:'site_verification_required'});
      const roots=document.querySelectorAll(s.root);if(roots.length!==1||!visible(roots[0]))return JSON.stringify({success:false,reason:'feed_not_unique'});
      return JSON.stringify({success:true,source_url:location.href,
        end_visible:!!(s.end_marker&&visible(document.querySelector(s.end_marker)))});
    })()""" % (json.dumps(uid), json.dumps(selectors))


def timeline_payload(value, uid, request_path):
    """Decode in Python, reject precision loss, and never cache error/login bodies."""
    if isinstance(value, str): value = json.loads(value)
    if not isinstance(value, dict) or value.get("success") is not True:
        return None, (value.get("reason") or "HTTP " + str(value.get("http_status"))) if isinstance(value, dict) else "invalid_response"
    from user_profile import desktop_url
    if not desktop_url(value.get("source_url", ""), uid) or value.get("request_path") != request_path or value.get("http_status") != 200:
        return None, "wrong_target_or_request"
    if not isinstance(value.get("body"), str):
        return None, "raw_response_required"
    try:
        payload = json.loads(value["body"])
    except (ValueError, TypeError):
        return None, "invalid_json_or_login"
    if not isinstance(payload, dict):
        return None, "business_error_or_verification"
    if "ok" in payload and (type(payload["ok"]) is not int or payload["ok"] != 1):
        return None, "business_error_or_verification"
    if payload.get("error") or payload.get("error_code") or payload.get("status") in {"error", "failed", "fail"}:
        return None, "business_error_or_verification"
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        return None, "invalid_timeline"
    if "ok" not in payload and "since_id" not in data:
        return None, "invalid_timeline"
    cursor = data.get("since_id")
    if type(cursor) is int: cursor = str(cursor)
    if cursor is not None and not isinstance(cursor, str):
        return None, "cursor_precision_unknown"
    data["since_id"] = cursor
    for row in data["list"]:
        if not isinstance(row, dict): return None, "invalid_record"
        rid = row.get("idstr") or row.get("id")
        if type(rid) is int: rid = str(rid)
        if not isinstance(rid, str) or not rid.isdigit(): return None, "id_precision_unknown"
        row["idstr"] = rid
    return payload, None


# --- m.weibo.cn container feed: page is directly addressable, so boundaries can be bisected ---

MOBILE_FEED_PREFIX = "107603"


def mobile_url(url, uid=None):
    p = urlsplit(url)
    valid = p.scheme == "https" and p.hostname == "m.weibo.cn" and not p.username and not p.password and p.port in (None, 443)
    if not valid:
        return False
    return uid is None or p.path.rstrip("/") in {"/u/" + uid, "/profile/" + uid}


def mobile_container_path(uid, page):
    """Construct the observed m.weibo.cn user-feed container route; page needs no cursor chain."""
    if not (isinstance(uid, str) and uid.isdigit()):
        raise ValueError("UID 必须是真实数字字符串")
    if type(page) is not int or page < 1:
        raise ValueError("page 为正整数")
    query = urlencode([
        ("type", "uid"),
        ("value", uid),
        ("containerid", MOBILE_FEED_PREFIX + uid),
        ("page", str(page)),
    ])
    return "/api/container/getIndex?" + query


def mobile_gate_expression(uid, request_path):
    """Same-origin synchronous XHR on m.weibo.cn; return responseText to keep IDs out of JS Number."""
    return """(()=>{
      const uid=%s,requestPath=%s;
      if(location.origin!=='https://m.weibo.cn')return JSON.stringify({success:false,reason:'mobile_required'});
      if(!new RegExp('^/(u|profile)/'+uid+'(/|$)').test(location.pathname))return JSON.stringify({success:false,reason:'wrong_target'});
      const x=new XMLHttpRequest();
      try{x.open('GET',requestPath,false);x.withCredentials=true;x.send();}
      catch(e){return JSON.stringify({success:false,reason:'request_failed'});}
      return JSON.stringify({success:x.status===200,http_status:x.status,source_url:location.href,
        request_path:requestPath,body:x.status===200?x.responseText:null});
    })()""" % (json.dumps(uid), json.dumps(request_path))


def mobile_original_url(pic):
    """Only actual returned original URLs; never construct a guessed CDN path."""
    for value in (pic.get('original_pic'), pic.get('largest'), pic.get('original')):
        if isinstance(value, dict): value = value.get('url')
        if isinstance(value, str) and urlsplit(value).scheme in {'https', 'http'}:
            return value
    return None


def mobile_payload(value, uid, request_path):
    """Decode one m.weibo.cn page: real mblogs plus card_type=58 boundary notices."""
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or value.get("success") is not True:
        return None, None, (value.get("reason") or "HTTP " + str(value.get("http_status"))) if isinstance(value, dict) else "invalid_response"
    if not mobile_url(value.get("source_url", ""), uid) or value.get("request_path") != request_path or value.get("http_status") != 200:
        return None, None, "wrong_target_or_request"
    if not isinstance(value.get("body"), str):
        return None, None, "raw_response_required"
    try:
        payload = json.loads(value["body"])
    except (ValueError, TypeError):
        return None, None, "invalid_json"
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        return None, None, "invalid_container"
    mblogs, notices = [], []

    def collect(cards):
        for card in cards:
            if card.get("card_type") == 58 and card.get("name"):
                notices.append(card.get("name"))
            if card.get("mblog"):
                mblogs.append(card["mblog"])
            collect(card.get("card_group") or [])

    collect(data["cards"])
    # Pre-normalize: keep IDs as strings and attach true original URLs without guessing CDN.
    for mblog in mblogs:
        user = mblog.get("user")
        if isinstance(user, dict) and user.get("idstr") is None and user.get("id") is not None:
            user["idstr"] = str(user["id"])
        pics = mblog.get("pics") or []
        if isinstance(pics, dict):
            pics = list(pics.values())
        # Filter out non-dict entries (e.g. empty-string keys in dict-style pics)
        pics = [p for p in pics if isinstance(p, dict)]
        mblog["pics"] = pics
        for pic in pics:
            if isinstance(pic, dict) and not pic.get("original_pic"):
                pic["original_pic"] = mobile_original_url(pic)
    return mblogs, notices, None
