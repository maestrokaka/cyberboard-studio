"""Offline wire and state checks for R6 audio; no device or microphone access."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "vendor/cyberboard-cli/cyberboard/_tools")]
import r6_audio as audio
import cb_protocol as protocol


class Stream:
    def __init__(self, replies=(), short=False):
        self.data = bytearray(b"".join(replies)); self.frames = []; self.short = short
    def write(self, data): self.frames.append(data); return 32 if self.short else len(data)
    def read(self, size):
        data = bytes(self.data[:min(size, 7)]); del self.data[:len(data)]; return data
    def flush(self): pass


class Bridge:
    def __init__(self, folder, product="AM01R6"):
        self.state_dir = Path(folder)
        self.identity = SimpleNamespace(port="FAKE", product_id=product, version="fixture-v1")
        self.cli = {"cb_protocol": protocol}
    def discover(self, payload): return self.identity
    def device_dict(self, value): return {"port": value.port, "productId": value.product_id, "firmware": value.version, "lastSeen": "variable"}
    def event(self, *args, **kwargs): pass


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.bridge = Bridge(self.temporary.name)
        self.expected = self.bridge.device_dict(self.bridge.identity)
    def set_payload(self, setting="mic_direction", value=21):
        return {"setting": setting, "value": value, "expectedDevice": self.expected}
    @contextlib.contextmanager
    def wire(self, stream):
        @contextlib.contextmanager
        def serial(*args): yield stream
        with patch.object(audio, "_serial", serial): yield
    def test_status_does_not_send_commands_or_claim_live_values(self):
        with patch.object(audio, "_serial", side_effect=AssertionError("must not open")):
            result = audio.status(self.bridge, {})
        self.assertTrue(result["supportsAudio"]); self.assertFalse(result["canReadSettings"])
        self.assertTrue(all(v is None for v in result["settings"].values()))
    def test_all_13_ui_options_use_only_short_set_commands(self):
        for setting, (command, values) in audio.OPTIONS.items():
            for value in values:
                stream = Stream([protocol.build_frame(7, command, bytes([value, 0]))])
                with self.wire(stream): result = audio.set_setting(self.bridge, self.set_payload(setting, value))
                self.assertEqual(stream.frames, [protocol.build_frame(7, command, bytes([value]))])
                self.assertEqual(result["verification"], "set_echo")
                self.assertFalse(result["acousticVerified"])
    def test_decimal_direction_is_not_hex_21(self):
        with self.assertRaises(audio.R6AudioError): audio.set_setting(self.bridge, self.set_payload(value=0x21))
    def test_rejects_unknown_setting_bool_and_invalid_mode(self):
        for setting, value in [("gain", 1), ("speaker", True), ("mic_tone", 0), ("noise_reduction", 3)]:
            with self.assertRaises(audio.R6AudioError): audio.set_setting(self.bridge, self.set_payload(setting, value))
    def test_changed_firmware_is_refused_before_sending(self):
        self.expected["firmware"] = "old"
        with patch.object(audio, "_serial", side_effect=AssertionError("must not open")), self.assertRaises(audio.R6AudioError):
            audio.set_setting(self.bridge, self.set_payload())
    def test_r4_is_never_sent_r6_audio_commands(self):
        self.bridge.identity.product_id = "CB04"
        with self.assertRaises(audio.R6AudioError): audio.set_setting(self.bridge, self.set_payload())
    def test_echo_mismatch_leaves_local_history_unknown(self):
        stream = Stream([protocol.build_frame(7, 10, bytes([32, 0]))])
        with self.wire(stream), self.assertRaises(audio.R6AudioError): audio.set_setting(self.bridge, self.set_payload())
        record = json.loads(audio._history_path(self.bridge).read_text())
        self.assertEqual(record["settings"]["mic_direction"]["state"], "unknown")
    def test_nonzero_mic_status_is_not_success(self):
        stream = Stream([protocol.build_frame(7, 10, bytes([21, 1]))])
        with self.wire(stream), self.assertRaises(audio.R6AudioError): audio.set_setting(self.bridge, self.set_payload())
    def test_crc_error_is_not_success(self):
        corrupt = bytearray(protocol.build_frame(7, 10, bytes([21, 0]))); corrupt[-1] ^= 1
        with self.wire(Stream([bytes(corrupt)])), self.assertRaises(audio.R6AudioError): audio.set_setting(self.bridge, self.set_payload())
    def test_short_write_is_unknown(self):
        with self.assertRaises(audio.R6AudioError) as error: audio.request(self.bridge, Stream(short=True), 10, 21)
        self.assertEqual(error.exception.details["state"], "unknown")
    def test_unrelated_frames_skipped_with_bounded_wait(self):
        stream = Stream([protocol.build_frame(1, 2), protocol.build_frame(7, 10, bytes([21, 0]))])
        response = audio.request(self.bridge, stream, 10, 21)
        self.assertEqual(response[2], 21)
    def test_timeout_does_not_retry_mutating_command(self):
        ticks = iter([0, 0.1, 3])
        stream = Stream()
        with self.assertRaises(audio.R6AudioError): audio.request(self.bridge, stream, 10, 21, clock=lambda: next(ticks))
        self.assertEqual(len(stream.frames), 1)
    def test_history_is_bound_to_firmware_and_is_not_live_state(self):
        audio._remember(self.bridge, self.expected, "speaker", 3, "acknowledged")
        changed_time = {**self.expected, "lastSeen": "later"}
        self.assertEqual(audio._history(self.bridge, changed_time)["speaker"]["value"], 3)
        self.assertEqual(audio._history(self.bridge, {**changed_time, "firmware": "different"}), {})
        self.assertIsNone(audio.status(self.bridge, {})["settings"]["speaker"])
    def test_calibration_requires_explicit_native_preparation(self):
        for payload in [{}, {"confirmCalibration": True}, {"nativeAudioActive": True}]:
            with self.assertRaises(audio.R6AudioError): audio.calibrate(self.bridge, payload)
    def test_calibration_wire_sequence_and_little_endian_impedance(self):
        stream = Stream([protocol.build_frame(7, 6, bytes([3])), protocol.build_frame(7, 4, bytes([1, 0, 0, 22, 0, 23]))])
        with self.wire(stream):
            result = audio.calibrate(self.bridge, {"confirmCalibration": True, "nativeAudioActive": True, "expectedDevice": self.expected}, sleep=lambda _: None)
        self.assertEqual([f[:2] for f in stream.frames], [b"\x07\x07", b"\x07\x06", b"\x07\x04"])
        self.assertEqual((result["leftOhms"], result["rightOhms"]), (5.5, 5.75)); self.assertTrue(result["passed"])
        self.assertFalse(result["testModeExitConfirmed"])


if __name__ == "__main__": unittest.main(verbosity=2)
