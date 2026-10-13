#!/usr/bin/env python3
"""dump — pull the device's current config into one provenance-labelled IR file.

The two halves of a CyberBoard config have asymmetric readability (see
cb_store): the keymap can be read straight off the device ([6,9] get_key_msg),
but the LED display / per-key frames cannot be read back at all — the only
record of them is the last full IR we wrote, kept locally in the store. So a
faithful dump is a *hybrid*: a live keymap stitched onto the stored LED state,
with each half labelled by where it came from so the result is never mistaken
for a clean live readout.

Provenance is emitted both as a `_provenance` block inside the IR (so the file
is self-describing) and as a one-line summary on stderr:

    keymap : live | stored@<ts> | unknown
    led    : last-written@<ts> | unknown

When the device is offline the keymap falls back to the stored copy (clearly
labelled `stored@<ts>`); with neither a device nor a stored config there is
nothing to dump and the command fails cleanly.

Usage:
    cb_dump.py [PORT] [-o FILE]      # -o omitted => stdout
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cb_store
from cb_device import DeviceInfo, list_devices, probe
from cb_read import DEFAULT_LAYERS, KEYS_PER_LAYER, read_keymap


def _require_full_keymap(layers: list[list[str]]) -> None:
    """Reject a truncated live read before it can overwrite stored data.

    A timed-out / partial [6,9] stream makes read_keymap slice whatever frames
    arrived into short or empty layers. Labelling that `live` and emitting it
    is dangerous: written back later it would erase the real keymap. So a dump
    must capture the full 7x200 matrix or fail loudly (the caller turns this
    into a clean error + exit 1, prompting a retry) — never a silent partial.
    """
    bad = [i for i, layer in enumerate(layers) if len(layer) != KEYS_PER_LAYER]
    if len(layers) != DEFAULT_LAYERS or bad:
        raise ValueError(
            f"live keymap read is incomplete (got {len(layers)} layers; "
            f"expected {DEFAULT_LAYERS}x{KEYS_PER_LAYER}) — the [6,9] stream was "
            "likely truncated. Re-run dump; nothing was changed."
        )


def _keymap_fragment(layers: list[list[str]]) -> dict:
    """Wrap read-back layers in the key_layer shape the IR / schema expect."""
    return {
        "valid": 1,
        "layer_num": len(layers),
        "layer_data": [{"layer": layer} for layer in layers],
    }


def _resolve_device(port: str | None) -> DeviceInfo | None:
    """The target device: the named port, else the first auto-detected board.

    An explicit port is filtered by `is_cyberboard` just like auto-detect — a
    dongle or other serial responder answers `probe()` with a DeviceInfo whose
    flag is False, and sending [6,9] to it would yield garbage layers we'd
    mislabel as a live keymap. Reject it so dump falls back to the stored copy.
    """
    if port is not None:
        device = probe(port, full=True)
        return device if device is not None and device.is_cyberboard else None
    boards = [d for d in list_devices(full=True) if d.is_cyberboard]
    return boards[0] if boards else None


def _file_ts(path: Path) -> str:
    """ISO8601 (UTC, second precision) of a file's last-modified time."""
    stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return stamp.isoformat(timespec="seconds")


# Sole-device resolution lives in cb_store (shared with `diff`); aliased here so
# the call site reads in dump's own vocabulary.
_stored_product_id = cb_store.sole_device


def dump_ir(device: DeviceInfo | None, *, stored_pid: str | None) -> tuple[dict, dict]:
    """Compose the hybrid IR and its provenance block.

    Raises ValueError with a user-facing message when there is nothing to dump.
    """
    product_id = device.product_id if device is not None else stored_pid
    if not product_id:
        raise ValueError(
            "no device connected and no stored config found — nothing to dump.\n"
            "  connect the R4 by wire, or run a write first to populate the store."
        )

    current = cb_store.load_current(product_id)
    cur_ts = _file_ts(cb_store.current_path(product_id)) if current is not None else None

    # --- keymap half: live read off the device, else the stored copy ---
    if device is not None:
        layers = read_keymap(device.port)
        _require_full_keymap(layers)
        keymap = _keymap_fragment(layers)
        keymap_prov = "live"
        version = device.version
        cb_store.record_seen(product_id, version=version)
    elif current is not None and "key_layer" in current:
        keymap = current["key_layer"]
        keymap_prov = f"stored@{cur_ts}"
        version = (cb_store.load_meta(product_id) or {}).get("version")
    else:
        keymap = None
        keymap_prov = "unknown"
        version = (cb_store.load_meta(product_id) or {}).get("version")

    # --- LED / body half: only the last full IR we wrote knows it ---
    if current is not None:
        ir = copy.deepcopy(current)
        ir.pop("_provenance", None)  # never nest a prior dump's provenance
        led_prov = f"last-written@{cur_ts}"
    else:
        ir = {}
        led_prov = "unknown"

    if keymap is not None:
        ir["key_layer"] = keymap

    if not ir:
        raise ValueError(
            f"nothing to dump for {product_id}: device not connected and no stored config.\n"
            "  connect the R4 by wire, or run a write first to populate the store."
        )

    prov = {
        "keymap": keymap_prov,
        "led": led_prov,
        "product_id": product_id,
        "version": version,
        "dumped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return {"_provenance": prov, **ir}, prov


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Dump the device's current config (hybrid: live keymap + stored LED).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("port", nargs="?", help="serial port (default: auto-detect)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write IR to FILE (default: stdout)")
    args = ap.parse_args()

    device = _resolve_device(args.port)
    if device is None and args.port is not None:
        print(f"dump: no CyberBoard responded on {args.port}; trying the stored config.",
              file=sys.stderr)

    try:
        out, prov = dump_ir(device, stored_pid=_stored_product_id())
    except (ValueError, OSError) as e:
        # OSError covers store stat/read failures (e.g. _file_ts on a vanished
        # current.json) — surface them in the same clean dump: style, not a traceback.
        print(f"dump: {e}", file=sys.stderr)
        return 1

    if prov["keymap"] != "live":
        print("dump: device not connected — keymap is the stored copy, not a live read.",
              file=sys.stderr)
    print(f"dump: keymap={prov['keymap']}, LED={prov['led']}, product_id={prov['product_id']}",
          file=sys.stderr)

    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        try:
            Path(args.output).write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"dump: {e}", file=sys.stderr)
            return 1
        print(f"dump: wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
