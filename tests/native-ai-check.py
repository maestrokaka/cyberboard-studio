#!/usr/bin/env python3
"""Run the shipped Swift settings policy without opening UI, Keychain or USB."""
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
source = (root / "native/Studio.swift").read_text(encoding="utf-8")
policy = source.split("// The bridge launches the CLI adapter directly;", 1)[0]
checks = r'''
func check(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw NSError(domain: "OfflineCheck", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}
func rejects(_ operation: () throws -> Void) throws {
    do { try operation() } catch { return }
    throw NSError(domain: "OfflineCheck", code: 1, userInfo: [NSLocalizedDescriptionKey: "Expected request rejection"])
}
do {
    let defaults = try AISettingsStore.configuration([:])
    try check(defaults["provider"] == "kimi-code" && defaults["model"] == "k3", "Code defaults")
    try check(try AISettingsStore.configuration(["provider": "kimi-open"])["model"] == "kimi-k3", "Open platform defaults")
    let global = try AISettingsStore.configuration(["baseUrl": "https://api.kimi.ai/coding/v1/", "model": "kimi:code-v1.0"])
    try check(global["baseUrl"] == "https://api.kimi.ai/coding/v1", "Global endpoint")
    for endpoint in ["http://api.kimi.com/coding/v1", "https://api.kimi.com.evil/coding/v1", "https://user@api.kimi.com/coding/v1", "https://api.kimi.com/coding/v1?key=x", "https://api.moonshot.cn/v1", "https://127.0.0.1/v1"] {
        try rejects { _ = try AISettingsStore.configuration(["baseUrl": endpoint]) }
    }
    for model in ["evil\nheader", "模型", String(repeating: "a", count: 129), "../../model"] {
        try rejects { _ = try AISettingsStore.configuration(["model": model]) }
    }
    try rejects { _ = try AISettingsStore.requestID(["requestId": "bad request"]) }
    try check(try AISettingsStore.requestID(["requestId": "generate-1"]) == "generate-1", "Request token")
    let secret = "sk-offline-credential-check"
    let reply: [String: Any] = ["apiKey": secret, "result": ["nested": ["note": "prefix:" + secret, "apiKey": secret]], "array": [secret, 4, true]]
    let safe = AISettingsStore.redact(reply, secret: secret)
    let data = try JSONSerialization.data(withJSONObject: safe, options: [.sortedKeys])
    let json = String(decoding: data, as: UTF8.self)
    try check(!json.contains(secret) && !json.contains("apiKey"), "Nested response credential disclosure")
    try check(json.contains("4") && json.contains("true"), "Redaction changed unrelated values")
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("cyberboard-model-migration-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let path = directory.appendingPathComponent("ai-settings.json")
    let store = AISettingsStore(stateDirectory: directory)
    func metadata(_ value: [String: Any]) throws {
        try JSONSerialization.data(withJSONObject: value).write(to: path, options: .atomic)
    }
    try metadata(["provider": "kimi-code", "model": "kimi-for-coding"])
    try check(try store.loadConfiguration()["model"] == "k3", "Legacy default was not migrated")
    let saved = try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [String: Any]
    try check(saved["modelDefaultsVersion"] as? Int == 2 && saved["apiKey"] == nil, "Migration marker or secret boundary")
    try check(try store.loadConfiguration()["model"] == "k3", "Migration was not stable")
    try metadata(["provider": "kimi-code", "model": "kimi-for-coding", "modelDefaultsVersion": 2])
    try check(try store.loadConfiguration()["model"] == "kimi-for-coding", "Explicit legacy alias was migrated again")
    try metadata(["provider": "kimi-code", "model": "k3-256k"])
    try check(try store.loadConfiguration()["model"] == "k3-256k", "Custom model was replaced")
    try metadata(["provider": "kimi-open", "model": "kimi-k3"])
    try check(try store.loadConfiguration()["model"] == "kimi-k3", "Open-platform model was replaced")

    try check(try AISettingsStore.configuration(["provider": "minimax"])["model"] == "MiniMax-M3", "MiniMax defaults")
    try check(try AISettingsStore.configuration(["provider": "deepseek"])["model"] == "deepseek-flash", "DeepSeek defaults")
    try check(AISettingsStore.supportsImages(try AISettingsStore.configuration(["provider": "deepseek"])), "Flash image capability")
    try check(!AISettingsStore.supportsImages(try AISettingsStore.configuration(["provider": "deepseek", "model": "deepseek-v4-pro"])), "Pro incorrectly marked vision")
    for provider in ["minimax", "deepseek"] {
        for endpoint in ["http://api.deepseek.com", "https://api.minimax.cn.evil/v1", "https://api.deepseek.com/v1?x=1", "https://user@api.minimax.cn/v1", "https://api.kimi.com/coding/v1"] {
            try rejects { _ = try AISettingsStore.configuration(["provider": provider, "baseUrl": endpoint]) }
        }
    }
    var keys: [String: String] = [:]
    let access = AICredentialAccess(read: { keys[$0] }, write: { keys[$0] = $1 }, delete: { keys.removeValue(forKey: $0) })
    let multiDirectory = directory.appendingPathComponent("multi")
    let multi = AISettingsStore(stateDirectory: multiDirectory, credentialAccess: access)
    _ = try multi.save(["provider": "kimi-code", "model": "k3-256k", "apiKey": "old-kimi-key"])
    _ = try multi.save(["provider": "minimax", "baseUrl": "https://api.minimax.io/v1", "model": "MiniMax-M3", "apiKey": "minimax-key"])
    _ = try multi.save(["provider": "deepseek", "model": "deepseek-v4-pro", "apiKey": "deepseek-key"])
    let multiPath = multiDirectory.appendingPathComponent("ai-settings.json")
    let storedText = String(decoding: try Data(contentsOf: multiPath), as: UTF8.self)
    try check(!storedText.contains("-key") && !storedText.contains("apiKey"), "Provider metadata leaked keys")
    let reopened = AISettingsStore(stateDirectory: multiDirectory, credentialAccess: access)
    let settings = try reopened.get()
    let allProfiles = settings["profiles"] as! [String: [String: Any]]
    try check(allProfiles["kimi-code"]?["model"] as? String == "k3-256k", "Kimi model lost after service switching")
    try check(allProfiles["minimax"]?["baseUrl"] as? String == "https://api.minimax.io/v1", "MiniMax region lost after restart")
    try check(allProfiles["deepseek"]?["hasKey"] as? Bool == true && allProfiles["deepseek"]?["supportsImages"] as? Bool == false, "Profile capability/key state wrong")
    try rejects { _ = try reopened.inject(["provider": "minimax"]) }
    let injected = try reopened.inject(["provider": "minimax"], allowInactive: true)
    try check(injected.secret == "minimax-key", "Inactive connection tested wrong key")

    let cleanMetadata = try Data(contentsOf: multiPath)
    for marker: Any in [99, "1", true] {
        var future = try JSONSerialization.jsonObject(with: cleanMetadata) as! [String: Any]
        future["profilesVersion"] = marker
        let invalidBytes = try JSONSerialization.data(withJSONObject: future)
        try invalidBytes.write(to: multiPath, options: .atomic)
        try rejects { _ = try reopened.loadConfiguration() }
        try check(try Data(contentsOf: multiPath) == invalidBytes, "Unknown schema was silently rewritten")
    }
    try cleanMetadata.write(to: multiPath, options: .atomic)
    _ = try reopened.save(["provider": "minimax", "removeKey": true])
    try check(keys["minimax"] == nil && keys["kimi-code"] == "old-kimi-key" && keys["deepseek"] == "deepseek-key", "Delete crossed provider credentials")
    try rejects { _ = try reopened.save(["provider": "deepseek", "apiKey": "has space"]) }

    var transactionalKeys: [String: String] = [:]
    var deniedProvider = ""
    var failMetadata = false
    var denyRollback = false
    let transactionAccess = AICredentialAccess(read: { provider in
        if provider == deniedProvider { throw NSError(domain: "Mock", code: 1) }
        return transactionalKeys[provider]
    }, write: { provider, key in
        if denyRollback && key == "kimi-original" { throw NSError(domain: "Mock", code: 2) }
        transactionalKeys[provider] = key
    }, delete: { transactionalKeys.removeValue(forKey: $0) })
    let transactionDirectory = directory.appendingPathComponent("transactions")
    let transactionStore = AISettingsStore(stateDirectory: transactionDirectory, credentialAccess: transactionAccess, beforeMetadataCommit: {
        if failMetadata { throw NSError(domain: "Mock", code: 3) }
    })
    _ = try transactionStore.save(["provider": "kimi-code", "apiKey": "kimi-original"])
    deniedProvider = "minimax"
    let successful = try transactionStore.save(["provider": "deepseek", "apiKey": "deepseek-original"])
    let unknown = (successful["profiles"] as! [String: [String: Any]])["minimax"]!
    try check(successful["provider"] as? String == "deepseek" && unknown["hasKey"] is NSNull && unknown["credentialError"] is String,
              "Inactive key failure hid committed save or became false absence")
    try check(try transactionStore.loadConfiguration()["provider"] == "deepseek" && transactionalKeys["deepseek"] == "deepseek-original", "Successful active state differs from reply")
    let transactionPath = transactionDirectory.appendingPathComponent("ai-settings.json")
    let baselineBytes = try Data(contentsOf: transactionPath)
    try rejects { _ = try transactionStore.save(["provider": "minimax", "apiKey": "cannot-read-old-key"]) }
    try check(try Data(contentsOf: transactionPath) == baselineBytes && transactionalKeys["minimax"] == nil, "Target unreadable key mutated state")
    failMetadata = true
    try rejects { _ = try transactionStore.save(["provider": "kimi-code", "apiKey": "kimi-replacement"]) }
    try check(try Data(contentsOf: transactionPath) == baselineBytes && transactionalKeys["kimi-code"] == "kimi-original", "Metadata failure did not roll back existing key")
    try rejects { _ = try transactionStore.save(["provider": "deepseek", "removeKey": true]) }
    try check(try Data(contentsOf: transactionPath) == baselineBytes && transactionalKeys["deepseek"] == "deepseek-original", "Metadata failure did not roll back deleted key")
    try rejects { _ = try transactionStore.save(["provider": "kimi-open", "apiKey": "open-new"]) }
    try check(try Data(contentsOf: transactionPath) == baselineBytes && transactionalKeys["kimi-open"] == nil, "Metadata failure retained a newly added credential")
    try check(try transactionStore.loadConfiguration()["provider"] == "deepseek", "Failed save switched active provider")
    denyRollback = true
    do {
        _ = try transactionStore.save(["provider": "kimi-code", "apiKey": "rollback-failure-new"])
        throw NSError(domain: "OfflineCheck", code: 4)
    } catch {
        try check(error.localizedDescription.contains("密钥恢复失败"), "Failed rollback did not report uncertain credential state")
    }
    try check(try Data(contentsOf: transactionPath) == baselineBytes && transactionalKeys["kimi-code"] == "rollback-failure-new", "Rollback failure state report was inaccurate")
    try check(try FileManager.default.contentsOfDirectory(atPath: transactionDirectory.path).allSatisfy({ !$0.hasSuffix(".tmp") }), "Failed metadata save left staging files")

    let revealDirectory = directory.appendingPathComponent("reveal-local")
    var revealReads = 0
    var revealDenied = ""
    let revealKeys = ["kimi-code": "mock-kimi-visible", "minimax": "mock-minimax-visible", "deepseek": "mock-deepseek-visible"]
    let revealAccess = AICredentialAccess(read: { provider in
        revealReads += 1
        if provider == revealDenied { throw NSError(domain: "Mock", code: 5) }
        return revealKeys[provider]
    }, write: { _, _ in throw NSError(domain: "OfflineCheck", code: 6) }, delete: { _ in throw NSError(domain: "OfflineCheck", code: 7) })
    let revealStore = AISettingsStore(stateDirectory: revealDirectory, credentialAccess: revealAccess)
    _ = try revealStore.save(["provider": "deepseek"])
    let revealPath = revealDirectory.appendingPathComponent("ai-settings.json")
    let revealBaseline = try Data(contentsOf: revealPath)
    for provider in ["kimi-code", "kimi-open", "minimax", "deepseek"] {
        let revealed = try revealStore.revealAIKey(["provider": provider])
        try check(Set(revealed.keys) == ["apiKey"] && revealed["apiKey"] as? String == (revealKeys[provider] ?? ""), "Reveal returned wrong provider key or extra fields")
    }
    try check(try Data(contentsOf: revealPath) == revealBaseline && revealStore.loadConfiguration()["provider"] == "deepseek", "Read-only reveal switched active configuration")
    let publicJSON = String(decoding: try JSONSerialization.data(withJSONObject: revealStore.get()), as: UTF8.self)
    try check(!publicJSON.contains("mock-") && !publicJSON.contains("apiKey"), "Normal get revealed a key")
    let readsBeforeInvalid = revealReads
    for payload: [String: Any] in [[:], ["provider": ""], ["provider": "other"], ["provider": "../kimi-code"], ["provider": 3]] {
        try rejects { _ = try revealStore.revealAIKey(payload) }
    }
    try check(revealReads == readsBeforeInvalid, "Invalid reveal selected a credential")
    revealDenied = "minimax"
    do {
        _ = try revealStore.revealAIKey(["provider": "minimax"])
        throw NSError(domain: "OfflineCheck", code: 8)
    } catch {
        try check(error.localizedDescription.contains("无法读取已保存"), "Failed reveal pretended the key was absent")
    }
    try check(try Data(contentsOf: revealPath) == revealBaseline, "Reveal failure mutated metadata")

    var secretReads = 0
    var existenceDenied = ""
    let presenceAccess = AICredentialAccess(read: { _ in
        secretReads += 1
        throw NSError(domain: "Mock", code: 9)
    }, write: { _, _ in throw NSError(domain: "OfflineCheck", code: 10) }, delete: { _ in throw NSError(domain: "OfflineCheck", code: 11) }, exists: { provider in
        if provider == existenceDenied { throw NSError(domain: "Mock", code: 12) }
        return provider == "kimi-code"
    })
    let presenceStore = AISettingsStore(stateDirectory: directory.appendingPathComponent("presence-only"), credentialAccess: presenceAccess)
    let presence = try presenceStore.get()
    let presenceProfiles = presence["profiles"] as! [String: [String: Any]]
    try check(presence["hasKey"] as? Bool == true && presenceProfiles["minimax"]?["hasKey"] as? Bool == false, "Presence lookup confused saved and missing credentials")
    try check(secretReads == 0, "Loading settings requested secret data")
    existenceDenied = "kimi-code"
    let uncertainPresence = try presenceStore.get()
    let uncertainProfiles = uncertainPresence["profiles"] as! [String: [String: Any]]
    try check(uncertainPresence["hasKey"] is NSNull && uncertainPresence["credentialError"] is String && uncertainProfiles["kimi-code"]?["hasKey"] is NSNull, "Active presence failure became missing or broke settings load")
    try check(secretReads == 0, "Failed presence lookup requested secret data")
    try rejects { _ = try presenceStore.revealAIKey(["provider": "kimi-code"]) }
    try check(secretReads == 1, "Explicit reveal did not attempt the selected credential read")
    // Real production file storage is exercised only under this temporary tree.
    let localDirectory = directory.appendingPathComponent("local-key-files")
    let local = AISettingsStore(stateDirectory: localDirectory)
    let missing = try local.get()
    let missingProfiles = missing["profiles"] as! [String: [String: Any]]
    try check(missing["hasKey"] as? Bool == false && missing["credentialError"] == nil && missing["credentialStore"] as? String == "本机文件", "Missing local file was not a clean unconfigured state")
    for provider in ["kimi-code", "kimi-open", "minimax", "deepseek"] {
        try check(missingProfiles[provider]?["hasKey"] as? Bool == false && missingProfiles[provider]?["credentialError"] == nil, "Missing provider file became an access failure")
        try check(try local.revealAIKey(["provider": provider])["apiKey"] as? String == "", "Missing file reveal was not empty")
        try rejects { _ = try local.inject(["provider": provider], allowInactive: true) }
    }
    try check(!FileManager.default.fileExists(atPath: localDirectory.path), "Reading missing keys created metadata or credentials")

    // Existing plain key files and model metadata remain byte-exact on reads.
    let keyDirectory = localDirectory.appendingPathComponent("ai-keys")
    try FileManager.default.createDirectory(at: keyDirectory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    let kimiLocalPath = keyDirectory.appendingPathComponent("kimi-code.key")
    let minimaxLocalPath = keyDirectory.appendingPathComponent("minimax.key")
    let localMetadataPath = localDirectory.appendingPathComponent("ai-settings.json")
    let originalKimi = Data("mock-existing-local-kimi-key".utf8)
    let originalMinimax = Data("mock-existing-local-minimax-key".utf8)
    try originalKimi.write(to: kimiLocalPath, options: .atomic)
    try originalMinimax.write(to: minimaxLocalPath, options: .atomic)
    for path in [kimiLocalPath, minimaxLocalPath] {
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
    let existingMetadata = try JSONSerialization.data(withJSONObject: ["provider": "kimi-code", "baseUrl": "https://api.kimi.ai/coding/v1", "model": "k3-256k", "modelDefaultsVersion": 2, "profilesVersion": 1], options: [.sortedKeys])
    try existingMetadata.write(to: localMetadataPath, options: .atomic)
    let existingSettings = try local.get()
    try check(existingSettings["hasKey"] as? Bool == true && existingSettings["baseUrl"] as? String == "https://api.kimi.ai/coding/v1", "Existing local credential or metadata was not recognized")
    try check(try local.revealAIKey(["provider": "kimi-code"])["apiKey"] as? String == "mock-existing-local-kimi-key", "Read changed the existing local Kimi key")
    try check(try local.revealAIKey(["provider": "minimax"])["apiKey"] as? String == "mock-existing-local-minimax-key", "Read selected the wrong service key")
    let request: [String: Any] = ["requestId": "local-inject", "brief": "offline-check", "images": [["name": "reference.jpg", "dataUrl": "data:image/jpeg;base64,offline"]]]
    let localInjection = try local.inject(request)
    let injectedAI = localInjection.payload["ai"] as! [String: String]
    try check(localInjection.secret == "mock-existing-local-kimi-key" && injectedAI["apiKey"] == localInjection.secret && injectedAI["provider"] == "kimi-code", "Local injection did not use the active provider")
    try check(localInjection.payload["requestId"] as? String == "local-inject" && localInjection.payload["images"] != nil, "Injection changed the user request")
    try check(try Data(contentsOf: localMetadataPath) == existingMetadata && Data(contentsOf: kimiLocalPath) == originalKimi && Data(contentsOf: minimaxLocalPath) == originalMinimax, "Read, reveal or injection changed local storage")

    _ = try local.save(["provider": "kimi-code", "model": "k3-256k", "apiKey": ""])
    try check(try Data(contentsOf: kimiLocalPath) == originalKimi, "Blank input replaced the saved key")
    _ = try local.save(["provider": "minimax", "baseUrl": "https://api.minimax.io/v1", "apiKey": "mock-minimax-local-new"])
    _ = try local.save(["provider": "deepseek", "model": "deepseek-v4-pro", "apiKey": "mock-deepseek-local-new"])
    try check(try Data(contentsOf: kimiLocalPath) == originalKimi, "Saving another provider changed Kimi")
    let localMetadataBytes = try Data(contentsOf: localMetadataPath)
    let localMetadataText = String(decoding: localMetadataBytes, as: UTF8.self)
    try check(!localMetadataText.contains("mock-") && !localMetadataText.contains("apiKey"), "Local keys leaked into metadata")
    let localRestart = AISettingsStore(stateDirectory: localDirectory)
    let restartedSettings = try localRestart.get()
    let restartedProfiles = restartedSettings["profiles"] as! [String: [String: Any]]
    try check(restartedSettings["provider"] as? String == "deepseek" && restartedSettings["hasKey"] as? Bool == true && restartedSettings["credentialError"] == nil, "Restart lost the active local key")
    try check(restartedProfiles["kimi-code"]?["model"] as? String == "k3-256k" && restartedProfiles["minimax"]?["baseUrl"] as? String == "https://api.minimax.io/v1", "Provider switching lost saved model/region profiles")
    try check(try localRestart.revealAIKey(["provider": "kimi-code"])["apiKey"] as? String == "mock-existing-local-kimi-key", "Restart changed Kimi key")
    try check(try localRestart.revealAIKey(["provider": "minimax"])["apiKey"] as? String == "mock-minimax-local-new", "Restart changed MiniMax key")
    try check(try localRestart.revealAIKey(["provider": "deepseek"])["apiKey"] as? String == "mock-deepseek-local-new", "Restart changed DeepSeek key")
    try rejects { _ = try localRestart.inject(["provider": "kimi-code"]) }
    try check(try localRestart.inject(["provider": "minimax"], allowInactive: true).secret == "mock-minimax-local-new", "Inactive connection injection crossed providers")
    let publicLocalText = String(decoding: try JSONSerialization.data(withJSONObject: localRestart.get()), as: UTF8.self)
    try check(!publicLocalText.contains("mock-") && !publicLocalText.contains("apiKey"), "Normal settings disclosed local keys")
    for path in [keyDirectory.appendingPathComponent("deepseek.key"), minimaxLocalPath] {
        let permissions = try FileManager.default.attributesOfItem(atPath: path.path)[.posixPermissions] as! NSNumber
        try check(permissions.intValue & 0o777 == 0o600, "Local key file permissions")
    }
    let directoryPermissions = try FileManager.default.attributesOfItem(atPath: keyDirectory.path)[.posixPermissions] as! NSNumber
    try check(directoryPermissions.intValue & 0o777 == 0o700, "Local key directory permissions")

    _ = try local.save(["provider": "minimax", "removeKey": true])
    try check(try Data(contentsOf: minimaxLocalPath).isEmpty, "Explicit removal did not clear the local key")
    let afterDelete = AISettingsStore(stateDirectory: localDirectory)
    try check(try afterDelete.get()["hasKey"] as? Bool == false, "Deleted key reappeared after restart")
    try check(try afterDelete.revealAIKey(["provider": "minimax"])["apiKey"] as? String == "", "Reveal returned a deleted key")
    try rejects { _ = try afterDelete.inject(["provider": "minimax"]) }
    try check(try afterDelete.revealAIKey(["provider": "kimi-code"])["apiKey"] as? String == "mock-existing-local-kimi-key" && afterDelete.revealAIKey(["provider": "deepseek"])["apiKey"] as? String == "mock-deepseek-local-new", "Removal crossed providers")
    try FileManager.default.removeItem(at: minimaxLocalPath)
    let absentAfterDelete = AISettingsStore(stateDirectory: localDirectory)
    try check(try absentAfterDelete.get()["hasKey"] as? Bool == false && absentAfterDelete.revealAIKey(["provider": "minimax"])["apiKey"] as? String == "", "Missing file did not remain unconfigured")
    try check(!FileManager.default.fileExists(atPath: minimaxLocalPath.path), "Missing key file was repopulated during reads")
    _ = try absentAfterDelete.save(["provider": "minimax", "apiKey": "mock-minimax-reentered"])
    try check(try absentAfterDelete.get()["hasKey"] as? Bool == true && absentAfterDelete.revealAIKey(["provider": "minimax"])["apiKey"] as? String == "mock-minimax-reentered", "Direct re-entry failed after a missing key")

    var failLocalMetadata = false
    let fileTransactionDirectory = directory.appendingPathComponent("local-transactions")
    let fileTransactions = AISettingsStore(stateDirectory: fileTransactionDirectory, beforeMetadataCommit: {
        if failLocalMetadata { throw NSError(domain: "MockFileCommit", code: 23) }
    })
    _ = try fileTransactions.save(["provider": "kimi-code", "apiKey": "mock-file-original"])
    let fileTransactionMetadata = fileTransactionDirectory.appendingPathComponent("ai-settings.json")
    let fileTransactionKey = fileTransactionDirectory.appendingPathComponent("ai-keys/kimi-code.key")
    let fileTransactionOpenKey = fileTransactionDirectory.appendingPathComponent("ai-keys/kimi-open.key")
    let fileMetadataBaseline = try Data(contentsOf: fileTransactionMetadata)
    let fileKeyBaseline = try Data(contentsOf: fileTransactionKey)
    failLocalMetadata = true
    try rejects { _ = try fileTransactions.save(["provider": "kimi-code", "apiKey": "mock-file-replacement"]) }
    try check(try Data(contentsOf: fileTransactionMetadata) == fileMetadataBaseline && Data(contentsOf: fileTransactionKey) == fileKeyBaseline, "File transaction failed to restore an overwritten key")
    try rejects { _ = try fileTransactions.save(["provider": "kimi-code", "removeKey": true]) }
    try check(try Data(contentsOf: fileTransactionKey) == fileKeyBaseline, "File transaction failed to restore a removed key")
    try rejects { _ = try fileTransactions.save(["provider": "kimi-open", "apiKey": "mock-file-recovery"]) }
    try check(!FileManager.default.fileExists(atPath: fileTransactionOpenKey.path), "Failed recovery left a new key or removal marker")
    try check(try Data(contentsOf: fileTransactionMetadata) == fileMetadataBaseline, "Failed recovery changed active metadata")
    failLocalMetadata = false
    _ = try fileTransactions.save(["provider": "kimi-open", "apiKey": "mock-file-recovery"])
    try check(try fileTransactions.get()["hasKey"] as? Bool == true, "Recovery after metadata failure remained locked")
    _ = try fileTransactions.save(["provider": "kimi-open", "removeKey": true])
    let removedBaseline = try Data(contentsOf: fileTransactionOpenKey)
    failLocalMetadata = true
    try rejects { _ = try fileTransactions.save(["provider": "kimi-open", "apiKey": "mock-would-resurrect"]) }
    try check(try Data(contentsOf: fileTransactionOpenKey) == removedBaseline && removedBaseline.isEmpty, "Rollback lost the removal marker")
    failLocalMetadata = false
    _ = try fileTransactions.save(["provider": "kimi-code", "apiKey": "mock-before-malformed"])
    failLocalMetadata = true
    let malformedBytes = Data([0xff, 0xfe, 0x80])
    try malformedBytes.write(to: fileTransactionKey, options: .atomic)
    let malformedMetadata = try Data(contentsOf: fileTransactionMetadata)
    try check(try fileTransactions.get()["hasKey"] is NSNull, "Malformed local key was reported as usable")
    try rejects { _ = try fileTransactions.save(["provider": "kimi-code", "apiKey": "mock-repair-malformed"]) }
    try check(try Data(contentsOf: fileTransactionKey) == malformedBytes && Data(contentsOf: fileTransactionMetadata) == malformedMetadata, "Failed repair did not restore exact malformed bytes and metadata")
    failLocalMetadata = false
    _ = try fileTransactions.save(["provider": "kimi-code", "apiKey": "mock-repair-malformed"])
    try check(try fileTransactions.revealAIKey(["provider": "kimi-code"])["apiKey"] as? String == "mock-repair-malformed", "Malformed local key blocked a direct replacement")
    try malformedBytes.write(to: fileTransactionKey, options: .atomic)
    _ = try fileTransactions.save(["provider": "kimi-code", "removeKey": true])
    try check(try Data(contentsOf: fileTransactionKey).isEmpty && fileTransactions.get()["hasKey"] as? Bool == false, "Malformed local key could not be removed")
    try Data(repeating: 65, count: 4097).write(to: fileTransactionKey, options: .atomic)
    _ = try fileTransactions.save(["provider": "kimi-code", "apiKey": "mock-repair-too-long"])
    try check(try fileTransactions.revealAIKey(["provider": "kimi-code"])["apiKey"] as? String == "mock-repair-too-long", "Invalid-length local key blocked a direct replacement")
    try check(try FileManager.default.contentsOfDirectory(atPath: fileTransactionKey.deletingLastPathComponent().path).allSatisfy({ !$0.hasSuffix(".tmp") }), "Key storage left temporary credential files")
    print("PASS macOS AI policies, isolated local key get/save/reveal/inject/delete/restart/provider switching and transaction rollback; no system credential access or USB.")
} catch {
    fputs("FAIL \(error.localizedDescription)\n", stderr)
    exit(1)
}
'''
# Allow throwing expressions in assertions while keeping the test helper small.
checks = checks.replace("@autoclosure () -> Bool", "@autoclosure () throws -> Bool").replace("if !condition()", "if try !condition()")
for token in ("SecItem", "SecKeychain", "kSec", "Keychain", "Security", "legacyCredentialRead", "readLegacyKey", "legacyChecked", "legacyUnavailable", "Cyberboard Studio.Kimi"):
    assert token not in source, f"Native host contains forbidden system credential access: {token}"
assert "Security" not in (root / "native/build.sh").read_text(encoding="utf-8")
with tempfile.TemporaryDirectory(prefix="cyberboard-native-ai-") as directory:
    temporary = pathlib.Path(directory)
    swift = temporary / "main.swift"
    swift.write_text(policy + checks, encoding="utf-8")
    binary = temporary / "ai-check"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", str(root / "build/swift-module-cache"),
                    "-framework", "Cocoa", "-framework", "WebKit", "-framework", "UniformTypeIdentifiers", str(swift), "-o", str(binary)], check=True)
    dependencies = subprocess.run(["/usr/bin/otool", "-L", str(binary)], capture_output=True, text=True, check=True).stdout
    symbols = subprocess.run(["/usr/bin/nm", "-u", str(binary)], capture_output=True, text=True, check=True).stdout
    assert "Security.framework" not in dependencies, "Native test binary links Security"
    assert "SecItem" not in symbols and "SecKeychain" not in symbols, "Native test binary imports system credential functions"
    subprocess.run([str(binary)], check=True)
    print("PASS native source/build and compiled-binary guards: no system credential APIs or Security framework")
