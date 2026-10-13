#!/usr/bin/env python3
"""Health check for the CyberBoard connection — `doctor` / preflight.

AM Master's worst failure mode is silence: you can't tell whether the board is
connected, held by another app, on the wrong port, or just dead. This runs the
exact checks that map to AM Master's known flakiness causes (see
.claude/rules/30-write-protocol.md §6) and reports a clear verdict — WITHOUT
writing anything. Every probe here is read-only ([1,1], [1,2], [2,6], [6,9]);
no JSON_START, no reset, no config change.

A clean run (device identified, port opens exclusively, CRC valid both ways,
and a full 94-frame keymap read-back streams back intact) is strong evidence
the write path is healthy — it exercises sustained multi-frame transfer, which
is what a config write needs.

Usage: cb_doctor.py [PORT]    # omit PORT to auto-scan
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Final

import serial  # pyserial

from cb_device import BAUD, DeviceInfo, candidate_ports, probe
from cb_protocol import build_frame, crc_ok

CMD_PRODUCT_ID: Final = (1, 1)
CMD_PRODUCT_INFO: Final = (1, 2)
CMD_CHECK_PAGES: Final = (2, 6)
CMD_GET_KEY_MSG: Final = (6, 9)
EXPECTED_KEYMAP_FRAMES: Final = 94
SYMBOL: Final = {"ok": "✓", "warn": "!", "fail": "✗"}


@dataclass(frozen=True)
class Check:
    status: str  # "ok" | "warn" | "fail"
    label: str
    detail: str = ""
    hint: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    @property
    def failed(self) -> bool:
        return any(c.status == "fail" for c in self.checks)


def _query(ser: serial.Serial, command: tuple[int, int]) -> bytes:
    ser.reset_input_buffer()
    ser.write(build_frame(*command))
    ser.flush()
    return ser.read(64)


def port_check(report: Report) -> list[str]:
    ports = candidate_ports()
    if not ports:
        report.add(Check(
            "fail", "serial ports",
            "no serial ports found" if sys.platform == "win32" else "no /dev/cu.usbmodem* devices found",
            "Connect the board over USB-C with a DATA cable (charge-only cables "
            "won't enumerate). Try a different cable/port. Wired, not dongle.",
        ))
        return ports
    report.add(Check("ok", "serial ports", f"{len(ports)} usbmodem candidate(s)"))
    return ports


def identify(report: Report, ports: list[str]) -> DeviceInfo | None:
    found: DeviceInfo | None = None
    others: list[str] = []
    dongles: list[str] = []
    for port in ports:
        info = probe(port, full=True)
        if info and info.is_cyberboard:
            found = info
            continue
        if info and info.is_dongle:
            dongles.append(f"{port} ({info.product_id})")
            continue
        others.append(port)

    if found:
        report.add(Check(
            "ok", "CyberBoard",
            f"{found.product_id} @ {found.port}  ver {found.version}  pages {found.pages}",
        ))
    elif dongles:
        report.add(Check(
            "fail", "CyberBoard",
            f"only a wireless dongle responded: {', '.join(dongles)}",
            "Config write targets the WIRED board. Connect the keyboard itself "
            "over USB-C (the dongle path is separate).",
        ))
    else:
        report.add(Check(
            "fail", "CyberBoard",
            "no port answered the [1,1] product_id probe",
            "Ports exist but none is a CyberBoard. Check the cable is a data "
            "cable and the board is powered/wired.",
        ))

    if others:
        report.add(Check(
            "warn", "other ports ignored",
            ", ".join(others),
            "These answered nothing / aren't CyberBoards (e.g. a monitor's USB "
            "hub). Correctly skipped — identity is by [1,1] response, not name.",
        ))
    return found


def deep_checks(report: Report, port: str) -> None:
    try:
        ser = serial.Serial(port, baudrate=BAUD, timeout=1.5, write_timeout=2, exclusive=True)
    except (serial.SerialException, OSError) as err:
        report.add(Check(
            "fail", "exclusive open",
            str(err),
            "The port is busy. Quit AM Master (or any app holding the serial "
            "port) and retry — a held port is the #1 cause of write failures.",
        ))
        return

    try:
        report.add(Check("ok", "exclusive open", f"{port} @ {BAUD} 8N1"))
        time.sleep(0.1)

        replies = {name: _query(ser, cmd) for name, cmd in (
            ("product_id", CMD_PRODUCT_ID),
            ("product_info", CMD_PRODUCT_INFO),
            ("check_pages", CMD_CHECK_PAGES),
        )}
        bad = [n for n, r in replies.items() if not crc_ok(r)]
        if bad:
            report.add(Check(
                "fail", "frame round-trip",
                f"invalid/again-missing CRC on: {', '.join(bad)}",
                "Replies are corrupt — line noise or a baud mismatch. Reseat the "
                "cable; this port may not be the real config channel.",
            ))
        else:
            report.add(Check("ok", "frame round-trip", "CRC-8 valid both directions (3/3 queries)"))

        ser.reset_input_buffer()
        ser.write(build_frame(*CMD_GET_KEY_MSG))
        ser.flush()
        frames = []
        while True:
            chunk = ser.read(64)
            if not chunk:
                break
            frames.append(chunk)
        bad_crc = sum(1 for f in frames if not crc_ok(f))
        if not frames:
            report.add(Check(
                "warn", "bulk read-back",
                "[6,9] keymap returned nothing",
                "Identity works but bulk transfer didn't respond. Writes may "
                "still work, but this path looked unhealthy.",
            ))
        elif bad_crc or len(frames) < EXPECTED_KEYMAP_FRAMES:
            report.add(Check(
                "warn", "bulk read-back",
                f"{len(frames)} frames (expected {EXPECTED_KEYMAP_FRAMES}), {bad_crc} bad CRC",
                "Partial/garbled bulk read — possible frame drops. A write might "
                "need a retry.",
            ))
        else:
            report.add(Check(
                "ok", "bulk read-back",
                f"{len(frames)} keymap frames, all CRC ok (sustained transfer healthy)",
            ))
    finally:
        ser.close()


def run(port_arg: str | None) -> Report:
    report = Report()
    if port_arg is not None:
        info = probe(port_arg, full=True)
        if info and info.is_cyberboard:
            report.add(Check("ok", "CyberBoard", f"{info.product_id} @ {info.port}  ver {info.version}  pages {info.pages}"))
            deep_checks(report, port_arg)
            return report
        report.add(Check("fail", "CyberBoard", f"{port_arg} did not identify as a CyberBoard"))
        return report

    ports = port_check(report)
    if not ports:
        return report
    found = identify(report, ports)
    if found:
        deep_checks(report, found.port)
    return report


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else None
    report = run(port)

    print("CyberBoard doctor\n")
    for c in report.checks:
        print(f"  {SYMBOL[c.status]} {c.label}: {c.detail}".rstrip())
        if c.hint and c.status != "ok":
            print(f"      -> {c.hint}")

    healthy = not report.failed and any(c.label == "CyberBoard" and c.status == "ok" for c in report.checks)
    print()
    if healthy:
        print("verdict: HEALTHY — device reachable; write path looks good.")
        return 0
    print("verdict: PROBLEM — see the ✗ above and its hint.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
