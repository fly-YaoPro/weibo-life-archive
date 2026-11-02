# 微博主页资料与封面

在已登录网页端目标主页读取名称、头像、粉丝、关注、转评赞。先用当前Harness的正常浏览器能力核验目标UID、用户资料卡边界和每项标签；资料卡不能是全页body，也不能误取导航栏中登录者的头像/姓名。信息来自当前主页显示，不从精选帖条数或转评赞求和推算。

user_profile.capture_profile(bu,source,selectors)保存到meta.profile：uid/name/source_url/captured_at/avatar_source_url/avatar_origin与followers/following/engagement。每项统计保留display/value/exact/observed；1.2万保持原显示并标近似，未知null、不填0。源页面字段不可见可以—并在工作区记录原因，不虚构指标。

头像由正常头像图片入口获取，manage_media avatar可下载已观察的HTTPS图片CDN；保存avatar_path/sha256/尺寸。受阻用正常浏览器图像入口核验，不生成肖像替身、不拿场景裁片或他人头像。生成场景/结尾图仍不得含本人、亲友或人像墙；头像仅作为平台已有真实用户资料。

资料已核实时可在回看第一页显示这组资料，标题、头像圆章、3个统计小格与两套手账材质协调。开场白和有据画像继续在封面照片下方；短屏内容续页，不缩字或裁正文。分享图在用户选择包含资料时复用同一meta.profile和头像，不重新猜数字、名字或身份。

新项目profile_required默认false；资料不完整可省略，不填替身。用户明确要求完整资料模式时才开启严格校验。输入JSON由Agent依据真实观察准备，用户只在必要时亲自登录/完成验证，不手填资料表或提供Cookie。
