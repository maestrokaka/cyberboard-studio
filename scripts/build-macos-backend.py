#!/usr/bin/env python3
"""Freeze the bridge/CLI into a relocatable macOS onedir, without user state."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "CyberboardBackend"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=ROOT / ".tools/macos-build/bin/python")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "build/macos-backend")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("Build macOS backend on macOS; PyInstaller is not an OS cross-compiler.")
    # Keep the venv launcher symlink; resolve() would bypass the private venv
    # and invoke its base interpreter without the installed builder packages.
    python = args.python.absolute()
    if not python.exists():
        raise SystemExit("Run scripts/setup-cli.py --env-dir .tools/macos-build --with-pyinstaller first.")
    dist = args.dist_dir.resolve()
    vendor = ROOT / "vendor/cyberboard-cli"
    tools = vendor / "cyberboard/_tools"
    work = ROOT / ".tools/macos-build-work"
    work.mkdir(parents=True, exist_ok=True)
    command = [str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
        "--name", NAME, "--target-arch", "arm64", "--distpath", str(dist), "--workpath", str(work / "work"), "--specpath", str(work),
        "--paths", str(vendor), "--paths", str(tools), "--paths", str(ROOT / "backend"),
        "--add-data", str(vendor / "cyberboard") + ":cyberboard",
        "--add-data", str(ROOT / "vendor/licenses") + ":licenses",
        "--copy-metadata", "cyberboard-cli", "--hidden-import", "serial.tools.list_ports_osx",
        "--hidden-import", "kimi_ai", "--hidden-import", "lighting_recipe", "--hidden-import", "ai_images"]
    for file in sorted(tools.glob("*.py")):
        if file.stem != "cb_keymap_tui":
            command += ["--hidden-import", file.stem]
    for module in ("serial", "PIL", "jsonschema", "jsonschema_specifications", "referencing", "rpds", "tzdata"):
        command += ["--collect-all", module]
    for package in ("pyserial", "Pillow", "jsonschema", "jsonschema-specifications", "attrs", "referencing", "rpds-py", "typing-extensions", "tzdata"):
        command += ["--copy-metadata", package]
    for module in ("textual", "mcp", "tkinter", "PIL.ImageQt", "PIL.ImageTk", "PyQt5", "PyQt6", "PySide2", "PySide6"):
        command += ["--exclude-module", module]
    command.append(str(ROOT / "backend/bridge.py"))
    # Explicit vendor path aids copy_metadata at build time; frozen output uses
    # its own bundle paths and does not rely on this environment or the venv.
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(vendor)
    environment["PYINSTALLER_CONFIG_DIR"] = str(ROOT / ".tools/pyinstaller-cache")
    log = work / "build.log"
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text(encoding="utf-8")[-12000:])
        raise SystemExit(result.returncode)
    bundle = dist / NAME
    executable = bundle / NAME
    if not executable.exists():
        raise SystemExit("Frozen backend executable missing.")
    notices = ["Cyberboard Studio macOS backend third-party notices", "",
        "cyberboard-cli 0.1.2: MIT; see _internal/cyberboard_cli-0.1.2.dist-info/licenses/LICENSE.",
        "Vendored CLI patches: AM01R6 identification, COM discovery, per-device locks, Windows data path and doctor diagnostics.",
        "PySerial: BSD-3-Clause; see _internal/licenses/pyserial-BSD-3-Clause.txt.",
        "Bundled pixel font: see _internal/cyberboard/_tools/fonts/README.md and BDF copyright.",
        "Python: PSF License Version 2; https://docs.python.org/3/license.html.",
        "PyInstaller bootloader: GPL-2.0-or-later with the PyInstaller exception; https://pyinstaller.org/en/stable/license.html.",
        "Other dependency licenses are preserved in _internal/*.dist-info/licenses/."]
    (bundle / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(notices) + "\n", encoding="utf-8")
    # Copy complete builder/interpreter notices alongside binary distribution.
    license_dir = bundle / "licenses"
    license_dir.mkdir(exist_ok=True)
    for package in ("PyInstaller",):
        directory = subprocess.check_output([str(python), "-c",
            f"import importlib.metadata; print(importlib.metadata.distribution({package!r})._path)"], text=True).strip()
        for file in Path(directory).rglob("*"):
            if file.is_file() and ("license" in file.name.lower() or "copying" in file.name.lower()):
                shutil.copy2(file, license_dir / file.name)
    prefix = subprocess.check_output([str(python), "-c", "import sys; print(sys.base_prefix)"], text=True).strip()
    for candidate in (Path(prefix) / "LICENSE.txt", Path(prefix) / "LICENSE", Path(prefix) / "lib/python3.12/LICENSE.txt", Path(prefix) / "share/doc/python3.12/LICENSE"):
        if candidate.exists():
            shutil.copy2(candidate, license_dir / "Python-LICENSE.txt")
            break
    if not (license_dir / "Python-LICENSE.txt").is_file():
        raise SystemExit("Python distribution license missing; cannot complete release bundle.")
    for directory in (bundle / "_internal").glob("*.dist-info"):
        destination = license_dir / directory.name
        for file in directory.rglob("*"):
            if file.is_file() and ("license" in file.name.lower() or "copying" in file.name.lower() or "notice" in file.name.lower()):
                target = destination / file.relative_to(directory)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
    shutil.copy2(ROOT / "vendor/licenses/pyserial-BSD-3-Clause.txt", license_dir / "pyserial-BSD-3-Clause.txt")
    # Read each actual Mach-O's declared minimum; SDK version is not minos.
    machos = []
    for file in bundle.rglob("*"):
        if not file.is_file() or file.is_symlink():
            continue
        with file.open("rb") as stream:
            magic = stream.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
            continue
        output = subprocess.check_output(["/usr/bin/otool", "-l", str(file)], text=True)
        minimums = re.findall(r"\bminos\s+(\d+(?:\.\d+){0,2})", output)
        minimums += re.findall(r"cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+(?:\.\d+){0,2})", output)
        if not minimums:
            raise SystemExit("No macOS minimum version load command in " + str(file))
        architecture = subprocess.check_output(["/usr/bin/lipo", "-archs", str(file)], text=True).strip()
        if "arm64" not in architecture.split():
            raise SystemExit("Non-arm64 binary collected: " + str(file))
        machos.append({"file": str(file.relative_to(bundle)), "architectures": architecture, "minimum_macos": minimums})
    maximum = max(tuple(int(n) for n in value.split(".")) + (0,) * (3 - len(value.split(".")))
                  for binary in machos for value in binary["minimum_macos"])
    if maximum > (13, 0, 0):
        raise SystemExit("Collected backend requires macOS " + ".".join(map(str, maximum)) + "; exceeds the macOS 13 release target.")
    # Build a deterministic offline bootstrap smoke check after relocating the
    # whole directory and removing access to the development Python environment.
    with tempfile.TemporaryDirectory(prefix="Cyberboard 后台 发布检查 ") as directory:
        temp = Path(directory)
        moved = temp / NAME
        shutil.copytree(bundle, moved, symlinks=True)
        env = os.environ.copy()
        env["CYBERBOARD_DATA_DIR"] = str(temp / "empty-cli-store")
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        checked = subprocess.run([str(moved / NAME), "--action", "bootstrap", "--state-dir", str(temp / "app state"),
            "--resource-dir", str(ROOT)], input="{}", text=True, capture_output=True, env=env, cwd=temp, timeout=30)
        if checked.returncode:
            raise SystemExit("Relocated backend failed: " + checked.stdout + checked.stderr)
        record = json.loads(checked.stdout.strip())
        value = record.get("result", {})
        if value.get("cliVersion") != "0.1.2" or value.get("config") is not None or value.get("history") != []:
            raise SystemExit("Unexpected offline bootstrap result: " + checked.stdout)
        if any(p.name in ("current.json", "history", "pyvenv.cfg") for p in bundle.rglob("*")):
            raise SystemExit("Private state or development venv was included in the release backend.")
    manifest = {"name": NAME, "target": "macos-" + platform.machine(), "python": subprocess.check_output([str(python), "--version"], text=True).strip(),
        "cli": "0.1.2 vendored", "relocated_offline_bootstrap": "passed", "private_device_state_bundled": False,
        "depends_on_system_python": False, "usb_accessed_during_build_or_test": False}
    manifest["mach_o_minimum_macos"] = ".".join(map(str, maximum))
    manifest["declared_app_minimum_macos"] = "13.0"
    manifest["mach_o_binaries"] = machos
    # Bind the frozen runtime to the reviewed source, so release checks catch
    # same-version bundles whose action names match but implementation is old.
    source_files = sorted((ROOT / "backend").glob("*.py")) + [
        ROOT / "vendor/cyberboard-cli/cyberboard/_tools/cb_device.py"
    ]
    manifest["source_hashes"] = {
        str(file.relative_to(ROOT)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in source_files
    }
    (bundle / "backend-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Relocated offline bootstrap passed; no USB or user device state.")
    print(executable)


if __name__ == "__main__":
    main()
