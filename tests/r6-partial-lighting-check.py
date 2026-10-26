#!/usr/bin/env python3
"""Offline scope/packing checks; no device, transport or real firmware."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import r6_partial_lighting as partial


def fixture():
    # Load the public synthetic config already used by the frontend checks.
    return json.loads(subprocess.check_output(["node", "-e", "process.stdout.write(JSON.stringify(require('./data/test-fixtures.cjs')()))"], cwd=ROOT))


class PartialLightingTests(unittest.TestCase):
    def setUp(self):
        self.before = fixture()
        self.before["macro_key"] = [{"original_key": "#00951500", "layer_key": ["#11070004", "#10070004"], "intvel_ms": [100, 100]}]
        self.before["tab_key"] = [{"ph_key_data": "#00951400", "first_key": "#11070004", "second_key": "#110700E1", "interval_time": 200}]
        self.before["key_layer"]["layer_data"][6]["layer"][199] = "#DEADBEEF"
        self.target = copy.deepcopy(self.before)
        self.target["page_data"][6]["frames"]["frame_data"][0]["frame_RGB"][0] = "#FF0000"

    def plan(self, **kwargs):
        return partial.preview_plan(self.before, self.target, slots=[2], domains=["top"], **kwargs)

    def test_local_scope_and_ignore_flags(self):
        before, target = copy.deepcopy(self.before), copy.deepcopy(self.target)
        plan = self.plan()
        self.assertFalse(plan["executable"])
        self.assertTrue(plan["requiresHardwareValidation"])
        self.assertTrue(plan["scope"]["localScopeVerified"])
        self.assertFalse(plan["scope"]["deviceStateVerified"])
        self.assertEqual(plan["validDirectives"][-1], 2)
        self.assertEqual(plan["validDirectives"][6 * 4:6 * 4 + 4], [2, 2, 1, 2])
        for page in range(8):
            if page != 6:
                self.assertEqual(plan["validDirectives"][page * 4:page * 4 + 4], [2] * 4)
        self.assertEqual(self.before, before)
        self.assertEqual(self.target, target)
        self.assertEqual(plan["profile"]["macro_key"], self.before["macro_key"])
        self.assertEqual(plan["profile"]["tab_key"], self.before["tab_key"])
        self.assertEqual(plan["profile"]["key_layer"]["layer_data"], self.before["key_layer"]["layer_data"])

    def test_packet_scope_crc_and_independent_RGB_reconstruction(self):
        plan = self.plan()
        packets = [bytes.fromhex(data) for data in plan["candidateFramesHex"]]
        self.assertEqual(packets[0][:3], bytes([2, 5, 8]))
        self.assertEqual(packets[1][:2], bytes([1, 5]))
        self.assertEqual(packets[2][:3], bytes([2, 1, 8]))
        self.assertEqual(packets[-1][:2], bytes([1, 6]))
        self.assertEqual(int.from_bytes(packets[-1][2:6], "big"), plan["dataFrameCount"])
        self.assertEqual({packet[1] for packet in packets if packet[0] == 4}, {6})
        self.assertFalse(any(packet[0] in (5, 6, 7, 12) for packet in packets))
        for data in packets:
            self.assertEqual(len(data), 64)
            self.assertEqual(partial._crc8(data[:63]), data[63])
        top = [data for data in packets if data[0] == 4 and data[2:4] == bytes([0, 0])]
        self.assertEqual([data[4] for data in top], list(range(11)))
        reconstructed = b"".join(data[5:61] for data in top)[:600]
        expected = b"".join(bytes.fromhex(color[1:]) for color in self.target["page_data"][6]["frames"]["frame_data"][0]["frame_RGB"])
        self.assertEqual(reconstructed, expected)

    def test_every_nontarget_subsystem_change_is_rejected(self):
        for mutate in [
            lambda c: c["key_layer"]["layer_data"][0]["layer"].__setitem__(0, "#00070005"),
            lambda c: c["macro_key"][0]["intvel_ms"].__setitem__(0, 1),
            lambda c: c["tab_key"][0].__setitem__("interval_time", 250),
            lambda c: c["page_data"][5]["frames"]["frame_data"][0]["frame_RGB"].__setitem__(0, "#FF0000"),
            lambda c: c["page_data"][6]["keyframes"]["frame_data"][0]["frame_RGB"].__setitem__(0, "#FF0000"),
            lambda c: c["page_data"][6].__setitem__("speed_ms", 20),
            lambda c: c["page_data"][6].__setitem__("lightness", 99),
            lambda c: c["page_data"][6].__setitem__("valid", 0),
            lambda c: c["page_data"][6]["word_page"].__setitem__("unicode", ["#0041"]),
            lambda c: c.__setitem__("unexpected", "changed"),
        ]:
            with self.subTest(mutate=mutate):
                target = copy.deepcopy(self.target)
                mutate(target)
                with self.assertRaises(partial.PartialLightingError):
                    partial.preview_plan(self.before, target, slots=[2], domains=["top"])

    def test_selected_axis_only_reconstruction(self):
        target = copy.deepcopy(self.before)
        target["page_data"][7]["keyframes"]["frame_data"][0]["frame_RGB"][0] = "#FFFF00"
        plan = partial.preview_plan(self.before, target, slots=[3], domains=["keys"])
        packets = [bytes.fromhex(data) for data in plan["candidateFramesHex"]]
        self.assertFalse(any(data[0] == 4 for data in packets))
        axis = [data for data in packets if data[0] == 5 and data[2] == 0]
        self.assertEqual(len(axis), 5)
        self.assertEqual({data[1] for data in axis}, {7})
        self.assertEqual([data[3] for data in axis], list(range(5)))
        rgb = b"".join(data[4:60] for data in axis)[:270]
        self.assertEqual(rgb[:3], bytes.fromhex("FFFF00"))
        self.assertEqual(plan["validDirectives"][7 * 4:7 * 4 + 4], [2, 2, 2, 1])

    def test_bad_scopes_and_unknown_formats_rejected(self):
        for slots, domains in [([], ["top"]), ([True], ["top"]), ([0], ["top"]), ([4], ["top"]), ([1, 1], ["top"]), ([2], []), ([2], ["top", "top"]), ([2], ["word"]), ([2], "top")]:
            with self.assertRaises(partial.PartialLightingError):
                partial.preview_plan(self.before, self.target, slots=slots, domains=domains)
        for mutation in [lambda c: c.__setitem__("page_num", 9), lambda c: c["page_data"][0].__setitem__("page_index", 1), lambda c: c["page_data"][6]["frames"].__setitem__("valid", 2), lambda c: c["page_data"][6]["frames"].__setitem__("frame_num", 256), lambda c: c["page_data"][6]["frames"].__setitem__("extraControl", 1)]:
            target = copy.deepcopy(self.target)
            mutation(target)
            with self.assertRaises(partial.PartialLightingError):
                partial.preview_plan(self.before, target, slots=[2], domains=["top"])

    def test_reserved_axis_and_partial_data_rejected(self):
        for position in partial.RESERVED_AXIS:
            target = copy.deepcopy(self.target)
            target["page_data"][6]["keyframes"]["frame_data"][0]["frame_RGB"][position] = "#FFFFFF"
            with self.assertRaises(partial.PartialLightingError):
                partial.preview_plan(self.before, target, slots=[2], domains=["top", "keys"])
        self.target["page_data"][6]["frames"]["frame_data"][0]["frame_RGB"].pop()
        with self.assertRaises(partial.PartialLightingError):
            self.plan()

    def test_noop_and_nan_rejected(self):
        with self.assertRaises(partial.PartialLightingError):
            partial.preview_plan(self.before, self.before, slots=[2], domains=["top"])
        self.target["other"] = float("nan")
        with self.assertRaises(partial.PartialLightingError):
            self.plan()

    def test_disabled_public_placeholder_is_preserved(self):
        for config in (self.before, self.target):
            config["page_data"][0]["frames"] = {"valid": 0, "frame_num": 0, "frame_data": [{"frame_index": 0, "frame_RGB": ["#000000"]}]}
            config["page_data"][0]["keyframes"] = {"valid": 0, "frame_num": 0, "frame_data": [{"frame_index": 0, "frame_RGB": ["#000000"]}]}
        plan = self.plan()
        self.assertEqual(plan["scope"]["changes"][0]["slot"], 2)

    def test_no_execute_or_transport_surface(self):
        self.assertFalse(hasattr(partial, "execute"))
        self.assertFalse(hasattr(partial, "dispatch"))
        source = (ROOT / "backend/r6_partial_lighting.py").read_text()
        self.assertNotIn("import serial", source)
        self.assertNotIn(".write(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
