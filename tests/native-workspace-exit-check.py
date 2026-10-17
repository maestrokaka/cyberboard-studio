#!/usr/bin/env python3
"""Exercise the actual host save-barrier scripts and macOS exit state offline.

No GUI, user workspace, API credential, or USB device is accessed. Windows gate
state is also exercised by windows/tests/host-bridge, on a portable .NET runtime.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
swift = (ROOT / "native/Studio.swift").read_text(encoding="utf-8")
windows = (ROOT / "windows/src/StudioForm.cs").read_text(encoding="utf-8")
TOKEN = "exit-test-0001"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run(command):
    subprocess.run(command, check=True, cwd=ROOT, timeout=60)


def extract_script(source, pattern, token_marker):
    match = re.search(pattern, source, re.S)
    check(match is not None, "Host exit script missing")
    return match.group(1).replace(token_marker, TOKEN)


scripts = {
    "macOS": extract_script(swift, r'let script = """\n(.*?)\n        """', r"\(token)"),
    "Windows": extract_script(windows, r'var script = \$\$\$"""\n(.*?)\n            """;', "{{{token}}}"),
}
cache = ROOT / "build/swift-module-cache"
cache.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="native-exit-", dir=ROOT / "build") as directory:
    temporary = Path(directory)
    gate = swift[swift.index("enum WorkspaceExitIntent"):swift.index("final class StudioApp:")]
    harness = temporary / "main.swift"
    harness.write_text("import Foundation\n" + gate + r'''
func check(_ condition: Bool, _ message: String) {
    if !condition { fatalError(message) }
}
var gate = WorkspaceExitGate()
check(!gate.isPending, "Exit gate starts pending")
let first = gate.begin(.closeWindow)!
check(gate.isPending && gate.intent == .closeWindow, "Close barrier not owned")
check(gate.begin(.terminate) == nil, "Double close started another save")
check(gate.finish("wrong") == nil && gate.isPending, "Unrelated reply approved close")
check(gate.finish(first) == .closeWindow && !gate.isPending, "Saved close did not release barrier")
check(gate.finish(first) == nil, "Duplicate ready reply approved a second close")
let timedOut = gate.begin(.terminate)!
check(gate.finish(timedOut) == .terminate, "Failure did not release barrier")
let retry = gate.begin(.reload)!
check(retry != timedOut, "Retry reused stale token")
check(gate.finish(timedOut) == nil && gate.isPending, "Delayed success closed a retry")
check(gate.finish(retry) == .reload, "Retry lost its intent")
print("PASS macOS exit state: save ownership, reentry, failure/retry and stale/duplicate replies")
''', encoding="utf-8")
    executable = temporary / "exit-gate"
    run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-module-cache-path", str(cache),
         str(harness), "-o", str(executable)])
    run([str(executable)])
    node = shutil.which("node")
    check(node is not None, "Node is required for the host Promise protocol test")
    import json
    js = temporary / "exit-protocol.cjs"
    js.write_text("const scripts = " + json.dumps(scripts, ensure_ascii=False) + ";\n" + r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  for (const [platform, script] of Object.entries(scripts)) {
    const replies = [];
    let commit, fail;
    const saved = new Promise((resolve, reject) => { commit=resolve; fail=reject; });
    const window = {
      StudioApp: {flushWorkspace: () => saved},
      StudioNative: {postMessage: value => replies.push(value)},
      webkit: {messageHandlers: {studio: {postMessage: value => replies.push(value)}}}
    };
    assert.equal(vm.runInNewContext(script, {window}), true, platform+' blocked its script callback');
    await tick();
    assert.equal(replies.length, 0, platform+' approved exit before durable commit');
    commit(); await tick();
    assert.equal(replies.length, 1);
    assert.equal(replies[0].action, 'closeWorkspaceReady');
    assert.equal(replies[0].id, 'exit-test-0001');
    assert.equal(replies[0].payload.token, replies[0].id);
    replies.length=0;
    window.StudioApp.flushWorkspace = () => Promise.reject(new Error('private diagnostic'));
    vm.runInNewContext(script, {window}); await tick();
    assert.equal(replies[0].action, 'closeWorkspaceFailed');
    assert.equal(JSON.stringify(replies).includes('private diagnostic'), false);
    replies.length=0;
    delete window.StudioApp;
    vm.runInNewContext(script, {window}); await tick();
    assert.equal(replies[0].action, 'closeWorkspaceFailed');
    console.log('PASS '+platform+' actual exit script: pending commit, failure and unavailable frontend');
  }
})().catch(error => { console.error(error); process.exitCode=1; });
''', encoding="utf-8")
    run([node, str(js)])

for name, source in (("macOS", swift), ("Windows", windows)):
    check("closeWorkspaceReady" in source and "closeWorkspaceFailed" in source, name + " lacks completion handlers")
    check(".now() + 20" in source or "TimeSpan.FromSeconds(20)" in source, name + " lacks a bounded exit wait")
    check("workspaceExit.isPending" in source or "workspaceExit.IsPending" in source, name + " allows navigation during saving")
check("BeginInvoke(Close)" in windows and "PostToUi(() =>" in windows[windows.index("private void FailWorkspaceExit"):],
      "Windows close/dialog may reenter a synchronous WebView callback")
for path in [ROOT / "native/Studio.swift", *sorted((ROOT / "windows/src").glob("*.cs"))]:
    source = path.read_text(encoding="utf-8")
    for token in ("SecItem", "SecKeychain", "kSec", "Keychain", "import Security", "DPAPI", "ProtectedData",
                  "CryptProtectData", "CryptUnprotectData", "CredRead", "CredWrite", "VaultEnumerate"):
        check(token not in source, str(path.relative_to(ROOT)) + " reintroduced " + token)
print("PASS bounded asynchronous host exit wiring and all native credential-interface guards")
