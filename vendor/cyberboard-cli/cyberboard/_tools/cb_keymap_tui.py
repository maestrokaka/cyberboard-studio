#!/usr/bin/env python3
"""Interactive TUI to edit a CyberBoard R4 keymap by clicking keys (issue #37).

Renders the keyboard-shaped grid from cb_keymap, makes every key clickable, and
reassigns a clicked key from a typed key name (resolved via keycode.py) or a raw
#MMPPUUUU code. Changed keys are highlighted; `s` saves the modified config.

Optional feature — needs the `textual` extra:  pip install 'cyberboard-cli[tui]'
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import ClassVar

import cb_keymap
import cb_keymap_color
import keycode

try:
    from rich.text import Text
    from textual import events
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Footer, Header, Input, Label, Static
except ModuleNotFoundError:
    raise SystemExit(
        "cb_keymap edit needs the TUI extra — pip install 'cyberboard-cli[tui]'"
    ) from None

# Layer-independent (widths are fixed by the template), so build the click
# hit-map and content spans once. _HIT maps a click (line, col) -> matrix index
# over each key box rectangle; _SPAN gives the (mid_line, start, end) of each
# cell's label text for change highlighting.
_GEOMETRY = cb_keymap.cell_geometry()
_HIT = {
    (ln, col): idx
    for idx, top, bot, cl, cr in _GEOMETRY
    for ln in range(top, bot + 1)
    for col in range(cl, cr + 1)
}
_SPAN = {idx: (top + 1, cl + 1, cr) for idx, top, bot, cl, cr in _GEOMETRY}


def _styled(layer: list[str], corners: str, changed: set[int]) -> Text:
    """Rendered keyboard as a Rich Text: category colors + changed-key highlight.

    Colors are applied as a geometry-driven span overlay (same mechanism as
    cb_keymap's ANSI post-pass) so they never disturb the plain-text layout;
    the changed-yellow overlay is applied last so it wins on edited cells."""
    lines = cb_keymap.render(layer, corners).split("\n")
    text = Text("\n".join(lines), no_wrap=True)
    starts, pos = [], 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1  # + newline
    cats = cb_keymap_color.categories(layer)
    for idx, (mid, c0, c1) in _SPAN.items():
        cat = cats.get(idx)
        if cat and cat != "blank":
            text.stylize(f"color({cb_keymap_color.CATEGORY_COLOR[cat]})",
                         starts[mid] + c0, starts[mid] + c1)
    for idx in changed:
        mid, c0, c1 = _SPAN[idx]
        text.stylize("bold black on yellow", starts[mid] + c0, starts[mid] + c1)
    return text


class KeyEditScreen(ModalScreen[str]):
    """Modal asking for the new assignment of one key."""

    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, index: int, label: str, code: str) -> None:
        super().__init__()
        self._index, self._label, self._code = index, label, code

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"key #{self._index}   now: {self._label or '(empty)'}   {self._code}")
            yield Input(placeholder="esc / a / lctrl / #00070029   (Enter=apply, Esc=cancel)", id="kc")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class Keyboard(Static):
    """The clickable keyboard grid."""

    def on_click(self, event: events.Click) -> None:
        idx = _HIT.get((event.offset.y, event.offset.x))
        if idx is not None:
            self.app.edit_index(idx)


class KeymapEditApp(App):
    """Click a key to reassign it; `s` saves, `←/→` switch layer."""

    CSS = """
    KeyEditScreen { align: center middle; }
    #dialog { width: 72; height: auto; padding: 1 2; border: thick $accent; background: $surface; }
    Keyboard { padding: 0; }
    """
    BINDINGS: ClassVar = [
        ("s", "save", "Save"),
        ("q", "quit", "Quit"),
        ("left", "prev_layer", "Prev layer"),
        ("right", "next_layer", "Next layer"),
    ]

    def __init__(self, config: dict, layers: list[list[str]], layer_n: int,
                 corners: str, out_path: str) -> None:
        super().__init__()
        self._config = config
        self._layers = layers  # same list objects held inside _config (saved in place)
        self._n = layer_n
        self._corners = corners
        self._out = out_path
        self._changed = [set() for _ in layers]
        # Snapshot the loaded values so a key reverted to its original is no
        # longer counted/highlighted as changed.
        self._original = [list(layer) for layer in layers]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Keyboard(id="board")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "CyberBoard R4 — keymap edit"
        self._refresh()

    def _refresh(self) -> None:
        n_changed = len(self._changed[self._n - 1])
        self.sub_title = (f"layer {self._n}/{len(self._layers)}   "
                          f"{n_changed} changed   click a key · s=save · ←/→=layer")
        self.query_one(Keyboard).update(
            _styled(self._layers[self._n - 1], self._corners, self._changed[self._n - 1]))

    def edit_index(self, idx: int) -> None:
        layer = self._layers[self._n - 1]
        code = layer[idx]

        def _apply(value: str) -> None:
            if not value:
                return
            try:
                new = keycode.name_to_code(value)
            except (KeyError, ValueError) as e:
                self.notify(str(e), title="invalid key", severity="error")
                return
            if new == layer[idx]:
                return
            layer[idx] = new
            changed = self._changed[self._n - 1]
            if new == self._original[self._n - 1][idx]:
                changed.discard(idx)
            else:
                changed.add(idx)
            self._refresh()

        self.push_screen(KeyEditScreen(idx, cb_keymap.decode(code), code), _apply)

    def action_prev_layer(self) -> None:
        if self._n > 1:
            self._n -= 1
            self._refresh()

    def action_next_layer(self) -> None:
        if self._n < len(self._layers):
            self._n += 1
            self._refresh()

    def action_save(self) -> None:
        # Atomic save: write a temp file in the same dir, then os.replace — an
        # interrupted write never truncates the user's (possibly only) config.
        target = Path(self._out)
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=target.parent or ".", delete=False
            ) as f:
                tmp_name = f.name
                json.dump(self._config, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_name, target)
        except OSError as e:
            if tmp_name is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
            self.notify(str(e), title="save failed", severity="error")
            return
        total = sum(len(c) for c in self._changed)
        self.notify(f"saved {self._out}  ({total} keys changed)", title="saved")


def _load(config_path: str, layer_n: int) -> tuple[dict, list[list[str]]]:
    try:
        with open(config_path) as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"cb_keymap edit: cannot read {config_path}: {e}") from None
    try:
        layers = [ld["layer"] for ld in config["key_layer"]["layer_data"]]
    except (KeyError, TypeError):
        raise SystemExit(
            f"cb_keymap edit: {config_path} has no key_layer.layer_data") from None
    if not 1 <= layer_n <= len(layers):
        raise SystemExit(
            f"cb_keymap edit: --layer {layer_n} out of range (1..{len(layers)})")
    for i, layer in enumerate(layers, 1):
        if (not isinstance(layer, list) or len(layer) != cb_keymap._MATRIX_SIZE
                or any(not isinstance(v, str) for v in layer)):
            raise SystemExit(f"cb_keymap edit: layer {i} malformed "
                             f"(need {cb_keymap._MATRIX_SIZE} string keycodes)")
    return config, layers


def run(config_path: str, layer_n: int = 1, corners: str = "round",
        out_path: str | None = None) -> int:
    """Launch the editor on `config_path`; saves to `out_path` (default: in place)."""
    config, layers = _load(config_path, layer_n)
    KeymapEditApp(config, layers, layer_n, corners, out_path or config_path).run()
    return 0
