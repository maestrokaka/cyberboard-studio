#!/usr/bin/env python3
"""history — list a device's saved snapshots so you can pick a restore/diff ref.

Lists `devices/<product_id>/history/` newest-first, with `current` shown first
(the last full IR written, marked `*`). Each row prints the **ref** you pass to
`diff` / `restore` (the snapshot stem, or the literal `current`), its size, and
its provenance when the stored IR carries a `_provenance` block (e.g. a config
captured via `dump`). Pure stdlib — no device needed.

Usage:
    cb_history.py [--device CB04]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cb_store


def _human_size(num_bytes: int) -> str:
    """A compact human-readable size (B / KB / MB)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} MB"


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def _provenance(path: Path) -> str:
    """A one-line provenance summary if the stored IR has a `_provenance` block."""
    try:
        prov = (json.loads(path.read_text(encoding="utf-8")) or {}).get("_provenance")
    except (OSError, ValueError):
        return ""
    if not isinstance(prov, dict):
        return ""
    parts = [f"{k}={prov[k]}" for k in ("keymap", "led") if prov.get(k)]
    return ", ".join(parts)


def _row(ref: str, path: Path, ref_width: int, *, mark: str = " ", note: str = "") -> str:
    parts = [f"{mark} {ref.ljust(ref_width)}", f"{_human_size(path.stat().st_size):>9}"]
    if note:
        parts.append(note)
    prov = _provenance(path)
    if prov:
        parts.append(f"[{prov}]")
    return "  ".join(parts)


def render_history(product_id: str) -> str:
    """The full listing for one device (current + snapshots, newest first)."""
    current = cb_store.current_path(product_id)
    snapshots = cb_store.list_history(product_id)  # newest first

    has_current = current.exists()
    if not has_current and not snapshots:
        return f"device {product_id}: no history yet (nothing has been written)."

    refs = (["current"] if has_current else []) + [s.stem for s in snapshots]
    ref_width = max(len(r) for r in refs)

    header = (f"device {product_id} — {len(snapshots)} snapshot(s)"
              + (" + current" if has_current else ""))
    lines = [header, ""]
    if has_current:
        lines.append(_row("current", current, ref_width, mark="*",
                          note=f"written {_mtime_iso(current)}"))
    lines += [_row(s.stem, s, ref_width) for s in snapshots]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="List saved snapshots (newest first) for a device.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--device", metavar="PRODUCT_ID",
                    help="device to list (default: the sole stored device)")
    args = ap.parse_args()

    product_id = args.device or cb_store.sole_device()
    if product_id is None:
        print("history: no stored device found "
              "(connect+write a config first, or pass --device).", file=sys.stderr)
        return 1

    print(render_history(product_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
