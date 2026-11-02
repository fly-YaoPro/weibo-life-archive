---
name: weibo-life-archive
description: 将指定微博主页的可访问原创图文整理成有真实照片、有据叙事、可点击日历和可编辑后续计划的人生手账。支持从零采集、断点续做和复用已有数据，附纸本与磨砂页面框架、离线交付及分享长图。
---

# 微博人生手账

从真实图文里找持续的兴趣、变化与普通日常，不把微博列表换个皮肤就当作人生回看。面向任何支持所需工具的 Agent；豆包适配见专用参考，不假设固定模型或宿主。

## 任务入口

- 从零制作：确认可编辑的目标主页，默认北京时间执行日前滚动十年。目标不自动等于登录者；只读取正常可访问的内容，不突破登录、验证或可见范围。
- 已有数据：先核验并复用记录、图片和覆盖报告；只补实际缺项，不重新抓取整个账号。已有手动计划、旧页面、断点和原始图片保留。
- 默认每年精选约30条，可按用户选择调到20—50条或完整归档。优先生活主线、具体变化及带图记录，也保留有价值的纯文字；月份尽量分散，不用随机抽样或高赞决定人生重要性。
- 已明确范围、模式或风格就沿用；缺少实质选择时一次问清。用户给的是整套制作任务，不逐阶段要求“继续”。

## 执行

1. 按[采集](references/collection.md)核验目标身份、正常浏览器登录态与一页数据，再按[流水线](references/pipeline.md)使用有界采集、逐页缓存、持久游标。遇验证或限流保存断点并请求用户处理，不清锁重置或换身份。宿主浏览器工具以实际文档为准；豆包才读[豆包适配](references/harness-doubao.md)。
2. 扫描后告知实际数量与覆盖，数据多时让用户选精选或完整。默认仅原创图文；视频帖封面为显式可选，不默认下载视频。先筛选再补全文、全部配图和真实大图入口。
3. 执行[图片完整性](references/images.md)：每条记录有源配图总数、清单核验依据和完整清单；全部选中记录的全部图片实际下载、解码并核对数量。缺图/未知总数不得当作完成，不能只下几张代表图。保留原始下载字节；压缩只生成展示副本，禁止自动删除未展示或未入选的原文件。
4. 按[数据契约](references/data-contract.md)和[叙事](references/editorial.md)写内容。总览不超过200字；主题约40—100字，每页回答不同问题。原话精确、照片与原帖对应，不从歌词/转述推断亲历，不编职业、年龄或心理诊断。原文与视觉锚点用于追溯，不要求生硬重复原句。
5. 先实际查看[包内参考图](references/case-effects.md)，提取构图、字体、材质与层级，使用[预制页面](references/implementation.md)构建。人物、照片和文案不得抄参考图；证据图使用真实平台图片或用户资料，AI图只作独立装饰。优先复用模板；确认是模板缺陷时允许最小修复并回归，不能靠改数据绕过错误。
6. 保持三个主板块：回看、日历、后续计划。回看有大标题、真实照片、具体片段、A/B/C主题与双面翻页；长内容自动续页，不用巨字填空。日历默认定位到有记录的日期，稀疏年份只铺有记录月份，并区分未读/未选/确无记录。
7. 从真实记录生成少量具体、可选的后续计划，写入 story.plans，带月份、依据和来源。页面支持修改、完成、增删、本地保存、导入导出和恢复；未来来信可放其上方，不能替代计划或留下空页。计划只是建议，不自动成为外部待办。
8. 记忆小屋、生成意象图、背景音乐均为可选增强，不能挡住基本交付；需要时读[体验](references/experience.md)、[图片设计](references/image-direction.md)、[音乐](references/music.md)。保留有据的歌曲推荐，与实际播放的可选BGM分开；不得擅自下载商业歌曲。
9. 按[分享](references/share-image.md)生成1080宽动态长图：与主页面一致的照片/排版，先预览再下载或复制。导出前让用户选择是否带头像/资料与原帖照片，不自动上传。没有场景、头像或来信也能导出，不要求恰好三件愿望。
10. 按[验收](references/acceptance.md)检查源数据、构建目录、独立HTML与真实浏览器交互；实际打开截图对照，结构通过不能当作语义、全量采集或审美通过。默认保留完整离线目录，可另加单HTML便携版；超体积预算不删除历史图片。
11. 交付时简短说明实际范围、模式、记录/图片数量和缺项，再按[部署](references/deployment.md)询问是否上线，推荐/预选“上线”，但须用户明确确认。豆包提供妙搭；其他 Agent 仅列实际可用方案。没有确认不上传、公开或修改权限。

## 验收与资源

在 Skill 目录执行，项目目录置于 Skill 之外：

```bash
python scripts/preflight.py
python scripts/audit_images.py /工作区/source
python scripts/check_story.py /工作区/source
python scripts/check_project.py /工作区/source --kind weibo --stage data
python scripts/build_journal.py --source /工作区/source --output /工作区/built-v1 --skin paper
python scripts/pack_html.py /工作区/built-v1 --output /工作区/delivery/人生手账-v1.html
python scripts/check_project.py /工作区/delivery/人生手账-v1.html --kind weibo --stage final
python scripts/browser_check.py /工作区/delivery/人生手账-v1.html --report-dir /工作区/checks
```

浏览器验收可用现有 Chromium，传 --browser-executable。换磨砂用 --skin frosted。需要完整资源入口时读[资源索引](references/resources.md)；遇采集卡点读[可靠性说明](references/doubao-reliability.md)。项目数据、登录态、真实照片和验收截图不进入公共 Skill 包。
