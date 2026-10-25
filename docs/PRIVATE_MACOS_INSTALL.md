# 私有 macOS Beta 安装说明

当前私有版使用 macOS ad-hoc 签名，没有 Apple Developer ID 公证。它适合本机和小范围测试；首次打开会出现“无法验证开发者”提示，这是预期行为。

## 下载与校验

1. 从 [MiaoCall Tasks Private Beta 3 Release](https://github.com/maestrokaka/cyberboard-studio-miaocall/releases/tag/v1.0.0-miaocall.tasks.beta.3) 下载 Apple Silicon ZIP 和同名 `.sha256` 文件。
2. 解压 ZIP，把 `Cyberboard Studio.app` 移到“应用程序”。
3. 在终端进入 ZIP 所在目录后运行：

   ```bash
   shasum -a 256 Cyberboard-Studio-1.0.0-miaocall.tasks.beta.3-macOS-Apple-Silicon.zip
   ```

   输出的摘要应与 `.sha256` 文件中的值一致。

## 第一次打开

1. 在“应用程序”中找到 `Cyberboard Studio.app`。
2. 按住 Control 点击，选择“打开”。
3. 在系统确认窗口中再次选择“打开”。
4. 之后从“应用程序”或 Dock 正常打开即可。

不要把“关闭 Gatekeeper”作为安装步骤，也不要在不清楚来源时运行网上复制的命令。这个包只应从本私有 Release 获取。

## 喵唤权限

普通灯效创作不需要喵唤权限。只有主动使用对应功能时，才按系统提示授权：

- **麦克风**：语音输入和按住物理键说话。
- **输入监控**：监听物理 `·` 键。
- **辅助功能**：桌面浮层的拖动和全局交互需要时使用。
- **自动化 · Spotify**：只在启用 Spotify 示例并执行播放时授权。

如果已经授权过旧版本，升级时先退出旧 App，再把新版本放到“应用程序”并重新打开。若系统仍显示旧的权限记录，到“系统设置 → 隐私与安全性”中检查当前 App 路径；不要把旧版本和新版同时保留并交替使用。

## English summary

This private beta is ad-hoc signed and is not notarized. Download the Apple Silicon ZIP and its SHA-256 file from the private Release, verify the checksum, move the app to Applications, then Control-click it and choose **Open** twice on first launch. Do not disable Gatekeeper or run copied quarantine-removal commands as part of the normal installation. Grant microphone, Input Monitoring, Accessibility, or Spotify automation only when the corresponding MiaoCall feature is enabled.
