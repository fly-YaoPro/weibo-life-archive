# 稳定配乐

默认要有真正可播放的本地音源，点击才播放，音量初始22%，可暂停。先保护已有用户音源；微博已分享歌曲可以作为内容推荐，但商业歌页面或在线播放URL不等于可下载授权。

## 原创默认路线

Skill 已预置原创 BGM `assets/audio/warm-lights.wav`（32秒五声音阶钟琴/铺底，约1.4MB）。运行 prepare_music.py 原创模式时优先直接复制预置文件，无需每次实时合成；预置文件不存在时才降级调用标准库实时生成。界面只显示曲名与唱片机。需要替换已有需署名曲目时运行 `--source original --replace`，旧音源文件留在工作区。更个性化的原创音频可由宿主生成。

BGM 为可选增强项，不配置不阻塞构建；配置后点击入册先播过渡音效，结束后才开音乐。

## 明确选用授权曲库时

Agent按回顾内容选择一个情绪，不让脚本推断用户心情：

| mood | 默认匹配 | 用途 |
| --- | --- | --- |
| gentle | Dream Culture | 温柔日常、陪伴 |
| reflective | Dream Culture | 旧日回看、留白 |
| bright | Carefree | 轻松日常、小快乐 |

`assets/music-catalog.json` 保存作者、原站、下载地址、ISRC、许可及情绪。2026-10-31已读取作者实时pieces.json和许可页，验证两条MP3可返回音频；这是该日的验证，不保证外站永久可用。作者现站提供CC BY 4.0，需要保留必要署名，可收在唱片资料入口；当前要求完全无许可文字的成品改用原创音源。

```bash
python scripts/prepare_music.py 项目目录 --mood gentle --source licensed
# 网络不可用时显式走原创备用音乐
python scripts/prepare_music.py 项目目录 --mood reflective --offline
```

脚本最多试两个已核验作者站候选，各12秒超时、24MB上限；校验HTTPS和重定向、文件签名、WAV帧、SHA256，原子写入audio/并登记story.bgm。已有音源不重下、不覆盖。下载MP3签名通过不等于解码通过，必须浏览器loadedmetadata与实际播放验收；不能把HTML错误页保存为MP3。

外站失败时使用标准库生成原创32秒五声音阶钟琴/铺底WAV，淡入淡出、循环。注明原创器乐与fallback_reason，不假称用户最爱或商业歌曲。它保证音源不缺席；听感仍要实际验收。

## 更适配的生成路线

宿主支持新音频生成且用户已授权整套配乐时，可以使用当前文生音频工具：描述纯器乐、温暖低动态、轻钢琴/钟琴、无歌词人声、循环自然，避免模仿具体歌曲。Trace1 `text_to_audio_plus` 的duration仅在用户指定时传，其他宿主以实际定义为准。保存真实返回WAV，登记origin=generated及真实reference；生成失败不空等，转默认路线。

如需增加曲库，先核验作者目录和每首录音的可再分发许可，再加入catalog；公版作曲不代表某段录音公版。不要通过付费音乐接口、抓播放缓存或无许可聚合站寻找下载捷径。
