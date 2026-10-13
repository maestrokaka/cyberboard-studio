Cyberboard Studio 0.1.0 · Windows x64 桌面版

开始使用
1. 把整个 ZIP 解压到一个普通文件夹，例如 D:\Apps\Cyberboard Studio。
2. 双击 Cyberboard Studio.exe。请保留同目录所有 DLL 与 resources 文件夹。
3. 如果提示缺少 WebView2，运行 Dependencies\MicrosoftEdgeWebview2Setup.exe，
   按 Microsoft 安装向导完成后，重新打开应用。此步骤需要网络。

推荐使用 Windows 11 x64。此包也面向仍受 .NET 10 支持的 Windows 10 LTSC/
Enterprise 版本；普通 Windows 10、ARM64 原生版和 32 位版尚未验证。
无需安装 Python、CLI 或 .NET：这些运行组件已附在软件包中。
本应用尚未进行商业代码签名。请使用本包提供的 SHA256SUMS 和发布校验文件
核对来源；本包不会设置防火墙、自动启动、计划任务或自动升级。

你可以直接预览与导出
• 已有的裂隙超载、数据暴雨、红线竞速三套作品。
• 实体键盘顶部与轴灯动画、整机与键盘特写、亮度、节奏和配色变体。
• JSON 原生导入导出、作品库、草稿保存。
• 检查 USB 连接后读取设备身份、固件与 81 个实体键的 7 层键位。
• 连接后同步系统时间。固件升级功能不在当前 CLI 中。
启动和打开预览不会自动连接或写入键盘。写入灯效仍需先查看同步计划，
再明确点击“同步到键盘”。底层继续使用完整配置备份、协议确认及键位读回。

从 Mac 带入这把键盘原来的配置（首次同步之前）
Windows 包不预置任何人的设备配置或历史。键盘不能读回灯效像素，所以
需要迁移这把键盘此前通过 CLI 成功写入后保存的完整记录，才能安全保留
其他槽位和键位。普通“导入灯效”只添加作品，不建立原配置记录。

1. 在 Mac 关闭 App 和 CLI，运行：
   .tools/cyberboard-cli/bin/cyberboard store path --device AM01R6
   复制返回的设备目录内 current.json 与 meta.json，保持它们放在同一文件夹。
   原目录通常为 ~/.local/share/cyberboard-cli/devices/AM01R6。
   R4 请把 AM01R6 替换成这把键盘实际的产品 ID，不要改写 meta.json。
2. 把这个文件夹带到 Windows（例如用 U 盘），关闭 App。
3. 双击“迁移原配置.cmd”，粘贴设备文件夹或 current.json 的完整路径。
   工具校验完整结构与编码 CRC，拒绝覆盖已存在的当前库；只复制本机记录，
   不探测或写入 USB，不复制锁文件或旧操作计划。
4. 重新打开 App，点击“检查连接”。确认读到正确设备后，即可准备同步。
   同步计划还会核对这把键盘当前的全部键位与迁移配置，异常时停止操作。

USB 连接
• 用能传输数据的 USB 线连接键盘，先关闭其他正在占用键盘的配置软件。
• Windows 通过 COM 口识别设备（例如 COM12），并核对真实键盘产品身份。
• 如果未发现设备，检查 Windows 设备管理器的“端口（COM 和 LPT）”。
  本软件不随包安装第三方 USB 驱动；请使用硬件厂商提供的驱动说明。
• 同步时保持 USB 连接，等待设备提交和键位校验完成；应用会阻止中途刷新/退出。

本机数据
• 工作台与备份：%LOCALAPPDATA%\Cyberboard Studio
• CLI 设备记录：%LOCALAPPDATA%\cyberboard-cli\devices
• 如显式设置了 CYBERBOARD_DATA_DIR，CLI 设备记录跟随该目录。
• 出错日志：%LOCALAPPDATA%\Cyberboard Studio\logs\host.log
删除或替换解压目录不会删除这些用户数据。

验证情况
这是在 Mac 上交叉编译的 Windows x64 版本。编译、共享界面测试、Windows
COM/锁/时区离线模拟、迁移测试、依赖校验与 PE 架构检查已完成。
本机没有 Windows 环境，Windows 原生启动与真实 USB 通信尚待实机验证。
“检查运行环境.cmd”只检查版本、时区、配置存储组件，不访问 USB。

运行组件和许可证
Microsoft .NET 10 / WinForms、WebView2 SDK、Python 3.12.10、Cyberboard CLI
0.1.2、pyserial、jsonschema、Pillow、tzdata 与传递依赖随包提供。
许可证见 licenses、resources\python\LICENSE.txt、THIRD-PARTY-NOTICES.txt
及各 Python 依赖的 .dist-info 目录。原版照片和设计作品沿用本项目资源。

官方运行环境说明：
https://learn.microsoft.com/en-us/dotnet/core/install/windows
https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution
