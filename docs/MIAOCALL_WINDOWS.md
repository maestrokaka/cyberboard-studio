# 喵唤 Windows · Private Beta 1

> 当前公开与私有发行版为 [Beta 15](RELEASE_NOTES_BETA15.md)。以下保留各功能的详细说明；涉及旧私有版本、下载包或仅限私有发布的描述，以 Beta 15 更新说明和仓库首页为准。

版本：`1.0.0-miaocall.windows.beta.1`。[Windows 私有测试包与 SHA-256](https://github.com/maestrokaka/cyberboard-studio-miaocall/releases/tag/v1.0.0-miaocall.windows.beta.1) 已提供下载；macOS 继续使用 Tasks Private Beta 3。Windows 真机的窗口、麦克风、全局按键、Codex 登录和 USB 尚待验收。

喵唤把你确认后的文字或语音交给本机 Codex，适合整理文件、总结资料、修改项目等任务。每个任务有自己的工作目录、记录与后续追问。实际可执行的操作取决于 Codex 已配置的工具和连接；本版没有接管其他 Codex 桌面聊天。

## 安装软件

1. 从 [Windows Private Beta 1 发布页](https://github.com/maestrokaka/cyberboard-studio-miaocall/releases/tag/v1.0.0-miaocall.windows.beta.1) 下载 Windows x64 ZIP 和对应 `.zip.sha256`，核对校验值。不要下载 Source code 代替安装包。
2. 将整个 ZIP 解压到普通目录，例如 `D:\Apps\Cyberboard Studio`，运行 `Cyberboard Studio.exe`。保留旁边所有 DLL、`resources`、`Dependencies`。
3. 若提示缺少 WebView2，运行随包的 `Dependencies\MicrosoftEdgeWebview2Setup.exe`，按 Microsoft 安装向导完成后重开。

推荐 Windows 11 x64。程序自带 Python、Cyberboard CLI 和 .NET 运行组件；**Codex 是另外安装的官方程序**，不随包复制账户或登录资料。没有 Windows 32 位、ARM64 原生包。此测试包没有商业代码签名，不修改系统的防火墙、计划任务或自动启动设置。

Windows 10 Compatibility 包仅用于已确认的 CET 启动兼容问题，不扩大 .NET 或 Codex 的系统支持范围。先使用普通包，启动异常时按下面的诊断步骤定位；不要混用两种包的文件。

## 连接 Codex：安装 → 登录 → 检测

打开「喵唤 · Beta」→「语音任务」，找到「连接本机 Codex」。已有官方 CLI 的用户可以先点「检测连接」。

| 入口 | 会发生什么 |
| --- | --- |
| **安装 Codex** | 展示来源并由你确认后，打开 PowerShell 运行 OpenAI 官方独立安装器，为当前 Windows 用户安装。 |
| **登录** | 由本机 Codex 打开官方浏览器登录页。密码只在官方页面填写；喵唤等待登录完成并重新检查状态。 |
| **检测连接** | 检查本机程序、app-server 连接和登录状态，不启动模型任务。 |
| **手动选择** | 自动查找失败时，选择官方安装目录中的原生 `codex.exe`；不要选择 `.cmd` 或 `.ps1` 包装脚本，也不要只搬走 EXE。 |

官方独立 CLI 可以在 Windows 原生运行，这条安装路线无需先配置 Node.js 或 WSL。安装按钮与「复制官方安装命令」采用以下官方命令；执行策略参数仅作用于这次 PowerShell 进程。[Codex CLI 官方说明](https://learn.chatgpt.com/docs/cli)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

安装完成后回到软件再点「检测连接」。默认会检查 `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe` 等原生路径，当前 App 不必依赖刚更新的 PATH。安装路径与部署选项见 [Windows 官方部署说明](https://learn.chatgpt.com/docs/enterprise/windows-deployment)。

Windows 桌面版与原生 Codex CLI 默认使用同一个 `%USERPROFILE%\.codex`。已有登录能否复用由官方接口返回结果决定；如果只安装了桌面版、尚未找到独立 CLI，先使用这里的安装入口。喵唤不读取或复制 `auth.json`，也不要求填写 Codex API Key。[Windows 桌面版说明](https://learn.chatgpt.com/docs/windows/windows-app) · [官方 app-server 接口](https://learn.chatgpt.com/docs/app-server)

### 首次任务提示初始化 Windows 隔离环境

先按官方 Codex 提示完成初始化，再回到喵唤。兼容设备可以使用 MXC；旧系统的官方备用方式可能需要你或管理员确认 UAC。公司设备若受策略限制，请由管理员处理。本软件不会自动切到完全访问权限、关闭隔离或修改长期执行策略。[Windows 隔离环境官方说明](https://learn.chatgpt.com/docs/windows/windows-sandbox)

## 先完成一个文字任务

1. 点击「选择目录」，挑一个用于测试的文件夹。默认只读；确实要修改文件时，再勾选「允许修改新任务的工作目录」。
2. 输入任务，例如「总结这个目录中几份文档的共同结论」，必要时添加最多 8 个文件，然后点击「交给 Codex」。
3. 在任务详情查看执行步骤、答复问题或核对额外权限。授权按请求进行，软件不自动批准。
4. 检查结果和返回文件。选择已有任务后可继续追问；执行中可以补充文字指令。

点击「停止任务」或按 Esc 请求中断，等待停止结果；已经发生的修改不会自动撤销。「已返回结果」表示正式执行结束并返回了文字或文件，仍需检查是否满足你的要求。

Spotify 不是 Windows 版的固定任务目标。本版没有提供 macOS 的专用播放验证工具；不能把打开应用当作歌曲已经播放。WorkBuddy、千问办公、豆包工作仍为规划入口。

## 再开启语音

在「模型配置」单独配置 MiniMax、千问或 OpenAI 的语音识别服务。**Codex 登录与语音识别服务是两条连接**；文字任务不需要语音 Key。AI 创作输入框的「语音输入」也使用该语音配置，转写完成后由你手动发送灯效创作。

开启「按键唤起」后，按住 Esc 下方的物理「·」键，看到「正在听你说」再开口，松开后识别。确认文字后再交给 Codex，也可用页面的按住说话按钮。快捷键默认关闭，退出 App 自动释放；关闭时按键正常输入。

无声或麦克风不可用时，到 Windows「设置 → 隐私和安全性 → 麦克风」检查麦克风及桌面应用访问，并确认系统默认输入设备。全局快捷键不需要 macOS 的“输入监控”授权；锁屏、安全桌面或其他高权限应用中的行为仍以 Windows 实机测试为准。

录音最长 60 秒，只在明确操作后采集，取消或结束后清理；不进入任务记录、作品或工作区。遇到超时不会自动重发录音。服务 Key 按服务保存在普通本机文件，界面默认隐藏并可显示；不读取或迁移旧 DPAPI 记录。

## 桌面喵娘

- 可选「常驻」或「仅唤醒」，常驻不等于开启录音。直接拖动桌面角色可改变位置；设置页中的角色图只作预览。
- 三套服装，水手服另有长发选项；每组 8 个姿势，共 32 张。角色大小、服装和桌面位置在本机保留。
- 15 处停留互动，甜萌、御姐、温柔、元气四种声线，共 60 条离线音频。声音默认关闭；拖动、录音、转写和任务期间暂停闲聊。
- 浮层随「经典深色 / 暖岛浅色」主题切换。需要确认语音时可在气泡里修改文字；任务授权或问题在任务详情中处理。
- AI 换装单独配置 MiniMax image-01；主动生成后先预览，再决定穿上。生成衣装当前是一张静态立绘，不自动产生整套姿势。

## 数据与故障排查

App 数据在 `%LOCALAPPDATA%\Cyberboard Studio`，CLI 设备记录在 `%LOCALAPPDATA%\cyberboard-cli\devices`。喵唤任务在前者的 `agent-tasks` 目录，衣橱、语音连接、桌面偏好和灯效工作区分别保存。安装目录与个人数据分开；升级前关闭旧 App 并备份个人数据，备份可能含 Key，不要公开上传。

| 现象 | 处理方式 |
| --- | --- |
| 找不到 Codex | 使用「安装 Codex」完成官方安装，再检测；自定义位置用「手动选择」选原生 EXE。 |
| 已安装桌面版仍未连接 | 先确认独立 CLI 可被找到；点击登录或检测，由官方接口判断已有登录。不要手动复制认证文件。 |
| 登录页打开后未完成 | 在官方浏览器完成登录，回 App 查看结果；取消或超时后可重新开始，不反复同时开启多个登录流程。 |
| 连接成功但任务初始化失败 | 按官方 Codex 提示处理 Windows 隔离环境；管理员限制由管理员检查。连接检查不等于所有任务工具已就绪。 |
| 语音失败，但文字任务成功 | 检查单独的语音模型、Key、区域、网络与默认麦克风；不需要重装 Codex。 |
| EXE 无窗口或立即退出 | 在完整解压目录运行「诊断启动.cmd」；不要只复制 EXE。缺少 WebView2 时安装随包引导程序。 |
| 任务报错或中断 | 在任务详情查看错误，可复制不含正文与 Key 的诊断；核对已发生的操作后再继续，不盲目重做。 |

反馈时附版本、Windows 版本、复现步骤和脱敏截图；不要发送 Key、录音、认证文件或整个个人数据目录。Windows 原生窗口、真实麦克风、按键监听、官方登录及 USB 写入仍是本 Beta 的实机验收项目；离线协议通过不能替代这些检查。

## 本版验证记录

- 17 组本机离线套件通过；两个实际 ZIP 各通过 14 项包检查，包内预览通过 64 组比例检查。
- Windows CI 通过 40 组宿主检查与 2 项进程探活，包括 Job Object 回收所属子进程，以及不误杀无关进程的检查。
- Windows CI 实际安装官方 `codex-cli 0.164.0`，不刷新 PATH 即发现默认安装路径；真实 app-server 的 `initialize` / `account/read` 返回 `installed=true`、`protocolReady=true`、`authenticated=false`。这次没有登录用户、启动模型轮次或执行 Codex 工具，用户官方浏览器登录仍待实机。
- Linux / Mac 通用 CI 通过。真实 GUI 操作、麦克风、全局快捷键、用户登录和 USB 仍待个人 Windows 电脑实测。

[Windows CI 记录](https://github.com/maestrokaka/cyberboard-studio-miaocall/actions/runs/40306014974) · [Linux / Mac CI 记录](https://github.com/maestrokaka/cyberboard-studio-miaocall/actions/runs/40306014874)
