"""Compile bounded, declarative AI lighting recipes; never evaluate model code.

All coordinates are normalized within one lighting region. The top display is
40 columns by 5 rows, in row-major order. Key coordinates follow the public
front-photo lamp layout, including three independent lamps under the spacebar.
Only this module's fixed drawing primitives can be selected by a recipe.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

RESERVED_LEDS = frozenset((57, 61, 74, 78, 82, 83, 84))
MAX_WORK = 8_000_000
MAX_LAYERS = 96
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
TEXT_CHARS = re.compile(r"^[A-Z0-9 .:+/\\=<>!?_-]{1,24}$")
BITMAP_ROW = re.compile(r"^[0-9A-Fa-f]{1,40}$")

# Derived once from data/photos/key-photo-layout.json front quads + lamp_uv,
# normalized by lamp extents. These are estimated public photo positions, not
# claimed hardware measurements; no photo or user device record is read here.
KEY_COORDINATES = (
    (0.0, 0.0), (0.081223, 0.0), (0.148113, 0.0), (0.21548, 0.0), (0.282848, 0.0),
    (0.361204, 0.0), (0.428571, 0.0), (0.496417, 0.0), (0.56474, 0.0), (0.643096, 0.0),
    (0.710941, 0.0), (0.778309, 0.0), (0.846632, 0.0), (0.926899, 0.0), (0.995222, 0.0),
    (0.003344, 0.226444), (0.069279, 0.226444), (0.13569, 0.226444), (0.20258, 0.226444), (0.26947, 0.226444),
    (0.336359, 0.226444), (0.403249, 0.226444), (0.470139, 0.226444), (0.53655, 0.226444), (0.602962, 0.226444),
    (0.669852, 0.226444), (0.736742, 0.226444), (0.803631, 0.226444), (0.895366, 0.226444), (0.990922, 0.226444),
    (0.021978, 0.421536), (0.10559, 0.421536), (0.172957, 0.421536), (0.239847, 0.421536), (0.306737, 0.421536),
    (0.373626, 0.421536), (0.440516, 0.421536), (0.507406, 0.421536), (0.574295, 0.421536), (0.641185, 0.421536),
    (0.708075, 0.421536), (0.774964, 0.421536), (0.842332, 0.421536), (0.913999, 0.421536), (0.990444, 0.421536),
    (0.030578, 0.615063), (0.121835, 0.615063), (0.189202, 0.615063), (0.256092, 0.615063), (0.323459, 0.615063),
    (0.391304, 0.615063), (0.45915, 0.615063), (0.526995, 0.615063), (0.59484, 0.615063), (0.662685, 0.615063),
    (0.73053, 0.615063), (0.798376, 0.615063), None, (0.891543, 0.615063), (0.989967, 0.615063),
    (0.047778, 0.805139), None, (0.15528, 0.805139), (0.223125, 0.805139), (0.29097, 0.805139),
    (0.358815, 0.805139), (0.42666, 0.805139), (0.494505, 0.805139), (0.562351, 0.805139), (0.630196, 0.805139),
    (0.698041, 0.805139), (0.765886, 0.805139), (0.838987, 0.805139), (0.924032, 0.805139), None,
    (0.016245, 1.0), (0.096512, 1.0), (0.177258, 1.0), None, (0.256568, 1.0),
    (0.422838, 1.0), (0.593883, 1.0), None, None, None,
    (0.668419, 1.0), (0.74343, 1.0), (0.854754, 1.0), (0.926899, 1.0), (1.0, 1.0),
)
TOP_COORDINATES = tuple((x / 39, y / 4) for y in range(5) for x in range(40))


class RecipeError(ValueError):
    """An untrusted model recipe does not satisfy the bounded contract."""


# Parameter tables are shared by prompt schema, validation and rendering.
# Numeric tuple: minimum, maximum, default; integers are separately listed.
COMMON_NUMBERS = {"opacity": (0, 1, 1)}
POSITION = {"x": (-2, 3, 0.5), "y": (-2, 3, 0.5)}
KINDS = {
    "solid": {"numbers": {}},
    "wave": {"numbers": {"angle": (-720, 720, 0), "frequency": (0.25, 20, 2),
                          "phase": (-16, 16, 0), "power": (1, 8, 2)}},
    "scan": {"numbers": {"position": (-2, 3, 0.5), "width": (0.01, 2, 0.2)},
             "enums": {"axis": ("x", "y")}},
    "ring": {"numbers": {**POSITION, "radius": (0, 4, 0.4), "width": (0.01, 2, 0.15),
                          "aspect": (0.25, 8, 1)}},
    "rect": {"numbers": {**POSITION, "width": (0.01, 4, 0.5), "height": (0.01, 4, 0.5),
                          "angle": (-720, 720, 0), "stroke": (0, 1, 0)}},
    "line": {"numbers": {"x1": (-2, 3, 0), "y1": (-2, 3, 0), "x2": (-2, 3, 1),
                          "y2": (-2, 3, 1), "width": (0.01, 2, 0.12), "aspect": (0.25, 8, 1)}},
    "checker": {"numbers": {"x": (-2, 3, 0), "y": (-2, 3, 0)},
                "integers": {"cells_x": (1, 40, 8), "cells_y": (1, 10, 5)},
                "booleans": {"invert": False}},
    "noise": {"numbers": {"rate": (0, 20, 8), "threshold": (0, 0.99, 0.75)},
              "integers": {"scale": (1, 40, 20), "seed": (0, 65535, 0)}},
    "particles": {"numbers": {"x": (-2, 3, 0), "y": (-2, 3, 0), "speed": (-4, 4, 1),
                               "radius": (0.01, 0.5, 0.08), "angle": (-720, 720, 90),
                               "aspect": (0.25, 8, 1), "tail": (0, 0.5, 0)},
                  "integers": {"count": (1, 24, 8), "seed": (0, 65535, 0)}},
    "text": {"numbers": {**POSITION, "scale": (0.5, 4, 1)}, "strings": {"text": 24}},
    # A bitmap keeps its source pixel height. A 32-row drawing can move past
    # the five-row viewport instead of being squeezed into five rows.
    "bitmap": {"numbers": {"x": (-2, 3, 0.5), "y": (-20, 20, 0.5), "scale": (0.5, 4, 1)}},
}


def _fail(path, message):
    raise RecipeError(f"{path}: {message}")


def _object(value, allowed, required, path):
    if type(value) is not dict:
        _fail(path, "必须是 JSON 对象")
    if any(type(key) is not str for key in value):
        _fail(path, "字段名必须是字符串")
    unknown = set(value) - set(allowed)
    if unknown:
        _fail(path, "不支持的字段 " + sorted(unknown)[0])
    missing = set(required) - set(value)
    if missing:
        _fail(path, "缺少字段 " + sorted(missing)[0])


def _number(value, minimum, maximum, path, *, integer=False):
    types = (int,) if integer else (int, float)
    if type(value) not in types:
        _fail(path, "必须是整数" if integer else "必须是有限数值")
    # A JSON integer may be too large to convert to float; range-check first.
    if value < minimum or value > maximum or not math.isfinite(value):
        _fail(path, f"必须在 {minimum}–{maximum} 范围内")
    return value


def _text(value, maximum, path, *, empty=False):
    if type(value) is not str or len(value) > maximum or (not empty and not value.strip()):
        _fail(path, f"必须是长度 {'0' if empty else '1'}–{maximum} 的文本")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        _fail(path, "不允许控制字符")
    return value


def _color(value, path):
    if type(value) is not str or not HEX_COLOR.fullmatch(value):
        _fail(path, "颜色必须为 #RRGGBB")
    return value.upper()


def _motion(value, bounds, path):
    if type(value) is not dict:
        return _number(value, bounds[0], bounds[1], path)
    _object(value, ("from", "to", "ease", "cycles", "phase"), ("from", "to"), path)
    for key in ("from", "to"):
        _number(value[key], bounds[0], bounds[1], path + "." + key)
    ease = value.get("ease", "linear")
    if type(ease) is not str or ease not in ("linear", "smooth", "sine", "triangle"):
        _fail(path + ".ease", "必须为 linear、smooth、sine 或 triangle")
    if ease in ("linear", "smooth") and ("cycles" in value or "phase" in value):
        _fail(path, "cycles 和 phase 仅用于 sine / triangle 循环运动")
    _number(value.get("cycles", 1), 1, 8, path + ".cycles")
    _number(value.get("phase", 0), 0, 1, path + ".phase")
    return value


def _validate_layer(layer, path, target, palette):
    if type(layer) is not dict or type(layer.get("kind")) is not str or layer["kind"] not in KINDS:
        _fail(path, "kind 必须为支持的灯效图层类型")
    kind = layer["kind"]
    table = KINDS[kind]
    numbers = {**COMMON_NUMBERS, **table["numbers"]}
    if kind == "bitmap":
        allowed = {"kind", "rows", "palette", "blend", *numbers}
        _object(layer, allowed, ("kind", "rows"), path)
        if target != "top":
            _fail(path, "bitmap 只支持顶部 40×5 屏幕")
        rows = layer["rows"]
        if type(rows) is not list or not 1 <= len(rows) <= 32:
            _fail(path + ".rows", "必须包含 1–32 行像素图")
        width = None
        for i, row in enumerate(rows):
            if type(row) is not str or not BITMAP_ROW.fullmatch(row):
                _fail(f"{path}.rows[{i}]", "每行必须是 1–40 个 0–F 十六进制索引字符")
            if width is None:
                width = len(row)
            elif len(row) != width:
                _fail(path + ".rows", "像素图每行必须等宽")
        if len(rows) * width > 1280:
            _fail(path + ".rows", "单个像素图不得超过 1280 格")
        colors = layer.get("palette", palette)
        if type(colors) is not list or not 1 <= len(colors) <= 15:
            _fail(path + ".palette", "必须包含 1–15 个颜色；省略时使用配方 palette")
        for i, color in enumerate(colors):
            _color(color, f"{path}.palette[{i}]")
        if any(int(char, 16) > len(colors) for row in rows for char in row):
            _fail(path + ".rows", "颜色索引超出 palette；0 透明，1–F 对应 palette[0]–palette[14]")
    else:
        allowed = {"kind", "color", "color_to", "blend", *numbers, *table.get("integers", {}),
                   *table.get("enums", {}), *table.get("booleans", {}), *table.get("strings", {})}
        _object(layer, allowed, ("kind", "color", *(("text",) if kind == "text" else ())), path)
        _color(layer["color"], path + ".color")
        if "color_to" in layer:
            _color(layer["color_to"], path + ".color_to")
    blend = layer.get("blend", "add")
    if type(blend) is not str or blend not in ("add", "max", "replace"):
        _fail(path + ".blend", "必须为 add、max 或 replace")
    for key, bounds in numbers.items():
        if key in layer:
            _motion(layer[key], bounds, path + "." + key)
    for key, bounds in table.get("integers", {}).items():
        if key in layer:
            _number(layer[key], bounds[0], bounds[1], path + "." + key, integer=True)
    for key, choices in table.get("enums", {}).items():
        if key in layer and (type(layer[key]) is not str or layer[key] not in choices):
            _fail(path + "." + key, "必须为 " + " / ".join(choices))
    for key in table.get("booleans", {}):
        if key in layer and type(layer[key]) is not bool:
            _fail(path + "." + key, "必须为布尔值")
    if kind == "text":
        if target != "top":
            _fail(path, "text 只支持顶部 40×5 屏幕")
        if type(layer["text"]) is not str or not TEXT_CHARS.fullmatch(layer["text"]):
            _fail(path + ".text", "仅支持 1–24 个大写英文字母、数字和常用标点")


def validate_recipe(recipe):
    """Reject unknown fields and unreasonable allocation/work before rendering."""
    _object(recipe, ("version", "name", "description", "frame_count", "speed_ms", "palette", "scenes"),
            ("version", "name", "description", "frame_count", "speed_ms", "palette", "scenes"), "recipe")
    _number(recipe["version"], 1, 1, "recipe.version", integer=True)
    _text(recipe["name"], 60, "recipe.name")
    _text(recipe["description"], 800, "recipe.description", empty=True)
    count = _number(recipe["frame_count"], 1, 255, "recipe.frame_count", integer=True)
    _number(recipe["speed_ms"], 10, 100, "recipe.speed_ms", integer=True)
    palette = recipe["palette"]
    if type(palette) is not list or not 1 <= len(palette) <= 8:
        _fail("recipe.palette", "必须包含 1–8 个颜色")
    for i, value in enumerate(palette):
        _color(value, f"recipe.palette[{i}]")
    scenes = recipe["scenes"]
    if type(scenes) is not list or not 1 <= len(scenes) <= 12:
        _fail("recipe.scenes", "必须包含 1–12 个场景")
    cursor = total_layers = work = 0
    for i, scene in enumerate(scenes):
        path = f"recipe.scenes[{i}]"
        _object(scene, ("name", "start", "end", "top", "keys"),
                ("name", "start", "end", "top", "keys"), path)
        _text(scene["name"], 60, path + ".name")
        start = _number(scene["start"], 0, count - 1, path + ".start", integer=True)
        end = _number(scene["end"], 1, count, path + ".end", integer=True)
        if start != cursor or end <= start:
            _fail(path, "场景必须按顺序连续覆盖时间轴，start 包含、end 不包含")
        cursor = end
        for target, lamps in (("top", 200), ("keys", 83)):
            layers = scene[target]
            if type(layers) is not list or len(layers) > 8:
                _fail(path + "." + target, "必须包含 0–8 个图层")
            total_layers += len(layers)
            if total_layers > MAX_LAYERS:
                _fail("recipe.scenes", "图层总数超过 96")
            for j, layer in enumerate(layers):
                _validate_layer(layer, f"{path}.{target}[{j}]", target, palette)
                complexity = layer.get("count", 8) if layer["kind"] == "particles" else 1
                work += (end - start) * lamps * complexity
                if layer["kind"] == "bitmap":
                    # Account for the bounded source-cell validation as well as
                    # constant-time per-lamp sampling; do not multiply every
                    # output sample by the full source bitmap area.
                    work += len(layer["rows"]) * len(layer["rows"][0])
                if work > MAX_WORK:
                    _fail("recipe.scenes", "渲染运算预算超限，请减少粒子、图层或帧数")
    if cursor != count:
        _fail("recipe.scenes", "最后一个场景的 end 必须等于 frame_count")
    return recipe


def _numeric_schema(bounds):
    minimum, maximum, default = bounds
    number = {"type": "number", "minimum": minimum, "maximum": maximum}
    return {"anyOf": [number, {"type": "object", "additionalProperties": False,
                              "required": ["from", "to"],
                              "properties": {"from": dict(number), "to": dict(number),
                                             "ease": {"enum": ["linear", "smooth", "sine", "triangle"]},
                                             "cycles": {"type": "number", "minimum": 1, "maximum": 8},
                                             "phase": {"type": "number", "minimum": 0, "maximum": 1}},
                              "allOf": [{"if": {"properties": {"ease": {"enum": ["linear", "smooth"]}},
                                                  "required": ["ease"]},
                                         "then": {"not": {"anyOf": [{"required": ["cycles"]},
                                                                     {"required": ["phase"]}]}}},
                                        {"if": {"not": {"required": ["ease"]}},
                                         "then": {"not": {"anyOf": [{"required": ["cycles"]},
                                                                     {"required": ["phase"]}]}}}]}],
            "default": default}


def recipe_schema():
    """JSON Schema sent to the model; semantic/time/work checks remain local."""
    color = {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}
    definitions = {}
    for kind, table in KINDS.items():
        properties = {"kind": {"const": kind},
                      "blend": {"enum": ["add", "max", "replace"], "default": "add"}}
        if kind != "bitmap":
            properties.update({"color": dict(color), "color_to": dict(color)})
        properties.update({key: _numeric_schema(bounds) for key, bounds in
                           {**COMMON_NUMBERS, **table["numbers"]}.items()})
        properties.update({key: {"type": "integer", "minimum": v[0], "maximum": v[1], "default": v[2]}
                           for key, v in table.get("integers", {}).items()})
        properties.update({key: {"enum": list(v), "default": v[0]}
                           for key, v in table.get("enums", {}).items()})
        properties.update({key: {"type": "boolean", "default": v}
                           for key, v in table.get("booleans", {}).items()})
        required = ["kind", "color"] if kind != "bitmap" else ["kind", "rows"]
        if kind == "text":
            properties["text"] = {"type": "string", "pattern": TEXT_CHARS.pattern, "maxLength": 24}
            required.append("text")
        if kind == "bitmap":
            properties["rows"] = {"type": "array", "minItems": 1, "maxItems": 32,
                                  "items": {"type": "string", "pattern": BITMAP_ROW.pattern,
                                            "minLength": 1, "maxLength": 40},
                                  "description": "Equal-width bitmap rows, at most 1280 cells. 0 is transparent; "
                                                 "1..F select palette[0]..palette[14]. Source pixels stay 1×scale display pixels."}
            properties["palette"] = {"type": "array", "minItems": 1, "maxItems": 15, "items": dict(color),
                                     "description": "Optional local colors; omitted palette inherits the recipe palette."}
        definitions[kind] = {"type": "object", "additionalProperties": False,
                             "properties": properties, "required": required}
    def layers(target):
        return {"type": "array", "maxItems": 8, "items": {"anyOf": [
            {"$ref": "#/$defs/" + kind} for kind in KINDS if target == "top" or kind not in ("text", "bitmap")]}}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Cyberboard lighting recipe v1",
            "type": "object", "additionalProperties": False,
            "description": "Normalized coordinates: x left→right, y top→bottom. Scene intervals are contiguous and cover frame_count. "
                           "Numeric motion endpoints stay within bounds; linear/smooth run once, sine/triangle repeat. "
                           "color_to interpolates color through the scene. Layers composite in list order. "
                           "Ring/line/particles aspect scales horizontal distance; top has 8:1 physical aspect. "
                           "Text is a 3×5 bitmap, x/y center, scale in display pixels; keys cannot render text. "
                           "Bitmap is top-only, 1..32 equal-width rows of 1..40 hexadecimal cells; 0 transparent, "
                           "1..F select local or inherited palette. Bitmap x/y indicate center, each cell is scale display pixels; "
                           "its height is NOT resized to 5 rows. Move y to reveal a tall character through the viewport. "
                           "At most 96 total layers and 8,000,000 lamp×layer×particle evaluations plus bitmap source cells.",
            "required": ["version", "name", "description", "frame_count", "speed_ms", "palette", "scenes"],
            "properties": {"version": {"const": 1}, "name": {"type": "string", "minLength": 1, "maxLength": 60},
                           "description": {"type": "string", "maxLength": 800},
                           "frame_count": {"type": "integer", "minimum": 1, "maximum": 255},
                           "speed_ms": {"type": "integer", "minimum": 10, "maximum": 100},
                           "palette": {"type": "array", "minItems": 1, "maxItems": 8, "items": dict(color)},
                           "scenes": {"type": "array", "minItems": 1, "maxItems": 12,
                                      "items": {"type": "object", "additionalProperties": False,
                                                "required": ["name", "start", "end", "top", "keys"],
                                                "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 60},
                                                               "start": {"type": "integer", "minimum": 0, "maximum": 254},
                                                               "end": {"type": "integer", "minimum": 1, "maximum": 255},
                                                               "top": layers("top"), "keys": layers("keys")}}}},
            "$defs": definitions}


def model_recipe_schema():
    """Return the same JSON Schema validation contract with shared motion defs.

    This is derived from recipe_schema(), not a separately maintained contract.
    A motion's required fields, allowed properties and easing conditions stay in
    one shared definition. Bounds remain on both scalar values and endpoints.
    Annotation defaults remain alongside each field's $ref (draft 2020-12).
    The local validate_recipe() still checks time coverage, palette indices and
    render budgets that neither schema can express on its own.
    """
    schema = recipe_schema()
    shared = {}
    motion_definitions = {}
    parameter_definitions = {}

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def compact(value):
        if isinstance(value, list):
            return [compact(item) for item in value]
        if not isinstance(value, dict):
            return value
        alternatives = value.get("anyOf")
        if isinstance(alternatives, list) and len(alternatives) == 2:
            number, motion = alternatives
            if (isinstance(number, dict) and number.get("type") == "number"
                    and isinstance(motion, dict) and motion.get("type") == "object"
                    and motion.get("properties", {}).get("from") == number
                    and motion.get("properties", {}).get("to") == number):
                base_motion = copy.deepcopy(motion)
                base_motion["properties"]["from"] = {"type": "number"}
                base_motion["properties"]["to"] = {"type": "number"}
                signature = canonical(base_motion)
                if signature not in motion_definitions:
                    name = "_motion" + str(len(motion_definitions))
                    motion_definitions[signature] = name
                    shared[name] = base_motion
                motion_ref = motion_definitions[signature]
                parameter = {"anyOf": [copy.deepcopy(number), {
                    "allOf": [{"$ref": "#/$defs/" + motion_ref},
                              {"properties": {"from": copy.deepcopy(number), "to": copy.deepcopy(number)}}]}]}
                signature = canonical(parameter)
                if signature not in parameter_definitions:
                    name = "_parameter" + str(len(parameter_definitions))
                    parameter_definitions[signature] = name
                    shared[name] = parameter
                # Preserve all siblings, including each parameter's own default.
                result = {key: compact(item) for key, item in value.items() if key != "anyOf"}
                result["$ref"] = "#/$defs/" + parameter_definitions[signature]
                return result
        return {key: compact(item) for key, item in value.items()}

    result = compact(schema)
    result["$defs"].update(shared)
    return result


def verified_recipe_examples(*, frame_count=192, speed_ms=40):
    """Return fresh, public grid examples compiled by the offline test suite.

    These demonstrate units and compositing, not preferred themes or a library
    to select instead of designing a new work. No assets or device state are
    read. Parameters follow the caller's requested frame count and speed.
    """
    _number(frame_count, 1, 255, "examples.frame_count", integer=True)
    _number(speed_ms, 10, 100, "examples.speed_ms", integer=True)
    open_rows = ["0100010", "1111111", "1231321", "1111111", "0111110"]
    closed_rows = ["0100010", "1111111", "1331331", "1111111", "0111110"]

    def pose(name, start, end, rows):
        return {"name": name, "start": start, "end": end,
                "top": [{"kind": "solid", "color": "#04121B"},
                        {"kind": "bitmap", "rows": rows,
                         "palette": ["#7B2FBE", "#F8F4FF", "#000000"],
                         "x": 20 / 39, "y": 2 / 4, "scale": 1, "blend": "replace"}],
                "keys": [{"kind": "solid", "color": "#7B2FBE", "opacity": 0.16}]}

    poses = [pose("定格", 0, frame_count, open_rows)]
    if frame_count >= 3:
        close_start = max(1, min(frame_count - 2, frame_count * 3 // 4))
        closed_count = max(1, min(frame_count // 8, round(120 / speed_ms)))
        close_end = min(frame_count - 1, close_start + closed_count)
        poses = [pose("睁眼", 0, close_start, open_rows),
                 pose("轻眨", close_start, close_end, closed_rows),
                 pose("回到睁眼", close_end, frame_count, open_rows)]
    character = {"version": 1, "name": "猫眼微光", "description": "七列五行的网格示例；黑色瞳孔替换底色，轴灯在换姿态时保持稳定。",
                 "frame_count": frame_count, "speed_ms": speed_ms,
                 "palette": ["#7B2FBE", "#F8F4FF", "#04121B"], "scenes": poses}
    position = {"from": 1.3, "to": -0.3} if frame_count >= 3 else 0.5
    scan = {"version": 1, "name": "向上光带", "description": "五行视窗的宽光带由下向上通过，两端离屏；极短时间轴只示范中心光带。",
            "frame_count": frame_count, "speed_ms": speed_ms, "palette": ["#24DDFC"], "scenes": [
                {"name": "上行", "start": 0, "end": frame_count,
                 "top": [{"kind": "scan", "color": "#24DDFC", "axis": "y", "width": 0.6,
                          "position": copy.deepcopy(position)}],
                 "keys": [{"kind": "scan", "color": "#24DDFC", "axis": "y", "width": 0.6,
                           "position": copy.deepcopy(position), "opacity": 0.45}]}]}
    for example in (character, scan):
        validate_recipe(example)
    return [character, scan]


def _value(value, t):
    if type(value) is not dict:
        return value
    ease = value.get("ease", "linear")
    if ease == "smooth":
        u = t * t * (3 - 2 * t)
    elif ease == "sine":
        u = (1 - math.cos(math.tau * (t * value.get("cycles", 1) + value.get("phase", 0)))) / 2
    elif ease == "triangle":
        u = 1 - abs(2 * ((t * value.get("cycles", 1) + value.get("phase", 0)) % 1) - 1)
    else:
        u = t
    return value["from"] + (value["to"] - value["from"]) * u


def _hash(seed, x, y=0):
    # Fixed integer mixing gives identical output across Python versions/platforms.
    n = (seed * 374761393 + x * 668265263 + y * 2246822519) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return (n ^ (n >> 16)) / 0xFFFFFFFF


# Deliberately small font: strong five-row silhouettes are readable on the panel.
_FONT_ROWS = {
    "A": ("010", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"), "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"), "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"), "N": ("101", "111", "111", "111", "101"),
    "O": ("010", "101", "101", "101", "010"), "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "011", "001"), "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"), "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("110", "001", "010", "100", "111"), "3": ("110", "001", "010", "001", "110"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "110", "001", "110"),
    "6": ("011", "100", "110", "101", "010"), "7": ("111", "001", "010", "010", "010"),
    "8": ("010", "101", "010", "101", "010"), "9": ("010", "101", "011", "001", "110"),
    " ": ("000",) * 5, ".": ("000", "000", "000", "000", "010"),
    ":": ("000", "010", "000", "010", "000"), "+": ("000", "010", "111", "010", "000"),
    "-": ("000", "000", "111", "000", "000"), "_": ("000", "000", "000", "000", "111"),
    "/": ("001", "001", "010", "100", "100"), "\\": ("100", "100", "010", "001", "001"),
    "=": ("000", "111", "000", "111", "000"), "<": ("001", "010", "100", "010", "001"),
    ">": ("100", "010", "001", "010", "100"), "!": ("010", "010", "010", "000", "010"),
    "?": ("110", "001", "010", "000", "010"),
}


def _prepare(layer, t, palette=None):
    table = KINDS[layer["kind"]]
    p = dict(layer)
    for key, bounds in {**COMMON_NUMBERS, **table["numbers"]}.items():
        p[key] = _value(layer.get(key, bounds[2]), t)
    for key, bounds in table.get("integers", {}).items():
        p[key] = layer.get(key, bounds[2])
    for key, choices in table.get("enums", {}).items():
        p[key] = layer.get(key, choices[0])
    for key, value in table.get("booleans", {}).items():
        p[key] = layer.get(key, value)
    if p["kind"] == "bitmap":
        colors = layer.get("palette", palette)
        p["palette_rgb"] = tuple(tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) for color in colors)
    else:
        first = tuple(int(layer["color"][i:i + 2], 16) for i in (1, 3, 5))
        last = tuple(int(layer.get("color_to", layer["color"])[i:i + 2], 16) for i in (1, 3, 5))
        p["rgb"] = tuple(a + (b - a) * t for a, b in zip(first, last))
    p["blend"] = layer.get("blend", "add")
    if "angle" in p:
        angle = math.radians(p["angle"])
        p["cos"], p["sin"] = math.cos(angle), math.sin(angle)
    if p["kind"] == "particles":
        p["points"] = tuple(((_hash(p["seed"], i, 1) + p["cos"] * t * p["speed"] + p["x"]) % 1,
                             (_hash(p["seed"], i, 2) + p["sin"] * t * p["speed"] + p["y"]) % 1)
                            for i in range(p["count"]))
    p["t"] = t
    return p


def _segment_distance(x, y, x1, y1, x2, y2, aspect=1):
    dx, dy = (x2 - x1) * aspect, y2 - y1
    px, py = (x - x1) * aspect, y - y1
    length = dx * dx + dy * dy
    u = max(0, min(1, (px * dx + py * dy) / length)) if length else 0
    return math.hypot(px - dx * u, py - dy * u)


def _intensity(p, x, y):
    kind = p["kind"]
    if kind == "solid":
        return 1
    if kind == "wave":
        return ((1 + math.sin(math.tau * ((x * p["cos"] + y * p["sin"]) * p["frequency"] - p["phase"]))) / 2) ** p["power"]
    if kind == "scan":
        return max(0, 1 - abs((x if p["axis"] == "x" else y) - p["position"]) * 2 / p["width"])
    if kind == "ring":
        distance = math.hypot((x - p["x"]) * p["aspect"], y - p["y"])
        return max(0, 1 - abs(distance - p["radius"]) * 2 / p["width"])
    if kind == "rect":
        dx, dy = x - p["x"], y - p["y"]
        xx, yy = abs(dx * p["cos"] + dy * p["sin"]), abs(-dx * p["sin"] + dy * p["cos"])
        if xx > p["width"] / 2 or yy > p["height"] / 2:
            return 0
        if not p["stroke"]:
            return 1
        return float(xx >= p["width"] / 2 - p["stroke"] or yy >= p["height"] / 2 - p["stroke"])
    if kind == "line":
        distance = _segment_distance(x, y, p["x1"], p["y1"], p["x2"], p["y2"], p["aspect"])
        return max(0, 1 - distance * 2 / p["width"])
    if kind == "checker":
        bit = (math.floor((x - p["x"]) * p["cells_x"]) + math.floor((y - p["y"]) * p["cells_y"])) % 2
        return float(bit != p["invert"])
    if kind == "noise":
        sample = _hash(p["seed"] + math.floor(p["t"] * p["rate"]), math.floor(x * p["scale"]), math.floor(y * p["scale"]))
        return max(0, (sample - p["threshold"]) / (1 - p["threshold"]))
    if kind == "particles":
        strength = 0
        for px, py in p["points"]:
            # Sample the nearest toroidal image; fixed maximum work per particle.
            dx, dy = x - px, y - py
            dx -= math.floor(dx + 0.5)
            dy -= math.floor(dy + 0.5)
            distance = _segment_distance(dx, dy, 0, 0, -p["cos"] * p["tail"], -p["sin"] * p["tail"], p["aspect"])
            strength = max(strength, max(0, 1 - distance / p["radius"]))
        return strength
    if kind == "text":
        width = len(p["text"]) * 4 - 1
        column = math.floor((x * 39 - p["x"] * 39) / p["scale"] + width / 2 + 0.5)
        row = math.floor((y * 4 - p["y"] * 4) / p["scale"] + 2.5)
        if not (0 <= column < width and 0 <= row < 5) or column % 4 == 3:
            return 0
        return int(_FONT_ROWS[p["text"][column // 4]][row][column % 4])
    raise AssertionError("A validated layer kind has no renderer")


def _bitmap_sample(layer, x, y):
    rows = layer["rows"]
    # Samples are pixel centers; equal-width rows retain their original height.
    column = math.floor((x * 39 - layer["x"] * 39) / layer["scale"] + len(rows[0]) / 2)
    row = math.floor((y * 4 - layer["y"] * 4) / layer["scale"] + len(rows) / 2)
    if not (0 <= row < len(rows) and 0 <= column < len(rows[0])):
        return None
    index = int(rows[row][column], 16)
    return layer["palette_rgb"][index - 1] if index else None


def _render(coordinates, layers):
    frame = []
    for coordinate in coordinates:
        if coordinate is None:
            frame.append("#000000")
            continue
        rgb = [0.0, 0.0, 0.0]
        for layer in layers:
            if layer["kind"] == "bitmap":
                color = _bitmap_sample(layer, *coordinate)
                if color is None:
                    continue
                alpha = layer["opacity"]
            else:
                color = layer["rgb"]
                alpha = _intensity(layer, *coordinate) * layer["opacity"]
            if alpha <= 0:
                continue
            if layer["blend"] == "replace":
                rgb = [a * (1 - alpha) + b * alpha for a, b in zip(rgb, color)]
            elif layer["blend"] == "max":
                rgb = [max(a, b * alpha) for a, b in zip(rgb, color)]
            else:
                rgb = [min(255, a + b * alpha) for a, b in zip(rgb, color)]
        frame.append("#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb))
    return frame


def compile_recipe(recipe, *, reference=None):
    """Return a normal Studio design without touching key mappings or hardware.

    Reference is accepted for the AI integration's shared interface. Geometry,
    colors and motion are defined entirely by the model's validated recipe;
    this function never selects or recolors a built-in animation template.
    """
    validate_recipe(recipe)
    digest = hashlib.sha256(json.dumps(recipe, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()[:16]
    top, keys, stages = [], [], []
    for scene in recipe["scenes"]:
        duration = scene["end"] - scene["start"]
        for i in range(duration):
            t = i / (duration - 1) if duration > 1 else 0
            top.append(_render(TOP_COORDINATES, [_prepare(layer, t, recipe["palette"]) for layer in scene["top"]]))
            keys.append(_render(KEY_COORDINATES, [_prepare(layer, t, recipe["palette"]) for layer in scene["keys"]]))
            stages.append(scene["name"])
    return {"id": "kimi-" + digest, "name": recipe["name"].strip(), "description": recipe["description"],
            "palette": [c.upper() for c in recipe["palette"]], "speed_ms": recipe["speed_ms"],
            "frame_count": recipe["frame_count"], "frames": top, "keyframes": keys,
            "stages": stages, "origin": "kimi"}
