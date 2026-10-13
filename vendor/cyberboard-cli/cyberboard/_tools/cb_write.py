#!/usr/bin/env python3
"""Write a full CyberBoard config (IR / official JSON) to the device.

This is the M1 milestone: take a known-good config — e.g. a merger
`outputs/*.json` the official app was able to write — encode it into the exact
ordered stream of 64-byte frames AM Master sends, and push it over USB CDC
serial with a JSON_START / … / JSON_END handshake.

Faithfully ported from the decompiled originals:
  - TransJsonCmd.py   — every frame's byte layout (the builders)
  - JsonToCmd.py      — chunking (rgb=11, key=5, layer=60) and ordering
  - KBSerialOption.send_r_series_all / json_down — the send sequence + the
    frame-count semantics (START is reset to 0, so JSON_END's total counts the
    DATA frames only — everything between START and END, exclusive).

Two decompiler artifacts were repaired against the clean HATSU analogs and the
clean builders: JsonToCmd's page_control / word_page inner loops (lost) and its
`keyframes is not None` guard (inverted). See .claude/rules/30-write-protocol.md.

SAFE BY DEFAULT: prints the frame plan and sends nothing unless --execute is
given. A full write overwrites keymap + LED, but is always recoverable via
AM Master (firmware is never touched).

Usage:
  cb_write.py CONFIG.json [PORT]              # dry-run: show the plan
  cb_write.py CONFIG.json [PORT] --execute    # actually write to the device
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from typing import Final

import serial  # pyserial

from cb_device import BAUD, probe
from cb_protocol import build_frame, crc_ok

# --- send order constants (KBSerialOption.send_r_series_all) ---------------
CMD_JSON_START: Final = (1, 5)
CMD_JSON_END: Final = (1, 6)
RGB_CHUNKS: Final = 11      # 600B display frame / 56 -> 10x56 + 40
KEY_CHUNKS: Final = 5       # 270B per-key frame / 56 -> 4x56 + 46
LAYER_CHUNK: Final = 60     # key_layer bytes per [6,7] frame
WORD_PER_FRAME: Final = 28  # unicode chars per [3,1] frame (28*2 = 56B)
PAGES_PER_CONTROL: Final = 4  # page_control entries per [2,2] frame
WRITE_DELAY: Final = 0.005  # GlobalInfo.com_write_delay
SETTLE_SECONDS: Final = 2.0  # flash-commit settle before the post-write probe (matches cb_set/cb_restore)
_PAYLOAD_MAX: Final = 61  # bytes [2:63]


# --- encoding helpers (TransJsonCmd top-of-file) --------------------------
def key_bytes(s: str) -> bytes:
    """`#MMPPUUUU` -> 4 bytes (key_to_bytes / rgba_to_bytes)."""
    return bytes.fromhex(s[1:9])


def rgb_bytes(s: str) -> bytes:
    """`#RRGGBB` -> 3 bytes (rgb_to_bytes)."""
    return bytes.fromhex(s[1:7])


def uni_bytes(s: str) -> bytes:
    """`#XXXX` -> 2 bytes (unicode_to_bytes)."""
    return bytes.fromhex(s[1:5])


def le16(n: int) -> bytes:
    """int_to_bytes(BE, signed) written low-byte-first on the wire."""
    be = int(n).to_bytes(2, "big", signed=True)
    return bytes([be[1], be[0]])


# --- per-section frame builders -------------------------------------------
def uncertainty_frames(pages: list[dict]) -> list[bytes]:
    """[2,1] one manifest frame: page count + per-page frame totals."""
    payload = bytearray([len(pages)])
    for pg in pages:
        payload += bytes([pg["page_index"], pg["word_page"].get("word_len", 0)])
        payload += le16(pg["frames"].get("frame_num", 0))
        payload += le16(pg["keyframes"].get("frame_num", 0))
    return [build_frame(2, 1, bytes(payload))]


def page_control_frames(pages: list[dict]) -> list[bytes]:
    """[2,2] page display settings, PAGES_PER_CONTROL pages per frame."""
    usb_count = math.ceil(len(pages) / PAGES_PER_CONTROL)

    def frame(idx: int) -> bytes:
        chunk = pages[idx * PAGES_PER_CONTROL : (idx + 1) * PAGES_PER_CONTROL]
        payload = bytearray([usb_count, idx, len(chunk)])
        for pg in chunk:
            color = pg["color"]
            payload += bytes([int(bool(pg["valid"])), pg["page_index"], pg["lightness"]])
            payload += le16(pg["speed_ms"])
            payload += bytes([int(bool(color["default"]))])
            payload += rgb_bytes(color["back_rgb"]) + rgb_bytes(color["rgb"])
        return build_frame(2, 2, bytes(payload))

    return [frame(i) for i in range(usb_count)]


def word_page_frames(pages: list[dict]) -> list[bytes]:
    """[3,1] text pages — only pages whose word_page has chars."""
    frames: list[bytes] = []
    for pg in pages:
        wp = pg["word_page"]
        chars = wp.get("unicode", [])
        if wp.get("word_len", 0) == 0:
            continue
        count = math.ceil(len(chars) / WORD_PER_FRAME)
        for i in range(count):
            sub = chars[i * WORD_PER_FRAME : (i + 1) * WORD_PER_FRAME]
            payload = bytes([i, pg["page_index"], int(bool(wp["valid"])), len(sub)])
            payload += b"".join(uni_bytes(c) for c in sub)
            frames.append(build_frame(3, 1, payload))
    return frames


def _rgb_all(frame_data: dict) -> bytes:
    return b"".join(rgb_bytes(c) for c in frame_data["frame_RGB"])


def rgb_frame_frames(pages: list[dict]) -> list[bytes]:
    """[4,page_index] 200px display frames: 600B -> 11 chunks of <=56B."""
    frames: list[bytes] = []
    for pg in pages:
        if pg["frames"].get("frame_num", 0) == 0:
            continue
        for fd in pg["frames"]["frame_data"]:
            blob = _rgb_all(fd)
            for i in range(RGB_CHUNKS):
                chunk = blob[i * 56 : (i + 1) * 56] if i < 10 else blob[10 * 56 : 600]
                payload = le16(fd["frame_index"]) + bytes([i]) + chunk
                frames.append(build_frame(4, pg["page_index"], payload))
    return frames


def key_frame_frames(pages: list[dict]) -> list[bytes]:
    """[5,page_index] 90 per-key frames: 270B -> 5 chunks of <=56B."""
    frames: list[bytes] = []
    for pg in pages:
        kf = pg["keyframes"]
        if kf is None or kf.get("frame_num", 0) == 0:
            continue
        for fd in kf["frame_data"]:
            blob = _rgb_all(fd)
            for i in range(KEY_CHUNKS):
                chunk = blob[i * 56 : (i + 1) * 56] if i < 4 else blob[4 * 56 : 270]
                payload = bytes([fd["frame_index"], i]) + chunk
                frames.append(build_frame(5, pg["page_index"], payload))
    return frames


def exchange_frames(config: dict) -> list[bytes]:
    """[6,1] one frame per exchange_key entry (input @4, output @24)."""
    num = config.get("exchange_num", 0)

    def frame(ek: dict) -> bytes:
        payload = bytearray(_PAYLOAD_MAX)
        payload[0] = num
        payload[1] = ek["exchange_index"]
        for i, k in enumerate(ek["input_key"]):
            payload[2 + i * 4 : 6 + i * 4] = key_bytes(k)
        for i, k in enumerate(ek["out_key"]):
            payload[22 + i * 4 : 26 + i * 4] = key_bytes(k)
        return build_frame(6, 1, bytes(payload))

    return [frame(ek) for ek in config.get("exchange_key", [])]


def swap_frames(config: dict) -> list[bytes]:
    """[6,6] swap keys, up to 11 per frame (9B each: index + in + out)."""
    swaps = config.get("swap_key", [])
    num = config.get("swap_key_num", len(swaps))
    usb_count = math.ceil(len(swaps) / 11) if swaps else 0

    def frame(idx: int) -> bytes:
        chunk = swaps[idx * 11 : (idx + 1) * 11]
        payload = bytearray([num, len(chunk)])
        for s in chunk:
            payload += bytes([s["swap_key_index"]]) + key_bytes(s["input_key"]) + key_bytes(s["out_key"])
        return build_frame(6, 6, bytes(payload))

    return [frame(i) for i in range(usb_count)]


def key_layer_frames(config: dict) -> list[bytes]:
    """[6,8] layer count, then [6,7] layer matrix in 60B chunks."""
    kl = config.get("key_layer")
    if kl is None or not kl.get("valid"):
        return []
    layer_num = kl["layer_num"]
    blob = b"".join(
        key_bytes(k) for layer in kl["layer_data"] for k in layer["layer"]
    )
    count = math.ceil(len(blob) / LAYER_CHUNK)
    control = build_frame(6, 8, bytes([layer_num]))
    chunks = [
        build_frame(6, 7, bytes([i]) + blob[i * LAYER_CHUNK : (i + 1) * LAYER_CHUNK])
        for i in range(count)
    ]
    return [control, *chunks]


@dataclass(frozen=True)
class FramePlan:
    sections: tuple[tuple[str, int], ...]
    frames: tuple[bytes, ...]

    @property
    def total(self) -> int:
        return len(self.frames)


def plan(config: dict) -> FramePlan:
    """Build the ordered data-frame stream (excludes START/END)."""
    pages = config["page_data"]
    sections = (
        ("uncertainty", uncertainty_frames(pages)),
        ("page_control", page_control_frames(pages)),
        ("word_page", word_page_frames(pages)),
        ("rgb_frame", rgb_frame_frames(pages)),
        ("key_frame", key_frame_frames(pages)),
        ("exchange", exchange_frames(config)),
        ("swap", swap_frames(config)),
        ("key_layer", key_layer_frames(config)),
    )
    frames = tuple(f for _, fs in sections for f in fs)
    return FramePlan(tuple((name, len(fs)) for name, fs in sections), frames)


def write_config(port: str, frames: tuple[bytes, ...], *, timeout: float = 10.0) -> tuple[bool, bytes]:
    """JSON_START -> all data frames (5ms apart) -> JSON_END(total). Returns (ack, end_reply)."""
    ser = serial.Serial(port, baudrate=BAUD, timeout=timeout, write_timeout=timeout, exclusive=True)
    try:
        time.sleep(0.1)
        ser.reset_input_buffer()

        ser.write(build_frame(*CMD_JSON_START))
        ser.flush()
        start_reply = ser.read(64)
        if not (len(start_reply) >= 3 and start_reply[2] == 1):
            return False, start_reply

        for frame in frames:
            time.sleep(WRITE_DELAY)
            ser.write(frame)
        ser.flush()

        end = build_frame(*CMD_JSON_END, len(frames).to_bytes(4, "big", signed=True))
        time.sleep(WRITE_DELAY)
        ser.write(end)
        ser.flush()

        reply = ser.read(64)
        # rev[2]==2 means "wait, flashing" — poll a bounded number of times.
        for _ in range(15):
            if len(reply) >= 3 and reply[2] == 1:
                return True, reply
            if not (len(reply) >= 3 and reply[2] == 2):
                break
            time.sleep(1.0)
            reply = ser.read(64)
        return (len(reply) >= 3 and reply[2] == 1), reply
    finally:
        ser.close()


def _record_write(product_id: str, config: dict, version: str | None) -> None:
    """Persist the just-written full IR to the state store (snapshot + current).

    `cyberboard write --execute` is the natural source of truth for `current.json`:
    LED frames can't be read back, so the last full IR we wrote is the only record
    of the device's LED state — without this, `dump`'s LED=last-written hybrid never
    works in a normal workflow (a dump right after a write would report LED=unknown).

    The device write already succeeded (and is irreversible) by the time we get here,
    so a store failure must NEVER mask it or change the exit code — every store-side
    error degrades to a warning. Each catch is deliberately broad (not just `OSError`):
    after the ACK, the store can still raise `ValueError` (e.g. an invalid
    `CYBERBOARD_HISTORY_MAX`) or `TypeError` (a non-serializable IR), and tracebacking
    past a successful destructive write would be the worst outcome. `current.json` (the
    LED source of truth) is saved in its OWN block, attempted FIRST and independent of
    the history snapshot — a snapshot-retention failure must not leave current stale.
    The two are separate sequential locked steps anyway — never nested (cb_store's flock
    is per-fd; nesting would self-deadlock). `_provenance` (added by `dump`) is stripped
    so `current.json` stays a clean full IR.
    """
    import cb_store

    ir = {k: v for k, v in config.items() if k != "_provenance"}
    try:
        cb_store.save_current(product_id, ir, version=version)
        print("state store: current.json updated")
    except Exception as e:  # noqa: BLE001 — post-successful-write, must not traceback
        print(f"warning: wrote the device but could not update current.json ({e}); "
              "it may be stale.", file=sys.stderr)
    try:
        snap = cb_store.snapshot(product_id, ir)
        print(f"state store: history snapshot {snap.stem}")
    except Exception as e:  # noqa: BLE001 — history is best-effort; current already saved
        print(f"warning: wrote the device but could not write a history snapshot ({e}).",
              file=sys.stderr)


def _keymap_verified(port: str, config: dict) -> bool:
    """Whether the device's [6,9] keymap read-back matches the config we wrote.

    An ACK doesn't prove the config landed (rule 30 §5a: ACK != correctness), so before
    recording current.json we confirm via the one half the firmware can read back — the
    keymap (LED frames can't be read back). Returns True when the read-back matches, or
    when there's no keymap to compare (an LED-only config — trust the ACK as we must for
    LED). Returns False (after a specific warning) on a mismatch or if the read-back
    itself fails, so the caller skips recording rather than store a config the device
    does not actually have.
    """
    import cb_read

    want = [[c.upper() for c in (layer.get("layer") or [])]
            for layer in ((config.get("key_layer") or {}).get("layer_data") or [])]
    if not want:
        return True  # nothing readable to verify (LED-only) — trust the ACK
    try:
        got = [[c.upper() for c in layer] for layer in cb_read.read_keymap(port)]
    except (ValueError, OSError) as e:
        print(f"warning: keymap read-back failed ({e}); not recording current.", file=sys.stderr)
        return False
    if got != want:
        print("warning: post-write keymap read-back didn't match the config; "
              "not recording current.", file=sys.stderr)
        return False
    return True


def _resolve_port(arg: str | None) -> str | None:
    if arg is not None:
        return arg
    board = probe_first()
    return board.port if board else None


def probe_first():
    from cb_device import list_devices

    boards = [d for d in list_devices(full=False) if d.is_cyberboard]
    return boards[0] if boards else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Write a full CyberBoard config over USB serial.")
    ap.add_argument("config", help="path to the config JSON (IR / official format)")
    ap.add_argument("port", nargs="?", help="serial port (default: auto-detect)")
    ap.add_argument("--execute", action="store_true", help="actually write (default: dry-run)")
    args = ap.parse_args()

    config = json.load(open(args.config))
    fp = plan(config)

    print(f"config: {args.config}")
    print(f"frame plan ({fp.total} data frames; JSON_END total = {fp.total}):")
    for name, count in fp.sections:
        print(f"  {name:16} {count:>5}")
    bad = [i for i, f in enumerate(fp.frames) if not (len(f) == 64 and crc_ok(f))]
    print(f"  {'all 64B + CRC ok':16} {'yes' if not bad else f'NO ({len(bad)} bad)'}")

    if not args.execute:
        print("\n(dry-run — nothing sent. re-run with --execute to write.)")
        return 0 if not bad else 1

    if bad:
        print("refusing to write: malformed frames present.", file=sys.stderr)
        return 1

    port = _resolve_port(args.port)
    if port is None:
        print("No CyberBoard found.", file=sys.stderr)
        return 1

    before = probe(port, full=True)
    print(f"\nport: {port}")
    print(f"before: {before.product_id if before else '?'} / {before.version if before else '?'}")
    print(f"writing {fp.total} frames (~{fp.total * WRITE_DELAY:.0f}s minimum)...")

    ok, reply = write_config(port, fp.frames)
    crc = "ok" if crc_ok(reply) else "bad/none"
    print(f"JSON_END reply ({len(reply)}B, crc {crc}): {reply.hex()}")
    print(f"ACK (byte[2]==1): {ok} -> {'SUCCESS' if ok else 'FAILED'}")

    # The device can still be committing flash right after the ACK, so wait the same
    # settle as cb_set/cb_restore before probing: a too-early probe could miss `after`
    # and wrongly skip the current.json/snapshot record for a write that did succeed.
    time.sleep(SETTLE_SECONDS)
    after = probe(port, full=True)
    print(f"after:  {after.product_id if after else 'NO RESPONSE'} / {after.version if after else '?'}")
    success = bool(ok and after and after.is_cyberboard)
    # Persist only a confirmed write to the *same* board. A non-ACK or a non-CyberBoard
    # afterward means current.json would be a lie; and if the board probed after differs
    # from the one probed before (serial node reused / board swapped between ACK and
    # probe), recording under after.product_id would mismark a different board's config.
    swapped = bool(before and after and before.product_id != after.product_id)
    if success and swapped:
        print("warning: board changed between the before/after probe; not recording current.",
              file=sys.stderr)
    # An ACK doesn't prove the config landed (rule 30 §5a: ACK != correctness). The keymap
    # half is read-back-able, so confirm it matches before recording — exactly what
    # cb_set/_finish does — to avoid storing a config the device doesn't actually have
    # (which would poison dump/history/restore). _keymap_verified warns on mismatch.
    elif success and _keymap_verified(port, config):
        _record_write(after.product_id, config, after.version)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
