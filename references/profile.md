# 目标主页资料

在已核验UID的weibo.com目标页优先调用user_profile.capture_profile_auto(bu, source)。它自动定位唯一资料区域并保存meta.profile；失败时才使用capture_profile(bu, source, selectors)，选择器不得指向全页或登录者/推荐卡资料。

保存uid/name/source_url/captured_at/avatar_source_url/avatar_origin和selector_basis；followers/following/engagement保留display/value/exact/observed。按页面原精度记录，缺失为未知，不用入选条数或互动求和代替主页统计。头像通过manage_media avatar或正常浏览器原头像入口保存，不能生成替身。

回看封面与分享图复用同一meta.profile和头像，不重复采集。字段约束见[数据契约](data-contract.md)，显示问题在验收时检查。
