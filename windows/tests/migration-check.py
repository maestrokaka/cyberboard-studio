#!/usr/bin/env python3
"""Offline migration checks. No device enumeration or USB actions are allowed."""
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT.parent / "vendor" / "cyberboard-cli"
if (VENDOR / "cyberboard").is_dir():
    sys.path.insert(0, str(VENDOR))
spec = importlib.util.spec_from_file_location("studio_migration", ROOT / "migrate-config.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
bridge = migration.load_bridge()


class MigrationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-migration-offline-")
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"CYBERBOARD_DATA_DIR": str(self.directory / "目标 当前库")})
        self.env.start()
        self.cli, _ = bridge.load_cli()
        self.source = self.directory / "原配置 带空格" / "AM01R6"
        self.source.mkdir(parents=True)
        black = lambda count: {"valid": 1, "frame_num": 1,
                               "frame_data": [{"frame_index": 0, "frame_RGB": ["#000000"] * count}]}
        self.config = {"page_num": 8, "page_data": [
            {"valid": 1, "page_index": i, "lightness": 100, "speed_ms": 40,
             "color": {"default": False, "back_rgb": "#000000", "rgb": "#000000"},
             "word_page": {"valid": 0, "word_len": 0, "unicode": []},
             "frames": black(200), "keyframes": black(90), "//": "此前写入的灯效"}
            for i in range(8)], "key_layer": {"valid": 1, "layer_num": 7,
            "layer_data": [{"layer": ["#00070004"] * 200} for _ in range(7)]},
            "exchange_num": 0, "exchange_key": [], "swap_key_num": 0, "swap_key": [],
            "opaqueExtension": {"中文": "完整保留"}}
        self.meta = {"product_id": "AM01R6", "version": "test-r6", "last_seen": "2026-10-12T02:00:00+00:00"}
        self.write_sources()
        self.device_actions = [patch.object(self.cli["cb_device"], "candidate_ports", side_effect=AssertionError("USB enumeration")),
                               patch.object(self.cli["cb_device"], "probe", side_effect=AssertionError("USB probe")),
                               patch.object(self.cli["cb_read"], "_drain", side_effect=AssertionError("USB read")),
                               patch.object(self.cli["cb_write"].serial, "Serial", side_effect=AssertionError("USB write")),
                               patch.object(self.cli["cb_store"], "save_current", side_effect=AssertionError("fabricated current metadata")),
                               patch.object(self.cli["cb_store"], "record_seen", side_effect=AssertionError("fabricated last_seen"))]
        for guard in self.device_actions:
            guard.start()

    def tearDown(self):
        for guard in reversed(self.device_actions):
            guard.stop()
        self.env.stop()
        self.temp.cleanup()

    def write_sources(self):
        (self.source / "current.json").write_text(json.dumps(self.config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.source / "meta.json").write_text(json.dumps(self.meta, ensure_ascii=False) + "\n", encoding="utf-8")
        for path in (self.source / "current.json", self.source / "meta.json"):
            os.utime(path, ns=(1_792_000_000_000_000_000, 1_792_000_000_123_000_000))

    @property
    def target(self):
        return self.cli["cb_store"].device_dir("AM01R6")

    def run_migration(self, **kwargs):
        return migration.migrate(kwargs.pop("source", self.source), bridge_module=bridge, cli=self.cli, **kwargs)

    def test_unicode_paths_exact_bytes_mtimes_and_no_usb(self):
        (self.source / ".lock").write_bytes(b"source lock must not be copied")
        (self.source / "history").mkdir()
        (self.source / "history" / "private.json").write_text("{}")
        result = self.run_migration()
        self.assertEqual(result["device"], "AM01R6")
        self.assertFalse(result["usbTouched"])
        for name in ("current.json", "meta.json"):
            self.assertEqual((self.target / name).read_bytes(), (self.source / name).read_bytes())
            self.assertEqual((self.target / name).stat().st_mtime_ns, (self.source / name).stat().st_mtime_ns)
        self.assertFalse((self.target / "history").exists())
        self.assertNotEqual((self.target / ".lock").read_bytes(), (self.source / ".lock").read_bytes())

    def test_current_file_parameter_and_requested_identity(self):
        result = self.run_migration(source=self.source / "current.json", requested_device="AM01R6")
        self.assertGreater(result["totalFrames"], 0)

    def test_existing_current_is_never_overwritten(self):
        self.target.mkdir(parents=True)
        (self.target / "current.json").write_text('{"original":true}')
        with self.assertRaisesRegex(migration.MigrationError, "不会覆盖"):
            self.run_migration()
        self.assertEqual((self.target / "current.json").read_text(), '{"original":true}')

    def test_untrusted_folder_cannot_be_given_a_new_identity(self):
        (self.source / "meta.json").unlink()
        untrusted = self.source.with_name("unknown")
        self.source.rename(untrusted)
        with self.assertRaisesRegex(migration.MigrationError, "无法确认"):
            self.run_migration(source=untrusted, requested_device="AM01R6")
        self.assertFalse(self.target.exists())

    def test_metadata_directory_and_requested_device_mismatch_rejected(self):
        self.meta["product_id"] = "CB04"
        self.write_sources()
        with self.assertRaisesRegex(migration.MigrationError, "不一致"):
            self.run_migration()
        self.meta["product_id"] = "AM01R6"
        self.write_sources()
        with self.assertRaisesRegex(migration.MigrationError, "不一致"):
            self.run_migration(requested_device="CB04")
        self.assertFalse(self.target.exists())

    def test_dongle_metadata_rejected(self):
        self.meta["product_id"] = "CB04_DONGLE"
        self.write_sources()
        with self.assertRaises(migration.MigrationError):
            self.run_migration()
        self.assertFalse(self.target.exists())

    def test_missing_metadata_allowed_only_with_real_device_directory(self):
        (self.source / "meta.json").unlink()
        self.run_migration()
        self.assertTrue((self.target / "current.json").is_file())
        self.assertFalse((self.target / "meta.json").exists())

    def test_optional_metadata_raw_or_canonical_checksum_must_match(self):
        for canonical in (False, True):
            with self.subTest(canonical=canonical):
                expected = bridge.digest(self.config) if canonical else hashlib.sha256((self.source / "current.json").read_bytes()).hexdigest()
                self.meta["config_sha256"] = expected
                self.write_sources()
                self.run_migration()
                (self.target / "current.json").unlink()
        self.meta["config_sha256"] = "0" * 64
        self.write_sources()
        with self.assertRaisesRegex(migration.MigrationError, "SHA-256 不一致"):
            self.run_migration()
        self.assertFalse((self.target / "current.json").exists())

    def test_partial_keymap_and_invalid_pixels_rejected_before_destination_edit(self):
        self.config["key_layer"]["layer_data"][0]["layer"].pop()
        self.write_sources()
        with self.assertRaisesRegex(migration.MigrationError, "完整配置"):
            self.run_migration()
        self.assertFalse(self.target.exists())
        self.config["key_layer"]["layer_data"][0]["layer"].append("#00070004")
        self.config["page_data"][5]["frames"]["frame_data"][0]["frame_RGB"].pop()
        self.write_sources()
        with self.assertRaisesRegex(migration.MigrationError, "完整配置"):
            self.run_migration()
        self.assertFalse(self.target.exists())

    def test_encoded_crc_failure_rejected_before_copy(self):
        with patch.object(self.cli["cb_protocol"], "crc_ok", return_value=False):
            with self.assertRaisesRegex(migration.MigrationError, "完整配置"):
                self.run_migration()
        self.assertFalse(self.target.exists())

    def test_nonfinite_json_and_missing_cli_report_readable_errors(self):
        self.config["opaqueExtension"]["number"] = float("nan")
        self.write_sources()
        with self.assertRaisesRegex(migration.MigrationError, "UTF-8 JSON"):
            self.run_migration()
        with patch.object(bridge, "load_cli", side_effect=bridge.BridgeError("cli_unavailable", "CLI 缺失")):
            with self.assertRaisesRegex(migration.MigrationError, "CLI 缺失"):
                migration.migrate(self.source, bridge_module=bridge)
        self.assertFalse(self.target.exists())

    def test_commit_failure_restores_original_metadata_without_half_baseline(self):
        self.target.mkdir(parents=True)
        prior = b'{"product_id":"AM01R6","last_seen":"old"}\n'
        (self.target / "meta.json").write_bytes(prior)
        os.utime(self.target / "meta.json", ns=(1_780_000_000_000_000_000, 1_780_000_000_000_000_000))
        original_replace = os.replace

        def fail_current(source, destination):
            if Path(destination).name == "current.json":
                raise OSError("simulated disk error")
            return original_replace(source, destination)

        with patch.object(migration.os, "replace", side_effect=fail_current):
            with self.assertRaises(OSError):
                self.run_migration()
        self.assertFalse((self.target / "current.json").exists())
        self.assertEqual((self.target / "meta.json").read_bytes(), prior)
        self.assertEqual((self.target / "meta.json").stat().st_mtime_ns, 1_780_000_000_000_000_000)
        self.assertEqual(list(self.target.glob("*.tmp")), [])

    def test_new_metadata_rolled_back_if_current_commit_fails(self):
        original_replace = os.replace
        def fail_current(source, destination):
            if Path(destination).name == "current.json":
                raise OSError("simulated disk error")
            return original_replace(source, destination)
        with patch.object(migration.os, "replace", side_effect=fail_current):
            with self.assertRaises(OSError):
                self.run_migration()
        self.assertFalse((self.target / "current.json").exists())
        self.assertFalse((self.target / "meta.json").exists())

    def test_interactive_cancel_and_readable_failure_exit_codes(self):
        with patch("builtins.input", return_value=""), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(migration.main([]), 2)
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(migration.main(["--source", str(self.directory / "missing")]), 1)
            self.assertIn("迁移未完成", err.getvalue())
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
