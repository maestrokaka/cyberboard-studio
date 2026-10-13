#!/usr/bin/env python3
"""get — show the keyboard's current config in the terminal (the readable dump).

Same hybrid gather as `dump` (a live keymap read off the device stitched onto the
stored LED state, each half labelled by provenance — see cb_dump / cb_store), but
rendered for human eyes instead of written as JSON: the keymap as a
keyboard-shaped grid per layer, the LED slots as frame counts. To pipe a
machine-readable IR to a file, use `dump`.

When the device is offline the keymap falls back to the stored copy (labelled
`stored@<ts>`); with neither a device nor a stored config there is nothing to
show and the command fails cleanly. LED that was never written reads as a clean
"(none stored)", not an error.

Pulls in pyserial via cb_dump (it probes the device); a dry/offline view still
works and just reports the stored copy.

Usage:
    cb_get.py [PORT]                 # layer 1 grid + LED slots + provenance
    cb_get.py [PORT] --layer N       # a specific layer
    cb_get.py [PORT] --all-layers    # every layer
"""
from __future__ import annotations

import argparse
import sys

import cb_dump
import cb_keymap
import cb_store

# slot (as the user names it) -> page_index in the IR
LED_SLOTS = {1: 5, 2: 6, 3: 7}


def _provenance_lines(prov: dict) -> list[str]:
    """Header: which keyboard, firmware version, and where each half came from."""
    version = f"  ({prov['version']})" if prov.get("version") else ""
    lines = [f"CyberBoard {prov['product_id']}{version}",
             f"  keymap: {prov['keymap']}    LED: {prov['led']}"]
    if prov["keymap"] != "live":
        lines.append("  (device offline — keymap is the stored copy, not a live read)")
    return lines


def _led_lines(ir: dict, led_prov: str) -> list[str]:
    """Per-slot display / per-key frame counts, or a clean note when unsaved."""
    if led_prov == "unknown":
        return ["LED slots: (none stored — write a config first)"]
    pages = {p.get("page_index"): p for p in ir.get("page_data", [])}
    rows = []
    for slot, page_index in LED_SLOTS.items():
        page = pages.get(page_index)
        if page is None:
            rows.append(f"  slot {slot} (page {page_index}): (absent)")
            continue
        disp = (page.get("frames") or {}).get("frame_num", 0)
        perkey = (page.get("keyframes") or {}).get("frame_num", 0)
        rows.append(f"  slot {slot} (page {page_index}): display={disp} frames, per-key={perkey} frames")
    return ["LED slots (frame counts):", *rows]


def _keymap_lines(ir: dict, targets: list[int] | None) -> list[str]:
    """Keyboard grids for the requested layers (`targets` 1-indexed; None = [1]).

    Each grid is `cb_keymap.render`, the same renderer `keymap show` uses, so a
    position decodes to the same short label here as there.
    """
    key_layer = ir.get("key_layer") or {}
    layers = [ld.get("layer") for ld in key_layer.get("layer_data", [])]
    if not layers:
        return ["keymap: (none)"]
    count = len(layers)
    want = targets if targets is not None else [1]

    lines: list[str] = []
    for layer_n in want:
        if not 1 <= layer_n <= count:
            lines.append(f"keymap layer {layer_n}: out of range (1..{count})")
            continue
        lines.append(f"keymap — layer {layer_n}/{count}:")
        lines.append(cb_keymap.render(layers[layer_n - 1]))
    if targets is None and count > 1:
        lines.append(f"({count} layers total — use --layer N or --all-layers)")
    return lines


def _targets(args, ir: dict) -> list[int] | None:
    """Resolve which layers to show from the flags (None = the default-one view)."""
    if args.all_layers:
        count = len((ir.get("key_layer") or {}).get("layer_data", []))
        return list(range(1, count + 1))
    if args.layer is not None:
        return [args.layer]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Show the device's current config (hybrid: live keymap + stored LED).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("port", nargs="?", help="serial port (default: auto-detect)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--layer", type=int, metavar="N", help="show only this layer (1-indexed)")
    group.add_argument("--all-layers", action="store_true", help="show every layer")
    args = ap.parse_args()

    device = cb_dump._resolve_device(args.port)
    if device is None and args.port is not None:
        print(f"get: no CyberBoard responded on {args.port}; showing the stored config.",
              file=sys.stderr)

    try:
        ir, prov = cb_dump.dump_ir(device, stored_pid=cb_store.sole_device())
    except (ValueError, OSError) as e:
        print(f"get: {e}", file=sys.stderr)
        return 1

    # Validate an explicit --layer against the actual count BEFORE printing, so
    # an invalid request fails non-zero (and prints nothing misleading) instead
    # of looking successful to a script.
    layer_count = len((ir.get("key_layer") or {}).get("layer_data", []))
    if args.layer is not None and not (1 <= args.layer <= layer_count):
        scope = f"1..{layer_count}" if layer_count else "this config has no keymap layers"
        print(f"get: --layer {args.layer} out of range ({scope}).", file=sys.stderr)
        return 1

    print("\n".join(_provenance_lines(prov)))
    print()
    print("\n".join(_keymap_lines(ir, _targets(args, ir))))
    print()
    print("\n".join(_led_lines(ir, prov["led"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
