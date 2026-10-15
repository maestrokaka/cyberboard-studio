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
STRONG_CHANNEL_MIN = 160
NEAR_WHITE_CHANNEL_MIN = 160
NEAR_WHITE_MIN_CHANNEL_RATIO = 0.75
LARGE_NEAR_WHITE_FRACTION = 0.25
MAX_FRAMES = 255
RESERVED_KEYS = frozenset((57, 61, 74, 78, 82, 83, 84))
_RGB = re.compile(r"^#[0-9a-fA-F]{6}$")
_NEGATION = re.compile(r"(?:不要|不能|避免|不允许|不需要|没有|不是|无需|勿|非|"
                       r"\bnot|\bnever|\bwithout|\bavoid|\bdon't|\bdo not|\bno)"
                       r"\s*(?:(?:任何|出现|再|全屏|大面积|主体|变成|使用|太|过于|a\s+|any\s+|"
                       r"full[- ]screen\s+|large\s+|turning\s+|becoming\s+|make\s+|it\s+|too\s+|overly\s+)\s*)*$", re.I)
_REGION_WORDS = r"轴灯|键灯|顶屏|顶部|\bkey lights\b|\bkeys\b|\bbacklight\b|\btop (?:display|screen|matrix)\b"
_LESS_BRIGHT = (r"暗一点|暗一些|稍微暗|(?:亮度)?低一点|(?:亮度)?低一些|"
                r"(?:不要|别|避免)(?:太|过于)(?:明)?亮|\bdimmer\b|\blow\b|"
                r"\b(?:don't|do not) (?:make (?:it )?)?(?:too|overly) bright\b")


def _affirmed(text, pattern):
    return any(not _NEGATION.search(text[max(0, m.start() - 32):m.start()])
               for m in re.finditer(pattern, text, re.I))


def _regional_dim(text, subject):
    """Keep comparative brightness requests within their named region/clause."""
    for match in re.finditer(subject, text, re.I):
        if _NEGATION.search(text[max(0, match.start() - 32):match.start()]):
            continue
        body = re.split(r"[，。；,;\n]|" + _REGION_WORDS, text[match.end():match.end() + 40],
                        maxsplit=1, flags=re.I)[0]
        if _affirmed(body, _LESS_BRIGHT):
            return True
    return False


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
        "dim": (_affirmed(text, r"低亮|暗色|夜间|微光|柔和|柔光|\bdim\b|\blow brightness\b|"
                          r"\bdark ambient\b|\bsoft (?:light|glow|lighting)\b") or
                (not re.search(_REGION_WORDS, text, re.I) and _affirmed(text, _LESS_BRIGHT))),
        "dim_keys": _regional_dim(text, r"轴灯|键灯|\bkey lights\b|\bkeys\b|\bbacklight\b"),
        "dim_top": _regional_dim(text, r"顶屏|顶部|\btop (?:display|screen|matrix)\b"),
        "subtle_keys": _affirmed(text, r"轴灯(?!.{0,8}(?:不要|不能|避免|不需要|无需|勿)).{0,8}(?:衬托|陪衬|弱光|压低|低调)|"
                                r"(?:衬托|陪衬|压低).{0,8}轴灯|\bsubtle (?:key lights|backlight|keys)\b|"
                                r"\b(?:key lights|backlight|keys).{0,12}\bsubtle\b"),
        "bright": _affirmed(text, r"高亮|明亮|足够亮|亮度充足|强光|\bbright\b|\bhigh brightness\b"),
        "white_mix": _affirmed(text, r"白色|白光|白猫|白兔|雪白|粉彩|柔光|柔和|渐变|彩虹混色|"
                              r"\bwhite\b|\bpastel\w*\b|\bsoft (?:light|glow|lighting)\b|"
                              r"\bgradient\w*\b|\brainbow (?:mix|blend)\w*\b"),
        "pure_primary": _affirmed(text, r"(?:纯|正)(?:红|绿|蓝|黄|青|品红|橙)(?:色|光)?|"
                                 r"\b(?:pure|solid|saturated) (?:red|green|blue|yellow|cyan|magenta|orange)\b"),
        # This is a prohibition, so do not run it through the positive-intent
        # negation filter used for exceptions such as '不要白色'.
        "avoid_white": bool(re.search(r"(?:不要|避免|不能|不许|不允许|勿).{0,6}(?:白色|白光|泛白|发白|漂白)|"
                                      r"(?:不泛白|不发白|无白色)|\b(?:no|without|avoid) white\b|"
                                      r"\b(?:do not|don't) (?:turn white|wash out)\b", text, re.I)),
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
                             r"\b(?:key lights|backlight|backlighting) off\b|"
                             r"\b(?:turn off|disable) (?:the )?(?:key lights|backlight|backlighting)\b"),
    }


def _rounded(value):
    return round(value, 6) if math.isfinite(value) else None


def _percentile(ordered, fraction):
    """Nearest-rank percentile of nonblack max-channel samples; empty is zero."""
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else 0


def _near_white(rgb):
    peak = max(rgb)
    return peak >= NEAR_WHITE_CHANNEL_MIN and min(rgb) / peak >= NEAR_WHITE_MIN_CHANNEL_RATIO


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
    samples = [max(c) for frame in pixels for c in frame]
    nonblack = sorted(value for value in samples if value > 0)
    strong = sum(value >= STRONG_CHANNEL_MIN for value in samples)
    near_white = sum(_near_white(c) for frame in pixels for c in frame)
    total = count * len(active)
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
        "sampled_pixel_count": total, "nonblack_pixel_count": len(nonblack),
        "nonblack_max_channel_p50": _percentile(nonblack, 0.5),
        "nonblack_max_channel_p90": _percentile(nonblack, 0.9),
        "strong_pixel_count": strong, "strong_pixel_fraction": _rounded(strong / total),
        "strong_nonblack_fraction": _rounded(strong / len(nonblack)) if nonblack else 0,
        "near_white_pixel_count": near_white, "near_white_pixel_fraction": _rounded(near_white / total),
        "near_white_nonblack_fraction": _rounded(near_white / len(nonblack)) if nonblack else 0,
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


def _layer_colors(layer, palette):
    """Actual declared sources only, excluding unused bitmap palette entries."""
    opacity = layer.get("opacity", 1)
    peak_opacity = max(opacity["from"], opacity["to"]) if type(opacity) is dict else opacity
    if peak_opacity <= 0:
        return []
    if layer["kind"] == "bitmap":
        colors = layer.get("palette", palette)
        used = {int(c, 16) for row in layer["rows"] for c in row} - {0}
        values = [colors[i - 1] for i in sorted(used)]
    else:
        values = [layer["color"]]
        if "color_to" in layer:
            values.append(layer["color_to"])
    return [tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) for value in values]


def _saturated(rgb):
    peak = max(rgb)
    return peak >= STRONG_CHANNEL_MIN and (peak - min(rgb)) / peak >= 0.65


def _mixing_sources(layers, palette):
    """Conservative evidence of different saturated layers mixing towards white.

    Dominant/replace alone do not add per-channel color evidence. Any actual
    white/neutral source disables the finding rather than judging its purpose.
    Source colors are not modified or used to grant user-intent exceptions.
    """
    sources = [_layer_colors(layer, palette) for layer in layers]
    if any(_near_white(color) for colors in sources for color in colors):
        return False
    prior, bounds = [], [0, 0, 0]
    mixing = False
    for layer, colors in zip(layers, sources):
        saturated = [color for color in colors if _saturated(color)]
        current = [max((c[i] for c in saturated), default=0) for i in range(3)]
        blend = layer.get("blend", "add")
        unlike = any(max(abs(a[i] / max(a) - b[i] / max(b)) for i in range(3)) >= 0.5
                     for a in prior for b in saturated)
        if blend in ("add", "max"):
            combined = ([min(255, a + b) for a, b in zip(bounds, current)] if blend == "add"
                        else [max(a, b) for a, b in zip(bounds, current)])
            mixing = mixing or (unlike and _near_white(combined))
            bounds = combined
        else:
            # Upper bounds are enough for a warning candidate; actual output
            # must independently contain a large near-white area below.
            bounds = [max(a, b) for a, b in zip(bounds, current)]
        prior.extend(saturated)
    return mixing


def _white_mixing_evidence(design, recipe):
    """Only structurally valid, timing-matched recipe sources support this check."""
    if type(recipe) is not dict:
        return []
    from lighting_recipe import RecipeError, validate_recipe
    try:
        validate_recipe(recipe)
    except (RecipeError, TypeError, KeyError, RecursionError):
        return []
    if (recipe["frame_count"] != len(design["frames"]) or
            recipe["frame_count"] != len(design["keyframes"]) or recipe["speed_ms"] != design["speed_ms"]):
        return []
    evidence = []
    for si, scene in enumerate(recipe["scenes"]):
        for region, field, active in (("top", "frames", tuple(range(200))),
                                      ("keys", "keyframes", tuple(i for i in range(90) if i not in RESERVED_KEYS))):
            if not _mixing_sources(scene[region], recipe["palette"]):
                continue
            frames = design[field][scene["start"]:scene["end"]]
            total = len(frames) * len(active)
            count = sum(_near_white(tuple(int(frame[i][p:p + 2], 16) for p in (1, 3, 5)))
                        for frame in frames for i in active)
            fraction = count / total
            if fraction >= LARGE_NEAR_WHITE_FRACTION:
                evidence.append({"scene_index": si, "region": region,
                                 "near_white_pixel_fraction": _rounded(fraction)})
    return evidence


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
               "visibility_proxy": {"kind": "digital_rgb_not_measured_light_output",
                                    "visible_channel_min": VISIBLE_CHANNEL_MIN,
                                    "black_channel_max": BLACK_CHANNEL_MAX,
                                    "nonblack_channel_min": 1, "strong_channel_min": STRONG_CHANNEL_MIN,
                                    "near_white_peak_min": NEAR_WHITE_CHANNEL_MIN,
                                    "near_white_min_channel_ratio": NEAR_WHITE_MIN_CHANNEL_RATIO,
                                    "large_near_white_pixel_fraction": LARGE_NEAR_WHITE_FRACTION}, "regions": {}}
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
            bucket = warnings if intent["dim"] or intent["dim_" + target_name] or intent["static"] or intent["sparse"] else issues
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

    if not (intent["all_off"] or intent["keys_off"] or intent["dim"] or intent["dim_keys"] or intent["subtle_keys"]):
        # A real but uniformly weak key track is distinct from an absent/off
        # track. Static is not permission for weak encoding under a bright top.
        if (keys["nonblack_pixel_count"] and keys["peak_rgb_channel"] < 128 and
                keys["nonblack_max_channel_p90"] < 96 and top["peak_rgb_channel"] >= STRONG_CHANNEL_MIN):
            add(issues, "weak_keys_intensity",
                "顶屏明亮，但轴灯整体偏暗；请提高轴灯主题亮区，保留黑底和拖尾。",
                region="keys", peak_rgb_channel=keys["peak_rgb_channel"],
                nonblack_max_channel_p90=keys["nonblack_max_channel_p90"])
    if not (black_issue or intent["all_off"] or intent["top_off"] or intent["dim"] or intent["dim_top"]):
        if (top["nonblack_pixel_count"] and top["peak_rgb_channel"] < 96 and
                top["nonblack_max_channel_p90"] < 64):
            add(issues if intent["bright"] else warnings, "weak_top_intensity",
                "顶屏整体较暗，请确认是否符合你想要的效果。",
                region="top", peak_rgb_channel=top["peak_rgb_channel"],
                nonblack_max_channel_p90=top["nonblack_max_channel_p90"])

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
    if not intent["white_mix"]:
        evidence = _white_mixing_evidence(design, recipe)
        if evidence:
            # Images may legitimately contain an unmentioned white subject.
            # Pixel/source evidence cannot establish reference-image fidelity.
            block = not has_images and (intent["avoid_white"] or intent["pure_primary"])
            add(issues if block else warnings, "saturated_layers_whitened",
                "有色灯光重叠后出现大片近白色，请核对主体是否应该保持原色。",
                evidence=evidence)
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
