import Cocoa
import WebKit
import UniformTypeIdentifiers

// The bridge launches the CLI adapter directly; payloads never enter a shell command.
final class JSONLineReader {
    private var buffer = Data()
    private(set) var finalReply: [String: Any]?
    private(set) var parseError: String?
    private let onEvent: ([String: Any]) -> Void

    init(onEvent: @escaping ([String: Any]) -> Void) { self.onEvent = onEvent }

    func append(_ data: Data) {
        buffer.append(data)
        while let end = buffer.firstIndex(of: 0x0A) {
            let line = Data(buffer[..<end])
            buffer.removeSubrange(...end)
            consume(line)
        }
    }

    func finish() {
        if !buffer.isEmpty { consume(buffer); buffer.removeAll() }
    }

    private func consume(_ data: Data) {
        if data.allSatisfy({ $0 == 0x20 || $0 == 0x09 || $0 == 0x0D }) { return }
        do {
            guard let record = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                parseError = "后台返回了无法识别的数据。"
                return
            }
            if record["event"] != nil || record["type"] as? String == "event" {
                onEvent(record)
            } else if record["result"] != nil || record["error"] != nil {
                finalReply = record
            } else {
                parseError = "后台返回的数据缺少结果字段。"
            }
        } catch { parseError = "后台返回的数据不是有效的 JSON。" }
    }
}

final class StudioApp: NSObject, NSApplicationDelegate, NSWindowDelegate,
                       WKScriptMessageHandler, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private let backendQueue = DispatchQueue(label: "local.cyberboard.studio.backend", qos: .userInitiated)
    private var deviceWritePending = false
    private var navigationGeneration = 0
    private let backendActions: Set<String> = [
        "bootstrap", "detect", "plan", "execute", "history", "keymap", "setTime", "restorePlan", "saveWorkspace"
    ]
    private let deviceWriteActions: Set<String> = ["execute", "setTime"]

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.appearance = NSAppearance(named: .darkAqua)
        if let iconURL = Bundle.main.url(forResource: "AppIcon", withExtension: "icns"),
           let icon = NSImage(contentsOf: iconURL) {
            NSApp.applicationIconImage = icon
        }
        installMenus()

        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "studio")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.underPageBackgroundColor = NSColor(calibratedRed: 0.055, green: 0.063, blue: 0.082, alpha: 1)

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 940),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Cyberboard Studio"
        window.contentMinSize = NSSize(width: 1120, height: 760)
        window.backgroundColor = NSColor(calibratedRed: 0.055, green: 0.063, blue: 0.082, alpha: 1)
        window.appearance = NSAppearance(named: .darkAqua)
        window.contentView = webView
        window.delegate = self
        window.setFrameAutosaveName("CyberboardStudioMainWindow")
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        if let resourceDir = Bundle.main.resourceURL {
            let webDir = resourceDir.appendingPathComponent("web", isDirectory: true)
            let index = webDir.appendingPathComponent("index.html")
            if FileManager.default.fileExists(atPath: index.path) {
                webView.loadFileURL(index, allowingReadAccessTo: webDir)
                return
            }
        }
        webView.loadHTMLString("<html><body style='background:#0e1015;color:#eef1f7;font:18px -apple-system;padding:40px'><h1>Cyberboard Studio</h1><p>应用资源尚未准备好，请重新构建 App。</p></body></html>", baseURL: nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if deviceWritePending { showWriteInProgress(); return .terminateCancel }
        return .terminateNow
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if deviceWritePending { showWriteInProgress(); return false }
        return true
    }

    private func showWriteInProgress() {
        let alert = NSAlert()
        alert.messageText = "设备操作正在进行"
        alert.informativeText = "请等待同步完成后再退出 Cyberboard Studio。"
        alert.addButton(withTitle: "继续等待")
        alert.beginSheetModal(for: window)
    }

    private func installMenus() {
        let bar = NSMenu()
        let appRoot = NSMenuItem()
        bar.addItem(appRoot)
        let appMenu = NSMenu()
        appRoot.submenu = appMenu
        appMenu.addItem(withTitle: "关于 Cyberboard Studio", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隐藏 Cyberboard Studio", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出 Cyberboard Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let fileRoot = NSMenuItem(title: "文件", action: nil, keyEquivalent: "")
        let fileMenu = NSMenu(title: "文件")
        let importItem = fileMenu.addItem(withTitle: "导入 JSON…", action: #selector(importFromMenu), keyEquivalent: "i")
        importItem.target = self
        let exportItem = fileMenu.addItem(withTitle: "导出 JSON…", action: #selector(exportFromMenu), keyEquivalent: "e")
        exportItem.target = self
        fileRoot.submenu = fileMenu
        bar.addItem(fileRoot)

        let editRoot = NSMenuItem(title: "编辑", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editRoot.submenu = editMenu
        bar.addItem(editRoot)

        let viewRoot = NSMenuItem(title: "视图", action: nil, keyEquivalent: "")
        let viewMenu = NSMenu(title: "视图")
        let reload = viewMenu.addItem(withTitle: "重新载入", action: #selector(reloadFromMenu), keyEquivalent: "r")
        reload.target = self
        viewRoot.submenu = viewMenu
        bar.addItem(viewRoot)
        NSApp.mainMenu = bar
    }

    @objc private func importFromMenu() { sendEvent(["event": "menu", "action": "importJSON"]) }
    @objc private func exportFromMenu() { sendEvent(["event": "menu", "action": "exportJSON"]) }
    @objc private func reloadFromMenu() {
        if deviceWritePending { showWriteInProgress(); return }
        webView.reload()
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "studio", message.frameInfo.isMainFrame,
              let body = message.body as? [String: Any],
              let id = body["id"], (id is String || id is NSNumber),
              let action = body["action"] as? String else { return }
        let payload = body["payload"] as? [String: Any] ?? [:]
        switch action {
        case "importJSON": importJSON(id: id)
        case "exportJSON": exportJSON(id: id, payload: payload)
        default:
            guard backendActions.contains(action) else {
                reply(id: id, error: "不支持的操作：\(action)"); return
            }
            runBackend(id: id, action: action, payload: payload)
        }
    }

    private func importJSON(id: Any) {
        let generation = navigationGeneration
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "选择 Cyberboard 灯效或完整配置 JSON"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self, generation == self.navigationGeneration else { return }
            guard response == .OK, let url = panel.url else {
                self.reply(id: id, result: ["cancelled": true]); return
            }
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let bytes = try Data(contentsOf: url)
                    let json = try JSONSerialization.jsonObject(with: bytes)
                    DispatchQueue.main.async {
                        guard generation == self.navigationGeneration else { return }
                        self.reply(id: id, result: ["fileName": url.lastPathComponent, "json": json])
                    }
                } catch {
                    DispatchQueue.main.async {
                        guard generation == self.navigationGeneration else { return }
                        self.reply(id: id, error: "无法读取这个 JSON 文件：\(error.localizedDescription)")
                    }
                }
            }
        }
    }

    private func exportJSON(id: Any, payload: [String: Any]) {
        let generation = navigationGeneration
        guard let json = payload["json"], JSONSerialization.isValidJSONObject(json) else {
            reply(id: id, error: "没有可导出的有效 JSON。")
            return
        }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        panel.canCreateDirectories = true
        panel.nameFieldStringValue = (payload["fileName"] as? String).map { URL(fileURLWithPath: $0).lastPathComponent } ?? "Cyberboard-design.json"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self, generation == self.navigationGeneration else { return }
            guard response == .OK, let url = panel.url else {
                self.reply(id: id, result: ["cancelled": true]); return
            }
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let data = try JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
                    try data.write(to: url, options: .atomic)
                    DispatchQueue.main.async {
                        guard generation == self.navigationGeneration else { return }
                        self.reply(id: id, result: ["fileName": url.lastPathComponent, "path": url.path])
                    }
                } catch {
                    DispatchQueue.main.async {
                        guard generation == self.navigationGeneration else { return }
                        self.reply(id: id, error: "保存失败：\(error.localizedDescription)")
                    }
                }
            }
        }
    }

    private func runBackend(id: Any, action: String, payload: [String: Any]) {
        let generation = navigationGeneration
        let writesDevice = deviceWriteActions.contains(action)
        if writesDevice && deviceWritePending {
            reply(id: id, error: "设备操作正在进行，请等待完成后再试。")
            return
        }
        guard let resources = Bundle.main.resourceURL else {
            reply(id: id, error: "找不到应用资源目录。")
            return
        }
        // Release bundles carry a frozen CLI adapter, independent of Python installations.
        // A source backend is used only when a developer explicitly supplies a Python path.
        let frozenBackend = resources.appendingPathComponent("backend/CyberboardBackend/CyberboardBackend")
        let executable: URL
        let leadingArguments: [String]
        if FileManager.default.isExecutableFile(atPath: frozenBackend.path) {
            executable = frozenBackend
            leadingArguments = []
        } else {
            let configuredPython = ProcessInfo.processInfo.environment["CYBERBOARD_CLI_PYTHON"]
                ?? (Bundle.main.object(forInfoDictionaryKey: "CyberboardDevelopmentPythonPath") as? String)
            let script = resources.appendingPathComponent("backend/bridge.py")
            guard let path = configuredPython, !path.isEmpty,
                  (path as NSString).isAbsolutePath,
                  FileManager.default.isExecutableFile(atPath: path),
                  FileManager.default.fileExists(atPath: script.path) else {
                reply(id: id, error: "后台组件缺失，请重新下载并完整解压 Cyberboard Studio。")
                return
            }
            executable = URL(fileURLWithPath: path)
            leadingArguments = ["-X", "utf8", "-u", script.path]
        }
        let input: Data
        do { input = try JSONSerialization.data(withJSONObject: payload) }
        catch { reply(id: id, error: "请求数据无法转换为 JSON。"); return }
        if writesDevice { deviceWritePending = true }
        let stateDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Cyberboard Studio", isDirectory: true)

        backendQueue.async { [weak self] in
            guard let self else { return }
            let process = Process()
            process.executableURL = executable
            process.arguments = leadingArguments + ["--action", action,
                                 "--state-dir", stateDir.path, "--resource-dir", resources.path]
            process.currentDirectoryURL = resources
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONUNBUFFERED"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            environment.removeValue(forKey: "PYTHONHOME")
            environment.removeValue(forKey: "PYTHONPATH")
            process.environment = environment
            let stdinPipe = Pipe(), stdoutPipe = Pipe(), stderrPipe = Pipe()
            process.standardInput = stdinPipe
            process.standardOutput = stdoutPipe
            process.standardError = stderrPipe
            let lines = JSONLineReader { record in
                var event = record
                if event["id"] == nil { event["id"] = id }
                DispatchQueue.main.async {
                    guard generation == self.navigationGeneration else { return }
                    self.sendEvent(event)
                }
            }
            let stderrLock = NSLock()
            var stderrData = Data()
            let ioGroup = DispatchGroup()
            var launchError: String?
            do {
                try process.run()
                ioGroup.enter()
                DispatchQueue.global(qos: .utility).async {
                    let data = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                    stderrLock.lock(); stderrData = Data(data.suffix(65536)); stderrLock.unlock()
                    ioGroup.leave()
                }
                ioGroup.enter()
                DispatchQueue.global(qos: .utility).async {
                    do { try stdinPipe.fileHandleForWriting.write(contentsOf: input) }
                    catch { /* A process that exits early may close stdin before receiving the payload. */ }
                    try? stdinPipe.fileHandleForWriting.close()
                    ioGroup.leave()
                }
                while let chunk = try stdoutPipe.fileHandleForReading.read(upToCount: 65536), !chunk.isEmpty {
                    lines.append(chunk)
                }
                process.waitUntilExit()
                ioGroup.wait()
                lines.finish()
            } catch {
                launchError = "无法启动后台组件：\(error.localizedDescription)"
                if process.isRunning { process.terminate(); process.waitUntilExit() }
                try? stdinPipe.fileHandleForWriting.close()
                ioGroup.wait()
            }
            stderrLock.lock(); let diagnostics = String(decoding: stderrData, as: UTF8.self); stderrLock.unlock()
            if !diagnostics.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                NSLog("Cyberboard Studio backend [%@]: %@", action, diagnostics)
            }
            let final = lines.finalReply
            let errorMessage = launchError ?? lines.parseError
            DispatchQueue.main.async {
                if writesDevice { self.deviceWritePending = false }
                guard generation == self.navigationGeneration else { return }
                if let error = errorMessage {
                    self.reply(id: id, error: error)
                } else if let final {
                    if let error = final["error"] { self.reply(id: id, error: error) }
                    else if let result = final["result"] {
                        if process.terminationStatus == 0 { self.reply(id: id, result: result) }
                        else { self.reply(id: id, error: "后台操作未成功完成（\(process.terminationStatus)）。") }
                    }
                } else {
                    self.reply(id: id, error: "后台没有返回操作结果（\(process.terminationStatus)）。")
                }
            }
        }
    }

    private func reply(id: Any, result: Any) { sendJSON(method: "receive", value: ["id": id, "result": result]) }
    private func reply(id: Any, error: Any) { sendJSON(method: "receive", value: ["id": id, "error": error]) }
    private func sendEvent(_ event: [String: Any]) { sendJSON(method: "event", value: event) }

    private func sendJSON(method: String, value: [String: Any]) {
        guard JSONSerialization.isValidJSONObject(value),
              let bytes = try? JSONSerialization.data(withJSONObject: value, options: [.withoutEscapingSlashes]),
              let json = String(data: bytes, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.StudioBridge && window.StudioBridge.\(method)(\(json));", completionHandler: nil)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        sendEvent(["event": "nativeReady", "app": "Cyberboard Studio", "version": "0.1.0"])
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        navigationGeneration += 1
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.absoluteString == "about:blank" { decisionHandler(.allow); return }
        if url.isFileURL, let resources = Bundle.main.resourceURL {
            let webDir = resources.appendingPathComponent("web", isDirectory: true).standardizedFileURL.path + "/"
            if url.standardizedFileURL.path.hasPrefix(webDir) { decisionHandler(.allow); return }
        }
        if navigationAction.navigationType == .linkActivated, ["https", "http"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }
}

let app = NSApplication.shared
let delegate = StudioApp()
app.delegate = delegate
app.run()
