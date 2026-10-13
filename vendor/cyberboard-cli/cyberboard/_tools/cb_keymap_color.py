#!/usr/bin/env python3
"""Category coloring for the cb_keymap keyboard grid (issue #37).

One classifier (keycode -> category) feeds BOTH consumers: `keymap show` maps
the category to an ANSI SGR color, the `keymap edit` TUI maps it to a Rich
style. Colors are applied as a `cell_geometry()`-driven span overlay so the
plain-text layout from `cb_keymap.render()` is never disturbed — keeping color
out of `render()` itself avoids the trap where ANSI bytes inflate `len()` and
shift the right-hand cluster.
"""
from __future__ import annotations

import re

import cb_keymap

# Category -> xterm-256 index, shared by ANSI (show) and Rich (TUI) so the two
# stay in sync (dark-terminal-safe mid brights; vendor=105 stays clear of the
# fn pink, per a palette review).
CATEGORY_COLOR = {
    "mod": 81,      # cyan        — Ctrl/Shift/Alt/Gui/Caps
    "fn": 213,      # pink        — F1-F12 + media
    "nav": 114,     # green       — Esc/Tab/Enter/Bsp/Space + Home/End/PgUp/PgDn/arrows
    "alnum": 252,   # white       — letters + digits
    "punct": 247,   # grey        — punctuation / symbols
    "vendor": 105,  # blue-violet — AM vendor page (0x92)
    "blank": 240,   # dim         — unassigned
}


def category(code: str) -> str:
    """Color category for a `#MMPPUUUU` keycode (see CATEGORY_COLOR keys)."""
    if not isinstance(code, str) or len(code) != 9 or not code.startswith("#"):
        return "blank"
    try:
        pp, uuuu = int(code[3:5], 16), int(code[5:9], 16)
    except ValueError:
        return "blank"
    if pp == 0 and uuuu == 0:
        return "blank"
    if pp == 0x92:
        return "vendor"
    if pp == 0x0C:
        return "fn"
    if pp == 0x07:
        if 0x3A <= uuuu <= 0x45:  # F1-F12
            return "fn"
        if 0xE0 <= uuuu <= 0xE7 or uuuu == 0x39:  # modifiers + Caps
            return "mod"
        if 0x46 <= uuuu <= 0x52:  # PrSc..arrows (nav cluster)
            return "nav"
        if 0x04 <= uuuu <= 0x27:  # letters + digits
            return "alnum"
        if uuuu in (0x28, 0x29, 0x2A, 0x2B, 0x2C):  # enter/esc/bsp/tab/space
            return "nav"
        return "punct"
    return "vendor"


_MOD_LABELS = {"Fn", "Cap", "⇪", *("LR"[s] + sym for s in (0, 1)
                                   for sym in "⌃⇧⌥⌘")}
_NAV_LABELS = {"Esc", "Tab", "Bsp", "Ent", "Spc", "Space", "Del", "Ins",
               "Home", "End", "PgUp", "PgDn", "←", "→", "↑", "↓"}
_MEDIA_LABELS = {"Prv", "Ply", "Nxt", "Stop", "Mut", "Vl+", "Vl-", "Br+", "Br-"}


def _category_of_label(label: str) -> str:
    """Color category for a skeleton default label (no keycode available)."""
    if not label:
        return "blank"
    if label in _MOD_LABELS:
        return "mod"
    if label in _NAV_LABELS:
        return "nav"
    if label in _MEDIA_LABELS or re.fullmatch(r"F\d+", label):
        return "fn"
    if len(label) == 1 and label.isalnum():
        return "alnum"
    return "punct"


def _skeleton_defaults() -> dict[int, str]:
    """matrix_index -> built-in default label (mirrors what `render(None)` draws)."""
    out = {r * cb_keymap.COLS + col: d
           for r, row in enumerate(cb_keymap._MAIN_ROWS)
           for col, _inner, d in row}
    out.update({r * cb_keymap.COLS + cb_keymap._NAV_COL: d
                for r, d in cb_keymap._NAV.items()})
    out[4 * cb_keymap.COLS + cb_keymap._UP_COL] = cb_keymap._UP_DEFAULT
    out.update({5 * cb_keymap.COLS + col: d
                for col, d in zip(cb_keymap._ARROW_COLS, cb_keymap._ARROW_DEFAULTS,
                                  strict=True)})
    return out


_DEFAULTS = _skeleton_defaults()


def categories(layer: list[str] | None) -> dict[int, str]:
    """Color category per matrix index — by keycode when a layer is given, else
    by the skeleton default label."""
    return {
        idx: (category(layer[idx]) if layer is not None and 0 <= idx < len(layer)
              else _category_of_label(_DEFAULTS.get(idx, "")))
        for idx, *_ in cb_keymap.cell_geometry()
    }


def colorize_ansi(plain: str, cats: dict[int, str]) -> str:
    """Wrap each cell's label span in ANSI color as a geometry-driven post-pass.

    Layout stays in `plain` (correct widths); only the label text gets SGR
    codes, so box borders keep the default color and no width-counting bug can
    shift the right-hand cluster (the trap of coloring inside `_box`)."""
    lines = plain.split("\n")
    by_line: dict[int, list[tuple[int, int, int]]] = {}
    for idx, top, _bot, cl, cr in cb_keymap.cell_geometry():
        cat = cats.get(idx)
        if cat and cat != "blank":
            by_line.setdefault(top + 1, []).append((cl + 1, cr, CATEGORY_COLOR[cat]))
    for ln, spans in by_line.items():
        if ln >= len(lines):
            continue
        s, parts, pos = lines[ln], [], 0
        for start, end, color in sorted(spans):
            parts.append(s[pos:start])
            parts.append(f"\x1b[38;5;{color}m{s[start:end]}\x1b[0m")
            pos = end
        parts.append(s[pos:])
        lines[ln] = "".join(parts)
    return "\n".join(lines)


def render_colored(layer: list[str] | None = None, corners: str = "round") -> str:
    """`cb_keymap.render()` with ANSI category colors (for a TTY)."""
    return colorize_ansi(cb_keymap.render(layer, corners), categories(layer))
