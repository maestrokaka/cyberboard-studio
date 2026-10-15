"""Conservative checks of compiled lighting pixels, not an aesthetic score.

The input is a Studio design after recipe/schema validation. Checks still fail
closed on malformed frames, and never execute recipes or inspect image files.
Visibility is a digital RGB proxy, not a measurement of physical LED brightness.
Only the user's brief grants intent exceptions; model-written descriptions and
scene names cannot excuse an accidentally empty or static render.
"""
from __future__ import annotations

import math
import re

VISIBLE_CHANNEL_MIN = 16
BLACK_CHANNEL_MAX = 2
MAX_FRAMES = 255
RESERVED_KEYS = frozenset((57, 61, 74, 78, 82, 83, 84))
_RGB = re.compile(r"^#[0-9a-fA-F]{6}$")
_NEGATION = re.compile(r"(?:不要|不能|避免|不允许|不需要|没有|不是|无需|勿|非|"
                       r"\bnot|\bnever|\bwithout|\bavoid|\bdon't|\bno)"
                       r"\s*(?:任何|出现|再|a\s+|any\s+)?$", re.I)


def _affirmed(text, pattern):
    return any(not _NEGATION.search(text[max(0, m.start() - 18):m.start()])
               for m in re.finditer(pattern, text, re.I))


def _intents(brief):
    text = brief[:8000] if isinstance(brief, str) else ""
    strong_static = _affirmed(text, r"静态|静止|不动|常亮|固定画面|不需要动画|无需动画|"
                             r"不要动画|不做动画|无动画|\bstatic\b|"
                             r"\bstill (?:image|frame|picture)\b|\bstationary\b|\bsteady\b|"
                             r"\bno (?:animation|motion)\b|\bwithout animation\b|"
                             r"\bnon[- ]animated\b|\b(?:do not|don't) animate\b")
    moving = _affirmed(text, r"动画|移动|滚动|流动|扫描|追逐|呼吸|脉动|闪烁|频闪|"
                      r"\banimat\w*\b|\bmov\w*\b|\bscroll\w*\b|\bchase\b|"
                      r"\bscan\w*\b|\bpuls\w*\b|\bbreath\w*\b|\bblink\w*\b")
    plain_color = _affirmed(text, r"纯色|单色|\bsolid colo[u]?r\b|\bflat colo[u]?r\b|\bmonochrome\b")
    return {
        "static": strong_static or (plain_color and not moving),
        "sparse": _affirmed(text, r"极简|稀疏|星空|星点|星野|星座|\bminimal\w*\b|"
                           r"\bsparse\b|\bstar\s*field\b|\bstarry\b|\bconstellation\b"),
        "flashing": _affirmed(text, r"闪烁|频闪|闪灯|爆闪|闪一下|闪光|\bblink\w*\b|"
                             r"\bflash\w*\b|\bflicker\w*\b|\bstrob\w*\b|\btwinkl\w*\b"),
        # A black background is negative space, not permission for blank frames.
        "dark_pause": _affirmed(text, r"黑场|暗场|熄灭|黑屏暂停|黑屏停顿|\bblackout\b|"
                               r"\bdark (?:pause|hold|scene)\b|\bblack (?:pause|hold|frames?)\b|"
                               r"\bfade to black\b"),
        "dim": _affirmed(text, r"低亮|暗色|夜间|微光|\bdim\b|\blow brightness\b|\bdark ambient\b"),
        "entry_exit": _affirmed(text, r"入场|出场|离场|退场|追逐|滚动|\boff.?screen\b|"
                               r"\benter\w*\b|\bexit\w*\b|\bchase\b|\bscroll\w*\b"),
        "seamless": _affirmed(text, r"无缝|首尾一致|首尾相同|\bseamless\b|\bmatching endpoints\b"),
        "all_off": _affirmed(text, r"全部熄灭|全程全黑|整套全黑|关闭所有灯|所有灯关闭|"
                            r"\ball lights off\b|\bturn off all lights\b|\bentirely black\b|"
                            r"\bblack throughout\b"),
        "top_off": _affirmed(text, r"关闭顶屏|关闭顶部|顶屏熄灭|顶部熄灭|只要轴灯|仅轴灯|"
                            r"\bkeys only\b|\bbacklight only\b|\bdisable (?:the )?top\b|"
                            r"\btop (?:display|matrix|screen) off\b"),
        "keys_off": _affirmed(text, r"关闭轴灯|轴灯熄灭|只要顶屏|仅顶屏|\btop only\b|"
                             r"\b(?:key lights|backlight|backlighting) off\b"),
    }


def _rounded(value):
    return round(value, 6) if math.isfinite(value) else None


def _runs(flags):
    result, start = [], None
    for index, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            result.append((start, index))
            start = None
    return result


def _region(frames, width, speed_ms, active):
    if type(frames) is not list or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("帧序列须包含 1–255 帧。")
    cache, pixels = {}, []
    for index, frame in enumerate(frames):
        if type(frame) is not list or len(frame) != width:
            raise ValueError(f"第 {index + 1} 帧须有 {width} 个 RGB 颜色。")
        for color in frame:
            if type(color) is not str or not _RGB.fullmatch(color):
                raise ValueError(f"第 {index + 1} 帧含无效 RGB 颜色。")
            if color not in cache:
                cache[color] = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        pixels.append(tuple(cache[frame[i]] for i in active))
    count = len(pixels)
    visible = [sum(max(c) >= VISIBLE_CHANNEL_MIN for c in frame) for frame in pixels]
    maxima = [max(max(c) for c in frame) for frame in pixels]
    dark = [value == 0 for value in visible]
    runs = _runs(dark)
    longest = max((end - start for start, end in runs), default=0)
    interior = max((end - start for start, end in runs if start and end < count), default=0)
    wrapped = longest
    if runs and runs[0][0] == 0 and runs[-1][1] == count and len(runs) > 1:
        wrapped = max(wrapped, runs[0][1] + count - runs[-1][0])

    def difference(a, b):
        return sum(abs(x - y) for ca, cb in zip(a, b) for x, y in zip(ca, cb)) / (len(active) * 3)

    steps = [difference(a, b) for a, b in zip(pixels, pixels[1:])]
    changes = [sum(a != b for a, b in zip(fa, fb)) / len(active)
               for fa, fb in zip(pixels, pixels[1:])]
    ordered = sorted(steps)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] if ordered else 0
    seam = difference(pixels[-1], pixels[0])
    return {
        "frame_count": count, "duration_ms": count * speed_ms, "active_led_positions": len(active),
        "visible_leds_min": min(visible), "visible_leds_mean": _rounded(sum(visible) / count),
        "visible_leds_max": max(visible), "peak_rgb_channel": max(maxima),
        "dark_frame_count": sum(dark), "dark_frame_fraction": _rounded(sum(dark) / count),
        "longest_dark_ms": longest * speed_ms, "longest_dark_loop_ms": wrapped * speed_ms,
        "longest_interior_dark_ms": interior * speed_ms,
        "unique_frames": len(set(pixels)), "static": len(set(pixels)) == 1,
        "step_changed_led_fraction_mean": _rounded(sum(changes) / len(changes)) if changes else 0,
        "step_mae_mean": _rounded(sum(steps) / len(steps)) if steps else 0,
        "step_mae_p95": _rounded(p95), "step_mae_max": _rounded(max(steps, default=0)),
        "loop_seam_mae": _rounded(seam),
        "loop_seam_changed_led_fraction": _rounded(sum(a != b for a, b in zip(pixels[-1], pixels[0])) / len(active)),
        "loop_seam_vs_p95": _rounded(seam / p95) if p95 else None,
    }


def inspect_design_quality(design, *, brief="", has_images=False):
    """Return JSON-safe issues, warnings and measured pixel/timing proxies.

    Only obvious unintended failures block `passed`. Deliberate darkness,
    sparse stars, blinking, still images and solid-color briefs are respected.
    `has_images` records context; pixels alone cannot establish reference-image
    fidelity, so image use does not impose an invented similarity score.
    """
    issues, warnings = [], []
    intent = _intents(brief)
    metrics = {"has_images": bool(has_images), "intent": intent,
               "visibility_proxy": {"visible_channel_min": VISIBLE_CHANNEL_MIN,
                                    "black_channel_max": BLACK_CHANNEL_MAX}, "regions": {}}
    report = {"passed": False, "issues": issues, "warnings": warnings, "metrics": metrics}

    def add(target, code, message, **details):
        target.append({"code": code, "message": message, **details})

    if type(design) is not dict:
        add(issues, "invalid_design", "质量检查需要已编译的作品对象。")
        return report
    speed = design.get("speed_ms")
    if type(speed) is not int or not 1 <= speed <= 32767:
        add(issues, "invalid_speed", "作品节奏须为 1–32767 毫秒的整数。")
        return report
    for region, field, width, active in (
        ("top", "frames", 200, tuple(range(200))),
        ("keys", "keyframes", 90, tuple(i for i in range(90) if i not in RESERVED_KEYS)),
    ):
        try:
            metrics["regions"][region] = _region(design.get(field), width, speed, active)
        except ValueError as error:
            add(issues, "invalid_frame_data", str(error), region=region)
    if issues:
        return report
    top, keys = (metrics["regions"][name] for name in ("top", "keys"))
    target = keys if intent["top_off"] else top
    target_name = "keys" if intent["top_off"] else "top"
    target_label = "轴灯" if intent["top_off"] else "顶屏"
    black_issue = False
    if not intent["all_off"]:
        if target["peak_rgb_channel"] <= BLACK_CHANNEL_MAX:
            add(issues, "all_dark_output", f"{target_label}全程接近熄灭，请检查主体位置和亮度。", region=target_name)
            black_issue = True
        elif target["visible_leds_max"] == 0:
            bucket = warnings if intent["dim"] or intent["static"] or intent["sparse"] else issues
            add(bucket, "near_black_output", f"{target_label}所有帧均低于可见性检查阈值，请核对是否有意保持微光。", region=target_name)
            black_issue = bucket is issues
        elif target["frame_count"] >= 10 and target["duration_ms"] >= 800 and target["dark_frame_fraction"] >= 0.95:
            allowed = intent["dark_pause"] or intent["flashing"] or intent["sparse"]
            add(warnings if allowed else issues, "mostly_dark_output",
                f"{target_label}至少 95% 的帧没有达到可见性检查阈值，请核对主体是否长期移出了视窗。", region=target_name)
            black_issue = not allowed
        if not black_issue:
            # More than a second AND a meaningful fraction of the loop. Leading
            # or trailing empty frames may be legitimate entrances/exits.
            limit = max(1000, target["duration_ms"] * 0.12)
            allowed = intent["dark_pause"] or intent["flashing"] or intent["sparse"] or intent["entry_exit"]
            if target["longest_interior_dark_ms"] >= limit:
                add(warnings if allowed else issues, "long_dark_gap",
                    f"{target_label}中段存在较长连续暗场，请增加可见主体或明确保留暗场的意图。",
                    region=target_name, duration_ms=target["longest_interior_dark_ms"])
            elif target["longest_dark_ms"] >= limit and target["dark_frame_fraction"] < 0.95:
                add(warnings, "edge_dark_hold", f"{target_label}开头或结尾有较长暗场，请检查出入场与循环节奏。",
                    region=target_name, duration_ms=target["longest_dark_ms"])

    if not black_issue and top["static"] and keys["static"] and not intent["all_off"]:
        allowed = intent["static"] or intent["sparse"]
        add(warnings if allowed else issues, "static_output",
            "顶屏和轴灯在整个时间轴中都完全不变；如需动画，请让形状、位置或颜色随帧变化。")

    for region, values in metrics["regions"].items():
        if values["frame_count"] < 12 or values["static"]:
            continue
        # Do not confuse a tiny moving star, a normal cut, or a strobe with a
        # broken loop. A dense seam much larger than every internal step is a
        # blocker only when the user explicitly requested seamless endpoints.
        severe = (values["loop_seam_mae"] >= 32 and
                  values["loop_seam_mae"] > max(values["step_mae_p95"] * 4, values["step_mae_max"] * 2) and
                  values["loop_seam_changed_led_fraction"] >= 0.35)
        if severe and not (intent["flashing"] or intent["entry_exit"]):
            add(issues if intent["seamless"] else warnings, "loop_seam_jump",
                "循环接缝的变化明显大于帧间变化，请检查是否需要补充回到开场的过程。", region=region)

    ai = design.get("ai")
    recipe = ai.get("recipe") if type(ai) is dict else design.get("recipe")
    inherited = []
    if type(recipe) is dict and type(recipe.get("scenes")) is list:
        for si, scene in enumerate(recipe["scenes"][:255]):
            if type(scene) is not dict:
                continue
            for region in ("top", "keys"):
                layers = scene.get(region)
                if type(layers) is not list:
                    continue
                for li, layer in enumerate(layers[:8]):
                    if type(layer) is dict and layer.get("kind") == "bitmap" and "palette" not in layer:
                        inherited.append(f"scenes[{si}].{region}[{li}]")
        if inherited:
            add(warnings, "bitmap_palette_inherited", "像素图省略了局部 palette，颜色将继承全局配色，请核对特征色。", layers=inherited)
    report["passed"] = not issues
    return report
