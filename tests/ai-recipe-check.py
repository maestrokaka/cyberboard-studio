#!/usr/bin/env python3
"""Offline contract and rendering checks; no model API, credentials or USB."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import lighting_recipe as compiler


def sample_recipe(frames=16):
    return {"version": 1, "name": "纵向折叠", "description": "光带上升，轴灯呼应。", "frame_count": frames,
            "speed_ms": 40, "palette": ["#12E5FF", "#FF460A"],
            "scenes": [{"name": "上升", "start": 0, "end": frames,
                        "top": [{"kind": "scan", "color": "#12E5FF", "axis": "y",
                                 "position": {"from": 1, "to": 0, "ease": "linear"}, "width": 0.4}],
                        "keys": [{"kind": "wave", "color": "#FF460A", "angle": 90,
                                  "frequency": 2, "phase": {"from": 0, "to": 2, "ease": "linear"}}]}]}


class RecipeChecks(unittest.TestCase):
    def reject(self, recipe, contains=None):
        with self.assertRaises(compiler.RecipeError) as context:
            compiler.compile_recipe(recipe)
        if contains:
            self.assertIn(contains, str(context.exception))

    def test_compiled_design_matches_hardware_frame_shape(self):
        design = compiler.compile_recipe(sample_recipe())
        self.assertEqual(design["origin"], "kimi")
        self.assertEqual(design["frame_count"], 16)
        self.assertEqual(len(design["stages"]), 16)
        self.assertEqual(design["speed_ms"], 40)
        for field, width in (("frames", 200), ("keyframes", 90)):
            self.assertEqual(len(design[field]), 16)
            for frame in design[field]:
                self.assertEqual(len(frame), width)
                self.assertTrue(all(compiler.HEX_COLOR.fullmatch(c) for c in frame))
        for frame in design["keyframes"]:
            self.assertTrue(all(frame[i] == "#000000" for i in compiler.RESERVED_LEDS))

    def test_normalized_key_layout_retains_three_independent_space_lamps(self):
        self.assertEqual(len(compiler.KEY_COORDINATES), 90)
        self.assertEqual({i for i, p in enumerate(compiler.KEY_COORDINATES) if p is None},
                         compiler.RESERVED_LEDS)
        spaces = [compiler.KEY_COORDINATES[i] for i in (79, 80, 81)]
        self.assertLess(spaces[0][0], spaces[1][0])
        self.assertLess(spaces[1][0], spaces[2][0])
        self.assertEqual([p[1] for p in spaces], [1, 1, 1])
        recipe = sample_recipe(1)
        recipe["scenes"][0]["keys"] = [{"kind": "scan", "color": "#FFFFFF", "axis": "x",
                                          "position": spaces[1][0], "width": 0.1}]
        frame = compiler.compile_recipe(recipe)["keyframes"][0]
        self.assertEqual(frame[80], "#FFFFFF")
        self.assertEqual(frame[79], "#000000")
        self.assertEqual(frame[81], "#000000")

    def test_upward_scroll_has_correct_top_row_direction_and_endpoints(self):
        design = compiler.compile_recipe(sample_recipe(5))
        first, last = design["frames"][0], design["frames"][-1]
        self.assertEqual(first[:160], ["#000000"] * 160)
        self.assertEqual(first[160:], ["#12E5FF"] * 40)
        self.assertEqual(last[:40], ["#12E5FF"] * 40)
        self.assertEqual(last[40:], ["#000000"] * 160)
        self.assertNotEqual(design["frames"][1], design["frames"][3])

    def test_scene_timeline_and_stage_names_are_exact(self):
        recipe = sample_recipe(4)
        recipe["scenes"] = [
            {"name": "起势", "start": 0, "end": 2, "top": [{"kind": "solid", "color": "#FF0000"}], "keys": []},
            {"name": "折叠", "start": 2, "end": 4, "top": [], "keys": [{"kind": "solid", "color": "#0000FF"}]}]
        design = compiler.compile_recipe(recipe)
        self.assertEqual(design["stages"], ["起势", "起势", "折叠", "折叠"])
        self.assertEqual(design["frames"][0], ["#FF0000"] * 200)
        self.assertEqual(design["frames"][2], ["#000000"] * 200)
        self.assertEqual(design["keyframes"][0], ["#000000"] * 90)
        self.assertEqual(design["keyframes"][2][80], "#0000FF")

    def test_distinct_geometry_and_palette_create_distinct_works(self):
        first = sample_recipe(4)
        second = copy.deepcopy(first)
        second["palette"] = ["#FF00AA"]
        second["scenes"][0]["top"] = [{"kind": "rect", "color": "#FF00AA", "width": 0.3, "height": 1,
                                         "x": {"from": 0.2, "to": 0.8}, "angle": {"from": 0, "to": 45}}]
        a, b = compiler.compile_recipe(first), compiler.compile_recipe(second)
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotEqual(a["frames"], b["frames"])
        self.assertEqual(b["palette"], ["#FF00AA"])

    def test_output_is_deterministic_and_does_not_modify_input(self):
        recipe = sample_recipe(8)
        recipe["scenes"][0]["top"] = [
            {"kind": "noise", "color": "#12E5FF", "seed": 123},
            {"kind": "particles", "color": "#FF460A", "seed": 456, "count": 8, "speed": 1.5}]
        original = copy.deepcopy(recipe)
        self.assertEqual(compiler.compile_recipe(recipe), compiler.compile_recipe(recipe, reference={"name": "ignored pixels"}))
        self.assertEqual(recipe, original)
        changed = copy.deepcopy(recipe)
        changed["scenes"][0]["top"][0]["seed"] = 124
        self.assertNotEqual(compiler.compile_recipe(recipe)["frames"], compiler.compile_recipe(changed)["frames"])

    def test_all_fixed_primitives_render_nonempty_without_external_code(self):
        examples = {
            "solid": {}, "wave": {}, "scan": {"position": 0.5, "width": 0.4},
            "ring": {"radius": 0.4, "width": 0.3}, "rect": {"width": 0.5, "height": 0.8},
            "line": {"width": 0.4}, "checker": {}, "noise": {"threshold": 0.2},
            "particles": {"radius": 0.3, "count": 12}, "text": {"text": "CYBER"},
        }
        for kind, fields in examples.items():
            with self.subTest(kind=kind):
                recipe = sample_recipe(3)
                recipe["scenes"][0]["top"] = [{"kind": kind, "color": "#EDFBFF", **fields}]
                with patch("builtins.eval", side_effect=AssertionError("model code evaluated")), \
                     patch("builtins.exec", side_effect=AssertionError("model code executed")), \
                     patch("builtins.open", side_effect=AssertionError("compiler attempted file I/O")):
                    design = compiler.compile_recipe(recipe)
                self.assertTrue(any(c != "#000000" for f in design["frames"] for c in f))

    def test_rgb_blend_and_scene_color_interpolation_preserve_endpoints(self):
        recipe = sample_recipe(3)
        recipe["scenes"][0]["top"] = [
            {"kind": "solid", "color": "#FF0000"},
            {"kind": "solid", "color": "#0000FF", "color_to": "#00FF00", "opacity": 0.5, "blend": "replace"}]
        design = compiler.compile_recipe(recipe)
        self.assertEqual(design["frames"][0][0], "#800080")
        self.assertEqual(design["frames"][-1][0], "#808000")
        recipe["scenes"][0]["top"][1]["blend"] = "max"
        self.assertEqual(compiler.compile_recipe(recipe)["frames"][0][0], "#FF0080")
        recipe["scenes"][0]["top"][1]["blend"] = "add"
        self.assertEqual(compiler.compile_recipe(recipe)["frames"][0][0], "#FF0080")

    def test_looping_motion_and_smooth_motion(self):
        for ease in ("sine", "triangle"):
            recipe = sample_recipe(5)
            recipe["scenes"][0]["top"] = [{"kind": "solid", "color": "#FFFFFF",
                                             "opacity": {"from": 0, "to": 1, "ease": ease}}]
            frame = compiler.compile_recipe(recipe)["frames"]
            self.assertEqual(frame[0][0], "#000000")
            self.assertEqual(frame[2][0], "#FFFFFF")
            self.assertEqual(frame[-1][0], "#000000")
        self.assertEqual(compiler._value({"from": 0, "to": 1, "ease": "smooth"}, 0.25), 0.15625)

    def test_text_scrolls_vertically_and_cannot_render_on_keys(self):
        recipe = sample_recipe(5)
        recipe["scenes"][0]["top"] = [{"kind": "text", "text": "TIPTOP", "color": "#5A0000",
                                         "y": {"from": 2, "to": -1}}]
        design = compiler.compile_recipe(recipe)
        self.assertTrue(all(c == "#000000" for c in design["frames"][0]))
        self.assertTrue(any(c == "#5A0000" for c in design["frames"][2]))
        self.assertTrue(all(c == "#000000" for c in design["frames"][-1]))
        recipe["scenes"][0]["keys"] = copy.deepcopy(recipe["scenes"][0]["top"])
        self.reject(recipe, "text 只支持")

    def test_supported_text_alphabet_is_complete(self):
        for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .:+/\\=<>!?_-":
            self.assertTrue(compiler.TEXT_CHARS.fullmatch(char))
            self.assertIn(char, compiler._FONT_ROWS)
        for text in ("猫爪", "lowercase", "\n", "A" * 25):
            recipe = sample_recipe(1)
            recipe["scenes"][0]["top"] = [{"kind": "text", "text": text, "color": "#FFFFFF"}]
            self.reject(recipe)

    def test_bitmap_preserves_colored_outline_and_transparent_background(self):
        recipe = sample_recipe(1)
        recipe["scenes"][0]["top"] = [
            {"kind": "solid", "color": "#102030"},
            {"kind": "bitmap", "rows": ["010", "121", "010"], "palette": ["#EF4500", "#FFDCA0"],
             "x": 20 / 39, "y": 0.5, "blend": "replace"}]
        frame = compiler.compile_recipe(recipe)["frames"][0]
        self.assertEqual(frame[2 * 40 + 20], "#FFDCA0")
        self.assertEqual(frame[2 * 40 + 19], "#EF4500")
        self.assertEqual(frame[1 * 40 + 20], "#EF4500")
        self.assertEqual(frame[1 * 40 + 19], "#102030")
        self.assertEqual(frame[0], "#102030")

    def test_bitmap_tall_character_scroll_reveals_all_rows_without_squashing(self):
        recipe = sample_recipe(17)
        recipe["palette"] = ["#FF0000", "#00FF00", "#0000FF"]
        rows = ["111"] * 4 + ["222"] * 4 + ["333"] * 4
        recipe["scenes"][0]["top"] = [
            {"kind": "bitmap", "rows": rows, "x": 20 / 39,
             "y": {"from": 2.75, "to": -1.75}, "scale": 1}]
        result = compiler.compile_recipe(recipe)
        self.assertEqual(result["frames"][0], ["#000000"] * 200)
        self.assertEqual(result["frames"][-1], ["#000000"] * 200)
        seen = {color for frame in result["frames"] for color in frame if color != "#000000"}
        self.assertEqual(seen, set(recipe["palette"]))
        # Center shows only the middle five source rows, rather than all twelve
        # rows resampled down to the display's five rows.
        center = result["frames"][8]
        self.assertEqual([center[y * 40 + 20] for y in range(5)],
                         ["#00FF00"] * 4 + ["#0000FF"])

    def test_bitmap_local_palette_all_fifteen_indices_and_scaling(self):
        recipe = sample_recipe(1)
        colors = [f"#{i:02X}0000" for i in range(1, 16)]
        recipe["scenes"][0]["top"] = [
            {"kind": "bitmap", "rows": ["123456789ABCDEF"], "palette": colors,
             "x": 20 / 39, "y": 0.5, "scale": 1}]
        frame = compiler.compile_recipe(recipe)["frames"][0]
        self.assertEqual(frame[2 * 40 + 13:2 * 40 + 28], colors)
        recipe["scenes"][0]["top"] = [
            {"kind": "bitmap", "rows": ["1"], "palette": ["#FF0000"], "scale": 2,
             "x": 20 / 39, "y": 0.5, "opacity": 0.5}]
        frame = compiler.compile_recipe(recipe)["frames"][0]
        self.assertEqual(frame.count("#800000"), 4)

    def test_bitmap_full_32_by_40_size_and_motion_bounds_compile(self):
        recipe = sample_recipe(9)
        recipe["scenes"][0]["top"] = [
            {"kind": "bitmap", "rows": ["1" * 40] * 32, "scale": 4,
             "y": {"from": 20, "to": -20}}]
        result = compiler.compile_recipe(recipe)
        self.assertEqual(result["frames"][0], ["#000000"] * 200)
        self.assertEqual(result["frames"][-1], ["#000000"] * 200)
        self.assertEqual(result["frames"][4], ["#12E5FF"] * 200)
        self.assertEqual(len(result["keyframes"]), 9)

    def test_bitmap_malicious_shape_palette_indices_and_fields_rejected(self):
        for rows in ([], [""], ["1" * 41], ["1"] * 33, ["123", "12"], ["1;eval()"], ["1\n2"],
                     [True], "111", ["G"], ["3"]):
            recipe = sample_recipe(1)
            recipe["scenes"][0]["top"] = [{"kind": "bitmap", "rows": rows}]
            self.reject(recipe)
        for palette in ([], ["#FFFFFF"] * 16, ["#FFF"], "#FFFFFF", [True]):
            recipe = sample_recipe(1)
            recipe["scenes"][0]["top"] = [{"kind": "bitmap", "rows": ["1"], "palette": palette}]
            self.reject(recipe)
        for extra in ({"url": "https://example.com/image.png"}, {"path": "/private/file"},
                      {"code": "import os"}, {"color": "#FFFFFF"}, {"scale": 0}, {"scale": 5},
                      {"y": 21}, {"y": {"from": 0, "to": -21}}, {"scale": float("inf")}):
            recipe = sample_recipe(1)
            recipe["scenes"][0]["top"] = [{"kind": "bitmap", "rows": ["1"], **extra}]
            self.reject(recipe)
        recipe = sample_recipe(1)
        recipe["scenes"][0]["keys"] = [{"kind": "bitmap", "rows": ["1"]}]
        self.reject(recipe, "bitmap 只支持")

    def test_bitmap_source_cells_are_included_in_work_budget(self):
        recipe = sample_recipe(1)
        recipe["scenes"][0]["top"] = [{"kind": "bitmap", "rows": ["1" * 40] * 32}]
        recipe["scenes"][0]["keys"] = []
        with patch.object(compiler, "MAX_WORK", 200 + 1280 - 1):
            self.reject(recipe, "预算超限")
        with patch.object(compiler, "MAX_WORK", 200 + 1280):
            self.assertEqual(len(compiler.compile_recipe(recipe)["frames"]), 1)

    def test_unknown_code_fields_and_unknown_layer_kinds_are_rejected(self):
        for location, field in (("root", "code"), ("scene", "key_layer"), ("layer", "expression"), ("motion", "eval")):
            recipe = sample_recipe()
            if location == "root":
                target = recipe
            elif location == "scene":
                target = recipe["scenes"][0]
            elif location == "layer":
                target = recipe["scenes"][0]["top"][0]
            else:
                target = recipe["scenes"][0]["top"][0]["position"]
            target[field] = "__import__('os').system('anything')"
            self.reject(recipe, "不支持的字段")
        recipe = sample_recipe()
        recipe["scenes"][0]["top"][0]["kind"] = "python"
        self.reject(recipe, "kind")

    def test_nonfinite_bool_numeric_strings_and_overflow_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), True, "0.5", 10 ** 10000):
            recipe = sample_recipe()
            recipe["scenes"][0]["top"][0]["position"] = value
            self.reject(recipe)
        for value in (True, 3.5, 0, 256, "192"):
            recipe = sample_recipe()
            recipe["frame_count"] = value
            self.reject(recipe)

    def test_strict_motion_bounds_and_unused_cycles_rejected(self):
        for motion in ({"from": 0, "to": 4}, {"from": 0}, {"from": 0, "to": 1, "ease": "bounce"},
                       {"from": 0, "to": 1, "cycles": 2}, {"from": 0, "to": 1, "ease": "smooth", "phase": 0},
                       {"from": 0, "to": 1, "ease": "sine", "cycles": 9},
                       {"from": 0, "to": 1, "ease": "sine", "phase": float("nan")}):
            recipe = sample_recipe()
            recipe["scenes"][0]["top"][0]["position"] = motion
            self.reject(recipe)

    def test_scene_gap_overlap_uncovered_and_reordered_rejected(self):
        for intervals in ([(1, 16)], [(0, 15)], [(0, 9), (8, 16)], [(0, 8), (9, 16)], [(8, 16), (0, 8)], [(0, 0)]):
            recipe = sample_recipe()
            recipe["scenes"] = [{"name": "test", "start": start, "end": end, "top": [], "keys": []}
                                for start, end in intervals]
            self.reject(recipe)

    def test_layer_scene_particle_and_work_limits_rejected_before_allocation(self):
        recipe = sample_recipe()
        recipe["scenes"][0]["top"] *= 9
        self.reject(recipe, "0–8")
        recipe = sample_recipe()
        recipe["scenes"] *= 13
        self.reject(recipe, "1–12")
        recipe = sample_recipe(255)
        particle = {"kind": "particles", "color": "#FFFFFF", "count": 24}
        recipe["scenes"][0]["top"] = [particle] * 8
        with patch.object(compiler, "_render", side_effect=AssertionError("must reject before render")):
            self.reject(recipe, "预算超限")
        recipe = sample_recipe(1)
        recipe["scenes"][0]["top"] = [{**particle, "count": 25}]
        self.reject(recipe, "1–24")
        recipe = sample_recipe(7)
        scene = {"name": "layer-limit", "top": [{"kind": "solid", "color": "#FFFFFF"}] * 8,
                 "keys": [{"kind": "solid", "color": "#FFFFFF"}] * 8}
        recipe["scenes"] = [{**scene, "start": i, "end": i + 1} for i in range(7)]
        self.reject(recipe, "超过 96")

    def test_invalid_colors_strings_structure_and_enum_types_rejected(self):
        for color in ("red", "#FFF", "#12345678", 0, {"url": "https://example.com"}):
            recipe = sample_recipe()
            recipe["scenes"][0]["top"][0]["color"] = color
            self.reject(recipe)
        for field, value in (("name", "   "), ("name", "A" * 61), ("description", "X" * 801),
                             ("palette", []), ("palette", ["#000000"] * 9), ("version", 2),
                             ("speed_ms", 9), ("speed_ms", 101), ("scenes", {})):
            recipe = sample_recipe()
            recipe[field] = value
            self.reject(recipe)
        recipe = sample_recipe()
        recipe["scenes"][0]["top"][0]["blend"] = ["add"]
        self.reject(recipe)
        recipe = sample_recipe()
        recipe["scenes"][0]["top"][0]["axis"] = True
        self.reject(recipe)

    def test_json_schema_serializes_and_agrees_on_valid_example(self):
        schema = compiler.recipe_schema()
        roundtrip = json.loads(json.dumps(schema, ensure_ascii=False, allow_nan=False))
        self.assertEqual(schema, roundtrip)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(len(schema["$defs"]), 11)
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Optional schema-check dependency not present; compiler tests use stdlib")
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(sample_recipe())
        for kind, table in compiler.KINDS.items():
            recipe = sample_recipe(1)
            layer = {"kind": kind, "color": "#FFFFFF", **({"text": "CYBER"} if kind == "text" else {})}
            if kind == "bitmap":
                layer = {"kind": "bitmap", "rows": ["010", "111", "010"]}
            recipe["scenes"][0]["top"] = [layer]
            validator.validate(recipe)
            compiler.compile_recipe(recipe)

    def test_compact_model_schema_is_substantially_smaller_and_keeps_defaults(self):
        full = compiler.recipe_schema()
        compact = compiler.model_recipe_schema()
        packed = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self.assertLess(len(packed(compact)), len(packed(full)) * 0.5)
        self.assertEqual(compact["required"], full["required"])
        self.assertEqual(compact["additionalProperties"], full["additionalProperties"])
        self.assertEqual(compact["properties"], full["properties"])
        for kind in compiler.KINDS:
            self.assertEqual(compact["$defs"][kind]["required"], full["$defs"][kind]["required"])
            self.assertEqual(compact["$defs"][kind]["additionalProperties"], False)
            for key, bounds in {**compiler.COMMON_NUMBERS, **compiler.KINDS[kind]["numbers"]}.items():
                field = compact["$defs"][kind]["properties"][key]
                self.assertEqual(field["default"], bounds[2])
                self.assertIn("$ref", field)
        # Both helpers return detached structures; callers cannot mutate the
        # local contract or another request's prompt by editing one result.
        compact["$defs"]["bitmap"]["required"].append("unsafe")
        self.assertNotIn("unsafe", compiler.model_recipe_schema()["$defs"]["bitmap"]["required"])
        self.assertEqual(compiler.recipe_schema(), full)

    def test_compact_schema_equivalence_covers_every_motion_field_and_edge(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Optional schema-check dependency not present")
        full = jsonschema.Draft202012Validator(compiler.recipe_schema())
        compact_schema = compiler.model_recipe_schema()
        jsonschema.Draft202012Validator.check_schema(compact_schema)
        compact = jsonschema.Draft202012Validator(compact_schema)
        checked = 0
        for kind, table in compiler.KINDS.items():
            for key, (minimum, maximum, default) in {**compiler.COMMON_NUMBERS, **table["numbers"]}.items():
                values = [minimum, maximum, default, minimum - 1, maximum + 1, True, False, str(default), None, [],
                          {"from": minimum, "to": maximum},
                          {"from": minimum, "to": maximum, "ease": "smooth"},
                          {"from": minimum, "to": maximum, "ease": "sine", "cycles": 8, "phase": 1},
                          {"from": minimum, "to": maximum, "ease": "triangle", "cycles": 1, "phase": 0},
                          {"from": minimum - 1, "to": maximum}, {"from": minimum, "to": maximum + 1},
                          {"from": minimum}, {"to": maximum}, {},
                          {"from": minimum, "to": maximum, "cycles": 1},
                          {"from": minimum, "to": maximum, "phase": 0},
                          {"from": minimum, "to": maximum, "ease": "linear", "cycles": 1},
                          {"from": minimum, "to": maximum, "ease": "smooth", "phase": 0},
                          {"from": minimum, "to": maximum, "ease": "sine", "cycles": 0},
                          {"from": minimum, "to": maximum, "ease": "sine", "phase": 2},
                          {"from": minimum, "to": maximum, "ease": "unknown"},
                          {"from": minimum, "to": maximum, "expression": "user code"}]
                for value in values:
                    recipe = sample_recipe(1)
                    layer = {"kind": kind, "color": "#FFFFFF"}
                    if kind == "text":
                        layer["text"] = "A"
                    elif kind == "bitmap":
                        layer = {"kind": kind, "rows": ["1"]}
                    layer[key] = value
                    recipe["scenes"][0]["top"] = [layer]
                    with self.subTest(kind=kind, parameter=key, value=value):
                        self.assertEqual(full.is_valid(recipe), compact.is_valid(recipe))
                    checked += 1
        self.assertGreater(checked, 1000)

    def test_compact_schema_keeps_required_unknown_field_and_static_constraints(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Optional schema-check dependency not present")
        full = jsonschema.Draft202012Validator(compiler.recipe_schema())
        compact = jsonschema.Draft202012Validator(compiler.model_recipe_schema())
        mutations = []
        for required in compiler.recipe_schema()["required"]:
            recipe = sample_recipe()
            del recipe[required]
            mutations.append(recipe)
        for location in ("root", "scene", "layer"):
            recipe = sample_recipe()
            target = recipe if location == "root" else recipe["scenes"][0]
            if location == "layer":
                target = target["top"][0]
            target["unsafe"] = "not supported"
            mutations.append(recipe)
        for kind, fields in (("solid", {}), ("bitmap", {}), ("bitmap", {"rows": ["G"]}),
                             ("bitmap", {"rows": ["1"] * 33}), ("bitmap", {"rows": ["1" * 41]}),
                             ("bitmap", {"rows": ["1"], "palette": []}),
                             ("text", {"color": "#FFFFFF", "text": "lowercase"}),
                             ("checker", {"color": "#FFFFFF", "cells_x": 41}),
                             ("checker", {"color": "#FFFFFF", "invert": 1}),
                             ("noise", {"color": "#FFFFFF", "seed": -1}),
                             ("particles", {"color": "#FFFFFF", "count": 25})):
            recipe = sample_recipe()
            recipe["scenes"][0]["top"] = [{"kind": kind, **fields}]
            mutations.append(recipe)
        for recipe in mutations:
            self.assertFalse(full.is_valid(recipe))
            self.assertFalse(compact.is_valid(recipe))

    def test_verified_grid_examples_compile_preserve_palette_and_loop(self):
        examples = compiler.verified_recipe_examples()
        self.assertEqual(len(examples), 2)
        character, scan = [compiler.compile_recipe(recipe) for recipe in examples]
        self.assertEqual((len(character["frames"]), len(scan["frames"])), (192, 192))
        self.assertEqual(character["frames"][0], character["frames"][-1])
        self.assertNotEqual(character["frames"][0], character["frames"][examples[0]["scenes"][1]["start"]])
        self.assertTrue(all(frame == character["keyframes"][0] for frame in character["keyframes"]))
        # Explicit local palette makes index 3 a true black pupil, replacing the
        # nonblack background; transparent index 0 still leaves it untouched.
        frame = character["frames"][0]
        self.assertEqual(frame[2 * 40 + 19], "#000000")
        self.assertEqual(frame[2 * 40 + 18], "#F8F4FF")
        self.assertEqual(frame[0], "#04121B")
        for field in ("frames", "keyframes"):
            self.assertTrue(all(color == "#000000" for color in scan[field][0] + scan[field][-1]))
            self.assertTrue(all(any(color != "#000000" for color in row) for row in scan[field][1:-1]))
        for design in (character, scan):
            self.assertTrue(all(frame[index] == "#000000" for frame in design["keyframes"]
                                for index in compiler.RESERVED_LEDS))
        # Examples are fresh values and use requested parameters even for tiny
        # test timelines, instead of installing a fixed 192-frame template.
        examples[0]["scenes"][0]["top"][1]["rows"][0] = "0000000"
        self.assertNotEqual(examples, compiler.verified_recipe_examples())
        for count, speed in ((1, 10), (2, 100), (3, 40), (12, 40), (255, 100)):
            for recipe in compiler.verified_recipe_examples(frame_count=count, speed_ms=speed):
                design = compiler.compile_recipe(recipe)
                self.assertEqual((len(design["frames"]), len(design["keyframes"]), design["speed_ms"]),
                                 (count, count, speed))
                self.assertTrue(any(color != "#000000" for frame in design["frames"] for color in frame))
        for changes in ({"frame_count": 0}, {"frame_count": True}, {"speed_ms": 101}):
            with self.assertRaises(compiler.RecipeError):
                compiler.verified_recipe_examples(**changes)


if __name__ == "__main__":
    unittest.main()
