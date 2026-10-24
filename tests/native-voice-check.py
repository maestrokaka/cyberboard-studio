#!/usr/bin/env python3
"""Exercise the production macOS recorder with synthetic WAV/permission handles.

No microphone permission, audio device, model API, personal state or USB is
accessed. Windows hardware lifecycle checks run in windows/tests/host-bridge.
"""
from pathlib import Path
import plistlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "native/Studio.swift").read_text(encoding="utf-8")
controller = source[source.index("protocol VoiceCaptureHandle"):source.index("struct AICredentialAccess")]
build = ROOT / "build/voice-keymap-local-20261018"
build.mkdir(parents=True, exist_ok=True)
cache = ROOT / "build/swift-module-cache"
cache.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="offline-native-voice-", dir=build) as directory:
    temporary = Path(directory)
    harness = temporary / "main.swift"
    harness.write_text("import Foundation\nimport AVFoundation\n" + controller + r'''
func check(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
    if try !condition() { throw VoiceRecordingController.failure(message) }
}
func rejects(_ run: () throws -> Void) throws {
    do { try run() } catch { return }
    throw VoiceRecordingController.failure("Expected rejection")
}
func wave(_ pcm: Data, extra: Bool = false) -> Data {
    var result = Data("RIFF".utf8)
    func n(_ value: Int, _ count: Int) { for offset in 0..<count { result.append(UInt8((value >> (offset * 8)) & 255)) } }
    n(36 + pcm.count + (extra ? 16 : 0), 4); result.append(Data("WAVEfmt ".utf8)); n(16, 4)
    n(1, 2); n(1, 2); n(16000, 4); n(32000, 4); n(2, 2); n(16, 2)
    if extra { result.append(Data("JUNK".utf8)); n(8, 4); result.append(Data("private!".utf8)) }
    result.append(Data("data".utf8)); n(pcm.count, 4); result.append(pcm)
    return result
}
final class FakeRecorder: VoiceCaptureHandle {
    let url: URL
    var currentTime: TimeInterval = 1
    var prepares = 0, starts = 0, stops = 0
    var canStart = true
    var bytes = wave(Data(repeating: 0, count: 32000), extra: true)
    init(_ url: URL) { self.url = url }
    func prepareToRecord() -> Bool { prepares += 1; return true }
    func record(forDuration duration: TimeInterval) -> Bool {
        starts += 1
        precondition(duration == 60)
        return canStart
    }
    func stop() { stops += 1; try! bytes.write(to: url) }
}
let directory = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-voice-" + UUID().uuidString)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: directory) }
func empty() throws -> Bool { try FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty }
var permissionRequests = 0
var captures: [FakeRecorder] = []
let recorder = VoiceRecordingController(temporaryDirectory: directory, requestPermission: { completion in
    permissionRequests += 1; completion(true)
}, createRecorder: { url in let device = FakeRecorder(url); captures.append(device); return device })
try check(permissionRequests == 0 && captures.isEmpty, "Controller construction accessed microphone")
var startResult: [String: Any]?
recorder.start("voice-one") { if case .success(let value) = $0 { startResult = value } }
try check(permissionRequests == 1 && startResult?["recording"] as? Bool == true, "Explicit start did not record")
try check(captures[0].starts == 1 && captures[0].prepares == 1, "Wrong capture lifecycle")
let mode = try FileManager.default.attributesOfItem(atPath: captures[0].url.path)[.posixPermissions] as! NSNumber
try check(mode.intValue == 0o600, "Temporary audio permissions too broad")
var duplicateRejected = false
recorder.start("voice-two") { if case .failure = $0 { duplicateRejected = true } }
try check(duplicateRejected && permissionRequests == 1, "Duplicate start requested permission/created capture")
try rejects { _ = try recorder.stop("wrong") }
try check(recorder.cancel("wrong")["cancelled"] as? Bool == false && captures[0].stops == 0, "Stale cancel stopped another request")
let stopped = try recorder.stop("voice-one")
let audio = stopped["audio"] as! [String: Any]
let base64 = (audio["dataUrl"] as! String).dropFirst("data:audio/wav;base64,".count)
let normalized = Data(base64Encoded: String(base64))!
try check(audio["durationMs"] as? Int == 1000 && audio["sampleRate"] as? Int == 16000, "Audio timing changed")
try check(normalized.count == 32044 && !String(decoding: normalized, as: UTF8.self).contains("private!"), "Non-audio metadata crossed bridge")
try check(captures[0].stops == 1 && recorder.requestID == nil && empty(), "Stop did not immediately delete/release")
try rejects { _ = try recorder.stop("voice-one") }
print("PASS macOS explicit permission, duplicate/stale requests, PCM/WAV timing, private metadata strip and stop cleanup")

var states: [[String: Any]] = []
recorder.onState = { states.append($0) }
recorder.start("at-limit") { _ in }
recorder.finishAtLimit("unrelated")
try check(captures[1].stops == 0, "Stale deadline stopped capture")
recorder.finishAtLimit("at-limit")
try check(states.count == 1 && states[0]["reason"] as? String == "limit" && captures[1].stops == 1 && empty(), "Deadline retained file/device")
try check(recorder.requestID == "at-limit", "Deadline lost stop ownership")
try check((try recorder.stop("at-limit")["audio"] as! [String: Any])["durationMs"] as? Int == 1000, "Deadline discarded recording")
recorder.start("cancel-active") { _ in }
try check(recorder.cancel("cancel-active")["cancelled"] as? Bool == true && empty() && captures[2].stops == 1, "Active cancellation leaked audio/device")
recorder.start("exit-active") { _ in }
recorder.cancelAll()
try check(empty() && recorder.requestID == nil && captures[3].stops == 1, "Exit/reload cancellation leaked")
print("PASS macOS 60 second deadline, retained in-memory stop result, cancel and exit cleanup")

var callbacks: [(Bool) -> Void] = []
var delayedCaptures = 0, cancelledStarts = 0
let pending = VoiceRecordingController(temporaryDirectory: directory, requestPermission: { callbacks.append($0) }, createRecorder: { url in
    delayedCaptures += 1; return FakeRecorder(url)
})
pending.start("reused-id") { if case .failure = $0 { cancelledStarts += 1 } }
try rejects { _ = try pending.stop("reused-id") }
_ = pending.cancel("reused-id")
pending.start("reused-id") { _ in }
callbacks[0](true)
try check(cancelledStarts == 1 && delayedCaptures == 0, "Delayed cancelled permission started a reused request")
callbacks[1](true)
try check(delayedCaptures == 1, "Current permission callback was ignored")
pending.cancelAll()
var deniedFactory = false, deniedResult = false
let denied = VoiceRecordingController(temporaryDirectory: directory, requestPermission: { $0(false) }, createRecorder: { url in
    deniedFactory = true; return FakeRecorder(url)
})
denied.start("denied") { if case .failure = $0 { deniedResult = true } }
try check(deniedResult && !deniedFactory && empty(), "Denied permission created audio")
let failing = VoiceRecordingController(temporaryDirectory: directory, requestPermission: { $0(true) }, createRecorder: { url in
    let capture = FakeRecorder(url); capture.canStart = false; return capture
})
failing.start("failed") { _ in }
try check(failing.requestID == nil && empty(), "Failed start retained audio")
let invalid = VoiceRecordingController(temporaryDirectory: directory, requestPermission: { $0(true) }, createRecorder: { url in
    let capture = FakeRecorder(url); capture.bytes = Data("invalid".utf8); return capture
})
invalid.start("invalid") { _ in }
try rejects { _ = try invalid.stop("invalid") }
try check(invalid.requestID == nil && empty(), "Invalid audio retained a file/device")
print("PASS macOS pending permission cancellation/race, denial, failed start and invalid audio cleanup")

for payload: [String: Any] in [[:], ["requestId": "bad id"], ["requestId": String(repeating: "a", count: 81)], ["requestId": 1]] {
    try rejects { _ = try VoiceRecordingController.requestID(payload) }
}
try check(try VoiceRecordingController.requestID(["requestId": "v-1_2"]) == "v-1_2", "Valid ID rejected")
var wrongRate = wave(Data(repeating: 0, count: 32000)); wrongRate[24] = 0
for bytes in [Data(), Data("invalid".utf8), wrongRate, wave(Data()), wave(Data(repeating: 0, count: 1920002))] {
    try rejects { _ = try VoiceRecordingController.wavAudio(bytes) }
}
let maximum = try VoiceRecordingController.wavAudio(wave(Data(repeating: 0, count: 1920000)))
try check(maximum["durationMs"] as? Int == 60000, "Exact maximum rejected")
print("PASS macOS malformed audio/IDs and exact 60 second/bridge bounds")
''', encoding="utf-8")
    executable = temporary / "voice-check"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", str(cache),
                    "-framework", "AVFoundation", str(harness), "-o", str(executable)], check=True, timeout=60)
    subprocess.run([str(executable)], check=True, timeout=30)

info = plistlib.loads((ROOT / "native/Info.plist").read_bytes())
assert "NSMicrophoneUsageDescription" in info
assert "NSSpeechRecognitionUsageDescription" not in info
windows = (ROOT / "windows/src/StudioForm.cs").read_text(encoding="utf-8")
for action in ("startVoiceRecording", "stopVoiceRecording", "cancelVoiceRecording", "cancelVoiceTranscription",
               "voiceSettings", "saveVoiceSettings", "deleteVoiceKey", "revealVoiceKey", "transcribeVoice", "keymapCatalog", "keymapPlan"):
    assert '"' + action + '"' in source and '"' + action + '"' in windows, action
assert "cancelActiveVoice()" in source[source.index("private func requestWorkspaceExit"):source.index("private func failWorkspaceExit")]
assert "voiceCancellation?.Cancel()" in windows[windows.index("private async Task RequestWorkspaceExitAsync"):]
assert "!self.voiceBackendActions.contains(action)" in source
assert "suppressDiagnostics: VoiceBackendActions.Contains(action)" in windows
print("PASS both host action allowlists, isolated cancellation, audio/credential diagnostic suppression and mic-only permission metadata")
