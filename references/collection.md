# 当前采集流程

适用于正常浏览器登录态。工具调用在浏览器所在机器执行，模块和签名以当前宿主浏览器Skill为准；不要为了采集提取Cookie或令牌。新项目采用下面的自动资料读取和移动站download路径，桌面游标/同步XHR/DOM仅在备选条件满足时使用。

## 1 初始化与目标资料

先用[流水线](pipeline.md)初始化项目，在正常weibo.com目标主页核验UID与登录。示例假定bu为已加载的宿主浏览器模块，source为实际项目路径：

```python
from user_profile import capture_profile_auto
print(capture_profile_auto(bu, source))
```

成功保存meta.profile后下载头像；字段语义见[主页资料](profile.md)。返回profile_not_unique/profile_fields_missing等状态时正常回读目标资料卡，必要时用capture_profile(bu, source, selectors)显式备选。不要反复尝试宽泛的全页选择器。

## 2 下载传输与续跑

按当前工具定义打开已登录的m.weibo.cn/u/UID目标页，再调用：

```python
from collect_weibo import configure_mobile, collect_mobile
print(configure_mobile(bu, source, transport='download'))
print(collect_mobile(bu, source, max_pages=1, deadline_seconds=30))
```

核对首批实际目标作者、长整数ID、完整日期和候选数，再按相同断点扩大到有界批次。每个浏览器工具调用只运行一次collect_mobile，建议max_pages=30、deadline_seconds=60；禁止在同一调用外套3—6批循环超过宿主总时限。max_pages为1—50、deadline_seconds为1—120，具体预算要适合当前Harness；列表串行，默认间隔2秒；configure_mobile的minimum_interval接受非负有限秒数，可按实际响应配置。已有断点配置保持原间隔，需调整时只改mobile-collection.json的minimum_interval，不删游标；失败保留45秒退避和验证停机。BU负责下载完整API JSON，脚本核验后缓存、解析、入库；无需Agent逐页导航或回传整页JSON。

每批读取status、next_page、candidate_count、cache_hits、boundary和last_pages；末两页的ordinary_oldest/ordinary_newest剔除置顶，用于判断连续普通记录是否跨过请求起点。ready继续；busy表示上一调用仍运行，等待后读取断点，不发重叠任务；cooldown按next_allowed_at等待；verify_once只做一次正常核验；handoff先处理登录/验证或工具阻挡，保留断点。工具级超时一次即停止当前路线，不能用加大预算、切标签和重复同步XHR无限试错。

mobile-collection.json保存目标和传输，mobile-state.json保存页码/速率，mobile-pages保存原始页，mobile-transport.json保存接收证据。缓存命中不重发网络请求。每页结束原子保存进度；进程锁会随进程退出释放，不需删除锁文件。混合页中的非目标作者卡片只在派生入库时过滤，页记录列出skipped_foreign_cards，原始JSON不改写；整页均为其他作者仍触发核验，不借此放行串号。旧配置不会被configure_mobile覆盖，传输切换与旧缓存兼容见[故障与兼容](doubao-reliability.md)。

## 3 时间范围与边界

只以实际原帖日期保留请求区间记录；置顶旧帖、接口total、某个空页不证明覆盖完整。probe_mobile_boundary(bu, source, high_page=..., deadline_seconds=...)可二分核验可访问末页，但不是每次采集的强制前置，也不会替代对区间内页面的读取。不要用近期页速猜历史总量。读到可信普通记录连续跨过requested_range.start后，可依据日期与连续页证据结束本次范围采集，保留断点；不要为了等待尾页complete继续读取整个账号的更早历史。collect_mobile的complete代表可访问尾页/边界到达，不自动证明请求区间全量。

遇到明确可见范围限制，仅保存当时可访问记录并说明；完整性以连续页证据、真实日期与正常页面终点核验，不把未读范围记成empty。缺ID/完整年份进入pending，不猜年份或造摘要hash ID。平台隐藏/删除内容不在可访问覆盖承诺内。

## 4 精选后的详情

Agent阅读候选后按真实ID评分，select/materialize后仅补入选记录。正文标记截断时补全文；图片清单未知或不足时，在浏览器执行环境调用：

```python
from detail_media import supplement_inventory
print(supplement_inventory(bu, source))
# 未知总数、需要人工确认的条目，可传已核验的入选ID列表：ids=[...]
```

自动检测覆盖源图数不足及text_status=pending的入选记录，不能证明未知图数已经完整。模块核对详情作者/ID及配图数量，保留已下载路径；详情仍标记折叠时自动请求同一ID的statuses/extend，清理HTML并保存原始响应证据；成功才更新全文状态，失败返回text_error且保留pending和已补相册。不按字数推断全文完整。正常打开m.weibo.cn/detail/真实ID、展开并核验一次选择器后，可调用supplement_text_from_page(bu, source, 真实ID, selectors, expanded=True)，只合并正文并保存详情证据，不覆盖图片清单。selectors的article/author/text/images/time定义及capture_detail由scripts/browser_helpers.py提供，按实际DOM填写。补图后重跑manage_media plan/download并检查[图片完整性](images.md)。第三方封面需正常浏览器取得同一封面、实际读图，再按[故障与兼容](doubao-reliability.md)登记。
