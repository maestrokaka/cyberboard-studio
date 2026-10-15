"""Offline Kimi request, stream, privacy and recipe integration checks; no USB/network."""
import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import kimi_ai as ai
import bridge

SECRET = "sk-offline-distinct-key-1234567890"
CONFIG = {"provider": "kimi-code", "baseUrl": ai.BASE_URLS["kimi-code"][0],
          "model": "kimi-for-coding", "apiKey": SECRET}


def recipe():
    return {"version": 1, "name": "上升裂隙", "description": "顶部纵向转场与轴灯呼应", "frame_count": 12,
            "speed_ms": 40, "palette": ["#12E5FF", "#FF460A"], "scenes": [
                {"name": "蓄能", "start": 0, "end": 6,
                 "top": [{"kind": "scan", "color": "#12E5FF", "axis": "y",
                          "position": {"from": 1.25, "to": -0.25}, "width": 0.6}],
                 "keys": [{"kind": "wave", "color": "#FF460A", "angle": 90, "frequency": 2,
                           "phase": {"from": 0, "to": 2}}]},
                {"name": "收束", "start": 6, "end": 12,
                 "top": [{"kind": "ring", "color": "#FF460A", "radius": {"from": 1, "to": 0},
                          "aspect": 8}], "keys": [{"kind": "solid", "color": "#12E5FF"}]}]}


class Response(io.BytesIO):
    def __init__(self, raw, stream=False):
        super().__init__(raw)
        self.headers = {"Content-Type": "text/event-stream; charset=utf-8" if stream else "application/json"}


def completion(text=None, finish="stop"):
    content = text if text is not None else json.dumps(recipe(), ensure_ascii=False)
    return Response(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": finish}],
                                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}).encode())


def stream(parts, finish="stop", done=True, reasoning=False):
    events = []
    if reasoning:
        events.append({"choices": [{"delta": {"reasoning_content": "private reasoning"}}]})
    events.extend({"choices": [{"delta": {"content": part}}]} for part in parts)
    events.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    events.append({"choices": [], "usage": {"total_tokens": 30}})
    raw = ": ping\r\n\r\n" + "".join("data: " + json.dumps(e, ensure_ascii=False) + "\r\n\r\n" for e in events)
    if done:
        raw += "data: [DONE]\r\n\r\n"
    return Response(raw.encode(), stream=True)


class Opener:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class KimiChecks(unittest.TestCase):
    def payload(self):
        return {"ai": copy.deepcopy(CONFIG), "requestId": "offline-token", "brief": "上下滚动，青色裂隙对撞",
                "frameCount": 12, "speedMs": 40, "reference": {"name": "参考", "palette": ["#12E5FF"]}}

    def error(self, code, callback):
        with self.assertRaises(ai.AIError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(SECRET, str(caught.exception))

    def test_default_configuration_and_hidden_repr(self):
        cfg = ai.configuration({"apiKey": SECRET})
        self.assertEqual(cfg.provider, "kimi-code")
        self.assertEqual(cfg.model, "k3")
        self.assertNotIn(SECRET, repr(cfg))

    def test_endpoints_are_provider_specific(self):
        for url in ("http://api.kimi.com/coding/v1", "https://evil.invalid/v1", "https://api.kimi.com/coding/v1?x=1",
                    "https://api.moonshot.cn/v1", "https://api.kimi.com.evil.invalid/coding/v1"):
            self.error("ai_invalid_settings", lambda: ai.configuration({**CONFIG, "baseUrl": url}))

    def test_other_provider_and_global_hosts(self):
        cfg = ai.configuration({"provider": "kimi-open", "baseUrl": ai.BASE_URLS["kimi-open"][1], "apiKey": SECRET})
        self.assertEqual(cfg.model, "kimi-k3")

    def test_keys_are_not_headers_injectable(self):
        for value in (SECRET + "\nInjected: true", "含中文", "x" * 4097, "has space"):
            self.error("ai_invalid_key", lambda: ai.configuration({**CONFIG, "apiKey": value}))
        self.error("ai_not_configured", lambda: ai.configuration({}))

    def test_redirects_are_never_followed(self):
        self.error("ai_redirect", lambda: ai.NoRedirects().redirect_request(None, None, 302, "", {}, "https://evil.invalid"))

    def test_connection_lists_models_without_generating(self):
        opener = Opener(Response(b'{"data":[{"id":"kimi-for-coding"}]}'))
        result = ai.KimiClient(ai.configuration(CONFIG), opener=opener).test_connection()
        self.assertTrue(result["success"])
        self.assertTrue(result["modelListed"])
        req = opener.calls[0][0]
        self.assertEqual(req.get_method(), "GET")
        self.assertTrue(req.full_url.endswith("/models"))
        self.assertEqual(req.get_header("User-agent"), ai.USER_AGENT)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_creative_network_request_and_complete_pixels(self):
        opener = Opener(completion())
        result = ai.generate(self.payload(), opener=opener)
        d = result["design"]
        self.assertEqual(d["origin"], "kimi-ai")
        self.assertEqual(len(d["frames"]), 12)
        self.assertEqual(len(d["keyframes"]), 12)
        for field, length in (("frames", 200), ("keyframes", 90)):
            for frame in d[field]:
                self.assertEqual(len(frame), length)
                self.assertTrue(all(ai.re.fullmatch(r"#[0-9A-F]{6}", c) for c in frame))
        for frame in d["keyframes"]:
            self.assertTrue(all(frame[i] == "#000000" for i in bridge.RESERVED_LEDS))
        request = opener.calls[0][0]
        body = json.loads(request.data)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + SECRET)
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertNotIn("temperature", body)
        self.assertNotIn(SECRET, request.data.decode())
        self.assertNotIn(SECRET, json.dumps(result))

    def test_only_reference_style_is_sent(self):
        payload = self.payload()
        payload["reference"].update({"key_layer": "private-keymap", "frames": "private-frames", "apiKey": "private-reference-key"})
        payload["device"] = "private-identity"
        payload["baseline"] = "private-baseline"
        messages = ai.creative_messages(payload)
        text = json.dumps(messages)
        for secret in ("private-keymap", "private-frames", "private-reference-key", "private-identity", "private-baseline", SECRET):
            self.assertNotIn(secret, text)

    def test_reference_aesthetics_keep_the_requested_output_contract(self):
        payload = {**self.payload(), "frameCount": 50, "speedMs": 100,
                   "brief": "黑底紫色小角色眨眼，轴灯轻微呼吸"}
        messages = ai.creative_messages(payload)
        system, request = messages[0]["content"], json.loads(messages[1]["content"])
        self.assertEqual(request["固定播放参数"], {"frame_count": 50, "speed_ms": 100, "loop_seconds": 5.0})
        self.assertIn("frame_count=50，speed_ms=100", system)
        self.assertIn("有效帧索引0..49", system)
        self.assertIn("不能把200颗顶部像素复制成轴灯", system)
        self.assertIn("示意帧", system)
        self.assertIn("能在5行里辨识的图案可完整静置", system)
        self.assertIn("不强制上下滚动", system)
        self.assertNotIn("781", system)
        # The final schema remains the actual executable contract rather than
        # a copied DIY page shape, invented shader, or raw pixel-array format.
        schema = json.loads(system.split("配方JSON Schema：\n", 1)[1])
        self.assertEqual(schema["properties"]["frame_count"]["maximum"], 255)
        self.assertIn("scenes", schema["required"])
        self.assertNotIn("frames", schema["properties"])
        self.assertNotIn("hsv", schema["$defs"])

    def test_small_character_and_breathing_keep_complete_independent_outputs(self):
        r = {"version": 1, "name": "紫影眨眼", "description": "紫色像素角色轻眨眼，轴灯低亮呼吸。",
             "frame_count": 50, "speed_ms": 100, "palette": ["#7B2FBE", "#FFFFFF"], "scenes": []}
        for name, start, end, rows in [("睁眼", 0, 45, ["01110", "12221", "12121", "11111", "01010"]),
                                       ("眨眼", 45, 50, ["01110", "11111", "12221", "11111", "01010"])]:
            r["scenes"].append({"name": name, "start": start, "end": end,
                                "top": [{"kind": "bitmap", "rows": rows, "x": 0.5, "y": 0.5}],
                                "keys": [{"kind": "solid", "color": "#7B2FBE", "opacity": {"from": 0.1, "to": 0.4, "ease": "sine"}}]})
        payload = {**self.payload(), "frameCount": 50, "speedMs": 100, "brief": "小角色只眨一次眼，轴灯低亮呼吸"}
        result = ai.generate(payload, opener=Opener(completion(json.dumps(r))))
        d = result["design"]
        self.assertEqual((len(d["frames"]), len(d["keyframes"]), d["speed_ms"]), (50, 50, 100))
        self.assertEqual({len(f) for f in d["frames"]}, {200})
        self.assertEqual({len(f) for f in d["keyframes"]}, {90})
        self.assertNotEqual(d["frames"][0], d["frames"][-1])
        self.assertNotEqual(d["keyframes"][0], d["keyframes"][22])
        self.assertTrue(all(f[i] == "#000000" for f in d["keyframes"] for i in bridge.RESERVED_LEDS))
        self.assertEqual({(layer.get("x"), layer.get("y")) for scene in r["scenes"] for layer in scene["top"]}, {(0.5, 0.5)})

    def test_reference_document_partial_and_200_lamp_keyboard_output_is_not_accepted(self):
        incomplete = recipe()
        incomplete["frame_count"] = 8
        for text in (json.dumps(incomplete), "设计思路：先看八帧示意。\n```json\n"+json.dumps(recipe())+"\n```",
                     json.dumps({"frames": {"frame_num": 8, "valid": 1, "frame_data": []}, "keyframes": {"frame_num": 8}, "speed_ms": 150})):
            opener = Opener(completion(text), completion(text))
            self.error("ai_recipe_invalid", lambda: ai.generate(self.payload(), opener=opener))
            self.assertEqual(len(opener.calls), 2)

    def test_k3_choice_and_bitmap_brief_compile_through_the_same_pipeline(self):
        drawing = recipe()
        drawing.update(name="猫影纵卷", description="橙色像素轮廓上下穿过顶部视窗。")
        drawing["scenes"] = [{"name": "纵卷", "start": 0, "end": 12,
                              "top": [{"kind": "bitmap", "rows": ["01110", "11111", "10101", "11111", "01110", "00100", "01110", "11111", "01110", "01010", "01010", "11011"],
                                       "palette": ["#FF460A"], "x": 0.5, "y": {"from": 2.75, "to": -1.75}, "scale": 1}],
                              "keys": [{"kind": "scan", "color": "#FF460A", "axis": "y", "position": {"from": 1, "to": 0}}]}]
        opener = Opener(completion(json.dumps(drawing, ensure_ascii=False)))
        payload = self.payload()
        payload["ai"].pop("model")
        payload["brief"] = "参考主体上下滚动，保留完整的卡通轮廓"
        payload["reference"] = {"palette": ["#FF460A"]}
        result = ai.generate(payload, opener=opener)
        body = json.loads(opener.calls[0][0].data)
        self.assertEqual(body["model"], "k3")
        self.assertEqual(result["model"], "k3")
        self.assertEqual(result["design"]["name"], "猫影纵卷")
        self.assertEqual(result["design"]["ai"]["recipe"]["scenes"][0]["top"][0]["rows"], drawing["scenes"][0]["top"][0]["rows"])
        self.assertTrue(any(c != "#000000" for frame in result["design"]["frames"] for c in frame))
        self.assertEqual(set(result["design"]["frames"][0]), {"#000000"})
        self.assertEqual(set(result["design"]["frames"][-1]), {"#000000"})
        self.assertNotIn("参考作品名", body["messages"][1]["content"])

    def test_utf8_sse_and_reasoning_is_not_exposed(self):
        text = json.dumps(recipe(), ensure_ascii=False)
        events = []
        opener = Opener(stream([text[:19], text[19:100], text[100:]], reasoning=True))
        result = ai.generate(self.payload(), opener=opener, progress=lambda *e: events.append(e))
        self.assertEqual(result["design"]["name"], "上升裂隙")
        self.assertNotIn("private reasoning", json.dumps(events))
        self.assertIn("ai_compile", [e[0] for e in events])

    def test_truncated_result_never_imported_or_retried(self):
        opener = Opener(completion(finish="length"))
        self.error("ai_incomplete", lambda: ai.generate(self.payload(), opener=opener))
        self.assertEqual(len(opener.calls), 1)

    def test_malformed_recipe_is_repaired_once(self):
        opener = Opener(completion('{"wrong":true}'), completion())
        result = ai.generate(self.payload(), opener=opener)
        self.assertTrue(result["repaired"])
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(result["usage"]["total_tokens"], 60)
        repair = json.loads(opener.calls[1][0].data)["messages"][-1]
        self.assertIn("wrong", repair["content"])
        self.assertEqual(repair["role"], "user")

    def test_invalid_recipe_stops_after_two_attempts(self):
        opener = Opener(completion('{"wrong":true}'), completion('{"wrong":true}'))
        self.error("ai_recipe_invalid", lambda: ai.generate(self.payload(), opener=opener))
        self.assertEqual(len(opener.calls), 2)

    def test_duplicate_keys_nonfinite_and_executable_programs_rejected(self):
        for value in ('{"version":1,"version":1}', '{"x":NaN}', '```python\nprint(1)\n```', '[1,2]', 'import os'):
            with self.assertRaises(ValueError):
                ai.parse_recipe(value)

    def test_json_fence_can_be_unwrapped(self):
        self.assertEqual(ai.parse_recipe('```json\n' + json.dumps(recipe()) + '\n```'), recipe())

    def test_oversized_responses_and_key_echo_rejected(self):
        for content in ("x" * (ai.MAX_CONTENT_BYTES + 1), SECRET):
            opener = Opener(completion(content))
            self.error("ai_response_invalid", lambda: ai.generate(self.payload(), opener=opener))

    def test_error_categories_do_not_echo_body_or_retry(self):
        for status, content, expected in ((401, "invalid key", "ai_auth"), (401, "subscription model", "ai_model_access"),
                                           (403, "client user-agent", "ai_client_restricted"), (403, "weekly limit", "ai_quota"),
                                           (429, "busy", "ai_rate_limit"), (404, "missing", "ai_model_missing"),
                                           (400, "invalid", "ai_bad_request"), (500, "service", "ai_service")):
            raw = urllib.error.HTTPError(CONFIG["baseUrl"], status, "private", {}, io.BytesIO((content + SECRET).encode()))
            opener = Opener(raw)
            self.error(expected, lambda: ai.generate(self.payload(), opener=opener))
            self.assertEqual(len(opener.calls), 1)

    def test_network_errors_and_deadline_are_safe(self):
        opener = Opener(urllib.error.URLError(SECRET))
        self.error("ai_network", lambda: ai.generate(self.payload(), opener=opener))
        client = ai.KimiClient(ai.configuration(CONFIG), opener=Opener(), timeout=-1)
        self.error("ai_timeout", lambda: client.test_connection())

    def test_bad_brief_or_parameters_do_not_call_network(self):
        for changes in ({"brief": ""}, {"brief": "x" * 6001}, {"speedMs": 5}, {"frameCount": True}, {"requestId": "../bad"}):
            payload = {**self.payload(), **changes}
            opener = Opener()
            with self.assertRaises(ai.AIError):
                ai.generate(payload, opener=opener)
            self.assertEqual(opener.calls, [])

    def test_bridge_ai_never_loads_device_state_or_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = bridge.Bridge(Path(tmp) / "state", tmp, cli={}, cli_version="offline", event_sink=lambda _: None)
            with patch.object(ai.urllib.request, "build_opener", return_value=Opener(completion())):
                result = b.generateAI(self.payload())
            self.assertEqual(len(result["design"]["frames"]), 12)
            self.assertFalse((Path(tmp) / "state").exists())
            with self.assertRaises(bridge.BridgeError) as error:
                b.generateAI({**self.payload(), "ai": {}})
            self.assertEqual(error.exception.code, "ai_not_configured")


if __name__ == "__main__":
    unittest.main(verbosity=2)
