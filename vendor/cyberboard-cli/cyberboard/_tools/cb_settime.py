#!/usr/bin/env python3
"""Set the CyberBoard's real-time clock — the safest first WRITE test.

Sends a single [1,3] cmd_set_time frame and checks the device ACK (reply
byte[2]==1). This writes only the RTC; it does NOT touch keymap or LED config,
so it's a low-risk way to prove the write path end-to-end before attempting a
full config write. See .claude/rules/30-write-protocol.md §3, §7.

Payload layout (from decompiled TransJsonCmd.cmd_set_time_send):
  [2:6] epoch seconds, big-endian   (sub-hour tz offset pre-added)
  [6]   tz sign: 0 = east(+), 1 = west(-), 2 = UTC
  [7]   tz whole hours, absolute

Usage: cb_settime.py [PORT]
"""
from __future__ import annotations

import sys
import time

import serial  # pyserial

from cb_device import BAUD, list_devices
from cb_protocol import build_frame, crc_ok

CMD_SET_TIME = (1, 3)


def time_payload() -> bytes:
    """Encode the current local time + timezone the way AM Master does."""
    is_dst = time.localtime().tm_isdst > 0
    tz_west_sec = time.altzone if is_dst else time.timezone  # seconds west of UTC
    hours = -tz_west_sec / 3600.0  # east-positive (JST = +9.0)
    sub_hour_sec = round((hours - int(hours)) * 3600)
    epoch = int(time.time()) + sub_hour_sec
    sign = 0 if hours > 0 else (1 if hours < 0 else 2)
    return epoch.to_bytes(4, "big", signed=True) + bytes([sign, abs(int(hours))])


def set_time(port: str, *, timeout: float = 2.0) -> tuple[bool, bytes]:
    """Send the RTC frame; returns (ack_ok, raw_reply)."""
    ser = serial.Serial(
        port, baudrate=BAUD, timeout=timeout, write_timeout=timeout, exclusive=True
    )
    try:
        time.sleep(0.1)
        ser.reset_input_buffer()
        frame = build_frame(*CMD_SET_TIME, time_payload())
        time.sleep(0.005)
        ser.write(frame)
        ser.flush()
        reply = ser.read(64)
        return (len(reply) >= 3 and reply[2] == 1), reply
    finally:
        ser.close()


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else None
    if port is None:
        boards = [d for d in list_devices() if d.is_cyberboard]
        if not boards:
            print("No CyberBoard found.", file=sys.stderr)
            return 1
        port = boards[0].port

    payload = time_payload()
    print(f"port: {port}")
    print(f"send [1,3] payload (epoch+tz): {payload.hex()}")
    ok, reply = set_time(port)
    crc = "ok" if crc_ok(reply) else "bad/none"
    print(f"reply ({len(reply)}B, crc {crc}): {reply.hex()}")
    print(f"ACK (byte[2]==1): {ok} -> {'SUCCESS' if ok else 'no ack / failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
