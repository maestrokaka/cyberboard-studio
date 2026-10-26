#!/usr/bin/env python3
"""Offline R6 direct writes with a simulated device, never real USB."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import r6_keymap as r6


def packet(sub, payload=b""):
    data = (bytes([6, sub]) + bytes(payload)).ljust(63, b"\0")
    return data + bytes([r6.crc8(data)])


def macro_read(items):
    chunks = [(item, index // 8, item["events"][index:index + 8]) for item in items for index in range(0, len(item["events"]), 8)]
    if not chunks:
        return [packet(10)]
    frames = []
    for global_index, (item, index, events) in enumerate(chunks):
        payload = bytes([len(chunks), global_index, int(item["trigger"][-2:], 16)]) + bytes.fromhex(item["trigger"][1:]) + bytes([index])
        for event in events:
            payload += bytes.fromhex(event["code"][1:]) + event["delayMs"].to_bytes(2, "big")
        frames.append(packet(10, payload))
    return frames


def hold_read(items):
    if not items:
        return [packet(14)]
    return [packet(14, len(items).to_bytes(2, "big") + bytes([0, index]) + bytes.fromhex(item["trigger"][1:]) + item["intervalMs"].to_bytes(2, "big") + bytes.fromhex(item["tapCode"][1:]) + bytes.fromhex(item["holdCode"][1:])) for index, item in enumerate(items)]


class SimulatedSerial:
    def __init__(self, device, **kwargs):
        self.device, self.queue, self.closed = device, [], False

    def reset_input_buffer(self):
        self.queue = []

    def write(self, data):
        self.device.writes.append(data)
        if data[:2] == b"\x06\x0a":
            self.queue = [] if self.device.unavailable else macro_read(self.device.macros)
        elif data[:2] == b"\x06\x0e":
            self.queue = [] if self.device.unavailable else hold_read(self.device.holds)
        else:
            self.device.mutations.append(data)
            if self.device.fail_write:
                self.device.fail_write = False
                return 12
            if data[:2] == b"\x06\x0b":
                layer, row, index = data[2:5]
                pos = row * 25 + index
                old, new = r6.read_code(data, 5), r6.read_code(data, 9)
                if self.device.matrix["layer_data"][layer]["layer"][pos].upper() == old:
                    self.device.matrix["layer_data"][layer]["layer"][pos] = new
            elif data[:2] == b"\x06\x0d":
                trigger = r6.read_code(data, 6)
                item = {"trigger": trigger, "intervalMs": int.from_bytes(data[10:12], "big"), "tapCode": r6.read_code(data, 12), "holdCode": r6.read_code(data, 16)}
                self.device.holds = [entry for entry in self.device.holds if entry["trigger"] != trigger]
                if item["intervalMs"] or item["tapCode"] != r6.ZERO or item["holdCode"] != r6.ZERO:
                    self.device.holds.append(item)
                self.device.holds.sort(key=lambda entry: entry["trigger"])
            elif data[:2] == b"\x06\x05":
                if data[3] == 0:
                    self.device.macro_batch = []
                self.device.macro_batch.append(data)
                if len(self.device.macro_batch) == data[2]:
                    reads = []
                    for item in self.device.macro_batch:
                        reads.append(packet(10, item[2:63]))
                    self.device.macros = r6.parse_macros(reads)
            else:
                raise AssertionError("Unexpected write: " + data.hex())
        return len(data)

    def read(self, count):
        return self.queue.pop(0) if self.queue else b""

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeBridge:
    def __init__(self, folder):
        self.state_dir = Path(folder)
        self.identity = types.SimpleNamespace(product_id="AM01R6", version="test-r6.1", port="TEST-USB")
        self.matrix = {"valid": 1, "layer_num": 7, "layer_data": [{"layer": ["#00070004"] * 200} for _ in range(7)]}
        self.matrix["layer_data"][6]["layer"][199] = "#DeAdBeEF"
        self.macros, self.holds = [], []
        self.unavailable, self.fail_write = False, False
        self.writes, self.mutations, self.events, self.macro_batch = [], [], [], []
        self.cli = {"cb_write": types.SimpleNamespace(serial=types.SimpleNamespace(Serial=lambda port, **kwargs: SimulatedSerial(self, **kwargs)))}

    def discover(self, payload):
        return self.identity

    def read_live(self, port):
        return copy.deepcopy(self.matrix), r6.matrix_bytes(self.matrix)

    def device_dict(self, identity):
        return {"productId": identity.product_id, "firmware": identity.version, "port": identity.port, "connected": True}

    def keymap_view(self, matrix, source="live"):
        return {**copy.deepcopy(matrix), "source": source, "keymapHash": r6.keymap_hash(matrix)}

    def decode_binding(self, code):
        return {"code": code, "name": "test"}

    def validated_key_changes(self, changes, allow_empty=False):
        r6.require(isinstance(changes, list) and (allow_empty or changes), "invalid", "invalid")
        seen = set()
        for item in changes:
            r6.require(isinstance(item, dict) and set(item) == {"layer", "matrixIndex", "code"} and type(item["layer"]) is int and 0 <= item["layer"] < 7 and type(item["matrixIndex"]) is int and 0 <= item["matrixIndex"] < 81 and (item["layer"], item["matrixIndex"]) not in seen, "invalid", "invalid")
            r6.code_bytes(item["code"])
            seen.add((item["layer"], item["matrixIndex"]))
        return changes

    def event(self, *args):
        self.events.append(args)

    def payload(self):
        return {"expectedKeymapHash": r6.keymap_hash(self.matrix), "expectedProductId": self.identity.product_id, "expectedFirmware": self.identity.version,
                "expectedAdvancedHash": r6.digest({"macros": self.macros, "pressHolds": self.holds})}


class DirectKeymapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.b = FakeBridge(self.temporary.name)
        self.sleep = patch.object(r6.time, "sleep", lambda _: None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.temporary.cleanup()

    def test_direct_key_packet_layout_and_crc(self):
        data = r6.change_key(6, 80, "#DEADBEEF", "#00070005")
        self.assertEqual(data[:13], bytes.fromhex("06 0b 06 03 05 de ad be ef 00 07 00 05"))
        self.assertEqual(len(data), 64)
        self.assertEqual(r6.crc8(data[:63]), data[63])

    def test_press_hold_packet_known_layout(self):
        item = {"trigger": "#00951403", "tapCode": "#11070004", "holdCode": "#110700E1", "intervalMs": 250}
        data = r6.press_hold_packet(item)
        self.assertEqual(data[:20], bytes.fromhex("06 0d 00 c8 00 03 00 95 14 03 00 fa 11 07 00 04 11 07 00 e1"))

    def test_macro_chunking_byte_order_and_preservation(self):
        events = [{"code": "#11070004", "delayMs": 300}] * 9
        packets = r6.macro_packets([{"trigger": "#00951500", "events": events}])
        self.assertEqual(len(packets), 2)
        self.assertEqual(packets[0][:16], bytes.fromhex("06 05 02 00 00 00 95 15 00 00 11 07 00 04 01 2c"))
        self.assertEqual(packets[1][9], 1)
        self.assertEqual(r6.parse_macros(macro_read([{"trigger": "#00951500", "events": events}])), [{"trigger": "#00951500", "events": events}])

    def test_full_readback_empty_sentinel_and_partial_rejected(self):
        self.assertEqual(r6.parse_macros([packet(10)]), [])
        self.assertEqual(r6.parse_press_holds([packet(14)]), [])
        events = [{"code": "#11070004", "delayMs": 1}] * 9
        frames = macro_read([{"trigger": "#00951500", "events": events}])
        for bad in [[frames[0]], [frames[0], frames[0]], [frames[1], frames[1]], [frames[0][:-1]]]:
            with self.assertRaises(r6.R6KeymapError):
                r6.parse_macros(bad)

    def test_no_activity_until_read_or_plan_and_read_preserves_raw(self):
        self.assertEqual(self.b.writes, [])
        value = r6.read(self.b, {})
        self.assertTrue(value["advanced"]["available"])
        self.assertEqual(value["keymap"]["layer_data"][6]["layer"][199], "#DeAdBeEF")
        self.assertEqual(self.b.mutations, [])

    def test_ordinary_direct_plan_does_not_require_or_write_led_json(self):
        before = copy.deepcopy(self.b.matrix)
        payload = self.b.payload()
        payload["keyChanges"] = [{"layer": 1, "matrixIndex": 3, "code": "#00070005"}]
        plan = r6.plan(self.b, payload)
        self.assertEqual(self.b.mutations, [])
        self.assertEqual(plan["totalFrames"], 1)
        self.assertFalse(plan["ledTransmitted"])
        result = r6.execute(self.b, {"token": plan["token"]})
        self.assertTrue(result["success"])
        self.assertIsNone(result["deviceAck"])
        self.assertEqual(result["verification"]["keymap"], "readback-verified")
        before["layer_data"][1]["layer"][3] = "#00070005"
        self.assertEqual(self.b.matrix, before)
        self.assertEqual({data[:2] for data in self.b.mutations}, {b"\x06\x0b"})
        with self.assertRaises(r6.R6KeymapError):
            r6.execute(self.b, {"token": plan["token"]})

    def test_plan_rejects_changed_identity_hash_and_nonphysical(self):
        payload = self.b.payload()
        payload["keyChanges"] = [{"layer": 0, "matrixIndex": 1, "code": "#00070005"}]
        for changes in [{"expectedFirmware": "old"}, {"expectedKeymapHash": "0" * 64}, {"keyChanges": [{"layer": 0, "matrixIndex": 199, "code": "#00070005"}]}, {"keyChanges": [{"layer": 0, "matrixIndex": 1, "code": "#00951500"}]}]:
            with self.assertRaises(r6.R6KeymapError):
                r6.plan(self.b, {**payload, **changes})
        self.assertEqual(self.b.mutations, [])

    def test_macro_create_edit_delete_and_nontarget_table(self):
        self.b.holds = [{"trigger": "#00951404", "tapCode": "#11070005", "holdCode": "#110700E1", "intervalMs": 200}]
        payload = self.b.payload()
        payload["edit"] = {"type": "macro", "layer": 0, "matrixIndex": 1, "events": [{"code": "#11070004", "delayMs": 10}, {"code": "#10070004", "delayMs": 10}]}
        plan = r6.plan(self.b, payload)
        result = r6.execute(self.b, {"token": plan["token"]})
        self.assertEqual(self.b.matrix["layer_data"][0]["layer"][1], "#00951500")
        self.assertEqual(result["verification"]["advanced"], "readback-verified")
        self.assertEqual(len(self.b.holds), 1)
        payload = self.b.payload()
        payload["edit"] = {"type": "remove-macro", "layer": 0, "matrixIndex": 1, "replacementCode": "#00070005"}
        plan = r6.plan(self.b, payload)
        r6.execute(self.b, {"token": plan["token"]})
        self.assertEqual(self.b.macros, [])
        self.assertEqual(self.b.matrix["layer_data"][0]["layer"][1], "#00070005")
        self.assertEqual(len(self.b.holds), 1)

    def test_press_hold_create_and_delete(self):
        payload = self.b.payload()
        payload["edit"] = {"type": "press-hold", "layer": 2, "matrixIndex": 5, "tapCode": "#11070004", "holdCode": "#110700E1", "intervalMs": 200}
        plan = r6.plan(self.b, payload)
        r6.execute(self.b, {"token": plan["token"]})
        self.assertEqual(self.b.holds[0]["trigger"], "#00951400")
        payload = self.b.payload()
        payload["edit"] = {"type": "remove-press-hold", "layer": 2, "matrixIndex": 5, "replacementCode": "#00070004"}
        plan = r6.plan(self.b, payload)
        r6.execute(self.b, {"token": plan["token"]})
        self.assertEqual(self.b.holds, [])

    def test_advanced_unavailable_never_invented_empty(self):
        self.b.unavailable = True
        value = r6.read(self.b, {})
        self.assertFalse(value["advanced"]["available"])
        self.assertNotIn("macros", value["advanced"])
        payload = self.b.payload()
        payload["edit"] = {"type": "macro", "layer": 0, "matrixIndex": 1, "events": []}
        with self.assertRaises(r6.R6KeymapError):
            r6.plan(self.b, payload)
        payload.pop("edit")
        payload["keyChanges"] = [{"layer": 0, "matrixIndex": 1, "code": "#00070005"}]
        result = r6.execute(self.b, {"token": r6.plan(self.b, payload)["token"]})
        self.assertEqual(result["verification"]["advanced"], "unavailable")

    def test_partial_write_unknown_blocks_replay_until_explicit_full_read(self):
        payload = self.b.payload()
        payload["keyChanges"] = [{"layer": 0, "matrixIndex": 1, "code": "#00070005"}]
        plan = r6.plan(self.b, payload)
        self.b.fail_write = True
        with self.assertRaises(r6.R6KeymapError) as ctx:
            r6.execute(self.b, {"token": plan["token"]})
        self.assertEqual(ctx.exception.code, "r6_state_unknown")
        record = json.loads((r6._directory(self.b) / plan["token"] / "plan.json").read_text())
        self.assertEqual(record["status"], "unknown")
        with self.assertRaises(r6.R6KeymapError):
            r6.plan(self.b, payload)
        r6.read(self.b, {})
        r6.plan(self.b, payload)

    def test_macro_unbalanced_and_shared_trigger_rejected(self):
        payload = self.b.payload()
        payload["edit"] = {"type": "macro", "layer": 0, "matrixIndex": 1, "events": [{"code": "#11070004", "delayMs": 1}]}
        with self.assertRaises(r6.R6KeymapError):
            r6.plan(self.b, payload)

        self.b.matrix["layer_data"][0]["layer"][1:3] = ["#00951500"] * 2
        self.b.macros = [{"trigger": "#00951500", "events": [{"code": "#11070004", "delayMs": 1}, {"code": "#10070004", "delayMs": 1}]}]
        payload = self.b.payload()
        payload["edit"] = {"type": "remove-macro", "layer": 0, "matrixIndex": 1, "replacementCode": "#00070005"}
        with self.assertRaises(r6.R6KeymapError):
            r6.plan(self.b, payload)

    def test_old_prepared_plan_cannot_skip_an_unknown_write(self):
        payload = self.b.payload()
        payload["keyChanges"] = [{"layer": 0, "matrixIndex": 1, "code": "#00070005"}]
        first, second = r6.plan(self.b, payload), r6.plan(self.b, payload)
        self.b.fail_write = True
        with self.assertRaises(r6.R6KeymapError):
            r6.execute(self.b, {"token": first["token"]})
        before = len(self.b.mutations)
        with self.assertRaises(r6.R6KeymapError):
            r6.execute(self.b, {"token": second["token"]})
        self.assertEqual(len(self.b.mutations), before)

    def test_full_json_guard_detects_unbound_macros_and_unknown_reads(self):
        self.b.macros = [{"trigger": "#00951507", "events": [{"code": "#11070004", "delayMs": 0}, {"code": "#10070004", "delayMs": 0}]}]
        # No matrix entry refers to this trigger, but it still must survive.
        result = r6.inspect_advanced_protection(self.b, self.b.identity)
        self.assertTrue(result["known"])
        self.assertTrue(result["active"])
        self.assertEqual(self.b.mutations, [])
        self.b.unavailable = True
        result = r6.inspect_advanced_protection(self.b, self.b.identity)
        self.assertFalse(result["known"])
        self.assertTrue(result["active"])
        self.assertEqual(result["source"], "readback-unavailable")

    def test_macro_update_preserves_other_macros_with_full_table(self):
        self.b.macros = [{"trigger": "#00951504", "events": [{"code": "#11070005", "delayMs": 0}, {"code": "#10070005", "delayMs": 50000}]}]
        payload = self.b.payload()
        payload["edit"] = {"type": "macro", "layer": 0, "matrixIndex": 1, "events": [{"code": "#11070004", "delayMs": 100}, {"code": "#10070004", "delayMs": 100}]}
        plan = r6.plan(self.b, payload)
        r6.execute(self.b, {"token": plan["token"]})
        preserved = next(item for item in self.b.macros if item["trigger"] == "#00951504")
        self.assertEqual(preserved["events"][0]["delayMs"], 0)
        self.assertEqual(preserved["events"][1]["delayMs"], 50000)

    def test_mutation_of_plan_file_and_device_after_prepare_rejected(self):
        payload = self.b.payload()
        payload["keyChanges"] = [{"layer": 0, "matrixIndex": 1, "code": "#00070005"}]
        plan = r6.plan(self.b, payload)
        path = r6._directory(self.b) / plan["token"] / "target.json"
        target = json.loads(path.read_text())
        target["keymap"]["layer_data"][5]["layer"][199] = "#FFFFFFFF"
        path.write_text(json.dumps(target))
        with self.assertRaises(r6.R6KeymapError):
            r6.execute(self.b, {"token": plan["token"]})
        self.assertEqual(self.b.mutations, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
