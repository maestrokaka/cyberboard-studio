#!/usr/bin/env python3
"""Render a CyberBoard R4 keymap as a keyboard-shaped ASCII grid.

Unlike a flat `idx -> key` table, this draws the actual physical layout with
box-drawing key boxes: the function/media strip on top, the right-hand nav
column (Home/End/PgUp/PgDn), a wide Space bar, and an inverted-T arrow cluster
at the bottom-right.

The R4 matrix is 25 cols x 8 rows = 200; physical index = row*25 + col. Physical
keys live in rows 0-5, cols 0-14. Cell labels are filled by decoding each
position's `#MMPPUUUU` keycode to a short name; with no config, a built-in
default R4 skeleton is shown.

Usage:
  cb_keymap.py                      # built-in default R4 skeleton
  cb_keymap.py CONFIG.json          # decode layer 1 of an IR/official config
  cb_keymap.py CONFIG.json --layer 2
Reads the key_layer from any official/IR config, or a cb_read.py --json dump.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

COLS = 25  # matrix columns; physical index = row * COLS + col

# --- HID usage-id -> short name, page 0x07 (keyboard/keypad) ---
HID07 = {0x04 + i: c for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
HID07.update({0x1E + i: str((i + 1) % 10) for i in range(10)})  # 1..9,0
HID07.update({
    0x28: "Ent", 0x29: "Esc", 0x2A: "Bsp", 0x2B: "Tab", 0x2C: "Spc", 0x2D: "-",
    0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`",
    0x36: ",", 0x37: ".", 0x38: "/", 0x39: "Cap", 0x46: "PrSc", 0x47: "ScLk",
    0x48: "Pause", 0x49: "Ins", 0x4A: "Home", 0x4B: "PgUp", 0x4C: "Del",
    0x4D: "End", 0x4E: "PgDn", 0x4F: "→", 0x50: "←", 0x51: "↓", 0x52: "↑",
    0x53: "NumLk", 0x65: "App",
})
HID07.update({0x3A + i: f"F{i + 1}" for i in range(12)})  # F1..F12
# Modifiers shown with macOS keycap symbols (⌃⇧⌥⌘) + side, compact and legible.
HID07.update({0xE0: "L⌃", 0xE1: "L⇧", 0xE2: "L⌥", 0xE3: "L⌘",
              0xE4: "R⌃", 0xE5: "R⇧", 0xE6: "R⌥", 0xE7: "R⌘"})
# page 0x0C (consumer / media)
HID0C = {0xB5: "Nxt", 0xB6: "Prv", 0xB7: "Stop", 0xCD: "Ply", 0xE2: "Mut",
         0xE9: "Vl+", 0xEA: "Vl-", 0x70: "Br+", 0x6F: "Br-"}


def decode(code: str) -> str:
    """`#MMPPUUUU` -> short cell label. MM=modifier, PP=usage page, UUUU=usage id.

    Unassigned (#00000000) renders blank. The AM vendor page (0x92) has no
    public name table here, so it falls back to a short `Fn<hex>` form; unknown
    pages fall back to `pp:uuuu`. Long names are truncated by the caller to the
    cell width.
    """
    if not isinstance(code, str) or len(code) != 9 or not code.startswith("#"):
        return code or ""
    try:
        mm, pp, uuuu = int(code[1:3], 16), int(code[3:5], 16), int(code[5:9], 16)
    except ValueError:
        return code
    if pp == 0 and uuuu == 0:
        return ""  # unassigned -> blank cell
    if pp == 0x07:
        name = HID07.get(uuuu, f"07:{uuuu:x}")
    elif pp == 0x0C:
        name = HID0C.get(uuuu, f"c{uuuu:x}")
    elif pp == 0x92:
        name = f"Fn{uuuu:x}"  # AM vendor page (names live in the web UI)
    else:
        name = f"{pp:x}:{uuuu:x}"
    return f"M{mm:x}+{name}" if mm else name


# --- Physical layout template -------------------------------------------------
# Each main-block cell is (col, inner_width, default_label); its matrix index is
# row*COLS + col. The right cluster is handled per row (nav box / arrow keys).
# Widths reproduce a real R4's relative key sizes (wide Tab/Caps/Shift/Enter,
# very wide Space).

_ROW0 = [(c, 5, lbl) for c, lbl in enumerate(
    ["Esc", "F1", "F2", "F3", "F4", "F5", "F6",
     "Prv", "Ply", "Nxt", "Mut", "Vl-", "Vl+", "Del"])]
_ROW1 = [(c, 5, lbl) for c, lbl in enumerate(
    ["`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "\\"])]
_ROW2 = ([(0, 8, "Tab")]
         + [(c + 1, 5, lbl) for c, lbl in enumerate(
             ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]"])]
         + [(13, 8, "Bsp")])
_ROW3 = ([(0, 10, "L⌃")]
         + [(c + 1, 5, lbl) for c, lbl in enumerate(
             ["A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", "."])]
         + [(13, 12, "Ent")])
_ROW4 = ([(0, 12, "L⇧")]
         + [(c + 1, 5, lbl) for c, lbl in enumerate(
             ["Z", "X", "C", "V", "B", "N", "M", ",", ".", "/"])]
         + [(11, 16, "R⇧")])
_ROW5 = [(0, 6, "Fn"), (1, 6, "L⌥"), (2, 6, "L⌘"),
         (6, 36, "Space"), (10, 6, "R⌘"), (11, 6, "R⌥")]

# Per-row right cluster: ("nav", col, inner, default) for rows 0-3, the Up key
# for row 4 (placed above Down), and the L/D/R arrows for row 5.
_NAV = {0: "Home", 1: "End", 2: "PgUp", 3: "PgDn"}
_NAV_COL, _NAV_INNER = 14, 12
_ARROW_INNER = 3
_UP_COL = 13          # shift row, idx 113
_ARROW_COLS = [12, 13, 14]  # bottom row Lft/Dwn/Rgt, idx 137/138/139
_ARROW_DEFAULTS = ["←", "↓", "→"]
_UP_DEFAULT = "↑"     # shift-row Up; shared so render() + the color skeleton can't drift

_MAIN_ROWS = [_ROW0, _ROW1, _ROW2, _ROW3, _ROW4, _ROW5]

GUTTER = 2          # spaces between the main block and the right cluster
_ARROW_INDENT = _ARROW_INNER + 1  # one arrow cell -> Up sits above Down


def _fit(label: str, inner: int) -> str:
    """Center a label in a cell of `inner` chars, truncating if too long."""
    s = label if len(label) <= inner else label[:inner]
    return s.center(inner)


# Outer-corner glyphs per style; the interior ┬/┴ junctions are unchanged.
CORNERS = {
    "round": ("╭", "╮", "╰", "╯"),
    "square": ("┌", "┐", "└", "┘"),
}


def _box(cells: list[tuple[str, int]],
         corners: tuple[str, str, str, str] = CORNERS["round"]) -> list[str]:
    """Render contiguous boxes (shared borders) -> 3 lines [top, mid, bottom]."""
    tl, tr, bl, br = corners
    top = tl + "┬".join("─" * w for _, w in cells) + tr
    mid = "│" + "│".join(_fit(lbl, w) for lbl, w in cells) + "│"
    bot = bl + "┴".join("─" * w for _, w in cells) + br
    return [top, mid, bot]


def _label_at(layer: list[str] | None, idx: int, default: str) -> str:
    """Decoded label for matrix `idx`, or the skeleton default with no config."""
    if layer is None:
        return default
    if 0 <= idx < len(layer):
        return decode(layer[idx])
    return ""


def render(layer: list[str] | None = None, corners: str = "round") -> str:
    """Render the keyboard grid. `layer` is a 200-entry keycode list, or None
    for the built-in default R4 skeleton. `corners` selects the box style
    ("round" -> ╭╮╰╯, "square" -> ┌┐└┘)."""
    glyphs = CORNERS.get(corners, CORNERS["round"])
    # 1. Render each row's main block; track the widest for a fixed nav offset.
    main_blocks: list[list[str]] = []
    for r, row in enumerate(_MAIN_ROWS):
        cells = [(_label_at(layer, r * COLS + col, default), inner)
                 for col, inner, default in row]
        main_blocks.append(_box(cells, glyphs))
    main_w = max(len(b[0]) for b in main_blocks)

    # 2. Build the right cluster for each row and stitch it on.
    out: list[str] = []
    for r, block in enumerate(main_blocks):
        if r in _NAV:  # rows 0-3: a single nav box
            label = _label_at(layer, r * COLS + _NAV_COL, _NAV[r])
            right = _box([(label, _NAV_INNER)], glyphs)
        elif r == 4:   # shift row: Up, indented to sit above Down
            label = _label_at(layer, r * COLS + _UP_COL, _UP_DEFAULT)
            right = [" " * _ARROW_INDENT + ln
                     for ln in _box([(label, _ARROW_INNER)], glyphs)]
        else:          # bottom row: Lft / Dwn / Rgt
            cells = [(_label_at(layer, r * COLS + col, default), _ARROW_INNER)
                     for col, default in zip(_ARROW_COLS, _ARROW_DEFAULTS)]
            right = _box(cells, glyphs)
        for i in range(3):
            out.append(block[i].ljust(main_w) + " " * GUTTER + right[i])
    return "\n".join(out)


def _main_width() -> int:
    """Width the main blocks are padded to (= the widest row's top line)."""
    return max(sum(inner for _, inner, _ in row) + len(row) + 1
               for row in _MAIN_ROWS)


def cell_geometry() -> list[tuple[int, int, int, int, int]]:
    """Layout of every key box as `(matrix_index, top_line, bottom_line,
    col_left, col_right)` in the same line/column coordinates `render()` emits
    (borders included, all inclusive). Layer-independent — widths are fixed by
    the template — so the TUI builds the click hit-map once and maps a click
    `(x=col, y=line)` back to a matrix index. Verified against `render()` output
    in the tests, so it can't silently drift from what is drawn."""
    cells: list[tuple[int, int, int, int, int]] = []
    for r, row in enumerate(_MAIN_ROWS):  # main blocks, left of the gutter
        top, col = 3 * r, 0
        for mcol, inner, _default in row:
            cells.append((r * COLS + mcol, top, top + 2, col, col + inner + 1))
            col += inner + 1
    base = _main_width() + GUTTER  # right cluster starts here on every row
    cells += [(r * COLS + _NAV_COL, 3 * r, 3 * r + 2, base, base + _NAV_INNER + 1)
              for r in _NAV]
    up_left = base + _ARROW_INDENT  # row 4: Up, indented above Down
    cells.append((4 * COLS + _UP_COL, 12, 14, up_left, up_left + _ARROW_INNER + 1))
    cells += [(5 * COLS + mcol, 15, 17,
               base + j * (_ARROW_INNER + 1), base + j * (_ARROW_INNER + 1) + _ARROW_INNER + 1)
              for j, mcol in enumerate(_ARROW_COLS)]
    return cells


_MATRIX_SIZE = 8 * COLS  # 25 cols x 8 rows = 200 keycodes per layer


def _load_layer(path: str, layer_n: int) -> list[str]:
    """Load + validate layer `layer_n` (1-indexed) from an IR/official config
    or `cb_read --json` dump. Rejects malformed shapes early so bad data can't
    reach decode()/_fit() and crash later."""
    try:
        with open(path) as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"cb_keymap: cannot read {path}: {e}") from None
    try:
        layers = [ly["layer"] for ly in config["key_layer"]["layer_data"]]
    except (KeyError, TypeError):
        raise SystemExit(f"cb_keymap: {path} has no key_layer.layer_data") from None
    if not 1 <= layer_n <= len(layers):
        raise SystemExit(
            f"cb_keymap: --layer {layer_n} out of range (1..{len(layers)})")
    layer = layers[layer_n - 1]
    if not isinstance(layer, list):
        raise SystemExit(f"cb_keymap: layer {layer_n} is not a list")
    if len(layer) != _MATRIX_SIZE:
        raise SystemExit(f"cb_keymap: layer {layer_n} has {len(layer)} keys; "
                         f"expected {_MATRIX_SIZE}")
    if any(not isinstance(v, str) for v in layer):
        raise SystemExit(f"cb_keymap: layer {layer_n} has non-string keycodes")
    return layer


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="cyberboard keymap",
        description="Render an R4 keymap as a keyboard-shaped ASCII grid.")
    sub = ap.add_subparsers(dest="action", required=True)
    show = sub.add_parser(
        "show", help="render the keymap as a keyboard-shaped ASCII grid")
    show.add_argument("config", nargs="?",
                      help="IR/official config JSON or a cb_read --json dump "
                           "(omit for the default R4 skeleton)")
    show.add_argument("--layer", type=int, default=1,
                      help="layer to show, 1-indexed (default: 1)")
    show.add_argument("--corners", choices=("round", "square"), default="round",
                      help="key-box corner style (default: round)")
    show.add_argument("--color", choices=("auto", "always", "never"),
                      default="auto",
                      help="colorize by key category (default: auto = TTY only)")

    edit = sub.add_parser(
        "edit", help="interactively edit the keymap by clicking keys (TUI; needs the 'tui' extra)")
    edit.add_argument("config",
                      help="IR/official config JSON to edit (a complete config)")
    edit.add_argument("--layer", type=int, default=1,
                      help="layer to start on, 1-indexed (default: 1)")
    edit.add_argument("--corners", choices=("round", "square"), default="round",
                      help="key-box corner style (default: round)")
    edit.add_argument("-o", "--output",
                      help="where to save edits (default: overwrite the input config)")
    args = ap.parse_args()

    if args.action == "edit":
        import cb_keymap_tui  # lazy: only the editor needs the textual extra
        return cb_keymap_tui.run(args.config, args.layer, args.corners, args.output)

    layer = _load_layer(args.config, args.layer) if args.config else None
    if args.config:
        print(f"CyberBoard R4 — {args.config}  (layer {args.layer})")
    else:
        print("CyberBoard R4 — default layout (no config)")
    color = (args.color == "always"
             or (args.color == "auto" and sys.stdout.isatty()
                 and os.environ.get("NO_COLOR") is None))
    if color:
        import cb_keymap_color  # lazy: plain rendering needs no color module
        print(cb_keymap_color.render_colored(layer, args.corners))
    else:
        print(render(layer, args.corners))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
