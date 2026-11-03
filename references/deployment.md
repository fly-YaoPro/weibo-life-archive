# 发布执行链

公开版授权前置：制作手账不等于同意公开上传。先确认发布平台、上传内容与可见范围；未确认时用journal_run的--build-only构建本地版本。已获得对应授权才执行下面的发布链；默认推荐上线，不替用户确认。

普通入口：`python scripts/journal_run.py --source /工作区/source --output-root /工作区/runs`。默认构建后自动发布，无需另写回执或手工探索发布方式。用户明确仅本地时设meta.presentation.local_only=true，入口直接完成本地交付。首图交互另按[最小验收](scene-hotspots.md)核对；不恢复全站重型验收。

publish_journal使用当前lark-cli：

- 当前版本：创建/复用html应用 → 初始化专属仓库 → 应用存储上传素材 → 写入远端资源映射 → commit/push sprint/default → release-create → release-get finished → 自动finalize_delivery。
- 旧版仅在apps帮助实际列出+deploy时，使用built_dir目录发布，再查询同一个release。
- 媒体只上传应用存储，不提交到git，不把离线HTML的Base64塞进仓库。生成图格式按实际字节识别。发布源码只复制HTML/CSS/JS，不上传采集缓存、凭据、原始项目或验收报告。不修改可见范围和访问权限；沿用平台默认可见范围，交付时如实说明。

source/deployment-state.json保存每个风格的app_id、上传缓存、仓库及release_id。中断或等待发布时使用：

```bash
python scripts/journal_run.py --resume-run /工作区/runs/本次目录
```

它继续当前release，不重建、重复上传或创建另一轮发布。普通publishing每约20秒查询、最多约5分钟；等待审批、未知状态或超时保持deployment_pending、delivery_complete=false，报告真实状态。不要自动审批或改权限。finished但无最终URL时不编造链接。

build_ok只证明本地静态通过；delivery_complete=true才表示交付闭环。未核验单HTML限额时publish_budget_ok为null，不代表平台预算已通过。真实发布失败或CLI/认证不可用时，保存原因和工具日志并自动交付完整HTML；不能自行把默认任务改成仅本地。

--build-only仅供显式本地诊断。其他宿主如有不同发布能力，可复用已构建的built_dir/html和finalize_delivery记录真实工具结果；不要重复打包。原有finalize_delivery CLI保留为兼容接口，普通制作无需另行调用。
