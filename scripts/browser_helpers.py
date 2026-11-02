"""Import inside the host's browser tool. No browser credentials or fixed MCP names."""
import json
from urllib.parse import urlsplit

from archive_common import identifier, load, save, timestamp


def detail_expression(selectors):
    """Selectors must be verified on ONE normal detail page before batching."""
    if (not isinstance(selectors, dict) or set(selectors) != {"article", "author", "text", "images", "time"}
            or any(not isinstance(s, str) or not s.strip() for s in selectors.values())):
        raise ValueError("需要 article/author/text/images/time 五个已核验的选择器")
    return """(()=>{
      const s=%s, roots=document.querySelectorAll(s.article);
      if(roots.length!==1)return JSON.stringify({error:'article_not_unique'});
      const root=roots[0],author=root.querySelector(s.author),text=root.querySelector(s.text),time=root.querySelector(s.time);
      if(!author||!text)return JSON.stringify({error:'missing_author_or_text'});
      return JSON.stringify({url:location.href,author_url:author.href,text:text.innerText,
        time:time?(time.dateTime||time.getAttribute('title')||time.textContent):null,
        images:Array.from(root.querySelectorAll(s.images)).map(i=>i.currentSrc||i.src).filter(Boolean)});
    })()""" % json.dumps(selectors, ensure_ascii=False)


def capture_detail(bu, record_id, author_uid, created_at, selectors):
    """Read a scoped article. The caller navigates and verifies original status first."""
    identifier(record_id)
    identifier(author_uid)
    created_at = timestamp(created_at)
    value = bu.js(detail_expression(selectors))
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as error:
        raise ValueError("详情读取未返回可解析的同步 JSON") from error
    if not isinstance(value, dict) or value.get("error"):
        raise ValueError("详情 DOM 已变化；保存诊断并重新核验一次，不继续批量")
    url = urlsplit(value.get("url", ""))
    if not _platform_url(url) or url.path.rstrip("/") not in {
            "/detail/" + record_id, "/status/" + record_id, "/" + record_id,
            "/" + author_uid + "/" + record_id}:
        raise ValueError("当前详情 URL 与目标记录不符")
    author = urlsplit(value.get("author_url", ""))
    author_path = author.path.rstrip("/")
    if not _platform_url(author) or author_path not in {"/u/" + author_uid, "/" + author_uid}:
        raise ValueError("文章作者未核验，不用登录账号代替目标作者")
    if not isinstance(value.get("text"), str) or not isinstance(value.get("images"), list):
        raise ValueError("详情正文或图片列表结构不正确")
    images, seen = [], set()
    from manage_media import validate_url
    for image_url in value["images"]:
        try:
            if not isinstance(image_url, str):
                raise ValueError("图片 URL 必须是字符串")
            validate_url(image_url)
        except ValueError:
            continue
        if image_url not in seen:
            seen.add(image_url)
            images.append({"origin": "platform", "source_url": image_url, "thumb_url": image_url,
                           "large_url": image_url, "thumb_path": None, "large_path": None,
                           "download_status": "unavailable"})
    return {"id": record_id, "author_uid": author_uid, "is_original": True,
            "created_at": created_at, "text": value["text"], "text_status": "complete",
            "url": value["url"], "images": images}


def _platform_url(url):
    return (url.scheme == "https" and not url.username and not url.password
            and url.hostname in {"m.weibo.cn", "weibo.com", "www.weibo.com"}
            and url.port in (None, 443))


class RouteBudget:
    """Track independent list/detail/image capabilities across fresh tool processes."""
    def __init__(self, state=None, limit=2, *, state_path=None):
        if type(limit) is not int or limit < 1:
            raise ValueError("失败上限必须为正整数")
        if state is not None and state_path is not None:
            raise ValueError("内存状态与断点文件只选其一")
        self.state_path, self.limit = state_path, limit
        self.state = load(state_path, {}) if state_path is not None else state if state is not None else {}
        if not isinstance(self.state, dict) or any(
                not isinstance(route, dict) or type(route.get("failures")) is not int
                or route["failures"] < 0 or route.get("status", "ready") not in
                {"ready", "verify_once", "fallback", "handoff"} for route in self.state.values()):
            raise ValueError("路线断点格式不正确，不重置已有失败记录")

    def record(self, capability, success, reason="", blocked=False, http_status=None):
        route = self.state.setdefault(capability, {"failures": 0})
        if not reason and http_status is not None:
            reason = "HTTP " + str(http_status)
        route.update(reason=reason)
        route["failures"] = 0 if success else route["failures"] + 1
        blocked = blocked or http_status in {401, 403, 429, 432}
        route["status"] = "handoff" if blocked else "ready" if success else "fallback" if route["failures"] >= self.limit else "verify_once"
        self._save()
        return route["status"]

    def run(self, capability, action, *, validate=None):
        """Execute once. Optional validate(value) returns record() keyword arguments."""
        route = self.state.get(capability, {})
        status = route.get("status") or ("fallback" if route.get("failures", 0) >= self.limit else "ready")
        if status in {"fallback", "handoff"}:
            return {"status": status, "value": None, "reason": route.get("reason", "")}
        try:
            value = action()
            observation = {"success": True} if validate is None else validate(value)
            if not isinstance(observation, dict) or type(observation.get("success")) is not bool:
                raise ValueError("业务校验必须返回包含 success 布尔值的状态字典")
        except Exception as error:
            code = getattr(error, "code", None)
            # Keep diagnostics free of response bodies, URLs and browser credentials.
            reason = type(error).__name__ + (" HTTP " + str(code) if type(code) is int else "")
            status = self.record(capability, False, reason, http_status=code if type(code) is int else None)
            return {"status": status, "value": None, "reason": reason}
        status = self.record(capability, **observation)
        return {"status": status, "value": value if status == "ready" else None,
                "reason": self.state[capability]["reason"]}

    def resume(self, capability):
        """Call only after normal-page verification or user takeover has resolved the failure."""
        self.state.pop(capability, None)
        self._save()

    def _save(self):
        if self.state_path is not None:
            save(self.state_path, self.state)
