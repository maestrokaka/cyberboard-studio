#!/usr/bin/env python3
"""diff — compare two configs (snapshot refs or files): keymap + LED frame counts.

Each argument is resolved independently as either a **file path** (an IR JSON on
disk) or a **store reference** against the sole stored device:

    current                 # the device's last-written full IR (current.json)
    2026-06-26T03-29-41Z    # a history snapshot stem (a leading prefix also works)

The comparison generalises cb_read's `--compare` (device-vs-config keymap diff)
to config-vs-config, and adds a per-slot LED frame-count diff. LED *pixels*
aren't compared — only frame counts — because the firmware can't read LED back,
so frame counts are the meaningful, reliably-stored signal.

Exit status mirrors a diff tool: 0 = identical, 1 = differences found (so it
composes in scripts), 2 = a usage/resolution error.

Pure stdlib (no pyserial / Pillow) — diffing two files needs no device.

Usage:
    cb_diff.py <a> <b> [--device CB04]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cb_store

# slot (as the user names it) -> page_index in the IR
LED_SLOTS = {1: 5, 2: 6, 3: 7}


def _resolve_ref(ref: str, pid: str | None) -> tuple[dict, str]:
    """Load the config `ref` points at and a short label. Raises ValueError.

    A real file path wins; otherwise `ref` is a store reference (`current` or a
    snapshot stem/prefix) resolved against device `pid`.
    """
    path = Path(ref)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), f"file:{ref}"

    if pid is None:
        raise ValueError(
            f"{ref!r} is not a file, and no single stored device was found to "
            "resolve it as a snapshot (use --device, or pass a file path)"
        )
    if ref == "current":
        current = cb_store.load_current(pid)
        if current is None:
            raise ValueError(f"no stored current.json for {pid}")
        return current, f"{pid}:current"

    matches = [s for s in cb_store.list_history(pid) if s.stem == ref or s.stem.startswith(ref)]
    if not matches:
        raise ValueError(f"{ref!r} is neither a file nor a snapshot of {pid}")
    if len(matches) > 1:
        raise ValueError(
            f"snapshot ref {ref!r} is ambiguous ({len(matches)} matches for {pid}); "
            "use a longer timestamp"
        )
    return json.loads(matches[0].read_text(encoding="utf-8")), f"{pid}:{matches[0].stem}"


def _keymap_layers(config: dict) -> list[list[str]] | None:
    """Upper-cased keycodes per layer, or None when the config has no key_layer."""
    key_layer = config.get("key_layer")
    if not key_layer:
        return None
    return [[c.upper() for c in layer.get("layer", [])]
            for layer in key_layer.get("layer_data", [])]


def keymap_diff(a: dict, b: dict) -> tuple[list[tuple[int, int, str | None, str | None]], str | None]:
    """Per-position keymap differences and an optional structural note.

    Returns (diffs, note). Each diff is (layer, index, old, new); a missing slot
    on one side reads as None. `note` flags a structural mismatch (one side has
    no key_layer) that the per-position list can't express.
    """
    la, lb = _keymap_layers(a), _keymap_layers(b)
    if la is None and lb is None:
        return [], "neither config has a keymap"
    if la is None or lb is None:
        side = "a" if la is None else "b"
        return [], f"only one side has a keymap (missing in {side})"

    diffs = [
        (li, ki, rowa[ki] if ki < len(rowa) else None, rowb[ki] if ki < len(rowb) else None)
        for li in range(max(len(la), len(lb)))
        for rowa, rowb in [(la[li] if li < len(la) else [], lb[li] if li < len(lb) else [])]
        for ki in range(max(len(rowa), len(rowb)))
        if (rowa[ki] if ki < len(rowa) else None) != (rowb[ki] if ki < len(rowb) else None)
    ]
    return diffs, None


def _slot_frame_counts(config: dict) -> dict[int, tuple[int | None, int | None]]:
    """page_index -> (display frame_num, per-key frame_num) for every page."""
    return {
        page.get("page_index"): (
            (page.get("frames") or {}).get("frame_num"),
            (page.get("keyframes") or {}).get("frame_num"),
        )
        for page in config.get("page_data", [])
    }


def led_diff(a: dict, b: dict) -> list[tuple[int, int, tuple, tuple]]:
    """Per-slot LED frame-count differences: (slot, page_index, counts_a, counts_b)."""
    fa, fb = _slot_frame_counts(a), _slot_frame_counts(b)
    return [
        (slot, page_index, fa.get(page_index), fb.get(page_index))
        for slot, page_index in LED_SLOTS.items()
        if fa.get(page_index) != fb.get(page_index)
    ]


def _counts_str(counts: tuple | None) -> str:
    if counts is None:
        return "(absent)"
    disp, perkey = counts
    return f"display={disp} per-key={perkey}"


def render_diff(a: dict, b: dict, label_a: str, label_b: str) -> tuple[str, bool]:
    """Human-readable diff report and whether any difference was found."""
    km, note = keymap_diff(a, b)
    led = led_diff(a, b)
    differs = bool(km) or bool(led) or note not in (None, "neither config has a keymap")

    lines = [f"diff: {label_a}  vs  {label_b}", ""]

    lines.append("keymap:")
    if note:
        lines.append(f"  {note}")
    if km:
        lines.append(f"  {len(km)} position(s) differ:")
        lines += [f"    layer {li + 1} idx {ki}: {old or '(none)'} -> {new or '(none)'}"
                  for li, ki, old, new in km]
    elif not note:
        lines.append("  no differences")

    lines += ["", "LED (frame counts):"]
    if led:
        lines += [f"  slot {slot} (page {pi}): {_counts_str(ca)} -> {_counts_str(cb)}"
                  for slot, pi, ca, cb in led]
    else:
        lines.append("  no frame-count differences")

    return "\n".join(lines), differs


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Diff two configs (snapshot refs or files): keymap + LED frame counts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("a", help="file path, 'current', or a snapshot timestamp")
    ap.add_argument("b", help="file path, 'current', or a snapshot timestamp")
    ap.add_argument("--device", metavar="PRODUCT_ID",
                    help="device whose snapshots to resolve refs against (default: sole stored)")
    args = ap.parse_args()

    pid = args.device or cb_store.sole_device()
    try:
        config_a, label_a = _resolve_ref(args.a, pid)
        config_b, label_b = _resolve_ref(args.b, pid)
    except (ValueError, OSError) as e:
        print(f"diff: {e}", file=sys.stderr)
        return 2

    report, differs = render_diff(config_a, config_b, label_a, label_b)
    print(report)
    return 1 if differs else 0


if __name__ == "__main__":
    sys.exit(main())
