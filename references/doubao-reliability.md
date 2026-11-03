# 故障与旧数据兼容

只在当前流程失败、恢复旧项目或维护适配时读取。正常入口是[采集](collection.md)，不要先遍历所有备选接口。

## 旧断点与传输

新configure_mobile默认download；已有mobile-collection不会被覆盖，缺transport的旧配置在代码里仍回退sync_xhr。正常目标页重新核验download后，可调用set_mobile_transport(source, 'download')切换配置；它不解除已有blocked状态。阻挡需正常登录/验证后按适用恢复流程处理，没有可用恢复入口时保留断点并报告，不删blocked/页码或搬Cookie。

工具级超时后停止该路线，不反复同步XHR、API导航或等待切标签。页面文本读取可能截断JSON，应使用当前宿主正常文件下载能力并核验完整正文。模块/截图/JS调用签名以当前浏览器Skill为准；每次调用可能跨进程，游标必须落盘。

## 桌面游标或DOM备选

仅当当前download通道不可用且已核验正常桌面列表时使用configure_history/collect_history：

```python
from collect_weibo import configure_history, collect_history
print(configure_history(bu, source, feed_selectors, observed_request))
print(collect_history(bu, source, max_pages=1, deadline_seconds=20))
```

选择器和实际同源请求在目标页核验，正常feature=0数据本地过滤原创。确认data.list/since_id、作者和日期后才扩大批次；游标可带后缀，不转整数。若为混合推荐feed或同步XHR阻塞，不把它继续当默认路线。DOM备选用configure_desktop/collect_snapshot，每次仅附近≤25条；虚拟列表不推进就停止该备选，不以近期样本称十年完整。

旧置顶不参与边界判定，缺标志时保留order_exceptions并通过verify_history_pins正常页核验。verify_boundary须回读正常目标页后才有界复查或confirm_history_end，状态参数以函数定义为准。

## 日期与媒体

- 缺真实ID/完整时间的观察进入pending；原帖详情核验后用resolve_observations或resolve_history_observations补独立证据，再重放缓存。后者绑定原页SHA与同一作者/原帖，不能改已有效日期、猜年份或解除其他阻挡。
- 旧pic_big等URL对象可用manage_media repair-urls修复，保留备份和repair-log，不重抓整个账号。新版详情补图用detail_media，不以字段改名或枚举缩减充当完整。
- 配图地址优先实际响应。包内移动解析器保留经过既有适配的PID到原图地址转换；失败时回正常原图入口核验，不扩展猜测更多CDN路径或以低图冒充原图。
- 第三方视频封面由正常浏览器取得同一实际封面，读图确认后调用register_external_cover(source, source_id, local_path)。该兼容函数把文件登记到该记录的封面条目；多封面记录先核对映射，不能把一张图冒充不同封面。
- 原帖截图单独保存screenshot并通过manage_media screenshots登记，绑定同一原文URL；不作为历史配图替身。

## 测试排错

仅在用户另行要求模板调试时：折叠details内元素需展开再点击；截图等待img.complete/naturalWidth与字体ready。Playwright缺浏览器时可指定实际系统Chrome路径，缺运行库时按宿主实测，不循环下载。像素差接近阈值时结合截图/边缘差异判断，不为测试噪声改源数据。模板修复见[维护](implementation.md)，不在普通制作中重写布局。

普通制作与交付仅做[首图最小验收](scene-hotspots.md)，以上截图/Playwright排障仅供单独调试。
