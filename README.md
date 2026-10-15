# Cyberboard Studio

**简体中文** · [English](README.en.md)

**第三方怒喵（Angry Miao）键盘工具，支持 CYBERBOARD R4 / CYBERBOARD R6，适用于 macOS / Windows。**

用 Kimi、MiniMax 或 DeepSeek，结合文字与参考图制作顶部与轴灯动画，在真实键盘照片上预览，再通过本机 CLI 同步到键盘。

[下载软件与查看版本记录](https://github.com/maestrokaka/cyberboard-studio/releases) · **[完整使用说明](docs/USER_GUIDE.md)** · [反馈问题](https://github.com/maestrokaka/cyberboard-studio/issues) · [支持作者](#支持作者)

第一次使用可先阅读[五分钟上手](docs/USER_GUIDE.md#quick-start)，查看安装、模型连接、文字与参考图创作、预览、JSON、原配置迁移、同步、键位、时间和故障处理的完整步骤。

## 完整演示

77 秒查看外观切换、不同灯效预览、Kimi k3 结合参考图创作，以及第 3 槽实际同步；生成与传输的等待过程已加速，结尾是 R6 实拍。此视频此前录制于 macOS，展示完整操作流程；下方截图与预设名单已更新至 v0.4.0。

https://github.com/user-attachments/assets/8289f982-09d3-45df-9ce7-5f7723c0da52

[查看本版软件包与版本说明](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v0.4.0)

## 应用截图

工作台与作品库截图更新至 v0.4.0，使用独立演示工作区，不连接键盘；Mac 与 Windows 共用这套界面。其余截图标明对应页面，八款外观比较图使用同一预览引擎、同一作品与同一帧。

### 灯效工作台

点击预览左侧的键盘小图切换外观，整机画面随可用空间放大。AI 创作常驻工作台，预览下方与三个槽位并排，右侧集中调整作品参数；常用操作尽量在一屏完成。

![带 AI 与参考图入口的灯效工作台](docs/screenshots/workbench-v040.jpg)

### 模型配置

左侧「模型配置」与灯效工作台并列，支持 Kimi Code / 开放平台、MiniMax 和 DeepSeek，分别保存服务、区域、模型和密钥。API Key 默认隐藏，可点击旁边的「显示 / 隐藏」查看当前服务已保存的 Key。切换服务会保留各自的连接；Key 按服务直接保存在本机，不增加系统授权弹窗，工作台与作品 JSON 不包含密钥。

![多服务与模型设置](docs/screenshots/model-services-v030.png)

### 键盘外观预览

工作台「参考外观」提供 8 款，直接点击预览左侧的键盘缩略图切换，当前外观高亮显示；小图下方以 `R6「Vision」` 等简洁名称标注，窄屏时排列为可横向滚动的图条。全部统一为正面整机的去背景画面。R4 与 R6 的「Vision」按型号分别提供，R6 使用最早提供的正面实拍；切换只影响观看，不修改作品或设备。

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

已纳入官网仍保留的售罄配色素材，参考外观与实时库存无关。[官网素材来源与检索范围](data/photos/official-photo-sources.json)

![八款正面整机预览，同一作品与同一帧](docs/screenshots/appearance-gallery-v030.png)

### 灯效作品库

内置 8 款作品，涵盖红黑球星卡、人物动作、赛博字标与抽象光效。浏览像素缩略图、配色、动画帧数与循环时长，进入工作台预览；自定义作品支持命名、移入回收站和恢复。

下图在八款作品中搜索「卡卡」，展示本次修订的三款内置作品。

![作品库筛选三款卡卡内置灯效](docs/screenshots/library-v040.jpg)

### 设备与配置

先读取完整配置 JSON，再选择需要恢复的内置模式，核对字段差异与备份后确认同步。页面同时列出数据来源和各槽位草稿；下图展示未连接演示工作区中的入口。

![设备与完整配置入口，演示工作区未连接键盘](docs/screenshots/device-configuration-v030.png)

## 下载与运行

| 文件 | 适用电脑 | 打开方式 |
| --- | --- | --- |
| `Cyberboard-Studio-0.4.0-macOS-AppleSilicon.zip` | Apple Silicon Mac，macOS 13 及以上 | 解压，将 `Cyberboard Studio.app` 放入「应用程序」，双击打开 |
| `Cyberboard-Studio-0.4.0-Windows-x64.zip` | Windows 11 x64；部分受 .NET 10 支持的 Windows 10 LTSC/Enterprise | 完整解压，双击 `Cyberboard Studio.exe`，保留旁边的 DLL 和 `resources` |
| `Cyberboard-Studio-0.4.0-Windows10-Compatibility-x64.zip` | 遇到明确 CET 启动兼容错误、暂时无法更新系统的旧 Windows 10 x64 | 独立解压到新目录；仅此包取消 App 的 CET 标记，普通包保持 CET |

软件包均带 CLI 和运行环境，无需自己安装 Python。Windows 缺少 WebView2 时，运行包内 `Dependencies/MicrosoftEdgeWebview2Setup.exe`，联网安装后重新打开应用。

当前版本为 [v0.4.0 预览版](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v0.4.0)，软件包与对应 SHA-256 校验文件在该版本的 **Assets** 中。[v0.3.0](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v0.3.0)、[v0.2.2](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v0.2.2)、[v0.2.1](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v0.2.1)、[v0.2.0](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v0.2.0) 与 [v0.1.0](https://github.com/maestrokaka/cyberboard-studio/releases/tag/v0.1.0) 保留作为历史版本。Mac 包为本机 ad-hoc 签名，尚未用 Apple Developer ID 签名或公证；系统可能提示无法验证开发者，可参照 [Apple 的应用打开说明](https://support.apple.com/en-gb/102445)。Intel Mac 尚未提供构建。Windows 版已交叉编译并通过离线检查，原生启动、本机 Key 保存与旧配置迁移、真实 USB 通信尚待 Windows 实机验证。

Windows 优先使用普通包。遇到「Unknown Hard Error」时，先运行包内「诊断启动.cmd」，不要仅凭弹框换包；只有退出码与日志明确指向 CET 兼容问题时，才考虑兼容包。优先安装系统累计更新后继续使用普通包，具体见[启动故障处理](docs/USER_GUIDE.md#faq)。

仓库与已发布版本公开可访问，无需登录即可查看源码、截图和下载软件。

v0.4.0 新增三款卡卡、初号机和故障字标预设，共 8 款内置作品。卡卡改稿分别优化脸部比例、清除 `KAKA 22` 前的多余斜线、补清暗色头部轮廓；把这些经验整理进有图 / 无图创作提示词。复杂主体支持最多 40×64 高画布，按比例宽幅快滚并安排识别停留；全局配色检查和预览延续原始 RGB，减少意外暗淡与异色泛白。模型 Key 按服务直接保存在本机，默认隐藏、一键查看。[设计过程与提示词改进](docs/LIGHTING_DESIGN_NOTES.md)

v0.3.0 新增 MiniMax、DeepSeek 模型连接与按模型区分的参考图支持；增加 7 款官网 R4 配色，连同最早实拍的 R6「Vision」共 8 款参考外观，通过左侧键盘缩略图切换。AI 创作、预览、参数与槽位操作整合到工作台，并加入首次配置、指定内置模式恢复及 Windows 启动诊断与端口异常处理。

## 当前功能

- AI 文字 / 参考图创作：最多 3 张图片，生成顶部与轴灯新动画，校验后自动入库预览。
- Kimi Code / 开放平台、MiniMax、DeepSeek 连接与服务检查，Key 按服务在本机独立保存，默认隐藏、点击即可显示，不另加系统授权。
- 独立「模型配置」页面，各服务可选官方模型或填写自定义模型 ID；仅支持视觉的模型接收参考图。
- 8 款内置作品：裂隙超载、数据暴雨、红线竞速、初号机 · 拘束解除、故障字标 · 终端夺权、卡卡 · 红黑22、卡卡 · 极速突破、卡卡 · 圣西罗之夜；顶部与轴灯独立帧序列。
- 8 款 R4 / R6 参考外观，包括两个型号各自的「Vision」；通过键盘缩略图切换并高亮当前选择，统一为去背景的正面整机预览，显示顶部及轴灯投影，记住所选外观。
- 暂停、时间轴、亮度、节奏和配色变体；不透光键帽用键缝微光表现轴灯，透明键帽保留透光观感。
- 作品命名、按显示名称导出 JSON、作品库与回收站；底部三个槽位选择目标、预览槽位内容和撤销草稿。
- R4 / R6 设备身份检查、81 个实体键的 7 层键位读取、时间同步。
- 同步前创建完整配置备份和计划，用户确认后传输，检查设备确认及全部键码读回。
- 灯效计划读取并保留设备当前完整键位；本机旧记录提供灯效和其他槽位，不用旧键码覆盖现有按键。
- 单独同步当前 `01 / 02 / 03` 槽位，或明确同步全部待同步草稿；单槽完成后保留其他草稿。
- 没有原 CLI 记录时，先查看首次配置的完整替换范围，再明确初始化；默认内置电量、马赛克、时钟开启，文字与流光关闭。
- 读取完整配置 JSON 后只选择需要恢复的内置模式，查看字段差异、同步前备份和来源，再确认写入；保留其他页面、当前键码和槽位草稿。
- 本地历史与恢复计划。

v0.2.0 已接入 Kimi，同时保留本地模板变体、外部 AI 创作规格导出与作品 JSON 导入。当前 CLI 不支持固件升级。

创作提示词提供角色微动作、渐变、自然、文字、游戏、光轨等方向，按本次主题组合，不套用固定场景模板。App 自动编排新作品的节奏与时长，也可在描述里直接写「4 秒循环」；当前预览作品的播放速度不会限制新创作。内部 AI 输出由本地编译成完整灯效，外部提示词则要求完整 Studio 作品 JSON。[提示词与格式说明](docs/USER_GUIDE.md#creative)

在左侧「模型配置」选择服务、区域和模型，输入自己的 API Key 并保存；回到工作台常驻的 AI 创作区，点击制作按钮（显示当前服务名称）：

- **没有参考图：** 直接写想看到的效果，例如「橙红火焰从底部窜起，轴灯像余烬，4 秒循环」。不必手写像素、帧数或运动参数。
- **有参考图：** 添加 1–3 张图片，补一句希望保留和怎样动，例如「让图中的猫眨眼，保留橙白配色，轴灯柔和呼吸」。需要支持图片的模型，也可只上传图片开始制作。

默认不沿用上个作品的名称、描述或配色。需要借用其风格时，在「更多工具」中主动勾选「使用当前作品风格」；本次描述与参考图仍优先。图片只保留在当前会话，不发送设备配置、键位或整份草稿。

生成后会检查灯光可见性和动画数据；格式或明显可见性问题最多触发一次修复请求，通过后入库预览。这些检查不评价审美，也不能保证还原参考图，仍需看完顶部与轴灯的整个循环，再决定是否同步。制作不会自动放入槽位或写入 USB；修复是额外模型调用，失败或取消也可能产生费用。完整步骤见[AI 创作说明](docs/USER_GUIDE.md#creative)。

默认 Code 模型为 `k3`，下拉可选择 `k3`、`k3-256k`、`kimi-for-coding` 或 `kimi-for-coding-highspeed`；开放平台默认 `kimi-k3`。两种服务都可选择「自定义模型…」填写有权限使用的官方模型 ID，使用不同密钥和额度。MiniMax 与 DeepSeek 使用各自的 API Key，不能混用 Kimi 密钥。[Kimi 模型配置](https://www.kimi.com/code/docs/kimi-code/models.html)

MiniMax 默认 `MiniMax-M3`，DeepSeek 默认 `deepseek-flash`，均支持参考图；下拉也提供其他官方模型和自定义 ID。DeepSeek Pro、MiniMax M2.7 等文字模型会明确阻止带图提交，未知自定义模型按纯文字处理。MiniMax `MiniMax-M3.1-Flash-Preview` 需对应 M Plan / Code 权限。[MiniMax 官方接口](https://platform.minimax.cn/docs/api-reference/text-openai-api) · [DeepSeek 模型能力](https://api-docs.deepseek.com/quick_start/pricing/)

AI 根据素材设计图案和时间轴：五行能辨认的角色适合少而精的眨眼、摆动等微动作；需要完整高造型时，可用最多 40×64 的像素图按需滚动。宽幅角色优先让实际轮廓占约 34–38 列，保持比例，缩短空场，并给脸、标志或文字留清楚的停留；抽象、静态与微动作作品采用适合各自主题的结构。真实顶屏始终只有 40×5，模型输出的有限配方由本地编译，不执行任意代码。

本轮 v0.4.0 的预设与提示词改进通过离线检查和动态预览，未重新调用真实模型 API，也未写入 USB。此前 macOS 已实际验证 Code 密钥保存、连接检查、`kimi-for-coding` 在线生成，以及 `k3` 结合参考图制作作品；R6 第 3 槽已完成实际传输、设备确认和全部键码读回核对，并查看实拍灯效。MiniMax、DeepSeek、R4 写入，以及新增首次配置与内置模式恢复尚未完成对应真实账户 / 硬件验收；协议、图片处理、动画编译和交互另有离线检查。Windows 原生启动、本机 Key 迁移和真实 USB 仍待 Windows 实机验证。Kimi 官方将 Code 会员接口用于编程工具，产品集成推荐开放平台；本 App 保持真实客户端身份，实际权限与可用性以平台为准。[Kimi 官方接入说明](https://www.kimi.com/code/docs/)

启动应用与播放预览不会自动调用模型、探测或写入 USB。软件包不包含个人设备配置、键位读取记录或历史。

## 第一次同步

灯效像素不能从键盘读回，软件必须有这把键盘此前成功写入后保存的完整 CLI 记录，才能保留其他槽位。准备计划时重新读取当前设备的全部键位，用它们合并目标灯效；旧记录的键码与当前不同，不需要为了改灯效重置按键。普通「导入灯效」仅添加作品，不建立设备基线。

- 在原 Mac 上，记录通常位于 `~/.local/share/cyberboard-cli/devices/AM01R6/`；R4 使用自己的产品 ID。保留 `current.json` 和 `meta.json`，不要改写身份。
- 在同一台 Mac 上，发布版沿用原 CLI 设备记录，可以直接检查连接并准备同步。
- 移到 Windows 时，关闭 App，双击包内「迁移原配置.cmd」，粘贴原设备目录或 `current.json` 的完整路径。工具校验结构与 CRC，拒绝覆盖已有记录，不操作 USB。详细步骤见[完整使用说明：首次同步](docs/USER_GUIDE.md#baseline)与 [Windows 包内说明](windows/release-readme.txt)。
- 在另一台 Mac 上，将可信记录复制至对应 CLI 设备目录，关闭 App 后复制，随后重新打开。

连接后先检查设备身份与键位，在工作台底部选择目标槽位，将当前作品放入或更新草稿，再点「同步槽位 0N」查看计划；一起修改多个槽位时使用「同步全部 (N)」。点击槽位卡只改变目标，要查看卡中的作品则点「预览」。确认写入后保持 USB 连接，等待提交和验证完成。

「刷新连接」只更新读取结果，不把键位写回设备或改写本机 `current.json`。新版计划分别保留原记录与当前键位的来源，显示差异和本次按键重映射为零；执行前会重新检查。升级前准备的旧计划需要关闭后重新准备。只有设备确认及全部 1,400 个键码读回一致，才把成功目标记录为当前配置。灯效仍来自上次写入记录，不能通过刷新恢复实际 LED 像素。

没有可信原记录的新用户可先预览、导出作品、读取键位和同步时间；也可在 App 中选择「准备首次配置」，核对全部三个槽位及内置页面的替换范围后，明确建立新的完整记录。此操作不能读回、备份或恢复未知的原灯效。保留旧灯效请优先迁移同一把键盘的可信记录，完整步骤见[首次配置说明](docs/USER_GUIDE.md#first-setup)。

恢复电量、马赛克或时钟时，在「设备与槽位」先「读取配置 JSON」，勾选需要的部分，再「准备修改计划」。完整来源是本机成功写入记录加本次设备全部键码；所选页面使用官网通用模板，不是这把键盘的出厂状态读回。核对字段差异和备份后再执行，其他槽位及草稿保留。

## 本机数据

| 数据 | macOS | Windows |
| --- | --- | --- |
| 作品、回收站、草稿、计划、备份、无密钥连接设置 | `~/Library/Application Support/Cyberboard Studio/` | `%LOCALAPPDATA%\Cyberboard Studio` |
| CLI 设备记录 | `~/.local/share/cyberboard-cli/devices/` | `%LOCALAPPDATA%\cyberboard-cli\devices` |

`CYBERBOARD_DATA_DIR` 可显式指定 CLI 记录目录。用户数据与应用安装目录分开保存。`ai-settings.json` 仅保存服务、地址和模型；两平台均在 Studio 数据目录的 `ai-keys/<服务>.key` 中直接保存 Key，不另加加密或系统授权。旧钥匙串 / DPAPI 记录只作无弹窗兼容迁移；迁移不到时直接重新输入保存即可，旧记录不会被删除。参考图不会写入这些数据文件。

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
STUDIO_UI_PLATFORM=windows node tests/ui-check.cjs
.tools/macos-build/bin/python tests/backend-check.py
.tools/macos-build/bin/python tests/ai-recipe-check.py
.tools/macos-build/bin/python tests/kimi-ai-check.py
.tools/macos-build/bin/python tests/kimi-ai-extra-check.py
.tools/macos-build/bin/python tests/multi-provider-ai-check.py
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

改好的代码提交并推送到 `main`。可下载软件放在 Releases，使用新的版本号保存更新说明、macOS / Windows 软件包及校验文件；无需把编译缓存或运行库加入 Git 历史。[GitHub Releases 说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)

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
