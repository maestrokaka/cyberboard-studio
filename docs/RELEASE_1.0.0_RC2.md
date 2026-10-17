# Cyberboard Studio 1.0.0-rc.2

**1.0 正式版候选，GitHub prerelease：`v1.0.0-rc.2`。**

## 修复 AI 灯效预览比例

RC1 的 AI 预览使用固定高度并同时占满宽度。宽窗口下，照片、顶部屏幕与轴灯被压扁。本版让三层画面按原始照片的裁切比例，使用同一缩放比例居中显示；完整机身保留，灯层位置与照片一致。

该约束用于 AI 预览、两版本比较、八种外观和工作台。画面宽高变化只影响观看大小，作品 RGB、帧数、速度和 USB 数据保持原样。

## 保留的 1.0 功能

独立对话创作、参考图、会话与版本、固定基础版本与局部修改、版本比较、明确保存入库、独立工作台和外观卡片、指定槽位草稿，以及 DeepSeek / MiniMax 接口修正均保留。

本轮只修预览与候选版本信息，沿用 [RC1 的真实 API 与功能验收](RELEASE_1.0.0_RC1.md)。不额外调用模型，不写入 USB。模型 Key 仍为普通本机文件、默认隐藏、提供显示 / 隐藏；没有系统凭据访问。

## 下载与验收

- `Cyberboard-Studio-1.0.0-rc.2-macOS-AppleSilicon.zip`
- `Cyberboard-Studio-1.0.0-rc.2-Windows-x64.zip`
- `Cyberboard-Studio-1.0.0-rc.2-Windows10-Compatibility-x64.zip`

每个 ZIP 配套 SHA-256。Mac 为 ad-hoc 签名，未公证；Windows 未商业签名。Windows 10 兼容包用途与系统支持边界保持原说明。

八款外观 × 八种窗口尺寸的 64 组预览几何检查通过：照片、顶部与轴灯同一矩形，完整机身与 83 个轴灯区域均在框内。整数 Canvas 分辨率与实际照片比例略有差异时仍保持统一缩放；外观切换与窗口反复调整不会漂移。原渲染器、真实 Canvas 照片检查及会话回归通过。

正式 Mac 包及两个 Windows 包分别使用其实际资源通过比例与保存回归；两种 Windows 包各 13 项结构 / 摘要检查通过，Mac 签名 / 冻结后台 / ZIP CRC 通过。已在用户 Mac 同一大窗口打开 RC2，确认键盘恢复原比例，顶部屏幕及轴灯仍对齐；旧会话、参考图、作品与草稿保留。Windows 原生 GUI / USB、R4 对应硬件写入仍需实机验收，不标为稳定发布。

关闭旧版后再打开候选版；会话、作品、参考图与槽位草稿保存在同一私人目录。损坏文件恢复与退出等待保存延续 RC1。

[完整使用说明](USER_GUIDE.md) · [反馈问题](https://github.com/maestrokaka/cyberboard-studio/issues)
