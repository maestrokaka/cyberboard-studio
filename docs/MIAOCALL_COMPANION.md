# 喵唤 · Companion Private Beta 2

此版本只发布到私有仓库 `maestrokaka/cyberboard-studio-miaocall` 的 `feature/miaocall-companion`。公开 Beta 14、公开 main 和安装包保持不变。当前新包为 macOS Apple Silicon、macOS 13+。

## 使用

进入「喵唤 · Beta」，三个页签分别负责桌面陪伴、换装衣橱、原有语音任务。AI 创作仍是首页。

- **桌面陪伴**：默认高度为 300（此前为 340），整体缩小约 12%。可选择常驻或仅唤醒、240–440 大小、停留互动与音量，点击「应用桌面设置」。常驻独立于全局快捷键，不开麦克风，也不自动启用监听。角色可直接拖动，位置保存；靠屏幕边缘时对话框自动换边。右键可切换声音、出现方式或暂时收起。
- **换装衣橱**：先选择立绘预览，再点击「穿上这一套」。三套服装为橙白水手服、奶油针织 JK、雪白西装套装；水手服另有橙白长发选项。四组各有待机、招手、猫耳、脸颊、伸展、低头、思考、开心 8 个独立姿势。角色统一为成年设定，保持橙白发色、琥珀眼和猫耳尾巴。
- **声音**：甜萌、御姐、温柔、元气四种成年声线，每种 15 条预先合成语音，共 60 条。声音默认关闭，试听为一次明确播放，不会更改所穿衣装或启用快捷键。正常互动不联网、无需 Key。采用 MiniMax 官方系统声线，没有使用个人声纹源文件。
- **语音任务**：沿用 MiniMax / 千问 / OpenAI 语音转文字配置，以及本机 Codex 的独立 Spotify 任务。快捷键仍默认关闭；新增陪伴功能不扩大 Agent 操作范围。

## 互动设计

停留约 480ms 后触发，全局间隔至少 3.2 秒，同一部位至少 9 秒；持续停在同一处只回应一次，需移开后再进入。拖动和录音、转写、AI 制作或语音任务期间暂停闲聊，避免抢占声音。姿势切换是独立绘制帧，不是 Live2D 骨骼动画。

| 部位 | 姿势 / 反馈 | 台词 |
| --- | --- | --- |
| 左猫耳 | 摸耳 / 竖耳 | 耳朵收到信号啦，喵。 |
| 右猫耳 | 摸耳 / 倾听 | 听见啦，我在这里。 |
| 头发 | 歪头 / 顺发 | 头发有一点乱，帮我顺一顺吧。 |
| 脸颊 | 歪头微笑 | 今天也要有个好心情。 |
| 领结 | 低头整理 | 我来整理一下领结。 |
| 肩膀 | 伸展 | 坐久了，一起伸个懒腰吧。 |
| 左袖口 | 招手 / 整理 | 袖口整理好了，准备出发。 |
| 右袖口 | 招手 / 整理 | 这里也要整整齐齐。 |
| 左手 | 招手 / 击掌 | 击个掌，继续加油。 |
| 右手 | 开心 | 收到你的鼓励啦。 |
| 尾巴 | 竖耳提醒 | 尾巴要轻轻碰哦。 |
| 裙摆 | 低头整理 / 保持距离 | 请留一点距离，我来整理衣摆。 |
| 膝部 | 低头提醒 | 要记得起来走动一下。 |
| 膝袜 | 看看搭配 | 今天的搭配，还不错吧。 |
| 鞋子 | 低头检查 | 鞋带检查完毕，随时出发。 |

桌面透明边缘会穿透鼠标；触点采用各部位矩形与角色 alpha 联合判断。自定义 AI 服装的轮廓可能不同，通用触点不保证每套精准贴合。

## AI 换装

衣橱 → AI 换装 → 生图连接，选择 MiniMax 区域并保存支持 `image-01` 的 Key。也可以明确选择复用本机已保存的 MiniMax 语音 Key。Key 以普通本机文件按服务保存，默认隐藏，可显示；没有 Keychain / DPAPI 访问。Coding 订阅 Key 不保证具备生图权限。

填写衣装描述与短发 / 长发，点击生成后只发送内置角色参考图和本次服装描述到 MiniMax 官方服务。不会发送灯效会话、设备记录或其他图片。生成按账户计费，超时不自动重试；可取消，描述保留。

成功后先显示预览，**不会自动穿上**。AI 新衣装当前只有一张静态立绘，互动可显示台词与声音，8 个独立动作仅内置四组提供。生成服务没有可靠的透明背景保证，因此要求纯绿色背景，移除明显绿色并检查透明范围；背景不合格则拒绝保存。绿色衣物不适合当前抠图方案。保留上限 20 套，可删除本机 AI 衣装，不能删除内置原素材。

## 本轮验证与边界

- MiniMax 官方 image-01 已通过真实参考图换装请求，返回 PNG 经正式模块处理，生成结果未自动应用。测试生成图只保存在 ignored build 中。
- 60 条官方系统声线音频已生成并由 macOS 完整解码。32 个姿势透明 PNG、长短发选项、设置边界、停留/冷却与边缘换边均有离线检查。
- 实际 macOS App 已验证长发应用、主窗口最小化后常驻、关闭重开后配置保留、桌面拖动与声线试听对应姿势。
- 原有键盘同步和创作功能按已有测试回归；本轮没有写 USB、重新录音、运行 Agent 或播放 Spotify。
- 其他系统的桌面宠物、Live2D、自动生成全套动作和无边界 Agent 操作不属于此 Beta。

## 资源与生成提示词

正式素材在 `web/assets/companion/`，四组各 8 张 320×640 透明 PNG；音频在其 `audio/`，配置在 `catalog.json`。原已批准 App Logo 与旧喵娘图片保留。

内置图使用 Codex 内建 imagegen 生成。最终提示词规范如下，用同一角色参考逐组生成 4×2 透明图集，再按格提取、去除低 alpha 游离噪点、等比放入固定画布：

> Use case: identity-preserve / stylized-concept. Asset: eight-pose desktop companion sprite atlas, exactly four columns and two rows. One clearly adult 23-year-old anime catgirl, elegant adult proportions, ivory-and-orange hair, amber eyes, white/orange cat ears and fluffy orange tail. Preserve the approved face and orange-white identity. Full body including both ears and shoes, equal size in every cell, generous transparent separation, actual transparent background, no words or props. Eight poses in reading order: neutral standing; friendly wave; hand by ear listening; hand by cheek with a small smile; gentle stretch; looking down to tidy clothes; thoughtful hand near chin; happy upright greeting. Clothes remain complete in all poses. Do not crop limbs or leak into adjacent cells.

四组衣装增量：

1. **sailor-short** — short orange/ivory bob, ivory long-sleeve sailor blouse, charcoal collar and pleated skirt, orange ribbon, opaque white knee socks, dark loafers.
2. **knit-short** — same short hair and identity, cream knit cardigan, orange bow, pale grey pleated skirt, opaque white knee socks, dark loafers.
3. **white-short** — same short hair and identity, tailored white blazer, ivory pleated skirt, orange small tie, opaque white tights, white shoes.
4. **sailor-long** — same sailor outfit and face as sailor-short, change hair to waist-length flowing orange/ivory long hair; preserve all eight pose categories.

运行时 AI 换装提示词见 `backend/companion.py`，固定人物、成年设定、完整着装和纯绿背景，仅插入用户服装描述与发型。互动句子和官方声线 ID 见 `catalog.json`；离线音频生成工具为 `scripts/build-companion-voices.py`。
