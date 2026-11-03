# 静态检查与首图最小验收

build_ok=true和artifact.contract_verified=true为本地静态完成标准；普通制作还需入口自动发布并返回delivery_complete=true：真实来源ID与日期、引用、图片归属、资源路径、热点目标、运行时数据及打包完整性通过。

4.4.2仅增加[首图最小实点验收](scene-hotspots.md)：宽屏与手机各一轮，按画面物件实点，不用目录点击或静态坐标校验代替；核对小记、原有主题/日期跳转、关闭返回和浮层边界。可在能打开的本地或线上产物做，不要求两边重复跑。宿主不支持打开时如实保留未验证，不假造结果，不为此安装新浏览器环境。其余全站截图、试听、分享PNG等仍不作交付前置。

叙事由Agent基于已读原文判断。evidence可选，supports兼容旧数据但不参与校验；简繁、字数、小事数量、重复摘句与相似度不阻塞构建。实际原话仍须来自对应原文，图片仍须属于对应来源。

构建成功后入口复用built_dir/html按[部署](deployment.md)自动发布。平台finished及工具返回的最终URL是发布完成依据，不能证明交互。发布失败回退完整HTML。browser_interactions_verified=false仍表示未验证全站。首图另存scene-click-check.json，记录产物、图指纹、视口、热点ID、实际点击位置、对应来源/目标及结果；未实测不写通过。只通过首图不将全站标记改true。

browser_check、check_flip、check_responsive、check_share、visual_review仍作为可选全站调试工具；check_homepage可辅助几何检查，但也不能替代按完成图核对物件与实点。
