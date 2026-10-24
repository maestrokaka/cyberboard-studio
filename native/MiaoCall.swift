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
    private var previousMouseLocation: NSPoint?

    override func mouseDown(with event: NSEvent) {
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

    override func mouseUp(with event: NSEvent) { previousMouseLocation = nil }

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
    var onSubmit: ((String) -> Void)?
    var onCancel: (() -> Void)?
    private var animation: Timer?
    private var phase = 0.0
    private var active = false
    private let positionDefaultsKey = "CyberboardStudio.MiaoCallOverlay.position"

    init(resources: URL) {
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
        content.addSubview(image)
        let bubble = NSView(frame: NSRect(x: 152, y: 96, width: 328, height: 180))
        bubble.wantsLayer = true
        bubble.layer?.backgroundColor = NSColor(calibratedWhite: 0.065, alpha: 0.96).cgColor
        bubble.layer?.cornerRadius = 22
        bubble.layer?.borderWidth = 1
        bubble.layer?.borderColor = NSColor(calibratedRed: 1, green: 0.38, blue: 0.08, alpha: 0.65).cgColor
        bubble.layer?.shadowColor = NSColor.black.cgColor
        bubble.layer?.shadowOpacity = 0.4
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
    }
    @objc private func submitClicked() { onSubmit?(transcript.stringValue) }
    @objc private func cancelClicked() { onCancel?() }
    private func movePanel(by delta: NSPoint) {
        panel.setFrameOrigin(NSPoint(x: panel.frame.origin.x + delta.x,
                                     y: panel.frame.origin.y + delta.y))
    }
    func windowDidMove(_ notification: Notification) {
        guard (notification.object as? NSWindow) === panel else { return }
        constrainAndPersistPosition()
    }
    private func visibleScreen(for frame: NSRect) -> NSScreen? {
        // While dragging, follow the display under the pointer. Choosing the
        // panel's current center first traps it at the edge of its old display.
        if let screen = NSScreen.screens.first(where: { $0.visibleFrame.contains(NSEvent.mouseLocation) }) { return screen }
        let center = NSPoint(x: frame.midX, y: frame.midY)
        if let screen = NSScreen.screens.first(where: { $0.visibleFrame.contains(center) }) { return screen }
        if let screen = NSScreen.screens.first(where: { $0.visibleFrame.intersects(frame) }) { return screen }
        return NSScreen.main ?? NSScreen.screens.first
    }
    private func constrainedOrigin(_ origin: NSPoint, in visible: NSRect) -> NSPoint {
        let maxX = max(visible.minX, visible.maxX - panel.frame.width)
        let maxY = max(visible.minY, visible.maxY - panel.frame.height)
        return NSPoint(x: min(max(origin.x, visible.minX), maxX), y: min(max(origin.y, visible.minY), maxY))
    }
    private func constrainAndPersistPosition() {
        guard let screen = visibleScreen(for: panel.frame) else { return }
        let origin = constrainedOrigin(panel.frame.origin, in: screen.visibleFrame)
        if panel.frame.origin != origin { panel.setFrameOrigin(origin) }
        UserDefaults.standard.set(["x": origin.x, "y": origin.y], forKey: positionDefaultsKey)
    }
    private func restoreOrPlacePosition() {
        let stored = (UserDefaults.standard.dictionary(forKey: positionDefaultsKey) as? [String: Any]).flatMap { values -> NSPoint? in
            guard let x = values["x"] as? NSNumber, let y = values["y"] as? NSNumber,
                  x.doubleValue.isFinite, y.doubleValue.isFinite else { return nil }
            return NSPoint(x: x.doubleValue, y: y.doubleValue)
        }
        let screen = stored.flatMap { visibleScreen(for: NSRect(origin: $0, size: panel.frame.size)) } ?? NSScreen.main ?? NSScreen.screens.first
        guard let visible = screen?.visibleFrame else { return }
        let origin = stored.map { constrainedOrigin($0, in: visible) }
            ?? constrainedOrigin(NSPoint(x: visible.maxX - panel.frame.width - 30, y: visible.minY + 24), in: visible)
        panel.setFrameOrigin(origin)
        UserDefaults.standard.set(["x": origin.x, "y": origin.y], forKey: positionDefaultsKey)
    }
    func show(state: String, text: String, recognized: String) {
        let labels = ["configuring": "正在准备喵唤…", "preparing": "正在准备语音…", "listening": "正在听你说…", "transcribing": "正在识别语音…", "awaitingConfirmation": "听清楚啦，确认一下？",
                      "connecting": "正在连接 Codex…", "thinking": "Codex 正在思考…", "acting": "正在为你操作…",
                      "completed": "任务完成啦", "cancelled": "已取消", "error": "需要你看一下"]
        title.stringValue = labels[state] ?? "喵唤 MiaoCall"
        message.stringValue = String(text.prefix(220))
        let confirming = state == "awaitingConfirmation"
        transcript.isHidden = !confirming
        submit.isHidden = !confirming
        cancel.frame.origin.x = confirming ? 76 : 220
        cancel.title = ["completed", "error", "cancelled"].contains(state) ? "收起" : "取消"
        if confirming { transcript.stringValue = recognized }
        active = ["configuring", "preparing", "listening", "transcribing", "connecting", "thinking", "acting"].contains(state)
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
    }
    func hide() { panel.orderOut(nil); animation?.invalidate(); animation = nil; image.frame.origin.y = 0 }
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
            let reader = JSONLineReader(maximumBytes: 1024 * 1024) { record in DispatchQueue.main.async { onEvent(record) } }
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
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + (keepInput ? 150 : 85), execute: watchdog)
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

// The only desktop capability exposed to the managed Codex session. Spotify's
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
    var canBegin: (() -> Bool)?
    var isBusy: Bool { enableGate.isPending || !["idle", "completed", "cancelled", "error"].contains(state) }
    init(resources: URL, recorder: VoiceRecordingController = VoiceRecordingController()) {
        self.resources = resources; self.recorder = recorder
        overlay = MiaoCallOverlay(resources: resources)
        overlay.onCancel = { [weak self] in self?.cancel() }
        overlay.onSubmit = { [weak self] text in
            guard let self else { return }
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
    func status() -> [String: Any] {
        ["enabled": enabled, "state": state, "transcript": transcript, "message": message,
         "physicalKeyCode": MiaoCallKeyGate.keyCode, "confirmBeforeSend": options["confirmBeforeSend"] as? Bool ?? true,
         "permissions": ["inputMonitoring": CGPreflightListenEventAccess(), "accessibility": AXIsProcessTrusted(),
                         "microphone": AVCaptureDevice.authorizationStatus(for: .audio) == .authorized],
         "agent": "codex", "supportedAgents": ["codex"], "voiceProvider": profile["provider"] as? String ?? ""]
    }
    func handle(action: String, payload: [String: Any], completion: @escaping (Result<[String: Any], Error>) -> Void) {
        switch action {
        case "miaoCallStatus": completion(.success(status()))
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
    func disable() {
        enabled = false; gate.reset()
        if let monitor { CGEvent.tapEnable(tap: monitor, enable: false); CFMachPortInvalidate(monitor) }
        if let source { CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes) }
        monitor = nil; source = nil; cancel(); publish("idle", "喵唤已关闭，· 恢复正常输入。")
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
        publish("connecting", "已交给 Codex。此 Beta 仅开放 Spotify 播放与状态查询。")
        let token = generation
        let request = MiaoCallChild(); child = request
        let tracks = options["tracks"] as? [[String: Any]] ?? []
        request.start(resources: resources, action: "miaoCallWorker", payload: ["transcript": clean, "tracks": tracks], keepInput: true, onEvent: { [weak self, weak request] event in
            guard let self, let request, token == self.generation else { return }
            if event["type"] as? String == "tool", event["tool"] as? String == "spotify", let id = event["id"] ?? event["callId"], let arguments = event["arguments"] as? [String: Any] {
                self.publish("acting", "正在打开 Spotify，并核对歌曲和实际播放进度。")
                self.spotify.run(arguments: arguments, allowedTracks: tracks) { [weak self, weak request] result in
                    guard let self, let request, token == self.generation else { return }
                    request.send(["type": "toolResult", "id": id, "result": result, "success": result["error"] == nil])
                }
            } else if let state = event["state"] as? String {
                let text = MiaoCallResultContract.message(event, fallback: "Codex 任务状态已更新。")
                if state == "completed" { self.publish("acting", "Codex 已结束，正在核对最终播放结果。") }
                else if ["cancelled", "error"].contains(state) { self.finish(state, text) }
                else if ["connecting", "thinking", "acting"].contains(state) { self.publish(state, text) }
            }
        }) { [weak self] result in
            guard let self, token == self.generation else { return }; self.child = nil
            switch result {
            case .failure(let error):
                if !["cancelled", "error", "idle"].contains(self.state) { self.finish("error", error.localizedDescription) }
            case .success(let value):
                let outcome = MiaoCallResultContract.terminal(value)
                self.finish(outcome.state, outcome.message)
            }
        }
    }
    func cancel() {
        generation += 1; keyReleasedBeforeStart = true
        enableGate.cancel()
        spotify.cancel()
        hideTask?.cancel(); child?.cancel(); child = nil; recorder.cancelAll()
        if isBusy { finish("cancelled", "已取消当前语音任务。已完成的 Spotify 播放不会自动撤销。") }
        else { overlay.hide(); publish("idle", "") }
    }
    deinit {
        if let monitor { CGEvent.tapEnable(tap: monitor, enable: false); CFMachPortInvalidate(monitor) }
        child?.cancel(); recorder.cancelAll()
    }
}
