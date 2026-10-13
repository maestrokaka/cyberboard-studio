#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Codec between an animated GIF and the IR display layer (40x5 = 200px per frame).

    cb_led.py gif2ir -i art.gif -b base.json --slot 1 -o config.json   # GIF -> IR slot
    cb_led.py ir2gif -i config.json --slot 1 -o art.gif [--recipe ...] # IR slot -> GIF
    cb_led.py play   -i art.gif [--loop N | --once] [--scale 2]        # play in the terminal
    cb_led.py play   -i config.json --slot 1                           # play an IR slot
    cb_led.py recipe  art.gif [--set "..."]                            # GIF comment R/W

The display panel is a 40x5 grid; each frame is 200 `#RRGGBB` strings in row-major
order (index = y*40 + x, top-left origin — confirmed by render_tui.py). A slot is a
Custom LED page: slot 1/2/3 == page_index 5/6/7 (.claude/rules/10).

Pure file->file (no device I/O), like cb_build. `gif2ir` patches ONLY the display
`frames` of the chosen page in a complete base IR — JSON_START erases the whole flash
so the written config must be complete (90 续8), and per-key `keyframes` are kept from
the base (the GIF<->keyframes-90 index map is still unresolved — 90 续15). The firmware
plays at most 256 frames/slot (90 续5), so gif2ir caps at 256 and reports the drop.

The GIF is the community-shareable interchange artifact; its generation recipe/prompt
lives in the GIF Comment Extension (GIF has no EXIF) — `ir2gif --recipe` embeds it,
`recipe` reads/writes it. The IR JSON stays official-schema-clean (no recipe field).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

W, H = 40, 5
PIXELS = W * H  # 200
MAX_FRAMES = 256  # firmware playback cap per slot (90 续5)

ESC = "\x1b"
RESET = f"{ESC}[0m"
UPPER_HALF = "▀"  # U+2580: fg paints the top pixel, bg the bottom pixel


def _warn(msg: str) -> None:
    print(f"cb_led: {msg}", file=sys.stderr)


def _slot_to_page(slot: int) -> int:
    if slot not in (1, 2, 3):
        raise SystemExit(f"cb_led: --slot must be 1, 2 or 3 (got {slot})")
    return slot + 4  # slot 1/2/3 -> page_index 5/6/7


def _page(config: dict, page_index: int) -> dict:
    try:
        return next(p for p in config["page_data"] if p.get("page_index") == page_index)
    except StopIteration:
        raise SystemExit(f"cb_led: config has no page_index {page_index}")


def _hex_px(s: str) -> tuple[int, int, int]:
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


# --- shared frame transforms (reused by gif2ir/ir2gif and cb_anim) ---------------

def frames_to_page(base: dict, slot: int, frames: list[list[str]],
                   speed_ms: int | None = None, lightness: int | None = None) -> dict:
    """Patch `frames` (list of 200 `#RRGGBB`) into the display layer of a base IR.

    Caps at MAX_FRAMES (firmware playback limit, 90 续5) and keeps the page's
    per-key `keyframes` untouched. The single source of truth for the GIF path
    (gif2ir) and the recipe path (cb_anim) alike. Returns the patched page.
    """
    page_index = _slot_to_page(slot)
    page = _page(base, page_index)
    # Guard: TRANSPARENT sentinel ("none") must never reach the codec — it means
    # a layers compositor was not used to resolve alpha (or a single-effect used
    # bg="transparent" outside a layers context).
    trans = next(
        (f"frame {i}, px {j}" for i, f in enumerate(frames) for j, px in enumerate(f)
         if px == "none"),
        None,
    )
    if trans is not None:
        raise SystemExit(
            f"cb_led: unresolved transparent pixel at {trans} — "
            f"bg='transparent' requires a 'layers' compositor (use 'layers': [...] in your recipe)"
        )
    bad = next((i for i, f in enumerate(frames) if len(f) != PIXELS), None)
    if bad is not None:
        raise SystemExit(f"cb_led: frame {bad} has {len(frames[bad])} px, expected {PIXELS}")
    if len(frames) > MAX_FRAMES:
        _warn(f"{len(frames)} frames; firmware plays only {MAX_FRAMES}/slot "
              f"— dropping {len(frames) - MAX_FRAMES}")
        frames = frames[:MAX_FRAMES]
    page["frames"] = {
        "valid": 1,
        "frame_num": len(frames),
        "frame_data": [{"frame_index": i, "frame_RGB": f} for i, f in enumerate(frames)],
    }
    page["valid"] = True
    if speed_ms is not None:
        page["speed_ms"] = speed_ms
    if lightness is not None:
        page["lightness"] = lightness
    return page


def frames_to_gif(frames: list[list[str]], output: str, scale: int = 16,
                  duration: int = 100, recipe: str | None = None, loop: int = 0) -> int:
    """Write `frames` (list of 200 `#RRGGBB`) as a scaled, looping animated GIF."""
    from PIL import Image

    if not frames:
        raise SystemExit("cb_led: no frames to write")
    imgs: list[Image.Image] = []
    for k, f in enumerate(frames):
        if len(f) != PIXELS:
            raise SystemExit(f"cb_led: frame {k} has {len(f)} px, expected {PIXELS}")
        img = Image.new("RGB", (W, H))
        img.putdata([_hex_px(s) for s in f])
        imgs.append(img.resize((W * scale, H * scale), Image.Resampling.NEAREST))
    save_kw: dict = dict(save_all=True, append_images=imgs[1:], duration=duration,
                         loop=loop, disposal=2)
    if recipe:
        save_kw["comment"] = recipe.encode("utf-8")
    imgs[0].save(output, **save_kw)
    return len(imgs)


def frames_to_montage(frames: list[list[str]], output: str, scale: int = 8,
                      max_rows: int = 24, seam: bool = True) -> dict:
    """Tile `frames` into one tall PNG — time goes downward — to inspect motion.

    A GIF renders as a still in many viewers (the Read tool shows only the first
    frame), so a recipe's motion / loop / seam can't be judged from a GIF alone;
    a montage of time-ordered frame strips can. Samples to <= `max_rows` frames,
    always keeping the first and last (the loop seam matters most), and — unless
    `seam` is off — appends the wrap pair [last, first] adjacently under a colored
    band so the loop join can be read directly. Returns
    {total, shown: [indices], seam: bool} so the caller can log what was sampled
    (no silent drop). Each strip is W*scale wide, H*scale tall.
    """
    from PIL import Image

    if not frames:
        raise SystemExit("cb_led: no frames to montage")
    bad = next((i for i, f in enumerate(frames) if len(f) != PIXELS), None)
    if bad is not None:
        raise SystemExit(f"cb_led: frame {bad} has {len(frames[bad])} px, expected {PIXELS}")

    n = len(frames)
    max_rows = max(1, max_rows)
    if n <= max_rows:
        shown = list(range(n))
    elif max_rows == 1:
        shown = [0]  # a one-row montage: just the first frame (avoids /0 below)
    else:
        shown = sorted({round(i * (n - 1) / (max_rows - 1)) for i in range(max_rows)})

    sw, sh, sep = W * scale, H * scale, 2
    white, band = (255, 255, 255), (255, 120, 0)  # band marks the wrap-seam section

    def strip(idx: int) -> Image.Image:
        img = Image.new("RGB", (W, H))
        img.putdata([_hex_px(s) for s in frames[idx]])
        return img.resize((sw, sh), Image.Resampling.NEAREST)

    # each part is (content, height): content is a frame-strip Image or an RGB fill
    parts: list[tuple[Image.Image | tuple[int, int, int], int]] = []
    for idx in shown:
        parts += [(strip(idx), sh), (white, sep)]
    parts.pop()  # no trailing gap
    show_seam = seam and n > 1
    if show_seam:  # colored band, then the wrap pair [last, first] adjacent
        parts += [(white, sep), (band, sep * 4), (strip(n - 1), sh), (white, sep), (strip(0), sh)]

    canvas = Image.new("RGB", (sw, sum(h for _, h in parts)), white)
    y = 0
    for content, h in parts:
        if isinstance(content, Image.Image):
            canvas.paste(content, (0, y))
        elif content != white:  # a non-background fill band
            canvas.paste(Image.new("RGB", (sw, h), content), (0, y))
        y += h
    canvas.save(output)
    return {"total": n, "shown": shown, "seam": show_seam}


# --- GIF -> IR -------------------------------------------------------------------

def _gif_frames(path: Path, resample: str) -> tuple[list[list[str]], int | None]:
    """Return (per-frame 200-hex lists downsampled to 40x5, first-frame duration ms)."""
    from PIL import Image

    modes = {"nearest": Image.Resampling.NEAREST, "lanczos": Image.Resampling.LANCZOS,
             "box": Image.Resampling.BOX}
    filt = modes[resample]
    im = Image.open(path)
    n = getattr(im, "n_frames", 1)
    duration = im.info.get("duration")  # ms; per the first frame
    frames: list[list[str]] = []
    for i in range(n):
        im.seek(i)  # sequential forward seek composites GIF disposal in Pillow
        rgb = im.convert("RGB")
        if rgb.size != (W, H):
            rgb = rgb.resize((W, H), filt)
        raw = rgb.tobytes()  # RGB triples; stable across Pillow versions
        frames.append(["#%02x%02x%02x" % (raw[j], raw[j + 1], raw[j + 2])
                       for j in range(0, len(raw), 3)])
    return frames, (int(duration) if duration else None)


def gif2ir(args: argparse.Namespace) -> int:
    base = json.loads(Path(args.base).read_text())
    frames, gif_ms = _gif_frames(Path(args.input), args.resample)
    speed = args.speed_ms if args.speed_ms is not None else gif_ms
    page = frames_to_page(base, args.slot, frames, speed, args.lightness)
    page_index = page["page_index"]

    Path(args.output).write_text(json.dumps(base, ensure_ascii=False, indent=2))
    note = f", speed_ms={page['speed_ms']}" if speed is not None else ""
    print(f"cb_led: slot {args.slot} (page {page_index}) <- {page['frames']['frame_num']} "
          f"display frames{note}; keyframes kept from base -> {args.output}")
    from PIL import Image  # report embedded recipe, if any
    comment = Image.open(args.input).info.get("comment")
    if comment:
        text = comment.decode("utf-8", "replace") if isinstance(comment, bytes) else comment
        print(f"cb_led: embedded recipe: {text}")
    return 0


# --- IR -> GIF -------------------------------------------------------------------

def ir2gif(args: argparse.Namespace) -> int:
    config = json.loads(Path(args.input).read_text())
    page_index = _slot_to_page(args.slot)
    page = _page(config, page_index)
    fd = page.get("frames", {}).get("frame_data", [])
    if not fd:
        raise SystemExit(f"cb_led: page {page_index} has no display frames")

    frames = [fr["frame_RGB"] for fr in fd]
    # ir2gif is a viewer; GIF can't faithfully hold rich color or dup frames (90 续17).
    # Warn rather than crush silently (project rule: silent cap 禁止).
    colors = {px for f in frames for px in f}
    if len(colors) > 256:
        _warn(f"{len(colors)} distinct colors across frames > 256 — GIF's single global "
              f"palette will approximate color (the IR JSON is the lossless form)")
    dups = sum(1 for i in range(1, len(frames)) if frames[i] == frames[i - 1])
    if dups:
        _warn(f"{dups} identical consecutive frame(s) will be coalesced by the GIF writer "
              f"(playback timing preserved, but the GIF's frame count will differ)")
    duration = args.speed_ms if args.speed_ms is not None else page.get("speed_ms", 100)
    n = frames_to_gif(frames, args.output, args.scale, duration, args.recipe)
    rec = " + recipe" if args.recipe else ""
    print(f"cb_led: slot {args.slot} (page {page_index}) -> {n} frames "
          f"@ {W * args.scale}x{H * args.scale}, {duration}ms/frame{rec} -> {args.output}")
    return 0


# --- recipe (GIF Comment Extension) ---------------------------------------------

def recipe(args: argparse.Namespace) -> int:
    from PIL import Image, ImageSequence

    im = Image.open(args.input)
    if args.set is None:
        comment = im.info.get("comment")
        if not comment:
            print("cb_led: (no recipe embedded)")
            return 0
        print(comment.decode("utf-8", "replace") if isinstance(comment, bytes) else comment)
        return 0
    # rewrite preserving every frame + timing
    frames = [f.convert("RGB") for f in ImageSequence.Iterator(im)]
    durations = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        durations.append(im.info.get("duration", 100))
    frames[0].save(args.input, save_all=True, append_images=frames[1:],
                   duration=durations, loop=im.info.get("loop", 0), disposal=2,
                   comment=args.set.encode("utf-8"))
    print(f"cb_led: recipe set on {args.input}")
    return 0


# --- terminal playback (half-block ▀) -------------------------------------------

def _halfblock_lines(frame: list[str], scale: int) -> list[str]:
    """Render one 200-px frame as 3 ANSI lines of upper-half-blocks.

    Two pixel rows share one text line: the foreground colors the top pixel and
    the background the bottom (U+2580 fills the upper half). Row 4 (the 5th,
    unpaired) leaves its lower half as the terminal's default bg. `scale` repeats
    each pixel horizontally (a cell is 1px wide x 2px tall, so widening helps it
    read closer to square).
    """
    px = [_hex_px(s) for s in frame]
    lines: list[str] = []
    for top in (0, 2, 4):
        bot = top + 1
        cells = []
        for x in range(W):
            tr, tg, tb = px[top * W + x]
            if bot < H:
                br, bgc, bb = px[bot * W + x]
                cells.append(f"{ESC}[38;2;{tr};{tg};{tb};48;2;{br};{bgc};{bb}m{UPPER_HALF * scale}")
            else:
                cells.append(f"{ESC}[38;2;{tr};{tg};{tb};49m{UPPER_HALF * scale}")
        lines.append("".join(cells) + RESET)
    return lines


def _play_frames(rendered: list[list[str]], delay: float, passes: int) -> None:
    """Animate pre-rendered frames in place on a TTY. `passes` 0 means forever."""
    out = sys.stdout
    height = len(rendered[0])  # grid text lines (3)
    out.write(f"{ESC}[?25l")  # hide cursor
    try:
        first = True
        count = 0
        while passes == 0 or count < passes:
            for lines in rendered:
                if not first:
                    out.write(f"{ESC}[{height}A")  # back to the top of the grid
                out.write("\r" + "\n".join(lines) + "\n")
                out.flush()
                first = False
                time.sleep(delay)
            count += 1
    except KeyboardInterrupt:
        pass  # Ctrl-C is the documented way to stop playback — exit the loop quietly
    finally:
        out.write(f"{ESC}[?25h")  # restore the cursor whatever happened
        out.flush()


def play(args: argparse.Namespace) -> int:
    if args.scale < 1:
        raise SystemExit("cb_led: --scale must be >= 1")
    if args.fps is not None and args.fps <= 0:
        raise SystemExit("cb_led: --fps must be > 0")
    if args.loop is not None and args.loop < 1:
        raise SystemExit("cb_led: --loop must be >= 1 (omit it to loop forever)")

    if args.slot is not None:
        config = json.loads(Path(args.input).read_text())
        page_index = _slot_to_page(args.slot)
        page = _page(config, page_index)
        fd = page.get("frames", {}).get("frame_data", [])
        if not fd:
            raise SystemExit(f"cb_led: page {page_index} has no display frames")
        frames = [fr["frame_RGB"] for fr in fd]
        default_ms = page.get("speed_ms", 100)
        src = f"slot {args.slot} (page {page_index}) of {Path(args.input).name}"
    else:
        frames, gif_ms = _gif_frames(Path(args.input), args.resample)
        default_ms = gif_ms or 100
        src = Path(args.input).name

    if not frames:
        raise SystemExit(f"cb_led: no frames to play in {Path(args.input).name}")
    bad = next((i for i, f in enumerate(frames) if len(f) != PIXELS), None)
    if bad is not None:
        raise SystemExit(f"cb_led: frame {bad} has {len(frames[bad])} px, expected {PIXELS}")
    if len(frames) > MAX_FRAMES:
        _warn(f"{len(frames)} frames; firmware plays only {MAX_FRAMES}/slot "
              f"— showing the first {MAX_FRAMES}")
        frames = frames[:MAX_FRAMES]

    ms = (1000.0 / args.fps) if args.fps else (
        args.speed_ms if args.speed_ms is not None else default_ms)
    delay = max(ms, 1.0) / 1000.0
    passes = 1 if args.once else (args.loop if args.loop else 0)
    rendered = [_halfblock_lines(f, args.scale) for f in frames]

    if not sys.stdout.isatty():
        # piped / redirected: no animation, just one static frame
        print("\n".join(rendered[0]))
        _warn("stdout is not a TTY — printed a single static frame (no animation)")
        return 0
    if os.environ.get("COLORTERM", "").lower() not in ("truecolor", "24bit"):
        _warn("COLORTERM is not 'truecolor' — the terminal may approximate colors")
    if len(rendered) == 1:
        print("\n".join(rendered[0]))  # a single-frame config is a static image
        return 0

    print(f"cb_led: playing {src} — {len(frames)} frames @ {1000.0 / max(ms, 1.0):.1f} fps "
          f"({'∞' if passes == 0 else passes} pass{'' if passes == 1 else 'es'}); Ctrl-C to stop")
    _play_frames(rendered, delay, passes)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="GIF <-> IR display-layer (40x5) codec")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g2i = sub.add_parser("gif2ir", help="GIF -> IR display frames (patched into a base)")
    g2i.add_argument("-i", "--input", required=True, help="source animated GIF")
    g2i.add_argument("-b", "--base", required=True, help="complete base IR config JSON")
    g2i.add_argument("--slot", type=int, required=True, help="1, 2 or 3 (page 5/6/7)")
    g2i.add_argument("-o", "--output", required=True, help="output IR config JSON")
    g2i.add_argument("--resample", choices=("nearest", "lanczos", "box"),
                     default="nearest", help="downscale filter to 40x5 (default nearest)")
    g2i.add_argument("--speed-ms", type=int, dest="speed_ms",
                     help="override page speed_ms (default: from GIF, else base)")
    g2i.add_argument("--lightness", type=int, help="override page lightness 0-100")
    g2i.set_defaults(func=gif2ir)

    i2g = sub.add_parser("ir2gif", help="IR display frames -> GIF (visual confirmation)")
    i2g.add_argument("-i", "--input", required=True, help="IR config JSON")
    i2g.add_argument("--slot", type=int, required=True, help="1, 2 or 3 (page 5/6/7)")
    i2g.add_argument("-o", "--output", required=True, help="output animated GIF")
    i2g.add_argument("--scale", type=int, default=16, help="pixel scale-up (default 16)")
    i2g.add_argument("--speed-ms", type=int, dest="speed_ms",
                     help="override frame duration ms (default: page speed_ms)")
    i2g.add_argument("--recipe", help="recipe/prompt text to embed in GIF comment")
    i2g.set_defaults(func=ir2gif)

    rec = sub.add_parser("recipe", help="read/write a GIF's embedded recipe (comment)")
    rec.add_argument("input", help="GIF file")
    rec.add_argument("--set", help="set the recipe text (default: print it)")
    rec.set_defaults(func=recipe)

    ply = sub.add_parser("play", help="play a GIF or IR slot in the terminal (half-block ▀)")
    ply.add_argument("-i", "--input", required=True,
                     help="animated GIF, or IR config JSON (with --slot)")
    ply.add_argument("--slot", type=int,
                     help="treat input as an IR config and play this slot (1/2/3)")
    ply.add_argument("--scale", type=int, default=1,
                     help="repeat each pixel horizontally (default 1)")
    ply.add_argument("--fps", type=float,
                     help="frames per second (overrides --speed-ms / GIF duration)")
    ply.add_argument("--speed-ms", type=int, dest="speed_ms",
                     help="ms per frame (overrides the IR/GIF default)")
    ply.add_argument("--resample", choices=("nearest", "lanczos", "box"), default="nearest",
                     help="GIF downscale filter to 40x5 (default nearest)")
    loop_grp = ply.add_mutually_exclusive_group()
    loop_grp.add_argument("--once", action="store_true", help="play a single pass then stop")
    loop_grp.add_argument("--loop", type=int, metavar="N",
                          help="play N passes then stop (default: loop forever)")
    ply.set_defaults(func=play)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
