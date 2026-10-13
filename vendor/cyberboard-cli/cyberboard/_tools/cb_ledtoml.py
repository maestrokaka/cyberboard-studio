#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Compose a `led.toml` manifest (multi-source LED slots) into a complete IR.

    cyberboard compose -m led.toml [-b base.json] -o config.json
    cb_ledtoml.py     -m led.toml [-b base.json] -o config.json   (standalone)

A *manifest* declares, per slot (1/2/3 = page 5/6/7), a `sources` list whose
frames are concatenated in order. That single list subsumes miaomerge's
keep / replace / combine actions (merge_configurations.rs):

  * omit a slot          -> keep   (untouched in the base)
  * one source           -> replace (that slot's display frames)
  * many sources         -> combine (concatenated, frame_index renumbered)

Each source is exactly one of:

  * gif    = "art.gif"              (downsampled to 40x5, like led gif2ir)
  * config = "other.json"          (a slot's display frames from another IR;
             slot = 2              optional `slot`, default = the outer index)
  * recipe = "scroll.json"         (a cb_anim recipe, expanded to frames)

Only the display layer (`frames`, 200px) is composed; per-key `keyframes` ride
unchanged from the base (the gif2ir invariant) — the base must be a complete
IR. Output is a complete IR ready for `cyberboard write` / `verify`.

The firmware plays at most MAX_FRAMES/slot, so a combine that overflows the cap
is truncated from the tail — and reported *per source* (which source was kept
in full, truncated, or dropped) so the cut is never silent (project rule).
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

import cb_anim  # shared: EFFECTS (effect registry)
import cb_led  # shared: frames_to_page, _gif_frames, _page, _slot_to_page, MAX_FRAMES

MAX_FRAMES = cb_led.MAX_FRAMES
SRC_KINDS = ("gif", "config", "recipe")
RESAMPLE = ("nearest", "lanczos", "box")


def _warn(msg: str) -> None:
    print(f"cb_ledtoml: {msg}", file=sys.stderr)


def _resolve(path_str: str, base_dir: Path) -> Path:
    """Resolve a manifest-relative path (absolute paths pass through)."""
    p = Path(path_str)
    return p if p.is_absolute() else base_dir / p


def _recipe_frames(recipe: dict) -> list[list[str]]:
    """Expand a cb_anim recipe to raw frames (no cap — the compose layer owns
    the single MAX_FRAMES cap, so `_render_recipe`'s own cap/warning is bypassed
    to keep the per-source accounting the one clear signal). Reuses cb_anim's
    effect registry, so the effect set stays in lockstep with `anim`."""
    segments = recipe.get("sequence") or [recipe]  # single-effect convenience
    frames: list[list[str]] = []
    for k, seg in enumerate(segments):
        fn = cb_anim.EFFECTS.get(seg.get("effect"))
        if fn is None:
            raise SystemExit(f"cb_ledtoml: recipe segment {k} has unknown effect "
                             f"{seg.get('effect')!r} (have: {', '.join(sorted(cb_anim.EFFECTS))})")
        frames.extend(fn(seg))
    return frames


def _source_frames(src: dict, outer_slot: int, resample: str,
                   base_dir: Path) -> tuple[str, list[list[str]], int | None]:
    """Return (label, frames, gif_ms) for one source. `gif_ms` is the GIF's
    first-frame duration (a speed fallback) for gif sources, else None."""
    kinds = [k for k in SRC_KINDS if k in src]
    if len(kinds) != 1:
        raise SystemExit(f"cb_ledtoml: each source needs exactly one of {SRC_KINDS} "
                         f"(got {kinds or 'none'})")
    kind = kinds[0]
    path = _resolve(src[kind], base_dir)
    if not path.exists():
        raise SystemExit(f"cb_ledtoml: {kind} source not found: {path}")
    if kind == "gif":
        frames, gif_ms = cb_led._gif_frames(path, resample)
        return f"gif:{path.name}", frames, gif_ms
    if kind == "config":
        src_slot = src.get("slot", outer_slot)
        if src_slot not in (1, 2, 3):
            raise SystemExit(f"cb_ledtoml: config source slot must be 1, 2 or 3 "
                             f"(got {src_slot!r})")
        cfg = json.loads(path.read_text())
        page_index = cb_led._slot_to_page(src_slot)  # validated above -> won't raise
        page = next((p for p in cfg.get("page_data", [])
                     if p.get("page_index") == page_index), None)
        if page is None:
            raise SystemExit(f"cb_ledtoml: config {path.name} has no slot {src_slot} "
                             f"(page_index {page_index})")
        fd = page.get("frames", {}).get("frame_data", [])
        if not fd:
            raise SystemExit(f"cb_ledtoml: config {path.name} slot {src_slot} "
                             f"has no display frames")
        return f"config:{path.name}#slot{src_slot}", [fr["frame_RGB"] for fr in fd], None
    rec = json.loads(path.read_text())
    return f"recipe:{path.name}", _recipe_frames(rec), None


def _cap_plan(counts: list[int]) -> tuple[list[int], int]:
    """Given per-source raw frame counts, return (kept_per_source, dropped_total)
    after the MAX_FRAMES cap is applied to the concatenation (tail-drop). Pure."""
    kept: list[int] = []
    used = 0
    for c in counts:
        k = min(c, max(0, MAX_FRAMES - used))
        kept.append(k)
        used += k
    return kept, sum(counts) - used


def _compose_slot(slot: dict, base: dict, base_dir: Path) -> tuple[int, dict]:
    """Compose one [[slot]] into the base; returns (slot_index, patched page)."""
    index = slot.get("index")
    if index not in (1, 2, 3):  # catches both missing (None) and out-of-range
        raise SystemExit(f"cb_ledtoml: each [[slot]] needs an index of 1, 2 or 3 "
                         f"(got {index!r})")
    resample = slot.get("resample", "nearest")
    if resample not in RESAMPLE:
        raise SystemExit(f"cb_ledtoml: slot {index} resample must be one of {RESAMPLE} "
                         f"(got {resample!r})")
    sources = slot.get("sources") or []
    if not isinstance(sources, list) or not all(isinstance(s, dict) for s in sources):
        raise SystemExit(f"cb_ledtoml: slot {index} sources must be a list of tables "
                         f'(e.g. sources = [ {{ recipe = "scroll.json" }} ])')
    if not sources:
        raise SystemExit(f"cb_ledtoml: slot {index} has no sources "
                         f"(omit the [[slot]] entirely to keep the base unchanged)")

    extracted = [_source_frames(s, index, resample, base_dir) for s in sources]
    counts = [len(frs) for _, frs, _ in extracted]
    kept, dropped = _cap_plan(counts)
    frames = [fr for (_, frs, _), k in zip(extracted, kept, strict=True) for fr in frs[:k]]

    speed = slot.get("speed_ms")
    if speed is None:  # fall back to the first GIF's duration, else base keeps its own
        speed = next((ms for _, _, ms in extracted if ms is not None), None)
    page = cb_led.frames_to_page(base, index, frames, speed, slot.get("lightness"))

    _report_slot(index, page, extracted, kept, dropped, speed)
    return index, page


def _report_slot(index: int, page: dict, extracted, kept: list[int],
                 dropped: int, speed: int | None) -> None:
    """Print the per-source frame accounting (silent cap 禁止)."""
    note = f", speed_ms={speed}" if speed is not None else ""
    print(f"cb_ledtoml: slot {index} (page {page['page_index']}) <- "
          f"{page['frames']['frame_num']} frames from {len(extracted)} source(s)"
          f"{note}; keyframes kept from base")
    for (label, frs, _), k in zip(extracted, kept, strict=True):
        if k == len(frs):
            print(f"    {label}: {len(frs)}")
        elif k == 0:
            print(f"    {label}: {len(frs)} -> DROPPED (past {MAX_FRAMES} cap)")
        else:
            print(f"    {label}: {len(frs)} -> truncated to {k} ({len(frs) - k} over cap)")
    if dropped:
        _warn(f"slot {index}: combined frames exceed {MAX_FRAMES}/slot — "
              f"dropped {dropped} from the tail (firmware plays only {MAX_FRAMES})")


def compose(args: argparse.Namespace) -> int:
    with open(args.manifest, "rb") as f:
        manifest = tomllib.load(f)
    base_dir = Path(args.manifest).resolve().parent

    base_path = args.base or manifest.get("meta", {}).get("base")
    if not base_path:
        raise SystemExit("cb_ledtoml: no base IR — set [meta].base in the manifest "
                         "or pass -b (LED has no read-back, so a complete base is required)")
    base = json.loads(_resolve(base_path, base_dir).read_text())

    slots = manifest.get("slot")
    if not slots:
        raise SystemExit("cb_ledtoml: manifest has no [[slot]] entries")
    if not isinstance(slots, list) or not all(isinstance(s, dict) for s in slots):
        raise SystemExit("cb_ledtoml: [[slot]] must be an array of tables — "
                         "write [[slot]] once per slot, not a single [slot]")
    raw_indices = [s.get("index") for s in slots]
    dups = sorted({i for i in raw_indices if i in (1, 2, 3) and raw_indices.count(i) > 1})
    if dups:
        raise SystemExit(f"cb_ledtoml: duplicate [[slot]] index {dups} — "
                         f"each slot (1/2/3) may appear at most once")

    composed = [_compose_slot(slot, base, base_dir) for slot in slots]
    Path(args.output).write_text(json.dumps(base, ensure_ascii=False, indent=2))
    print(f"cb_ledtoml: composed {len(composed)} slot(s) "
          f"({', '.join(str(i) for i, _ in composed)}) -> {args.output}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compose a led.toml manifest (multi-source slots) into a complete IR")
    ap.add_argument("-m", "--manifest", required=True, help="led.toml manifest")
    ap.add_argument("-b", "--base", help="complete base IR config JSON (overrides [meta].base)")
    ap.add_argument("-o", "--output", required=True, help="output IR config JSON")
    return compose(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
