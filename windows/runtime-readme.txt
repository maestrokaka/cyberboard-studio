Windows private Python runtime
==============================

Build output: windows/runtime/python/
Copy this whole directory to the application's resources/python/ unchanged.
Build inputs are cached in .tools/windows-runtime/downloads/ (ignored by Git).
Tests and preparation scripts under windows/runtime/ are not
part of the released app. No device history, baseline, macOS venv or user
configuration is included.

Entry points
------------
GUI bridge: resources/python/python.exe -X utf8 resources/backend/bridge.py
            --state-dir <LOCALAPPDATA>/Cyberboard Studio
            --resource-dir <application resources path>
CLI:        resources/python/python.exe -X utf8 -m cyberboard.cli <arguments>

The host should use python.exe with redirected stdin/stdout/stderr and a
hidden console. Do not use pythonw.exe for the bridge: its standard streams
are not console streams. Use the absolute application-relative interpreter
path rather than the PATH or a user's installed Python.

python312._pth explicitly contains python312.zip, ., Lib/site-packages,
../backend and import site. It is relative to the private interpreter location,
enables isolated mode and ignores environment/registry Python paths. No
PYTHONPATH/PYTHONHOME setup or pip install on the user's computer is required.
Pass -X utf8 in the command; this avoids depending on PYTHONUTF8 being honored
by the isolated interpreter.

Set CYBERBOARD_DATA_DIR for child processes to the host's per-user CLI store
directory if host and standalone CLI state should be shared. Otherwise the
patched Windows CLI uses %LOCALAPPDATA%/cyberboard-cli. The bridge's own
--state-dir should also stay in LOCALAPPDATA, outside Program Files/resources.

Included versions
-----------------
Python 3.12.10 embed AMD64 (PSF license and its included third-party notices)
cyberboard-cli 0.1.2 (MIT), existing local AM01R6 identity patch retained
pyserial 3.5, Pillow 12.3.0, jsonschema 4.26.0, attrs 26.1.0,
jsonschema-specifications 2025.9.1, referencing 0.37.0,
rpds-py 2026.9.1, typing-extensions 4.16.0, tzdata 2026.5.

CLI optional LED and strict schema-validation dependencies are included. TUI
(textual) and MCP server dependencies are excluded because the desktop GUI
does not use these extra integrations. Those optional standalone CLI modes cannot run
without their extra dependencies.

Windows-specific compatibility
------------------------------
cb_device enumerates COM ports with pyserial list_ports.comports() and then
uses the existing CRC-valid identity query. R4 and R6 identities are retained;
dongles remain excluded. Device lock uses msvcrt's byte locking with an explicit
retry loop and stable non-truncated lock file. Unix behavior remains available
for offline tests. Store defaults to LOCALAPPDATA and doctor messages describe
serial ports on Windows.

Supported host target: Windows 10/11 x64; the Windows universal CRT is part of
supported OS versions. Python's VC runtime DLLs are included from the official
archive. This package was assembled on macOS: mocked discovery/lock tests,
source tests, official artifact checksums and x64 PE headers can be checked
here; launch, COM drivers and real USB write behavior need a Windows machine.

Rebuild / validation
--------------------
Only official wheel metadata is committed under windows/runtime/downloads/.
fetch-runtime.py re-downloads the exact official artifacts to the ignored
.tools/windows-runtime/downloads/ cache and verifies their pinned SHA-256.
prepare-runtime.py verifies Python's official release checksum and all wheels'
official SHA-256 values, unpacks privately and copies the committed reviewed
vendor/cyberboard-cli source. Its cross-platform patches are already applied;
the Windows assembler does not patch it again or reference a developer's venv.

From this App repository root, with Python >=3.11:
 python3 scripts/setup-cli.py
 python3 windows/runtime/fetch-runtime.py
 python3 windows/runtime/prepare-runtime.py
 .tools/cli/bin/python windows/runtime/tests/runtime-check.py
 On Windows the final test command uses .tools\cli\Scripts\python.exe.

On Windows, offline smoke checks from the final release folder:
 resources\python\python.exe -X utf8 -m cyberboard.cli --version
 resources\python\python.exe -X utf8 -m cyberboard.cli store --selftest
 resources\python\python.exe -X utf8 -c "from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Shanghai'))"

Licenses and provenance
-----------------------
The final private runtime includes LICENSE.txt, THIRD-PARTY-NOTICES.txt,
original wheel .dist-info licenses and runtime-manifest.json with versions,
download URLs, checksums and source hashes. Preserve these in the release.
The pyserial 3.5 wheel has copyright/SPDX source headers but no standalone
LICENSE file; licenses/pyserial-BSD-3-Clause.txt reproduces the declared
standard BSD-3-Clause terms with the source copyright holder and dates.

Primary documentation checked:
https://www.python.org/downloads/release/python-31210/
https://docs.python.org/3.12/using/windows.html#the-embeddable-package
https://docs.python.org/3.12/library/sys_path_init.html#pth-files
https://docs.python.org/3/library/msvcrt.html#msvcrt.locking
https://pyserial.readthedocs.io/en/latest/tools.html#serial.tools.list_ports.comports
https://pypi.org/project/tzdata/
https://pypi.org/project/jsonschema/
https://pypi.org/project/pillow/
https://github.com/GeneralD/cyberboard-cli
