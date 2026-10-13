#!/usr/bin/env python3
"""Portable runtime checks; mocked Windows paths only, never real serial I/O."""
from __future__ import annotations

import errno
import base64
import csv
import hashlib
import importlib
import json
import os
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "python"
TOOLS = RUNTIME / "Lib/site-packages/cyberboard/_tools"
sys.path.insert(0, str(TOOLS))
device = importlib.import_module("cb_device")
store = importlib.import_module("cb_store")
protocol = importlib.import_module("cb_protocol")
from serial.tools.list_ports_common import ListPortInfo


class RuntimeCheck(unittest.TestCase):
    def test_windows_enumerates_com_handles_without_posix_glob(self):
        ports = [ListPortInfo("COM12"), ListPortInfo("COM3")]
        with mock.patch.object(device.sys, "platform", "win32"), \
                mock.patch.object(device.list_ports, "comports", return_value=ports), \
                mock.patch.object(device.glob, "glob", side_effect=AssertionError("POSIX glob called")):
            self.assertEqual(device.candidate_ports(), ["COM3", "COM12"])

    def test_mac_discovery_preserved(self):
        with mock.patch.object(device.sys, "platform", "darwin"), \
                mock.patch.object(device.glob, "glob", return_value=["/dev/cu.usbmodem2", "/dev/cu.usbmodem1"]):
            self.assertEqual(device.candidate_ports(), ["/dev/cu.usbmodem1", "/dev/cu.usbmodem2"])

    def test_r4_and_r6_require_valid_identity_not_merely_a_port_name(self):
        for identity, accepted in [("CB04", True), ("AM01R6", True), ("AM01R6_DONGLE", False), ("Other", False)]:
            text = identity.encode("ascii")
            reply = protocol.build_frame(1, 1, bytes([len(text)]) + text)
            serial = mock.Mock()
            serial.read.return_value = reply
            with mock.patch.object(device.serial, "Serial", return_value=serial), \
                    mock.patch.object(device.time, "sleep"):
                found = device.probe("COM3")
            self.assertEqual(found.is_cyberboard, accepted)
            serial.close.assert_called_once()
        serial = mock.Mock()
        serial.read.return_value = bytes(64)
        with mock.patch.object(device.serial, "Serial", return_value=serial), \
                mock.patch.object(device.time, "sleep"):
            self.assertIsNone(device.probe("COM3"))

    def test_windows_store_default_and_overrides(self):
        with mock.patch.object(store.sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"}, clear=True):
            self.assertEqual(store.store_root(), Path("C:/Users/Test/AppData/Local/cyberboard-cli"))
            os.environ["XDG_DATA_HOME"] = "/test/xdg"
            self.assertEqual(store.store_root(), Path("/test/xdg/cyberboard-cli"))
            os.environ["CYBERBOARD_DATA_DIR"] = "/test/explicit"
            self.assertEqual(store.store_root(), Path("/test/explicit"))

    def test_windows_lock_retries_and_unlocks_same_byte_even_on_error(self):
        calls = []
        attempts = 0
        def locking(fd, mode, length):
            nonlocal attempts
            calls.append((mode, length, os.lseek(fd, 0, os.SEEK_CUR)))
            if mode == 2:
                attempts += 1
                if attempts == 1:
                    raise OSError(errno.EACCES, "lock already held")
        fake = types.SimpleNamespace(locking=locking, LK_NBLCK=2, LK_UNLCK=0)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"CYBERBOARD_DATA_DIR": directory}), \
                mock.patch.object(store.sys, "platform", "win32"), \
                mock.patch.dict(sys.modules, {"msvcrt": fake}), \
                mock.patch.object(store.time, "sleep") as sleep:
            with self.assertRaisesRegex(ValueError, "body failure"):
                with store.device_lock("AM01R6"):
                    raise ValueError("body failure")
            self.assertEqual(calls, [(2, 1, 0), (2, 1, 0), (0, 1, 0)])
            sleep.assert_called_once_with(0.1)
            path = Path(directory) / "devices/AM01R6/.lock"
            self.assertEqual(path.read_bytes(), b"\0")
            calls.clear()
            with store.device_lock("AM01R6"):
                pass
            self.assertEqual(path.read_bytes(), b"\0", "locking another time must not truncate the file")
            self.assertEqual(calls, [(2, 1, 0), (0, 1, 0)])

    def test_windows_lock_propagates_unexpected_errors(self):
        fake = types.SimpleNamespace(locking=mock.Mock(side_effect=OSError(errno.EIO, "disk error")), LK_NBLCK=2, LK_UNLCK=0)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"CYBERBOARD_DATA_DIR": directory}), \
                mock.patch.object(store.sys, "platform", "win32"), \
                mock.patch.dict(sys.modules, {"msvcrt": fake}):
            with self.assertRaises(OSError):
                with store.device_lock("CB04"):
                    self.fail("body entered despite lock failure")

    def test_store_roundtrip_in_temporary_directory(self):
        self.assertEqual(store._selftest(), 0)

    def test_private_path_file_no_absolute_machine_paths(self):
        self.assertEqual((RUNTIME / "python312._pth").read_text().splitlines(),
            ["python312.zip", ".", "Lib/site-packages", "../backend", "import site"])

    def test_native_executables_are_windows_x64_not_mac(self):
        binaries = [*RUNTIME.glob("*.exe"), *RUNTIME.rglob("*.dll"), *RUNTIME.rglob("*.pyd")]
        self.assertGreater(len(binaries), 10)
        for binary in binaries:
            contents = binary.read_bytes()
            self.assertEqual(contents[:2], b"MZ", binary)
            offset = struct.unpack_from("<I", contents, 0x3C)[0]
            self.assertEqual(contents[offset:offset + 4], b"PE\0\0", binary)
            self.assertEqual(struct.unpack_from("<H", contents, offset + 4)[0], 0x8664, binary)

    def test_no_private_user_baseline_history_or_mac_venv(self):
        names = {p.name for p in RUNTIME.rglob("*")}
        self.assertFalse(names & {"current.json", "history", "pyvenv.cfg", ".DS_Store"})
        self.assertEqual(list(RUNTIME.rglob("*.so")), [])
        self.assertEqual(list(RUNTIME.rglob("*.dylib")), [])

    def test_cli_source_manifest_and_licenses_present(self):
        manifest = json.loads((RUNTIME / "runtime-manifest.json").read_text())
        self.assertFalse(manifest["device_state_bundled"])
        self.assertEqual(manifest["target"], "win-x64")
        for name, sha in manifest["cli"]["source_files_sha256"].items():
            contents = (RUNTIME / "Lib/site-packages" / name).read_bytes()
            self.assertEqual(hashlib.sha256(contents).hexdigest(), sha)
        self.assertTrue((RUNTIME / "LICENSE.txt").is_file())
        self.assertTrue((RUNTIME / "Lib/site-packages/cyberboard_cli-0.1.2.dist-info/licenses/LICENSE").is_file())
        self.assertTrue((RUNTIME / "licenses/pyserial-BSD-3-Clause.txt").is_file())

    def test_dependency_wheel_records_match_all_installed_files(self):
        site = RUNTIME / "Lib/site-packages"
        checked = 0
        for record in site.glob("*.dist-info/RECORD"):
            with record.open(encoding="utf-8", newline="") as stream:
                for name, hash_spec, size in csv.reader(stream):
                    if not hash_spec:
                        continue
                    algorithm, expected = hash_spec.split("=", 1)
                    contents = (site / name).read_bytes()
                    actual = base64.urlsafe_b64encode(hashlib.new(algorithm, contents).digest()).rstrip(b"=").decode()
                    self.assertEqual(actual, expected, name)
                    self.assertEqual(len(contents), int(size), name)
                    checked += 1
        self.assertGreater(checked, 700)

    def test_binary_wheel_tags_are_cpython312_windows_amd64(self):
        site = RUNTIME / "Lib/site-packages"
        for name in ("pillow-12.3.0.dist-info", "rpds_py-2026.9.1.dist-info"):
            tags = (site / name / "WHEEL").read_text()
            self.assertIn("Tag: cp312-cp312-win_amd64", tags)
            self.assertNotIn("macosx", tags)


if __name__ == "__main__":
    unittest.main(verbosity=2)
