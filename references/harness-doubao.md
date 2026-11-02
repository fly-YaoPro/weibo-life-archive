# 豆包可选宿主适配

仅在豆包环境读取；通用Skill不依赖本文件里的特定模块。

## 能力与环境

先读取宿主已安装浏览器 Skill 和当前工具定义。local-pc常见使用 `computer_use_tool`、`plane="bu"`、`import seed_browser_use as bu`；其他宿主可能是 `aha_browser_use`。不要固定模块名，传结构化参数，不把对象再次字符串化。截图、滚动、点击签名均按当前定义；Trace 的 `screenshot(with_cursor=False)` 不受支持。页面更新后重新 snapshot，不能复用旧 ref。

每次浏览器调用可能启动新Python进程。Skill脚本和项目输入必须在**浏览器执行所在机器**可读取；先核对存在性，不把服务器路径交给local-pc。将当前真实Skill/scripts路径加入sys.path，复用脚本；状态存在JSON文件，不依赖Python全局变量。

## 网页端、登录与脚本

首次导航/采集之前读取当前Harness的computer_use、browser_use相关Skill（当前存在的两类都读取）。打开微博网页端；未登录用实际宿主接管能力唤起用户登录，等待完成后回读。接管参数按所用控制工具与操作系统，不能把浏览器操作填成别的控制类型。登录已验证不重复请求；不从本机shell恢复Cookie或搬登录态。

以已登录weibo.com目标页为入口。观察正常列表加载的实际请求及一页返回（无网络面板能力时可用本Skill已核验路径先单页验证），核验UID/作者/日期/游标；使用相对同源请求，当前已知适配路径为/ajax/statuses/mymblog。不要猜feature=1含义，正常feature=0数据本地过滤转发。传给浏览器机器上的脚本：

```python
import sys
sys.path.insert(0, "当前机器实际Skill/scripts路径")
from user_profile import capture_profile
from collect_weibo import configure_history, collect_history
# bu来自当前Harness；选择器和observed_request均从正常目标页实际观察。
print(capture_profile(bu, "实际source路径", profile_selectors))
print(configure_history(bu, "实际source路径", feed_selectors, observed_request))
print(collect_history(bu, "实际source路径", max_pages=3, deadline_seconds=20))
```

configure_history只需要已核验的root/logged_in/logged_out页面状态选择器（可带blocked/end_marker），不要求抓卡片或原创筛选选择器，observed_request使用正常页实际加载的相对路径；没有网络读取能力时可先用本Skill已核验的唯一路径做max_pages=1验证，再续批次。路径，含目标uid、page=1、feature=0及已观察count。配置不覆盖已有断点。collect_history默认每批3页/20秒，最多5页/60秒，返回同步JSON；重复调用读取history-state.json继续，不依赖Python全局变量。内部一次请求使用同步XHR的responseText，Python解析长ID，不用async/await+fetch或设置responseType。Trace中的http_get不带页面登录态导致403，不据此反复试外部请求。

每次看实际status/next_allowed_at/页数与日期进展，遵从cooldown；verify_order由Agent核验正常页置顶选择器，再verify_history_pins读取实际链接，不要求用户填写JSON；handoff由用户验证后正常回读，再resume_history_after_verification，保留原游标。verify_boundary回读正常目标页后最多retry_boundary=True单页复查一次；真实可见end_marker才confirm_history_end，不猜范围。20秒预算在请求间检查，同步XHR自身需当前宿主工具超时控制。若接口单页不通可使用configure_desktop/collect_snapshot的可见DOM备选，每次正常滚动后一个≤25条快照；虚拟列表不推进就记录限制，不能手写几十次滚动后把近期样本当全量。

DOM缺真实永久链接或完整时间时保存pending，正常点时间/详情后resolve_observations补齐；历史页缺完整created_at时按pipeline用resolve_history_observations登记同一原帖完整时间证据并重放，原raw与SHA保持不变。432、request_failed、DOM停住、旧置顶和一个空页都不证明历史终点；不读取Vue私有状态或逆向bundle，不造hash ID。接口路径只作为当前有证据的适配器，实际站点变动须单页重新核验，不能盲目追加备用接口。浏览器动作和字段按实际工具/正常页定义，不固定站点CSS类或模块名。

## 制作及交付

图片生成使用目标Harness实际提供的专用工具。先发现并读取该工具定义及相关Skill，再按实际模型与用户选择提供参数；工具名称、参数键、模型枚举和返回结构都不能硬编码。本机CLI/Endpoint缺失不代表目标Harness没有生成能力，不要求Agent安装arkcli、创建ep或切换凭据来替代已有专用工具。使用真实返回的完成产物路径/URL，不猜下载地址。

音乐和打包可用普通Python在local-pc执行，不依赖浏览器登录态。最终通过 `present_files` 或实际宿主文件入口提交最新完整HTML文件；完整离线目录保留，可加单HTML；实际文件入口以宿主能力为准，不含登录态。分享PNG是用户在HTML中主动导出的功能，验收文件留本地。

Trace2中的headless虚拟时间截图曾漏显示图片；使用实际浏览器等待img.complete且naturalWidth>0、字体ready后截图，不仅靠--virtual-time-budget。启用scene时入册须真实点击并检查2秒后的首页内容，不只直接访问#review；页面属性fit=ready不能证明介绍没有被拆走。所有路径以当前执行机器为准，不能复制Trace中的macOS用户名或会话路径。
