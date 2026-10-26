#!/usr/bin/env python3
"""Fault-injected USB synchronization states; all ports and stores are synthetic."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("sync_test_fixtures", Path(__file__).with_name("backend-check.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
bridge = fixtures.bridge


class DeviceSyncStateChecks(fixtures.BackendChecks):
    def metadata(self, plan):
        return bridge.load_json(self.backend.state_dir / "plans" / plan["token"] / "plan.json")

    def fail_execute(self, plan):
        with self.assertRaises(bridge.BridgeError) as caught:
            self.backend.execute({"token": plan["token"], "confirmInitialization": True})
        return caught.exception

    def serial_fault(self, method, fail_when=lambda *args: True, error=None, short=None):
        original_factory = self.serial

        def factory(*args, **kwargs):
            serial = original_factory(*args, **kwargs)
            original = getattr(serial, method)

            def faulty(*values):
                if fail_when(*values):
                    if short is not None:
                        original(*values)  # The device may receive a partial write.
                        return short
                    raise error or OSError("synthetic serial fault")
                return original(*values)

            setattr(serial, method, faulty)
            return serial

        return patch.object(self.cli["cb_write"].serial, "Serial", factory)

    def assert_unknown(self, plan, stage, keymap="unknown"):
        metadata = self.metadata(plan)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["transferState"], stage)
        self.assertEqual(metadata["keymapVerification"], keymap)
        self.assertEqual(metadata["deviceState"], "unknown")
        self.assertTrue(metadata["deviceMayHaveChanged"])
        self.expect_error("baseline_result_unknown", lambda: self.backend.plan(self.payload()))
        self.assertEqual(self.recorded, [])

    def test_prepared_state_never_claims_device_change(self):
        plan = self.prepared()
        for key, value in bridge.sync_state().items():
            self.assertEqual(plan[key], value)
            self.assertEqual(self.metadata(plan)[key], value)
        self.assertEqual(self.sent, [])

    def test_serial_open_failure_keeps_old_baseline_usable(self):
        plan = self.prepared()
        with patch.object(self.cli["cb_write"].serial, "Serial", side_effect=OSError("port busy")):
            error = self.fail_execute(plan)
        self.assertEqual(error.details["transferState"], "not-started")
        self.assertEqual(error.details["deviceState"], "unchanged")
        self.assertFalse(error.details["deviceMayHaveChanged"])
        self.assertEqual(self.sent, [])
        self.backend.plan(self.payload())

    def test_serial_reset_failure_precedes_destructive_boundary(self):
        plan = self.prepared()
        with self.serial_fault("reset_input_buffer"):
            self.fail_execute(plan)
        self.assertEqual(self.metadata(plan)["transferState"], "not-started")
        self.assertEqual(self.sent, [])
        self.backend.plan(self.payload())

    def test_start_event_failure_is_not_a_device_write(self):
        plan = self.prepared()
        with patch.object(self.backend, "event", side_effect=RuntimeError("closed event stream")):
            self.fail_execute(plan)
        self.assertEqual(self.metadata(plan)["deviceState"], "unchanged")
        self.assertEqual(self.sent, [])
        self.backend.plan(self.payload())

    def test_durable_start_marker_failure_sends_nothing(self):
        plan = self.prepared()
        original = bridge.atomic_json

        def fail_start(path, value, **kwargs):
            if Path(path).name == "plan.json" and value.get("transferState") == "started":
                raise OSError("start marker unavailable")
            return original(path, value, **kwargs)

        with patch.object(bridge, "atomic_json", fail_start):
            self.fail_execute(plan)
        self.assertFalse(self.metadata(plan)["deviceMayHaveChanged"])
        self.assertEqual(self.sent, [])
        self.backend.plan(self.payload())

    def test_start_write_exception_blocks_old_led_baseline(self):
        plan = self.prepared()
        with self.serial_fault("write", lambda frame: frame[:2] == b"\x01\x05"):
            error = self.fail_execute(plan)
        self.assertTrue(error.details["deviceMayHaveChanged"])
        self.assert_unknown(plan, "started")

    def test_short_start_write_is_not_accepted(self):
        plan = self.prepared()
        with self.serial_fault("write", lambda frame: frame[:2] == b"\x01\x05", short=9):
            error = self.fail_execute(plan)
        self.assertEqual(error.code, "short_usb_write")
        self.assertEqual(len(self.sent), 1)
        self.assert_unknown(plan, "started")

    def test_bad_start_crc_blocks_old_led_baseline(self):
        plan = self.prepared()
        self.bad_start_crc = True
        self.assertEqual(self.fail_execute(plan).code, "start_ack_failed")
        self.assert_unknown(plan, "started")

    def test_data_write_interruption_blocks_old_led_baseline(self):
        plan = self.prepared()
        with self.serial_fault("write", lambda frame: frame[:2] not in (b"\x01\x05", b"\x01\x06")):
            self.fail_execute(plan)
        self.assert_unknown(plan, "started")

    def test_flush_failure_after_start_keeps_unknown_state(self):
        plan = self.prepared()
        with self.serial_fault("flush"):
            self.fail_execute(plan)
        self.assertEqual(len(self.sent), 1)
        self.assert_unknown(plan, "started")

    def test_short_end_write_is_not_accepted(self):
        plan = self.prepared()
        with self.serial_fault("write", lambda frame: frame[:2] == b"\x01\x06", short=10):
            error = self.fail_execute(plan)
        self.assertEqual(error.code, "short_usb_write")
        self.assert_unknown(plan, "started")

    def test_missing_commit_ack_distinguishes_sent_from_acknowledged(self):
        plan = self.prepared()
        self.bad_end_header = True
        error = self.fail_execute(plan)
        self.assertEqual(error.code, "end_ack_failed")
        self.assertFalse(error.details["deviceAck"])
        self.assertEqual(error.details["ledVerification"], "unknown")
        self.assert_unknown(plan, "sent")

    def test_keymap_mismatch_preserves_device_receipt_without_claiming_led_readback(self):
        plan = self.prepared()
        self.retry_mismatches = 3
        error = self.fail_execute(plan)
        self.assertEqual(error.code, "verification_failed")
        self.assertTrue(error.details["deviceAck"])
        self.assertEqual(error.details["ledVerification"], "protocol-ack-only")
        self.assert_unknown(plan, "acknowledged", "mismatch")

    def test_readback_transport_failure_is_unknown_not_mismatch(self):
        plan = self.prepared()
        original = self.backend.read_live

        def read(port):
            if self.after_write:
                raise OSError("readback cable disconnected")
            return original(port)

        with patch.object(self.backend, "read_live", read):
            self.fail_execute(plan)
        self.assert_unknown(plan, "acknowledged")

    def test_process_interrupt_leaves_durable_unknown_state(self):
        plan = self.prepared()
        with self.serial_fault("write", lambda frame: frame[:2] != b"\x01\x05", error=KeyboardInterrupt()), \
                self.assertRaises(KeyboardInterrupt):
            self.backend.execute({"token": plan["token"]})
        self.assert_unknown(plan, "started")

    def test_failed_report_does_not_hide_original_error_or_unlock_baseline(self):
        plan = self.prepared()
        self.bad_end_header = True
        original = bridge.atomic_json

        def fail_report(path, value, **kwargs):
            if Path(path).name == "plan.json" and value.get("status") == "failed":
                raise OSError("failure report unavailable")
            return original(path, value, **kwargs)

        with patch.object(bridge, "atomic_json", fail_report):
            error = self.fail_execute(plan)
        self.assertEqual(error.code, "end_ack_failed")
        self.assertIn("failure report unavailable", error.details["reportWarning"])
        self.assertEqual(self.metadata(plan)["status"], "executing")
        self.expect_error("baseline_result_unknown", lambda: self.backend.plan(self.payload()))

    def test_legacy_failed_record_is_conservative_even_when_target_equals_baseline(self):
        plan = self.prepared()
        metadata = self.metadata(plan)
        for key in bridge.sync_state():
            metadata.pop(key)
        metadata.update(status="failed", targetHash=metadata["storedBaselineHash"])
        bridge.atomic_json(self.backend.state_dir / "plans" / plan["token"] / "plan.json", metadata)
        self.expect_error("baseline_result_unknown", lambda: self.backend.plan(self.payload()))
        self.assertEqual(bridge.recorded_sync_state(metadata)["transferState"], "unknown")

    def test_new_not_started_record_cannot_hide_an_older_unknown_write(self):
        old, newer = self.prepared(), self.prepared()
        old_metadata = self.metadata(old)
        old_metadata.update(bridge.sync_state("started"), status="failed")
        bridge.atomic_json(self.backend.state_dir / "plans" / old["token"] / "plan.json", old_metadata)
        new_metadata = self.metadata(newer)
        new_metadata.update(bridge.sync_state(), status="failed", failedTimestamp=bridge.time.time()+10)
        bridge.atomic_json(self.backend.state_dir / "plans" / newer["token"] / "plan.json", new_metadata)
        self.expect_error("baseline_result_unknown", lambda: self.backend.plan(self.payload()))

    def test_same_target_failed_new_record_cannot_reuse_baseline(self):
        plan = self.prepared()
        metadata = self.metadata(plan)
        metadata.update(bridge.sync_state("sent"), status="failed", targetHash=metadata["storedBaselineHash"])
        bridge.atomic_json(self.backend.state_dir / "plans" / plan["token"] / "plan.json", metadata)
        self.expect_error("baseline_result_unknown", lambda: self.backend.plan(self.payload()))

    def test_success_keeps_legacy_fields_and_separates_led_ack(self):
        plan = self.prepared()
        report = self.backend.execute({"token": plan["token"]})
        self.assertTrue(report["success"] and report["deviceAck"] and report["keymapMatch"] and report["stateStored"])
        for key, value in bridge.sync_state("acknowledged", "verified").items():
            self.assertEqual(report[key], value)
            self.assertEqual(self.metadata(plan)[key], value)
        self.assertEqual(report["ledSource"], "last-written")

    def test_history_snapshot_exposes_failure_without_becoming_a_success_report(self):
        plan = self.prepared()
        self.bad_end_header = True
        self.fail_execute(plan)
        item = next(item for item in self.backend.history({})["history"] if plan["token"] in item["id"])
        self.assertEqual(item["snapshotScope"], "before-write")
        self.assertEqual(item["attemptStatus"], "failed")
        self.assertEqual(item["transferState"], "sent")
        self.assertEqual(item["deviceState"], "unknown")
        self.assertNotIn("success", item)

    def test_initialization_open_failure_does_not_leave_permanent_marker(self):
        plan = self.initialization_prepared()
        with patch.object(self.cli["cb_write"].serial, "Serial", side_effect=OSError("port unavailable")):
            self.fail_execute(plan)
        self.assertFalse(self.backend.initialization_marker("AM01R6").exists())
        self.assertFalse(self.metadata(plan)["deviceMayHaveChanged"])
        self.backend.initializePlan(self.initialization_payload())

    def test_initialization_start_plan_failure_removes_only_own_unwritten_marker(self):
        plan = self.initialization_prepared()
        original = bridge.atomic_json

        def fail_start(path, value, **kwargs):
            if Path(path).name == "plan.json" and value.get("transferState") == "started":
                raise OSError("cannot save started plan")
            return original(path, value, **kwargs)

        with patch.object(bridge, "atomic_json", fail_start):
            self.fail_execute(plan)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.backend.initialization_marker("AM01R6").exists())
        self.backend.initializePlan(self.initialization_payload())


if __name__ == "__main__":
    suite = unittest.TestSuite(DeviceSyncStateChecks(name) for name in sorted(DeviceSyncStateChecks.__dict__)
                               if name.startswith("test_"))
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
