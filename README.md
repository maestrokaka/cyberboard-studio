# Cyberboard Studio

**简体中文** · [English](README.en.md)

**第三方怒喵（Angry Miao）键盘工具，面向 CYBERBOARD R4 / CYBERBOARD R6，适用于 macOS / Windows。**

用 Kimi、MiniMax 或 DeepSeek，在独立的 AI 对话中结合文字与参考图创作顶部与轴灯动画；比较不同版本，在真实键盘照片上预览，再到工作台调整并同步到指定槽位。

[下载候选版与版本记录](https://github.com/maestrokaka/cyberboard-studio/releases) · **[完整使用说明](docs/USER_GUIDE.md)** · [反馈问题](https://github.com/maestrokaka/cyberboard-studio/issues) · [支持作者](#支持作者)

当前为 **1.0.0-rc.2 候选版**，供正式版前试用。Windows 原生 GUI / USB、R4 写入等仍需实机验收，具体范围见[候选版说明](docs/RELEASE_1.0.0_RC2.md)。第一次使用可先阅读[五分钟上手](docs/USER_GUIDE.md#quick-start)。

## 完整演示

77 秒查看外观切换、灯效预览、Kimi k3 结合参考图创作，以及第 3 槽同步；生成与传输等待已加速，结尾是 R6 实拍。视频使用此前版本的界面；1.0 候选版将 AI 创作、工作台与键盘外观分成独立页面，最新页面见下方截图。

https://github.com/user-attachments/assets/8289f982-09d3-45df-9ce7-5f7723c0da52

[查看候选版软件包与版本说明](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v1.0.0-rc.2)

## 内置灯效 GIF

我已经借助 AI 创作并打磨了 **10 款灯效**，全部内置到软件中。无需配置模型，打开就能预览，选好后即可同步到键盘。

想做自己的灯效，也可以接入 **Kimi、MiniMax 或 DeepSeek**，写下你的想法，让 AI 帮你创作。

有想要的主题、角色或灯效，欢迎[到 GitHub Issues 留言告诉我](https://github.com/maestrokaka/cyberboard-studio/issues)。附上一句话描述或参考图，下一款内置灯效，也许就来自你的脑洞。

下方是这 10 款灯效的整机动态预览，点击动图可查看大图。

| 预设 | 预设 |
| --- | --- |
| **01 裂隙超载**<br>青紫装甲与裂隙转场 · 7.68 秒<br><a href="docs/previews/neon-rift.gif"><img src="docs/previews/neon-rift.gif" width="384" alt="裂隙超载：顶部与轴灯完整循环" /></a> | **02 数据暴雨**<br>绿色数据光点与落雨 · 7.68 秒<br><a href="docs/previews/data-storm.gif"><img src="docs/previews/data-storm.gif" width="384" alt="数据暴雨：顶部与轴灯完整循环" /></a> |
| **03 红线竞速**<br>红白轨迹与速度感 · 7.68 秒<br><a href="docs/previews/redline-rush.gif"><img src="docs/previews/redline-rush.gif" width="384" alt="红线竞速：顶部与轴灯完整循环" /></a> | **04 EVA初号机 · 觉醒序列**<br>紫绿装甲、眼部与觉醒阶段 · 4.8 秒<br><a href="docs/previews/eva-awakening.gif"><img src="docs/previews/eva-awakening.gif" width="384" alt="EVA初号机觉醒序列：顶部与轴灯完整循环" /></a> |
| **05 故障字标 · 终端夺权**<br>宽幅赛博字标与错位转场 · 4.8 秒<br><a href="docs/previews/glitch-override.gif"><img src="docs/previews/glitch-override.gif" width="384" alt="故障字标终端夺权：顶部与轴灯完整循环" /></a> | **06 马里奥 · 红帽闯关**<br>纯红帽子与像素闯关 · 4.2 秒<br><a href="docs/previews/mario-run.gif"><img src="docs/previews/mario-run.gif" width="384" alt="马里奥红帽闯关：顶部与轴灯完整循环" /></a> |
| **07 猫逐萤火**<br>小猫与萤火追逐 · 6 秒<br><a href="docs/previews/cat-firefly.gif"><img src="docs/previews/cat-firefly.gif" width="384" alt="猫逐萤火：顶部与轴灯完整循环" /></a> | **08 卡卡 · 红黑22**<br>球星卡、肖像与姓名号码 · 4.8 秒<br><a href="docs/previews/kaka-rossonero.gif"><img src="docs/previews/kaka-rossonero.gif" width="384" alt="卡卡红黑22：顶部与轴灯完整循环" /></a> |
| **09 卡卡 · 极速突破**<br>带球动作与清楚的 KAKA 22 · 4.8 秒<br><a href="docs/previews/kaka-breakaway.gif"><img src="docs/previews/kaka-breakaway.gif" width="384" alt="卡卡极速突破：顶部与轴灯完整循环" /></a> | **10 卡卡 · 圣西罗之夜**<br>庆祝姿态与红白旗浪 · 4.8 秒<br><a href="docs/previews/kaka-san-siro.gif"><img src="docs/previews/kaka-san-siro.gif" width="384" alt="卡卡圣西罗之夜：顶部与轴灯完整循环" /></a> |

<details>
<summary>关于动图预览</summary>

动图采用 CYBERBOARD R6「Vision」去背景正面实拍照片，与 App 共用预览渲染器，合成顶部与轴灯的完整原速动画。源作品 RGB 与节奏不变；GIF 编码可能产生轻微色差，照片合成预览不代表实机色准。[GIF 校验记录](docs/previews/manifest.json) · [三款卡卡的优化过程](docs/LIGHTING_DESIGN_NOTES.md)

</details>

## 应用截图

候选版把三个主要步骤分开：**AI 创作 → 灯效工作台 → 设备同步**。截图使用独立演示工作区，不展示个人密钥或设备记录。

### AI 创作

对话是主画面，右侧轻预览可以收起。每次成功生成形成独立版本；选择基础版本后，可继续修改「顶部 + 轴灯」「仅顶部」或「仅轴灯」。会话历史放在页面内部，支持搜索和继续创作。结果留在会话中，点击「保存到作品库」才保存指定版本，点击「在工作台打开」再调整和交付。

![AI 创作：对话、参考图与独立灯效版本](docs/screenshots/create-v100rc2.png)

### 灯效工作台

大整机预览、亮度 / 节奏 / 配色工具和三槽总览集中在一页。点击槽位卡选择目标，「预览」查看槽位内容，「撤销草稿」只撤销本机准备的内容。先放入或更新目标槽位草稿，再查看计划并同步；切换 AI 会话不会清空槽位草稿。

![灯效工作台：整机预览、参数与三槽总览](docs/screenshots/workbench-v100rc2.png)

### 键盘与外观

8 款外观独立成卡片页，支持 R4 / R6 筛选，并用同一作品、同一帧比较。全部采用沿外壳轮廓去背景的正面整机照片，标签使用 `R6「Vision」` 等简洁名称。选择只影响观看，USB 实际设备身份以手动检查为准。

![八款外观：统一正面、同一灯效帧](docs/screenshots/appearances-v100rc2.png)

| 参考外观 | 照片来源 |
| --- | --- |
| CYBERBOARD R6「Vision」 | 最早提供的正面实拍 |
| CYBERBOARD R4「Fluo Free」 | 怒喵官方商城 |
| CYBERBOARD R4「Bebop」 | 怒喵官方商城 |
| CYBERBOARD R4「Gangstar」 | 怒喵官方商城 |
| CYBERBOARD R4「Cloud White V2」 | 怒喵官方商城 |
| CYBERBOARD R4「Stone Face」 | 怒喵官方商城 |
| CYBERBOARD R4「Paisley」 | 怒喵官方商城 |
| CYBERBOARD R4「Vision」 | 怒喵官网 R4 产品页 |

包含官网仍保留的合格售罄配色素材，参考外观与实时库存无关。[素材来源与校准记录](data/photos/official-photo-sources.json)

模型配置单独管理四种服务和各自的 Key；设备页提供「设备与槽位 / 键位查看 / 同步记录」子标签。作品库保留搜索、命名、回收站与恢复功能，10 款内置作品均可删除。

## 下载与运行

| 文件 | 适用电脑 | 打开方式 |
| --- | --- | --- |
| `Cyberboard-Studio-1.0.0-rc.2-macOS-AppleSilicon.zip` | Apple Silicon Mac，macOS 13 及以上 | 解压，将 `Cyberboard Studio.app` 放入「应用程序」 |
| `Cyberboard-Studio-1.0.0-rc.2-Windows-x64.zip` | Windows 11 x64；部分受 .NET 10 支持的 Windows 10 LTSC / Enterprise | 完整解压后运行 `Cyberboard Studio.exe`，保留 DLL 和 `resources` |
| `Cyberboard-Studio-1.0.0-rc.2-Windows10-Compatibility-x64.zip` | 日志明确出现 CET 启动兼容问题的旧 Windows 10 x64 | 独立解压到新目录，仅此包取消 App 的 CET 标记 |

在 [v1.0.0-rc.2 的 Assets](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v1.0.0-rc.2) 下载 ZIP 和对应 SHA-256 文件。包内包含 CLI 和运行环境，无需另外安装 Python；Windows 缺少 WebView2 时，运行 `Dependencies/MicrosoftEdgeWebview2Setup.exe` 联网安装。Intel Mac、Windows 32 位与 ARM64 原生包尚未提供。

Mac 包为本机 ad-hoc 签名，尚未使用 Apple Developer ID 签名或公证；首次打开可参照 [Apple 的应用打开说明](https://support.apple.com/en-gb/102445)。Windows 候选包的原生启动、Key 文件操作与 USB 仍需实机验收。遇到「Unknown Hard Error」先运行「诊断启动.cmd」，仅在日志明确指向 CET 时考虑兼容包；优先更新系统后使用普通包。详见[故障处理](docs/USER_GUIDE.md#faq)。

历史版本保留在 [Releases](https://github.com/maestrokaka/cyberboard-studio/releases)。用户数据与安装目录分开，升级前请关闭旧 App。首次成功保存新版工作区时会保留 `workspace-before-1.0.json`，已有作品、回收站、内置删除记录和槽位草稿继续保留。候选版不会因升级自动写入键盘。

## 当前功能

- 独立 AI 对话，文字与最多 3 张参考图；本机保存历史、参考图、输入草稿和完整灯效版本。
- 明确选择基础版本，限定顶部、轴灯或两者修改；局部修改保留另一灯域的完整颜色帧与时序，原版本不变。
- 版本预览、同步比较、停止、重试、指定版本导出和明确保存入库；空会话不能保存或交付旧作品。
- Kimi Code / 开放平台、MiniMax、DeepSeek 配置。Kimi Code 默认 `k3`，MiniMax 新连接默认 `MiniMax-M3.1-Flash-Preview`，DeepSeek 默认 `deepseek-flash`；保留已保存的其他模型选择。
- 10 款内置作品与 8 款正面参考外观，无 Key 时也可离线体验预设。
- 工作台亮度、节奏、配色变体、名称、JSON 导入导出，三槽目标选择、预览和撤销草稿。
- 作品库搜索、回收站恢复与确认后永久清理，全部内置作品可删除且升级不自动补回。
- R4 / R6 身份查询、81 个实体键的 7 层只读键位、Asia/Shanghai（UTC+8）时间同步。
- 同步前完整配置备份与计划；指定单槽或明确同步全部待同步草稿，保留当前全部键码并读回检查。
- 缺少原记录时提供明确范围的首次配置，已有记录时可只恢复指定内置模式；本机历史与恢复计划。

DeepSeek 读取限制修正为分别约束有效输出、思考内容和传输数据；MiniMax 兼容完整 `stop` 后流关闭的结束方式，并为 M3 调整思考参数。未完成或超限回复仍会拒绝，不接受半成品。[模型与验收范围](docs/RELEASE_1.0.0_RC2.md)

## 从一句描述开始

1. 在「模型配置」选服务、区域和有权限的模型，输入 Key 并「保存并使用」。Key 默认隐藏，点击「显示 / 隐藏」即可查看；只按服务存本机普通文件，不访问旧系统凭据。
2. 到「AI 创作」新建对话。无图可写「橙红火焰从底部窜起，轴灯像余烬，4 秒循环」；有图可上传后写「完整角色从下向上快速滚动，保留原配色，脸部稍停」。
3. 点击「发送并制作」。生成检查完成后选择版本预览；继续修改时选好基础版本和范围，例如「仅轴灯，改成纯黄，顶部保持原样」。
4. 满意后保存指定版本，或在工作台打开。放入目标槽位，检查同步计划，再确认写入。

生成会发送本次描述、选中的压缩图片、简短对话回顾及明确选定的基础配方。图片与对话只保存在本机工作区，作品 JSON 不含图片和 Key；不会把整份工作区、键位或设备配置发给模型。默认不借用其他工作台作品的风格，只有勾选风格参考时才加入对应名称、描述和配色。模型计费、权限与图片支持以平台和账户为准；M3.1 Flash 需要相应套餐权限。

每次生成最多额外请求一次结构或基本可见性修复；通过检查仍需看完整循环，审美和实机色准由你确认。取消、失败或修复也可能消耗模型额度。当前 CLI 没有固件升级，App 暂无键位编辑、通用图片生成或视频导出。

## 第一次同步

键盘不能完整读回灯效像素，单槽同步需要**同一把实体键盘**此前成功写入后留下的完整配置记录，通常为设备目录中的 `current.json` 与 `meta.json`。普通「导入灯效」只添加作品，不建立这份设备记录；从 Mac 转到 Windows 可使用「迁移原配置.cmd」。详见[原配置与首次配置](docs/USER_GUIDE.md#baseline)。

没有可信记录时，App 可准备首次配置：当前完整 1,400 键码会读取、原样写入并校验；选中草稿写入指定槽位，其余槽位停用并黑屏，其他灯光采用官网标准方案。**旧灯效、文字、独立宏、交换键和换键表无法保留，部分特殊功能可能需重设。** 先核对替换范围，再确认建立配置；键码快照不是旧完整灯效备份。

普通同步先放入草稿并核对计划，保留其他槽位和当前键码；只有点击计划中的确认按钮才会写入 USB。设备确认、键码验证与本机记录保存分别显示，不能把进度到头当成全部完成。[完整同步说明](docs/USER_GUIDE.md#sync)

## 本机数据

| 数据 | macOS | Windows |
| --- | --- | --- |
| 会话、版本、参考图、作品、回收站、草稿、计划和备份 | `~/Library/Application Support/Cyberboard Studio/` | `%LOCALAPPDATA%\Cyberboard Studio` |
| CLI 设备记录 | `~/.local/share/cyberboard-cli/devices/` | `%LOCALAPPDATA%\cyberboard-cli\devices` |

新版 `workspace.json` 使用 v2 格式，包含会话、参考图和完整版本；升级备份 `workspace-before-1.0.json` 也属于私人数据。会话切换与槽位草稿相互独立。保存完成后才报告成功，退出 / 重新载入前等待保存，失败时可留在 App 导出重要作品。当前最多 20 个会话，每会话 12 个版本、60 条消息，整份工作区上限 32 MiB，超限请先导出再整理，不自动删除旧记录。

`ai-settings.json` 只有服务、地址和模型；Key 独立存于 `ai-keys/<服务>.key`，不写入工作区、作品、导出、日志、发布包或 GitHub。旧 Keychain / DPAPI 记录不读取、解密、迁移或删除；只有旧系统记录时请重新粘贴 Key 保存。备份 Studio 数据目录时也包含个人 Key，请妥善保管，不要整目录公开上传。

## 从源码构建

需要 Python 3.12、Node.js；Mac 构建还需 Xcode Command Line Tools，Windows 构建还需 .NET 10 SDK。

本仓库保留经过验证的 CLI 0.1.2 源码、R6 识别与跨平台补丁，见 [CLI 来源与许可证](vendor/README.md)。源码素材在 `data/`，测试使用合成配置，不能将其当作真实设备基线。

Mac，在仓库根目录执行：

```sh
python3 scripts/setup-cli.py --env-dir .tools/macos-build --with-pyinstaller
.tools/macos-build/bin/python scripts/build-macos-backend.py
python3 scripts/prepare-data.py
native/build.sh --backend-dir build/macos-backend/CyberboardBackend
```

这会先冻结独立后台，再生成 `build/Cyberboard Studio.app`。Mac 构建会检查发布素材不含个人基线，并验证签名。

Windows 独立运行环境准备与校验见 [运行环境构建说明](windows/runtime-readme.txt)。准备 `windows/runtime/python` 后：

```sh
python windows/build.py --dotnet /path/to/dotnet --nuget /path/to/nuget-cache --bootstrapper /path/to/MicrosoftEdgeWebview2Setup.exe
```

`--dotnet`、`--nuget` 可省略以使用本机 SDK 与仓库内缓存；软件包始终包含完整运行组件。Windows 使用 `EnableWindowsTargeting`，允许从 Mac 交叉编译。WebView2 引导安装器来自 [Microsoft 官方下载](https://go.microsoft.com/fwlink/p/?LinkId=2124703)。

可选重建 GitHub 的十款照片合成 GIF：使用已安装 Pillow 的 Python 环境、Node.js 与 `@napi-rs/canvas`，在仓库根目录执行；这是发布素材工具，不是 App 新增的视频导出功能。

```sh
npm install --prefix .tools/gif-render @napi-rs/canvas
python scripts/build-preset-gifs.py
```

生成器默认查找 `.tools/gif-render/node_modules`，也可通过 `STUDIO_CANVAS_MODULE` 指定 Canvas 模块。它用 App 预览引擎合成照片动画；临时 PNG 只写入 `build/`，不上传。

## 离线验证

```sh
node tests/model-check.cjs
node tests/presets-check.cjs
node tests/frontend-regressions.cjs
node tests/library-ui-check.cjs
node tests/renderer-check.cjs
node tests/preview-selector-check.cjs
node tests/ui-check.cjs
node tests/ai-ui-check.cjs
node tests/chat-ui-check.cjs
STUDIO_UI_PLATFORM=windows node tests/ui-check.cjs
.tools/macos-build/bin/python tests/backend-check.py
.tools/macos-build/bin/python tests/ai-recipe-check.py
.tools/macos-build/bin/python tests/kimi-ai-check.py
.tools/macos-build/bin/python tests/kimi-ai-extra-check.py
.tools/macos-build/bin/python tests/multi-provider-ai-check.py
.tools/macos-build/bin/python tests/ai-conversation-check.py
.tools/macos-build/bin/python tests/workspace-conversation-check.py
.tools/macos-build/bin/python tests/ai-images-check.py
.tools/macos-build/bin/python tests/native-ai-check.py
.tools/macos-build/bin/python windows/tests/migration-check.py
```

测试使用设备和 HTTP 替身，不访问 USB，也不消耗真实模型额度。发布包另外检查依赖校验和、架构、许可证、无个人状态，以及 Mac 后台整体搬移后的运行能力。

## 代码结构

- `web/`：灯效工作台、JSON 模型、照片预览和已确认的 Logo。
- `backend/bridge.py`：CLI 桥接、备份、同步计划、实际传输与验证。
- `backend/kimi_ai.py`、`lighting_recipe.py`、`ai_images.py`：模型调用、有限灯效编排与参考图规范化。
- `native/`：macOS 窗口、原生文件对话框、后台通信与同步保护。
- `windows/src/`：WinForms / WebView2 窗口、文件对话框和后台进度。
- `windows/runtime/`：Windows 运行环境的官方来源、固定版本和准备脚本。
- `vendor/`：CLI 源码、补丁说明及第三方许可。
- `data/`：灯效作品、公开预设目录 `preset-catalog.json`、照片校准、通用实体布局与合成测试 fixture。
- `scripts/`：环境准备、素材生成和 Mac 后台构建。

## 在 GitHub 更新

源码与公开文档提交到 `main`；软件包通过 Releases 发布。`v1.0.0-rc.2` 使用 prerelease 标记，验收完成前不标成稳定 1.0.0。个人会话、参考图、工作区、设备记录、Key 和编译缓存不进入 Git 历史。

---

## 支持作者

**键盘已经亮了，咖啡杯还空着。☕**

如果 Cyberboard Studio 帮你点亮了喜欢的灯效，欢迎请 **Kakà** 喝杯咖啡，给下一次灵感补一点咖啡因。金额随心，心意满格；支持完全自愿，不影响任何功能的使用。

<p align="center">
  <a href="docs/assets/wechat-support.svg"><img src="docs/assets/wechat-support.svg" width="280" alt="Kakà 的微信收款二维码" /></a>
  <br />
  <strong>微信扫一扫 · Kakà</strong>
  <br />
  <sub>点击二维码可查看大图</sub>
</p>

有 Bug、有脑洞，或者想聊聊你的键盘，欢迎写信给 [maestrokaka@gmail.com](mailto:maestrokaka@gmail.com)。

**咖啡可以扫码，问题请走邮件。** 付款留言不方便跟进，别让你的好点子迷路了。

如果你需要英文界面的 App，欢迎联系我：[maestrokaka@gmail.com](mailto:maestrokaka@gmail.com)。
