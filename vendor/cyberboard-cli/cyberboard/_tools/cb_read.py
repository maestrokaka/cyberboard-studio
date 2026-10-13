#!/usr/bin/env python3
"""Read the keymap back from the CyberBoard — the M2 read path.

The official app never uses the device's read commands (the `cmd_get_*`
builders in TransJsonCmd are dead code), but the R4 firmware honors them. In
particular [6,9] (get_key_msg) streams the entire key_layer matrix back as
4-byte keycodes, chunked 60 bytes per frame exactly like the [6,7] write.

Verified on hardware 2026-06-22: dumping after a full write round-trips
1400/1400 keycodes (7 layers x 200 keys) with zero mismatches — so this gives
automated write -> read -> diff verification for the keymap. (No LED-frame
read-back path is known; [6,15] get_flash returns only flash status metadata,
not frame data, so LED still needs a visual check.)

Usage:
  cb_read.py keymap [PORT]                 # print the keymap as keycodes
  cb_read.py keymap [PORT] --json          # emit a key_layer JSON fragment
  cb_read.py keymap [PORT] --compare CFG   # diff against a config's key_layer
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Final

import serial  # pyserial

from cb_device import BAUD, list_devices
from cb_protocol import build_frame, crc_ok

CMD_GET_KEY_MSG: Final = (6, 9)
KEYS_PER_LAYER: Final = 200  # 25 x 8 physical matrix
DEFAULT_LAYERS: Final = 7    # R4
CHUNK: Final = 60            # payload bytes per [6,9] frame


def _drain(port: str, command: tuple[int, int], *, timeout: float = 1.0) -> list[bytes]:
    ser = serial.Serial(port, baudrate=BAUD, timeout=timeout, write_timeout=2, exclusive=True)
    try:
        time.sleep(0.1)
        ser.reset_input_buffer()
        ser.write(build_frame(*command))
        ser.flush()
        frames: list[bytes] = []
        while True:
            chunk = ser.read(64)
            if not chunk:
                break
            frames.append(chunk)
        return frames
    finally:
        ser.close()


def read_keymap(port: str, *, layers: int = DEFAULT_LAYERS) -> list[list[str]]:
    """Return `layers` lists of KEYS_PER_LAYER `#MMPPUUUU` keycodes."""
    frames = sorted(_drain(port, CMD_GET_KEY_MSG), key=lambda f: f[2])
    if any(not crc_ok(f) for f in frames):
        raise ValueError("keymap read returned a frame with a bad CRC")
    blob = b"".join(f[3:63] for f in frames)
    codes = ["#%02X%02X%02X%02X" % tuple(blob[i : i + 4]) for i in range(0, len(blob), 4)]
    return [codes[i * KEYS_PER_LAYER : (i + 1) * KEYS_PER_LAYER] for i in range(layers)]


def _resolve_port(arg: str | None) -> str | None:
    if arg is not None:
        return arg
    boards = [d for d in list_devices() if d.is_cyberboard]
    return boards[0].port if boards else None


def _compare(read_layers: list[list[str]], config_path: str) -> int:
    config = json.load(open(config_path))
    written = [
        [c.upper() for c in layer["layer"]]
        for layer in config["key_layer"]["layer_data"]
    ]
    flat_read = [c for layer in read_layers for c in layer]
    flat_written = [c for layer in written for c in layer]
    n = min(len(flat_read), len(flat_written))
    mismatches = [(i, flat_read[i], flat_written[i]) for i in range(n) if flat_read[i] != flat_written[i]]
    print(f"compare {n} keycodes: matches={n - len(mismatches)}/{n}")
    for i, r, w in mismatches[:10]:
        print(f"  idx {i}: device {r} != config {w}")
    return 0 if not mismatches else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Read keymap from the CyberBoard.")
    ap.add_argument("what", choices=["keymap"], help="what to read")
    ap.add_argument("port", nargs="?", help="serial port (default: auto-detect)")
    ap.add_argument("--layers", type=int, default=DEFAULT_LAYERS)
    ap.add_argument("--json", action="store_true", help="emit a key_layer JSON fragment")
    ap.add_argument("--compare", metavar="CFG", help="diff against a config's key_layer")
    args = ap.parse_args()

    port = _resolve_port(args.port)
    if port is None:
        print("No CyberBoard found.", file=sys.stderr)
        return 1

    layers = read_keymap(port, layers=args.layers)

    if args.compare:
        return _compare(layers, args.compare)

    if args.json:
        fragment = {"valid": 1, "layer_num": len(layers), "layer_data": [{"layer": ly} for ly in layers]}
        print(json.dumps({"key_layer": fragment}, indent=2))
        return 0

    for li, layer in enumerate(layers):
        active = [(i, c) for i, c in enumerate(layer) if c != "#00000000"]
        print(f"layer {li}: {len(active)} mapped keys")
        print("   " + " ".join(c for _, c in active[:16]) + (" ..." if len(active) > 16 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
