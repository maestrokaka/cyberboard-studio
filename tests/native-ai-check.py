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
    print("PASS macOS AI policies, recursive credential redaction and one-time model metadata migration; no Keychain or USB accessed.")
} catch {
    fputs("FAIL \(error.localizedDescription)\n", stderr)
    exit(1)
}
'''
# Allow throwing expressions in assertions while keeping the test helper small.
checks = checks.replace("@autoclosure () -> Bool", "@autoclosure () throws -> Bool").replace("if !condition()", "if try !condition()")
with tempfile.TemporaryDirectory(prefix="cyberboard-native-ai-") as directory:
    temporary = pathlib.Path(directory)
    swift = temporary / "main.swift"
    swift.write_text(policy + checks, encoding="utf-8")
    binary = temporary / "ai-check"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", str(root / "build/swift-module-cache"),
                    "-framework", "Cocoa", "-framework", "WebKit", "-framework", "UniformTypeIdentifiers", str(swift), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
