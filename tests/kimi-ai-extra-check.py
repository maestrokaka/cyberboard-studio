"""Additional offline protocol edge cases; credentials and network are mocked."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import kimi_ai as ai

existing = importlib.util.spec_from_file_location("kimi_fixture", ROOT / "tests" / "kimi-ai-check.py")
fixture = importlib.util.module_from_spec(existing)
existing.loader.exec_module(fixture)


class StrictProtocolChecks(unittest.TestCase):
    def payload(self):
        return {"ai": fixture.CONFIG.copy(), "requestId": "offline-edge", "brief": "纵向几何折叠",
                "frameCount": 12, "speedMs": 40}

    def error(self, codes, callback):
        with self.assertRaises(ai.AIError) as context:
            callback()
        self.assertIn(context.exception.code, codes)
        self.assertNotIn(fixture.SECRET, str(context.exception))

    def test_stream_requires_done_marker_even_after_finish_reason_stop(self):
        text = json.dumps(fixture.recipe())
        opener = fixture.Opener(fixture.stream([text], done=False))
        self.error(("ai_incomplete", "ai_response_invalid"), lambda: ai.generate(self.payload(), opener=opener))
        self.assertEqual(len(opener.calls), 1)

    def test_done_marker_without_finish_reason_never_imports(self):
        raw = ("data: " + json.dumps({"choices": [{"delta": {"content": json.dumps(fixture.recipe())}}]})
               + "\n\ndata: [DONE]\n\n").encode()
        opener = fixture.Opener(fixture.Response(raw, stream=True))
        self.error(("ai_incomplete", "ai_response_invalid"), lambda: ai.generate(self.payload(), opener=opener))

    def test_duplicate_event_keys_are_rejected_without_repair(self):
        raw = b'data: {"choices":[],"choices":[]}\n\ndata: [DONE]\n\n'
        opener = fixture.Opener(fixture.Response(raw, stream=True))
        self.error(("ai_response_invalid",), lambda: ai.generate(self.payload(), opener=opener))
        self.assertEqual(len(opener.calls), 1)

    def test_long_sse_line_and_large_wire_stop_before_model_content(self):
        for raw in (b":" + b"x" * 65536 + b"\n", (b":" + b"x" * 4095 + b"\n") * 513):
            with self.subTest(bytes=len(raw)):
                opener = fixture.Opener(fixture.Response(raw, stream=True))
                self.error(("ai_response_large",), lambda: ai.generate(self.payload(), opener=opener))
                self.assertEqual(len(opener.calls), 1)

    def test_model_list_unknown_or_large_reply_is_not_connection_success(self):
        for raw in (b'{"models":[]}', b'{"data":[],' + b' ' * ai.MAX_WIRE_BYTES):
            with self.subTest(bytes=len(raw)):
                opener = fixture.Opener(fixture.Response(raw))
                client = ai.KimiClient(ai.configuration(fixture.CONFIG), opener=opener)
                self.error(("ai_response_invalid", "ai_response_large"), client.test_connection)

    def test_overall_deadline_includes_connect_and_body_read_time(self):
        clock = [0.0]

        class DelayedResponse(fixture.Response):
            def read(self, size=-1):
                clock[0] += 0.5
                return super().read(size)

        class DelayedOpener:
            def open(self, request, timeout):
                clock[0] += 0.75
                normal = fixture.completion()
                return DelayedResponse(normal.getvalue())

        with patch.object(ai.time, "monotonic", side_effect=lambda: clock[0]):
            client = ai.KimiClient(ai.configuration(fixture.CONFIG), opener=DelayedOpener(), timeout=1)
            self.error(("ai_timeout",), lambda: client.completion([{"role": "user", "content": "test"}]))

    def test_repair_has_exactly_the_requested_frame_and_speed(self):
        invalid = fixture.recipe()
        invalid["frame_count"] = 11
        opener = fixture.Opener(fixture.completion(json.dumps(invalid)), fixture.completion())
        result = ai.generate(self.payload(), opener=opener)
        self.assertTrue(result["repaired"])
        self.assertEqual(len(result["design"]["frames"]), 12)
        self.assertEqual(result["design"]["speed_ms"], 40)
        self.assertEqual(len(opener.calls), 2)

    def test_payload_fields_never_spill_into_request_body(self):
        payload = self.payload()
        payload.update({"current": "private-current", "meta": "private-meta", "history": "private-history",
                        "key_layer": "private-key-layer", "device": {"productId": "private-device"}})
        payload["reference"] = {"id": "private-id", "frames": "private-pixels", "keyframes": "private-axis",
                                "ai": {"recipe": "private-previous-recipe"}, "name": "公共作品名"}
        opener = fixture.Opener(fixture.completion())
        ai.generate(payload, opener=opener)
        body = opener.calls[0][0].data.decode()
        self.assertNotIn("private-", body)
        self.assertIn("公共作品名", body)

    def test_authorization_is_only_a_header_and_no_redirect_handler_forwards_it(self):
        opener = fixture.Opener(fixture.completion())
        result = ai.generate(self.payload(), opener=opener)
        request = opener.calls[0][0]
        self.assertEqual(request.get_header("User-agent"), "CyberboardStudio/0.2.0")
        self.assertNotIn(fixture.SECRET, request.full_url)
        self.assertNotIn(fixture.SECRET, request.data.decode())
        self.assertNotIn(fixture.SECRET, json.dumps(result))
        for status in (301, 302, 303, 307, 308):
            self.error(("ai_redirect",), lambda: ai.NoRedirects().redirect_request(
                request, None, status, "redirect", {}, "https://evil.example"))

    def test_reference_image_urls_and_corrupt_payloads_never_call_network(self):
        for value in ("https://evil.example/private.png", "file:///private/photo.jpg",
                      "data:image/svg+xml;base64,PHN2Zz4=", "data:image/jpeg;base64,!!!",
                      "data:image/jpeg;base64,bm90IGFuIGltYWdl", "data:image/jpeg;base64," + "A" * 560000):
            payload = {**self.payload(), "images": [{"dataUrl": value}]}
            opener = fixture.Opener()
            self.error(("ai_image_invalid",), lambda: ai.generate(payload, opener=opener))
            self.assertEqual(opener.calls, [])

    def test_image_only_creation_sends_pixels_but_no_filenames_or_metadata(self):
        from PIL import Image
        from ai_images import normalize
        image = Image.new("RGB", (8, 8), "#24DDFC")
        exif = Image.Exif()
        exif[270] = "private-image-description"
        raw = io.BytesIO()
        image.save(raw, "JPEG", exif=exif)
        ref = normalize(raw.getvalue(), "private-raw-local-name.jpg")
        ref.update({"path": "private-file-path", "original": "private-original-bytes"})
        payload = {**self.payload(), "brief": "", "images": [ref]}
        opener = fixture.Opener(fixture.completion())
        result = ai.generate(payload, opener=opener)
        body = json.loads(opener.calls[0][0].data)
        content = body["messages"][1]["content"]
        self.assertEqual([part["type"] for part in content], ["text", "image_url"])
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertNotIn("private-", json.dumps(body))
        self.assertNotIn("dataUrl", json.dumps(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
