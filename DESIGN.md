# Cyberboard Studio · 1.0

A desktop lighting studio for macOS and Windows. The interface offers two persistent styles: Classic Dark (the existing restrained charcoal/Linear language) and Warm Island Light (adapted from Animal Island UI). The keyboard is the subject: real calibrated front photographs show the selected design, while sparse lavender controls guide creation and delivery. LED colors come from the artwork data.

## Tokens and platform behavior

Canvas `#010102`; sidebar `#0f1011`; panel `#141516`; hover `#18191a`; hairline `#23252a`; strong border `#34343a`; text `#f7f8f8`; secondary `#8a8f98`; tertiary `#62666d`; primary `#5e6ad2`; primary hover `#828fff`; verified success `#27a644`.

Use SF Pro on macOS and Segoe UI on Windows. Core content is 13px, controls and metadata 11–13px, page titles 20–24px. Reserve smaller type for optional decoration. Use SF Mono / Menlo for time, frames, hex and device identifiers. A 4px spacing unit, 6–8px controls and 12px panels keep the rhythm consistent. No decorative atmospheric gradients.

Sidebar 184px, workbench inspector approximately 250–280px. Use a native titlebar and real platform controls. Minimum window 1120×760. Preview, common parameters and three slots should fit a normal desktop window; complex conversations, long lists and smaller windows may scroll within their own regions rather than hide controls. Controls have at least 32px targets. Focus uses a 2px lavender outline. Reduced motion pauses players by default and removes ornamental transitions.

The approved icon is the orange tile containing a white, proportionate keyboard enclosure with the correct display opening and cat paw. Only the paw is rotated 180 degrees. The same raster asset drives the sidebar, macOS ICNS and Windows ICO; no Logo review destination is included.

## Selectable interface styles

Settings → Interface style offers exactly two visual cards: `dark` / 经典深色 and `island` / 暖岛浅色. Existing workspaces default to dark. Persist `uiTheme` with the workspace; a bounded local cache only avoids first-paint flashes. Failed saves restore the previous choice. Theme changes must never alter RGB, timing, conversation versions, drafts, keymaps or hardware state.

Warm Island follows Animal Island UI v2.3.0 (MIT, source commit 279959f): cream #f8f8f0 and #fffdf5 surfaces, earth-brown text #794f27/#725d42, mint #19c8b9 actions, Nunito + Noto Sans SC local fonts, rounded/pill controls, and locally bundled naive-icons. It is an adaptation of the existing native/vanilla interface, not a React runtime migration. Complex native review sheets retain their accessible rectangular layout rather than adopting decorative blob clipping. Original dark tokens below remain scoped to the dark style. Mac titlebar and under-page colors follow the style; native settings dialogs use the platform appearance.

The light photo stage uses a warm neutral surface. Preserve transparent photo contours and the exact shared contain geometry for all three canvas layers. Off LEDs, keycaps, photographs and source RGB are never recolored to fit the UI. Distinguish Appearance (paintbrush), Keymap (key), Model (bulb/chip) and Settings icons. Do not restore a temporary logo-review page, system credential prompts, fake AI results or sample-conversation data when integrating a visual trial.

## Information hierarchy

Application navigation, conversation history and lighting versions are separate levels.

| Navigation group | Destinations |
| --- | --- |
| 创作 | AI 创作, 灯效工作台, 灯效作品库 |
| 键盘 | 键盘与外观, 键位编辑, 设备与槽位 |
| 设置 | 模型配置 |

The device destination provides internal tabs for slots / configuration and sync records. Keymap editing is a separate destination: 81 physical keys, seven layers, readable vendor functions, searchable assignments, independent persistent drafts and a reviewed keymap-only plan. Unknown raw keycodes are retained exactly; lighting drafts never become keymap changes. Studio preferences and optional support remain secondary destinations. The global sidebar never becomes a conversation list.

## AI creation

AI creation has a dedicated page. The main column is a conversation with a stable title, model status, History and New Conversation actions. History opens internally and supports search; choosing a conversation closes it. The secondary column contains a collapsible calibrated keyboard preview, version selection and delivery actions. It must not repeat a full set of save / workbench actions under every old message.

The composer accepts a concise description and up to three reference images, shows the saved model, and provides an explicit base-version choice and scope: both regions, only the top matrix, or only the backlight. Images remain visible in their input / sent-message context. Images and conversation drafts persist locally. Model requests occur only on an explicit Send/Create action; no simulated AI response or USB completion is permitted.

Each accepted result becomes a complete immutable version. Sending a modification locks the chosen base version at request start. Scoped edits preserve the other region's full RGB frames and timing; a malformed or unverified edit is rejected. Old results stay selectable after errors, cancellation and new turns. The preview always identifies its selected version. Comparison lets the user select two versions, synchronize playback or inspect corresponding loop phases.

Generation does not automatically create a library entry or slot draft. The user explicitly exports a version, saves that version to the library, or opens a copy in the workbench. Workbench changes never mutate the old conversation version. Empty conversations disable export, save and workbench delivery rather than exposing an earlier result.

Stop, provider errors, format errors, interruption and disk-save errors are distinct states with useful next actions. Retry restores the original description, references, base, scope and model; changing to another saved model requires an explicit choice. Do not silently swap a provider or fall back to a local template. Preserve the unfinished brief and old results. Persistence success is reported only after the file write completes.

## Lighting workbench

The workbench concentrates on large photo preview, real parameters, JSON and device delivery. AI chat and the appearance picker live on their separate pages. Show all three slot cards below the large preview, with the target, content, frame counts, last-written / pending status and separate Preview and Undo Draft actions.

Clicking a slot selects an assignment target without changing the work being designed. Its Preview action loads that slot's content. The inspector names the target and distinguishes assigning or updating its local draft from actual synchronization. Parameter changes require explicit reassignment before they affect the prepared draft. Conversation switches, new conversations and appearance choices never clear drafts.

Single-slot sync uses only the selected target's prepared draft. Show Sync All only when several drafts are pending; untouched slots do not join the request. Keep advanced configuration actions on the device page. The sync sheet shows a concrete merged plan before execution, measured transfer progress, device acknowledgement, full keymap verification and record-saving status as separate claims.

Brightness acts on original RGB and slot brightness without rewriting the source artwork. The common timing slider covers 10–100ms beside an exact 1–32767ms number input; imported timings remain exact. Frame labels distinguish top, backlight and the common loop when sequence lengths differ. Preview-only rendering and backlight visibility controls do not alter exported LED data.

## Keyboard appearances

A dedicated card gallery supplies eight front-view appearances with R4 / R6 filtering. Compare using the same design and same frame. The selected card has a restrained lavender border and accessible pressed state; hover and keyboard focus remain distinct. Short, one-line labels omit the repeated CYBERBOARD prefix. Full names and photo source are available with the main preview.

The catalog names are exactly:

- CYBERBOARD R6「Vision」
- CYBERBOARD R4「Fluo Free」
- CYBERBOARD R4「Bebop」
- CYBERBOARD R4「Gangstar」
- CYBERBOARD R4「Cloud White V2」
- CYBERBOARD R4「Stone Face」
- CYBERBOARD R4「Paisley」
- CYBERBOARD R4「Vision」

R4 and R6 Vision are distinct model choices. R6 uses the earliest provided front photograph; R4 uses qualified official site / store images, including sold-out colorways. Preserve the photographs' original pixels and use calibrated screen / backlight projections. Clip photo and canvases along the physical enclosure on a quiet `#111315` stage in dark mode, or the warm neutral photo stage in light mode. Keep the full enclosure proportional, without stretching, cropping the keyboard or adding fictional colorways. Only the clean front view is offered.

Opaque keycaps receive restrained light in key gaps; transparent keycaps retain transmission. Selection is remembered and changes only preview appearance, never the artwork, slot drafts or connected-device identity. Clearly separate the photo model from the manually detected USB identity. Photo composition is an approximation, not a real-time camera feed or hardware color measurement.

## Model configuration and local data

Kimi Code / Open Platform, MiniMax and DeepSeek keep independent saved endpoints, models and keys. Changing a form value does not activate a service until Save. New Kimi Code uses k3; new MiniMax uses M3.1 Flash Preview, while existing manually saved model choices are retained. Show image capabilities and account errors accurately; a model-list check never implies generation permission.

API keys use ordinary per-provider local files. The field is hidden by default with a direct Show / Hide action. Service switches and leaving this page restore masking. There is no additional reveal confirmation, Keychain / DPAPI encryption, system authorization or legacy credential lookup / migration. Existing plain-file keys remain usable; users with only legacy system records paste and save again. Never add system credential access as a compatibility fallback.

The v2 private workspace holds conversations, normalized reference images, immutable versions, library state, removed built-ins and independent slot drafts. Before the first v2 save, retain the prior workspace as `workspace-before-1.0.json`. Await disk persistence before success and before ordinary exit / reload. A failure leaves the app open for export or retry. Respect 20 conversations, 12 versions and 60 turns per conversation, and a 32MiB workspace cap without silently evicting old results.

API Keys stay outside workspace, designs, exports, logs, public assets, commits and packages. Device configuration / keymaps are excluded from AI requests. A selected base recipe and bounded creative history are explicit request inputs. The image payload is normalized locally, and artwork export omits the reference images and transcript.

## Dictation and optional voice Agent

The AI composer has an explicit voice-input button. ASR service and model are configured independently of lighting generation; only confirmed speech-to-text models are available. A click starts bounded recording, another finishes it, and recognized text enters the current draft for review. Recording never automatically submits a creative turn. Cancel, navigation races, context changes and exit cannot insert late text into another conversation. Raw audio is temporary and excluded from persisted workspace, logs and exports; ASR Keys follow the same ordinary local-file and show/hide policy.

MiaoCall is a separate opt-in Beta destination on macOS. Its global shortcut starts disabled, is registered only after the user enables it, and is released on exit. The current Codex adapter uses an official local app-server ephemeral task with only configured Spotify playback/status tools. Do not claim completion from a model reply or app launch: require the official terminal event plus verified target track, playback state and progress. WorkBuddy, Qwen Office and Doubao Work remain future integrations.

## Library, dialogs and support

All ten approved built-ins and custom works support local trash, restore and confirmed permanent deletion. Removed built-ins stay removed after restart / upgrade. Restoring a work does not restore its discarded slot drafts. Keep custom names and JSON import / export. Source labels distinguish bundled examples, local CLI records and live keymap reads; imported configuration contributes artwork rather than replacing bindings.

Modal sheets have fixed headings and actions, a scrollable body, contained Tab focus and focus return on dismissal. Background content is inert while open. Close actions obey real device-commit protection; progress completion is not a substitute for acknowledgement and verification.

Support is optional. Preserve the approved icon, restrained charcoal layout and original payment artwork with a white QR quiet zone. Display author Kakà and contact maestrokaka@gmail.com. No amount, tracking or automatic transaction belongs in the app. The README ends with the original QR and playful copy, rather than an app screenshot; release notes contain product changes and validation.

## Candidate acceptance

MiaoCall Beta 14 is a public prerelease for macOS Apple Silicon. The separately available Windows RC2 packages are historical builds. Reviews cover the full flow and retained functions, not only the new screen. Distinguish offline tests, live-provider tests, native host checks and USB acceptance. Never label Windows / R4 stable on the basis of cross-compilation or shared mocks. Package only public resources and an empty / explicitly isolated demonstration workspace; private tests and screenshots stay in ignored build directories.


## MiaoCall Beta

MiaoCall is a separate opt-in destination. Use the approved orange/ivory catgirl, with charcoal surfaces and a restrained orange action accent. Listening, recognition, editable confirmation, Codex activity and playback verification have distinct states. Keep controls simple: switch, physical key hint, hold-to-test, cancel and voice settings. Song catalog edits require an explicit apply action before the global key uses them. WorkBuddy, Qwen Office and Doubao Work remain visibly unavailable until implemented.

The native floating companion never activates or opens while idle. Preserve transparent character proportions; show bounded, actionable task information beside her. Allow the desktop character to be dragged across the desktop and remember its position; the settings-page illustration is not the floating companion. Success requires an official task terminal plus actual Spotify playback progress. The current public snapshot preserves the verified MiaoCall macOS identity and signed package. Do not merge earlier private development history, tags, test audio or desktop-recording materials into the public origin.


## Shared control geometry

Reserve an invariant end gutter for every select: 34px in Classic Dark and 38px in Warm Island. Context-specific spacing must not move selected text into the arrow area. Keep short options fully readable; truncate long titles within the text area. Group each label with its control when wrapping.

Generic theme defaults use low-specificity selectors so component geometry wins. Primary buttons are flat, without a hard bottom shadow or positional transform; hover and active states use color feedback. Disabled buttons also have no shadow or positional transform. Pill links need explicit inline padding and a separate, non-shrinking icon. Review both themes at regular and compact desktop sizes across all destinations.


## Content-sized slot cards and compact keymaps

The workbench slot area sizes to its card contents instead of a fixed vertical budget. Keep slot metadata inside the rounded border and leave a clear gap before the action row. The keyboard preview takes the remaining space; never vertically center oversized card content into a compressed button.

At compact desktop widths, stack the keymap inspector below the keyboard before key labels become cramped. Bound long function labels to two wrapped lines, preserve full labels in the inspector and tooltips, and never modify raw key codes for presentation. Review real text rectangles against clipping ancestors, including off-screen components within scrollable pages. Distinguish intentional ellipses, line clamps and closed disclosures from defects.


## Responsive preview work

Keep selected-card feedback immediate. Prepare gallery lighting incrementally, reuse identical comparison snapshots and cancel queued work when leaving the page. Thumbnail raster sizes may match their displayed size; the main preview keeps its existing precision and uniform photo/LED/key-light projection.

Suspend hidden preview work while preserving the current frame and playback choice. Reuse bounded static photo/mask results only when calibration, crop, material and raster dimensions match; never cache or recolor artwork RGB. Release caches on destruction, and retain the durable workspace-save/exit contract.
