#!/usr/bin/env python3
"""Pixel-quality regression examples compiled offline; no model, image or USB I/O."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from ai_quality import inspect_design_quality
from lighting_recipe import compile_recipe


def solid(color="#FFFFFF", **extra):
    return {"kind": "solid", "color": color, **extra}


def scene(start, end, top, keys=None):
    return {"name": "示例", "start": start, "end": end, "top": top, "keys": keys or []}


def compiled(scenes, speed=40):
    return compile_recipe({"version": 1, "name": "像素检查样例", "description": "",
                           "frame_count": scenes[-1]["end"], "speed_ms": speed,
                           "palette": ["#00DCF0", "#9A24FF"], "scenes": scenes})


def gap_design():
    return compiled([scene(0, 12, [solid()]), scene(12, 44, []), scene(44, 64, [solid("#00DCF0")])])


def codes(report, field="issues"):
    return {item["code"] for item in report[field]}


class QualityChecks(unittest.TestCase):
    def test_offscreen_compiled_subject_is_repairable_not_a_successful_black_design(self):
        design = compiled([scene(0, 40, [{"kind": "bitmap", "rows": ["11", "11"],
                                        "palette": ["#FFFFFF"], "x": 3, "y": 20}])])
        result = inspect_design_quality(design, brief="小猫从左走到右", has_images=True)
        self.assertFalse(result["passed"])
        self.assertIn("all_dark_output", codes(result))
        self.assertEqual(result["metrics"]["regions"]["top"]["visible_leds_max"], 0)

    def test_almost_whole_loop_empty_is_detected_without_rejecting_spatially_sparse_stars(self):
        design = compiled([scene(0, 98, []), scene(98, 100, [solid()])])
        result = inspect_design_quality(design, brief="一道光横向流动")
        self.assertIn("mostly_dark_output", codes(result))
        self.assertEqual(result["metrics"]["regions"]["top"]["dark_frame_fraction"], 0.98)
        self.assertTrue(inspect_design_quality(design, brief="稀疏星空，偶尔有星星闪烁")["passed"])

    def test_unrequested_long_interior_black_scene_is_an_issue(self):
        result = inspect_design_quality(gap_design(), brief="青白光束保持可见并发生碰撞")
        self.assertIn("long_dark_gap", codes(result))
        self.assertEqual(result["metrics"]["regions"]["top"]["longest_interior_dark_ms"], 1280)

    def test_intentional_dark_holds_and_strobes_are_not_rejected(self):
        for brief in ("白光后保留黑场停顿，再出现青光", "a deliberate dark pause between two flashes",
                      "频闪，亮一下再熄灭", "strobe flashes with dark holds"):
            with self.subTest(brief=brief):
                result = inspect_design_quality(gap_design(), brief=brief)
                self.assertTrue(result["passed"], result)
                self.assertIn("long_dark_gap", codes(result, "warnings"))

    def test_negating_an_exception_does_not_grant_it(self):
        for brief in ("不要黑场，保持主体可见", "avoid dark pauses", "no black hold"):
            with self.subTest(brief=brief):
                self.assertIn("long_dark_gap", codes(inspect_design_quality(gap_design(), brief=brief)))
        still = compiled([scene(0, 40, [solid()])])
        self.assertIn("static_output", codes(inspect_design_quality(still, brief="not static, animate the light")))

    def test_entrance_exit_darkness_is_a_warning_without_inventing_a_bad_loop(self):
        design = compiled([scene(0, 30, []), scene(30, 70, [solid()]), scene(70, 100, [])])
        result = inspect_design_quality(design, brief="角色追逐，从画面外入场再离场")
        self.assertTrue(result["passed"], result)
        self.assertIn("edge_dark_hold", codes(result, "warnings"))
        self.assertEqual(result["metrics"]["regions"]["top"]["longest_dark_loop_ms"], 2400)

    def test_accidental_static_is_detected_but_static_and_solid_color_requests_pass(self):
        design = compiled([scene(0, 40, [solid("#800000")], [solid("#050000")])])
        self.assertIn("static_output", codes(inspect_design_quality(design, brief="让红光在键盘上流动")))
        for brief in ("静态红色背景", "纯色常亮", "不需要动画", "不要动画", "a static red poster",
                      "solid color", "no animation", "no motion", "don't animate", "a still image"):
            with self.subTest(brief=brief):
                self.assertTrue(inspect_design_quality(design, brief=brief)["passed"])
        self.assertIn("static_output", codes(inspect_design_quality(design, brief="纯色呼吸动画")))
        self.assertIn("static_output", codes(inspect_design_quality(design, brief="the cat is still moving")))

    def test_model_description_cannot_grant_a_static_exception(self):
        design = compiled([scene(0, 40, [solid()])])
        design["description"] = "用户需要静态常亮 no animation"
        self.assertIn("static_output", codes(inspect_design_quality(design, brief="制作流动波浪")))

    def test_one_pixel_moving_star_is_not_rejected_for_low_led_coverage(self):
        design = compiled([scene(0, 60, [{"kind": "bitmap", "rows": ["1"], "palette": ["#FFFFFF"],
                                        "x": {"from": 0.1, "to": 0.9}, "y": 0.5}])])
        result = inspect_design_quality(design, brief="极简星空中一颗星星缓慢滑过")
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["metrics"]["regions"]["top"]["visible_leds_max"], 1)
        self.assertNotIn("loop_seam_jump", codes(result))

    def test_intentional_dim_and_complete_off_are_distinct_from_accidental_empty(self):
        dim = compiled([scene(0, 40, [solid("#050000")])])
        self.assertTrue(inspect_design_quality(dim, brief="夜间低亮纯色常亮")["passed"])
        self.assertIn("near_black_output", codes(inspect_design_quality(dim, brief="高亮光束动画")))
        off = compiled([scene(0, 40, [])])
        self.assertTrue(inspect_design_quality(off, brief="关闭所有灯，全程全黑")["passed"])
        self.assertFalse(inspect_design_quality(off, brief="黑场之后恢复主体")["passed"])

    def test_keys_only_has_a_real_checked_target_and_respects_reserved_positions(self):
        design = compiled([scene(0, 40, [], [{"kind": "wave", "color": "#FFFFFF", "frequency": 1,
                                            "phase": {"from": 0, "to": 1}}])])
        result = inspect_design_quality(design, brief="只要轴灯，波浪呼吸")
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["metrics"]["regions"]["keys"]["active_led_positions"], 83)
        self.assertFalse(inspect_design_quality(design, brief="顶屏和轴灯联动")["passed"])

    def test_dense_seam_jump_blocks_only_explicit_seamless_request(self):
        design = compiled([scene(0, 40, [solid(opacity={"from": 0.2, "to": 1})])])
        result = inspect_design_quality(design, brief="无缝循环，首尾一致")
        self.assertIn("loop_seam_jump", codes(result))
        values = result["metrics"]["regions"]["top"]
        self.assertGreater(values["loop_seam_mae"], values["step_mae_max"] * 2)
        result = inspect_design_quality(design, brief="白光渐亮")
        self.assertTrue(result["passed"], result)
        self.assertIn("loop_seam_jump", codes(result, "warnings"))

    def test_intentional_color_cuts_do_not_look_like_a_broken_seam(self):
        design = compiled([scene(0, 10, [solid("#FF0000")]), scene(10, 20, [solid("#0000FF")])])
        result = inspect_design_quality(design, brief="红蓝交替频闪")
        self.assertTrue(result["passed"], result)
        self.assertNotIn("loop_seam_jump", codes(result) | codes(result, "warnings"))

    def test_bitmap_global_palette_inheritance_is_only_a_warning(self):
        recipe = {"version": 1, "name": "像素徽标", "description": "", "frame_count": 20,
                  "speed_ms": 40, "palette": ["#00DCF0", "#9A24FF"],
                  "scenes": [scene(0, 20, [{"kind": "bitmap", "rows": ["121", "212", "121"]}])]}
        design = compile_recipe(recipe)
        design["ai"] = {"recipe": recipe}
        result = inspect_design_quality(design, brief="静态像素徽标", has_images=True)
        self.assertTrue(result["passed"], result)
        self.assertIn("bitmap_palette_inherited", codes(result, "warnings"))
        self.assertNotIn("bitmap_palette_inherited", codes(result))

    def test_report_is_json_safe_deterministic_and_does_not_modify_or_read_files(self):
        design = compiled([scene(0, 40, [solid()])])
        original = copy.deepcopy(design)
        with patch("builtins.open", side_effect=AssertionError("quality inspection did file I/O")):
            first = inspect_design_quality(design, brief="静态海报")
            second = inspect_design_quality(design, brief="静态海报")
        self.assertEqual(first, second)
        self.assertEqual(design, original)
        json.dumps(first, allow_nan=False)
        self.assertIsNone(first["metrics"]["regions"]["top"]["loop_seam_vs_p95"])

    def test_bad_frame_inputs_return_bounded_json_reports(self):
        valid = compiled([scene(0, 20, [solid()])])
        cases = [None, {}, {**valid, "speed_ms": float("nan")}, {**valid, "speed_ms": True},
                 {**valid, "frames": [["#FFFFFF"]]}, {**valid, "keyframes": []},
                 {**valid, "frames": [["wrong"] * 200]}, {**valid, "frames": valid["frames"] * 20}]
        for design in cases:
            with self.subTest(kind=type(design).__name__):
                result = inspect_design_quality(design)
                self.assertFalse(result["passed"])
                self.assertTrue(result["issues"])
                json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
