# 按需资源索引

从SKILL.md进入，只读当前阶段需要的文档；无需扫描全部脚本或预读维护案例。实际参数以脚本--help/函数签名为准，包完整性由skill_manifest与preflight检查。

## 制作任务

| 阶段 | 权威入口 |
| --- | --- |
| 采集/主页 | [collection](collection.md)、[profile](profile.md)、[Doubao适配](harness-doubao.md) |
| 本地命令/编译辅助 | [pipeline](pipeline.md)、[efficiency](efficiency.md) |
| 数据字段/叙事/配图 | [data-contract](data-contract.md)、[editorial](editorial.md)、[images](images.md) |
| 首尾插画/实际参考图 | [image-direction](image-direction.md)、[case-effects](case-effects.md) |
| 音乐/分享 | [music](music.md)、[share-image](share-image.md) |
| 产品结构/风格 | [experience](experience.md)、[style-system](style-system.md)，按需[paper](style-paper.md)/[frosted](style-frosted.md) |
| 最终验收/发布 | [acceptance](acceptance.md)、[deployment](deployment.md) |
| 调用示例 | [usage](usage.md) |

## 故障或维护时再读

[doubao-reliability](doubao-reliability.md)处理旧断点、同步XHR、日期/媒体异常；[implementation](implementation.md)界定普通制作与模板维护；[homepage](homepage.md)、[motion-design](motion-design.md)、[immersive-design](immersive-design.md)和[visual-acceptance](visual-acceptance.md)用于布局/动效回归；[harness-validation](harness-validation.md)用于环境变化与性能复测。

主要执行脚本：archive_pipeline、collect_weibo、user_profile、detail_media、manage_media、story_tools、journal_run。独立诊断：check_story/check_project、audit_images、pack_html --estimate。首图交互另按[最小验收](scene-hotspots.md)核对；其余浏览器测试按需；browser_check及专项浏览器脚本仅在用户另行要求调试时使用。

assets/starter为完整前端，assets/cases为虚构设计参考；固定画风与物件构图在assets/art-direction.json/scene-composition.json，原创音源在assets/audio，来源说明在assets/provenance.json。测试脚本保留用于维护，不是每次制作的前置任务；个人项目、生成回执、缓存与验收截图不加入公共Skill。
