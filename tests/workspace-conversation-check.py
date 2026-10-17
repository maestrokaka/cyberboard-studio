"""Offline RC workspace persistence, migration and independent slot records.

All files are temporary; CLI/USB/model access is forbidden by the fixture.
"""
import base64
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import bridge
from ai_images import normalize
from PIL import Image

STAMP = "2026-10-17T09:00:00Z"


class NoCLI(dict):
    def __getitem__(self, item):
        raise AssertionError("Workspace operations must not access CLI/USB")


class WorkspaceConversationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cyberboard-rc-workspace-")
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.backend = self.restart()
        self.image = self.jpeg()

    def tearDown(self):
        self.temp.cleanup()

    def restart(self):
        return bridge.Bridge(self.state, ROOT, NoCLI(), "offline", lambda _: None)

    def jpeg(self):
        raw = io.BytesIO()
        Image.new("RGB", (8, 8), "#0088FF").save(raw, "PNG")
        image = normalize(raw.getvalue(), "参考图.png")
        return {k: image[k] for k in ("name", "dataUrl")}

    def design(self, identity="work-blue"):
        keys = ["#FF0000"] * 90
        for i in bridge.RESERVED_LEDS:
            keys[i] = "#000000"
        return {"id": identity, "name": "蓝光", "description": "蓝色顶部与红色轴灯", "speed_ms": 40,
                "frame_count": 2, "palette": ["#0000FF", "#FF0000"],
                "frames": [["#0000FF"] * 200, ["#000088"] * 200], "keyframes": [keys, keys.copy()]}

    def conversation(self, identity="conversation-one"):
        return {"id": identity, "title": "蓝光创作", "createdAt": STAMP, "updatedAt": STAMP,
                "draft": {"brief": "轴灯改成黄色", "images": [copy.deepcopy(self.image)],
                          "scope": "keys", "baseVersionId": "version-one"},
                "versions": [{"id": "version-one", "label": "V1", "createdAt": STAMP,
                              "design": self.design(), "provider": "kimi-code", "model": "k3",
                              "scope": "both", "savedDesignId": "work-blue", "changeSummary": "第一版"},
                             {"id": "version-two", "label": "V2", "createdAt": STAMP,
                              "design": self.design("work-yellow"), "provider": "kimi-code", "model": "k3",
                              "scope": "keys", "baseVersionId": "version-one", "changeSummary": "轴灯改黄"}],
                "selectedVersionId": "version-two", "turns": [
                    {"id": "turn-user", "role": "user", "text": "根据参考图制作", "createdAt": STAMP,
                     "images": [copy.deepcopy(self.image)], "requestId": "mock-request"},
                    {"id": "turn-assistant", "role": "assistant", "text": "灯效已完成", "createdAt": STAMP,
                     "versionId": "version-one", "provider": "kimi-code", "model": "k3"}]}

    def workspace(self):
        return {"designs": [self.design()], "pending": [{"slot": 3, "designId": "work-blue",
                                                           "brightness": 90, "speedMs": 40}],
                "trash": [], "removedBuiltinIds": ["deleted-preset"], "selectedId": "work-blue",
                "targetSlot": 3, "brightness": 100, "speedMs": 40, "palette": "original", "brief": "旧输入",
                "exportFormat": "design", "previewAppearanceId": "r6-vision",
                "conversations": [self.conversation()], "activeConversationId": "conversation-one"}

    def expect_rejected(self, payload, codes=("invalid_workspace",)):
        before = (self.state / "workspace.json").read_bytes() if (self.state / "workspace.json").exists() else None
        with self.assertRaises(bridge.BridgeError) as caught:
            self.backend.saveWorkspace(payload)
        self.assertIn(caught.exception.code, codes)
        if before is not None:
            self.assertEqual((self.state / "workspace.json").read_bytes(), before)
        else:
            self.assertFalse((self.state / "workspace.json").exists())

    def test_save_restart_preserves_versions_images_drafts_and_all_slot_state(self):
        value = self.workspace(); original = copy.deepcopy(value)
        result = self.backend.saveWorkspace(value)
        self.assertTrue(result["saved"])
        saved = json.loads((self.state / "workspace.json").read_bytes())
        self.assertEqual(saved["version"], 2)
        restored, warning = self.restart().load_workspace()
        self.assertIsNone(warning)
        for field, expected in original.items():
            self.assertEqual(restored[field], expected)
        self.assertEqual(value, original, "Normalizing and validating must not mutate caller state")
        self.assertEqual(result["pendingCount"], 1)

    def test_new_or_switched_conversation_never_clears_delivery_drafts(self):
        value = self.workspace()
        empty = {"id": "new-dialog", "title": "新对话", "createdAt": STAMP, "updatedAt": STAMP,
                 "draft": {"brief": "未发送描述", "images": [], "scope": "both", "baseVersionId": None},
                 "turns": [], "versions": [], "selectedVersionId": None}
        self.backend.saveWorkspace(value)
        for active in ("new-dialog", "conversation-one", None):
            value["conversations"] = [value["conversations"][0], empty]
            value["activeConversationId"] = active
            self.backend.saveWorkspace(value)
            restored, warning = self.restart().load_workspace()
            self.assertIsNone(warning)
            self.assertEqual(restored["pending"], value["pending"])
            self.assertEqual(restored["selectedId"], "work-blue")
            self.assertEqual(restored["designs"], value["designs"])

    def test_v1_upgrade_retains_original_content_and_independent_existing_records(self):
        value = self.workspace()
        value.pop("conversations"); value.pop("activeConversationId")
        value.update(version=1, savedAt=STAMP)
        self.state.mkdir()
        location = self.state / "workspace.json"
        original = json.dumps(value, ensure_ascii=False, indent=2).encode()
        location.write_bytes(original)
        restored, warning = self.restart().load_workspace()
        self.assertIsNone(warning)
        self.assertEqual(restored["conversations"], [])
        self.assertIsNone(restored["activeConversationId"])
        restored["conversations"] = [self.conversation()]
        restored["activeConversationId"] = "conversation-one"
        self.backend.saveWorkspace(restored)
        backups = [p for p in self.state.rglob("*") if p.is_file() and p != location
                   and json.loads(p.read_bytes()) == value]
        self.assertEqual(len(backups), 1, "First v1→v2 save must retain one complete migration backup")
        self.assertEqual(json.loads(location.read_bytes())["version"], 2)
        for field in ("designs", "pending", "removedBuiltinIds", "selectedId"):
            self.assertEqual(json.loads(location.read_bytes())[field], value[field])
        before = backups[0].read_bytes()
        restored["brief"] = "后续更新"
        self.backend.saveWorkspace(restored)
        self.assertEqual(backups[0].read_bytes(), before)

    def test_duplicate_version_design_hash_is_valid_but_duplicate_version_id_is_not(self):
        value = self.workspace()
        value["conversations"][0]["versions"][1]["design"] = copy.deepcopy(value["conversations"][0]["versions"][0]["design"])
        self.backend.saveWorkspace(value)
        value["conversations"][0]["versions"][1]["id"] = "version-one"
        self.expect_rejected(value)

    def test_dangling_selected_draft_turn_and_base_references_are_rejected_atomically(self):
        self.backend.saveWorkspace(self.workspace())
        for path in ("active", "selected", "draft", "turn-version", "turn-base", "version-base"):
            value = self.workspace(); c = value["conversations"][0]
            if path == "active": value["activeConversationId"] = "missing"
            elif path == "selected": c["selectedVersionId"] = "missing"
            elif path == "draft": c["draft"]["baseVersionId"] = "missing"
            elif path == "turn-version": c["turns"][1]["versionId"] = "missing"
            elif path == "turn-base": c["turns"][0]["baseVersionId"] = "missing"
            else: c["versions"][1]["baseVersionId"] = "missing"
            with self.subTest(reference=path): self.expect_rejected(value)

    def test_empty_and_duplicate_record_ids_reject_without_losing_saved_work(self):
        self.backend.saveWorkspace(self.workspace())
        for target in ("conversation", "version", "turn"):
            for invalid in ("", "   ", "x" * 129):
                value = self.workspace(); c = value["conversations"][0]
                record = c if target == "conversation" else c["versions"][0] if target == "version" else c["turns"][0]
                record["id"] = invalid
                with self.subTest(target=target, invalid=len(invalid)): self.expect_rejected(value)
        value = self.workspace(); value["conversations"].append(copy.deepcopy(value["conversations"][0]))
        self.expect_rejected(value)
        value = self.workspace(); c = value["conversations"][0]; c["turns"].append(copy.deepcopy(c["turns"][0]))
        self.expect_rejected(value)

    def test_invalid_or_remote_images_and_private_image_fields_are_rejected(self):
        self.backend.saveWorkspace(self.workspace())
        for image in ({"name": "remote", "dataUrl": "https://example.invalid/image.jpg"},
                      {"dataUrl": "data:image/jpeg;base64,!!!"},
                      {"dataUrl": "data:image/jpeg;base64,bm90LWltYWdl"},
                      {**self.image, "path": "/private/raw-file"},
                      {**self.image, "original": "private-raw-bytes"},
                      {"dataUrl": "data:image/jpeg;base64," + "A" * 560001}):
            value = self.workspace(); value["conversations"][0]["draft"]["images"] = [image]
            self.expect_rejected(value)
        value = self.workspace(); value["conversations"][0]["turns"][0]["images"] = [self.image] * 4
        self.expect_rejected(value)

    def test_image_pixels_are_re_normalized_without_retaining_exif(self):
        raw = io.BytesIO(); exif = Image.Exif(); exif[270] = "private-exif-secret"
        Image.new("RGB", (8, 8), "#0088FF").save(raw, "JPEG", exif=exif)
        image = {"name": "clean.jpg", "dataUrl": "data:image/jpeg;base64," + base64.b64encode(raw.getvalue()).decode()}
        value = self.workspace(); value["conversations"][0]["draft"]["images"] = [image]
        self.backend.saveWorkspace(value)
        restored, warning = self.restart().load_workspace()
        self.assertIsNone(warning)
        saved = restored["conversations"][0]["draft"]["images"][0]["dataUrl"]
        pixels = base64.b64decode(saved.split(",", 1)[1])
        self.assertNotIn(b"private-exif-secret", pixels)
        with Image.open(io.BytesIO(pixels)) as source:
            self.assertFalse(source.getexif())
        self.assertEqual(value["conversations"][0]["draft"]["images"][0], image)

    def test_top_level_device_metadata_is_not_saved_and_credentials_fail_closed(self):
        value = self.workspace()
        value.update(device={"productId": "private-device"}, current="private-device-current", meta="private-device-meta",
                     key_layer="private-keymap", apiKey="ignored-top-level-secret")
        self.backend.saveWorkspace(value)
        raw = (self.state / "workspace.json").read_text()
        self.assertNotIn("private-device", raw)
        self.assertNotIn("private-keymap", raw)
        self.assertNotIn("ignored-top-level-secret", raw)
        for place in ("design-field", "design-text", "turn-text", "draft-text"):
            value = self.workspace(); c = value["conversations"][0]
            if place == "design-field": c["versions"][0]["design"]["authorization"] = "mock-secret"
            elif place == "design-text": c["versions"][0]["design"]["description"] = "sk-" + "offlineCredential" * 3
            elif place == "turn-text": c["turns"][0]["text"] = "sk-cp-" + "offlineCredential" * 3
            else: c["draft"]["brief"] = "sk-" + "offlineCredential" * 3
            with self.subTest(place=place): self.expect_rejected(value, ("workspace_credentials",))

    def test_capacity_limits_are_explicit_and_previous_workspace_survives(self):
        self.backend.saveWorkspace(self.workspace())
        for target, number in (("conversations", 21), ("versions", 13), ("turns", 61)):
            value = self.workspace(); c = value["conversations"][0]
            if target == "conversations":
                value[target] = [{**copy.deepcopy(c), "id": "c-" + str(i)} for i in range(number)]
            elif target == "versions":
                c[target] = [{**copy.deepcopy(c[target][0]), "id": "v-" + str(i)} for i in range(number)]
            else:
                c[target] = [{**copy.deepcopy(c[target][0]), "id": "t-" + str(i)} for i in range(number)]
            with self.subTest(target=target): self.expect_rejected(value, ("workspace_limit",))
        with patch.object(bridge, "MAX_WORKSPACE_BYTES", 2048):
            self.expect_rejected(self.workspace(), ("workspace_too_large",))
        oversized = self.state / "workspace.json"
        oversized.write_bytes(b" " * 8193)
        with patch.object(bridge, "MAX_WORKSPACE_BYTES", 8192):
            loaded, warning = self.restart().load_workspace()
        self.assertIsNone(loaded)
        self.assertTrue(warning)
        self.assertEqual(oversized.stat().st_size, 8193)

    def test_exact_record_limits_fit_and_real_32_mib_envelope_is_enforced(self):
        value = self.workspace(); original = value["conversations"][0]
        original["versions"] = [{**copy.deepcopy(original["versions"][0]), "id": "v-" + str(i)} for i in range(12)]
        original["selectedVersionId"] = "v-11"
        original["draft"]["baseVersionId"] = "v-11"
        original["turns"] = [{**copy.deepcopy(original["turns"][0]), "id": "t-" + str(i)} for i in range(60)]
        value["conversations"] = [{**copy.deepcopy(original), "id": "c-" + str(i)} for i in range(20)]
        value["activeConversationId"] = "c-0"
        self.backend.saveWorkspace(value)
        restored, warning = self.restart().load_workspace()
        self.assertIsNone(warning)
        self.assertEqual(len(restored["conversations"]), 20)
        self.assertEqual(len(restored["conversations"][0]["versions"]), 12)
        self.assertEqual(len(restored["conversations"][0]["turns"]), 60)
        self.assertEqual(bridge.MAX_WORKSPACE_BYTES, 32 * 1024 * 1024)
        too_large = self.workspace()
        too_large["designs"][0]["untrustedLargeMetadata"] = "x" * bridge.MAX_WORKSPACE_BYTES
        self.expect_rejected(too_large, ("workspace_too_large",))

    def test_turn_and_version_scopes_cannot_restore_an_unrecognized_operation(self):
        self.backend.saveWorkspace(self.workspace())
        for record in ("turn", "version", "draft"):
            value = self.workspace(); c = value["conversations"][0]
            selected = c["turns"][0] if record == "turn" else c["versions"][0] if record == "version" else c["draft"]
            selected["scope"] = "device-write"
            with self.subTest(record=record): self.expect_rejected(value)

    def test_failed_atomic_write_does_not_erase_previous_workspace_or_leave_temp(self):
        self.backend.saveWorkspace(self.workspace())
        location = self.state / "workspace.json"; before = location.read_bytes()
        value = self.workspace(); value["conversations"][0]["title"] = "新标题"
        with patch.object(Path, "replace", side_effect=OSError("offline simulated disk failure")):
            with self.assertRaises(OSError): self.backend.saveWorkspace(value)
        self.assertEqual(location.read_bytes(), before)
        self.assertEqual(list(self.state.glob(".*.tmp")), [])

    def test_damaged_json_bad_version_or_invalid_records_can_recover_after_private_backup(self):
        original_values = [b'{invalid JSON\x00private-legacy-bytes', b'["bad-root"]',
                           json.dumps({"version": "damaged-version"}).encode(),
                           json.dumps({"version": True}).encode(),
                           json.dumps({"version": 2, "conversations": [{"id": "incomplete"}]}).encode()]
        self.state.mkdir()
        location = self.state / "workspace.json"
        for raw in original_values:
            with self.subTest(raw=raw[:24]):
                location.write_bytes(raw)
                loaded, warning = self.restart().load_workspace()
                self.assertIsNone(loaded)
                self.assertTrue(warning)
                self.assertEqual(location.read_bytes(), raw)
                self.assertTrue(self.backend.saveWorkspace(self.workspace())["saved"])
                backups = [p for p in self.state.glob("workspace-recovery-*.json") if p.read_bytes() == raw]
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
                loaded, warning = self.restart().load_workspace()
                self.assertIsNone(warning)
                self.assertEqual(loaded["pending"], self.workspace()["pending"])
                # Reintroducing the same bad store must reuse its exact snapshot.
                location.write_bytes(raw)
                self.backend.saveWorkspace(self.workspace())
                self.assertEqual(len([p for p in self.state.glob("workspace-recovery-*.json") if p.read_bytes() == raw]), 1)

    def test_unreadable_backup_failure_never_overwrites_the_original(self):
        self.state.mkdir()
        location = self.state / "workspace.json"; original = b'{damaged private data'
        location.write_bytes(original)
        with patch.object(Path, "replace", side_effect=OSError("offline backup failure")):
            with self.assertRaises(bridge.BridgeError) as caught:
                self.backend.saveWorkspace(self.workspace())
        self.assertEqual(caught.exception.code, "workspace_recovery_failed")
        self.assertEqual(location.read_bytes(), original)
        self.assertEqual(list(self.state.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
