#!/usr/bin/env python3
"""Assemble a private Windows Python from pinned, downloaded official artifacts.

This is a build-time tool: it does not install into a system interpreter, probe
serial ports, or copy device state. Run it with the project's existing Python.
"""
from __future__ import annotations

import email
import hashlib
import json
import shutil
import struct
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
PINNED_METADATA = HERE / "downloads"
DOWNLOADS = APP / ".tools/windows-runtime/downloads"
OUTPUT = HERE / "python"
VENDOR = APP / "vendor/cyberboard-cli"
PYTHON_ZIP = "python-3.12.10-embed-amd64.zip"
PYTHON_MD5 = "fe8ef205f2e9c3ba44d0cf9954e1abd3"
PYTHON_URL = "https://www.python.org/ftp/python/3.12.10/" + PYTHON_ZIP


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Unexpected upstream source while applying Windows patch")
    return text.replace(old, new, 1)


def checked_extract(archive, directory):
    """Wheel/archive paths are checked before extraction, including .data layout."""
    base = directory.resolve()
    for item in archive.infolist():
        name = item.filename
        if ".data/" in name:
            # These packages have no required scripts/data outside site-packages.
            parts = name.split("/")
            if len(parts) > 2 and parts[1] in ("purelib", "platlib"):
                name = "/".join(parts[2:])
            else:
                continue
        destination = (directory / name).resolve()
        if not destination.is_relative_to(base):
            raise RuntimeError(f"Unsafe archive member {name}")
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(item))


def main():
    python_archive = DOWNLOADS / PYTHON_ZIP
    if not python_archive.is_file():
        raise RuntimeError("Run windows/runtime/fetch-runtime.py to populate the pinned artifact cache first.")
    if hashlib.md5(python_archive.read_bytes()).hexdigest() != PYTHON_MD5:
        raise RuntimeError("Python archive differs from python.org release checksum")
    if sha(python_archive) != "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3":
        raise RuntimeError("Python archive differs from the pinned SHA-256")
    # Only our dedicated generated output is replaced; no user state is read.
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    with zipfile.ZipFile(python_archive) as archive:
        checked_extract(archive, OUTPUT)
    (OUTPUT / "python312._pth").write_text(
        "python312.zip\n.\nLib/site-packages\n../backend\nimport site\n", encoding="utf-8")
    site = OUTPUT / "Lib/site-packages"
    site.mkdir(parents=True)
    packages = []
    upstream_cli = None
    for wheel in sorted(DOWNLOADS.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            meta_name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            metadata = email.message_from_bytes(archive.read(meta_name))
            # The upstream wheel is retained as a reference; vendoring below
            # starts from the committed, reviewed cross-platform CLI source.
            if metadata["Name"] != "cyberboard-cli":
                checked_extract(archive, site)
        official = json.loads((PINNED_METADATA / (wheel.name + ".json")).read_text(encoding="utf-8"))
        entry = next(f for f in official["urls"] if f["filename"] == wheel.name)
        if entry["digests"]["sha256"] != sha(wheel):
            raise RuntimeError(f"Wheel differs from PyPI checksum: {wheel.name}")
        if metadata["Name"] == "cyberboard-cli":
            upstream_cli = {"file": wheel.name, "url": entry["url"], "sha256": sha(wheel)}
            continue
        packages.append({"name": metadata["Name"], "version": metadata["Version"],
            "license": metadata["License-Expression"] or metadata["License"],
            "requires": metadata.get_all("Requires-Dist", []), "file": wheel.name,
            "url": entry["url"], "sha256": sha(wheel)})
    for name in ("cyberboard", "cyberboard_cli-0.1.2.dist-info"):
        shutil.copytree(VENDOR / name, site / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    # Installation-specific bookkeeping must not claim the modified CLI still
    # has the original wheel's RECORD hashes or console scripts.
    dist = site / "cyberboard_cli-0.1.2.dist-info"
    for name in ("RECORD", "INSTALLER", "direct_url.json", "REQUESTED"):
        (dist / name).unlink(missing_ok=True)
    shutil.copytree(HERE / "licenses", OUTPUT / "licenses")
    modified = []
    for filename in ("cb_device.py", "cb_store.py", "cb_doctor.py"):
        output = site / "cyberboard/_tools" / filename
        original = VENDOR / "cyberboard/_tools" / filename
        modified.append({"file": str(output.relative_to(OUTPUT)),
            "vendored_sha256": sha(original), "runtime_sha256": sha(output)})
    cli_files = {str(p.relative_to(site)): sha(p) for p in sorted((site / "cyberboard").rglob("*")) if p.is_file()}
    pe = (OUTPUT / "python.exe").read_bytes()
    offset = struct.unpack_from("<I", pe, 0x3C)[0]
    if pe[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", pe, offset + 4)[0] != 0x8664:
        raise RuntimeError("Python executable is not Windows x64 PE")
    manifest = {"target": "win-x64", "python": {"version": "3.12.10", "file": PYTHON_ZIP,
        "url": PYTHON_URL, "sha256": sha(python_archive), "license": "PSF-2.0 and bundled third-party notices in LICENSE.txt"},
        "cli": {"name": "cyberboard-cli", "version": "0.1.2", "license": "MIT", "source": "https://github.com/GeneralD/cyberboard-cli",
        "local_patches": ["AM01R6 identity detection (verified vendored patch)", "Windows COM port discovery", "Windows msvcrt per-device lock", "LOCALAPPDATA store default", "portable doctor diagnostics"],
        "vendored_files": modified, "source_files_sha256": cli_files, "upstream_wheel": upstream_cli,
        "restored_schema": {"source": "https://raw.githubusercontent.com/GeneralD/cyberboard-cli/v0.1.2/schemas/cyberboard-config.schema.json",
        "sha256": sha(site / "cyberboard/schemas/cyberboard-config.schema.json")}},
        "packages": packages, "exclude_from_release": ["downloads", "tests", "prepare-runtime.py", "fetch-metadata.py", "fetch-runtime.py"],
        "startup": "resources/python/python.exe -X utf8 resources/backend/bridge.py",
        "path_file": "python312.zip;.;Lib/site-packages;../backend;import site",
        "optional_cli_dependencies_excluded": ["textual (TUI)", "mcp (MCP server)"],
        "device_state_bundled": False,
        "additional_license_notices": {"pyserial": "licenses/pyserial-BSD-3-Clause.txt; copyright and SPDX identifier from serial/__init__.py"}}
    (OUTPUT / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    notices = ["Cyberboard Studio Windows private runtime third-party notices", "",
        "Python 3.12.10: see LICENSE.txt alongside python.exe (PSF and Python bundled dependencies).",
        "cyberboard-cli 0.1.2: MIT; see Lib/site-packages/cyberboard_cli-0.1.2.dist-info/licenses/LICENSE.",
        "Modified for Windows COM discovery, state-store locking, Windows data path, and AM01R6 identification.",
        "Bundled pixel font: see cyberboard/_tools/fonts/README.md and tom-thumb.bdf COPYRIGHT.", ""]
    for package in packages:
        if package['name'] == "pyserial":
            notices.append("pyserial 3.5: BSD-3-Clause; see licenses/pyserial-BSD-3-Clause.txt and the wheel's source copyright/SPDX headers.")
        else:
            notices.append(f"{package['name']} {package['version']}: {package['license']}; original notices retained in its .dist-info directory.")
    notices += ["", "PyPI wheel contents and all included licenses are preserved; no pip, TUI or MCP runtime was added."]
    (OUTPUT / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(notices) + "\n", encoding="utf-8")
    print(f"Prepared {OUTPUT} with {len(packages)} pinned dependency wheels; Windows x64 PE checked.")


if __name__ == "__main__":
    main()
