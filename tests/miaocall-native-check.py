#!/usr/bin/env python3
"""Offline checks for the production shortcut and Spotify completion boundary.

No system permission, event tap, audio device, Spotify command, Agent, or user
state is accessed. Actual microphone and desktop execution require a live run.
"""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "native/MiaoCall.swift").read_text(encoding="utf-8")
key_gate = source[source.index("struct MiaoCallKeyGate"):source.index("private final class MiaoCallPanel")]
verification = source[source.index("    static func verifyProgress"):source.index("    private func execute")]
reader_source = (ROOT / "native/Studio.swift").read_text(encoding="utf-8")
reader = reader_source[reader_source.index("final class JSONLineReader"):reader_source.index("// A single asynchronous save barrier")]
code = r'''
func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
}
func rejects(_ input: String) -> Bool {
    do { _ = try MiaoCallTranscript.validated(input); return false } catch { return true }
}
check(rejects("") && rejects(" \n\t") && rejects(String(repeating: "中", count: 2001)), "Blank or long transcript accepted")
check((try? MiaoCallTranscript.validated("  播放晴天  ")) == "播放晴天", "Transcript whitespace normalization failed")
check((try? MiaoCallTranscript.validated(String(repeating: "中", count: 2000))) != nil, "Exact 2000 codepoint bound rejected")
check(rejects(String(repeating: "👨‍👩‍👧‍👦", count: 300)), "Grapheme clusters bypassed backend codepoint bound")
print("PASS blank/long transcript errors, trimming and backend-compatible 2000 codepoint limit")
let specific = MiaoCallResultContract.terminal(["ok": false, "status": "error", "message": "请先登录 Codex。"])
check(specific.state == "error" && specific.message == "请先登录 Codex。", "Final worker detail was ignored")
check(MiaoCallResultContract.message(["message": "未完成", "detail": "歌曲不在授权目录中。"], fallback: "fallback") == "歌曲不在授权目录中。", "State detail lost to generic message")
check(MiaoCallResultContract.terminal(["ok": true, "status": "completed"]).state == "error", "Completed without playback evidence accepted")
check(MiaoCallResultContract.message(["detail": String(repeating: "中", count: 1000)], fallback: "").count == 500, "Worker detail was unbounded")
let general = MiaoCallResultContract.terminal(["ok":true,"status":"completed","taskId":"task-"+String(repeating:"a",count:32),"text":"资料摘要已返回。"])
check(general.state=="completed","A non-music task with official result was rejected")
check(MiaoCallResultContract.terminal(["ok":true,"status":"completed","taskId":"task-"+String(repeating:"a",count:32)]).state=="error","Empty general completion was accepted")
print("PASS bounded worker details, explicit final failure and required completion evidence")
var enable = MiaoCallEnableGate()
let setupOne = enable.begin()!
check(enable.isPending && enable.begin() == nil, "Concurrent enable was accepted")
enable.cancel()
check(!enable.isPending && !enable.finish(setupOne), "Late cancelled enable recreated hook")
let setupTwo = enable.begin()!
check(!enable.finish(setupOne) && enable.isPending, "Old enable callback cleared a newer pending enable")
check(enable.finish(setupTwo) && !enable.isPending, "Current enable did not finish")
check(!enable.finish(setupTwo), "Enable callback completed twice")
print("PASS pending enable mutual exclusion, cancel/disable late result and newer operation ownership")
var gate = MiaoCallKeyGate()
check(gate.consume(code: 49, down: true, repeated: false, modified: false, busy: false) == nil, "Other keys intercepted")
check(gate.consume(code: 50, down: true, repeated: false, modified: true, busy: false) == nil, "Modifier chord intercepted")
check(gate.consume(code: 50, down: false, repeated: false, modified: false, busy: false) == nil, "Orphan keyup intercepted")
check(gate.consume(code: 50, down: true, repeated: true, modified: false, busy: false) == nil, "Repeated orphan began recording")
check(gate.consume(code: 50, down: true, repeated: false, modified: false, busy: true) == "consume", "Busy task shortcut leaked into typing")
check(gate.consume(code: 50, down: false, repeated: false, modified: false, busy: true) == "stop", "Busy shortcut release leaked")
check(gate.consume(code: 50, down: true, repeated: false, modified: false, busy: false) == "start", "Physical press did not start")
check(gate.consume(code: 50, down: true, repeated: true, modified: false, busy: true) == "consume", "Autorepeat leaked/started another recording")
check(gate.consume(code: 50, down: false, repeated: false, modified: true, busy: true) == "stop", "Modifier pressed during hold orphaned recording")
check(!gate.held, "Release retained hold")
_ = gate.consume(code: 50, down: true, repeated: false, modified: false, busy: false)
gate.reset()
check(!gate.held && gate.consume(code: 50, down: false, repeated: false, modified: false, busy: false) == nil, "Disable/cancel retained hold")
print("PASS physical key, modifiers, repeats, busy task, orphan release and reset")
let uri = "spotify:track:5pIcwtJYNJx93l420oR2Vm"
check(SpotifyCheck.validURI(uri), "Official track URI rejected")
for value in ["spotify:track:short", "spotify:track:5pIcwtJYNJx93l420oR2Vm\"", "spotify:track:5pIcwtJYNJx93l420oR2Vm\n", "https://open.spotify.com/track/5pIcwtJYNJx93l420oR2Vm", "spotify:episode:5pIcwtJYNJx93l420oR2Vm", "$(touch /tmp/a)"] {
    check(!SpotifyCheck.validURI(value), "Invalid URI allowed into official script")
}
let before: [String: Any] = ["uri": uri, "playing": true, "positionMs": 1000]
let after: [String: Any] = ["uri": uri, "playing": true, "positionMs": 1400]
check(SpotifyCheck.verifyProgress(first: before, latest: after, expectedURI: uri), "Actual matching playback progression rejected")
check(SpotifyCheck.verifyProgress(first: before, latest: after, expectedURI: nil), "Readback observation failed")
for changed: [String: Any] in [["uri": uri, "playing": false, "positionMs": 1400], ["uri": uri, "playing": true, "positionMs": 1000], ["uri": uri, "playing": true, "positionMs": 1200], ["uri": uri, "playing": true, "positionMs": 500], ["uri": "spotify:track:AAAAAAAAAAAAAAAAAAAAAA", "playing": true, "positionMs": 1400], ["uri": uri, "positionMs": 1400]] {
    check(!SpotifyCheck.verifyProgress(first: before, latest: changed, expectedURI: uri), "Paused, stale, wrong or incomplete state claimed success")
}
check(!SpotifyCheck.verifyProgress(first: before, latest: after, expectedURI: "spotify:track:AAAAAAAAAAAAAAAAAAAAAA"), "Wrong requested track claimed success")
print("PASS strict track URI and matching, playing, advancing completion boundary")
var events = 0
let bounded = JSONLineReader(maximumBytes: 40) { _ in events += 1 }
bounded.append(Data("{\"event\":\"state\"}\n".utf8))
check(events == 1, "Bounded stream dropped valid event")
bounded.append(Data(repeating: 65, count: 41))
bounded.append(Data("{\"event\":\"state\"}\n".utf8)); bounded.finish()
check(events == 1 && bounded.parseError != nil && bounded.finalReply == nil, "Oversized stream was not bounded")
print("PASS bounded process output and no post-limit event acceptance")
'''
build = ROOT / "build/miaocall-native-check"
build.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="offline-", dir=build) as directory:
    directory = Path(directory)
    main = directory / "main.swift"
    main.write_text("import Foundation\n" + key_gate + "\nstruct SpotifyCheck {\n" + verification + "\n}\ntypealias MiaoCallSpotify = SpotifyCheck\n" + reader + code, encoding="utf-8")
    binary = directory / "check"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", str(ROOT / "build/swift-module-cache"), str(main), "-o", str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=15)

info = plistlib.loads((ROOT / "native/Info.plist").read_bytes())
assert info.get("NSMicrophoneUsageDescription") and info.get("NSAppleEventsUsageDescription")
assert "CGEvent.tapCreate" in source and "private(set) var enabled = false" in source
assert "source: source" in source and "play track" in source
assert "isMovableByWindowBackground = true" in source
assert "panel.delegate = self" in source
assert "positionDefaultsKey" in source and "restoreOrPlacePosition()" in source
assert "constrainAndPersistPosition()" in source
assert "private final class MiaoCallDraggablePetView: NSImageView" in source
assert "image.onDrag = { [weak self] delta in self?.movePanel(by: delta) }" in source
assert 'image.setAccessibilityLabel("拖动喵娘可移动桌面浮层")' in source
assert source.index("visibleFrame.contains(NSEvent.mouseLocation)") < source.index("visibleFrame.contains(center)")
assert "addCursorRect(bounds, cursor: .openHand)" in source
for forbidden in ("osascript", "CGEventPost", "AXUIElementPerformAction", "NSAppleScript(source: transcript", "ProcessInfo.processInfo.environment[\"SPOTIFY_TOKEN\"]"):
    assert forbidden not in source, forbidden
print("PASS explicit permission descriptions, off-by-default hook, narrow official Spotify adapter")

# Exercise the exact build guard, including the modifier substring that once
# prevented this Beta from packaging. No credential API is loaded or called.
build_script = (ROOT / "native/build.sh").read_text(encoding="utf-8")
guard_start = build_script.index("import pathlib, re, sys\n")
guard_code = build_script[guard_start:build_script.index("\nPY", guard_start)]
with tempfile.TemporaryDirectory(prefix="guard-", dir=build) as directory:
    sample = Path(directory) / "sample.swift"
    for body, rejected in [("event.flags.intersection([.maskSecondaryFn])", False),
                           ("let item = kSecAttrAccount", True),
                           ("let result = SecItemCopyMatching()", True)]:
        sample.write_text(body, encoding="utf-8")
        result = subprocess.run([sys.executable, "-", str(sample)], input=guard_code,
                                text=True, capture_output=True, timeout=10)
        assert (result.returncode != 0) == rejected, body
print("PASS production build guard accepts Fn modifier and rejects credential identifiers")
