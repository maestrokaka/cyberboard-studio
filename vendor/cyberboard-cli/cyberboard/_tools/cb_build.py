#!/usr/bin/env python3
"""Build a write-ready IR config from keymap.toml + a complete base IR (the toml->json step).

    cb_build.py -k keymap.toml [-b base.json] -o config.json   # build
    cb_build.py --dump config.json [-o keymap.toml] [--full]   # IR -> keymap.toml

`build` is a pure file->file transform (no device I/O): it deep-copies the base IR and
applies the toml as a DIFF PATCH — JSON_START erases the whole flash, so the written
config must be complete, and the toml only carries overrides (90 续8, .claude/rules/40).

Override model:
- `[layer.1]`..`[layer.7]` (1-indexed; array index N-1) patch individual positions.
  Position = R4 alias or `r{row}c{col}` coordinate (keymap_alias.resolve_position);
  value = readable name or raw `#MMPPUUUU` (keycode.name_to_code). `.`/"" clears.
  Omitted layers/positions stay as in the base.
- `[[swap_key]]` / `[[exchange_key]]` / `[[macro]]` / `[[fn_key]]` REPLACE the whole
  corresponding base table when present (else kept). swap/exchange are sent by the
  R-series write; macro/fn_key are NOT (90 §5) — they go into the IR but won't reach
  the device yet, so build warns.

`--dump` emits a keymap.toml from an IR (every occupied position per layer, plus the
function tables) so a user can start from their current config and so the round-trip
`build(dump(C), base=C) == C` holds. `--full` emits all 200 positions/layer (incl.
explicit clears) for a base-independent exact round-trip.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tomllib
from pathlib import Path

from keycode import UNASSIGNED, code_to_name, name_to_code
from keymap_alias import COLS, coord_to_index, load_preset, resolve_position

LAYERS = 7
KEYS_PER_LAYER = 200
UNWRITTEN = ("macro", "fn_key")  # accepted, built into IR, but not sent by R-series write


def _warn(msg: str) -> None:
    print(f"cb_build: {msg}", file=sys.stderr)


# --- build: keymap.toml -> IR ----------------------------------------------------

def _resolve_base(toml: dict, cli_base: str | None, toml_path: Path | None) -> dict:
    meta = toml.get("meta", {})
    if meta.get("refresh_keymap_from_device"):
        raise SystemExit("cb_build: refresh_keymap_from_device is not supported in build "
                         "(pure file step) — capture the device keymap into a base with "
                         "cb_read first, then build from it.")
    raw = cli_base or meta.get("base")
    if not raw:
        raise SystemExit("cb_build: no base IR (pass -b, or set [meta].base in the toml). "
                         "A complete base is required: JSON_START erases everything.")
    path = Path(raw)
    if not path.is_absolute() and toml_path is not None and not cli_base:
        path = (toml_path.parent / path)  # [meta].base is relative to the toml file
    return json.loads(path.read_text())


def apply_layers(config: dict, toml: dict, aliases: dict[str, str]) -> int:
    layer_data = config["key_layer"]["layer_data"]
    applied = 0
    for n_str, overrides in toml.get("layer", {}).items():
        n = int(n_str)
        if not (1 <= n <= LAYERS):
            raise SystemExit(f"cb_build: layer {n} out of range (1..{LAYERS})")
        layer = layer_data[n - 1]["layer"]
        for pos, value in overrides.items():
            idx = resolve_position(pos, aliases)
            layer[idx] = name_to_code(str(value))
            applied += 1
    return applied


def _codes(values: list) -> list[str]:
    return [name_to_code(str(v)) for v in values]


def apply_swap(config: dict, entries: list[dict]) -> None:
    config["swap_key"] = [
        {"swap_key_index": i, "input_key": name_to_code(str(e["input"])),
         "out_key": name_to_code(str(e["out"]))}
        for i, e in enumerate(entries)
    ]
    config["swap_key_num"] = len(entries)


def apply_exchange(config: dict, entries: list[dict]) -> None:
    config["exchange_key"] = [
        {"exchange_index": i, "input_key": _codes(e["input"]), "out_key": _codes(e["out"])}
        for i, e in enumerate(entries)
    ]
    config["exchange_num"] = len(entries)


def apply_macro(config: dict, entries: list[dict]) -> None:
    # Real configs allow len(interval_ms) != len(out) (factory macro idx2: out=2, intvel=1),
    # so preserve interval_ms as given rather than enforcing equality.
    config["MACRO_key"] = [
        {"MACRO_key_index": i, "input_key": name_to_code(str(e["input"])),
         "out_key": _codes(e["out"]), "intvel_ms": list(e.get("interval_ms", []))}
        for i, e in enumerate(entries)
    ]
    config["MACRO_key_num"] = len(entries)


def apply_fn(config: dict, entries: list[dict]) -> None:
    config["Fn_key"] = [
        {"Fn_key_index": i, "input_key": name_to_code(str(e["input"])),
         "out_key": name_to_code(str(e["out"]))}
        for i, e in enumerate(entries)
    ]
    config["Fn_key_num"] = len(entries)


def build(toml: dict, base: dict, aliases: dict[str, str]) -> dict:
    config = copy.deepcopy(base)
    n_layers = apply_layers(config, toml, aliases)
    summary = [f"{n_layers} layer override(s)"]
    if "swap_key" in toml:
        apply_swap(config, toml["swap_key"]); summary.append(f"{len(toml['swap_key'])} swap")
    if "exchange_key" in toml:
        apply_exchange(config, toml["exchange_key"]); summary.append(f"{len(toml['exchange_key'])} exchange")
    if "macro" in toml:
        apply_macro(config, toml["macro"]); summary.append(f"{len(toml['macro'])} macro")
    if "fn_key" in toml:
        apply_fn(config, toml["fn_key"]); summary.append(f"{len(toml['fn_key'])} fn_key")
    if any(k in toml for k in UNWRITTEN):
        _warn("macro/fn_key are written into the IR but NOT sent by the R-series write "
              "(90 §5) — they won't reach the device yet.")
    _warn("applied: " + ", ".join(summary))
    return config


# --- dump: IR -> keymap.toml -----------------------------------------------------

def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_keymap(config: dict, *, full: bool = False) -> str:
    idx_alias = {coord_to_index(c): a for a, c in load_preset().items()}
    lines = ["[meta]", 'product = "R4"',
             "# base = \"...\"   # set before build (a complete base IR is required)", ""]
    for li, layer in enumerate(config["key_layer"]["layer_data"], start=1):
        lines.append(f"[layer.{li}]")
        for idx, code in enumerate(layer["layer"]):
            if not full and code == UNASSIGNED:
                continue
            pos = idx_alias.get(idx, f"r{idx // COLS}c{idx % COLS}")
            lines.append(f"{pos} = {_quote(code_to_name(code))}")
        lines.append("")
    lines.extend(_dump_functions(config))
    return "\n".join(lines).rstrip() + "\n"


def _real(*codes: str) -> bool:
    """An entry is a placeholder (skip it) when all its key fields are unassigned."""
    return any(c != UNASSIGNED for c in codes)


def _dump_functions(config: dict) -> list[str]:
    """One key=value per line (valid TOML). Placeholder (all-unassigned) entries are
    skipped — they carry no config, so dumping them is noise and build sets *_num from
    the real entries anyway (factory exchange = 7 placeholders, num=0)."""
    out: list[str] = []
    for e in config.get("swap_key", []):
        if not _real(e["input_key"], e["out_key"]):
            continue
        out += ["[[swap_key]]",
                f"input = {_quote(code_to_name(e['input_key']))}",
                f"out = {_quote(code_to_name(e['out_key']))}", ""]
    for e in config.get("exchange_key", []):
        if not _real(*e["input_key"], *e["out_key"]):
            continue
        i = "[" + ", ".join(_quote(code_to_name(c)) for c in e["input_key"]) + "]"
        o = "[" + ", ".join(_quote(code_to_name(c)) for c in e["out_key"]) + "]"
        out += ["[[exchange_key]]", f"input = {i}", f"out = {o}", ""]
    for e in config.get("MACRO_key", []):
        if not _real(e["input_key"], *e["out_key"]):
            continue
        o = "[" + ", ".join(_quote(code_to_name(c)) for c in e["out_key"]) + "]"
        iv = "[" + ", ".join(str(x) for x in e.get("intvel_ms", [])) + "]"
        out += ["[[macro]]",
                f"input = {_quote(code_to_name(e['input_key']))}",
                f"out = {o}", f"interval_ms = {iv}", ""]
    for e in config.get("Fn_key", []):
        if not _real(e["input_key"], e["out_key"]):
            continue
        out += ["[[fn_key]]",
                f"input = {_quote(code_to_name(e['input_key']))}",
                f"out = {_quote(code_to_name(e['out_key']))}", ""]
    return out


# --- CLI -------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Build a write-ready IR config from keymap.toml.")
    ap.add_argument("-k", "--keymap", type=Path, help="keymap.toml override file")
    ap.add_argument("-b", "--base", help="complete base IR JSON (overrides [meta].base)")
    ap.add_argument("-o", "--out", type=Path, help="output path (default: stdout)")
    ap.add_argument("--dump", type=Path, metavar="CONFIG", help="emit keymap.toml from an IR config")
    ap.add_argument("--full", action="store_true", help="with --dump: emit all positions incl. clears")
    args = ap.parse_args()

    if args.dump:
        text = dump_keymap(json.loads(args.dump.read_text()), full=args.full)
        (args.out.write_text(text) if args.out else sys.stdout.write(text))
        return 0

    if not args.keymap:
        ap.error("either -k/--keymap (build) or --dump is required")
    toml = tomllib.loads(args.keymap.read_text())
    base = _resolve_base(toml, args.base, args.keymap)
    config = build(toml, base, load_preset())
    text = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    (args.out.write_text(text) if args.out else sys.stdout.write(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
