#!/usr/bin/env python3
"""Keycode value codec: readable name <-> `#MMPPUUUU`.

This is namespace ② (value) of `keymap.toml` (see `.claude/rules/40-cli-spec.md`):
what a key *emits*, as opposed to namespace ① (which physical key), handled by
`keymap_alias.py`. The two share STD_NAMES so "the a key" (alias `a`) and "emits a"
(value `a`) use one vocabulary.

Design — hybrid, lossless:
- Standard keys (HID page 0x07 keyboard, 0x0C consumer/media) get clean lowercase
  tokens we author here (the authoritative UI label table renders these as keycap
  faces like `!<br/>1` and non-unique strings, useless for a reversible codec).
- Vendor functions (page 0x92) get a curated, *bijective* subset of the authoritative
  UI labels (Layer1-7, Fn1-7, LED/PCB/BT/system). The CLI does not interpret 0x92
  semantics — these are convenience labels only (black box, 90 続12).
- Everything else — undecoded vendor codes, any modifier (MM != 00), unknown pages —
  round-trips through the raw `#MMPPUUUU` passthrough form. So code -> name -> code is
  always identity, which is what makes the toml<->IR round-trip lossless.
"""
from __future__ import annotations

import re

UNASSIGNED = "#00000000"
CLEAR_TOKEN = "."  # toml value that explicitly clears a position to UNASSIGNED
_CODE_RE = re.compile(r"^#[0-9A-Fa-f]{8}$")

# --- Standard keys: (usage page, usage id) -> clean lowercase token --------------
# Page 0x07 (keyboard/keypad). Symbol keys are named by function, not keycap face,
# since the face is shift-dependent (the `1` key is not "!").
_STD_07: dict[int, str] = {0x04 + i: c for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
_STD_07.update({0x1E + i: str((i + 1) % 10) for i in range(10)})  # 1..9,0
_STD_07.update({0x3A + i: f"f{i + 1}" for i in range(12)})         # f1..f12
_STD_07.update({
    0x28: "enter", 0x29: "esc", 0x2A: "backspace", 0x2B: "tab", 0x2C: "space",
    0x2D: "minus", 0x2E: "equal", 0x2F: "lbracket", 0x30: "rbracket", 0x31: "backslash",
    0x33: "semicolon", 0x34: "quote", 0x35: "grave", 0x36: "comma", 0x37: "period",
    0x38: "slash", 0x39: "caps", 0x46: "printscreen", 0x47: "scrolllock", 0x48: "pause",
    0x49: "insert", 0x4A: "home", 0x4B: "pageup", 0x4C: "delete", 0x4D: "end",
    0x4E: "pagedown", 0x4F: "right", 0x50: "left", 0x51: "down", 0x52: "up",
    0x53: "numlock", 0x65: "app",
    0xE0: "lctrl", 0xE1: "lshift", 0xE2: "lalt", 0xE3: "lgui",
    0xE4: "rctrl", 0xE5: "rshift", 0xE6: "ralt", 0xE7: "rgui",
})
# Page 0x0C (consumer / media)
_STD_0C: dict[int, str] = {
    0xB5: "next", 0xB6: "prev", 0xB7: "stop", 0xCD: "play", 0xE2: "mute",
    0xE9: "volup", 0xEA: "voldown", 0x70: "brightup", 0x6F: "brightdown",
}

# Shared with keymap_alias.py (positions reuse this vocabulary for standard keys).
STD_NAMES: dict[tuple[int, int], str] = {
    **{(0x07, u): n for u, n in _STD_07.items()},
    **{(0x0C, u): n for u, n in _STD_0C.items()},
}

# --- Vendor (page 0x92): curated, bijective subset of the authoritative UI labels --
# (90 続11-12, `_re/keycode_labels.json`). Convenience labels only; the firmware
# semantics are a black box. Rare / non-unique vendor codes (LFn/RFn, NP zone,
# pages 0x90/0x91/0x95) are intentionally omitted -> they round-trip as raw `#...`.
VENDOR_NAMES: dict[tuple[int, int], str] = {
    # Layer switch (permanent)
    (0x92, 0x0C0F): "Layer1", (0x92, 0x0C10): "Layer2", (0x92, 0x0C11): "Layer3",
    (0x92, 0x0C12): "Layer4", (0x92, 0x0C13): "Layer5", (0x92, 0x0C14): "Layer6",
    (0x92, 0x0C15): "Layer7",
    # Fn (momentary) — Fn2 is the oddball 0C0B (90 续12)
    (0x92, 0x0C20): "Fn1", (0x92, 0x0C0B): "Fn2", (0x92, 0x0C22): "Fn3",
    (0x92, 0x0C23): "Fn4", (0x92, 0x0C24): "Fn5", (0x92, 0x0C25): "Fn6",
    (0x92, 0x0C26): "Fn7",
    # Display LED (top 40x5) + wireless
    (0x92, 0x0100): "NextLED", (0x92, 0x0101): "LED_OnOff",
    (0x92, 0x0102): "LED_Light+", (0x92, 0x0103): "LED_Light-",
    (0x92, 0x0104): "LED_Speed+", (0x92, 0x0105): "LED_Speed-",
    (0x92, 0x0140): "LED_Rotation",
    (0x92, 0x0106): "BT1", (0x92, 0x0107): "BT2", (0x92, 0x0108): "BT3",
    (0x92, 0x0130): "2_4G",
    # PCB per-key backlight ("lighting")
    (0x92, 0x0900): "NextPCB", (0x92, 0x0901): "PCB_Light+",
    (0x92, 0x0902): "PCB_Light-", (0x92, 0x0903): "PCB_OnOff",
    (0x92, 0x0904): "PCB_Speed+", (0x92, 0x0905): "PCB_Speed-",
    (0x92, 0x0920): "PCB_SAT", (0x92, 0x0921): "PCB_Light", (0x92, 0x091F): "LED_Color",
    # System
    (0x92, 0x0922): "Win_Mac", (0x92, 0x0910): "Battery", (0x92, 0x0A02): "Reset",
    (0x92, 0x1300): "TouchSen",
}

CODE_TO_NAME: dict[tuple[int, int], str] = {**STD_NAMES, **VENDOR_NAMES}
# Case-insensitive reverse map; assert bijection so the round-trip stays lossless.
_NAME_TO_KEY: dict[str, tuple[int, int]] = {}
for _k, _n in CODE_TO_NAME.items():
    _lower = _n.lower()
    if _lower in _NAME_TO_KEY:
        raise ValueError(f"duplicate keycode name {_n!r}: {_NAME_TO_KEY[_lower]} and {_k}")
    _NAME_TO_KEY[_lower] = _k


def _parts(code: str) -> tuple[int, int, int]:
    """`#MMPPUUUU` -> (mm, pp, uuuu)."""
    if not _CODE_RE.match(code):
        raise ValueError(f"not an 8-hex keycode: {code!r}")
    return int(code[1:3], 16), int(code[3:5], 16), int(code[5:9], 16)


def code_to_name(code: str) -> str:
    """`#MMPPUUUU` -> readable name, or raw `#...` when unnamed.

    Unassigned -> `.` (the clear token). Any modifier (MM != 00) stays raw, since the
    named table is MM=00 only. Unknown page/usage stays raw -> always round-trips.
    """
    mm, pp, uuuu = _parts(code)
    if pp == 0 and uuuu == 0:
        return CLEAR_TOKEN
    if mm == 0 and (pp, uuuu) in CODE_TO_NAME:
        return CODE_TO_NAME[(pp, uuuu)]
    return f"#{code[1:].upper()}"


def name_to_code(value: str) -> str:
    """Readable name (or raw `#...` passthrough, or `.`) -> `#MMPPUUUU`.

    Passthrough `#...` is validated and upper-cased so it round-trips byte-for-byte.
    Name lookup is case-insensitive. `.` / empty clears to unassigned.
    """
    v = value.strip()
    if v in ("", CLEAR_TOKEN):
        return UNASSIGNED
    if v.startswith("#"):
        _parts(v)  # validate 8-hex; raises otherwise
        return f"#{v[1:].upper()}"
    key = _NAME_TO_KEY.get(v.lower())
    if key is None:
        raise KeyError(f"unknown keycode name: {value!r} (use a readable name or #MMPPUUUU)")
    pp, uuuu = key
    return f"#00{pp:02X}{uuuu:04X}"
