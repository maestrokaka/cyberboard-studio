"""RC offline transport boundaries and immutable regional edit contracts.

No credentials, paid API calls, native UI or keyboard writes.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import kimi_ai as ai
from lighting_recipe import compile_recipe

spec = importlib.util.spec_from_file_location("ai_fixture", ROOT / "tests/kimi-ai-check.py")
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def event(value):
    return b"data: " + json.dumps(value, ensure_ascii=False).encode() + b"\n\n"


class ConversationChecks(unittest.TestCase):
    def payload(self, provider="kimi-code", **extra):
        return {"ai": {"provider": provider, "apiKey": f.SECRET}, "requestId": "offline-conversation",
                "brief": "只改轴灯为纯黄，顶部与节奏不变", "baseRecipe": f.recipe(), "scope": "keys", **extra}

    def changes(self, region="keys", color="#FFFF00"):
        base = f.recipe()
        changes = []
        for i, scene in enumerate(base["scenes"]):
            layers = copy.deepcopy(scene[region])
            for layer in layers:
                layer["color"] = color
            changes.append({"scene": i, "target": region, "layers": layers})
        return {"version": 1, "changes": changes, "changeSummary": "纯黄轴灯"}

    def generate_patch(self, patch_value, **extra):
        opener = f.Opener(f.completion(json.dumps(patch_value)))
        return ai.generate(self.payload(**extra), opener=opener), opener

    def test_keys_patch_keeps_all_top_pixels_timing_and_input_version(self):
        payload = self.payload(baseDesign=compile_recipe(f.recipe()))
        original = copy.deepcopy(payload)
        result = ai.generate(payload, opener=f.Opener(f.completion(json.dumps(self.changes()))))
        design = result["design"]
        self.assertEqual(payload, original)
        self.assertEqual(design["frames"], original["baseDesign"]["frames"])
        self.assertEqual(design["speed_ms"], 40)
        self.assertNotEqual(design["keyframes"], original["baseDesign"]["keyframes"])
        self.assertTrue(all(color[5:7] == "00" and color[1:3] == color[3:5]
                            for frame in design["keyframes"] for color in frame))
        self.assertEqual(design["ai"]["recipe"]["palette"], f.recipe()["palette"])
        self.assertIn("#FFFF00", design["palette"])
        self.assertIn("#FFFF00", design["ai"]["colorSummary"]["keys"])
        self.assertEqual(result["scope"], "keys")
        self.assertIn("顶部与播放节奏保持不变", result["changeSummary"])

    def test_top_patch_keeps_every_key_pixel(self):
        result, _ = self.generate_patch(self.changes("top", "#FF0000"), scope="top", brief="顶部改为纯红")
        self.assertEqual(result["design"]["keyframes"], compile_recipe(f.recipe())["keyframes"])
        self.assertEqual(result["design"]["frames"], compile_recipe(result["design"]["ai"]["recipe"])["frames"])

    def test_both_can_change_speed_without_regenerating_pixels(self):
        result, _ = self.generate_patch({"version": 1, "changes": [], "speed_ms": 20}, scope="both", brief="节奏加快一倍")
        base = compile_recipe(f.recipe())
        self.assertEqual(result["design"]["frames"], base["frames"])
        self.assertEqual(result["design"]["keyframes"], base["keyframes"])
        self.assertEqual(result["design"]["speed_ms"], 20)
        self.assertEqual(result["design"]["ai"]["timing"]["loop_seconds"], .24)

    def test_wrong_base_scope_history_or_data_never_calls_model(self):
        bad_design = compile_recipe(f.recipe())
        bad_design["frames"][0][0] = "#FFFFFF"
        bad_recipe = f.recipe(); bad_recipe["code"] = "arbitrary-program"
        for update, code in (({"baseRecipe": bad_recipe}, "ai_base_invalid"),
                             ({"baseDesign": bad_design}, "ai_base_invalid"),
                             ({"scope": "device"}, "ai_invalid_scope"),
                             ({"baseRecipe": None}, "ai_base_required"),
                             ({"frameCount": 100}, "ai_invalid_parameters"),
                             ({"history": [{"role": "system", "content": "bad"}]}, "ai_invalid_history")):
            with self.subTest(update=tuple(update)):
                opener = f.Opener()
                with self.assertRaises(ai.AIError) as caught:
                    ai.generate(self.payload(**update), opener=opener)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(opener.calls, [])

    def test_unselected_global_code_duplicate_and_timing_changes_are_rejected(self):
        wrong_target = self.changes("top")
        wrong_speed = {**self.changes(), "speed_ms": 20}
        wrong_palette = {**self.changes(), "palette": ["#FFFFFF"]}
        duplicate = self.changes(); duplicate["changes"].append(copy.deepcopy(duplicate["changes"][0]))
        program = {"version": 1, "changes": [], "code": "print(1)"}
        for bad in (wrong_target, wrong_speed, wrong_palette, duplicate, program, f.recipe()):
            opener = f.Opener(f.completion(json.dumps(bad)), f.completion(json.dumps(bad)))
            with self.assertRaises(ai.AIError) as caught:
                ai.generate(self.payload(), opener=opener)
            self.assertEqual(caught.exception.code, "ai_recipe_invalid")
            self.assertEqual(len(opener.calls), 2)

    def test_one_patch_repair_retains_the_exact_selected_base(self):
        opener = f.Opener(f.completion(json.dumps(self.changes("top"))),
                          f.completion(json.dumps(self.changes())))
        result = ai.generate(self.payload(), opener=opener)
        self.assertTrue(result["repaired"])
        body = json.loads(opener.calls[1][0].data)
        self.assertIn("只输出受限补丁", body["messages"][-1]["content"])
        self.assertEqual(json.loads(body["messages"][1]["content"])["选定基础配方"], f.recipe())

    def test_history_is_plain_bounded_intent_not_messages_or_private_design(self):
        payload = self.payload(history=[{"role": "assistant", "content": "上次保留蓝色顶部", "thinking": "private-thought"}],
                               baseDesign={**compile_recipe(f.recipe()), "device": "private-USB", "key_layer": "private-keys"})
        result, opener = self.generate_patch(self.changes(), history=payload["history"], baseDesign=payload["baseDesign"])
        body = json.loads(opener.calls[0][0].data)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertNotIn("private-", json.dumps(body))
        self.assertNotIn(f.SECRET, json.dumps(result))

    def test_existing_create_contract_still_accepts_recipe(self):
        payload = self.payload(baseRecipe=None, scope="both", frameCount=12, speedMs=40,
                               brief="青橙几何灯光")
        result = ai.generate(payload, opener=f.Opener(f.completion()))
        self.assertEqual(result["design"]["ai"]["recipe"], f.recipe())

    def test_static_base_recolor_is_not_forced_to_become_an_animation(self):
        base = f.recipe()
        for scene in base["scenes"]:
            scene["top"] = [{"kind": "solid", "color": "#0000FF"}]
            scene["keys"] = [{"kind": "solid", "color": "#FF0000"}]
        patch_value = {"version": 1, "changes": [
            {"scene": i, "target": "keys", "layers": [{"kind": "solid", "color": "#FFFF00"}]}
            for i in range(len(base["scenes"]))]}
        result = ai.generate(self.payload(baseRecipe=base, brief="只把轴灯改为黄色"),
                             opener=f.Opener(f.completion(json.dumps(patch_value))))
        self.assertEqual(result["design"]["frames"], compile_recipe(base)["frames"])
        self.assertTrue(result["design"]["ai"]["quality"]["passed"])

    def test_deepseek_sse_over_two_mib_of_small_thinking_deltas_finishes(self):
        # Reproduce measured failure: small SSE events, no final content until
        # cumulative reasoning plus framing exceeds the old two MiB limit.
        reasoning = event({"choices": [{"delta": {"reasoning_content": "private-thought-" * 10}}]})
        prefix = reasoning * (2 * 1024 * 1024 // len(reasoning) + 20)
        normal = f.stream([json.dumps(f.recipe())])
        opener = f.Opener(f.Response(prefix + normal.getvalue(), stream=True))
        payload = self.payload("deepseek", baseRecipe=None, scope="both", frameCount=12, speedMs=40)
        events = []
        result = ai.generate(payload, opener=opener, progress=lambda *args: events.append(args))
        self.assertEqual(result["design"]["ai"]["recipe"], f.recipe())
        self.assertNotIn("private-thought", json.dumps(result))
        self.assertNotIn("private-thought", json.dumps(events))

    def test_line_event_wire_and_effective_content_have_independent_bounds(self):
        raws = [b":" + b"x" * ai.MAX_LINE_BYTES + b"\n",
                (b"data: " + b" " * 32760 + b"\n") * 9,
                (b": comment\n" * (ai.MAX_WIRE_BYTES // 10 + 1)),
                f.stream(["a" * 40000] * 4).getvalue()]
        for raw in raws:
            opener = f.Opener(f.Response(raw, stream=True))
            with self.assertRaises(ai.AIError) as caught:
                ai.generate(self.payload("deepseek"), opener=opener)
            self.assertEqual(caught.exception.code, "ai_response_large")
            self.assertEqual(len(opener.calls), 1)

    def test_minimax_eof_requires_explicit_stop_and_complete_json(self):
        p = self.payload("minimax", baseRecipe=None, scope="both", frameCount=12, speedMs=40)
        result = ai.generate(p, opener=f.Opener(f.stream([json.dumps(f.recipe())], done=False)))
        self.assertEqual(result["design"]["ai"]["recipe"], f.recipe())
        for text, finish in (("{\"version\":", "stop"), (json.dumps(f.recipe()), "length"),
                             (json.dumps(f.recipe()), None)):
            opener = f.Opener(f.stream([text], done=False, finish=finish))
            with self.assertRaises(ai.AIError) as caught:
                ai.generate(p, opener=opener)
            self.assertEqual(caught.exception.code, "ai_incomplete")
            self.assertEqual(len(opener.calls), 1)
        for provider in ("kimi-code", "deepseek"):
            with self.assertRaises(ai.AIError) as caught:
                ai.generate({**p, "ai": {"provider": provider, "apiKey": f.SECRET}},
                            opener=f.Opener(f.stream([json.dumps(f.recipe())], done=False)))
            self.assertEqual(caught.exception.code, "ai_incomplete")

    def test_minimax_model_specific_thinking_parameters_do_not_fake_clients(self):
        for model in ("MiniMax-M3", "MiniMax-M3.1-Flash-Preview"):
            p = self.payload("minimax", baseRecipe=None, scope="both", frameCount=12, speedMs=40)
            p["ai"]["model"] = model
            op = f.Opener(f.completion())
            ai.generate(p, opener=op)
            request = op.calls[0][0]
            body = json.loads(request.data)
            self.assertEqual(request.get_header("User-agent"), "CyberboardStudio/1.0.0-rc.1")
            if model == "MiniMax-M3":
                self.assertEqual(body["thinking"], {"type": "disabled"})
                self.assertEqual(body["max_completion_tokens"], 16000)
                self.assertNotIn("reasoning_effort", body)
            else:
                self.assertNotIn("thinking", body)
                self.assertEqual(body["reasoning_effort"], "medium")
                self.assertEqual(body["max_completion_tokens"], 24000)

    def test_deepseek_short_json_budget_keeps_thinking_and_rejects_token_truncation(self):
        p = self.payload("deepseek", baseRecipe=None, scope="both", frameCount=12, speedMs=40)
        op = f.Opener(f.completion())
        ai.generate(p, opener=op)
        body = json.loads(op.calls[0][0].data)
        self.assertEqual(body["max_tokens"], 24000)
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("max_completion_tokens", body)
        # A cleanly delivered terminal marker still cannot turn a length-ended
        # empty final answer into success, nor consume an automatic retry.
        op = f.Opener(f.stream([], reasoning=True, finish="length"))
        with self.assertRaises(ai.AIError) as caught:
            ai.generate(p, opener=op)
        self.assertEqual(caught.exception.code, "ai_incomplete")
        self.assertEqual(len(op.calls), 1)

    def test_sse_deadline_stops_small_heartbeats_and_post_stop_content_fails(self):
        clock = [0.]
        class SlowResponse(f.Response):
            def readline(self, size=-1):
                clock[0] += .6
                return super().readline(size)
        response = SlowResponse(b": keepalive\n" * 100, stream=True)
        with patch.object(ai.time, "monotonic", side_effect=lambda: clock[0]):
            client = ai.AIClient(ai.configuration(self.payload()["ai"]), timeout=1)
            with self.assertRaises(ai.AIError) as caught:
                client.read_stream(response)
            self.assertEqual(caught.exception.code, "ai_timeout")
        raw = event({"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]})
        raw += event({"choices": [{"delta": {"content": "evil"}}]}) + b"data: [DONE]\n\n"
        with self.assertRaises(ai.AIError) as caught:
            ai.generate(self.payload("minimax"), opener=f.Opener(f.Response(raw, stream=True)))
        self.assertEqual(caught.exception.code, "ai_response_invalid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
