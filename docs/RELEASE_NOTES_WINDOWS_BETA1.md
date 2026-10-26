# MiaoCall · Windows Private Beta 1

版本：`1.0.0-miaocall.windows.beta.1`。[Windows x64 私有测试版与 SHA-256](https://github.com/maestrokaka/cyberboard-studio-miaocall/releases/tag/v1.0.0-miaocall.windows.beta.1) 已提供下载；仅同步私有仓库，macOS Tasks Private Beta 3 与公开 Beta 14 保持原样。

## 本次变化

- Windows 接入喵唤通用 Codex 任务：工作目录、文字或语音指令、持久记录、继续追问、执行中补充、逐次授权、结果与文件。
- 新增「连接本机 Codex」：安装官方原生 CLI、浏览器登录、检测连接和手动选择程序。独立安装路线不要求 Node.js 或 WSL，不读取或复制登录文件。
- 原生桌面喵娘支持常驻 / 仅唤醒、拖动记位置、主题气泡、服装与长发、停留互动及可关闭的四种离线声线；AI 换装先预览再应用。
- Windows 物理按键按住录音、松开识别、确认后交给 Codex；默认关闭，退出时释放。语音识别与 Codex 登录分别配置。
- 保留两种主题、AI 对话与版本、十款预设、独立外观选择、键位编辑、三槽草稿及同步审核；不因安装或升级自动写入键盘。
- Windows 的任务工具使用本机 Codex 配置。没有复制 macOS 专用 Spotify 播放验证，未接入的其他 Agent 仍明确标为规划中。

## 安装与开始

完整解压 Windows x64 ZIP，打开 `Cyberboard Studio.exe`；缺少 WebView2 时运行随包安装器。随后在「喵唤 · Beta」→「语音任务」依次安装、登录、检测 Codex，先用只读文字任务验证，再配置语音和快捷键。[完整 Windows 指南](MIAOCALL_WINDOWS.md)

## 验证范围

- 17 组本机离线套件通过。
- 两个实际 ZIP 各通过 14 项包检查；包内预览通过 64 组比例检查。
- Windows CI 通过 40 组宿主检查和 2 项进程探活，包含 Job Object 所属子进程回收及不误杀无关进程的检查。
- Windows CI 实际安装官方 `codex-cli 0.164.0`，未刷新 PATH 即自动发现默认路径。真实 app-server 初始化与 `account/read` 返回已安装、协议就绪、未登录；没有登录用户账户、启动模型轮次或执行 Codex 工具。
- Linux / Mac 通用 CI 通过。

[Windows CI](https://github.com/maestrokaka/cyberboard-studio-miaocall/actions/runs/40306014974) · [Linux / Mac CI](https://github.com/maestrokaka/cyberboard-studio-miaocall/actions/runs/40306014874)

本版仍需个人 Windows 电脑验收原生窗口与桌面拖动、透明点击区域、真实麦克风、全局快捷键、用户浏览器登录、实际 Codex 任务和 USB。进程探活和未登录接口检查不能替代这些验收；本版不是稳定 1.0 正式版。

不附桌面演示视频、私人音频、声纹源素材、Key 或用户工作区。历史 Mac 包与公开发布附件不变。
