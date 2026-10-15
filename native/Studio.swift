import Cocoa
import WebKit
import UniformTypeIdentifiers
import Security

struct AICredentialAccess {
    let read: (String) throws -> String?
    let write: (String, String) throws -> Void
    let delete: (String) throws -> Void
    var exists: ((String) throws -> Bool)? = nil
}

final class AISettingsStore {
    private let stateDirectory: URL
    private let lock = NSLock()
    private let service = "Cyberboard Studio.Kimi"
    private var lastModelMigration = false
    private var profiles: [String: [String: String]] = [:]
    private let credentialAccess: AICredentialAccess?
    private let beforeMetadataCommit: (() throws -> Void)?
    private static let endpoints: [String: [String]] = [
        "kimi-code": ["https://api.kimi.com/coding/v1", "https://api.kimi.ai/coding/v1"],
        "kimi-open": ["https://api.moonshot.cn/v1", "https://api.moonshot.ai/v1"],
        "minimax": ["https://api.minimax.cn/v1", "https://api.minimax.io/v1"],
        "deepseek": ["https://api.deepseek.com", "https://api.deepseek.com/v1"]
    ]

    init(stateDirectory: URL, credentialAccess: AICredentialAccess? = nil, beforeMetadataCommit: (() throws -> Void)? = nil) {
        self.stateDirectory = stateDirectory
        self.credentialAccess = credentialAccess
        self.beforeMetadataCommit = beforeMetadataCommit
    }
    private static let defaultModels = ["kimi-code": "k3", "kimi-open": "kimi-k3", "minimax": "MiniMax-M3", "deepseek": "deepseek-flash"]
    static func supportsImages(_ config: [String: String]) -> Bool {
        switch config["provider"] {
        case "minimax": return ["MiniMax-M3", "MiniMax-M3.1-Flash-Preview"].contains(config["model"] ?? "")
        case "deepseek": return ["deepseek-flash", "deepseek-v4-flash-vision-exp"].contains(config["model"] ?? "")
        default: return config["provider"] == "kimi-code" || config["provider"] == "kimi-open"
        }
    }
    private static func failure(_ message: String) -> NSError {
        NSError(domain: "CyberboardStudio.AI", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
    private static func validToken(_ value: String) -> Bool {
        value.range(of: "\\A[A-Za-z0-9._:-]{1,128}\\z", options: .regularExpression) != nil
    }
    static func requestID(_ payload: [String: Any]) throws -> String {
        guard let value = payload["requestId"] as? String,
              value.range(of: "\\A[A-Za-z0-9_-]{1,80}\\z", options: .regularExpression) != nil else { throw failure("AI 请求编号无效。") }
        return value
    }
    static func configuration(_ payload: [String: Any]) throws -> [String: String] {
        let provider = payload["provider"] as? String ?? "kimi-code"
        guard let endpoints = Self.endpoints[provider] else { throw Self.failure("请选择受支持的模型服务。") }
        var baseURL = (payload["baseUrl"] as? String ?? endpoints[0]).trimmingCharacters(in: .whitespacesAndNewlines)
        while baseURL.hasSuffix("/") { baseURL.removeLast() }
        guard endpoints.contains(baseURL) else { throw Self.failure("API 地址必须为对应服务的官方 HTTPS 地址。") }
        let model = (payload["model"] as? String ?? Self.defaultModels[provider]!)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validToken(model) else { throw Self.failure("模型名称只能包含字母、数字、点、横线、下划线或冒号，最多 128 个字符。") }
        return ["provider": provider, "baseUrl": baseURL, "model": model]
    }
    private func query(_ provider: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: provider]
    }
    private func readKey(_ provider: String) throws -> String? {
        if let credentialAccess { return try credentialAccess.read(provider) }
        var request = query(provider)
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let bytes = item as? Data, let key = String(data: bytes, encoding: .utf8) else {
            throw Self.failure("无法访问 macOS 钥匙串，请允许 Cyberboard Studio 访问已保存的 API Key。")
        }
        return key
    }
    private func keyExists(_ provider: String) throws -> Bool {
        if let credentialAccess {
            if let exists = credentialAccess.exists { return try exists(provider) }
            return !(try credentialAccess.read(provider) ?? "").isEmpty
        }
        // Loading settings only needs to know whether a saved item exists.
        // Never request secret data or wait for a system authorization dialog here.
        var request = query(provider)
        request[kSecReturnAttributes as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        request[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUIFail
        var item: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &item)
        if status == errSecItemNotFound { return false }
        guard status == errSecSuccess else {
            throw Self.failure("此服务的密钥状态暂时无法读取，请检查系统凭据访问权限后重试。")
        }
        return true
    }
    private func writeKey(_ provider: String, _ key: String) throws {
        if let credentialAccess { try credentialAccess.write(provider, key); return }
        let attributes = [kSecValueData as String: Data(key.utf8)]
        let status = SecItemUpdate(query(provider) as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var request = query(provider)
            request[kSecValueData as String] = Data(key.utf8)
            request[kSecAttrLabel as String] = "Cyberboard Studio · \(provider)"
            guard SecItemAdd(request as CFDictionary, nil) == errSecSuccess else { throw Self.failure("无法将 API Key 保存到 macOS 钥匙串。") }
        } else if status != errSecSuccess { throw Self.failure("无法更新 macOS 钥匙串中的 API Key。") }
    }
    private func deleteKey(_ provider: String) throws {
        if let credentialAccess { try credentialAccess.delete(provider); return }
        let status = SecItemDelete(query(provider) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw Self.failure("无法删除 macOS 钥匙串中的 API Key。") }
    }
    private func writeMetadata(_ config: [String: String]) throws {
        try FileManager.default.createDirectory(at: stateDirectory, withIntermediateDirectories: true)
        let path = stateDirectory.appendingPathComponent("ai-settings.json")
        var metadata: [String: Any] = config
        metadata["modelDefaultsVersion"] = 2
        profiles[config["provider"]!] = config
        metadata["profilesVersion"] = 1
        metadata["profiles"] = profiles
        // Only non-secret service metadata is serialized, including during migration.
        let bytes = try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
        let temporary = stateDirectory.appendingPathComponent(".ai-settings-" + UUID().uuidString + ".tmp")
        defer { try? FileManager.default.removeItem(at: temporary) }
        try bytes.write(to: temporary, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
        try beforeMetadataCommit?()
        // Rename is the final fallible operation: permissions are set before the
        // active configuration is replaced, so a reported failure cannot hide a commit.
        let status = temporary.withUnsafeFileSystemRepresentation { source in
            path.withUnsafeFileSystemRepresentation { destination in rename(source!, destination!) }
        }
        guard status == 0 else { throw Self.failure("无法保存模型配置，原配置已保留。") }
    }
    func loadConfiguration() throws -> [String: String] {
        lastModelMigration = false
        profiles = [:]
        let path = stateDirectory.appendingPathComponent("ai-settings.json")
        if !FileManager.default.fileExists(atPath: path.path) { return try Self.configuration([:]) }
        do {
            let bytes = try Data(contentsOf: path)
            guard bytes.count <= 16384, let value = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { throw Self.failure("") }
            var config = try Self.configuration(value)
            if let marker = value["profilesVersion"] {
                guard let version = marker as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(), version.doubleValue == 1 else { throw Self.failure("") }
            }
            if let rawProfiles = value["profiles"] {
                guard let items = rawProfiles as? [String: [String: Any]], items.count <= Self.endpoints.count else { throw Self.failure("") }
                for (provider, item) in items {
                    guard Self.endpoints[provider] != nil, item["provider"] as? String == provider else { throw Self.failure("") }
                    profiles[provider] = try Self.configuration(item)
                }
            }
            profiles[config["provider"]!] = config
            let version = (value["modelDefaultsVersion"] as? NSNumber)?.intValue ?? 0
            if version < 2 {
                if config["provider"] == "kimi-code", config["model"] == "kimi-for-coding" {
                    config["model"] = "k3"
                    lastModelMigration = true
                }
                try writeMetadata(config)
            }
            return config
        } catch { throw Self.failure("模型配置文件无法读取，请在模型配置中重新保存服务配置。") }
    }
    private func publicSettings(_ config: [String: String], hasKey: Any) throws -> [String: Any] {
        var result: [String: Any] = config
        result["hasKey"] = hasKey
        result["credentialStore"] = "macOS 钥匙串"
        result["modelDefaultsVersion"] = 2
        result["modelMigrated"] = lastModelMigration
        result["supportsImages"] = Self.supportsImages(config)
        var publicProfiles: [String: [String: Any]] = [:]
        for provider in Self.endpoints.keys.sorted() {
            let profile = try profiles[provider] ?? Self.configuration(["provider": provider])
            var item: [String: Any] = profile
            if provider == config["provider"] {
                item["hasKey"] = hasKey
                if hasKey is NSNull { item["credentialError"] = "此服务的密钥状态暂时无法读取，请检查系统凭据访问权限后重试。" }
            }
            else {
                do { item["hasKey"] = try keyExists(provider) }
                catch {
                    item["hasKey"] = NSNull()
                    item["credentialError"] = "此服务的密钥暂时无法读取，请检查系统凭据访问权限后重试。"
                }
            }
            item["supportsImages"] = Self.supportsImages(profile)
            publicProfiles[provider] = item
        }
        result["profiles"] = publicProfiles
        return result
    }
    func get() throws -> [String: Any] {
        lock.lock(); defer { lock.unlock() }
        let config = try loadConfiguration()
        let hasKey: Any
        do { hasKey = try keyExists(config["provider"]!) }
        catch { hasKey = NSNull() }
        var result = try publicSettings(config, hasKey: hasKey)
        if hasKey is NSNull { result["credentialError"] = "此服务的密钥状态暂时无法读取，请检查系统凭据访问权限后重试。" }
        return result
    }
    func revealAIKey(_ payload: [String: Any]) throws -> [String: Any] {
        lock.lock(); defer { lock.unlock() }
        guard let provider = payload["provider"] as? String, Self.endpoints[provider] != nil else {
            throw Self.failure("请选择受支持的模型服务。")
        }
        // The explicit local reveal action is separate from ordinary settings;
        // it never loads metadata, changes the active provider or writes a key.
        do { return ["apiKey": try readKey(provider) ?? ""] }
        catch { throw Self.failure("无法读取已保存的 API Key，请检查系统凭据访问权限后重试。") }
    }
    func save(_ payload: [String: Any]) throws -> [String: Any] {
        lock.lock(); defer { lock.unlock() }
        // A user-initiated save can recover malformed metadata without deleting credentials.
        do { _ = try loadConfiguration() } catch { profiles = [:] }
        lastModelMigration = false
        let config = try Self.configuration(payload)
        let input = payload["apiKey"] as? String ?? ""
        guard !input.contains("\r"), !input.contains("\n"), input.count <= 4096 else { throw Self.failure("API Key 格式无效，请粘贴完整的单行密钥。") }
        let key = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard key.isEmpty || key.unicodeScalars.allSatisfy({ $0.value >= 33 && $0.value <= 126 }) else { throw Self.failure("API Key 只能包含可打印的单行字符，不包含空格。") }
        let remove = payload["removeKey"] as? Bool ?? false
        guard !(remove && !key.isEmpty) else { throw Self.failure("删除密钥与设置新密钥不能同时进行。") }
        let provider = config["provider"]!
        // Prepare every fallible read and the public response before credentials
        // or active metadata change. Unrelated locked accounts are explicit unknowns.
        let previousKey = try readKey(provider)
        let nextKey = remove ? nil : (key.isEmpty ? previousKey : key)
        profiles[provider] = config
        let prepared = try publicSettings(config, hasKey: !(nextKey ?? "").isEmpty)
        let changesKey = nextKey != previousKey
        do {
            if changesKey {
                if let nextKey { try writeKey(provider, nextKey) }
                else { try deleteKey(provider) }
            }
            try writeMetadata(config)
        } catch {
            if changesKey {
                do {
                    if let previousKey { try writeKey(provider, previousKey) }
                    else { try deleteKey(provider) }
                } catch {
                    throw Self.failure("模型配置未切换，但密钥恢复失败，当前密钥状态无法确认。请检查系统凭据权限后重新保存该服务。")
                }
            }
            throw Self.failure("模型配置未保存，原配置和密钥已保留。请检查本机存储与凭据访问权限后重试。")
        }
        return prepared
    }
    func inject(_ payload: [String: Any], allowInactive: Bool = false) throws -> (payload: [String: Any], secret: String) {
        lock.lock(); defer { lock.unlock() }
        let active = try loadConfiguration()
        let provider = payload["provider"] as? String ?? active["provider"]!
        guard Self.endpoints[provider] != nil else { throw Self.failure("请选择受支持的模型服务。") }
        guard allowInactive || provider == active["provider"] else { throw Self.failure("当前模型配置已切换，请刷新后重新制作。") }
        let config = try provider == active["provider"] ? active : (profiles[provider] ?? Self.configuration(["provider": provider]))
        guard let key = try readKey(config["provider"]!), !key.isEmpty else { throw Self.failure("请先在模型配置中保存 API Key。") }
        var settings: [String: Any] = config
        settings["apiKey"] = key
        var result = payload
        result["ai"] = settings
        return (result, key)
    }
    static func redact(_ value: Any, secret: String) -> Any {
        if let string = value as? String { return secret.isEmpty ? string : string.replacingOccurrences(of: secret, with: "[已隐藏]") }
        if let items = value as? [Any] { return items.map { redact($0, secret: secret) } }
        if let object = value as? [String: Any] {
            var safe: [String: Any] = [:]
            for (key, item) in object where key != "apiKey" { safe[key] = redact(item, secret: secret) }
            return safe
        }
        return value
    }
}

// The bridge launches the CLI adapter directly; payloads never enter a shell command.
final class JSONLineReader {
    private var buffer = Data()
    private(set) var finalReply: [String: Any]?
    private(set) var parseError: String?
    private let onEvent: ([String: Any]) -> Void

    init(onEvent: @escaping ([String: Any]) -> Void) { self.onEvent = onEvent }

    func read(from handle: FileHandle) {
        // read(upToCount:) can wait for the entire requested length or EOF on
        // macOS pipes. availableData returns each available chunk immediately.
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty { break }
            append(chunk)
        }
    }

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
    private let aiQueue = DispatchQueue(label: "local.cyberboard.studio.ai", qos: .userInitiated)
    private let credentialQueue = DispatchQueue(label: "local.cyberboard.studio.credentials", qos: .userInitiated)
    private let aiProcessLock = NSLock()
    private var aiProcess: Process?
    private var aiCancelled = false
    private var activeAIRequestID: String?
    private let aiSettings = AISettingsStore(stateDirectory: FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Cyberboard Studio", isDirectory: true))
    private var deviceWritePending = false
    private var navigationGeneration = 0
    private let backendActions: Set<String> = [
        "bootstrap", "detect", "readConfiguration", "plan", "builtInPlan", "initializePlan", "execute", "history", "keymap", "setTime", "restorePlan", "saveWorkspace"
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
        cancelActiveAI()
        return .terminateNow
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if deviceWritePending { showWriteInProgress(); return false }
        cancelActiveAI()
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
        cancelActiveAI()
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
        case "importAIImages": importAIImages(id: id)
        case "getAISettings", "saveAISettings", "revealAIKey":
            if action == "saveAISettings", activeAIRequestID != nil {
                reply(id: id, error: "AI 请求正在进行，请先取消或等待完成再修改模型配置。"); return
            }
            let generation = navigationGeneration
            credentialQueue.async { [weak self] in
                guard let self else { return }
                do {
                    let result: [String: Any]
                    switch action {
                    case "getAISettings": result = try self.aiSettings.get()
                    case "revealAIKey": result = try self.aiSettings.revealAIKey(payload)
                    default: result = try self.aiSettings.save(payload)
                    }
                    DispatchQueue.main.async { guard generation == self.navigationGeneration else { return }; self.reply(id: id, result: result) }
                } catch {
                    DispatchQueue.main.async { guard generation == self.navigationGeneration else { return }; self.reply(id: id, error: error.localizedDescription) }
                }
            }
        case "generateAI", "testAIConnection":
            guard !deviceWritePending else { reply(id: id, error: "设备写入正在进行，请等待完成后再使用 AI。"); return }
            guard activeAIRequestID == nil else { reply(id: id, error: "已有 AI 请求正在进行，请先取消或等待完成。"); return }
            do {
                let requestID = try (action == "generateAI" || payload["requestId"] != nil)
                    ? AISettingsStore.requestID(payload) : UUID().uuidString
                activeAIRequestID = requestID
                aiProcessLock.lock(); aiCancelled = false; aiProcessLock.unlock()
                runBackend(id: id, action: action, payload: payload, aiRequestID: requestID)
            } catch { reply(id: id, error: error.localizedDescription) }
        case "cancelAI":
            do {
                let requestID = try AISettingsStore.requestID(payload)
                let cancelled = activeAIRequestID == requestID
                if cancelled { cancelActiveAI() }
                reply(id: id, result: ["cancelled": cancelled, "requestId": requestID])
            } catch { reply(id: id, error: error.localizedDescription) }
        default:
            guard backendActions.contains(action) else {
                reply(id: id, error: "不支持的操作：\(action)"); return
            }
            runBackend(id: id, action: action, payload: payload)
        }
    }

    private func importAIImages(id: Any) {
        let generation = navigationGeneration
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg, .webP, .gif]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.message = "选择最多 3 张参考图（PNG、JPEG、WebP 或 GIF，每张最多 20 MB）"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self, generation == self.navigationGeneration else { return }
            guard response == .OK else { self.reply(id: id, result: ["cancelled": true]); return }
            let urls = panel.urls
            guard !urls.isEmpty, urls.count <= 3 else { self.reply(id: id, error: "一次最多选择 3 张参考图。"); return }
            do {
                for url in urls {
                    let size = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
                    guard size.isRegularFile == true, let bytes = size.fileSize, bytes > 0, bytes <= 20 * 1024 * 1024 else {
                        self.reply(id: id, error: "参考图必须为有效文件，且每张不超过 20 MB。"); return
                    }
                }
            } catch { self.reply(id: id, error: "无法读取所选参考图，请重新选择。"); return }
            // Paths come only from the user-approved native dialog; the web bridge cannot call prepareAIImages directly.
            self.runBackend(id: id, action: "prepareAIImages", payload: ["paths": urls.map { $0.path }])
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

    private func cancelActiveAI() {
        guard activeAIRequestID != nil else { return }
        aiProcessLock.lock()
        aiCancelled = true
        if let process = aiProcess, process.isRunning { process.terminate() }
        aiProcessLock.unlock()
    }

    private func runBackend(id: Any, action: String, payload: [String: Any], aiRequestID: String? = nil) {
        let generation = navigationGeneration
        let isAI = aiRequestID != nil
        let writesDevice = deviceWriteActions.contains(action)
        if writesDevice && (deviceWritePending || activeAIRequestID != nil) {
            reply(id: id, error: "设备操作或 AI 请求正在进行，请等待完成后再试。")
            return
        }
        guard let resources = Bundle.main.resourceURL else {
            if isAI { activeAIRequestID = nil }
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
                if isAI { activeAIRequestID = nil }
                reply(id: id, error: "后台组件缺失，请重新下载并完整解压 Cyberboard Studio。")
                return
            }
            executable = URL(fileURLWithPath: path)
            leadingArguments = ["-X", "utf8", "-u", script.path]
        }
        if writesDevice { deviceWritePending = true }
        let stateDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Cyberboard Studio", isDirectory: true)

        let queue = isAI ? aiQueue : backendQueue
        queue.async { [weak self] in
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
            var secret = ""
            let lines = JSONLineReader { record in
                var event = isAI ? AISettingsStore.redact(record, secret: secret) as! [String: Any] : record
                if event["id"] == nil { event["id"] = id }
                if let aiRequestID { event["requestId"] = aiRequestID }
                DispatchQueue.main.async {
                    guard generation == self.navigationGeneration else { return }
                    self.sendEvent(event)
                }
            }
            let stderrLock = NSLock()
            var stderrData = Data()
            let ioGroup = DispatchGroup()
            var launchError: String?
            var watchdog: DispatchWorkItem?
            do {
                var requestPayload = payload
                if isAI {
                    let injected = try self.aiSettings.inject(payload, allowInactive: action == "testAIConnection")
                    requestPayload = injected.payload
                    secret = injected.secret
                }
                let input = try JSONSerialization.data(withJSONObject: requestPayload)
                if isAI {
                    self.aiProcessLock.lock()
                    if self.aiCancelled {
                        self.aiProcessLock.unlock()
                        throw NSError(domain: "CyberboardStudio.AI.Cancel", code: 1)
                    }
                    self.aiProcess = process
                    do { try process.run(); self.aiProcessLock.unlock() }
                    catch { self.aiProcess = nil; self.aiProcessLock.unlock(); throw error }
                    let timeout = DispatchWorkItem { [weak self, weak process] in
                        guard let self, let process else { return }
                        self.aiProcessLock.lock()
                        if self.aiProcess === process, process.isRunning {
                            self.aiCancelled = true
                            process.terminate()
                        }
                        self.aiProcessLock.unlock()
                    }
                    watchdog = timeout
                    DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 360, execute: timeout)
                } else { try process.run() }
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
                lines.read(from: stdoutPipe.fileHandleForReading)
                process.waitUntilExit()
                ioGroup.wait()
                lines.finish()
            } catch {
                launchError = isAI ? AISettingsStore.redact(error.localizedDescription, secret: secret) as? String
                    : "无法启动后台组件：\(error.localizedDescription)"
                if process.isRunning { process.terminate(); process.waitUntilExit() }
                try? stdinPipe.fileHandleForWriting.close()
                ioGroup.wait()
            }
            watchdog?.cancel()
            self.aiProcessLock.lock()
            let cancelled = isAI && self.aiCancelled
            if isAI, self.aiProcess === process { self.aiProcess = nil }
            self.aiProcessLock.unlock()
            stderrLock.lock(); let diagnostics = String(decoding: stderrData, as: UTF8.self); stderrLock.unlock()
            if !isAI && action != "prepareAIImages" && !diagnostics.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                NSLog("Cyberboard Studio backend [%@]: %@", action, diagnostics)
            }
            let final = lines.finalReply.map { isAI ? AISettingsStore.redact($0, secret: secret) as! [String: Any] : $0 }
            let errorMessage = launchError ?? lines.parseError
            DispatchQueue.main.async {
                if writesDevice { self.deviceWritePending = false }
                if isAI, self.activeAIRequestID == aiRequestID { self.activeAIRequestID = nil }
                guard generation == self.navigationGeneration else { return }
                if cancelled {
                    self.reply(id: id, result: ["cancelled": true, "requestId": aiRequestID!])
                } else if let error = errorMessage {
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
        sendEvent(["event": "nativeReady", "app": "Cyberboard Studio", "version": "0.3.1"])
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        cancelActiveAI()
        navigationGeneration += 1
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if deviceWritePending { decisionHandler(.cancel); return }
        if url.absoluteString == "about:blank" { decisionHandler(.allow); return }
        if url.isFileURL, let resources = Bundle.main.resourceURL {
            let webDir = resources.appendingPathComponent("web", isDirectory: true).standardizedFileURL.path + "/"
            if url.standardizedFileURL.path.hasPrefix(webDir) { decisionHandler(.allow); return }
        }
        if navigationAction.navigationType == .linkActivated,
           ["https", "http"].contains(url.scheme ?? "") || url.absoluteString == "mailto:maestrokaka@gmail.com" {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }
}

let app = NSApplication.shared
let delegate = StudioApp()
app.delegate = delegate
app.run()
