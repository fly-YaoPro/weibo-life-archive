# 减少手写派生字段

用story_tools index导出当前真实ID、原文、图片索引和缺项；只在源数据变化时刷新。正文source_ids保留真实ID即可，不必写公共或逐章节evidence，也无需supports。

实际引用可用quote_span:[start,end]，按Python Unicode字符偏移从对应source_id原文截取，保留原繁简、标点、空格与换行；不要凭记忆重写原话。图片可用image_refs:[{source_id,image_index}]，所属source_id必须属于章节来源。

journal_run、独立story诊断与build.prepare共用同一编译入口；诊断不修改原文件，默认配乐尚未准备不报假错误。无需单独compile：

- scene.source_ids自动取objects来源并集。
- letter.image_source_ids取结尾objects来源并集，并并入letter.source_ids。
- 热点可用object_index指向scene.objects下标，自动填object_name、source_ids、id、label、description；仍需实际生成图上的x/y坐标。
- target可用主题ID字符串，或{theme_id:"真实主题ID"}；自动规范为{view:"review",theme_id:...}。旧{view:"theme",theme:...}也兼容。无效目标仍报错。
- 配乐由journal_run自动准备，不因尚未运行配乐准备步骤而手工补字段。

预检失败集中处理errors；长度、简繁、相似度及supports不阻塞，也不向正文硬塞词语。构建后入口自动发布，delivery_complete=true才交付；续跑--resume-run，不重复预检或打包；只补[首图最小验收](scene-hotspots.md)。
