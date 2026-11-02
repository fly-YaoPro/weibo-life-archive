# 完整资源索引

所有文件均随Skill发布，不依赖本机临时目录。按任务阶段读取MD，确定性环节优先直接执行Script。

## Markdown

| 文件 | 用途 |
| --- | --- |
| [acceptance.md](acceptance.md) | 数据与浏览器功能验收 |
| [case-effects.md](case-effects.md) | 实际查看项目参考图的方法 |
| [collection.md](collection.md) | 微博权限、原创过滤、覆盖与续采 |
| [doubao-reliability.md](doubao-reliability.md) | 真实成功Trace的方法、全文/置顶/封面/模板卡点与效率 |
| [data-contract.md](data-contract.md) | 数据、素材、封面和离线HTML约定 |
| [editorial.md](editorial.md) | 事实、叙事、引用与画像边界 |
| [experience.md](experience.md) | 首屏、封面、年历与来信完整体验 |
| [harness-doubao.md](harness-doubao.md) | 实际浏览器工具能力与宿主注意事项 |
| [homepage.md](homepage.md) | 全屏寻物首页、浮动提示和小记交互 |
| [image-direction.md](image-direction.md) | 场景与结尾图生成构图及无人物约束 |
| [immersive-design.md](immersive-design.md) | immersive-design |
| [implementation.md](implementation.md) | story字段与预制前端实现 |
| [motion-design.md](motion-design.md) | 柔性双面翻页、入册音效与滚动渐入 |
| [music.md](music.md) | 真实配乐、原创默认和许可曲库路线 |
| [pipeline.md](pipeline.md) | 初始化、导入、精选、下载与构建命令 |
| [profile.md](profile.md) | 网页端用户资料、原头像和统计精度 |
| [share-image.md](share-image.md) | 1080宽动态分享长图 |
| [style-frosted.md](style-frosted.md) | 磨砂示例的通透与黄橙高亮 |
| [style-paper.md](style-paper.md) | 纸本示例的珊瑚红与相纸 |
| [style-system.md](style-system.md) | 纸本/磨砂两套风格共用结构 |
| [usage.md](usage.md) | 用户调用示例 |
| [visual-acceptance.md](visual-acceptance.md) | 实际打开HTML、对照截图、修正差距 |
| [resources.md](resources.md) | 本索引 |

## Script

| 文件 | 职责 |
| --- | --- |
| [audit_images.py](../scripts/audit_images.py) | 源配图清单、数量、文件与规格硬性检查 |
| [test_fusion.py](../scripts/test_fusion.py) | 融合后默认策略、续采断点与无损图片回归 |
| [check_plans.py](../scripts/check_plans.py) | 离线真实浏览器计划编辑、导入、删除与恢复 |
| [archive_common.py](../scripts/archive_common.py) | 时间、路径、ID、文件与HTML清理公共函数 |
| [archive_pipeline.py](../scripts/archive_pipeline.py) | 去重、配额、物化及统计 |
| [browser_check.py](../scripts/browser_check.py) | 实际浏览器功能与音效时序 |
| [browser_helpers.py](../scripts/browser_helpers.py) | 详情读取与失败路线断点 |
| [build_journal.py](../scripts/build_journal.py) | 校验来源并组装两套离线前端 |
| [check_homepage.py](../scripts/check_homepage.py) | 全屏构图、单行引导、原图热点、目录找物与轻交互 |
| [check_flip.py](../scripts/check_flip.py) | 正反翻页、连点、遮挡与落页像素检查 |
| [check_project.py](../scripts/check_project.py) | 数据与独立HTML静态检查 |
| [check_responsive.py](../scripts/check_responsive.py) | 窄屏/中宽屏逐页内容完整性 |
| [check_share.py](../scripts/check_share.py) | 六段结构、原图归属、滚动预览与复制反馈 |
| [check_story.py](../scripts/check_story.py) | story.json的source_ids/image_paths批量一致性检查，一次返回全部异常 |
| [check_styles.py](../scripts/check_styles.py) | 双风格差异及同源内容一致 |
| [collect_weibo.py](../scripts/collect_weibo.py) | 已登录页面内历史分页、游标证据、批次预算、阻挡与DOM备用 |
| [experience.py](../scripts/experience.py) | 原文/视觉锚点、叙事去重、首屏/来信/音乐契约 |
| [runtime_contract.py](../scripts/runtime_contract.py) | 共享source/build/单文件身份、媒体、叙事与体验验证 |
| [test_check_share.py](../scripts/test_check_share.py) | 昵称原始空格和视频封面来源验证 |
| [test_runtime_contract.py](../scripts/test_runtime_contract.py) | 单HTML身份/日期/视频/图源/体验变异拒绝回归 |
| [manage_media.py](../scripts/manage_media.py) | 图下载/缓存/预算/截图登记 |
| [pack_html.py](../scripts/pack_html.py) | 内嵌一次媒体和代码，产出完整HTML |
| [preflight.py](../scripts/preflight.py) | 安装完整性 |
| [prepare_art_direction.py](../scripts/prepare_art_direction.py) | 有据物件映射、固定水彩彩铅风格提示词，离线不生图 |
| [test_art_direction.py](../scripts/test_art_direction.py) | 提示词来源与首尾风格回归 |
| [test_collect_history.py](../scripts/test_collect_history.py) | 多页断点、日期边界、HTTP阻挡、大整数与视频封面 |
| [test_narrative.py](../scripts/test_narrative.py) | 重复/无据叙事、意象映射与最终HTML变异回归 |
| [make_synthetic_fixture.py](../scripts/make_synthetic_fixture.py) | 显式合成夹具，用于离线功能回归，不作真实采集证明 |
| [prepare_music.py](../scripts/prepare_music.py) | 原创配乐或明确选择的许可曲库 |
| [test_build_journal.py](../scripts/test_build_journal.py) | 合成数据回归测试 |
| [test_check_project.py](../scripts/test_check_project.py) | 合成数据回归测试 |
| [test_framework.cjs](../scripts/test_framework.cjs) | 合成数据回归测试 |
| [test_pipeline.py](../scripts/test_pipeline.py) | 合成数据回归测试 |
| [test_reliability.py](../scripts/test_reliability.py) | 合成数据回归测试 |
| [user_profile.py](../scripts/user_profile.py) | 主页名称/头像/统计读取与精度/归属校验 |
| [weibo_web.py](../scripts/weibo_web.py) | 网页DOM快照、真实永久链接ID与完整时间 |
| [test_weibo_web.py](../scripts/test_weibo_web.py) | 网页身份/日期/资料与阻挡回归 |
| [visual_review.py](../scripts/visual_review.py) | 真实截图、翻页正/背帧与并排对照 |

## 预制资源

- assets/starter：index、core/app、reader、motion、experience、share、plans、fusion.css、paper/frosted样式及favicon；由build_journal与pack_html一起输出，不能只复制部分CSS/JS。
- assets/cases与assets/provenance.json：虚构的原始风格参考，不作用户证据照片。
- assets/scene-composition.json：生成工具无关的场景美术与构图安全区。
- [assets/art-direction.json](../assets/art-direction.json)：Trace1水彩彩铅纸纹/窗光风格锁、负向要求、首尾构图与读图验收。
- assets/music-catalog.json：已核验许可目录；默认仍为原创音频。

个人项目的JSON、HTML、录音下载、用户附件GIF和验证截图保留工作区，不作为Skill模板资料上传。动作规律与有用验证逻辑已转到上述MD/Script。
