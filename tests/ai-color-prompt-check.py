"""Offline color-policy regressions for shared AI and external Studio prompts.

Checks the actual messages serialized for every provider, including image and
soft/white requests. HTTP replies are in-memory; no model, hardware or secrets.
"""
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import kimi_ai as ai
from ai_images import normalize
from PIL import Image


BRIEFS = (
    "红帽角色和黄色金币，亮主题轴灯，4秒循环",
    "白色小猫与粉色花瓣，柔和微光，呼吸暗相需要熄灭，4秒循环",
    "蓝色静态标志，关闭轴灯",
    "火焰保留奶白火心，不要改成单色红",
)


def reference_image():
    pixels = Image.new("RGB", (3, 1))
    pixels.putdata([(255, 0, 0), (255, 255, 0), (255, 255, 255)])
    raw = io.BytesIO()
    pixels.save(raw, "PNG")
    return normalize(raw.getvalue())


class Reply(io.BytesIO):
    def __init__(self):
        super().__init__(json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}).encode())
        self.headers = {"Content-Type": "application/json"}


class MemoryHTTP:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return Reply()


class ColorPromptChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = reference_image()
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node is required to check the actual Studio prompt exporter")
        script = r"""
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const context={window:{}};vm.createContext(context);
vm.runInContext(fs.readFileSync(input.source,'utf8'),context);
const design={id:'color-test',name:'OLD-NAME',description:'OLD-DESCRIPTION',palette:['#ECA0C8','#FFFFFF'],frames:[Array(200).fill('#000000')],keyframes:[Array(90).fill('#000000')],speed_ms:40};
const before=JSON.stringify(design);
const prompts=input.briefs.map(brief=>context.window.StudioModel.prompt(brief,design));
const optedIn=context.window.StudioModel.prompt(input.briefs[0],design,{useReference:true});
process.stdout.write(JSON.stringify({prompts,optedIn,unchanged:before===JSON.stringify(design)}));
"""
        result = subprocess.run([node, "-e", script], input=json.dumps({"source": str(ROOT / "web/studio-model.js"), "briefs": BRIEFS}),
                                text=True, capture_output=True, check=True, timeout=20)
        cls.external = json.loads(result.stdout)

    def messages(self, brief=BRIEFS[0], image=False, provider="kimi-code"):
        payload = {"brief": brief, "frameCount": 12, "speedMs": 40,
                   "ai": {"provider": provider, "model": ai.DEFAULT_MODELS[provider],
                          "baseUrl": ai.BASE_URLS[provider][0], "apiKey": "offline-color-policy-secret"}}
        if image:
            payload["images"] = [copy.deepcopy(self.image)]
        return payload, ai.creative_messages(payload)

    def assert_color_contract(self, prompt):
        for text in ("#FF0000/#FFFF00/#0000FF", "白色、粉色、柔和、微光", "不强套纯主色",
                     "固有色", "摄影白高光/反光", "220–255", "100–220", "黑底保持#000000",
                     "弱尾可直接归黑", "微光、低亮、呼吸暗相或关闭轴灯的要求优先",
                     "不是实机色准或亮度校准", "dominant", "有效RGB最大通道整色择强",
                     "平手后层优先", "max只用于同色", "异色add/max都可能泛白", "replace覆盖"):
            self.assertIn(text, prompt)
        self.assertRegex(prompt, r"明确红/黄/蓝.*默认")
        self.assertNotIn("降低亮度衬托顶屏", prompt)

    def test_actual_wire_messages_share_policy_for_every_provider_and_image_mode(self):
        for provider in ai.BASE_URLS:
            for image in (False, True):
                with self.subTest(provider=provider, image=image):
                    payload, messages = self.messages(provider=provider, image=image)
                    memory = MemoryHTTP()
                    text, _ = ai.AIClient(ai.configuration(payload["ai"]), opener=memory).completion(messages)
                    self.assertEqual(text, "{}")
                    self.assertEqual(len(memory.requests), 1)
                    sent = json.loads(memory.requests[0].data)
                    self.assertEqual(sent["model"], ai.DEFAULT_MODELS[provider])
                    self.assert_color_contract(sent["messages"][0]["content"])
                    self.assertEqual(sent["messages"], messages)
                    self.assertNotIn(payload["ai"]["apiKey"], json.dumps(sent))

    def test_user_white_soft_dark_and_off_requests_survive_both_input_paths(self):
        for brief in BRIEFS:
            for image in (False, True):
                with self.subTest(brief=brief, image=image):
                    _, messages = self.messages(brief, image)
                    user = messages[1]["content"]
                    request = json.loads(user[0]["text"] if image else user)
                    self.assertEqual(request["创作描述"], brief)
                    self.assert_color_contract(messages[0]["content"])
                    self.assertEqual("有图流程" in messages[0]["content"], image)
                    self.assertEqual("无图流程" in messages[0]["content"], not image)

    def test_reference_input_is_not_mutated_or_replaced_by_style_palette(self):
        original = copy.deepcopy(self.image)
        _, messages = self.messages(image=True)
        self.assertEqual(self.image, original)
        self.assertEqual(messages[1]["content"][1]["type"], "image_url")
        self.assertTrue(messages[1]["content"][1]["image_url"]["url"].startswith("data:image/"))
        request = json.loads(messages[1]["content"][0]["text"])
        self.assertNotIn("可选参考风格", request)
        self.assertIn("需要白色的主体仍保留白色", messages[0]["content"])

    def test_old_axis_dimming_is_replaced_without_removing_topic_specific_softness(self):
        _, messages = self.messages("夜空里的萤火虫，只要微光")
        prompt = messages[0]["content"]
        self.assertIn("萤火虫建议", prompt)
        self.assertNotIn("火焰建议", prompt)
        self.assertIn("少量独立微光", prompt)
        self.assertIn("微光、低亮、呼吸暗相或关闭轴灯的要求优先", prompt)
        self.assertNotIn("降低亮度衬托顶屏", prompt)

    def test_backend_policy_is_once_and_keeps_json_recipe_and_size_constraints(self):
        _, messages = self.messages()
        prompt = messages[0]["content"]
        self.assertEqual(prompt.count(ai.COLOR_GUIDANCE), 1)
        self.assertLess(len(prompt), 22000)
        self.assertIn("只返回一个完整声明式recipe JSON对象", prompt)
        self.assertIn("逐层明确palette", prompt)
        self.assertIn("黑五官才能遮背景", prompt)
        self.assertIn("只能使用合同图元", prompt)

    def test_serialized_model_contract_supports_the_recommended_blend(self):
        _, messages = self.messages()
        schema = json.loads(messages[0]["content"].split("\n配方JSON Schema：\n", 1)[1])
        blends = [node["properties"]["blend"] for node in schema["$defs"].values()
                  if isinstance(node, dict) and "blend" in node.get("properties", {})]
        self.assertTrue(blends, "actual model contract must describe layer blending")
        for blend in blends:
            if "$ref" in blend:
                blend = schema["$defs"][blend["$ref"].rsplit("/", 1)[1]]
            self.assertIn("dominant", blend["enum"])

    def test_external_export_has_same_color_contract_for_all_briefs(self):
        for brief, prompt in zip(BRIEFS, self.external["prompts"]):
            with self.subTest(brief=brief):
                self.assertIn(brief, prompt)
                self.assert_color_contract(prompt)
                self.assertIn("最终仍只输出下述RGB数组，不增加混色或图层字段", prompt)
                self.assertIn("frames与keyframes必须是直接二维颜色数组", prompt)
                self.assertIn("预览、导出与同步使用同一RGB", prompt)
                self.assertIn("不做仅预览提亮或全局gamma抬黑", prompt)
                self.assertNotIn("用户明确要求高亮时再使用", prompt)

    def test_export_does_not_mutate_pixels_or_turn_style_reference_on(self):
        self.assertTrue(self.external["unchanged"])
        for prompt in self.external["prompts"]:
            self.assertNotIn("OLD-NAME", prompt)
            self.assertNotIn("OLD-DESCRIPTION", prompt)
        self.assertIn("OLD-NAME", self.external["optedIn"])
        self.assertIn("#FFFFFF", self.external["prompts"][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
