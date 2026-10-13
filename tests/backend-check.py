#!/usr/bin/env python3
"""Offline bridge checks. Serial ports and the CLI store are fully isolated."""
import copy
import errno
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "cyberboard-cli"
if (VENDOR / "cyberboard").is_dir():
    sys.path.insert(0, str(VENDOR))
spec = importlib.util.spec_from_file_location("studio_bridge", ROOT / "backend" / "bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BackendChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cyberboard-studio-offline-")
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"CYBERBOARD_DATA_DIR": str(self.directory / "cli-store")})
        self.env.start()
        self.real_cli, version = bridge.load_cli()
        self.identity = types.SimpleNamespace(product_id="AM01R6", version="test-r6", port="/dev/mock-cyberboard",
                                              is_dongle=False, is_cyberboard=True)
        self.probes = 0
        self.reads = 0
        self.sent = []
        self.serial_opens = 0
        self.serial_requests = []
        self.after_reads = 0
        self.retry_mismatches = 0
        self.after_write = False
        self.bad_start_crc = False
        self.bad_end_header = False
        self.events = []
        self.recorded = []
        resources = self.directory / "resources"
        (resources / "web" / "assets").mkdir(parents=True)
        keys = [{"physical": f"key-{i}", "matrix_index": i, "row": i // 15, "col": i % 15, "span": 2,
                 "bindings": [{"short": "A", "name": "A", "code": "#00070004"} for _ in range(7)]}
                for i in range(81)]
        (resources / "web" / "assets" / "keymap-layout.json").write_text(json.dumps({"keys": keys}))
        self.baseline = self.fixture()
        self.live = copy.deepcopy(self.baseline["key_layer"])
        self.target = None
        self.real_cli["cb_store"].save_current("AM01R6", self.baseline, version="test-r6")
        self.cli = dict(self.real_cli)
        self.cli["cb_device"] = types.SimpleNamespace(BAUD=9600, candidate_ports=lambda: [self.identity.port], probe=self.probe)
        self.cli["cb_read"] = types.SimpleNamespace(_drain=self.drain)
        writer = self.real_cli["cb_write"]
        self.cli["cb_write"] = types.SimpleNamespace(plan=writer.plan, WRITE_DELAY=0.005, SETTLE_SECONDS=2,
                                                     CMD_JSON_START=(1, 5), CMD_JSON_END=(1, 6),
                                                     serial=types.SimpleNamespace(Serial=self.serial), _record_write=self.record)
        self.cli["cb_settime"] = types.SimpleNamespace(serial=types.SimpleNamespace(Serial=self.serial))
        self.backend = bridge.Bridge(self.directory / "app-state", resources, self.cli, version, self.events.append)
        self.sleep = patch.object(bridge.time, "sleep", return_value=None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.env.stop()
        self.temp.cleanup()

    def fixture(self):
        frame = lambda n: {"valid": 1, "frame_num": 1,
                           "frame_data": [{"frame_index": 0, "frame_RGB": ["#000000"] * n}]}
        pages = []
        for index in range(8):
            pages.append({"valid": 1, "page_index": index, "lightness": 100, "speed_ms": 40,
                          "color": {"default": False, "back_rgb": "#000000", "rgb": "#000000"},
                          "word_page": {"valid": 0, "word_len": 0, "unicode": []},
                          "frames": frame(200), "keyframes": frame(90), "//": f"original-{index}"})
        codes = ["#00070004"] * 81 + ["#00000000"] * 119
        return {"product_info": {"product_id": "AM01R6"}, "page_num": 8, "page_data": pages,
                "key_layer": {"valid": 1, "layer_num": 7, "layer_data": [{"layer": codes[:]} for _ in range(7)]},
                "exchange_num": 0, "exchange_key": [], "swap_key_num": 0, "swap_key": [],
                "extraPreserved": {"opaque": [1, 2, "manufacturer-extension"]}}

    def design(self):
        top = [["#FF1200"] * 200, ["#00AABB"] * 200]
        axes = [["#008877"] * 90, ["#AB2200"] * 90]
        for frame in axes:
            for index in bridge.RESERVED_LEDS:
                frame[index] = "#000000"
        return {"id": "offline-design", "name": "Test animation", "speed_ms": 50, "frames": top, "keyframes": axes}

    def payload(self):
        return {"assignments": [{"slot": 2, "design": self.design(), "brightness": 75, "speedMs": 60}]}

    def probe(self, port, **kwargs):
        self.probes += 1
        return self.identity if port == self.identity.port else None

    def drain(self, port, command, **kwargs):
        self.reads += 1
        self.assertEqual(port, self.identity.port)
        self.assertEqual(command, (6, 9))
        keymap = copy.deepcopy(self.target["key_layer"] if self.after_write else self.live)
        if self.after_write:
            self.after_reads += 1
            if self.after_reads <= self.retry_mismatches:
                keymap["layer_data"][0]["layer"][0] = "#00070005"
        data = bridge.matrix(keymap)
        data += b"\0" * (94 * 60 - len(data))
        return [self.real_cli["cb_protocol"].build_frame(6, 9, bytes([index]) + data[index * 60:(index + 1) * 60])
                for index in range(94)]

    def serial(self, *args, **kwargs):
        self.serial_opens += 1
        self.serial_requests.append((args, kwargs))
        parent = self

        class SerialStub:
            def __init__(self):
                self.reply = b""

            def reset_input_buffer(self):
                pass

            def flush(self):
                pass

            def close(self):
                pass

            def write(self, data):
                parent.sent.append(data)
                protocol = parent.real_cli["cb_protocol"]
                if data[:2] == b"\x01\x05":
                    self.reply = protocol.build_frame(1, 5, b"\x01")
                    if parent.bad_start_crc:
                        self.reply = self.reply[:-1] + bytes([self.reply[-1] ^ 1])
                elif data[:2] == b"\x01\x06":
                    parent.after_write = True
                    self.reply = protocol.build_frame(1, 3 if parent.bad_end_header else 6, b"\x01")
                elif data[:2] == b"\x01\x03":
                    self.reply = protocol.build_frame(1, 3, b"\x01")
                return len(data)

            def read(self, count):
                result, self.reply = self.reply, b""
                return result

        return SerialStub()

    def record(self, pid, config, version):
        self.recorded.append(copy.deepcopy(config))
        self.real_cli["cb_store"].save_current(pid, config, version=version)
        self.real_cli["cb_store"].snapshot(pid, config)

    def prepared(self, payload=None):
        result = self.backend.plan(payload or self.payload())
        self.target = bridge.load_json(self.backend.state_dir / "plans" / result["token"] / "target.json")
        return result

    def expect_error(self, code, callback):
        with self.assertRaises(bridge.BridgeError) as result:
            callback()
        self.assertEqual(result.exception.code, code)

    def test_bootstrap_never_probes_or_claims_connected(self):
        result = self.backend.bootstrap({})
        self.assertFalse(result["device"]["connected"])
        self.assertEqual(result["config"]["_provenance"]["led"], "last-written")
        self.assertIsNone(result["workspace"])
        self.assertEqual(self.probes + self.reads + self.serial_opens, 0)

    def test_workspace_roundtrip_is_offline_and_preserves_drafts(self):
        draft = {"designs": [self.design()], "pending": [{"slot": 2, "designId": "offline-design", "brightness": 61, "speedMs": 85}],
                 "selectedId": "offline-design", "targetSlot": 2, "brief": "黑白裂隙，青紫对撞。", "palette": "cyan",
                 "brightness": 74, "speedMs": 77, "exportFormat": "config"}
        result = self.backend.saveWorkspace(draft)
        self.assertTrue(result["saved"])
        self.assertEqual(result["designCount"], 1)
        restored = self.backend.bootstrap({})["workspace"]
        for key, value in draft.items():
            self.assertEqual(restored[key], value)
        self.assertEqual(self.probes + self.reads + self.serial_opens, 0)
        self.assertEqual(self.real_cli["cb_store"].load_current("AM01R6"), self.baseline)

    def test_workspace_can_reference_bundled_design_ids(self):
        result = self.backend.saveWorkspace({"designs": [], "pending": [{"slot": 1, "designId": "neon-rift", "brightness": 100, "speedMs": 40}],
                                            "selectedId": "neon-rift", "targetSlot": 1, "brief": "", "palette": "original"})
        self.assertEqual(result["pendingCount"], 1)
        self.assertEqual(self.backend.bootstrap({})["workspace"]["pending"][0]["designId"], "neon-rift")
        restored = self.backend.bootstrap({})["workspace"]
        self.assertEqual(restored["brightness"], 100)
        self.assertEqual(restored["speedMs"], 40)
        self.assertEqual(restored["exportFormat"], "design")

    def test_workspace_selected_parameters_and_export_format_validated(self):
        self.expect_error("invalid_input", lambda: self.backend.saveWorkspace({"brightness": 101}))
        self.expect_error("invalid_input", lambda: self.backend.saveWorkspace({"speedMs": 0}))
        self.expect_error("invalid_workspace", lambda: self.backend.saveWorkspace({"exportFormat": "arbitrary"}))
        self.assertEqual(self.probes + self.reads + self.serial_opens, 0)

    def test_workspace_rejects_invalid_frames_and_speed(self):
        draft = {"designs": [self.design()]}
        draft["designs"][0]["frames"][0].pop()
        self.expect_error("invalid_animation", lambda: self.backend.saveWorkspace(draft))
        draft = {"designs": [self.design()]}
        draft["designs"][0]["speed_ms"] = 0
        self.expect_error("invalid_input", lambda: self.backend.saveWorkspace(draft))
        self.assertFalse((self.backend.state_dir / "workspace.json").exists())
        self.assertEqual(self.probes + self.reads + self.serial_opens, 0)

    def test_workspace_size_limit_and_nonserializable_metadata(self):
        with patch.object(bridge, "MAX_WORKSPACE_BYTES", 1024):
            self.expect_error("workspace_too_large", lambda: self.backend.saveWorkspace({"designs": [self.design()]}))
        draft = {"designs": [self.design()]}
        draft["designs"][0]["extra"] = float("nan")
        self.expect_error("invalid_workspace", lambda: self.backend.saveWorkspace(draft))

    def test_workspace_max_30_designs_and_unique_pending_slots(self):
        designs = []
        for index in range(31):
            design = self.design()
            design["id"] = f"design-{index}"
            designs.append(design)
        self.expect_error("workspace_limit", lambda: self.backend.saveWorkspace({"designs": designs}))
        pending = [{"slot": 1, "designId": "neon-rift", "brightness": 100, "speedMs": 40}] * 2
        self.expect_error("invalid_workspace", lambda: self.backend.saveWorkspace({"pending": pending}))

    def test_corrupt_workspace_does_not_prevent_cli_bootstrap(self):
        self.backend.state_dir.mkdir(parents=True)
        location = self.backend.state_dir / "workspace.json"
        location.write_text("{broken")
        result = self.backend.bootstrap({})
        self.assertIsNone(result["workspace"])
        self.assertIn("workspaceWarning", result)
        self.assertEqual(result["config"]["key_layer"], self.baseline["key_layer"])
        self.assertEqual(location.read_text(), "{broken")

    def test_detect_refreshes_all_physical_bindings_from_live(self):
        self.live["layer_data"][0]["layer"][0] = "#00070005"
        result = self.backend.detect({})
        self.assertTrue(result["connected"])
        self.assertEqual(len(result["keymap"]["keys"]), 81)
        self.assertEqual(result["keymap"]["keys"][0]["bindings"][0]["code"], "#00070005")
        self.assertEqual(result["keymap"]["keys"][0]["bindings"][0]["short"], "B")
        self.assertEqual(len(bridge.matrix(result["keymap"])), 5600)
        self.assertEqual(self.sent, [])

    def test_plan_preserves_other_slots_keys_and_unknown_fields(self):
        result = self.prepared()
        self.assertEqual(result["changedSlots"], [2])
        self.assertEqual(self.target["key_layer"], self.baseline["key_layer"])
        for index in range(8):
            if index != 6:
                self.assertEqual(self.target["page_data"][index], self.baseline["page_data"][index])
        self.assertEqual(self.target["extraPreserved"], self.baseline["extraPreserved"])
        self.assertEqual(self.target["page_data"][6]["lightness"], 75)
        self.assertEqual(self.target["page_data"][6]["speed_ms"], 60)
        self.assertTrue(Path(result["backupPath"]).is_file())
        self.assertEqual(self.sent, [])

    def test_plan_enables_selected_disabled_text_slot(self):
        self.baseline["page_data"][6]["valid"] = 0
        self.baseline["page_data"][6]["word_page"] = {"valid": 1, "word_len": 1, "unicode": ["#0041"]}
        self.real_cli["cb_store"].save_current("AM01R6", self.baseline)
        self.prepared()
        self.assertIs(self.target["page_data"][6]["valid"], True)
        self.assertEqual(self.target["page_data"][6]["word_page"], {"valid": 0, "word_len": 0, "unicode": []})
        for index in range(8):
            if index != 6:
                self.assertEqual(self.target["page_data"][index], self.baseline["page_data"][index])
        self.assertEqual(self.sent, [])

    def test_inactive_baseline_page_accepts_zero_speed(self):
        self.baseline["page_data"][1].update(valid=0, speed_ms=0)
        self.real_cli["cb_store"].save_current("AM01R6", self.baseline)
        self.prepared()
        self.assertEqual(self.target["page_data"][1], self.baseline["page_data"][1])
        self.assertTrue(bridge.validate_config(self.target, self.cli).total > 0)

    def test_invalid_frame_shape_rejected_before_usb(self):
        payload = self.payload()
        payload["assignments"][0]["design"]["frames"][0].pop()
        self.expect_error("invalid_animation", lambda: self.backend.plan(payload))
        self.assertEqual(self.probes + self.reads + self.serial_opens, 0)

    def test_reserved_key_led_and_duplicate_slots_rejected(self):
        payload = self.payload()
        payload["assignments"][0]["design"]["keyframes"][0][57] = "#FFFFFF"
        self.expect_error("reserved_led", lambda: self.backend.plan(payload))
        payload = self.payload()
        payload["assignments"].append(copy.deepcopy(payload["assignments"][0]))
        self.expect_error("invalid_slots", lambda: self.backend.plan(payload))
        self.assertEqual(self.serial_opens, 0)

    def test_missing_or_mismatched_baseline_prevents_plan(self):
        self.live["layer_data"][0]["layer"][0] = "#00070005"
        self.expect_error("baseline_keymap_changed", lambda: self.backend.plan(self.payload()))
        self.assertEqual(self.sent, [])

    def test_stale_store_prevents_execute(self):
        result = self.prepared()
        updated = copy.deepcopy(self.baseline)
        updated["extraPreserved"]["opaque"].append(4)
        self.real_cli["cb_store"].save_current("AM01R6", updated)
        self.expect_error("baseline_changed", lambda: self.backend.execute({"token": result["token"]}))
        self.assertEqual(self.sent, [])

    def test_changed_live_keys_prevent_execute(self):
        result = self.prepared()
        self.live["layer_data"][0]["layer"][0] = "#00070005"
        self.expect_error("keymap_changed", lambda: self.backend.execute({"token": result["token"]}))
        self.assertEqual(self.sent, [])

    def test_expired_plan_prevents_execute(self):
        result = self.prepared()
        file = self.backend.state_dir / "plans" / result["token"] / "plan.json"
        metadata = bridge.load_json(file)
        metadata["createdTimestamp"] -= 1801
        bridge.atomic_json(file, metadata)
        self.expect_error("plan_expired", lambda: self.backend.execute({"token": result["token"]}))
        self.assertEqual(self.sent, [])

    def test_execute_uses_real_crc_frames_and_actual_progress_then_verifies(self):
        result = self.prepared()
        self.retry_mismatches = 2
        done = self.backend.execute({"token": result["token"]})
        self.assertTrue(done["success"] and done["deviceAck"] and done["keymapMatch"] and done["stateStored"])
        self.assertEqual(self.after_reads, 3)
        self.assertEqual(len(self.sent), result["totalFrames"] + 2)
        self.assertTrue(all(len(frame) == 64 and self.real_cli["cb_protocol"].crc_ok(frame) for frame in self.sent))
        self.assertEqual(self.sent[0][:2], b"\x01\x05")
        self.assertEqual(self.sent[-1][:2], b"\x01\x06")
        self.assertEqual(int.from_bytes(self.sent[-1][2:6], "big"), result["totalFrames"])
        transfers = [event["transferred"] for event in self.events]
        self.assertEqual(transfers, sorted(transfers))
        self.assertEqual(transfers[-1], result["totalFrames"])
        self.assertEqual(self.recorded, [self.target])
        self.expect_error("plan_consumed", lambda: self.backend.execute({"token": result["token"]}))

    def test_ack_crc_and_header_required(self):
        result = self.prepared()
        self.bad_start_crc = True
        self.expect_error("start_ack_failed", lambda: self.backend.execute({"token": result["token"]}))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.recorded, [])

    def test_wrong_end_ack_is_not_success(self):
        result = self.prepared()
        self.bad_end_header = True
        self.expect_error("end_ack_failed", lambda: self.backend.execute({"token": result["token"]}))
        self.assertEqual(self.recorded, [])

    def test_history_restore_is_only_a_plan_and_preserves_keys(self):
        self.real_cli["cb_store"].snapshot("AM01R6", self.baseline)
        history = self.backend.history({})["history"]
        self.assertEqual(history[0]["source"], "last-written")
        result = self.backend.restorePlan({"snapshotId": history[0]["id"], "preserveKeymap": True})
        target = bridge.load_json(self.backend.state_dir / "plans" / result["token"] / "target.json")
        self.assertEqual(target["key_layer"], self.baseline["key_layer"])
        self.assertEqual(result["changedSlots"], [1, 2, 3])
        self.assertEqual(self.sent, [])
        self.expect_error("invalid_snapshot", lambda: self.backend.snapshot_path("cli:../escape.json", "AM01R6"))

    def test_partial_keymap_stream_rejected(self):
        original = self.cli["cb_read"]._drain
        self.cli["cb_read"]._drain = lambda *args, **kwargs: original(*args, **kwargs)[:-1]
        self.expect_error("incomplete_keymap", lambda: self.backend.detect({}))
        self.assertEqual(self.sent, [])

    def test_time_sync_writes_rtc_only_with_timezone(self):
        result = self.backend.setTime({"timezone": "Asia/Shanghai"})
        self.assertTrue(result["success"])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][:2], b"\x01\x03")
        self.assertEqual(self.sent[0][6:8], bytes([0, 8]))
        self.assertEqual(self.recorded, [])

    def test_windows_com_port_preserves_plan_write_and_verification_guards(self):
        self.identity.port = "COM12"
        result = self.prepared({**self.payload(), "port": "COM12"})
        self.assertEqual(result["device"]["port"], "COM12")
        self.assertEqual(self.sent, [])
        written = self.backend.execute({"token": result["token"]})
        self.assertTrue(written["deviceAck"] and written["keymapMatch"] and written["stateStored"])
        self.assertEqual(written["device"]["port"], "COM12")
        self.assertEqual(self.serial_requests[0][0][0], "COM12")
        # pyserial's Windows implementation requires exclusive access; True
        # is supported and must not be changed to False for the Windows port.
        self.assertIs(self.serial_requests[0][1]["exclusive"], True)
        self.assertEqual(self.recorded[0]["key_layer"], self.baseline["key_layer"])

    def test_invalid_or_missing_timezone_never_probes_or_writes(self):
        self.expect_error("invalid_timezone", lambda: self.backend.setTime({"timezone": "Not/A_Zone"}))
        self.expect_error("invalid_timezone", lambda: self.backend.setTime({"timezone": 8}))
        with patch.object(bridge, "ZoneInfo", side_effect=bridge.ZoneInfoNotFoundError("tzdata missing")):
            self.expect_error("timezone_data_missing", lambda: self.backend.setTime({"timezone": "Asia/Shanghai"}))
        self.assertEqual(self.probes + self.reads + self.serial_opens, 0)

    def test_windows_timezone_database_and_fractional_offset_encoding(self):
        epoch = 1_792_000_000
        with patch.object(bridge.sys, "platform", "win32"), patch.object(bridge.time, "time", return_value=epoch):
            result = self.backend.setTime({"timezone": "Asia/Kathmandu"})
        self.assertEqual(result["timezone"], "Asia/Kathmandu")
        self.assertEqual(int.from_bytes(self.sent[0][2:6], "big", signed=True), epoch + 45 * 60)
        self.assertEqual(self.sent[0][6:8], bytes([0, 5]))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.recorded, [])


class PlatformChecks(unittest.TestCase):
    def test_windows_json_lines_remain_utf8_under_legacy_code_page(self):
        buffers = [io.BytesIO(), io.BytesIO(), io.BytesIO()]
        streams = [io.TextIOWrapper(buffer, encoding="cp1252", newline="\r\n") for buffer in buffers]
        try:
            with patch.object(bridge.sys, "platform", "win32"), \
                    patch.object(bridge.sys, "stdin", streams[0]), \
                    patch.object(bridge.sys, "stdout", streams[1]), \
                    patch.object(bridge.sys, "stderr", streams[2]):
                bridge.configure_stdio()
                bridge.emit({"result": {"name": "猫爪 · 灯效", "path": "C:\\用户\\作品.json"}})
                encoded = buffers[1].getvalue()
            self.assertEqual(json.loads(encoded.decode("utf-8"))["result"]["name"], "猫爪 · 灯效")
            self.assertTrue(encoded.endswith(b"\n"))
            self.assertNotIn(b"\r\n", encoded)
            self.assertTrue(all(stream.encoding == "utf-8" for stream in streams))
        finally:
            for stream in streams:
                stream.close()

    def test_windows_operation_lock_retries_contention_and_unlocks_on_exception(self):
        calls = []
        attempts = 0

        def locking(fd, command, length):
            nonlocal attempts
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), 0)
            self.assertEqual(length, 1)
            self.assertGreaterEqual(os.fstat(fd).st_size, 1)
            calls.append(command)
            if command == 1:
                attempts += 1
                if attempts <= 2:
                    raise OSError(errno.EACCES, "locked by another app process")

        fake = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=0, locking=locking)
        with tempfile.TemporaryDirectory(prefix="studio-lock-") as folder, \
                patch.object(bridge.sys, "platform", "win32"), \
                patch.dict(bridge.sys.modules, {"msvcrt": fake}), \
                patch.object(bridge.time, "sleep") as sleep:
            path = Path(folder) / "state" / ".operation.lock"
            with self.assertRaisesRegex(RuntimeError, "failed operation"):
                with bridge.operation_lock(path):
                    self.assertEqual(attempts, 3)
                    raise RuntimeError("failed operation")
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(calls, [1, 1, 1, 0])
            self.assertEqual(path.read_bytes(), b"\0")

    def test_windows_operation_lock_does_not_retry_filesystem_errors(self):
        error = OSError(errno.EBADF, "invalid handle")
        fake = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=0, locking=lambda *args: (_ for _ in ()).throw(error))
        with tempfile.TemporaryDirectory(prefix="studio-lock-") as folder, \
                patch.object(bridge.sys, "platform", "win32"), \
                patch.dict(bridge.sys.modules, {"msvcrt": fake}), \
                patch.object(bridge.time, "sleep") as sleep:
            with self.assertRaises(OSError) as caught:
                with bridge.operation_lock(Path(folder) / ".operation.lock"):
                    self.fail("An invalid handle must never acquire the operation lock.")
            self.assertIs(caught.exception, error)
            sleep.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX lock branch")
    def test_posix_operation_lock_releases_on_exception(self):
        import fcntl
        with tempfile.TemporaryDirectory(prefix="studio-lock-") as folder, patch.object(fcntl, "flock") as flock:
            with self.assertRaises(RuntimeError):
                with bridge.operation_lock(Path(folder) / ".operation.lock"):
                    raise RuntimeError("failed operation")
            self.assertEqual([call.args[1] for call in flock.call_args_list], [fcntl.LOCK_EX, fcntl.LOCK_UN])

    def test_atomic_json_handles_unicode_paths_and_preserves_previous_file_on_failure(self):
        with tempfile.TemporaryDirectory(prefix="studio-state-") as folder:
            path = Path(folder) / "用户 作品" / "workspace.json"
            old = {"name": "原作品", "frames": [1, 2, 3]}
            bridge.atomic_json(path, old)
            bridge.atomic_json(path, {"name": "更新灯效"}, compact=True)
            self.assertEqual(bridge.load_json(path), {"name": "更新灯效"})
            with patch.object(os, "fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    bridge.atomic_json(path, old)
            self.assertEqual(bridge.load_json(path), {"name": "更新灯效"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
