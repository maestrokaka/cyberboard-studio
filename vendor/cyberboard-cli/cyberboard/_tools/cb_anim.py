#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Deterministic recipe renderer for the ① display layer (40x5 = 200px per frame).

    cb_anim.py render  -r recipe.json -b base.json -o config.json [--gif art.gif]
    cb_anim.py preview -r recipe.json -o art.gif [--scale 16]
    cb_anim.py montage -r recipe.json -o sheet.png [--scale 8] [--max 24 | --no-seam]

A *recipe* is a small declarative JSON document. A deterministic renderer expands
it to 40x5xN frames — the AI/author only picks knobs, no raw code runs (whitelisted
effects). The frames feed cb_led's shared transforms: `render` patches them into a
complete base IR (display `frames` only; per-key `keyframes` kept from base, like
gif2ir), `preview` writes just the GIF for a fast visual loop.

Recipe shape (a single effect, or a `sequence` of segments concatenated):

    { "slot": 1, "speed_ms": 80,
      "sequence": [
        { "effect": "text_scroll", "text": "HELLO", "fg": "#00ff88" },
        { "effect": "solid", "color": "#000000", "frames": 8 },
        { "effect": "text_scroll", "text": "WORLD", "fg": "#ff0066", "gap": 40 }
      ] }

The four authoring knobs the user asked for map cleanly onto this:
  ① seamless loop  — text_scroll `gap: 0` (default) tiles toroidally, no seam.
  ② length         — text via `step` (px/frame), solid via `frames`.
  ③ MAX256         — firmware plays <=256 frames/slot (90 续5); we warn + truncate.
  ④ concatenate    — `sequence` appends short clips into one slot (≈ merger combine).

The whole recipe JSON is embedded in the output GIF's Comment (GIF has no EXIF), so
the artifact carries its own generator — the same convention cb_led uses (10/40).
"""
from __future__ import annotations

import argparse
import colorsys
import json
import math
import sys
from pathlib import Path

import cb_font  # BDF parser, glyph overrides, text_strip
import cb_led  # shared: frames_to_page, frames_to_gif, W, H, PIXELS, MAX_FRAMES

W, H, PIXELS, MAX_FRAMES = cb_led.W, cb_led.H, cb_led.PIXELS, cb_led.MAX_FRAMES
FONT_PATH = cb_font.FONT_PATH  # re-exported for backward compatibility

# Sentinel for a transparent pixel inside the compositor.  Any frame that still
# contains this value when it reaches frames_to_page is a bug — the codec guard
# will catch it with a clean error.
TRANSPARENT = "none"


def _warn(msg: str) -> None:
    print(f"cb_anim: {msg}", file=sys.stderr)


def _color(s: str) -> str:
    """Normalize a '#RRGGBB' string (also accepts without '#'); raise on garbage."""
    h = s.lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        raise SystemExit(f"cb_anim: bad color {s!r} (want #RRGGBB)")
    return "#" + h.lower()


def _bg_color(seg: dict, default: str = "#000000") -> str:
    """Return the background colour for a segment.

    - If ``"bg"`` is absent: returns ``default`` (opaque black by default).
    - If ``"bg"`` is explicitly ``"transparent"`` / ``"none"`` / ``"null"``
      (case-insensitive): returns the ``TRANSPARENT`` sentinel so a ``layers``
      compositor can punch through.
    - Otherwise: validates and normalises as ``#RRGGBB``.

    Use this instead of ``_color`` for the ``bg`` key so that a ``layers``
    compositor can overlay text onto a background without obscuring it.
    """
    raw = seg.get("bg")
    if raw is None:
        return default
    if str(raw).lower() in ("transparent", "none", "null"):
        return TRANSPARENT
    return _color(raw)


def _colors(seg: dict, key: str = "colors", minimum: int = 1) -> list[str]:
    """Parse a required list of '#RRGGBB' colors from a recipe segment."""
    raw = seg.get(key)
    if not isinstance(raw, list) or len(raw) < minimum:
        raise SystemExit(f"cb_anim: {seg.get('effect')!r} needs a {key!r} list "
                         f"of >= {minimum} colors")
    return [_color(c) for c in raw]


def _hsv_hex(h: float, s: float, v: float) -> str:
    """HSV (each 0..1, hue wraps) -> '#RRGGBB'. The hue wheel is periodic, which is
    what makes a full hue sweep loop seamlessly."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(max(s, 0.0), 1.0), min(max(v, 0.0), 1.0))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _rgb(s: str) -> tuple[int, int, int]:
    h = s.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp_hex(c0: str, c1: str, t: float) -> str:
    """Linear-interpolate two '#RRGGBB' by t in [0,1]."""
    a, b = _rgb(c0), _rgb(c1)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


# --- effects (procedural family) -------------------------------------------------

def _effect_text_scroll(seg: dict) -> list[list[str]]:
    """Horizontal marquee. gap=0 -> seamless toroidal tiling (no seam, ①)."""
    text = seg.get("text")
    if not text:
        raise SystemExit("cb_anim: text_scroll needs a non-empty 'text'")
    fg = _color(seg.get("fg", "#00ff88"))
    bg = _bg_color(seg)
    spacing = int(seg.get("spacing", 1))
    step = max(1, int(seg.get("step", 1)))
    gap = max(0, int(seg.get("gap", 0)))
    direction = seg.get("direction", "left")
    if direction not in ("left", "right"):
        raise SystemExit(f"cb_anim: text_scroll direction must be left/right, got {direction!r}")

    mask, ink_w = cb_font.text_strip(text, spacing, H)
    strip_w = ink_w + gap  # gap columns (blank) appended for the loop seam
    nframes = math.ceil(strip_w / step)
    if strip_w % step:
        _warn(f"text_scroll {text!r}: strip width {strip_w} not divisible by step {step} "
              f"— loop may jitter at the wrap")

    frames: list[list[str]] = []
    for i in range(nframes):
        shift = i * step
        off = (-shift if direction == "right" else shift) % strip_w
        flat = [bg] * PIXELS
        for y in range(H):
            row = mask[y]
            base = y * W
            for x in range(W):
                sx = (off + x) % strip_w
                if sx < ink_w and row[sx]:
                    flat[base + x] = fg
        frames.append(flat)
    return frames


def _effect_solid(seg: dict) -> list[list[str]]:
    """A static color held for N frames — useful as a separator/segment (②/④)."""
    color = _color(seg.get("color", "#000000"))
    n = max(1, int(seg.get("frames", 1)))
    return [[color] * PIXELS for _ in range(n)]


def _effect_hue_cycle(seg: dict) -> list[list[str]]:
    """Rainbow that cycles the hue wheel — the '模様回転' archetype as a marquee.
    Seamless by construction: a full hue sweep returns to the start (frame N == 0).
    `spread` (degrees across the 40px width) turns a uniform breathing strip into a
    flowing rainbow; `direction` chooses which way it flows."""
    sat = float(seg.get("saturation", 1.0))
    val = float(seg.get("value", 1.0))
    cycle = max(1, int(seg.get("cycle_frames", seg.get("frames", 60))))
    spread = float(seg.get("spread", 0.0)) / 360.0  # hue turns across the strip width
    direction = seg.get("direction", "left")
    if direction not in ("left", "right"):
        raise SystemExit(f"cb_anim: hue_cycle direction must be left/right, got {direction!r}")
    sign = -1.0 if direction == "right" else 1.0
    frames: list[list[str]] = []
    for i in range(cycle):
        base = sign * i / cycle
        cols = [_hsv_hex(base + spread * (x / W), sat, val) for x in range(W)]
        frames.append([cols[x] for _y in range(H) for x in range(W)])
    return frames


def _effect_stripes(seg: dict) -> list[list[str]]:
    """Sliding colored bands (vertical, or diagonal via `slant`). Seamless by modulo
    tiling over period = len(colors) * band_width."""
    colors = _colors(seg, minimum=1)
    band = max(1, int(seg.get("band_width", 4)))
    step = max(1, int(seg.get("step", 1)))
    slant = int(seg.get("slant", 0))  # x-shift per row -> diagonal bands
    direction = seg.get("direction", "left")
    if direction not in ("left", "right"):
        raise SystemExit(f"cb_anim: stripes direction must be left/right, got {direction!r}")
    period = len(colors) * band
    nframes = math.ceil(period / step)
    if period % step:
        _warn(f"stripes: period {period} not divisible by step {step} — loop may jitter")
    sign = -1 if direction == "right" else 1
    frames: list[list[str]] = []
    for i in range(nframes):
        off = (sign * i * step) % period
        flat = [colors[0]] * PIXELS
        for y in range(H):
            r = y * W
            for x in range(W):
                sx = (x + y * slant + off) % period
                flat[r + x] = colors[(sx // band) % len(colors)]
        frames.append(flat)
    return frames


def _effect_gradient_scroll(seg: dict) -> list[list[str]]:
    """A closed-loop multi-stop gradient scrolling horizontally (seamless). The ramp
    wraps colors[-1] -> colors[0], so the scroll has no seam. `width` is the px span of
    one full gradient loop; `slant` tilts it diagonally."""
    colors = _colors(seg, minimum=2)
    width = max(2, int(seg.get("width", W)))
    step = max(1, int(seg.get("step", 1)))
    slant = int(seg.get("slant", 0))
    direction = seg.get("direction", "left")
    if direction not in ("left", "right"):
        raise SystemExit(f"cb_anim: gradient_scroll direction must be left/right, got {direction!r}")
    n = len(colors)
    ramp = []
    for px in range(width):
        t = px / width * n  # position around the closed color loop, 0..n
        i0 = int(t) % n
        ramp.append(_lerp_hex(colors[i0], colors[(i0 + 1) % n], t - int(t)))
    nframes = math.ceil(width / step)
    if width % step:
        _warn(f"gradient_scroll: width {width} not divisible by step {step} — loop may jitter")
    sign = -1 if direction == "right" else 1
    frames: list[list[str]] = []
    for i in range(nframes):
        off = (sign * i * step) % width
        flat = [ramp[0]] * PIXELS
        for y in range(H):
            r = y * W
            for x in range(W):
                flat[r + x] = ramp[(x + y * slant + off) % width]
        frames.append(flat)
    return frames


# --- effects (sprite family — externally-loaded artwork) -------------------------

def _load_sprite(seg: dict) -> list[list[str]]:
    """Load a sprite image, fit its width to 40px (keeping the vertical axis — the
    scroll axis — at full proportional height), and return an N-row x 40-col grid of
    '#RRGGBB'. Uses the first frame of an animated GIF. Lazy PIL import (the [led]
    extra), matching cb_led."""
    path = seg.get("sprite")
    if not path:
        raise SystemExit("cb_anim: sprite needs a 'sprite' image path")
    src = Path(path)
    if not src.exists():
        raise SystemExit(f"cb_anim: sprite not found: {src}")
    from PIL import Image
    modes = {"nearest": Image.Resampling.NEAREST, "lanczos": Image.Resampling.LANCZOS,
             "box": Image.Resampling.BOX}
    resample = seg.get("resample", "nearest")
    if resample not in modes:
        raise SystemExit(f"cb_anim: sprite resample must be one of {sorted(modes)}, "
                         f"got {resample!r}")
    try:
        with Image.open(src) as im:  # context manager so the file handle isn't leaked
            im.seek(0)  # first frame of an animated GIF
            rgb = im.convert("RGB")  # independent copy — safe to use after the file closes
    except OSError as e:
        raise SystemExit(f"cb_anim: cannot read sprite {src} as an image: {e}")
    ow, oh = rgb.size
    nh = round(oh * W / ow)  # fit width to 40, keep height proportional (the scroll axis)
    if nh < H:
        raise SystemExit(f"cb_anim: sprite too short — fits to {W}x{nh}, need height "
                         f">= {H} for a vertical scroll (use a taller image)")
    fit = rgb.resize((W, nh), modes[resample])
    px = fit.load()
    return [["#%02x%02x%02x" % px[x, y] for x in range(W)] for y in range(nh)]


def _effect_sprite(seg: dict) -> list[list[str]]:
    """Vertical marquee: slide the 5px display window up (or down) a tall sprite image
    (width-fit to 40px, full proportional height = the scroll axis). The 'キャラ縦
    スクロール' archetype.

    Loop semantics are the INVERSE of text_scroll's. For arbitrary artwork, gap=0 wrap
    joins the sprite's top edge directly to its bottom edge — a visible jump unless the
    art tiles vertically. The clean loop here is gap>0 (scroll fully off into `bg`, then
    re-enter): the blank-to-blank join is what's seam-free. So set gap>=5 for a one-shot
    scroll that loops cleanly; gap=0 only if your sprite tiles vertically."""
    grid = _load_sprite(seg)
    n_rows = len(grid)
    step = max(1, int(seg.get("step", 1)))
    gap = max(0, int(seg.get("gap", 0)))
    bg = _color(seg.get("bg", "#000000"))
    direction = seg.get("direction", "up")
    if direction not in ("up", "down"):
        raise SystemExit(f"cb_anim: sprite direction must be up/down, got {direction!r}")
    total = n_rows + gap  # rows the window cycles through (sprite + blank gap)
    nframes = math.ceil(total / step)
    if total % step:
        _warn(f"sprite: scroll height {total} not divisible by step {step} — loop may jitter")
    if nframes > MAX_FRAMES:
        _warn(f"sprite: {n_rows}px-tall sprite at step {step} needs {nframes} frames > "
              f"{MAX_FRAMES}/slot — the scroll is truncated before it loops (later frames "
              f"dropped); raise `step` to fit")
    sign = 1 if direction == "up" else -1  # up = content rises (window offset increases)
    frames: list[list[str]] = []
    for i in range(nframes):
        off = (sign * i * step) % total
        flat = [bg] * PIXELS
        for wy in range(H):  # window row -> display y; gap rows stay bg
            src = (off + wy) % total
            if src < n_rows:
                row = grid[src]
                base = wy * W
                for x in range(W):
                    flat[base + x] = row[x]
        frames.append(flat)
    return frames


EFFECTS = {
    "text_scroll": _effect_text_scroll,
    "solid": _effect_solid,
    "hue_cycle": _effect_hue_cycle,
    "stripes": _effect_stripes,
    "gradient_scroll": _effect_gradient_scroll,
    "sprite": _effect_sprite,
}


# --- layer compositor ------------------------------------------------------------

def _composite(layer_segs: list[dict]) -> list[list[str]]:
    """Composite a stack of effect layers bottom-to-top, alpha (transparent) punching
    through to the layer below.

    Frame-count policy:
    - Try ``math.lcm`` of all layer lengths — the natural seamless period.
    - If the LCM > MAX_FRAMES, fall back to ``max`` of all lengths and warn that
      the layers will drift at the loop seam (they won't repeat in phase).
    """
    if not layer_segs:
        raise SystemExit("cb_anim: 'layers' must be a non-empty list")
    layer_frames: list[list[list[str]]] = []
    for i, seg in enumerate(layer_segs):
        if "layers" in seg or "sequence" in seg:
            raise SystemExit(f"cb_anim: layers[{i}] must not contain 'layers' or 'sequence' "
                             f"(nesting is not supported)")
        layer_frames.append(_render_segment(seg))

    lens = [len(lf) for lf in layer_frames]
    natural = math.lcm(*lens)
    if natural <= MAX_FRAMES:
        n = natural
    else:
        n = max(lens)
        _warn(f"layers: lcm of layer lengths {lens} = {natural} > {MAX_FRAMES}; "
              f"using max({n}) — the layers will drift at the loop seam")

    composited: list[list[str]] = []
    for i in range(n):
        flat = [TRANSPARENT] * PIXELS
        for lf in layer_frames:
            src = lf[i % len(lf)]
            flat = [
                (src[j] if src[j] != TRANSPARENT else flat[j])
                for j in range(PIXELS)
            ]
        # bottom layer may still carry TRANSPARENT if it also used transparent bg —
        # resolve remaining sentinels to black so the codec boundary is always opaque
        composited.append([px if px != TRANSPARENT else "#000000" for px in flat])
    return composited


def _render_segment(seg: dict) -> list[list[str]]:
    """Dispatch a single segment: either a ``layers`` compositor or a named effect."""
    if "layers" in seg:
        return _composite(seg["layers"])
    eff = seg.get("effect")
    fn = EFFECTS.get(eff)
    if fn is None:
        raise SystemExit(f"cb_anim: unknown effect {eff!r} "
                         f"(have: {', '.join(sorted(EFFECTS))}; "
                         f"for compositing use 'layers': [...])")
    return fn(seg)


# --- recipe -> frames ------------------------------------------------------------

def _assert_opaque(frames: list[list[str]]) -> None:
    """Fail cleanly if any TRANSPARENT sentinel survives to the codec boundary.

    A bare ``bg: "transparent"`` used outside a ``layers`` compositor has nothing
    beneath it to punch through to, so the sentinel ("none") would otherwise reach
    a codec and crash ungracefully — ``frames_to_gif`` (preview/montage) chokes on
    it, and ``frames_to_page`` (write) has its own backstop guard. Catching it here
    makes *every* output path fail with the same actionable message.
    """
    leak = next((i for i, f in enumerate(frames) if TRANSPARENT in f), None)
    if leak is not None:
        raise SystemExit(
            f"cb_anim: transparent bg at frame {leak} has nothing beneath it — "
            f"bg='transparent' is only valid inside a 'layers' composite "
            f"(wrap the effect: 'layers': [<background>, <this effect>])")


def _render_recipe(recipe: dict) -> tuple[int, int, list[list[str]]]:
    """Expand a recipe to (slot, speed_ms, frames). Caps at MAX_FRAMES with a
    generation-time warning that names the overflow (advisor: warn early, ③)."""
    slot = int(recipe.get("slot", 1))
    speed = int(recipe.get("speed_ms", 100))
    segments = recipe.get("sequence") or [recipe]  # single-effect convenience
    frames: list[list[str]] = []
    for seg in segments:
        frames.extend(_render_segment(seg))
    _assert_opaque(frames)
    if len(frames) > MAX_FRAMES:
        _warn(f"recipe expands to {len(frames)} frames > {MAX_FRAMES}/slot "
              f"— truncating to {MAX_FRAMES} (firmware playback cap, 90 续5)")
        frames = frames[:MAX_FRAMES]
    return slot, speed, frames


# --- subcommands -----------------------------------------------------------------

def render(args: argparse.Namespace) -> int:
    recipe = json.loads(Path(args.recipe).read_text())
    slot, speed, frames = _render_recipe(recipe)
    if args.slot is not None:
        slot = args.slot
    base = json.loads(Path(args.base).read_text())
    page = cb_led.frames_to_page(base, slot, frames, speed)
    Path(args.output).write_text(json.dumps(base, ensure_ascii=False, indent=2))
    print(f"cb_anim: slot {slot} (page {page['page_index']}) <- "
          f"{page['frames']['frame_num']} display frames, speed_ms={speed}; "
          f"keyframes kept from base -> {args.output}")
    if args.gif:
        cb_led.frames_to_gif(frames, args.gif, args.scale, speed,
                             json.dumps(recipe, ensure_ascii=False))
        print(f"cb_anim: preview -> {args.gif}")
    return 0


def preview(args: argparse.Namespace) -> int:
    recipe = json.loads(Path(args.recipe).read_text())
    _slot, speed, frames = _render_recipe(recipe)
    n = cb_led.frames_to_gif(frames, args.output, args.scale, speed,
                             json.dumps(recipe, ensure_ascii=False))
    print(f"cb_anim: {n} frames @ {W * args.scale}x{H * args.scale}, "
          f"{speed}ms/frame -> {args.output}")
    return 0


def montage(args: argparse.Namespace) -> int:
    """recipe -> a tall still PNG (time goes down) so motion/loop/seam can be judged
    in a viewer that only shows a GIF's first frame (e.g. the Read tool)."""
    recipe = json.loads(Path(args.recipe).read_text())
    _slot, _speed, frames = _render_recipe(recipe)
    info = cb_led.frames_to_montage(frames, args.output, args.scale,
                                    args.max, not args.no_seam)
    shown, total = info["shown"], info["total"]
    if len(shown) == total:
        note = f"all {total}"
    elif len(shown) == 1:
        note = f"1 of {total} (frame {shown[0]})"
    else:
        note = f"{len(shown)} of {total} (even-sampled, incl. first+last)"
    seam = " + wrap-seam pair [last,first]" if info["seam"] else ""
    print(f"cb_anim: montage {note} frames{seam} @ "
          f"{W * args.scale}x{H * args.scale}/frame -> {args.output}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Recipe -> IR display-layer (40x5) renderer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="recipe -> IR frames patched into a base (+ optional GIF)")
    r.add_argument("-r", "--recipe", required=True, help="recipe JSON")
    r.add_argument("-b", "--base", required=True, help="complete base IR config JSON")
    r.add_argument("-o", "--output", required=True, help="output IR config JSON")
    r.add_argument("--slot", type=int, help="override recipe slot (1/2/3 = page 5/6/7)")
    r.add_argument("--gif", help="also write a preview GIF here")
    r.add_argument("--scale", type=int, default=16, help="GIF pixel scale-up (default 16)")
    r.set_defaults(func=render)

    p = sub.add_parser("preview", help="recipe -> GIF only (fast visual loop, no base)")
    p.add_argument("-r", "--recipe", required=True, help="recipe JSON")
    p.add_argument("-o", "--output", required=True, help="output animated GIF")
    p.add_argument("--scale", type=int, default=16, help="pixel scale-up (default 16)")
    p.set_defaults(func=preview)

    m = sub.add_parser("montage",
                       help="recipe -> tall PNG (time down) to inspect motion/loop in a still viewer")
    m.add_argument("-r", "--recipe", required=True, help="recipe JSON")
    m.add_argument("-o", "--output", required=True, help="output PNG (frame montage)")
    m.add_argument("--scale", type=int, default=8, help="pixel scale-up per frame (default 8)")
    m.add_argument("--max", type=int, default=24,
                   help="max frame rows; more frames are even-sampled (default 24)")
    m.add_argument("--no-seam", action="store_true",
                   help="omit the wrap-seam [last,first] pair at the bottom")
    m.set_defaults(func=montage)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
