# 已登录网页端微博采集

## 开始与登录

采集前先检索并Read当前Harness中computer_use和browser_use相关Skill；存在的两类都读，工具签名、接管方式、运行机器以实际定义为准。先打开https://weibo.com网页端，未登录时通过当前控制工具对应的用户接管入口请求登录，等待用户完成并正常回读登录状态。已登录就核验后继续；不能拿没有登录按钮当成功，也不让用户提供Cookie、密码、Token或手写JSON。

从目标主页核验真实UID，登录者不代替采集目标。读取名称、头像、粉丝、关注、转评赞的当前页面显示；保存到meta.profile，见[主页资料](profile.md)。资料只读，未知null，不用所采微博的点赞/条数推主页统计。

## 已登录页面内分页优先

使用已登录浏览器中的weibo.com正常页面。先在目标主页观察正常网页加载请求，或无网络面板时用本Skill已验证的唯一路径先单页核验；核对目标UID、data.list、since_id与真实日期，再调用configure_history/collect_history（见流水线）。预制适配器仅调用已观察的同源相对列表路径，不导出Cookie，不转shell匿名请求，不逆向站点bundle。需要按page直接跳深页、或网页端游标无法覆盖完整时间范围时，改用移动站深度采集（见下节）；离线缓存仍可导入。

Trace2报告正常列表使用feature=0；feature=1的原创含义未经验证，不能猜。分页读取全部后按真实作者与retweeted_status本地排除转发；原创视频仅用户显式选择collection.include_video_covers时保留，单独取封面。正文、照片、视频分别核验；先判日期再保留区间内素材索引，下载在精选后执行。旧置顶不参与历史边界，不能只因首页出现早年微博就停。实返缺置顶标志时首页异常前缀保留候选，记录order_exceptions并继续正常游标；用verify_history_pins在正常页面读取真实置顶卡片原帖链接后核验。verify_order表示边界到了但排序异常未核验，不虚标complete。

doubao的部分bu.js只接受同步结果。适配器使用页面内同步XHR返回responseText，不用Promise/fetch、不设置同步responseType；凭据仅由浏览器自动携带。Python解析JSON保留长ID/游标精度，每页先原子保存原始正文数据与下一游标，再导入去重。每批默认3页/20秒，最多5页/60秒，批次内遵守持久速率并按剩余时长提前返回；跨工具调用直接续跑，不让Agent手写85页循环。

仅当单页接口验证不通过时用DOM备选：先核验selectors再configure_desktop/collect_snapshot，一次附近可见≤25条。宿主一次正常滚动/日期切换后采一次，虚拟列表反复重复时应报告该路线不推进，不能从近期几十条直接称十年完整。正常日期定位可辅助分窗，关键词搜索不是全量。

## 移动站深度采集与二分

移动站`https://m.weibo.cn/api/container/getIndex`（containerid=`107603<uid>`）的page参数可直接跳页、不依赖游标链，适合探测账号可访问边界并高效覆盖完整时间范围。先在已登录浏览器打开移动站目标主页`/u/UID`，运行configure_mobile核验同源页面并初始化mobile-state.json，再用probe_mobile_boundary二分探测，最后collect_mobile分批采集。

probe_mobile_boundary用标准二分查找最后一个非空页：先确认page=1有效、high_page为空，再对页码二分，仅约log2(high_page)次请求即可定位边界。card_type=58是平台声明的边界卡片，其name含“半年”即博主设置了仅展示半年内微博，此时half_year_visible=true，只收集可访问的半年数据，不试图突破；无58卡片、仅空cards则表示已到账号最早微博。边界结果写回mobile-state.json，采集到达last_page或收到58卡片即complete。

移动站主体为card_type=9（mblog），部分账号用card_group嵌套，解析器会递归处理；card_type=156为推荐卡、忽略。注意部分账号mblog的pics是字典（键为"0""1"…）而非数组，直接遍历会取到键名，weibo_web.py已用`isinstance(pics,dict)`判断并转成`list(pics.values())`，改解析逻辑时务必保留此兼容。mblog的pics每项含pid；原图只取实际original_pic/largest等返回入口，不用pid拼接或猜CDN路径。移动站同样遵守保守串行（间隔≥4秒）、cooldown与handoff断点，不绕过可见范围；可访问范围以实测边界为准，交付时如实说明覆盖起止。

桌面端`/ajax/statuses/mymblog?feature=0`在部分账号返回的是混合feed（掺杂推荐/非本人内容），并非纯个人时间线，不能据此采集；遇到此情况直接走移动站getIndex方案，不要在桌面端反复过滤混合内容。

## 节奏、阻挡与身份

历史分页保存history-state.json、history-collection.json与history-pages/逐页证据；DOM保存desktop-state.json。未到时间返回cooldown；登录失效、可见验证、HTTP401/403/429/432或持续失败锁定handoff。用户完成登录/验证并正常回读后调用对应resume函数；不因时间过去、重启工具或删状态解除。保持原断点，不换身份/请求头绕过阻挡。保守节奏不保证免风控，登录也不证明所有历史可访问。

ID必须来自真实mid或正常原帖永久链接，可用公开base62转换；不把文字/日期hash当微博ID、不造详情链接。完整年份时间读实际tooltip/原帖；只有明确相对时间才按观察时刻换算，不把所有MM-DD补成当前年。缺ID/完整时间进pending-observations，正常点开原帖后用resolve_observations补齐，未识别项不是空记录。

## 模式、精选和覆盖

沿用已确定范围/模式；未知时只问一次完整或精选。默认北京时间执行日前滚动十年，可能跨11自然年份。精选默认每年约30条、月上限5以分散日期；可按用户选择调至每年20—50或完整模式；Agent阅读实际记录评理由，脚本做配额/去重。兼顾持续爱好、变化和普通日常，不只关键词、高赞或随机抽样，不为凑数补造。

读取停住、连续空页、固定页数、接口total或近年样本都不证明十年完整。完整游标链、普通记录时间单调性与连续跨越start的批次支持已访问历史范围；异常、缺时间、重复游标或排序不可信时暂停边界判定，空页/无cursor需额外正常页核验。按证据登记逐月覆盖，可访问数据覆盖不代表平台隐藏/删除内容。不可访问/未读区间未知，不能把十年擅自缩到近半年后称完成。范围与限制在交付回复说明一次，观众页面仅保留简洁实际范围和精选标识，不铺调试说明。

## 原图与截图

为入选记录补完整文字和全部图；通过正常原帖/图片查看器读取真实原图入口，保存original_url/original_path及实际尺寸，不猜CDN路径或把列表9图当全部。没有原图入口保留实际可得版本和状态，禁止用生成图、场景裁片、头像或帖子截图替代微博配图。

下载用manage_media串行、缓存、预算与HTTP阻挡停止；默认Referer网页端。生成场景/结尾图只在decorations，真实配图在records.images。截图单独登记screenshot，需实际浏览器捕获与读图核验，不能冒充原图。

微博图片CDN按路径前缀区分尺寸：wap180/wap360为缩略图，orj960/orj1080为中等图，`large/`前缀（即pic_infos的largest字段）才是平台原图，去掉前缀的裸URL会404。original_url须取largest，无法获得原图时再退回orj960。构建时记录卡片默认引用original_path（原图），large_path次之，缩略图仅作最终回退，不在Web列表里用缩略图拉伸导致发虚；原图分辨率以平台实返为准，不做超分或猜CDN。

视频封面优先取真实返回media_info.big_pic_info.pic_big.url，其次page_info.page_pic；各种尺寸URL必须来自实返字段，不猜CDN路径。缓存到records.video.covers，并标明封面而非照片。第三方不可达时保留正文/视频记录及失败原因，不能为凑齐下载成功数悄悄替换历史素材。封面为空与没有视频不同。

历史页单条时间缺失/无效时不丢整页：保存raw与pending断点，用正常详情读取同一ID/作者/完整时间/捕获时间，经resolve_history_observations登记独立证据后重放缓存副本继续。此入口不能修改已有效日期、换作者/ID、改raw或解除限流阻挡。
