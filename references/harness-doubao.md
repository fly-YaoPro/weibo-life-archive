# Doubao Harness 适配

## 执行位置

读取实际使用的浏览器Skill和工具定义。常见入口是computer_use_tool、plane="bu"和aha_browser_use，其他版本可能不同；不能把普通shell当作带浏览器登录态的请求工具。需要原生桌面操作时才加载computer_use。

Skill脚本与项目路径须在浏览器所在机器可读，将实际scripts路径加入sys.path。浏览器调用可能跨进程，状态以项目JSON为准，不靠全局变量续跑。解包到新目录，不删除旧项目；登录按宿主接管入口完成，已登录不重复请求。

## 当前入口

按[采集流程](collection.md)使用capture_profile_auto、configure_mobile(transport='download')和collect_mobile。先做一页核验，成功后用有界批次继续；旧配置缺transport时仍可能使用sync_xhr，需按[故障与兼容](doubao-reliability.md)显式核验切换，不清除阻挡或重置页码。不要先重走桌面接口、同步XHR和API导航的整套探测。

图片生成调用宿主实际专用工具，按[插画设计](image-direction.md)选择模型与参数；不要因本机缺某个CLI就安装另一套生成平台。只使用真实返回产物。

## 验收与发布

启动时运行preflight --runtime，确定微博采集与发布路径。本地构建用journal_run；首图按[最小验收](scene-hotspots.md)核对，其余浏览器测试按需，发布按[部署](deployment.md)。工具能力、文件可读性、下载完成或平台finished状态各自只证明对应环节，不能互相替代。

普通制作无需预读维护案例。宿主/网站变化、脚本报错或模板修复时再读[故障与兼容](doubao-reliability.md)、[页面维护](implementation.md)及[验证范围](harness-validation.md)。
