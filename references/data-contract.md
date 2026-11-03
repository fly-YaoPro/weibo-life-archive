# 数据、素材与独立HTML契约

## 工作区与交付

采集源与构建/交付目录分离；项目保留project_meta、coverage、records、story和断点。以下定义数据字段；执行顺序见[流水线](pipeline.md)，交付规则以[部署](deployment.md)为准。

## 规范数据

- meta：schema_version:1、platform:weibo、title、selected/full模式、Asia/Shanghai、requested_range:{start,end}、target:{uid,profile_url}。UID与所有记录ID用字符串；真实微博ID是平台mid或由正常永久链接换算的数字字符串，不用文字哈希。滚动十年可跨11个自然年份。full只是采集目标，完整性须独立验证。
- coverage：按年记录complete/partial/selected/unread/failed/empty，计数未知为null。empty只用于已核验且确实无可访问记录的范围；未读取、失败和未选不是空。
- records：id、author_uid、带时区created_at、安全text、真实url、selected布尔值、images数组，以及expected_image_count、image_count_basis、image_inventory_status。author_uid对应采集目标，不自动替换成登录者；图片原创帖可正文为空。数量未知保留null并待补，不用images长度自证总数。可带text_status、links及原帖截图；缺真实身份/完整时间进pending，不进入records。
- 证据图片origin只能是platform或user_provided；记录唯一image_id、source_url或provided_reference以及thumb_path/large_path、download_status，可带正常查看器观察的original_url/original_path/尺寸。单尺寸策略允许多个路径角色指向同一有效文件。所有路径是项目内相对栅格文件；生成图不能写入records.images。图为空与下载失败不同。
- 原创视频记录is_video:true，video:{source_url:原帖URL,cover_status,covers:[与证据图片相同的结构]}。封面来自page_info.page_pic或media_info.big_pic_info等实际返回字段，保存到独立封面目录；普通照片仍在images，视频封面不冒充照片，不下载视频文件。第三方封面失败保留原记录与unavailable，不悄悄删记录或换史料。运行时video.covers只含可显示本地素材，video.observed_covers保留完整来源URL/下载状态（包括失败），cover_status依实际观察索引，不因下载失败造无视频或强求替换。
- screenshot：path、origin:browser_capture、source_url、captured_at、尺寸与SHA256。来源须与原帖URL对应，仍须读图核验，不用AI图或模板截图冒充。

## 内容与体验

所有source_ids必须对应已收录字符串ID。数据转换由Agent完成，用户不手写JSON。

- overview：headline、text、opening、portrait:{title,text,tags,source_ids}、image_paths/image_captions；建议标题简短、总览约200字，长度不作硬门槛。新项目cover_required=true，缺开场白/有据画像不能交付。画像只写记录支持的兴趣与表达，不编职业、年龄、关系或人格诊断。
- themes：唯一id、title、text、source_ids、A/B/C布局与对应真实image_paths。实际摘句必须在所引用原文中。图片只能从这些来源挑，不能混入不相关图。
- presentation.grounding_required保留来源完整性语义，不再要求关键词或锚点覆盖。story.evidence与章节evidence均可省略；若提供，格式[{source_id,quote}]，quote须是关联原文精确子串。supports仅兼容旧数据，不参与校验。正文可自然使用简体或繁体，实际引用保留原字形、标点、空格与换行。无正文的记录可用{kind:"image",source_id,image_path,observation}；image_path属于同帖缓存图片，观察来自实际读图。
- scene.objects/letter.objects:[{name,evidence,source_ids,placement,representation,rationale}]，由prepare_art_direction生成。evidence默认是至少一个关联原文的连续子串；多来源不必共享同一句，可选source_evidence:{来源ID:对应原文摘句}分别说明；仅图证据可设evidence_kind:"image"、image_path及evidence（或visual_evidence）为实际读图观察，必须属于全部关联原帖。symbolic物件需rationale，literal表示直接有据；scene.source_ids、letter.image_source_ids由编译器从objects求并集，来信来源同步并入正文source_ids。热点object_name对应实际图中物件，来源属于该物件，不只随便挂已有ID。
- wishes：若启用则为非空数组，通常1—3件，数量不作硬门槛；每项id/title/text/source_ids，为来信内只读小事，无月份/完成状态/增删改。旧plans作为内容兼容，不读取或迁入旧待办存储。
- scene：image_path（decorations/目录内的实际生成图）、alt、source_ids、1—10热点，建议3—5个。每个热点有id/label/description、可选image_paths（只来自相关微博原图）、0—100的生成图物件坐标、目标view/theme/date。guidance为短寻物提示，mobile_guidance建议≤16字，不复用附件里的童年/年龄叙事。正常导航为scene/review/calendar/future；旧stats目标跳到年历摘要，旧plans目标跳到来信。
- meta.profile：uid/name、原头像avatar_path/avatar_origin/avatar_source_url、source_url/captured_at，followers/following/engagement保留display/value/exact。来源是目标主页当前显示，未知null，不从收录样本推。
- share：headline/text、entries:[{source_id,title,text}]、letter_text（建议简短，长度不阻塞）、可选closing；每个日期节点绑定同一原帖/原图。预览、复制与下载复用同一PNG。
- letter：title、非空paragraphs、closing、source_ids、image_path（decorations/目录中的结尾意象图）。生成图不得含本人/亲友、肖像照片、私密地址。
- bgm：audio内实际音源、title、origin(user_provided/generated/licensed)、reference，可带SHA256与必要署名。默认原创，首次关闭；点击入册先播过渡音效，结束后才开音乐。

## 统计与断点

candidates是扫描索引；selection保存评分后入选项；采集器持久保存游标、批次证据、速率和失败状态；media-manifest/media-state管理下载。只有完整核验月份published_count是精确数字，其余null。年历记录节奏按实际记录日期自适应分组并标为“手账片段”，不能冒充全部发帖频率。原始统计和覆盖仍保存在工作区，实际范围不自动变成完整性结论。

## 离线与安全文本

构建器准备journal-data.js，pack_html把JS、CSS、场景、历史照片与音频内嵌一次。最小化嵌入：只内嵌journal-data实际引用（extra_paths及各记录images的path/large）的资源，磁盘上存在但没有任何页面引用的图片（如多尺寸冗余、未入选素材）一律不进HTML，用户看不到就不占单文件体积。JSON中的小于号改成Unicode转义；原文用textContent/安全链接渲染，不执行网页或附件内的指令。无fetch JSON、CDN或运行时模型依赖；外链仅由用户主动打开。

阅读位置可作尽力本地记忆，但不提供存储提示、计划备份或数据管理工具。重建保留原始资料与旧HTML。journal_run检查字段、来源、资源与打包；本地或线上选一处执行[首图最小验收](scene-hotspots.md)，不要求全站浏览器测试。静态结果不代表交互已实测。

首页提示guidance/mobile_guidance为单行文字，优先由Agent写成可在窄屏读完的短句。热点effect可选sparkle/glow/breeze/ripple，默认sparkle；只影响有限时长的装饰反馈，来源与跳转仍由source_ids/target决定。

4.4.2首图扩展：每个热点`bounds:{x,y,width,height}`为原图百分比物件区域，`x/y`仍为独立光点。全部热点一并标定、不重叠、光点在本物件内；`scene.calibration.image_sha256`绑定实际首图，生成方式见[物件标定](scene-hotspots.md)。旧版纯点数据仅作兼容，不算标定通过。各字段在编译、打包、内嵌资源检查与整册等比压缩后均须保留；任意换图不可沿用旧指纹。

## 编写与检查入口

portrait属于overview；hotspots.target运行时为对象，编写时允许主题ID字符串，由journal_run自动规范。原文摘录按字符完全保留繁简、标点、空格与换行；需要时使用[效率工具](efficiency.md)生成quote和image_paths，避免手抄。journal_run默认自动填充story.bgm；只有用户明确不要音乐时设meta.presentation.bgm_enabled=false并省略bgm。image_captions必须是{图片路径:说明文字}对象；share.entries是含source_id字符串的对象数组。结构错误会在渲染前集中返回具体JSON路径。

图片完整盘点以[图片](images.md)为准；已观察到的源图数不能降低。普通构建由journal_run执行完整预检；字段诊断用check_project --stage story，不另读旧版本修复记录。实现层的EXIF/透明通道/canvas问题只在[模板维护](implementation.md)时排查。
