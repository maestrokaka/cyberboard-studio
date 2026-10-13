#!/usr/bin/env python3
"""Verify real Swift pipe progress is delivered before child completion, offline."""
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
source = (root / "native/Studio.swift").read_text(encoding="utf-8")
reader = source.split("final class JSONLineReader {", 1)[1].split("final class StudioApp:", 1)[0]
reader = "import Foundation\nfinal class JSONLineReader {" + reader
checks = r'''
let child = Process()
child.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
child.arguments = ["-u", "-c", """
import json,sys,time
progress=json.dumps({'event':'progress','stage':'ai_request','label':'灯效编排'},ensure_ascii=False).encode('utf-8')+bytes([10])
sys.stdout.buffer.write(progress[:3]); sys.stdout.buffer.flush()
time.sleep(.03)
sys.stdout.buffer.write(progress[3:]); sys.stdout.buffer.flush()
time.sleep(2)
sys.stdout.write(json.dumps({'result':{'success':True}},ensure_ascii=False)); sys.stdout.flush()
"""]
let pipe = Pipe()
child.standardOutput = pipe
let started = Date()
var firstEventElapsed: TimeInterval?
var eventCount = 0
var invalidEvent = false
let lines = JSONLineReader { record in
    eventCount += 1
    if firstEventElapsed == nil { firstEventElapsed = Date().timeIntervalSince(started) }
    if record["stage"] as? String != "ai_request" || record["label"] as? String != "灯效编排" { invalidEvent = true }
}
try child.run()
lines.read(from: pipe.fileHandleForReading)
child.waitUntilExit()
lines.finish()
guard let elapsed = firstEventElapsed, elapsed < 1.0,
      eventCount == 1, !invalidEvent, child.terminationStatus == 0,
      lines.parseError == nil,
      (lines.finalReply?["result"] as? [String: Any])?["success"] as? Bool == true else {
    fputs("FAIL progress was buffered until completion or records were damaged: \(firstEventElapsed ?? -1)\n", stderr)
    exit(1)
}
print("PASS native progress arrived in \(String(format: \"%.3f\", elapsed)) s before the 2 s child completion; fragmented Unicode and final unterminated record preserved.")
'''
checks = checks.replace('String(format: \\"%.3f\\", elapsed)', 'String(format: "%.3f", elapsed)')
with tempfile.TemporaryDirectory(prefix="cyberboard-native-stream-") as directory:
    temporary = pathlib.Path(directory)
    swift = temporary / "main.swift"
    swift.write_text(reader + checks, encoding="utf-8")
    binary = temporary / "stream-check"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", str(root / "build/swift-module-cache"),
                    str(swift), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
