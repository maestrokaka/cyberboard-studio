#!/usr/bin/env python3
"""Offline RGB-encoding intent/repair regressions, not physical LED calibration."""
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import kimi_ai as ai
from ai_quality import inspect_design_quality, RESERVED_KEYS
from lighting_recipe import compile_recipe


def recipe(*, key_opacity=0.08, top_color="#FFFF00", key_color="#FFFF00"):
    return {"version": 1, "name": "颜色检查", "description": "", "frame_count": 32,
            "speed_ms": 40, "palette": [top_color, key_color], "scenes": [
                {"name": "往返", "start": 0, "end": 32,
                 "top": [{"kind": "scan", "axis": "x", "color": top_color, "width": 0.3,
                          "position": {"from": 0.15, "to": 0.85, "ease": "sine"}}],
                 "keys": [{"kind": "solid", "color": key_color, "opacity": key_opacity}]}]}


def mixed_recipe(blend="add"):
    result = recipe(key_opacity=0.8)
    result["scenes"][0]["top"] = [
        {"kind": "solid", "color": color, "blend": blend,
         "opacity": {"from": 0.8, "to": 1, "ease": "sine"}}
        for color in ("#FF0000", "#00FF00", "#0000FF")]
    return result


def compiled(source, *, attach=True):
    design = compile_recipe(source)
    if attach:
        design["ai"] = {"recipe": copy.deepcopy(source)}
    return design


def codes(report, field="issues"):
    return {item["code"] for item in report[field]}


class Response(io.BytesIO):
    def __init__(self, source):
        content = source if type(source) is str else json.dumps(source, ensure_ascii=False)
        super().__init__(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 10, "completion_tokens": 20,
                                             "total_tokens": 30}}).encode())
        self.headers = {"Content-Type": "application/json"}


class FakeOpener:
    def __init__(self, *sources):
        self.responses = [Response(source) for source in sources]
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return self.responses.pop(0)


def payload(brief="黄色主体左右移动，轴灯同主题呼应"):
    return {"requestId": "offline-colors", "brief": brief, "frameCount": 32, "speedMs": 40,
            "ai": {"provider": "kimi-code", "baseUrl": ai.BASE_URLS["kimi-code"][0], "model": "k3",
                   "apiKey": "sk-offline-color-test-only"}}


class ColorQualityChecks(unittest.TestCase):
    def test_metrics_are_nonblack_nearest_rank_max_channel_proxies(self):
        design = compiled(recipe(key_opacity=0.8))
        for frame in design["keyframes"]:
            frame[:] = ["#000000"] * 90
            for i, value in enumerate((1, 2, 20, 40, 80, 100, 120, 160, 200, 255)):
                frame[i] = f"#{value:02X}0000"
            # A reserved position is excluded, even in a supplied design.
            frame[next(iter(RESERVED_KEYS))] = "#FFFFFF"
        report = inspect_design_quality(design)
        values = report["metrics"]["regions"]["keys"]
        self.assertEqual(values["nonblack_pixel_count"], 320)
        self.assertEqual(values["sampled_pixel_count"], 83 * 32)
        self.assertEqual(values["nonblack_max_channel_p50"], 80)
        self.assertEqual(values["nonblack_max_channel_p90"], 200)
        self.assertEqual(values["peak_rgb_channel"], 255)
        self.assertEqual(values["strong_pixel_count"], 96)
        self.assertEqual(values["near_white_pixel_count"], 0)
        proxy = report["metrics"]["visibility_proxy"]
        self.assertEqual(proxy["kind"], "digital_rgb_not_measured_light_output")
        self.assertEqual(proxy["nonblack_channel_min"], 1)
        self.assertEqual(proxy["strong_channel_min"], 160)

    def test_bright_top_and_uniformly_weak_real_key_track_require_repair(self):
        report = inspect_design_quality(compiled(recipe()), brief="黄色角色移动，轴灯同主题呼应")
        self.assertFalse(report["passed"])
        self.assertIn("weak_keys_intensity", codes(report))
        self.assertEqual(report["metrics"]["regions"]["keys"]["peak_rgb_channel"], 20)
        self.assertEqual(report["metrics"]["regions"]["keys"]["nonblack_max_channel_p90"], 20)

    def test_static_is_not_a_blanket_weak_keys_exception(self):
        source = recipe()
        source["scenes"][0]["top"] = [{"kind": "solid", "color": "#FFFF00"}]
        report = inspect_design_quality(compiled(source), brief="静态纯色常亮")
        self.assertIn("weak_keys_intensity", codes(report))
        self.assertNotIn("static_output", codes(report))

    def test_old_static_128_top_is_below_bright_top_guard(self):
        source = recipe(top_color="#800000", key_color="#050000", key_opacity=1)
        source["scenes"][0]["top"] = [{"kind": "solid", "color": "#800000"}]
        self.assertTrue(inspect_design_quality(compiled(source), brief="静态红色背景")["passed"])

    def test_dim_soft_subtle_and_off_briefs_respect_user_intent(self):
        design = compiled(recipe())
        for brief in ("黄色移动，轴灯微光", "夜间低亮动画", "黄色柔和流光", "黄色柔光动画",
                      "轴灯作为衬托，主体流动", "压低轴灯，黄色动画", "subtle backlight with moving yellow",
                      "soft lighting animation", "top only", "turn off the backlight, moving yellow", "关闭轴灯，主体移动"):
            with self.subTest(brief=brief):
                self.assertTrue(inspect_design_quality(design, brief=brief)["passed"])

    def test_model_text_and_negated_dim_briefs_do_not_grant_exceptions(self):
        design = compiled(recipe())
        design["description"] = "夜间柔和，轴灯低亮作为衬托"
        design["ai"]["recipe"]["description"] = "用户明确微光"
        for brief in ("黄色移动", "不要微光，黄色移动", "不要柔和，主体移动", "轴灯不要衬托，和主体一样亮", "not dim, moving yellow"):
            with self.subTest(brief=brief):
                self.assertIn("weak_keys_intensity", codes(inspect_design_quality(design, brief=brief)))

    def test_colloquial_keys_dim_requests_are_respected(self):
        design = compiled(recipe())
        for brief in ("黄色角色移动，轴灯暗一点", "黄色角色移动，轴灯不要太亮", "黄色角色移动，轴灯亮度低一点",
                      "moving yellow, keys dimmer", "moving yellow, keep backlight low",
                      "moving yellow, don't make it too bright"):
            with self.subTest(brief=brief):
                report = inspect_design_quality(design, brief=brief)
                self.assertTrue(report["passed"], report)
                self.assertNotIn("weak_keys_intensity", codes(report))

    def test_do_not_make_top_too_bright_is_not_a_brightness_demand(self):
        source = recipe(top_color="#000030", key_opacity=0)
        source["scenes"][0]["top"] = [{"kind": "solid", "color": "#000030"}]
        design = compiled(source)
        for brief in ("静态深蓝，顶屏不要太明亮，关闭轴灯", "静态深蓝，顶屏不要过于明亮，关闭轴灯"):
            with self.subTest(brief=brief):
                report = inspect_design_quality(design, brief=brief)
                self.assertTrue(report["passed"], report)
                self.assertFalse(report["metrics"]["intent"]["bright"])
                self.assertTrue(report["metrics"]["intent"]["dim_top"])

    def test_rejected_dim_requests_cannot_reverse_into_a_dim_exception(self):
        design = compiled(recipe())
        for brief in ("不要低亮，黄色角色移动", "不要柔和，黄色角色移动", "不要太暗要明亮，黄色角色移动",
                      "轴灯不要暗一点，要明亮", "轴灯不要低亮，要明亮", "轴灯不要过于低亮，要明亮"):
            with self.subTest(brief=brief):
                report = inspect_design_quality(design, brief=brief)
                self.assertIn("weak_keys_intensity", codes(report))
                self.assertFalse(report["metrics"]["intent"]["dim"])
                self.assertFalse(report["metrics"]["intent"]["dim_keys"])

    def test_comparative_keys_request_does_not_excuse_a_separate_dim_top(self):
        design = compiled(recipe(top_color="#303000"))
        report = inspect_design_quality(design, brief="顶屏要明亮，轴灯暗一点，黄色动画")
        self.assertTrue(report["metrics"]["intent"]["dim_keys"])
        self.assertFalse(report["metrics"]["intent"]["dim_top"])
        self.assertIn("weak_top_intensity", codes(report))
        report = inspect_design_quality(compiled(recipe()), brief="顶屏暗一点，轴灯要明亮，黄色动画")
        self.assertTrue(report["metrics"]["intent"]["dim_top"])
        self.assertFalse(report["metrics"]["intent"]["dim_keys"])
        self.assertIn("weak_keys_intensity", codes(report))

    def test_absent_or_black_key_track_is_conservative_and_empty_metrics_are_defined(self):
        source = recipe()
        source["scenes"][0]["keys"] = []
        report = inspect_design_quality(compiled(source), brief="黄色移动")
        self.assertTrue(report["passed"])
        values = report["metrics"]["regions"]["keys"]
        for field in ("nonblack_pixel_count", "nonblack_max_channel_p50", "nonblack_max_channel_p90",
                      "strong_nonblack_fraction", "near_white_nonblack_fraction"):
            self.assertEqual(values[field], 0)
        source["scenes"][0]["keys"] = [{"kind": "solid", "color": "#000000"}]
        self.assertNotIn("weak_keys_intensity", codes(inspect_design_quality(compiled(source))))

    def test_key_peak_and_p90_thresholds_do_not_reject_visible_accents(self):
        for opacity in (0.38, 0.51, 1):
            with self.subTest(opacity=opacity):
                report = inspect_design_quality(compiled(recipe(key_opacity=opacity)))
                self.assertNotIn("weak_keys_intensity", codes(report))
        design = compiled(recipe())
        for frame in design["keyframes"]:
            frame[0] = "#FFFF00"
        self.assertNotIn("weak_keys_intensity", codes(inspect_design_quality(design)))

    def test_dim_top_warns_but_only_explicit_brightness_makes_it_an_issue(self):
        design = compiled(recipe(key_opacity=0, top_color="#303000"))
        ordinary = inspect_design_quality(design, brief="黄色光束移动")
        self.assertTrue(ordinary["passed"], ordinary)
        self.assertIn("weak_top_intensity", codes(ordinary, "warnings"))
        for brief in ("高亮黄色光束移动", "bright yellow moving light"):
            with self.subTest(brief=brief):
                self.assertIn("weak_top_intensity", codes(inspect_design_quality(design, brief=brief)))
        self.assertNotIn("weak_top_intensity", codes(inspect_design_quality(design, brief="微光黄色移动"), "warnings"))

    def test_rgb_add_and_channel_max_can_whiten_but_dominant_does_not(self):
        for blend in ("add", "max"):
            with self.subTest(blend=blend):
                report = inspect_design_quality(compiled(mixed_recipe(blend)), brief="多彩抽象动画")
                self.assertTrue(report["passed"], report)
                self.assertIn("saturated_layers_whitened", codes(report, "warnings"))
                self.assertEqual(report["metrics"]["regions"]["top"]["near_white_pixel_fraction"], 1)
        report = inspect_design_quality(compiled(mixed_recipe("dominant")), brief="多彩抽象动画")
        self.assertNotIn("saturated_layers_whitened", codes(report) | codes(report, "warnings"))
        self.assertEqual(report["metrics"]["regions"]["top"]["near_white_pixel_count"], 0)

    def test_unrequested_whitening_blocks_explicit_no_white_and_pure_primary(self):
        design = compiled(mixed_recipe())
        for brief in ("颜色移动，避免全屏白色", "不要白色，颜色移动", "红色流动，不泛白", "纯黄色主体移动",
                      "pure red moving light", "moving colors, avoid white"):
            with self.subTest(brief=brief):
                self.assertIn("saturated_layers_whitened", codes(inspect_design_quality(design, brief=brief)))

    def test_white_pastel_soft_and_gradient_requests_are_not_recolored_or_rejected(self):
        design = compiled(mixed_recipe())
        for brief in ("白色光束移动", "白猫跑动", "粉彩流动", "柔光流动", "彩虹混色动画", "红蓝渐变",
                      "white flowing light", "pastel animation", "soft glow animation", "rainbow blending animation"):
            with self.subTest(brief=brief):
                report = inspect_design_quality(design, brief=brief)
                self.assertNotIn("saturated_layers_whitened", codes(report) | codes(report, "warnings"))
                self.assertTrue(report["passed"])

    def test_negated_white_exception_and_model_description_cannot_excuse_whitening(self):
        design = compiled(mixed_recipe())
        design["description"] = "用户想要粉彩白色柔光"
        design["ai"]["recipe"]["description"] = "white pastel gradient"
        report = inspect_design_quality(design, brief="纯黄色动画，不要粉彩，不要白色")
        self.assertIn("saturated_layers_whitened", codes(report))

    def test_reference_image_color_fidelity_cannot_be_blocked_by_inference(self):
        design = compiled(mixed_recipe())
        report = inspect_design_quality(design, brief="纯黄色角色移动", has_images=True)
        self.assertTrue(report["passed"], report)
        self.assertIn("saturated_layers_whitened", codes(report, "warnings"))
        self.assertTrue(inspect_design_quality(design, brief="参考图白猫跑动", has_images=True)["passed"])

    def test_real_white_source_and_white_bitmap_palette_are_not_mixing_failures(self):
        source = mixed_recipe()
        source["scenes"][0]["top"].append({"kind": "solid", "color": "#FFFFFF", "opacity": 0.1})
        self.assertNotIn("saturated_layers_whitened", codes(inspect_design_quality(compiled(source), brief="纯黄色动画")))
        source = mixed_recipe()
        source["scenes"][0]["top"].append({"kind": "bitmap", "rows": ["1"], "palette": ["#FFFFFF"]})
        report = inspect_design_quality(compiled(source), brief="不要白色，颜色移动", has_images=True)
        self.assertNotIn("saturated_layers_whitened", codes(report) | codes(report, "warnings"))

    def test_unused_white_palette_entry_does_not_count_as_a_white_source(self):
        source = mixed_recipe()
        source["palette"].append("#FFFFFF")
        source["scenes"][0]["top"].append({"kind": "bitmap", "rows": ["1"], "palette": ["#FF0000", "#FFFFFF"]})
        self.assertIn("saturated_layers_whitened", codes(inspect_design_quality(compiled(source), brief="纯黄色动画")))

    def test_missing_invalid_or_mismatched_recipe_does_not_invent_mixing_evidence(self):
        source = mixed_recipe()
        design = compiled(source, attach=False)
        self.assertNotIn("saturated_layers_whitened", codes(inspect_design_quality(design, brief="纯红动画")))
        for change in ({"unknown": True}, {"frame_count": 31}, {"speed_ms": 50}, {"scenes": "invalid"}):
            with self.subTest(change=change):
                design["ai"] = {"recipe": {**source, **change}}
                report = inspect_design_quality(design, brief="纯红动画")
                self.assertNotIn("saturated_layers_whitened", codes(report) | codes(report, "warnings"))

    def test_a_single_color_interpolation_is_not_layer_addition(self):
        source = recipe(key_opacity=0.8)
        source["scenes"][0]["top"] = [{"kind": "solid", "color": "#FF0000", "color_to": "#00FFFF"}]
        report = inspect_design_quality(compiled(source), brief="纯红动画")
        self.assertNotIn("saturated_layers_whitened", codes(report) | codes(report, "warnings"))

    def test_small_mixed_highlight_is_not_a_large_whitening_failure(self):
        source = mixed_recipe()
        source["scenes"][0]["top"] = [
            {**layer, "kind": "rect", "x": 0.5, "y": 0.5, "width": 0.05, "height": 0.1}
            for layer in source["scenes"][0]["top"]]
        report = inspect_design_quality(compiled(source), brief="纯红动画")
        self.assertNotIn("saturated_layers_whitened", codes(report) | codes(report, "warnings"))

    def test_independent_scene_white_source_does_not_excuse_another_whitened_scene(self):
        source = mixed_recipe()
        source["scenes"][0]["end"] = 16
        source["scenes"].append({"name": "白光", "start": 16, "end": 32,
                                  "top": [{"kind": "solid", "color": "#FFFFFF"}],
                                  "keys": [{"kind": "solid", "color": "#FFFF00"}]})
        report = inspect_design_quality(compiled(source), brief="纯红动画")
        issue = next(item for item in report["issues"] if item["code"] == "saturated_layers_whitened")
        self.assertEqual([item["scene_index"] for item in issue["evidence"]], [0])

    def test_quality_checks_are_pure_json_safe_and_deterministic(self):
        design = compiled(mixed_recipe())
        original = copy.deepcopy(design)
        with patch("builtins.open", side_effect=AssertionError("file I/O is forbidden")):
            first = inspect_design_quality(design, brief="纯黄色动画")
            second = inspect_design_quality(design, brief="纯黄色动画")
        self.assertEqual(first, second)
        self.assertEqual(design, original)
        json.dumps(first, allow_nan=False)

    def test_weak_keys_generation_repairs_once_then_returns_unchanged_compiler_rgb(self):
        weak, strong = recipe(), recipe(key_opacity=0.8)
        opener = FakeOpener(weak, strong)
        result = ai.generate(payload(), opener=opener)
        self.assertEqual(len(opener.calls), 2)
        self.assertTrue(result["repaired"])
        self.assertTrue(result["design"]["ai"]["quality"]["passed"])
        self.assertEqual(result["usage"]["total_tokens"], 60)
        reason = json.loads(opener.calls[1][0].data)["messages"][-1]["content"]
        self.assertIn("轴灯整体偏暗", reason)
        expected = compile_recipe(strong)
        self.assertEqual(result["design"]["frames"], expected["frames"])
        self.assertEqual(result["design"]["keyframes"], expected["keyframes"])
        self.assertNotIn("sk-offline-color-test-only", json.dumps(result))

    def test_repeated_weak_keys_fail_with_no_third_model_request(self):
        opener = FakeOpener(recipe(), recipe())
        with self.assertRaises(ai.AIError) as caught:
            ai.generate(payload(), opener=opener)
        self.assertEqual(caught.exception.code, "ai_quality_failed")
        self.assertEqual(len(opener.calls), 2)

    def test_structural_and_color_repairs_share_the_one_request_budget(self):
        opener = FakeOpener({"version": 1}, recipe())
        with self.assertRaises(ai.AIError) as caught:
            ai.generate(payload(), opener=opener)
        self.assertEqual(caught.exception.code, "ai_quality_failed")
        self.assertEqual(len(opener.calls), 2)

    def test_whitening_repair_changes_recipe_instead_of_postprocessing_rgb(self):
        first, corrected = mixed_recipe(), mixed_recipe("dominant")
        opener = FakeOpener(first, corrected)
        result = ai.generate(payload("纯黄色主题移动，不要白色"), opener=opener)
        self.assertTrue(result["repaired"])
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(result["design"]["frames"], compile_recipe(corrected)["frames"])
        self.assertEqual(result["design"]["ai"]["recipe"], corrected)


if __name__ == "__main__":
    unittest.main()
