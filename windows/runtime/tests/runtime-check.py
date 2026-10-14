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

    def test_failed_candidate_does_not_hide_keyboard_before_or_after_it(self):
        identity = protocol.build_frame(1, 1, bytes([6]) + b"AM01R6")
        for ports in (["COM3", "COM12"], ["COM12", "COM3"]):
            with self.subTest(ports=ports):
                opened, handles = [], []

                def create(port, **settings):
                    opened.append(port)
                    self.assertEqual(settings, {"baudrate": 9600, "timeout": 1.5,
                                                "write_timeout": 1.5, "exclusive": True})
                    handle = mock.Mock()
                    handles.append(handle)
                    if port == "COM3":
                        handle.write.side_effect = device.serial.SerialTimeoutException("Write timeout")
                    else:
                        handle.read.return_value = identity
                    return handle

                with mock.patch.object(device, "candidate_ports", return_value=ports), \
                        mock.patch.object(device.serial, "Serial", side_effect=create), \
                        mock.patch.object(device.time, "sleep"):
                    found = device.list_devices()
                self.assertEqual(opened, ports)
                self.assertEqual([(info.port, info.product_id) for info in found], [("COM12", "AM01R6")])
                for handle in handles:
                    handle.close.assert_called_once()
                    handle.write.assert_called_once_with(protocol.build_frame(1, 1))

    def test_probe_reports_exact_query_stage_for_each_io_failure(self):
        replies = [protocol.build_frame(1, 1, bytes([6]) + b"AM01R6"),
                   protocol.build_frame(1, 2, bytes([4]) + b"1.00"),
                   protocol.build_frame(2, 6, bytes([8]))]
        commands = [(1, 1), (1, 2), (2, 6)]
        for query_index, stage in enumerate(("identity", "firmware", "pages")):
            for point in ("reset_input_buffer", "write", "flush", "read"):
                for exception, kind in ((device.serial.SerialTimeoutException("Write timeout"), "timeout"),
                                        (device.serial.SerialException("Device disconnected"), "serial_error"),
                                        (OSError("Driver I/O failure"), "serial_error")):
                    with self.subTest(stage=stage, point=point, kind=kind):
                        handle = mock.Mock()
                        handle.read.side_effect = replies
                        successful = replies[:query_index] if point == "read" else [None] * query_index
                        getattr(handle, point).side_effect = [*successful, exception]
                        with mock.patch.object(device.serial, "Serial", return_value=handle), \
                                mock.patch.object(device.time, "sleep"):
                            info, failure = device.probe_with_diagnostics("COM3", full=True)
                        if query_index == 0:
                            self.assertIsNone(info)
                        else:
                            self.assertEqual(info, device.DeviceInfo(
                                "COM3", "AM01R6", "1.00" if query_index == 2 else None,
                                None, True, False))
                        self.assertEqual(failure, {"port": "COM3", "stage": stage, "kind": kind,
                                                  "reason": str(exception)})
                        handle.close.assert_called_once()
                        expected_queries = query_index + (point != "reset_input_buffer")
                        self.assertEqual(handle.write.call_args_list,
                                         [mock.call(protocol.build_frame(*cmd)) for cmd in commands[:expected_queries]])

    def test_legacy_probe_still_rejects_partial_identity_after_metadata_timeout(self):
        identity = protocol.build_frame(1, 1, bytes([6]) + b"AM01R6")
        version = protocol.build_frame(1, 2, bytes([4]) + b"1.00")
        for query_index in (1, 2):
            with self.subTest(query_index=query_index):
                handle = mock.Mock()
                handle.read.side_effect = [identity, version][:query_index]
                handle.write.side_effect = [None] * query_index + [device.serial.SerialTimeoutException("Write timeout")]
                with mock.patch.object(device.serial, "Serial", return_value=handle), \
                        mock.patch.object(device.time, "sleep"):
                    self.assertIsNone(device.probe("COM3", full=True))
                self.assertEqual(handle.write.call_count, query_index + 1)
                handle.close.assert_called_once()

    def test_open_error_diagnostics_and_old_probe_api(self):
        for exception, kind in ((device.serial.SerialTimeoutException("Open timed out"), "timeout"),
                                (device.serial.SerialException("Access denied"), "serial_error"),
                                (OSError("Port missing"), "serial_error")):
            with self.subTest(kind=kind), \
                    mock.patch.object(device.serial, "Serial", side_effect=exception) as create, \
                    mock.patch.object(device, "_query", side_effect=AssertionError("query after failed open")):
                self.assertEqual(device.probe_with_diagnostics("COM3"),
                                 (None, {"port": "COM3", "stage": "open", "kind": kind,
                                         "reason": str(exception)}))
                self.assertIsNone(device.probe("COM3"))
                self.assertEqual(create.call_count, 2)

    def test_close_error_does_not_conceal_original_failure_or_valid_identity(self):
        identity = protocol.build_frame(1, 1, bytes([6]) + b"AM01R6")
        for write_error in (None, device.serial.SerialTimeoutException("Write timeout")):
            with self.subTest(write_error=write_error):
                handle = mock.Mock()
                handle.write.side_effect = write_error
                handle.read.return_value = identity
                handle.close.side_effect = OSError("Disconnect during close")
                with mock.patch.object(device.serial, "Serial", return_value=handle), \
                        mock.patch.object(device.time, "sleep"):
                    info, failure = device.probe_with_diagnostics("COM3")
                handle.close.assert_called_once()
                if write_error is None:
                    self.assertEqual(info.product_id, "AM01R6")
                    self.assertIsNone(failure)
                else:
                    self.assertIsNone(info)
                    self.assertEqual(failure["reason"], "Write timeout")

    def test_full_query_replies_still_require_real_crc(self):
        identity = protocol.build_frame(1, 1, bytes([6]) + b"AM01R6")
        version = protocol.build_frame(1, 2, bytes([4]) + b"1.00")
        pages = protocol.build_frame(2, 6, bytes([8]))
        for valid in (True, False):
            with self.subTest(valid=valid):
                handle = mock.Mock()
                damaged_version = version[:-1] + bytes([version[-1] ^ 1])
                damaged_pages = pages[:-1] + bytes([pages[-1] ^ 1])
                handle.read.side_effect = [identity, version if valid else damaged_version,
                                          pages if valid else damaged_pages]
                with mock.patch.object(device.serial, "Serial", return_value=handle), \
                        mock.patch.object(device.time, "sleep"):
                    info, failure = device.probe_with_diagnostics("COM12", full=True)
                self.assertIsNone(failure)
                self.assertEqual((info.product_id, info.version, info.pages),
                                 ("AM01R6", "1.00" if valid else None, 8 if valid else None))
                self.assertEqual(handle.write.call_args_list,
                                 [mock.call(protocol.build_frame(*cmd)) for cmd in ((1, 1), (1, 2), (2, 6))])
                handle.close.assert_called_once()

    def test_nonmatch_is_not_mislabeled_as_transport_failure(self):
        for reply, expected_id in ((bytes(64), None),
                                   (protocol.build_frame(1, 1), None),
                                   (protocol.build_frame(1, 1, bytes([5]) + b"Other"), "Other"),
                                   (protocol.build_frame(1, 1, bytes([13]) + b"AM01R6_DONGLE"), "AM01R6_DONGLE")):
            with self.subTest(identity=expected_id):
                handle = mock.Mock()
                handle.read.return_value = reply
                with mock.patch.object(device.serial, "Serial", return_value=handle), \
                        mock.patch.object(device.time, "sleep"):
                    info, failure = device.probe_with_diagnostics("COM3", full=True)
                self.assertIsNone(failure)
                self.assertEqual(info.product_id if info else None, expected_id)
                self.assertFalse(info and info.is_cyberboard)
                handle.write.assert_called_once_with(protocol.build_frame(1, 1))
                handle.close.assert_called_once()

    def test_every_failed_candidate_has_bounded_diagnostic_without_retry(self):
        ports = ["COM3", "COM12"]
        handles = []

        def create(port, **settings):
            handle = mock.Mock()
            handle.write.side_effect = device.serial.SerialTimeoutException("T" * 750)
            handles.append(handle)
            return handle

        with mock.patch.object(device.serial, "Serial", side_effect=create), \
                mock.patch.object(device.time, "sleep"):
            failures = [device.probe_with_diagnostics(port)[1] for port in ports]
        self.assertEqual([failure["port"] for failure in failures], ports)
        self.assertTrue(all(failure["stage"] == "identity" and failure["kind"] == "timeout" and
                            failure["reason"] == "T" * 500 for failure in failures))
        for handle in handles:
            handle.write.assert_called_once_with(protocol.build_frame(1, 1))
            handle.read.assert_not_called()
            handle.close.assert_called_once()

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
