import Cocoa
import AVFoundation
import ApplicationServices

// An opt-in physical shortcut. The event tap exists only for an enabled session;
// switching it off restores the original event without synthesizing replacement keys.
struct MiaoCallKeyGate {
    static let keyCode: Int64 = 50
    private(set) var held = false
    mutating func consume(code: Int64, down: Bool, repeated: Bool, modified: Bool, busy: Bool) -> String? {
        guard code == Self.keyCode else { return nil }
        if !down, held { held = false; return "stop" }
        guard down, !modified else { return nil }
        if held { return "consume" }
        guard !repeated else { return nil }
        held = true
        return busy ? "consume" : "start"
    }
    mutating func reset() { held = false }
}

// A pending enable owns its own cancellation token. Configuration is an async
// operation, so a late voice-settings reply must never recreate a disabled tap.
struct MiaoCallEnableGate {
    private(set) var token: UUID?
    var isPending: Bool { token != nil }
    mutating func begin() -> UUID? {
        guard token == nil else { return nil }
        let next = UUID(); token = next; return next
    }
    mutating func finish(_ candidate: UUID) -> Bool {
        guard token == candidate else { return false }
        token = nil; return true
    }
    mutating func cancel() { token = nil }
}

enum MiaoCallTranscript {
    static func validated(_ input: String) throws -> String {
        let clean = input.trimmingCharacters(in: .whitespacesAndNewlines)
        func failure(_ message: String) -> NSError {
            NSError(domain: "CyberboardStudio.MiaoCall", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
        }
        guard !clean.isEmpty else { throw failure("请先填写语音指令。") }
        guard clean.unicodeScalars.count <= 2000 else { throw failure("指令不能超过 2000 字，请缩短后再交给 Codex。") }
        return clean
    }
}

enum MiaoCallResultContract {
    static func message(_ value: [String: Any], fallback: String) -> String {
        let detail = (value["detail"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let message = (value["message"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return String((!detail.isEmpty ? detail : !message.isEmpty ? message : fallback).prefix(500))
    }
    static func terminal(_ value: [String: Any]) -> (state: String, message: String) {
        let state = value["status"] as? String ?? "error"
        if value["ok"] as? Bool == true, state == "completed",
           let taskID = value["taskId"] as? String,
           taskID.range(of: "^task-[0-9a-f]{32}$", options: .regularExpression) != nil {
            let text = value["text"] as? String ?? ""
            let files = value["artifacts"] as? [String] ?? []
            if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !files.isEmpty {
                return ("completed", message(value, fallback: String(text.prefix(220)).isEmpty ? "Codex 已返回文件，请检查任务结果。" : String(text.prefix(220))))
            }
        }
        if value["ok"] as? Bool == true, state == "completed",
           let playback = value["playback"] as? [String: Any], playback["verified"] as? Bool == true,
           playback["playing"] as? Bool == true, MiaoCallSpotify.validURI(playback["uri"] as? String ?? "") {
            return ("completed", message(value, fallback: "Spotify 已播放目标歌曲，播放进度已核实。"))
        }
        if state == "cancelled", value["ok"] as? Bool == false {
            return ("cancelled", message(value, fallback: "Codex 任务已取消。"))
        }
        return ("error", message(value, fallback: "Codex 未返回完整且已核实的播放结果，请重试。"))
    }
}

private final class MiaoCallPanel: NSPanel {
    var onEscape: (() -> Void)?
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { onEscape?() }
}

/// The desktop companion itself is the drag handle. This view lives only in the
/// floating panel; the mascot artwork inside the main settings page is static.
private final class MiaoCallDraggablePetView: NSImageView {
    var onDrag: ((NSPoint) -> Void)?
    var onMenu: ((NSEvent) -> Void)?
    var onOpenTask: (() -> Void)?
    private(set) var pressed = false
    private var previousMouseLocation: NSPoint?
    private var bitmap: NSBitmapImageRep?
    private var interactionBitmap: NSBitmapImageRep?
    func setInteractionImage(_ image: NSImage?) { interactionBitmap = image?.tiffRepresentation.flatMap(NSBitmapImageRep.init(data:)) }
    override var image: NSImage? { didSet { bitmap = image?.tiffRepresentation.flatMap(NSBitmapImageRep.init(data:)) } }

    func opaquePoint(_ windowPoint: NSPoint, forInteraction: Bool = false) -> NSPoint? {
        guard let image, let bitmap = forInteraction ? interactionBitmap : bitmap else { return nil }
        let local = convert(windowPoint, from: nil)
        let scale = min(bounds.width / image.size.width, bounds.height / image.size.height)
        let rect = NSRect(x: (bounds.width - image.size.width * scale) / 2,
                          y: (bounds.height - image.size.height * scale) / 2,
                          width: image.size.width * scale, height: image.size.height * scale)
        guard rect.contains(local) else { return nil }
        let point = NSPoint(x: (local.x - rect.minX) / rect.width, y: 1 - (local.y - rect.minY) / rect.height)
        let x = min(bitmap.pixelsWide - 1, max(0, Int(point.x * Double(bitmap.pixelsWide))))
        let y = min(bitmap.pixelsHigh - 1, max(0, Int(point.y * Double(bitmap.pixelsHigh))))
        guard (bitmap.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.15 else { return nil }
        return point
    }

    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 2 { onOpenTask?(); return }
        pressed = true
        previousMouseLocation = NSEvent.mouseLocation
        window?.makeFirstResponder(nil)
    }

    override func mouseDragged(with event: NSEvent) {
        let location = NSEvent.mouseLocation
        if let previousMouseLocation {
            let delta = NSPoint(x: location.x - previousMouseLocation.x,
                                y: location.y - previousMouseLocation.y)
            if delta != .zero { onDrag?(delta) }
        }
        previousMouseLocation = location
    }

    override func mouseUp(with event: NSEvent) { previousMouseLocation = nil; pressed = false }
    override func rightMouseDown(with event: NSEvent) { onMenu?(event) }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .openHand)
    }
}

private final class MiaoCallOverlay: NSObject, NSWindowDelegate {
    let panel: MiaoCallPanel
    let title = NSTextField(labelWithString: "喵唤 MiaoCall")
    let message = NSTextField(wrappingLabelWithString: "")
    let transcript = NSTextField(string: "")
    let submit = NSButton(title: "交给 Codex", target: nil, action: nil)
    let cancel = NSButton(title: "取消", target: nil, action: nil)
    let activity = NSProgressIndicator()
    let image = MiaoCallDraggablePetView()
    let style: CompanionStyle
    private let bubble = NSView()
    private let voice = CompanionVoice()
    var onPreferencesChanged: (() -> Void)?
    var canInteract: (() -> Bool)?
    var onSubmit: ((String) -> Void)?
    var onCancel: (() -> Void)?
    var onOpenTask: (() -> Void)?
    private var animation: Timer?
    private var phase = 0.0
    private var active = false
    private var taskState = "idle"
    private var interaction = CompanionInteractionGate()
    private var reactionUntil: TimeInterval = 0
    private var layingOut = false
    private var suspended = false
    private var petTimer: Timer?
    private let positionDefaultsKey = "CyberboardStudio.MiaoCallOverlay.companionPosition.v1"

    init(resources: URL) {
        style = CompanionStyle(resources: resources)
        panel = MiaoCallPanel(contentRect: NSRect(x: 0, y: 0, width: 488, height: 300),
                              styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        super.init()
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.isMovableByWindowBackground = true
        panel.delegate = self
        let content = NSView(frame: panel.contentView!.bounds)
        panel.contentView = content
        image.frame = NSRect(x: 0, y: 0, width: 186, height: 280)
        image.imageScaling = .scaleProportionallyUpOrDown
        image.image = NSImage(contentsOf: resources.appendingPathComponent("web/assets/miaocall/nekomimi.png"))
        image.setAccessibilityLabel("拖动喵娘可移动桌面浮层")
        image.onDrag = { [weak self] delta in self?.movePanel(by: delta) }
        image.onMenu = { [weak self] event in self?.contextMenu(event) }
        image.onOpenTask = { [weak self] in self?.onOpenTask?() }
        content.addSubview(image)
        bubble.frame = NSRect(x: 152, y: 96, width: 328, height: 180)
        bubble.wantsLayer = true
        bubble.layer?.cornerRadius = 22
        bubble.layer?.shadowColor = NSColor.black.cgColor
        bubble.layer?.shadowRadius = 12
        content.addSubview(bubble)
        title.frame = NSRect(x: 22, y: 140, width: 282, height: 23)
        title.font = .systemFont(ofSize: 15, weight: .semibold)
        title.textColor = NSColor(calibratedRed: 1, green: 0.54, blue: 0.25, alpha: 1)
        bubble.addSubview(title)
        message.frame = NSRect(x: 22, y: 83, width: 282, height: 51)
        message.font = .systemFont(ofSize: 13)
        message.textColor = NSColor(calibratedWhite: 0.94, alpha: 1)
        message.maximumNumberOfLines = 3
        bubble.addSubview(message)
        transcript.frame = NSRect(x: 22, y: 49, width: 284, height: 30)
        transcript.font = .systemFont(ofSize: 13)
        transcript.placeholderString = "确认你的语音指令"
        transcript.isHidden = true
        bubble.addSubview(transcript)
        submit.frame = NSRect(x: 178, y: 12, width: 130, height: 30)
        submit.bezelStyle = .rounded
        submit.contentTintColor = NSColor(calibratedRed: 1, green: 0.49, blue: 0.15, alpha: 1)
        submit.target = self
        submit.action = #selector(submitClicked)
        submit.isHidden = true
        bubble.addSubview(submit)
        cancel.frame = NSRect(x: 220, y: 12, width: 88, height: 30)
        cancel.bezelStyle = .rounded
        cancel.target = self
        cancel.action = #selector(cancelClicked)
        bubble.addSubview(cancel)
        activity.frame = NSRect(x: 24, y: 20, width: 20, height: 20)
        activity.style = .spinning
        activity.controlSize = .small
        activity.isDisplayedWhenStopped = false
        bubble.addSubview(activity)
        panel.onEscape = { [weak self] in self?.onCancel?() }
        applyTheme(UserDefaults.standard.string(forKey: "studioUITheme") ?? "dark")
        applyStyle()
    }
    func applyTheme(_ theme: String) {
        let palette = CompanionPalette(light: theme == "island")
        let appearance = NSAppearance(named: palette.light ? .aqua : .darkAqua)
        panel.appearance = appearance; bubble.appearance = appearance
        bubble.layer?.backgroundColor = palette.background.cgColor
        bubble.layer?.borderColor = palette.border.cgColor
        bubble.layer?.borderWidth = palette.light ? 1.5 : 1
        bubble.layer?.shadowOpacity = palette.light ? 0.12 : 0.24
        title.textColor = palette.title; message.textColor = palette.text
        title.font = NSFont.systemFont(ofSize: 15, weight: .semibold)
        message.font = NSFont.systemFont(ofSize: 13)
        if palette.light {
            if let rounded = title.font?.fontDescriptor.withDesign(.rounded) { title.font = NSFont(descriptor: rounded, size: 15) }
            if let rounded = message.font?.fontDescriptor.withDesign(.rounded) { message.font = NSFont(descriptor: rounded, size: 13) }
        }
        transcript.textColor = palette.text; transcript.backgroundColor = palette.secondary
        transcript.bezelStyle = .roundedBezel; transcript.focusRingType = .default
        for button in [submit, cancel] {
            button.wantsLayer = true; button.isBordered = false
            button.layer?.cornerRadius = 13
            button.layer?.backgroundColor = (button === submit ? palette.accent : palette.secondary).cgColor
            button.layer?.borderColor = palette.border.cgColor
            button.layer?.borderWidth = button === submit ? 0 : 1
            button.font = .systemFont(ofSize: 12, weight: .semibold)
            button.contentTintColor = button === submit && !palette.light ? .white : palette.text
        }
    }
    @objc private func submitClicked() {
        if submit.title == "查看任务" { onOpenTask?() }
        else if taskState == "awaitingConfirmation" { onSubmit?(transcript.stringValue) }
    }
    @objc private func cancelClicked() { if taskState == "idle" { hide() } else { onCancel?() } }
    private func movePanel(by delta: NSPoint) {
        interaction.reset(); reactionUntil = 0; voice.stop()
        panel.setFrameOrigin(NSPoint(x: panel.frame.origin.x + delta.x,
                                     y: panel.frame.origin.y + delta.y))
    }
    func windowDidMove(_ notification: Notification) {
        guard !layingOut, (notification.object as? NSWindow) === panel else { return }
        constrainAndPersistPosition()
    }
    private func visibleScreen(for frame: NSRect) -> NSScreen? {
        // While dragging, follow the display under the pointer. Choosing the
        // panel's current center first traps it at the edge of its old display.
        if image.pressed, let screen = NSScreen.screens.first(where: { $0.visibleFrame.contains(NSEvent.mouseLocation) }) { return screen }
        let center = NSPoint(x: frame.minX + image.frame.midX, y: frame.minY + image.frame.midY)
        if let screen = NSScreen.screens.first(where: { $0.visibleFrame.contains(center) }) { return screen }
        if let screen = NSScreen.screens.first(where: { $0.visibleFrame.intersects(frame) }) { return screen }
        return NSScreen.main ?? NSScreen.screens.first
    }
    private func constrainAndPersistPosition() {
        layoutPet(expanded: !bubble.isHidden)
        let anchor = NSPoint(x: panel.frame.minX + image.frame.minX, y: panel.frame.minY)
        UserDefaults.standard.set(["x": anchor.x, "y": anchor.y], forKey: positionDefaultsKey)
    }
    private func restoreOrPlacePosition() {
        let saved = UserDefaults.standard.dictionary(forKey: positionDefaultsKey)
            ?? UserDefaults.standard.dictionary(forKey: "CyberboardStudio.MiaoCallOverlay.position")
        let stored = saved.flatMap { values -> NSPoint? in
            guard let x = values["x"] as? NSNumber, let y = values["y"] as? NSNumber,
                  x.doubleValue.isFinite, y.doubleValue.isFinite else { return nil }
            return NSPoint(x: x.doubleValue, y: y.doubleValue)
        }
        let screen = stored.flatMap { anchor in NSScreen.screens.first { $0.visibleFrame.contains(anchor) } } ?? NSScreen.main ?? NSScreen.screens.first
        guard let visible = screen?.visibleFrame else { return }
        let anchor = stored ?? NSPoint(x: visible.maxX - image.frame.width - 30, y: visible.minY + 24)
        layingOut = true
        panel.setFrameOrigin(NSPoint(x: anchor.x - image.frame.minX, y: anchor.y))
        layingOut = false
        constrainAndPersistPosition()
    }
    func show(state: String, text: String, recognized: String) {
        taskState = state; reactionUntil = 0; interaction.reset(); voice.stop(); suspended = false
        let labels = ["configuring": "正在准备喵唤…", "preparing": "正在准备语音…", "listening": "正在听你说…", "transcribing": "正在识别语音…", "awaitingConfirmation": "听清楚啦，确认一下？",
                      "connecting": "正在连接 Codex…", "thinking": "Codex 正在思考…", "acting": "正在为你操作…",
                      "awaitingApproval": "Codex 需要你的授权", "awaitingInput": "Codex 需要补充信息",
                      "cancelling": "正在停止任务…", "completed": "Codex 已返回结果", "cancelled": "已取消", "error": "需要你看一下"]
        title.stringValue = labels[state] ?? "喵唤 MiaoCall"
        message.stringValue = String(text.prefix(220))
        let confirming = state == "awaitingConfirmation"
        let needsTask = ["awaitingApproval", "awaitingInput", "completed"].contains(state)
        transcript.isHidden = !confirming
        submit.isHidden = !(confirming || needsTask)
        submit.title = needsTask ? "查看任务" : "交给 Codex"
        cancel.frame.origin.x = confirming || needsTask ? 76 : 220
        cancel.title = ["completed", "error", "cancelled"].contains(state) ? "收起" : "取消"
        if confirming { transcript.stringValue = recognized }
        active = ["configuring", "preparing", "listening", "transcribing", "connecting", "thinking", "acting"].contains(state)
        image.image = style.picture(state == "completed" ? "happy" : state == "listening" ? "ears" : state == "thinking" ? "think" : "idle")
        bubble.isHidden = false
        layoutPet(expanded: true)
        if active { activity.startAnimation(nil) } else { activity.stopAnimation(nil) }
        if animation == nil {
            animation = Timer.scheduledTimer(withTimeInterval: 1.0 / 24, repeats: true) { [weak self] _ in
                guard let self else { return }
                self.phase += 0.12
                let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
                self.image.frame.origin.y = self.active && !reduceMotion ? 3 + sin(self.phase) * 3 : 0
                self.image.alphaValue = self.active ? 0.95 + sin(self.phase) * 0.05 : 1
            }
        }
        if !panel.isVisible {
            restoreOrPlacePosition()
        }
        panel.orderFrontRegardless()
        beginPetTimer()
    }
    func hide() {
        taskState = "idle"; active = false; reactionUntil = 0; voice.stop(); interaction.reset()
        animation?.invalidate(); animation = nil; image.frame.origin.y = 0
        applyStyle()
    }
    func applyStyle() {
        voice.stop(); interaction.reset(); reactionUntil = 0
        guard taskState == "idle" else { return }
        image.image = style.picture()
        image.setInteractionImage(image.image)
        bubble.isHidden = true
        layoutPet(expanded: false)
        if style.resident && !suspended {
            if !panel.isVisible { restoreOrPlacePosition() }
            panel.orderFrontRegardless(); beginPetTimer()
        } else { panel.orderOut(nil); petTimer?.invalidate(); petTimer = nil }
    }
    private func layoutPet(expanded: Bool) {
        layingOut = true
        defer { layingOut = false }
        let height = (style.preferences["size"] as? NSNumber)?.doubleValue ?? 300
        let anchor = NSPoint(x: panel.frame.minX + image.frame.minX, y: panel.frame.minY)
        guard let visible = visibleScreen(for: panel.frame)?.visibleFrame else { return }
        let placement = CompanionPlacement.calculate(anchor: anchor, size: height, expanded: expanded, visible: visible)
        image.frame = placement.image; bubble.frame = placement.bubble
        panel.setFrame(placement.frame, display: true)
    }
    private func beginPetTimer() {
        guard petTimer == nil else { return }
        petTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 15, repeats: true) { [weak self] _ in self?.pollPointer() }
    }
    private func pollPointer() {
        guard panel.isVisible else { return }
        let now = ProcessInfo.processInfo.systemUptime
        let windowPoint = panel.convertPoint(fromScreen: NSEvent.mouseLocation)
        let normalized = image.opaquePoint(windowPoint)
        let inBubble = !bubble.isHidden && bubble.frame.contains(windowPoint)
        // Transparent margins must not consume clicks intended for the desktop.
        panel.ignoresMouseEvents = !image.pressed && normalized == nil && !inBubble
        if taskState != "idle" { interaction.reset(); return }
        if canInteract?() == false { voice.stop(); interaction.reset(); return }
        if reactionUntil > 0 && now >= reactionUntil {
            reactionUntil = 0; image.image = style.picture(); bubble.isHidden = true; layoutPet(expanded: false)
            if !style.resident { panel.orderOut(nil); petTimer?.invalidate(); petTimer = nil; return }
        }
        let zone = image.opaquePoint(windowPoint, forInteraction: true).flatMap { style.zone(at: $0) }
        if let identity = interaction.consume(zone?["id"] as? String, now: now,
                                               blocked: image.pressed || reactionUntil > now || style.preferences["hover"] as? Bool != true) {
            react(identity)
        }
    }
    func react(_ identity: String, forceAudio: Bool = false, audioSettings: [String: Any]? = nil) {
        guard taskState == "idle", canInteract?() != false, let zone = style.zones.first(where: { $0["id"] as? String == identity }) else { return }
        reactionUntil = ProcessInfo.processInfo.systemUptime + 2.4
        image.image = style.picture(zone["pose"] as? String ?? "idle")
        title.stringValue = "轻触 · " + (zone["name"] as? String ?? "喵娘")
        message.stringValue = zone["text"] as? String ?? "我在这里。"
        transcript.isHidden = true; submit.isHidden = true; cancel.isHidden = false; cancel.title = "收起"
        activity.stopAnimation(nil); bubble.isHidden = false; layoutPet(expanded: true)
        if !panel.isVisible { restoreOrPlacePosition() }
        panel.orderFrontRegardless(); beginPetTimer(); voice.play(zone: zone, style: style, force: forceAudio, audioSettings: audioSettings)
    }
    private func contextMenu(_ event: NSEvent) {
        let menu = NSMenu()
        let task = NSMenuItem(title: "查看任务", action: #selector(openTaskClicked), keyEquivalent: "")
        task.target = self; menu.addItem(task)
        let sound = NSMenuItem(title: style.soundEnabled ? "关闭互动声音" : "开启互动声音", action: #selector(toggleSound), keyEquivalent: "")
        sound.target = self; menu.addItem(sound)
        let mode = NSMenuItem(title: style.resident ? "仅唤醒时出现" : "常驻桌面", action: #selector(toggleResident), keyEquivalent: "")
        mode.target = self; menu.addItem(mode)
        let hide = NSMenuItem(title: "暂时收起", action: #selector(suspendPet), keyEquivalent: "")
        hide.target = self; menu.addItem(hide)
        NSMenu.popUpContextMenu(menu, with: event, for: image)
    }
    @objc private func openTaskClicked() { onOpenTask?() }
    @objc private func toggleSound() {
        var value = style.preferences; value["sound"] = !style.soundEnabled
        try? style.save(value); applyStyle(); onPreferencesChanged?()
    }
    @objc private func toggleResident() {
        var value = style.preferences; value["mode"] = style.resident ? "wake" : "resident"
        try? style.save(value); suspended = false; applyStyle(); onPreferencesChanged?()
    }
    @objc private func suspendPet() { suspended = true; panel.orderOut(nil); petTimer?.invalidate(); petTimer = nil; voice.stop() }
    func resume() { suspended = false; applyStyle() }
    deinit { petTimer?.invalidate(); animation?.invalidate(); voice.stop() }
}

// Bounded JSONL child transport. Credential and audio payloads remain on private
// pipes, never in argv, logs, preferences, or progress events.
private final class MiaoCallChild {
    private let lock = NSLock()
    private var process: Process?
    private var input: FileHandle?
    private var cancelled = false
    private var gracefulCancellation = false
    private let queue = DispatchQueue(label: "local.cyberboard.studio.miaocall.child", qos: .userInitiated)
    func start(resources: URL, action: String, payload: [String: Any], keepInput: Bool,
               onEvent: @escaping ([String: Any]) -> Void, completion: @escaping (Result<[String: Any], Error>) -> Void) {
        queue.async { [self] in
            let child = Process()
            let bundled = resources.appendingPathComponent("backend/CyberboardBackend/CyberboardBackend")
            let development = ProcessInfo.processInfo.environment["CYBERBOARD_CLI_PYTHON"] ?? Bundle.main.object(forInfoDictionaryKey: "CyberboardDevelopmentPythonPath") as? String
            if FileManager.default.isExecutableFile(atPath: bundled.path) {
                child.executableURL = bundled; child.arguments = []
            } else if let development, (development as NSString).isAbsolutePath, FileManager.default.isExecutableFile(atPath: development) {
                child.executableURL = URL(fileURLWithPath: development)
                child.arguments = ["-X", "utf8", "-u", resources.appendingPathComponent("backend/bridge.py").path]
            } else {
                DispatchQueue.main.async { completion(.failure(VoiceRecordingController.failure("语音后台组件缺失，请完整解压软件包。"))) }; return
            }
            child.arguments! += ["--action", action, "--state-dir", FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Cyberboard Studio").path, "--resource-dir", resources.path]
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONUNBUFFERED"] = "1"; environment["PYTHONIOENCODING"] = "utf-8"
            environment.removeValue(forKey: "PYTHONHOME"); environment.removeValue(forKey: "PYTHONPATH")
            child.environment = environment
            child.currentDirectoryURL = resources
            let stdinPipe = Pipe(), stdoutPipe = Pipe(), stderrPipe = Pipe()
            child.standardInput = stdinPipe; child.standardOutput = stdoutPipe; child.standardError = stderrPipe
            let reader = JSONLineReader(maximumBytes: action.hasPrefix("companion") ? 12 * 1024 * 1024 : action == "miaoCallWorker" ? 8 * 1024 * 1024 : action.hasPrefix("agentTask") ? 3 * 1024 * 1024 : 1024 * 1024) { record in DispatchQueue.main.async { onEvent(record) } }
            let stderrGroup = DispatchGroup()
            self.lock.lock()
            if self.cancelled { self.lock.unlock(); DispatchQueue.main.async { completion(.failure(VoiceRecordingController.failure("已取消。"))) }; return }
            self.process = child; self.input = stdinPipe.fileHandleForWriting
            self.gracefulCancellation = keepInput
            do { try child.run(); self.lock.unlock() }
            catch { self.process = nil; self.input = nil; self.lock.unlock(); DispatchQueue.main.async { completion(.failure(VoiceRecordingController.failure("无法启动语音任务后台。"))) }; return }
            stderrGroup.enter()
            DispatchQueue.global(qos: .utility).async {
                while !stderrPipe.fileHandleForReading.availableData.isEmpty { /* Drain without logging private server diagnostics. */ }
                stderrGroup.leave()
            }
            let watchdog = DispatchWorkItem { [weak self] in self?.cancel() }
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + (action == "companionOutfitGenerate" ? 135 : keepInput ? 1830 : 85), execute: watchdog)
            do {
                var data = try JSONSerialization.data(withJSONObject: payload)
                if keepInput { data.append(0x0A) }
                try stdinPipe.fileHandleForWriting.write(contentsOf: data)
                if !keepInput { try stdinPipe.fileHandleForWriting.close() }
                reader.read(from: stdoutPipe.fileHandleForReading); reader.finish()
                if reader.parseError != nil { self.cancel() }
                child.waitUntilExit(); stderrGroup.wait(); watchdog.cancel()
                self.lock.lock(); let cancelled = self.cancelled
                self.process = nil; self.input = nil; self.lock.unlock()
                let result: Result<[String: Any], Error>
                if cancelled { result = .failure(VoiceRecordingController.failure("已取消。")) }
                else if let error = reader.parseError { result = .failure(VoiceRecordingController.failure(error)) }
                else if let final = reader.finalReply, let error = final["error"] {
                    let message = (error as? [String: Any])?["message"] as? String ?? error as? String ?? "语音任务未完成。"
                    result = .failure(VoiceRecordingController.failure(message))
                } else if child.terminationStatus == 0, let value = reader.finalReply?["result"] as? [String: Any] { result = .success(value) }
                else if keepInput, child.terminationStatus == 0 { result = .success([:]) }
                else { result = .failure(VoiceRecordingController.failure("语音任务未完整完成，请重试。")) }
                DispatchQueue.main.async { completion(result) }
            } catch {
                watchdog.cancel(); self.cancel()
                DispatchQueue.main.async { completion(.failure(VoiceRecordingController.failure("语音任务连接中断，请重试。"))) }
            }
        }
    }
    func send(_ payload: [String: Any]) {
        lock.lock(); defer { lock.unlock() }
        guard !cancelled, let input, var data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        data.append(0x0A); try? input.write(contentsOf: data)
    }
    func cancel() {
        lock.lock(); defer { lock.unlock() }
        guard !cancelled else { return }; cancelled = true
        if let input, var data = try? JSONSerialization.data(withJSONObject: ["type": "cancel"]) { data.append(0x0A); try? input.write(contentsOf: data) }
        try? input?.close(); input = nil
        if let process, process.isRunning {
            // The managed Codex worker needs a bounded grace period to issue
            // formal turn/interrupt and reap its app-server process group.
            let grace: TimeInterval = gracefulCancellation ? 6 : 0
            if grace == 0 { process.terminate() }
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + grace) { [weak process] in
                guard let process, process.isRunning else { return }
                if grace > 0 { process.terminate() }
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 2) { [weak process] in
                    if let process, process.isRunning { Darwin.kill(process.processIdentifier, SIGKILL) }
                }
            }
        }
    }
    deinit { cancel() }
}

// Optional verified desktop example; general Codex tasks use their own available tools. Spotify's
// bundled official scripting dictionary supplies play track/current track/state.
final class MiaoCallSpotify {
    private let queue = DispatchQueue(label: "local.cyberboard.studio.miaocall.spotify", qos: .userInitiated)
    private let cancellationLock = NSLock()
    private var cancellationGeneration = 0
    func cancel() { cancellationLock.lock(); cancellationGeneration += 1; cancellationLock.unlock() }
    private func currentGeneration() -> Int { cancellationLock.lock(); defer { cancellationLock.unlock() }; return cancellationGeneration }
    static func verifyProgress(first: [String: Any], latest: [String: Any], expectedURI: String?) -> Bool {
        guard let uri = latest["uri"] as? String, validURI(uri), first["uri"] as? String == uri,
              expectedURI == nil || expectedURI == uri, first["playing"] as? Bool == true,
              latest["playing"] as? Bool == true, let before = first["positionMs"] as? Int,
              let after = latest["positionMs"] as? Int, after - before >= 300 else { return false }
        return true
    }
    static func validURI(_ uri: String) -> Bool { uri.range(of: "\\Aspotify:track:[A-Za-z0-9]{22}\\z", options: .regularExpression) != nil }
    private func execute(_ body: String) throws -> NSAppleEventDescriptor {
        let source = "with timeout of 12 seconds\n tell application id \"com.spotify.client\"\n" + body + "\n end tell\nend timeout"
        var error: NSDictionary?
        let result = NSAppleScript(source: source)?.executeAndReturnError(&error)
        guard error == nil, let result else {
            throw VoiceRecordingController.failure("无法读取 Spotify 播放状态。请允许本软件控制 Spotify，并确认已登录且此歌曲在当前地区可播放。")
        }
        return result
    }
    private func playback() throws -> [String: Any] {
        let record = try execute("return {(player state as text), (id of current track), (name of current track), (artist of current track), player position}")
        guard record.numberOfItems == 5 else { throw VoiceRecordingController.failure("Spotify 没有返回完整播放状态。") }
        let rawURI = record.atIndex(2)?.stringValue ?? ""
        let uri = rawURI.hasPrefix("spotify:track:") ? rawURI : "spotify:track:" + rawURI
        return ["playing": record.atIndex(1)?.stringValue == "playing", "uri": uri,
                "title": String((record.atIndex(3)?.stringValue ?? "").prefix(200)),
                "artist": String((record.atIndex(4)?.stringValue ?? "").prefix(200)),
                "positionMs": Int((record.atIndex(5)?.doubleValue ?? 0) * 1000)]
    }
    func run(arguments: [String: Any], allowedTracks: [[String: Any]], completion: @escaping ([String: Any]) -> Void) {
        let token = currentGeneration()
        let action = arguments["action"] as? String ?? ""
        guard ["playTrackUri", "getPlayback"].contains(action) else { completion(["error": "此 Beta 只支持播放目录中的歌曲与读取播放状态。"]); return }
        let uri = arguments["uri"] as? String ?? ""
        guard action != "playTrackUri" || Self.validURI(uri) && allowedTracks.contains(where: { $0["uri"] as? String == uri }) else {
            completion(["error": "歌曲不在本次授权播放目录中。"]); return
        }
        guard let spotifyURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.spotify.client") else { completion(["error": "请先安装 Spotify 桌面版并登录。"]); return }
        let configuration = NSWorkspace.OpenConfiguration(); configuration.activates = action == "playTrackUri"
        NSWorkspace.shared.openApplication(at: spotifyURL, configuration: configuration) { _, error in
            guard error == nil else { DispatchQueue.main.async { completion(["error": "Spotify 启动失败，请确认软件完整且已登录。"]) }; return }
            self.queue.asyncAfter(deadline: .now() + (action == "playTrackUri" ? 1.5 : 0.8)) {
                guard token == self.currentGeneration() else { return }
                do {
                    if action == "playTrackUri" {
                        var commandError: Error?
                        for _ in 0..<8 {
                            do { _ = try self.execute("play track \"" + uri + "\""); commandError = nil; break }
                            catch { commandError = error; Thread.sleep(forTimeInterval: 0.8) }
                        }
                        if let commandError { throw commandError }
                    }
                    var first: [String: Any]?
                    var latest: [String: Any] = [:]
                    var verified = false
                    // Read-only observations, bounded to eight seconds. Completion
                    // means matching URI AND real playback position advancing. Spotify can
                    // expose its window before its player-state Apple event is ready, so a
                    // transient read failure is retried instead of being reported as a task failure.
                    for _ in 0..<8 {
                        guard token == self.currentGeneration() else { return }
                        do { latest = try self.playback() }
                        catch { Thread.sleep(forTimeInterval: 0.8); continue }
                        let matches = action == "playTrackUri" ? latest["uri"] as? String == uri : Self.validURI(latest["uri"] as? String ?? "")
                        if matches, latest["playing"] as? Bool == true {
                            if let first, Self.verifyProgress(first: first, latest: latest, expectedURI: action == "playTrackUri" ? uri : nil) { verified = true; break }
                            if first == nil { first = latest }
                        } else { first = nil }
                        Thread.sleep(forTimeInterval: 0.8)
                    }
                    latest["verified"] = verified
                    if !verified { latest["message"] = "尚未观测到目标歌曲持续播放，请检查登录、地区或 Spotify 账户播放限制。" }
                    DispatchQueue.main.async { completion(latest) }
                } catch { DispatchQueue.main.async { completion(["error": error.localizedDescription, "verified": false]) } }
            }
        }
    }
}

final class MiaoCallController {
    private let resources: URL
    private let recorder: VoiceRecordingController
    private let overlay: MiaoCallOverlay
    private let spotify = MiaoCallSpotify()
    private var child: MiaoCallChild?
    private var wardrobeChild: MiaoCallChild?
    private var taskQueries: [UUID: MiaoCallChild] = [:]
    private var currentTaskID: String?
    private var agentRequest: [String: Any]?
    private var taskResult: [String: Any]?
    private var selectedAttachments: Set<String> = []
    private var monitor: CFMachPort?
    private var source: CFRunLoopSource?
    private var gate = MiaoCallKeyGate()
    private var enableGate = MiaoCallEnableGate()
    private var generation = 0
    private var hideTask: DispatchWorkItem?
    private var keyReleasedBeforeStart = false
    private var options: [String: Any] = [:]
    private var profile: [String: Any] = [:]
    private(set) var enabled = false
    private(set) var state = "idle"
    private(set) var transcript = ""
    private var message = ""
    var onEvent: (([String: Any]) -> Void)?
    var onShowTask: (() -> Void)?
    var canBegin: (() -> Bool)?
    var isBusy: Bool { enableGate.isPending || !["idle", "completed", "cancelled", "error"].contains(state) }
    init(resources: URL, recorder: VoiceRecordingController = VoiceRecordingController()) {
        self.resources = resources; self.recorder = recorder
        overlay = MiaoCallOverlay(resources: resources)
        overlay.canInteract = { [weak self] in self?.canBegin?() != false && self?.isBusy != true }
        overlay.onCancel = { [weak self] in self?.cancel() }
        overlay.onOpenTask = { [weak self] in self?.onShowTask?() }
        overlay.onPreferencesChanged = { [weak self] in
            guard let self else { return }
            var event = self.status(); event["event"] = "miaoCall"; event["type"] = "state"; self.onEvent?(event)
        }
        overlay.onSubmit = { [weak self] text in
            guard let self else { return }
            if ["awaitingApproval", "awaitingInput", "completed"].contains(self.state) { self.onShowTask?(); return }
            do { try self.submit(text) }
            catch {
                self.transcript = String(text.prefix(6000))
                self.publish("awaitingConfirmation", error.localizedDescription)
            }
        }
        recorder.onState = { [weak self] event in
            guard let self else { return }
            if event["reason"] as? String == "limit" { self.stopRecording() }
            else if event["reason"] as? String == "error" { self.finish("error", "录音未能保存，请重新尝试。") }
        }
    }
    func applyTheme(_ theme: String) { overlay.applyTheme(theme) }
    func status() -> [String: Any] {
        ["enabled": enabled, "state": state, "transcript": transcript, "message": message,
         "physicalKeyCode": MiaoCallKeyGate.keyCode, "confirmBeforeSend": options["confirmBeforeSend"] as? Bool ?? true,
         "permissions": ["inputMonitoring": CGPreflightListenEventAccess(), "accessibility": AXIsProcessTrusted(),
                         "microphone": AVCaptureDevice.authorizationStatus(for: .audio) == .authorized],
         "agent": "codex", "supportedAgents": ["codex"], "voiceProvider": profile["provider"] as? String ?? ""]
            .merging(["companion": overlay.style.preferences, "taskId": currentTaskID ?? "",
                      "request": agentRequest ?? [:], "taskResult": taskResult ?? [:]], uniquingKeysWith: { _, new in new })
    }
    func handle(action: String, payload: [String: Any], completion: @escaping (Result<[String: Any], Error>) -> Void) {
        switch action {
        case "miaoCallTaskList", "miaoCallTaskRead", "miaoCallTaskArchive", "miaoCallTaskDelete", "miaoCallTaskContext", "miaoCallTaskConfigure", "miaoCallTaskReveal", "miaoCallTaskExport", "miaoCallTaskDiagnostics":
            if ["miaoCallTaskConfigure", "miaoCallTaskArchive", "miaoCallTaskDelete"].contains(action) && isBusy {
                completion(.failure(VoiceRecordingController.failure("请先完成或停止当前任务。"))); return
            }
            if action == "miaoCallTaskDelete" {
                let alert = NSAlert(); alert.messageText = "删除这条归档任务记录？"
                alert.informativeText = "仅删除喵唤本机对话记录，不删除任务文件或 Codex 保存的原会话。此操作不能撤销。可先导出记录。"
                alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "删除记录")
                guard alert.runModal() == .alertSecondButtonReturn else { completion(.success(["cancelled": true])); return }
            }
            let mapping = ["miaoCallTaskList": "agentTaskList", "miaoCallTaskRead": "agentTaskRead",
                           "miaoCallTaskArchive": "agentTaskArchive", "miaoCallTaskDelete": "agentTaskDelete", "miaoCallTaskContext": "agentTaskContext",
                           "miaoCallTaskConfigure": "agentTaskConfigure", "miaoCallTaskReveal": "agentTaskReveal",
                           "miaoCallTaskExport": "agentTaskExport", "miaoCallTaskDiagnostics": "agentTaskDiagnostics"]
            var requestPayload = payload
            if action == "miaoCallTaskList" { requestPayload["activeTaskId"] = isBusy ? currentTaskID : nil }
            if action == "miaoCallTaskConfigure" { requestPayload.removeValue(forKey: "cwd") }
            taskQuery(mapping[action]!, requestPayload) { result in
                if case .success(var value) = result, action == "miaoCallTaskDiagnostics" {
                    value["appVersion"] = Bundle.main.object(forInfoDictionaryKey: "CyberboardDisplayVersion") as? String ?? "unknown"
                    value["permissions"] = self.status()["permissions"]
                    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]), let text = String(data: data, encoding: .utf8) {
                        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
                    }
                }
                if case .success(let value) = result, action == "miaoCallTaskReveal", let path = value["path"] as? String {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
                }
                if case .success(let value) = result, action == "miaoCallTaskExport", let data = value["json"] {
                    let panel = NSSavePanel(); panel.allowedContentTypes = [.json]
                    panel.nameFieldStringValue = value["fileName"] as? String ?? "MiaoCall-task.json"
                    panel.begin { response in
                        do {
                            if response == .OK, let url = panel.url { try JSONSerialization.data(withJSONObject: data, options: [.prettyPrinted, .sortedKeys]).write(to: url, options: .atomic) }
                            completion(.success(["exported": response == .OK]))
                        } catch { completion(.failure(VoiceRecordingController.failure("任务导出未完成。"))) }
                    }
                } else { completion(result) }
            }
        case "miaoCallTaskChooseFolder":
            guard !isBusy else { completion(.failure(VoiceRecordingController.failure("请先完成当前任务。"))); return }
            let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false
            panel.allowsMultipleSelection = false; panel.message = "选择新任务的工作目录；修改范围由任务权限决定。"
            panel.begin { [weak self] response in
                guard response == .OK, let url = panel.url else { completion(.success(["cancelled": true])); return }
                self?.taskQuery("agentTaskConfigure", ["cwd": url.path], completion)
            }
        case "miaoCallTaskChooseFiles":
            guard !isBusy else { completion(.failure(VoiceRecordingController.failure("请先完成当前任务。"))); return }
            let panel = NSOpenPanel(); panel.canChooseDirectories = false; panel.allowsMultipleSelection = true
            panel.message = "添加最多 8 个任务文件，文件只在提交任务时交给 Codex。"
            panel.begin { [weak self] response in
                guard response == .OK else { completion(.success(["cancelled": true])); return }
                guard panel.urls.count <= 8 else { completion(.failure(VoiceRecordingController.failure("最多添加 8 个文件。"))); return }
                let paths = panel.urls.map { $0.path }; self?.selectedAttachments.formUnion(paths)
                completion(.success(["paths": paths]))
            }
        case "miaoCallTaskSelect":
            guard !isBusy else { completion(.failure(VoiceRecordingController.failure("请先完成或停止当前任务。"))); return }
            currentTaskID = payload["taskId"] as? String; taskResult = nil; options["attachments"] = []
            completion(.success(status()))
        case "miaoCallRunTask":
            guard !isBusy, canBegin?() != false else { completion(.failure(VoiceRecordingController.failure("请先完成当前操作。"))); return }
            currentTaskID = payload["taskId"] as? String
            options["tracks"] = (payload["tracks"] as? [[String: Any]] ?? []).filter { MiaoCallSpotify.validURI($0["uri"] as? String ?? "") }.prefix(20).map { $0 }
            options["attachments"] = (payload["attachments"] as? [String] ?? []).filter { selectedAttachments.contains($0) }.prefix(8).map { $0 }
            state = "awaitingConfirmation"
            do { try submit(payload["text"] as? String ?? ""); completion(.success(status())) }
            catch { state = "idle"; completion(.failure(error)) }
        case "miaoCallTaskRespond":
            guard let pending = agentRequest, pending["id"] as? String == payload["id"] as? String else { completion(.failure(VoiceRecordingController.failure("这条请求已结束。"))); return }
            child?.send(["type": pending["kind"] as? String == "questions" ? "answers" : "approval",
                         "id": payload["id"] ?? "", "decision": payload["decision"] ?? "decline",
                         "answers": payload["answers"] ?? [:]])
            agentRequest = nil; publish("thinking", "已将你的答复交给 Codex。")
            completion(.success(status()))
        case "miaoCallTaskSteer":
            guard ["thinking", "acting", "connecting"].contains(state), let child else { completion(.failure(VoiceRecordingController.failure("当前任务不能补充，请在结果后继续追问。"))); return }
            do { let text = try MiaoCallTranscript.validated(payload["text"] as? String ?? ""); child.send(["type": "steer", "text": text]); completion(.success(["queued": true])) }
            catch { completion(.failure(error)) }
        case "miaoCallCompanionSave":
            do {
                try overlay.style.save(payload); overlay.resume()
                completion(.success(status()))
            } catch { completion(.failure(error)) }
        case "miaoCallCompanionTest":
            guard !isBusy else { completion(.failure(VoiceRecordingController.failure("请先完成当前语音任务。"))); return }
            do {
                var preview = overlay.style.preferences
                if let voice = payload["voice"] { preview["voice"] = voice }
                if let volume = payload["volume"] { preview["volume"] = volume }
                let checked = try overlay.style.validate(preview)
                overlay.react(payload["zone"] as? String ?? "cheek", forceAudio: payload["sound"] as? Bool == true, audioSettings: checked)
                completion(.success(status()))
            } catch { completion(.failure(error)) }
        case "miaoCallOutfitCancel":
            wardrobeChild?.cancel(); wardrobeChild = nil
            completion(.success(["cancelled": true]))
        case "miaoCallImageSettings", "miaoCallImageSave", "miaoCallImageReveal", "miaoCallOutfitGenerate", "miaoCallOutfitDelete":
            guard !isBusy, wardrobeChild == nil else { completion(.failure(VoiceRecordingController.failure("正在处理任务或衣装，请稍后再试。"))); return }
            let methods = ["miaoCallImageSettings": "companionImageSettings", "miaoCallImageSave": "companionImageSave", "miaoCallImageReveal": "companionImageReveal", "miaoCallOutfitGenerate": "companionOutfitGenerate", "miaoCallOutfitDelete": "companionOutfitDelete"]
            let request = MiaoCallChild(); wardrobeChild = request
            request.start(resources: resources, action: methods[action]!, payload: payload, keepInput: false, onEvent: { _ in }) { [weak self, weak request] result in
                if let self, self.wardrobeChild === request {
                    self.wardrobeChild = nil
                    if case .success = result, action == "miaoCallOutfitDelete", payload["id"] as? String == self.overlay.style.preferences["outfit"] as? String {
                        var value = self.overlay.style.preferences; value["outfit"] = "sailor-short"
                        try? self.overlay.style.save(value); self.overlay.applyStyle()
                    }
                }
                completion(result)
            }
        case "miaoCallStatus":
            var value = status(); value["customOutfits"] = overlay.style.customOutfits(); completion(.success(value))
        case "miaoCallEnable":
            guard !isBusy, let setupToken = enableGate.begin() else { completion(.failure(VoiceRecordingController.failure("请先完成或取消当前喵唤任务。"))); return }
            generation += 1
            let setupGeneration = generation
            let candidateOptions: [String: Any] = ["confirmBeforeSend": payload["confirmBeforeSend"] as? Bool ?? true,
                       "tracks": (payload["tracks"] as? [[String: Any]] ?? []).filter { MiaoCallSpotify.validURI($0["uri"] as? String ?? "") }.prefix(20).map { $0 }]
            publish("configuring", "正在读取语音连接，准备好后才启用全局按键。此时不会录音。")
            loadProfile { [weak self] result in
                guard let self else { return }
                guard self.enableGate.finish(setupToken), setupGeneration == self.generation else {
                    completion(.failure(VoiceRecordingController.failure("开启操作已取消。"))); return
                }
                switch result {
                case .failure(let error):
                    self.finish("error", error.localizedDescription); completion(.failure(error))
                case .success:
                    self.options = candidateOptions
                    do { try self.enableMonitor(); completion(.success(self.status())) }
                    catch { self.enabled = false; self.finish("error", error.localizedDescription); completion(.failure(error)) }
                }
            }
        case "miaoCallDisable": disable(); completion(.success(status()))
        case "miaoCallCancel": cancel(); completion(.success(status()))
        case "miaoCallSubmit":
            do { try submit(payload["text"] as? String ?? transcript); completion(.success(status())) }
            catch { completion(.failure(error)) }
        case "miaoCallStartRecording":
            guard !isBusy, canBegin?() != false else { completion(.failure(VoiceRecordingController.failure("已有录音、AI 或设备操作正在进行，请先结束。"))); return }
            if !isBusy { options["tracks"] = payload["tracks"] ?? options["tracks"]; if let confirm = payload["confirmBeforeSend"] as? Bool { options["confirmBeforeSend"] = confirm } }
            startRecording(); completion(.success(status()))
        case "miaoCallStopRecording": stopRecording(); completion(.success(status()))
        default: completion(.failure(VoiceRecordingController.failure("不支持的喵唤操作。")))
        }
    }
    private func taskQuery(_ action: String, _ payload: [String: Any], _ completion: @escaping (Result<[String: Any], Error>) -> Void) {
        let identity = UUID(), query = MiaoCallChild()
        taskQueries[identity] = query
        query.start(resources: resources, action: action, payload: payload, keepInput: false, onEvent: { _ in }) { [weak self] result in
            self?.taskQueries.removeValue(forKey: identity); completion(result)
        }
    }
    private func loadProfile(completion: @escaping (Result<Void, Error>) -> Void) {
        let token = generation
        let request = MiaoCallChild(); child = request
        request.start(resources: resources, action: "voiceSettings", payload: [:], keepInput: false, onEvent: { _ in }) { [weak self] result in
            guard let self else { return }
            guard token == self.generation else { completion(.failure(VoiceRecordingController.failure("操作已取消。"))); return }
            self.child = nil
            switch result {
            case .failure(let error): completion(.failure(error))
            case .success(let value):
                guard value["hasKey"] as? Bool == true else { completion(.failure(VoiceRecordingController.failure("请先在模型配置中保存语音识别服务与 Key。"))); return }
                self.profile = value.filter { ["provider", "model", "region"].contains($0.key) }
                completion(.success(()))
            }
        }
    }
    private func enableMonitor() throws {
        if let monitor {
            gate.reset(); CGEvent.tapEnable(tap: monitor, enable: true)
            enabled = true; publish("idle", "喵唤已开启，按住 · 说话，松开发送识别。"); return
        }
        if !CGPreflightListenEventAccess() { _ = CGRequestListenEventAccess() }
        let mask = (CGEventMask(1) << CGEventType.keyDown.rawValue) | (CGEventMask(1) << CGEventType.keyUp.rawValue)
        let info = Unmanaged.passUnretained(self).toOpaque()
        let callback: CGEventTapCallBack = { _, type, event, info in
            guard let info else { return Unmanaged.passUnretained(event) }
            let owner = Unmanaged<MiaoCallController>.fromOpaque(info).takeUnretainedValue()
            if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                owner.gate.reset()
                owner.enabled = false
                owner.cancel()
                owner.publish("error", "系统暂停了按键监听，请重新开启喵唤。")
                return Unmanaged.passUnretained(event)
            }
            guard owner.enabled else { return Unmanaged.passUnretained(event) }
            let code = event.getIntegerValueField(.keyboardEventKeycode)
            if code == 53, type == .keyDown, owner.isBusy { owner.cancel(); return nil }
            let modified = !event.flags.intersection([.maskCommand, .maskControl, .maskAlternate, .maskShift, .maskSecondaryFn]).isEmpty
            let result = owner.gate.consume(code: code, down: type == .keyDown,
                                             repeated: event.getIntegerValueField(.keyboardEventAutorepeat) != 0,
                                             modified: modified, busy: owner.isBusy)
            if result == "start" { owner.startRecording(); return nil }
            if result == "stop" { owner.stopRecording(); return nil }
            if result == "consume" { return nil }
            return Unmanaged.passUnretained(event)
        }
        guard let port = CGEvent.tapCreate(tap: .cgSessionEventTap, place: .headInsertEventTap, options: .defaultTap,
                                          eventsOfInterest: mask, callback: callback, userInfo: info) else {
            throw VoiceRecordingController.failure(permissionFailureMessage())
        }
        guard let runSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, port, 0) else {
            CFMachPortInvalidate(port)
            throw VoiceRecordingController.failure("按键监听已获许可，但系统未能启动监听。请退出并重新打开 App 后再试。")
        }
        monitor = port; source = runSource
        CFRunLoopAddSource(CFRunLoopGetMain(), runSource, .commonModes)
        CGEvent.tapEnable(tap: port, enable: true)
        enabled = true; publish("idle", "喵唤已开启，按住 · 说话，松开发送识别。")
    }

    private func permissionFailureMessage() -> String {
        let appName = (Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
            ?? (Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String)
            ?? "Cyberboard Studio · MiaoCall"
        let inputMonitoring = CGPreflightListenEventAccess()
        let accessibility = AXIsProcessTrusted()
        if !inputMonitoring && !accessibility {
            return "「\(appName)」还没有输入监控和辅助功能权限。请在系统设置的「隐私与安全性」中，分别打开输入监控与辅助功能里的「\(appName)」，然后重新开启喵唤。"
        }
        if !inputMonitoring {
            return "「\(appName)」还没有输入监控权限。请在系统设置的「隐私与安全性 → 输入监控」中添加并打开当前这个「\(appName)」，然后重新开启喵唤。"
        }
        if !accessibility {
            return "「\(appName)」还没有辅助功能权限。请在系统设置的「隐私与安全性 → 辅助功能」中添加并打开当前这个「\(appName)」，然后重新开启喵唤。"
        }
        return "「\(appName)」的两项权限均已允许，但系统未能建立按键监听。请退出并重新打开 App；若仍失败，请在系统设置中重新添加当前版本的 App。"
    }
    func shutdown() { taskQueries.values.forEach { $0.cancel() }; taskQueries.removeAll(); wardrobeChild?.cancel(); wardrobeChild = nil; disable() }
    func disable() {
        enabled = false; gate.reset()
        if let monitor { CGEvent.tapEnable(tap: monitor, enable: false); CFMachPortInvalidate(monitor) }
        if let source { CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes) }
        monitor = nil; source = nil; cancel(); if state != "cancelling" { publish("idle", "喵唤已关闭，· 恢复正常输入。") }
    }
    private func publish(_ state: String, _ text: String) {
        self.state = state; message = text
        var event = status(); event["event"] = "miaoCall"; event["type"] = "state"
        onEvent?(event)
        if state == "idle" { overlay.hide() }
        else { overlay.show(state: state, text: text, recognized: transcript) }
    }
    private func finish(_ state: String, _ text: String) {
        publish(state, text)
        hideTask?.cancel()
        let token = generation
        let task = DispatchWorkItem { [weak self] in
            guard let self, token == self.generation else { return }
            self.overlay.hide(); self.publish("idle", "")
        }
        hideTask = task
        let visibleDuration: TimeInterval = state == "error" || state == "completed" ? 12 : 5
        DispatchQueue.main.asyncAfter(deadline: .now() + visibleDuration, execute: task)
    }
    func startRecording() {
        guard !isBusy, canBegin?() != false else { return }
        generation += 1; hideTask?.cancel(); child?.cancel(); child = nil
        transcript = ""; keyReleasedBeforeStart = false
        publish("preparing", "正在准备麦克风和语音连接，开始聆听后再说话。")
        let token = generation
        loadProfile { [weak self] result in
            guard let self, token == self.generation else { return }
            switch result {
            case .failure(let error): self.finish("error", error.localizedDescription)
            case .success:
                if self.keyReleasedBeforeStart { self.finish("cancelled", "按住 · 说完再松开。此次没有录音。"); return }
                let requestID = "miaocall-" + UUID().uuidString
                self.recorder.start(requestID) { [weak self] result in
                    guard let self, token == self.generation else { return }
                    if case .failure(let error) = result { self.finish("error", error.localizedDescription) }
                    else {
                        self.publish("listening", "按住 · 说出你的指令，松开后识别。Esc 可取消。")
                        if self.keyReleasedBeforeStart { self.stopRecording() }
                    }
                }
            }
        }
    }
    func stopRecording() {
        if state == "preparing" {
            keyReleasedBeforeStart = true
            if recorder.requestID != nil { cancel() }
            return
        }
        guard state == "listening" else { return }
        guard let id = recorder.requestID else { keyReleasedBeforeStart = true; return }
        do {
            let stopped = try recorder.stop(id)
            guard let audio = stopped["audio"] as? [String: Any] else { throw VoiceRecordingController.failure("录音数据无效。") }
            transcribeAudio(audio, requestID: id, token: generation)
        } catch {
            // Permission may still be resolving while the physical key goes up.
            // Preserve that release so a delayed grant never starts an orphan recording.
            keyReleasedBeforeStart = true
            if recorder.requestID != nil { recorder.cancelAll(); finish("cancelled", "录音尚未开始，请在权限准备好后重新按住 ·。") }
            else { finish("error", error.localizedDescription) }
        }
    }
    private func transcribeAudio(_ audio: [String: Any], requestID: String, token: Int) {
        guard token == generation else { return }
        var payload: [String: Any] = ["requestId": requestID, "audio": audio]
        for name in ["Provider", "Model", "Region"] { payload["expected" + name] = profile[name.lowercased()] }
        publish("transcribing", "正在把声音转成文字，音频不会保存到作品或历史记录。")
        let request = MiaoCallChild(); child = request
        request.start(resources: resources, action: "transcribeVoice", payload: payload, keepInput: false, onEvent: { _ in }) { [weak self] result in
            guard let self, token == self.generation else { return }; self.child = nil
            switch result {
            case .failure(let error): self.finish("error", error.localizedDescription)
            case .success(let value):
                guard let text = value["text"] as? String, !text.isEmpty else { self.finish("error", "没有识别到文字，请重新尝试。"); return }
                self.transcript = text
                self.publish("awaitingConfirmation", "确认后交给独立 Codex 会话执行。你可以先改一改识别文字。")
                if self.options["confirmBeforeSend"] as? Bool == false {
                    do { try self.submit(text) }
                    catch { self.publish("awaitingConfirmation", error.localizedDescription) }
                }
            }
        }
    }
    func submit(_ text: String) throws {
        guard state == "awaitingConfirmation" else { throw VoiceRecordingController.failure("当前没有等待确认的语音指令。") }
        let clean = try MiaoCallTranscript.validated(text)
        transcript = clean
        taskResult = nil; agentRequest = nil
        generation += 1; hideTask?.cancel()
        publish("connecting", "已交给 Codex，任务和结果会保存在本机。")
        let token = generation
        let request = MiaoCallChild(); child = request
        let tracks = options["tracks"] as? [[String: Any]] ?? []
        var taskPayload: [String: Any] = ["transcript": clean, "tracks": tracks, "attachments": options["attachments"] as? [String] ?? []]
        if let currentTaskID { taskPayload["taskId"] = currentTaskID }
        request.start(resources: resources, action: "miaoCallWorker", payload: taskPayload, keepInput: true, onEvent: { [weak self, weak request] event in
            guard let self, let request, token == self.generation, self.state != "cancelling" else { return }
            if let identity = event["taskId"] as? String, !identity.isEmpty { self.currentTaskID = identity }
            if event["type"] as? String == "tool", event["tool"] as? String == "spotify", let id = event["id"] ?? event["callId"], let arguments = event["arguments"] as? [String: Any] {
                self.publish("acting", "正在执行 Spotify 示例，并核对实际播放状态。")
                self.spotify.run(arguments: arguments, allowedTracks: tracks) { [weak self, weak request] result in
                    guard let self, let request, token == self.generation, self.state != "cancelling" else { return }
                    request.send(["type": "toolResult", "id": id, "result": result, "success": result["error"] == nil])
                }
            } else if event["type"] as? String == "request", let pending = event["request"] as? [String: Any] {
                self.agentRequest = pending
                self.publish(pending["kind"] as? String == "questions" ? "awaitingInput" : "awaitingApproval", "请在任务详情中查看并答复；本次没有自动授权。")
                self.onEvent?(event)
            } else if event["type"] as? String == "requestResolved" {
                self.agentRequest = nil; self.onEvent?(event)
            } else if let phase = event["state"] as? String {
                let detail = MiaoCallResultContract.message(event, fallback: "Codex 任务状态已更新。")
                if phase == "completed" { self.publish("acting", "Codex 已结束，正在保存结果。") }
                else if ["connecting", "thinking", "acting"].contains(phase) { self.publish(phase, detail); self.onEvent?(event) }
            } else { self.onEvent?(event) }
        }) { [weak self] result in
            guard let self, token == self.generation else { return }; self.child = nil; self.agentRequest = nil
            switch result {
            case .failure(let error): self.finish(self.state == "cancelling" ? "cancelled" : "error", self.state == "cancelling" ? "任务已停止，已发生的修改不会自动撤销。" : error.localizedDescription)
            case .success(let value):
                self.taskResult = value
                if let identity = value["taskId"] as? String { self.currentTaskID = identity }
                let outcome = MiaoCallResultContract.terminal(value)
                self.finish(outcome.state, outcome.message)
            }
        }
    }

    func cancel() {
        if ["connecting", "thinking", "acting", "awaitingApproval", "awaitingInput", "cancelling"].contains(state), let child {
            guard state != "cancelling" else { return }
            agentRequest = nil; spotify.cancel(); hideTask?.cancel()
            publish("cancelling", "正在停止 Codex；已经发生的修改不会自动撤销。")
            child.cancel()
            return
        }
        generation += 1; keyReleasedBeforeStart = true; agentRequest = nil
        enableGate.cancel()
        spotify.cancel()
        hideTask?.cancel(); child?.cancel(); child = nil; recorder.cancelAll()
        if isBusy { finish("cancelled", "已停止当前任务，已经发生的操作不会自动撤销。") }
        else { overlay.hide(); publish("idle", "") }
    }
    deinit {
        if let monitor { CGEvent.tapEnable(tap: monitor, enable: false); CFMachPortInvalidate(monitor) }
        child?.cancel(); wardrobeChild?.cancel(); recorder.cancelAll()
    }
}
