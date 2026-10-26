Cyberboard Studio 1.0.0-miaocall.windows.beta.1 · Windows x64 私有测试版

第三方怒喵（Angry Miao）键盘工具，面向 CYBERBOARD R4 / CYBERBOARD R6。
本版将喵唤通用 Codex 任务与桌面喵娘接入 Windows。仍为私有 Beta，Windows
原生窗口、麦克风、全局快捷键、Codex 登录与真实任务、USB 和 R4 写入待实机验收。
本次不替换 macOS Tasks Beta 3，也不修改公开仓库和公开 Beta 14。
完整指南与验收范围：
https://github.com/maestrokaka/cyberboard-studio-miaocall/blob/feature/miaocall-companion/docs/MIAOCALL_WINDOWS.md
https://github.com/maestrokaka/cyberboard-studio-miaocall/blob/feature/miaocall-companion/docs/RELEASE_NOTES_WINDOWS_BETA1.md

下载与安装
1. 整个 ZIP 解压到普通目录，例如 D:\Apps\Cyberboard Studio。
2. 运行 Cyberboard Studio.exe，保留旁边所有 DLL、resources 和 Dependencies。
3. 若缺 WebView2，运行 Dependencies\MicrosoftEdgeWebview2Setup.exe，
   联网按 Microsoft 向导安装后重开 App。不要直接在 ZIP 内运行或只复制 EXE。

推荐 Windows 11 x64；Windows 10 是否可运行还取决于 .NET 与 Codex 官方支持范围。
Intel Mac、32 位 Windows、Windows ARM64 原生包不在本包范围。
Python、Cyberboard CLI 和 .NET 运行组件已附，无需另外安装。
Codex 由下面的官方安装入口另外安装，不随包复制账户资料。此包没有商业代码签名，
请核对包内 SHA256SUMS 及 GitHub 对应 .zip.sha256。应用不设置自动启动、
防火墙、计划任务或自动升级。

先用普通 Windows 包。遇到 Unknown Hard Error 先运行“诊断启动.cmd”，
仅当日志明确出现 CET 兼容问题时，独立解压 Windows10 Compatibility 包测试。
兼容包只取消本 App 的 CET 标记，不修改系统安全设置，不扩大 .NET 官方系统
支持范围。优先更新系统后继续使用普通包，不要混用普通和兼容包的文件。

Windows Private Beta 1 本次更新
• 通用 Codex 任务：工作目录、文字或语音输入、持久记录、继续追问、执行中
  补充指令、逐次授权和结果文件。实际能力取决于本机 Codex 的工具和连接。
• “连接本机 Codex”提供安装、浏览器登录、检测和手动选择原生 codex.exe。
  默认原生 Windows 路线，无需先配置 Node.js 或 WSL，不读取或复制认证文件。
• 桌面喵娘支持常驻/仅唤醒、直接拖动、记住位置、浅深主题气泡、三套服装、
  长发选项、32个姿势和15处互动；四种离线声线共60条，默认静音。
• AI换装需单独配置MiniMax image-01，主动生成后先预览再穿上，可取消或删除。
  AI新衣装目前是静态立绘，不自动生成整套姿势。
• 按住物理“·”录音，松开识别，默认先确认文字再提交。快捷键默认关闭，
  退出时释放；常驻桌面不自动录音。AI创作输入框也支持独立语音转文字。
• 延续AI对话版本、两种主题、独立外观选择、可读Fn层与键位编辑、十预设、
  三槽草稿、回收站、JSON与同步审核。正常退出/重载先等待工作区保存。
• Windows不提供Mac专用Spotify播放验证工具；没有把通用任务限制为播放音乐。
  WorkBuddy、千问办公、豆包工作仍为规划入口。

快速连接 Codex
1. 进入“喵唤 · Beta”→“语音任务”，找到“连接本机 Codex”。已有官方CLI
   可先点击“检测连接”。文字任务不需要语音Key、麦克风或全局按键。
2. 未安装时点“安装 Codex”，核对官方来源并确认，按PowerShell窗口完成。
   这是当前用户安装；所用执行策略参数只对本次进程生效，不修改长期策略。
3. 点击“登录”，在官方浏览器页面完成ChatGPT登录。密码只在官方页面填写。
4. 回到App点“检测连接”。不在默认目录时用“手动选择”找到原生codex.exe，
   保留其旁边的运行时文件；不要选.cmd/.ps1，也不要复制auth.json。
5. 选择测试目录，默认只读。输入一个任务，点击“交给 Codex”。确实需要写
   文件时再勾选允许修改；收到额外权限请求时在任务详情核对并逐次答复。
6. 首次执行如果要求Windows隔离环境初始化，按官方Codex提示完成；旧系统
   可能需要管理员确认UAC。软件不关闭隔离、不静默改为完全访问权限。

“复制官方安装命令”复制OpenAI发布的独立CLI安装命令：
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
默认目录为 %LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe。
已经登录Windows桌面版时，由官方接口判断能否复用同一用户的登录。
检测连接成功不等于所有任务工具、网络或隔离环境都已初始化。
官方安装：https://learn.chatgpt.com/docs/cli
官方Windows部署：https://learn.chatgpt.com/docs/enterprise/windows-deployment
Windows隔离环境：https://learn.chatgpt.com/docs/windows/windows-sandbox

语音与桌面喵娘
先在“模型配置”保存MiniMax、千问或OpenAI的语音识别服务，再开启按键唤起。
按住Esc下方的物理“·”，看到正在聆听再说话，松开识别；确认文字再交给Codex。
无声时检查Windows“隐私和安全性→麦克风”的桌面应用访问和默认输入设备。
语音服务和Codex登录分别配置：文字任务可用但转写失败时，先检查语音连接。
录音最长60秒，音频只用于本次转写；结束/取消后清理，不进入作品或任务记录。
转写超时不会自动重发；停止任务不撤销已经发生的修改。

常驻与快捷键独立。角色可直接拖到桌面位置；设置页图片只作预览。
互动声音默认关闭，可选甜萌、御姐、温柔、元气；鼠标停留后才响应，拖动、
录音及任务时暂停闲聊。桌面气泡跟随设置中的经典深色/暖岛浅色主题。

五分钟体验
1. 无需 Key 或键盘：到“灯效工作台”，右侧选择预设播放、暂停、拖动时间轴。
2. 在“键盘与外观”选正面卡片；返回工作台或 AI 页。外观只影响观看，
   实际设备身份须通过“检查连接”确定。
3. 在“模型配置”选服务、区域和有权限的模型，输入 Key 并“保存并使用”。
4. 打开“AI 创作”，新建对话，写描述或加1–3张参考图，点“发送并制作”。
5. 生成后预览整个循环。继续修改时核对基础版本和范围，例如仅轴灯：
   “改纯黄，保留原动作，顶部不变”。每次形成新版本，旧版留存可比较。
6. 满意后明确保存指定版本，或“在工作台打开”；调整后再放入目标槽位。

模型配置与隐私
• Kimi Code 新连接默认 k3，开放平台 kimi-k3；MiniMax 新连接默认
  MiniMax-M3.1-Flash-Preview，DeepSeek deepseek-flash。已有手动选择保留。
  各服务的中国/国际地址、模型和Key独立。修改表单后需“保存并使用”生效。
• M3.1 Flash 需要相应套餐权限。MiniMax M3/M3.1、DeepSeek Flash及界面标明的
  视觉模型可以参考图；文字模型/未知 MiniMax、DeepSeek自定义ID不接收图片，
  选择文字模型会保留图片，需明确移除或换回视觉模型。
• API Key 默认隐藏，按钮直接显示/隐藏。Key只存 ai-keys\<provider>.key普通
  UTF-8本机文件；不增加系统保护、查看确认或系统凭据授权。不读取、解密、
  迁移或删除旧 credentials\<provider>.dpapi。只有旧记录时重新粘贴保存。
• ai-settings.json只保存服务/地址/模型。Key不进入会话、作品、JSON、日志、
  软件包或GitHub。备份整个数据目录会包含个人Key，不能公开分享。
• “测试连接”检查模型列表与凭据，不等于生成权限；列表接口不存在会明确
  说明需实际制作。Kimi Code的会员额度、开放平台的Key与额度不能混用。
  应用保持真实客户端身份，被限制时用官方支持方式或开放平台，不伪装。

文字、图片与多轮修改
无图例：“橙红火焰从底部窜起，轴灯像余烬，4秒循环。”
有图例：“完整角色从下向上快滚，保留橙白配色和耳朵，脸部稍停。”
可以只上传图片；使用基础版本时明确核对版本ID和范围。局部编辑需要带有效
AI配方的版本。全新创作自动编排节奏，范围仅顶部/仅轴灯时保留原整体时序。
角色可用最多40×64高画布经过真实40×5窗口，不能把复杂角色压扁到五行；
不同主题仍使用合适的微动作或抽象编排，不统一套快滚或固定模板。

参考图支持PNG/JPEG/WebP/GIF第一帧，原图每张最多20MiB、约3200万像素。
本地纠正方向、转sRGB、去EXIF/GPS，压为最长边1280像素、最多400KiB JPEG。
压缩图随本机会话保留，重启可回看；不写入作品JSON。发送本次描述、选中
图片、短文字回顾及明确基底配方；不发送原图路径/文件名、整份工作区、
键位或设备配置。风格参考只有主动勾选才加入另一个工作台作品的说明/配色。

停止或失败不接受半成品，不改变已有结果或槽位。错误“重试”恢复原输入、
图片、范围、基底和模型；换模型需明确选择，不自动切服务。结构/基本可见性
最多额外修复一次，仍不合格就拒绝。已提交、取消、超时和修复可能计费。
RGB检查不等于审美或实机色准，请看完整循环后决定是否同步。
最多20会话、每会话12版/60消息，整份工作区32MiB；超限先导出再整理，
不自动删旧记录。删除会话前导出未入库版本，已保存作品和槽位草稿保留。

作品、JSON和回收站
十款内置：裂隙超载、数据暴雨、红线竞速、EVA初号机·觉醒序列、故障字标·
终端夺权、马里奥·红帽闯关、猫逐萤火、卡卡·红黑22、卡卡·极速突破、
卡卡·圣西罗之夜。卡卡三款在最后，RGB和节奏延续已确认版本。
全部内置/自定义作品支持移入回收站、恢复和确认后永久删除；内置删除记录
重启/升级保留。删除作品会撤销引用它的草稿，不改变已写入键盘的灯效。
恢复作品不会恢复旧草稿。自定义在用最多30套，回收站合计最多30套。

工作台可命名自定义作品、调亮度与节奏、按名称导出完整JSON。
作品JSON适合分享，不含Key、参考图和对话。完整配置JSON含个人键位，
请勿随意公开。普通导入只提取灯效，不建立设备基线、不替换键位。
模板变体是本地工具，改变已有色系/节奏，不调用AI生成新剧情。

只同步一个槽位
1. 工作台打开作品/指定AI版本，调整参数。点击01/02/03卡选放入目标；
   只有卡内“预览”才加载槽位内容。选槽不会自动把该槽设为当前作品。
2. “放入槽位0N”或“更新槽位0N草稿”准备本机内容，再检查连接。
3. “同步槽位0N”核对计划仅改此槽，查看备份、来源和当前键位保留。
4. 明确“同步到键盘”，保持USB，等待提交、全键码验证及本机保存。
成功只清除本次槽草稿；其他保留。多个草稿一起写需明确“同步全部(N)”。
“撤销草稿”只撤销本机准备。底层合并并传完整配置，其他槽依赖可信记录。

原记录与首次配置
USB可读身份、固件和键码，不能完整读回灯效像素。正常单槽同步要有同一把
实体键盘此前成功CLI写入后的 current.json/meta.json。若用其他工具改LED，
本机记录可能过时，App不能从像素发现这类变化。

没有可信记录时可准备首次配置：选中草稿写入目标槽，其余槽停用黑屏；
电量/马赛克/时钟按官网标准开启，文字/流光按标准关闭。旧灯效、文字、
独立宏、交换键与换键表无法保留，特殊功能可能需重设。
读取并原样写当前1400键码、执行前再核对、提交后全读回验证；键码快照
不是旧完整配置备份。核对替换范围、勾选确认再建立配置；结果不确定时
保留计划按提示处理，不盲目再次初始化。

已有完整记录：设备页先“读取配置JSON”，只选择要恢复的内置模式，
或快速选择电量/马赛克/时钟，再准备计划。其他页、槽位及当前键码保留。
读取后内容变了需重读。不能编码的有效扩展字段会停止写入，可导出用官方工具。

从Mac迁入同一把键盘记录
1. Mac关闭App/CLI，从 ~/.local/share/cyberboard-cli/devices/ 找实际产品ID目录。
   R6通常AM01R6，R4以实际ID为准。带走同目录current.json/meta.json，不改写meta。
   显式设置过CYBERBOARD_DATA_DIR时用该记录目录。
2. Windows关闭App，运行“迁移原配置.cmd”，输入设备目录或current.json路径。
3. 工具核结构和编码CRC，拒绝覆盖现存当前库，不访问USB或复制旧锁/计划。
4. 打开App检查正确设备。计划保留记录灯效并读取全部当前键码，不用旧码
   覆盖按键。不是同一实体键盘时不能使用另一把键盘的记录。

USB、键位与时间
使用能传数据的USB线，关闭AM_Master和其他配置程序。Windows识别COM口并
核对产品身份；一个端口超时继续检查其他端口，已知多设备不误选。
键位不完整时不能显示连接成功。设备管理器可查看“端口（COM和LPT）”。
本包不安装第三方USB驱动，以硬件厂商说明为准。
独立“键位编辑”页显示81实体键/7层可读功能，先改本机草稿，再通过专用计划
核对全部1400键码、设备/固件和可信灯效基线后写入；未知原始码保留。
“同步记录”查看本机历史。键位写入与灯效同步是不同计划，不自动混用。
时间同步使用电脑当前时刻和 Asia/Shanghai（UTC+8），没有时区选择。
当前CLI不能升级固件。写入期间正常刷新/退出受保护，等待提交验证完成。

本机数据与升级
%LOCALAPPDATA%\Cyberboard Studio：workspace.json、会话/图片/版本、作品/
草稿/回收站、backups、plans、ai-settings.json、ai-keys和按需logs\host.log。
还包含agent-tasks、agent-task-settings.json、语音连接/Key、companion-outfits、
companion-image.key、companion-desktop.json与companion-position.json。
这些个人文件不进入源码或发布包；Codex官方会话由Codex自身保存。
%LOCALAPPDATA%\cyberboard-cli\devices：CLI完整配置及历史。
显式CYBERBOARD_DATA_DIR会改变CLI记录目录。安装目录与数据目录分开。

升级前关闭App备份两数据目录；首次v2保存保留workspace-before-1.0.json。
不要同时运行新旧版访问同一工作区。退回旧版前先备份新数据，再明确恢复
升级前工作区；旧版不识别新会话。历史包可从GitHub Releases获取。
删除/替换安装目录不删除用户数据。数据目录含Key和私人参考图，不能整包公开。
保存失败请留在App导出重要版本并修复存储。退出/重载会等待保存，失败有重试入口。

启动诊断
关闭旧窗口，在EXE同目录运行“诊断启动.cmd”。报告在控制台给出的
%TEMP%\Cyberboard-Studio-startup-日期-随机编号目录。保留summary.txt、
app-host-trace.log、app-stdout.txt、app-stderr.txt与probe-*，可区分运行时和窗口。
超过15秒仍运行只是尚未判断，可能等系统弹框；工具不强制关进程。
只收集系统/架构、固定组件哈希和本次输出；不读Key、工作区、原host.log，
不访问USB或改系统。报告可能含本地路径，反馈前自行去隐私。
“检查运行环境.cmd”只验Python/CLI/时区/存储，不能证明主窗口或USB可用。

验收范围
Windows宿主交叉编译和39组离线宿主检查已在Mac运行通过。协议、录音数据、
取消和任务授权使用合成子进程；这不代表Windows原生权限、真实录音或真实
Codex浏览器登录已验收。Windows专用进程回收还须在Windows执行对应检查。
最终包和附件校验以发布说明为准，不把编译成功当成完整实机验证。
Windows原生窗口、拖动/透明点击区域、麦克风、全局按键、官方登录与任务、
Key保存/USB、R4写入及更多固件仍需实机。没有固件升级、视频导出或自动更新。

运行组件与许可证
Microsoft .NET 10 / WinForms、WebView2 SDK、Python 3.12.10、Cyberboard CLI
0.1.2、pyserial、jsonschema、Pillow、tzdata及传递依赖随包提供。
见licenses、resources\python\LICENSE.txt、THIRD-PARTY-NOTICES.txt和.dist-info。

官方运行环境说明
https://learn.microsoft.com/en-us/dotnet/core/install/windows
https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution
