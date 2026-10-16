"""Offline identity, typography and tall-scroll prompt/recipe integration checks.

Fixtures use only generated public pixels and in-memory HTTP responses. These
checks verify the instructions and bounded format, not portrait likeness or art.
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import kimi_ai as ai
from ai_images import normalize
from PIL import Image

spec = importlib.util.spec_from_file_location("composition_fixture", ROOT / "tests/kimi-ai-check.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class CompositionPromptChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = io.BytesIO()
        Image.new("RGB", (3, 5), "#592E18").save(raw, "PNG")
        cls.image = normalize(raw.getvalue())

    def payload(self, *, images=False, provider="kimi-code", brief="完整人物向上滚动，保留身份与文字"):
        payload = {"ai": {"provider": provider, "model": ai.DEFAULT_MODELS[provider],
                          "baseUrl": ai.BASE_URLS[provider][0], "apiKey": fixture.SECRET},
                   "requestId": "offline-composition", "brief": brief, "frameCount": 80, "speedMs": 30}
        if images:
            payload["images"] = [copy.deepcopy(self.image)]
        return payload

    def test_all_provider_messages_describe_the_actual_64_row_bounded_contract(self):
        for provider in ai.BASE_URLS:
            for images in (False, True):
                with self.subTest(provider=provider, images=images):
                    payload = self.payload(provider=provider, images=images)
                    before = copy.deepcopy(payload)
                    messages = ai.creative_messages(payload)
                    prompt = messages[0]["content"]
                    schema = json.loads(prompt.split("\n配方JSON Schema：\n", 1)[1])
                    rows = schema["$defs"]["bitmap"]["properties"]["rows"]
                    self.assertEqual((rows["maxItems"], rows["items"]["maxLength"]), (64, 40))
                    self.assertFalse(schema["$defs"]["bitmap"]["additionalProperties"])
                    self.assertIn("40×64/2560格", prompt)
                    self.assertIn("8,000,000", schema["description"])
                    self.assertIn("96 total layers", schema["description"])
                    self.assertNotIn("高图最多40×32", prompt)
                    self.assertNotIn("优先宽8–16格", prompt)
                    self.assertLess(len(prompt), 22000)
                    self.assertEqual(payload, before)

    def test_scroll_guidance_is_wide_uniform_upward_and_conditional(self):
        for images in (False, True):
            prompt = ai.creative_messages(self.payload(images=images))[0]["content"]
            for rule in ("34–38列", "宽高用同一个scale", "不能横拉", "紧裁无用透明边",
                         "上行时bitmap中心y递减", "1.2–2秒", "关键字再作短停", "不强套4.8秒",
                         "静态、缓慢或微动作时优先遵从", "抽象/纯灯光主题", "不强制高画布或角色滚动"):
                self.assertIn(rule, prompt)
            self.assertIn("不能横拉或把高图挤成5行", prompt)
            self.assertIn("不随手写-20到20造成长黑屏", prompt)

    def test_image_identity_and_text_only_identity_do_not_claim_the_same_evidence(self):
        image = ai.creative_messages(self.payload(images=True))[0]["content"]
        text = ai.creative_messages(self.payload())[0]["content"]
        self.assertIn("有图流程", image)
        self.assertNotIn("无图流程", image)
        for rule in ("参考的脸型", "五官位置与头身比例", "不用通用大眼脸替代身份", "不要把白色主体当背景去掉"):
            self.assertIn(rule, image)
        self.assertIn("无图流程", text)
        self.assertNotIn("有图流程", text)
        self.assertIn("无参考图不臆造精确五官细节", text)
        self.assertNotIn("人物肖像先对照参考的脸型", text)
        for prompt in (text, image):
            self.assertIn("数值检查不等于肖像相似或审美保证", prompt)
            self.assertNotIn("KAKA", prompt)
            self.assertNotIn("EVA", prompt)

    def test_dark_head_structure_occlusion_and_real_viewport_are_checked_together(self):
        prompt = ai.creative_messages(self.payload(images=True))[0]["content"]
        for rule in ("主体完整包围盒", "头顶/耳/手脚边距", "同色亮边与负形", "头顶、后脑、耳、颈要连续",
                     "不能靠白头块或光圈补形", "背景/旗帜/光束先画", "主体与身份锚点后画",
                     "装饰不能截断五官或头颈", "实际5行视窗", "必要时先等比完整短停再近扫"):
            self.assertIn(rule, prompt)

    def test_typography_has_its_own_clean_hold_and_mutually_exclusive_decoration(self):
        prompt = ai.creative_messages(self.payload(brief="干净的英文字标"))[0]["content"]
        for rule in ("文字用独立干净hold", "字形包围盒、字间距与边距", "装饰层互斥",
                     "额外笔画", "text仅ASCII 3×5字库"):
            self.assertIn(rule, prompt)
        self.assertIn("颜色大写#RRGGBB", prompt)
        self.assertIn("完整声明式recipe JSON对象", prompt)

    def test_explicit_timing_and_soft_static_user_intent_survive_new_defaults(self):
        brief = "静态白色图标，柔和微光，不需要纵向滚动"
        payload = self.payload(brief=brief, images=True)
        messages = ai.creative_messages(payload)
        prompt = messages[0]["content"]
        request = json.loads(messages[1]["content"][0]["text"])
        self.assertEqual(request["创作描述"], brief)
        self.assertEqual(request["固定播放参数"], {"frame_count": 80, "speed_ms": 30, "loop_seconds": 2.4})
        self.assertIn("总循环2.400秒", prompt)
        self.assertIn("用户明确要求静态时保留固定姿态", prompt)
        self.assertIn("白色、粉色、柔和、微光", prompt)
        self.assertIn("不是实机色准或亮度校准", prompt)

    def test_64_row_recipe_works_through_each_provider_without_expanding_retry_budget(self):
        rows = ["1" * 40 if y % 4 else "12" * 20 for y in range(64)]
        recipe = {"version": 1, "name": "纵向网格", "description": "有界64行网格向上经过五行窗口。",
                  "frame_count": 69, "speed_ms": 20, "palette": ["#FF0000", "#000000"],
                  "scenes": [{"name": "上行", "start": 0, "end": 69,
                              "top": [{"kind": "bitmap", "rows": rows, "palette": ["#FF0000", "#000000"],
                                       "scale": 1, "blend": "replace", "y": {"from": 9, "to": -8}}],
                              "keys": [{"kind": "scan", "color": "#FF0000", "axis": "x", "width": 0.6,
                                        "position": {"from": 0.2, "to": 0.8, "ease": "sine"}, "blend": "dominant"}]}]}
        for provider in ai.BASE_URLS:
            with self.subTest(provider=provider):
                payload = self.payload(provider=provider, brief="红色网格向上滚动，轴灯纯红")
                payload.update(frameCount=69, speedMs=20)
                opener = fixture.Opener(fixture.completion(json.dumps(recipe)))
                result = ai.generate(payload, opener=opener)
                self.assertFalse(result["repaired"])
                self.assertEqual(len(opener.calls), 1)
                request = opener.calls[0][0]
                self.assertEqual(request.get_header("User-agent"), "CyberboardStudio/0.4.2")
                self.assertEqual(result["design"]["ai"]["promptVersion"], 4)
                self.assertEqual(result["design"]["ai"]["recipe"]["scenes"][0]["top"][0]["rows"], rows)
                self.assertEqual(len(result["design"]["frames"]), 69)
                self.assertEqual(len(result["design"]["keyframes"][0]), 90)
                self.assertNotIn(fixture.SECRET, json.dumps(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
