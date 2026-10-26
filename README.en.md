# Cyberboard Studio · Next-version preview

[简体中文](README.md) · **English**

A third-party **CYBERBOARD R4 / R6** studio: create lighting through AI conversations, compare versions on real keyboard photographs, and review a plan before syncing. The optional MiaoCall companion sends held-key voice instructions to local Codex. R6 now has dedicated sound controls, local microphone playback and advanced keymap editing.

**App binaries are not publicly released yet** · [Release notes — Chinese](docs/RELEASE_NOTES_BETA15.md) · [R6 configuration guide — Chinese](docs/R6_CONFIGURATION.md) · [Report an issue](https://github.com/maestrokaka/cyberboard-studio/issues)

This is a **preview of the next version, not a public App release**. Source, documentation and screenshots are public; new App packages remain private for testing. Historical Beta 14, RC2 and 0.4.x releases are preserved. The current source includes the Beta 15.1 Windows cancellation correction; screenshots show the Beta 15 feature set.

## New in Beta 15

- **Clearer sync states:** distinguish sent data, device acknowledgement, verified keymap data and unknown state. A failure or interruption after a potentially mutating write blocks reuse of the old lighting baseline; the app does not blindly repeat a full write.
- **Dedicated R6 Sound page:** speaker channels, microphone direction, noise reduction and tone presets use independent short commands. Opening the page only checks connectivity. Unavailable current values remain unknown; a setting echo is not acoustic verification.
- **Local microphone test:** list system audio devices and identify the system default input, explicitly record up to 30 seconds, then play or clear the recording locally. Leaving the page clears it; no ASR service is called. Speaker calibration is an advanced, separately confirmed operation.
- **R6 single-key, tap/hold and macro editing:** independent commands and tables, reviewed plans, device/baseline binding and backups. Add, update or delete entries, and choose the ordinary binding after deletion. Full keycodes and readable advanced tables are checked after transmission; an incomplete table is never replaced with an invented empty table.
- **Persistent Codex tasks:** choose a working directory, attach files, continue a task, steer it during execution, review individual permissions and inspect results and files. Spotify is an optional Mac example.
- **Quick Windows Codex setup:** Install → Sign in → Check connection through the official native CLI, without requiring Node.js or WSL and without reading or copying authentication files.
- **Desktop companion and wardrobe:** resident or wake-only mode, remembered drag position, three outfits plus long hair, 32 poses, 15 interaction regions and four offline voice styles. Sound is off by default. AI outfits are previewed before application.
- **Firmware handoff:** show the device version and open Angry Miao's official updater. Firmware is not flashed inside this app. The partial lighting protocol is still awaiting hardware validation and is not enabled by default.

## Lighting studio

AI lighting supports Kimi, MiniMax and DeepSeek, text and up to three references, saved conversations, immutable versions and scoped edits. The workbench combines photo previews, brightness/timing/palette controls, three independent slot drafts and reviewed sync plans. Ten removable presets work without a model key.

Compare eight front-view R4/R6 appearances at the same design and moment. Classic Dark and Warm Island Light can be switched instantly and persist after restart. Readable functions cover 81 physical keys across seven layers. AI dictation uses a separately configured MiniMax, Qwen or OpenAI ASR service; review the transcript before sending it to create lighting.

## Video tour · Bilibili edition

The **3:07 Beta 14** landscape video introduces AI lighting and the held-key companion workflow, with Chinese narration, captions and music. It retains the earlier interface and feature scope; see the Beta 15 screenshots and release notes for additions.

https://github.com/user-attachments/assets/a0ea2c61-1c65-4d93-a893-b44f2995d499

Watch the compressed 720p preview in the embedded player. Original-quality video and editing sources are not provided, and Releases contain no video assets. Lighting uses photo compositing; the MiaoCall segment illustrates the workflow.

## Screenshots

| AI creation · Warm Island Light | Workbench · Classic Dark |
| --- | --- |
| ![AI creation](docs/screenshots/create-beta15-light.png) | ![Keyboard lighting and three slots](docs/screenshots/workbench-beta15-dark.png) |
| **Keyboard appearances** | **R6 sound and microphone test** |
| ![Eight appearances at the same moment](docs/screenshots/appearances-beta15-light.png) | ![Independent R6 sound controls and local playback](docs/screenshots/r6-audio-beta15-light.png) |
| **R6 keymap editor** | **MiaoCall and companion** |
| ![Keymap, tap/hold and macro editor](docs/screenshots/keymap-beta15-dark.png) | ![Persistent Codex tasks and companion](docs/screenshots/miaocall-beta15-light.png) |

Screenshots use a separate demonstration environment, without personal keys, conversations or device records. Photo-composited lighting is not hardware color calibration, and sample states do not establish a real hardware write.

## Public preview and testing status

This update publishes source, documentation and screenshots only. **No new public App binaries are available.** The briefly published Beta 15 release has been withdrawn; historical Beta 14, RC2 and 0.4.x releases remain available.

macOS Apple Silicon, Windows x64 and Windows 10 Compatibility are being tested privately. The Mac build uses ad-hoc signing, without Developer ID notarization. New R6 audio and advanced key controls still require hardware acceptance; partial lighting writes remain disabled, and firmware updates are handed off to the official website.

## Quick start

1. Preview a built-in effect in the workbench without a model key.
2. Configure Kimi, MiniMax or DeepSeek under Model Configuration.
3. Start an AI conversation with text or references, such as “orange flames rising from below, ember-like key lighting, four-second loop.”
4. Choose a base version and edit scope, such as “only make the key backlight pure yellow; keep the top unchanged.”
5. Save the chosen version, prepare a slot draft, inspect the device and sync plan, then confirm the write.

Descriptions and selected references are submitted only when Create is clicked. Provider keys are stored in ordinary local files, masked by default with a Show/Hide control. Legacy Keychain/DPAPI records are never read, decrypted or migrated.

## MiaoCall: give Codex a task

Sign in to local Codex and open MiaoCall → Voice Tasks. Windows includes **Install → Sign in → Check connection**. Choose a working directory and optional files; new tasks default to read-only, and changes require an explicit choice. Submit a typed task, or configure ASR and confirm a held-key voice transcript. Review steps, individual approvals and questions, then inspect results and files. Existing tasks support follow-ups and typed steering during execution.

MiaoCall creates and resumes its own persistent sessions through the official local app-server; available tools and permissions determine what a task can do. It does not take over other desktop chats. Codex sign-in and ASR are separate connections, and typed tasks need no voice key. WorkBuddy, Qwen Office and Doubao Work remain planned integrations.

The shortcut starts off, types normally while disabled, and is released on exit. Resident companion mode is independent of recording. Idle interactions pause during recording, transcription and tasks. Four offline voice styles are muted by default. AI wardrobe generation sends the character reference and outfit description only after an explicit click and requires preview before application; generated outfits currently have one static pose. [Task guide — Chinese](docs/MIAOCALL_TASKS.md) · [Companion guide — Chinese](docs/MIAOCALL_COMPANION.md)

## Built-in lighting GIFs



I've created and refined **ten lighting designs with AI**, and included them in the app. You can preview and use them without configuring a model, then sync your favorites to the keyboard.

To make something of your own, connect **Kimi, MiniMax or DeepSeek**, describe your idea, and let AI help you create it.

If there's a theme, character or effect you'd love to see, [leave me a suggestion in GitHub Issues](https://github.com/maestrokaka/cyberboard-studio/issues). Add a short description or reference image—the next built-in design might start with your idea.

The ten full-keyboard previews below follow the app's order. Click a GIF for a larger view.

| Preset | Preset |
| --- | --- |
| **01 Neon Rift · 裂隙超载**<br>Cyan-purple armor and rift transitions · 7.68 s<br><a href="docs/previews/neon-rift.gif"><img src="docs/previews/neon-rift.gif" width="384" alt="Neon Rift: complete top and key-light loop" /></a> | **02 Data Storm · 数据暴雨**<br>Green data particles and rain · 7.68 s<br><a href="docs/previews/data-storm.gif"><img src="docs/previews/data-storm.gif" width="384" alt="Data Storm: complete top and key-light loop" /></a> |
| **03 Redline Rush · 红线竞速**<br>Red-white trails and speed · 7.68 s<br><a href="docs/previews/redline-rush.gif"><img src="docs/previews/redline-rush.gif" width="384" alt="Redline Rush: complete top and key-light loop" /></a> | **04 EVA Awakening · EVA初号机 · 觉醒序列**<br>Purple-green armor, eyes and awakening stages · 4.8 s<br><a href="docs/previews/eva-awakening.gif"><img src="docs/previews/eva-awakening.gif" width="384" alt="EVA Awakening: complete top and key-light loop" /></a> |
| **05 Glitch Override · 故障字标 · 终端夺权**<br>Wide cyberpunk lettering and glitch transitions · 4.8 s<br><a href="docs/previews/glitch-override.gif"><img src="docs/previews/glitch-override.gif" width="384" alt="Glitch Override: complete top and key-light loop" /></a> | **06 Mario · 马里奥 · 红帽闯关**<br>Pure-red cap and pixel adventure · 4.2 s<br><a href="docs/previews/mario-run.gif"><img src="docs/previews/mario-run.gif" width="384" alt="Mario: complete top and key-light loop" /></a> |
| **07 Cat Chasing Fireflies · 猫逐萤火**<br>A cat chasing fireflies · 6 s<br><a href="docs/previews/cat-firefly.gif"><img src="docs/previews/cat-firefly.gif" width="384" alt="Cat Chasing Fireflies: complete top and key-light loop" /></a> | **08 Kaká Rossonero 22 · 卡卡 · 红黑22**<br>Player card, portrait, name and number · 4.8 s<br><a href="docs/previews/kaka-rossonero.gif"><img src="docs/previews/kaka-rossonero.gif" width="384" alt="Kaka Rossonero 22: complete top and key-light loop" /></a> |
| **09 Kaká Breakaway · 卡卡 · 极速突破**<br>Dribbling action and a clear KAKA 22 title · 4.8 s<br><a href="docs/previews/kaka-breakaway.gif"><img src="docs/previews/kaka-breakaway.gif" width="384" alt="Kaka Breakaway: complete top and key-light loop" /></a> | **10 Kaká San Siro · 卡卡 · 圣西罗之夜**<br>Celebration pose and red-white flags · 4.8 s<br><a href="docs/previews/kaka-san-siro.gif"><img src="docs/previews/kaka-san-siro.gif" width="384" alt="Kaka San Siro: complete top and key-light loop" /></a> |

<details>
<summary>About these previews</summary>

Each animation uses a background-removed, front-view CYBERBOARD R6 Vision photograph, with top-matrix and key lighting composited by the app's preview renderer. The full original loop timing and source RGB are unchanged. GIF encoding may introduce slight color differences; these photo-composited screen previews are not hardware color calibration. [GIF verification manifest](docs/previews/manifest.json) · [Kaká design notes — Chinese](docs/LIGHTING_DESIGN_NOTES.md)

</details>

## Data and validation scope

Works, conversations, references, slot drafts, provider keys, tasks and device records stay outside the installation folder and release assets. AI/MiaoCall recording is limited to 60 seconds; R6 local tests to 30 seconds. Audio is captured only after an explicit action and cleaned up without entering works or the workspace. Lighting writes, keymap writes, sound settings and calibration each have explicit controls; selecting an appearance or upgrading does not execute them.

Checks cover synthetic device protocols, failure/interruption states, complete keycodes and advanced tables, sound echoes, recording lifecycle, both themes, preview proportions and actual packages. Offline/CI results do not replace acceptance of R6 sound parameters and physical direction, microphone recording/playback, new macros/tap-hold, partial lighting, Windows GUI/shortcuts/user sign-in and USB. [Acceptance boundaries — Chinese](docs/R6_CONFIGURATION.md#验证范围)

Earlier native Windows CI verified host compilation, owned descendant cleanup, official Codex installation and discovery, real app-server initialization and signed-out account queries. This did not sign in a user or run a real model task. Beta 14 photo-mask, preview-performance and packaged speech TLS dependency fixes are retained.

## Building and contributing

The repository includes patched `cyberboard-cli` 0.1.2; see [provenance and licenses](vendor/README.md). Mac builds require Python 3.12, Node.js and Xcode Command Line Tools:

```sh
python3 scripts/setup-cli.py --env-dir .tools/macos-build --with-pyinstaller
.tools/macos-build/bin/python scripts/build-macos-backend.py
python3 scripts/prepare-data.py
native/build.sh --backend-dir build/macos-backend/CyberboardBackend
```

Windows builds require .NET 10 SDK and the prepared Python runtime; see the [runtime guide](windows/runtime-readme.txt). `python scripts/check-release.py --mac-native` runs local release checks, and detailed UI/backend/package checks are in `tests/`. Synthetic tests do not access USB or use model credits.

Source lives in `web/`, `backend/`, `native/` and `windows/src/`. Public artwork, photographs and generic layouts are in `data/`; third-party code and licenses are in `vendor/`. R6 additions are independently implemented from the official website's observed communication behavior rather than copied website business code.

Beta 15 is synchronized to the public and private repositories. Historical Beta 14, RC2 and private tags/assets remain intact. Releases contain packages and checksums, without videos, personal audio, voice-cloning sources, keys, workspaces or device records. For feedback, include the app version, operating system, keyboard model, firmware version and reproduction steps in an [issue](https://github.com/maestrokaka/cyberboard-studio/issues).

## Support the author



**Your keyboard is glowing. My coffee cup could use a refill. ☕**

If Cyberboard Studio helped bring your keyboard to life, you're welcome to buy **Kakà** a coffee and fuel the next lighting idea. Any amount is appreciated. Support is optional and does not affect access to features.

<p align="center">
  <a href="docs/assets/wechat-support.svg"><img src="docs/assets/wechat-support.svg" width="280" alt="Kakà's WeChat support QR code" /></a>
  <br />
  <strong>Scan with WeChat · Kakà</strong>
</p>

For questions and suggestions, email [maestrokaka@gmail.com](mailto:maestrokaka@gmail.com). Please use email or GitHub Issues for feedback rather than payment messages.

**Would you like an English-language version of the app? Please contact me at [maestrokaka@gmail.com](mailto:maestrokaka@gmail.com).**
