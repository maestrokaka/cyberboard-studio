#!/usr/bin/env python3
"""Discover and describe connected CyberBoard devices over USB CDC serial.

READ-ONLY: sends only identity/status queries ([1,1] product_id, [1,2]
product_info, [2,6] check_pages) and never modifies keyboard config. This is
the foundation for the future `cbctl devices` / `cbctl device info` commands,
and the robust answer to AM Master's flaky detection: instead of trusting a
device-node name or a hardcoded VID/PID, open each candidate serial port and
ask it who it is — only a device that returns a CRC-valid CyberBoard reply
counts (a co-resident LG monitor exposes its own cu.usbmodem* port, hence the
need to verify by reply, not by name).

Usage:
    cb_device.py list [--json] [--all]
    cb_device.py info [PORT] [--json]

Requires pyserial (see tools/requirements.txt).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from dataclasses import asdict, dataclass

import serial  # pyserial
from serial.tools import list_ports

from cb_protocol import build_frame, crc_ok, parse_string_reply

BAUD = 9600
CMD_PRODUCT_ID = (1, 1)
CMD_PRODUCT_INFO = (1, 2)
CMD_CHECK_PAGES = (2, 6)
PORT_GLOB = "/dev/cu.usbmodem*"


@dataclass(frozen=True)
class DeviceInfo:
    port: str
    product_id: str | None
    version: str | None
    pages: int | None
    is_cyberboard: bool
    is_dongle: bool


def candidate_ports() -> list[str]:
    """Enumerate Windows COM ports or preserve macOS callout discovery.

    Windows USB devices provide COM handles, not /dev nodes. A port only counts
    as a board after the existing CRC-valid identity handshake; no VID/PID or
    COM-number guess replaces that verification.
    """
    if sys.platform == "win32":
        return [port.device for port in sorted(list_ports.comports())]
    return sorted(glob.glob(PORT_GLOB))


def _query(ser: serial.Serial, command: tuple[int, int]) -> bytes:
    ser.reset_input_buffer()
    time.sleep(0.005)  # mirror AM Master's inter-frame delay
    ser.write(build_frame(*command))
    ser.flush()
    return ser.read(64)


def probe(port: str, *, full: bool = False, timeout: float = 1.5) -> DeviceInfo | None:
    """Identify the device on `port`. Returns None if it isn't a CyberBoard.

    `full=True` additionally fetches firmware version and page count.
    """
    try:
        ser = serial.Serial(
            port, baudrate=BAUD, timeout=timeout, write_timeout=timeout, exclusive=True
        )
    except (serial.SerialException, OSError):
        return None
    try:
        time.sleep(0.1)
        reply = _query(ser, CMD_PRODUCT_ID)
        if not crc_ok(reply):
            return None
        product_id = parse_string_reply(reply)
        if product_id is None:
            return None
        upper = product_id.upper()
        is_dongle = "DONGLE" in upper
        is_cyberboard = (upper.startswith("CB") or upper == "AM01R6") and not is_dongle
        version: str | None = None
        pages: int | None = None
        if full and is_cyberboard:
            info = _query(ser, CMD_PRODUCT_INFO)
            version = parse_string_reply(info) if crc_ok(info) else None
            checked = _query(ser, CMD_CHECK_PAGES)
            pages = checked[2] if crc_ok(checked) else None
        return DeviceInfo(port, product_id, version, pages, is_cyberboard, is_dongle)
    finally:
        ser.close()


def list_devices(*, full: bool = False) -> list[DeviceInfo]:
    return [info for port in candidate_ports() if (info := probe(port, full=full)) is not None]


def _resolve_target(port: str | None) -> DeviceInfo | None:
    if port is not None:
        return probe(port, full=True)
    boards = [d for d in list_devices(full=True) if d.is_cyberboard]
    return boards[0] if boards else None


def _print_table(devices: list[DeviceInfo]) -> None:
    if not devices:
        print("No CyberBoard found. Connect the R4 by wire (not the dongle).")
        return
    for d in devices:
        kind = "dongle" if d.is_dongle else ("CyberBoard" if d.is_cyberboard else "other")
        line = f"{d.port}  {d.product_id or '?':<12} [{kind}]"
        if d.version is not None:
            line += f"  fw={d.version}"
        if d.pages is not None:
            line += f"  pages={d.pages}"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="enumerate connected CyberBoard devices")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--all", action="store_true", help="include version/pages for each")

    p_info = sub.add_parser("info", help="full detail for one device (auto-detects if PORT omitted)")
    p_info.add_argument("port", nargs="?")
    p_info.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.cmd == "list":
        devices = list_devices(full=args.all)
        if args.json:
            print(json.dumps([asdict(d) for d in devices], indent=2))
        else:
            _print_table(devices)
        return 0 if devices else 1

    device = _resolve_target(args.port)
    if device is None:
        print("No CyberBoard found.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(asdict(device), indent=2))
    else:
        _print_table([device])
    return 0


if __name__ == "__main__":
    sys.exit(main())
