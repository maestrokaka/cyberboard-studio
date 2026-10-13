"""Wire-protocol primitives for the AngryMiao CyberBoard (USB CDC serial).

The reusable core every cbctl command builds on: a 64-byte frame whose last
byte is a CRC-8 (poly 0x07) over the first 63. Verified against real R4
hardware on 2026-06-22 — the device accepted our frames and its replies carry
a matching CRC-8. See .claude/rules/30-write-protocol.md.

Pure stdlib; no serial I/O here so it stays trivially testable and liftable
into the eventual CLI package.
"""
from __future__ import annotations

from typing import Final

FRAME_SIZE: Final = 64
_CRC_PAYLOAD: Final = 63  # bytes [0:63]; CRC lands in [63]
_MAX_PAYLOAD: Final = 61  # bytes [2:63]


def crc8(data: bytes) -> int:
    """CRC-8 / poly 0x07, init 0x00, no reflection (== PyPI `crc8` default)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def build_frame(category: int, subcommand: int, payload: bytes = b"") -> bytes:
    """A 64-byte command frame: [0]=category, [1]=subcommand, [2:]=payload, [63]=CRC-8."""
    if len(payload) > _MAX_PAYLOAD:
        raise ValueError(f"payload exceeds {_MAX_PAYLOAD} bytes: {len(payload)}")
    cmd = bytearray(FRAME_SIZE)
    cmd[0] = category
    cmd[1] = subcommand
    cmd[2 : 2 + len(payload)] = payload
    cmd[_CRC_PAYLOAD] = crc8(bytes(cmd[:_CRC_PAYLOAD]))
    return bytes(cmd)


def crc_ok(frame: bytes) -> bool:
    """True iff `frame` is 64 bytes with a valid trailing CRC-8."""
    return len(frame) == FRAME_SIZE and crc8(bytes(frame[:_CRC_PAYLOAD])) == frame[_CRC_PAYLOAD]


def parse_string_reply(frame: bytes) -> str | None:
    """Decode a `[2]=length, [3:3+length]=ascii` reply (product_id / version).

    Returns None when the frame is too short or the length byte is implausible.
    """
    if len(frame) < 3:
        return None
    length = frame[2]
    if not 0 < length <= _MAX_PAYLOAD:
        return None
    # The reported length can include a trailing NUL terminator (e.g. the
    # version string); strip it so callers get the clean text.
    return frame[3 : 3 + length].decode("ascii", "replace").rstrip("\x00")
