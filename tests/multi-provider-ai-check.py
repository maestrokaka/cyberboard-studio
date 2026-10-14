"""Offline official provider protocol and capability regressions, no keys/network/USB."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import kimi_ai as ai

spec = importlib.util.spec_from_file_location("kimi_fixture", ROOT / "tests/kimi-ai-check.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class MultiProviderChecks(unittest.TestCase):
    def payload(self, provider, **settings):
        return {"ai": {"provider": provider, "apiKey": fixture.SECRET, **settings},
                "requestId": "offline-multi", "brief": "橙蓝几何转场", "frameCount": 12, "speedMs": 40}

    def test_provider_defaults_and_strict_official_endpoints(self):
        self.assertEqual(ai.configuration(self.payload("minimax")["ai"]).model, "MiniMax-M3")
        self.assertEqual(ai.configuration(self.payload("deepseek")["ai"]).model, "deepseek-flash")
        for provider in ("minimax", "deepseek"):
            for url in ai.BASE_URLS[provider]:
                self.assertEqual(ai.configuration(self.payload(provider, baseUrl=url + "/")["ai"]).base_url, url)
            for url in ("http://api.deepseek.com", "https://api.minimax.cn.evil/v1", "https://api.deepseek.com/v1?x=1",
                        "https://user@api.minimax.cn/v1", ai.BASE_URLS["kimi-code"][0]):
                with self.assertRaises(ai.AIError) as error:
                    ai.configuration(self.payload(provider, baseUrl=url)["ai"])
                self.assertEqual(error.exception.code, "ai_invalid_settings")

    def test_provider_wire_options_and_local_compilation(self):
        for provider in ("minimax", "deepseek"):
            opener = fixture.Opener(fixture.stream([json.dumps(fixture.recipe())], reasoning=True))
            events = []
            result = ai.generate(self.payload(provider), opener=opener, progress=lambda s, m: events.append(m))
            body = json.loads(opener.calls[0][0].data)
            self.assertEqual(result["design"]["origin"], provider + "-ai")
            self.assertEqual(result["design"]["ai"]["provider"], provider)
            self.assertEqual((len(result["design"]["frames"]), len(result["design"]["keyframes"])), (12, 12))
            self.assertNotIn("Kimi", " ".join(events))
            self.assertNotIn(fixture.SECRET, json.dumps(result))
            self.assertNotIn("private reasoning", json.dumps(result))
            self.assertEqual(body["stream_options"], {"include_usage": True})
            if provider == "minimax":
                self.assertEqual(body["max_completion_tokens"], 16000)
                self.assertTrue(body["reasoning_split"])
                self.assertNotIn("max_tokens", body)
                self.assertNotIn("reasoning_effort", body)
            else:
                self.assertEqual(body["thinking"], {"type": "enabled"})
                self.assertEqual(body["reasoning_effort"], "high")
                self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_reference_images_use_valid_detail_and_no_private_metadata(self):
        from PIL import Image
        from ai_images import normalize
        raw = io.BytesIO()
        Image.new("RGB", (8, 8), "#FE6820").save(raw, "PNG")
        image = normalize(raw.getvalue(), "private-filename.png")
        for provider in ("minimax", "deepseek"):
            payload = self.payload(provider)
            payload.update(images=[image], brief="")
            opener = fixture.Opener(fixture.completion())
            ai.generate(payload, opener=opener)
            body = json.loads(opener.calls[0][0].data)
            part = body["messages"][1]["content"][1]["image_url"]
            self.assertTrue(part["url"].startswith("data:image/jpeg;base64,"))
            if provider == "minimax":
                self.assertEqual(part["detail"], "default")
            self.assertNotIn("private-filename", json.dumps(body))

    def test_text_only_and_unknown_models_cannot_silently_discard_images(self):
        from PIL import Image
        from ai_images import normalize
        raw = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(raw, "PNG")
        image = normalize(raw.getvalue())
        for provider, model in (("minimax", "MiniMax-M2.7"), ("deepseek", "deepseek-v4-pro"),
                                ("minimax", "future-id"), ("deepseek", "future-id")):
            opener = fixture.Opener()
            with self.assertRaises(ai.AIError) as error:
                ai.generate({**self.payload(provider, model=model), "images": [image]}, opener=opener)
            self.assertEqual(error.exception.code, "ai_images_unsupported")
            self.assertEqual(opener.calls, [])

    def test_minimax_unavailable_model_list_is_not_success_or_paid_probe(self):
        error = urllib.error.HTTPError("https://api.minimax.cn/v1/models", 404, "missing", {}, io.BytesIO(b"{}"))
        opener = fixture.Opener(error)
        result = ai.AIClient(ai.configuration(self.payload("minimax")["ai"]), opener=opener).test_connection()
        self.assertFalse(result["success"])
        self.assertTrue(result["needsGenerationTest"])
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0][0].get_method(), "GET")

    def test_no_auth_body_or_provider_errors_can_escape_or_auto_retry(self):
        for status, body, code in ((401, b"bad key", "ai_auth"), (429, b"busy", "ai_rate_limit"),
                                  (400, b'{"error":{"code":1008,"message":"secret"}}', "ai_quota"),
                                  (200, b'{"base_resp":{"status_code":2049,"status_msg":"secret"}}', "ai_auth")):
            response = fixture.Response(body) if status == 200 else urllib.error.HTTPError(
                "https://api.minimax.cn/v1/chat/completions", status, "bad", {}, io.BytesIO(body))
            opener = fixture.Opener(response)
            with self.assertRaises(ai.AIError) as error:
                ai.generate(self.payload("minimax"), opener=opener)
            self.assertEqual(error.exception.code, code)
            self.assertNotIn("secret", str(error.exception))
            self.assertEqual(len(opener.calls), 1)
        self.assertIn("DeepSeek", str(ai.http_error(401, b"bad", "deepseek")))
        self.assertNotIn("Kimi", str(ai.http_error(429, b"bad", "minimax")))

    def test_each_provider_models_get_reports_capability_without_generation(self):
        for provider in ("minimax", "deepseek"):
            model = ai.DEFAULT_MODELS[provider]
            opener = fixture.Opener(fixture.Response(json.dumps({"data": [{"id": model}]}).encode()))
            result = ai.AIClient(ai.configuration(self.payload(provider)["ai"]), opener=opener).test_connection()
            self.assertTrue(result["success"] and result["modelListed"] and result["supportsImages"])
            self.assertEqual(result["maxReferenceImages"], 3)
            self.assertEqual(opener.calls[0][0].get_method(), "GET")


if __name__ == "__main__":
    unittest.main(verbosity=2)
