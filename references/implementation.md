# 制作边界与模板维护

## 普通制作

使用journal_run及assets/starter完成构建。Agent准备真实数据、叙事和素材；不为单次任务重写前端、另做简版或修改打包后的HTML。字段按[数据契约](data-contract.md)，预检失败按具体错误修复；不要改假数据掩盖模板缺陷。

页面交互、材质、长内容续页与分享排版由模板承担，普通任务不需先读前端实现。启用的故事模块与实际配图通过[成品验收](acceptance.md)核对。

## 确认是Skill缺陷时

修改Skill/模板属于维护工作：保留原版本，在源脚本或starter中最小修复，再构建到新目录；不能只改最终HTML而丢失可重建来源。按修改范围运行相应离线Python/前端回归。普通制作、维护和交付补做[首图最小验收](scene-hotspots.md)，不要求全站重型浏览器检查；[视觉调试](visual-acceptance.md)仅供用户另行要求时参考。

布局问题按需查[首页](homepage.md)、[动效](motion-design.md)、[风格](style-system.md)；宿主、旧数据与采集错误按[故障与兼容](doubao-reliability.md)。测试素材不得进入真实records，用户数据与凭据不得打进公共Skill包。

## 特定实现故障

- 图片格式/透明异常：检查manage_media的格式识别与压缩分支，EXIF转置前保存原格式；不要将透明图强制转JPEG。
- 分享canvas污染：按share.js实际加载路径检查同源、内嵌映射与blob生命周期；不能通过删除真实照片规避导出错误。

这些是代码维护线索，不是普通制作任务需逐项执行的步骤。
