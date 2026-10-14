#!/usr/bin/env python3
"""Verify a signed macOS release and its relocated, offline frozen backend.

This never launches the UI, detects devices, or performs USB operations. Backend
calls are limited to bootstrap and saveWorkspace, using temporary CLI/App stores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOGO = Path("assets/branding/product-icon/cyberboard-studio-photo-contour-v6-paw-180.png")
ALLOWED_ACTIONS = frozenset({"bootstrap", "saveWorkspace"})


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=45, **kwargs)
    require(result.returncode == 0,
            f"Command failed ({result.returncode}): {command[0]}\n{result.stderr.strip()}\n{result.stdout[:1000]}")
    return result


def signature(app):
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])


def preview_data(web):
    source = (web / "data.js").read_text(encoding="utf-8")
    prefix = "window.STUDIO_DATA="
    require(source.startswith(prefix) and source.rstrip().endswith(";"), "Unexpected preview-data format")
    data = json.loads(source[len(prefix):].rstrip().removesuffix(";"))
    require(data.get("baseConfig") is None, "Preview data includes a personal device baseline")
    require(data.get("snapshot") == {"productId": None, "firmware": None, "connected": False},
            "Preview data includes personal device metadata")
    keys = data.get("keyLayout", [])
    require(len(keys) == 81 and all(len(key.get("bindings", [])) == 1 for key in keys),
            "Preview layout must contain 81 physical keys and only factory base-layer labels")
    layout = json.loads((web / "assets/keymap-layout.json").read_text(encoding="utf-8"))
    require(layout.get("keys") == keys, "Standalone key layout differs from sanitized preview data")
    return data


def official_artwork(resources):
    source = ROOT / "web" / LOGO
    packaged = resources / "web" / LOGO
    master = ROOT / "branding/product-icon/cyberboard-studio-photo-contour-v6-paw-180.png"
    require(sha256(source) == sha256(packaged), "Packaged formal Logo differs from approved source PNG")
    icon = resources / "AppIcon.icns"
    require(icon.is_file() and icon.read_bytes()[:4] == b"icns", "macOS AppIcon is missing or invalid")
    try:
        from PIL import Image
    except ImportError:
        print("PASS approved Logo PNG is byte-exact (Pillow absent; source asset hash verified)")
        return
    with Image.open(master) as reference, Image.open(source) as approved, Image.open(packaged) as actual:
        require(reference.size == approved.size == actual.size, "Logo dimensions changed")
        require(reference.convert("RGB").tobytes() == actual.convert("RGB").tobytes(),
                "Logo RGB differs from the approved master")
        require(approved.mode == actual.mode == "RGBA", "Approved source and packaged Logo must preserve alpha")
        require(approved.getchannel("A").tobytes() == actual.getchannel("A").tobytes(), "Source Logo alpha changed")
        require(actual.getchannel("A").getextrema() == (0, 255), "Logo transparency is missing")
    print("PASS approved master RGB, source alpha and formal Logo hash")


def bundle_structure(app):
    contents = app / "Contents"
    resources = contents / "Resources"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    require(info.get("CFBundleShortVersionString") == "0.3.0", "App version differs from this release")
    require(info.get("LSMinimumSystemVersion") == "13.0", "App deployment minimum changed")
    require("CyberboardDevelopmentPythonPath" not in info, "Release App records a development Python path")
    native = contents / "MacOS" / info["CFBundleExecutable"]
    require(run(["/usr/bin/lipo", "-archs", str(native)]).stdout.strip() == "arm64", "Native App is not arm64")
    backend = resources / "backend/CyberboardBackend"
    binary = backend / "CyberboardBackend"
    require(binary.is_file() and os.access(binary, os.X_OK), "Frozen backend executable is missing")
    require(run(["/usr/bin/lipo", "-archs", str(binary)]).stdout.strip() == "arm64", "Frozen backend is not arm64")
    require((backend / "_internal/base_library.zip").is_file(), "Frozen Python standard library is missing")
    require((backend / "_internal/libpython3.12.dylib").is_file(), "Frozen Python shared library is missing")
    require(any((backend / "_internal").rglob("*.so")), "Frozen native dependency modules are missing")
    required_licenses = [backend / "licenses/Python-LICENSE.txt", backend / "licenses/COPYING.txt",
                        backend / "THIRD-PARTY-NOTICES.txt"]
    require(all(path.is_file() and path.stat().st_size for path in required_licenses), "Runtime license notices are missing")
    require(any((backend / "licenses").glob("cyberboard_cli-*.dist-info/licenses/LICENSE")), "CLI license is missing")
    manifest = json.loads((backend / "backend-build-manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("target") == "macos-arm64" and manifest.get("depends_on_system_python") is False,
            "Frozen backend manifest does not describe a portable arm64 runtime")
    require(manifest.get("private_device_state_bundled") is False, "Frozen backend includes private device state")
    expected_sources = [*sorted((ROOT / "backend").glob("*.py")),
                        ROOT / "vendor/cyberboard-cli/cyberboard/_tools/cb_device.py"]
    expected_hashes = {path.relative_to(ROOT).as_posix(): sha256(path) for path in expected_sources}
    require(manifest.get("source_hashes") == expected_hashes,
            "Frozen backend source hashes differ from current Python modules or patched device discovery")
    require(not (resources / "backend/bridge.py").exists(), "Source/development backend is included in the release")
    for removed in ("assets/desk.jpg", "assets/photos/r4-cloud-perspective.jpg", "assets/photos/r6-launch-front.png"):
        require(not (resources / "web" / removed).exists(), "Excluded-angle photo remains in the package: " + removed)
    for name in ("index.html", "app.js", "studio-model.js", "ai-client.js", "library-client.js", "preview-selector.js", "preview-engine.js", "polish.css", "dialogs.js", "assets/builtin-default-pages.json", "assets/support/wechat-pay.jpg", "assets/photos/r4-fluo-front.jpg", "assets/photos/r4-bebop-front.jpg"):
        require(sha256(resources / "web" / name) == sha256(ROOT / "web" / name),
                "Packaged web source is missing or stale: " + name)
    # --help exits before Bridge/CLI initialization. A fresh web tree alone must
    # not conceal a stale frozen backend lacking the configuration fixes.
    help_text = run([str(binary), "--help"]).stdout
    action_list = re.search(r"--action\s+\{([^}]+)\}", help_text)
    require(action_list is not None, "Frozen backend does not advertise its action contract")
    advertised = set(action_list.group(1).split(","))
    configuration_actions = {"readConfiguration", "builtInPlan", "initializePlan", "plan", "execute"}
    require(configuration_actions <= advertised, "Frozen backend lacks the configuration/default-mode fixes")
    native_source = (ROOT / "native/Studio.swift").read_text(encoding="utf-8")
    transport = re.search(r"backendActions:\s*Set<String>\s*=\s*\[(.*?)\]", native_source, re.S)
    require(transport and configuration_actions <= set(re.findall(r'"([^"\n]+)"', transport.group(1))),
            "macOS native bridge cannot forward every configuration action")
    defaults = json.loads((resources / "web/assets/builtin-default-pages.json").read_text(encoding="utf-8"))
    require([page["page_index"] for page in defaults["pages"]] == list(range(5)) and
            [bool(page["valid"]) for page in defaults["pages"]] == [True, True, True, False, False],
            "Bundled standard modes must enable battery, mosaic and clock")
    require(any((backend / "_internal").rglob("_imagingcms*.so")), "Color conversion native module is missing")
    forbidden_names = {"current.json", "meta.json", "workspace.json", "ai-settings.json", "pyvenv.cfg", ".operation.lock"}
    forbidden_directories = {".venv", "venv", "history", "devices", "credentials", "test-fixtures"}
    for path in app.rglob("*"):
        require(path.name.lower() not in forbidden_names, "Private/development file bundled: " + str(path.relative_to(app)))
        require(not (path.is_dir() and path.name.lower() in forbidden_directories),
                "Private/development directory bundled: " + str(path.relative_to(app)))
        if path.is_symlink():
            require(path.exists() and path.resolve().is_relative_to(app.resolve()),
                    "Broken or external runtime symlink: " + str(path.relative_to(app)))
    preview_data(ROOT / "web")
    packaged = preview_data(resources / "web")
    require(packaged == preview_data(ROOT / "web"), "Packaged preview differs from sanitized source data")
    official_artwork(resources)
    signature(app)
    print("PASS arm64 binaries, frozen runtime/licenses, release privacy and strict signature")
    return resources


def call_backend(binary, resources, state, cli_store, working_directory, action, payload):
    require(action in ALLOWED_ACTIONS, "Package checks may only call offline backend actions")
    env = os.environ.copy()
    original_home = env.get("HOME")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("CYBERBOARD_CLI_PYTHON", None)
    env["CYBERBOARD_DATA_DIR"] = str(cli_store)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    require(env.get("HOME") == original_home, "The test must never replace HOME")
    result = run([str(binary), "--action", action, "--state-dir", str(state), "--resource-dir", str(resources)],
                 input=json.dumps(payload, ensure_ascii=False), cwd=working_directory, env=env)
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    require(records and all(isinstance(record, dict) for record in records), "Backend returned invalid JSON-lines")
    replies = [record for record in records if "result" in record or "error" in record]
    require(len(replies) == 1 and "error" not in replies[0], "Backend request failed: " + str(replies))
    return replies[0]["result"]


def relocated_offline_checks(app):
    with tempfile.TemporaryDirectory(prefix="cyberboard-macos-release-") as directory:
        temporary = Path(directory).resolve()
        moved = temporary / "中文 目录" / "Cyberboard Studio.app"
        moved.parent.mkdir()
        shutil.copytree(app, moved, symlinks=True)
        signature(moved)
        source_links = {path.relative_to(app).as_posix(): os.readlink(path) for path in app.rglob("*") if path.is_symlink()}
        moved_links = {path.relative_to(moved).as_posix(): os.readlink(path) for path in moved.rglob("*") if path.is_symlink()}
        require(source_links == moved_links, "Relocation changed frozen-runtime symlinks")
        resources = moved / "Contents/Resources"
        binary = resources / "backend/CyberboardBackend/CyberboardBackend"
        state = temporary / "临时 工作台状态"
        cli_store = temporary / "临时 CLI 空存储"
        cli_store.mkdir()
        bootstrap = call_backend(binary, resources, state, cli_store, temporary, "bootstrap", {})
        require(bootstrap.get("cliVersion") == "0.1.2", "Relocated backend cannot load the bundled CLI")
        require(bootstrap.get("history") == [] and bootstrap.get("config") is None and bootstrap.get("workspace") is None,
                "Fresh relocated backend loaded nonempty device/workspace state")
        device = bootstrap.get("device", {})
        require(device.get("connected") is False and all(device.get(key) is None for key in ("productId", "firmware", "port", "lastSeen")),
                "Offline bootstrap reports a device connection or cached private identity")
        print("PASS relocated signed App: empty-store bootstrap, bundled CLI 0.1.2, connected=false")

        payload = {"designs": [], "pending": [], "selectedId": None, "targetSlot": 2,
                   "brief": "搬移后的离线工作台 保存检查", "palette": "original", "brightness": 63,
                   "speedMs": 40, "exportFormat": "design"}
        saved = call_backend(binary, resources, state, cli_store, temporary, "saveWorkspace", payload)
        require(saved.get("saved") is True and saved.get("designCount") == 0 and saved.get("pendingCount") == 0,
                "Offline saveWorkspace failed")
        workspace_file = state / "workspace.json"
        require(workspace_file.is_file(), "Workspace did not persist in the explicit temporary state directory")
        workspace = json.loads(workspace_file.read_text(encoding="utf-8"))
        require(all(workspace.get(key) == value for key, value in payload.items()), "Persisted workspace payload changed")
        require(workspace.get("version") == 1 and isinstance(workspace.get("savedAt"), str), "Workspace metadata is missing")
        restored = call_backend(binary, resources, state, cli_store, temporary, "bootstrap", {})
        require(restored.get("workspace") == {key: value for key, value in workspace.items() if key != "version"},
                "Relocated bootstrap did not restore the persisted workspace")
        require(restored.get("config") is None and restored.get("history") == [] and restored["device"]["connected"] is False,
                "Local workspace save changed device state")
        require(list(cli_store.iterdir()) == [], "Offline tests unexpectedly created CLI device records")
        signature(moved)
        print("PASS relocated offline saveWorkspace and bootstrap restore; no CLI device records")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=ROOT / "build/Cyberboard Studio.app")
    args = parser.parse_args()
    app = args.app.expanduser().resolve()
    require(app.is_dir(), "Build the macOS .app before running package checks")
    require(os.uname().sysname == "Darwin", "macOS package checks require a Mac")
    bundle_structure(app)
    relocated_offline_checks(app)
    print("macOS package checks passed. Only bootstrap/saveWorkspace ran; UI and USB were not accessed.")


if __name__ == "__main__":
    main()
