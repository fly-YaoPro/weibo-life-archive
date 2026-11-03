# 执行命令

命令在Skill目录执行，项目放Skill之外；所有示例路径换为当前机器实际路径。已有项目沿用目标、范围、素材与断点，不重复init。浏览器函数调用见[采集流程](collection.md)，叙事字段见[数据契约](data-contract.md)。

## 初始化或导入

```bash
python scripts/preflight.py --runtime
python scripts/archive_pipeline.py /工作区/source init --uid 实际UID --profile-url 实际主页URL --mode selected --skin paper
```

默认窗口为北京时间执行日前十年；需要固定窗口时加--start/--end。已有合法导出或缓存时可以直接ingest，不必联网重采：

```bash
python scripts/archive_pipeline.py /工作区/source ingest --input /工作区/batch.json
```

支持规范records数组、data.list、data.cards及嵌套card_group。ID用字符串，完整时间带时区；图数未知保持null。正常采集器自行入库，不再单独重放相同批次。

## 阅读与精选

```bash
python scripts/story_tools.py /工作区/source index --candidates --output /工作区/candidate-index-v1.json
python scripts/archive_pipeline.py /工作区/source select --ratings /工作区/ratings.json
python scripts/archive_pipeline.py /工作区/source materialize
```

ratings为Agent读过原文后的`[{"id":"真实ID","score":8.5,"reason":"有据取舍","event_key":"可选事件去重键"}]`。未评分不补位，月/年上限由project_meta.selection_policy执行。full模式不需要select。materialize输出本轮records、覆盖/统计及待补数量；候选数、入选数和平台发帖数口径不能混用。

## 入选素材与故事

```bash
python scripts/story_tools.py /工作区/source index --output /工作区/retained-index-v1.json
python scripts/manage_media.py /工作区/source avatar
python scripts/manage_media.py /工作区/source plan
python scripts/manage_media.py /工作区/source download --workers 3
```

先处理索引pending中的全文/相册缺项；相册详情通过浏览器环境中的detail_media补齐，不用shell匿名HTTP替代。下载器默认单尺寸、每张全部入选配图均有任务，URL/内容缓存去重、下载后按原默认参数压缩；已成功素材不重下。资源预算可按需求传--max-mb/--max-file-mb，重压缩或特殊格式见[图片](images.md)。

Agent写story；需要精确截取和路径映射时使用[效率工具](efficiency.md)。journal_run默认自动准备[配乐](music.md)，无需单独运行prepare_music；两张插画按[插画设计](image-direction.md)生成并实际检查。

## 一次构建

```bash
python scripts/journal_run.py --source /工作区/source --output-root /工作区/runs
```

它包含默认原创配乐、统一story编译与预检、新目录构建、整册素材预算、单次打包、静态契约及自动发布交付。默认只做meta.skin或paper，明确需要双风格时加--skins paper frosted。只有已核验宿主单HTML上限时才传--publish-max-mb。默认素材目标24MiB，--book-max-mb可调整。使用delivery.artifacts中的交付结果；中断用--resume-run本次目录，诊断才用--build-only，不扫描旧目录猜文件名。

若返回preflight_failed，集中修复errors后重跑。独立诊断命令：

```bash
python scripts/check_project.py /工作区/source --kind weibo --stage story
python scripts/audit_images.py /工作区/source
python scripts/pack_html.py /工作区/本次built --estimate --max-mb 已核验上限
```

data阶段仅检查源数据；check_story与--stage story为同一入口，不需要一起运行。pack估算不写文件；手工build/pack只在调试时使用，且输出必须为新路径。旧URL对象修复、原帖截图与日期覆盖登记见[故障与兼容](doubao-reliability.md)。

构建后由同一入口按[部署](deployment.md)自动发布；首图交互另按[最小验收](scene-hotspots.md)核对；不恢复全站重型验收。发布完成以工具finished和最终URL为准；无需在每个制作项目中运行整包开发单元测试。
