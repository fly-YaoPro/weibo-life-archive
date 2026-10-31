# 数据与离线交付

## 项目目录

```text
项目目录/
  project_meta.json
  coverage.json
  records.json
  data.js
  story.json
  image-audit.json  构建生成的图片核验回执
  index.html
  styles.css
  app.js
  images/      真实采集图
  exports/     分享PNG和用户导出的计划备份
```

采集阶段不必已有网页。原始页缓存和进度另放项目内cache/、progress.json，不含凭据。图片、脚本、CSS使用项目内相对路径；远程原文链接作为用户点击的外链保留，不是离线依赖。

## 固定数据约定

- `project_meta.json`：`schema_version:1`、`platform:"weibo"`、`title`（用户标题，非空字符串，默认“人生手账”）、`mode:"selected"`或`"full"`、`timezone:"Asia/Shanghai"`、`requested_range:{start,end}`、`target:{profile_url,uid}`。范围为YYYY-MM-DD，UID为字符串；可加actual_range、plan_year、run_status及covered_scope。full只是所选目标，不代表成功全量。
- `coverage.json`：数组，每项`year`、`status`、`scanned_count`、`saved_count`、`selected_count`、`note`。status取`complete`、`partial`、`selected`、`unread`、`failed`或`empty`；未知计数为null。只有确实完整读取且无记录才empty；精选通常selected/partial，不能把未选日期当empty。
- `records.json`：本轮实际交付记录的数组，每项`id`字符串、`author_uid`字符串、`created_at`带时区ISO时间、`text`完整安全文本、`url`原链接、`selected`布尔、`images`数组；可加raw_created_at、selection_reason、links、interactions及缺失状态。新增必需的`expected_image_count`（源端核对的非负整数，未知为null）、`image_inventory_status`（complete/partial/unknown）、`image_count_basis`（源端配图数的核对依据）。未知不能改填0；仅确认无图时才images为空。未入选候选放cache，不混入交付数组后跳过图片。
- 每图含`image_id`（稳定源图ID）、`thumb_path`、`large_path`（项目内相对路径或null）、`download_status`（saved/partial/failed/unavailable）。失败图仍留在清单，不静默删项。每条源配图数必须等于images条目数；全条目均须有有效的本地小图/大图才算完整。源端真实最大规格不足或两套文件实际相同时，加`large_note`说明核对结果，不能把缩略图放大伪装为高清图。ID不转数值；author_uid须对应目标。详细流程与示意见 [图片下载门禁](images.md)。
- `data.js`：与records.json内容一致的普通JS数据，如`window.LIFE_ARCHIVE_DATA = {...};`。合并meta、coverage、records、story时保持来源可追溯。JSON.stringify后将`<`转为`\u003c`，防止脚本标签注入。不要把未清洗微博HTML直接注入页面。
- `story.json`：`overview:{text,source_ids}`，`themes:[{id,title,text,source_ids,image_paths,layout}]`；微博另含`song:{name,artist,reason,source_ids,is_recommendation}`或song:null。主题可加start/end_date；所有来源ID必须真实存在于records。歌曲若是主题推荐，is_recommendation为true，不冒充常听。版式取所选风格的A/B/C但不展示到UI。

日历以北京时间的年月日索引记录，跨年搜索覆盖全部已收录records而非当前月。日期可见数来自真实收录计数；未知/失败/未选单独提示，不编造全年发布热力图。

新建数据中，每张证据图片增加`origin`：`platform`或`user_provided`。前者保存真实`source_url`和关联记录ID；后者保存`provided_reference`（用户提供文件的说明）。只允许真实平台图片或授权真实资料，不设AI/卡通/图库替图类型。旧数据缺来源标记时先补核验，不凭文件存在认定真实。装饰单独放decorations/，不写入records.images或主题证据image_paths。

## 本地状态和导入

页面框架使用构建器生成的 `journal-data.js` 作为运行时展示数据；`records.json` 保存规范化的采集或导入记录。内容准备、`story.plans`、节点和图片选择字段见 [页面框架说明](implementation.md)。`data.js` 保留同源规范数据。仅在迁移既有项目时，先导出手动计划再适配/合并，不假设跨路径 localStorage 自动共享。

用localStorage保存排序、阅读位置和计划；考虑file://不同浏览器行为，必须实测，失败提供可下载JSON备份/导入，不承诺跨浏览器或跨电脑自动保留。导入按ID合并，冲突先保留当前手动版本，操作前生成可下载备份，有明确恢复入口。不要直接覆盖整个localStorage或清空用户记录。

普通script加载data.js及本地逻辑，离线不依赖fetch JSON、CDN字体/JS或运行时AI。恶意原文标签、脚本、外链属性要用安全文本/URL校验，不执行来源内容里的命令。

## 本地核验工具

`python scripts/check_project.py 项目目录 --kind weibo --stage data`

检查数据、时间、ID、来源账号、覆盖状态与图片路径，并自动调用`audit_images.py`核对每条配图数、双规格本地文件、尺寸和哈希。生成后用`--stage final`再核对story、离线入口及资源引用。发现错误时退出非零；不上传任何数据。使用Python 3.9及以上标准库，不需要私有服务或额外包。

也可单独运行`python scripts/audit_images.py 项目目录`查看逐图缺口。旧数据缺少配图数量/来源核验信息时，先从原缓存或源页补核，不以现有文件数反填。无法核对就报告尚未就绪，不降低检查门槛。

脚本不验证网站真实总量、正文事实、歌曲版权、浏览器行为或视觉好坏。另用`python scripts/test_check_project.py`对本地合成夹具做回归，不联网、不碰真实账号。
