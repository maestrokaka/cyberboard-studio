"""Unified `cyberboard` command — a thin dispatcher over the cb_* tools.

The keyboard logic lives in the standalone `tools/cb_*.py` modules (each a
self-contained script with its own `main()`). This dispatcher unifies them
behind a single `cyberboard <command>` entry point without changing their
behaviour: it puts the tools directory on `sys.path`, lazily imports only
the module the requested command needs (so a missing optional dependency
surfaces as a clean message, not an import error at startup), rewrites
`sys.argv`, and calls that module's `main()`.

Design note (multi-harness): this stays pure Python with no Claude/MCP
specifics. The MCP server and skills call this same core; only their own
UX layers live elsewhere.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

# Optional dependencies some commands pull in (a few only lazily, inside a
# function — e.g. cb_led imports PIL when it actually renders). A missing one
# is translated into a clean install hint instead of a traceback, but only
# when the package is genuinely absent: a ModuleNotFoundError naming one of
# these while it IS installed signals an internal import bug and must surface.
_OPTIONAL_DEPS = {
    "serial": "device I/O needs pyserial:  pip install cyberboard-cli",
    "PIL": "LED rendering needs pillow:    pip install 'cyberboard-cli[led]'",
}

# The cb_* modules sit in ../tools in the repo (editable install), or in
# cyberboard/_tools when shipped in a wheel (force-included by pyproject).
# Adding that dir to sys.path lets us import them and lets their own
# intra-imports (`import cb_protocol`, `import cb_led`, ...) resolve as-is.
# Prefer the bundled copy when present (a wheel install): it is the
# authoritative location and avoids picking up an unrelated site-packages
# top-level `tools/`. In the repo (editable / source), _tools does not
# exist, so we fall back to ../tools.
_PKG_TOOLS = Path(__file__).resolve().parent / "_tools"
_REPO_TOOLS = Path(__file__).resolve().parent.parent / "tools"
_TOOLS = _PKG_TOOLS if _PKG_TOOLS.is_dir() else _REPO_TOOLS

# command -> (module, prepended argv, one-line help). Order is display order.
COMMANDS: dict[str, tuple[str, list[str], str]] = {
    "devices": ("cb_device", ["list"], "list connected CyberBoard devices"),
    "device": ("cb_device", [], "one device's detail (info [PORT])"),
    "doctor": ("cb_doctor", [], "non-destructive connectivity health check"),
    "build": ("cb_build", [], "keymap.toml -> IR config (--dump for IR -> toml)"),
    "verify": ("cb_verify", [], "validate an IR config against the schema"),
    "led": ("cb_led", [], "GIF <-> IR display codec + terminal player (gif2ir / ir2gif / play / recipe)"),
    "anim": ("cb_anim", [], "render declarative LED animations (render / preview / montage)"),
    "compose": ("cb_ledtoml", [], "compose a led.toml manifest (multi-source slots) -> IR"),
    "read": ("cb_read", [], "read config back from the device (keymap)"),
    "keymap": ("cb_keymap", [], "keyboard-shaped keymap grid: show, or edit (TUI, click to reassign)"),
    "write": ("cb_write", [], "write an IR config to the device"),
    "set-time": ("cb_settime", [], "set the device RTC clock"),
    "store": ("cb_store", [], "where per-device configs are saved (path / --selftest)"),
    "get": ("cb_get", [], "show current config in the terminal (live keymap grid + stored LED)"),
    "dump": ("cb_dump", [], "dump current config (live keymap + stored LED) to a file/stdout"),
    "diff": ("cb_diff", [], "diff two configs (snapshot refs or files): keymap + LED frame counts"),
    "history": ("cb_history", [], "list a device's saved snapshots (newest first)"),
    "restore": ("cb_restore", [], "re-write a past snapshot to the device (undo; dry-run by default)"),
    "set": ("cb_set", [], "edit one setting in place: set key <layer> <pos> <val> / set led <slot> <gif|recipe> (dry-run by default)"),
}

# Meta commands handled by the dispatcher itself (not a cb_* tool).
_COMPLETION_HELP = "print a shell completion script (bash/zsh/fish)"

# Second-level actions for the multi-action commands (mirror each tool's own
# subparsers). Used only to enrich shell completion — never for dispatch.
SUBCOMMANDS: dict[str, list[str]] = {
    "device": ["info"],
    "keymap": ["show", "edit"],
    "led": ["gif2ir", "ir2gif", "play", "recipe"],
    "anim": ["render", "preview", "montage"],
    "store": ["path"],
    "set": ["key", "led"],
    "completion": ["bash", "zsh", "fish"],
}


def _optional_dep_hint(cmd: str, exc: ModuleNotFoundError) -> int | None:
    """Clean message + exit code for a missing optional dep, else None.

    Returns None (so the caller re-raises) for any other import error, and
    also when the named package is actually installed — meaning the failure
    is an internal sub-import bug we must not hide behind a "missing dep".
    """
    name = (exc.name or "").split(".")[0]
    hint = _OPTIONAL_DEPS.get(name)
    if hint is None or importlib.util.find_spec(name) is not None:
        return None
    print(f"cyberboard {cmd}: missing dependency {name!r}.\n  {hint}", file=sys.stderr)
    return 1


def _version() -> str:
    # Prefer installed package metadata; fall back to the in-tree __version__
    # (running from the repo, not installed), then a sentinel if even that
    # is unreachable (running cli.py as a loose script).
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("cyberboard-cli")
    except PackageNotFoundError:
        try:
            from cyberboard import __version__

            return __version__
        except ImportError:
            return "0.0.0+local"


def _usage() -> str:
    width = max(len(name) for name in (*COMMANDS, "completion"))
    lines = [
        "cyberboard — configure the AngryMiao CyberBoard R4 without AM Master",
        "",
        "usage: cyberboard <command> [args...]",
        "",
        "commands:",
    ]
    for name, (_, _, help_text) in COMMANDS.items():
        lines.append(f"  {name.ljust(width)}  {help_text}")
    lines += [
        f"  {'completion'.ljust(width)}  {_COMPLETION_HELP}",
        "",
        "run 'cyberboard <command> --help' for command-specific options",
    ]
    return "\n".join(lines)


def _completion(rest: list[str]) -> int:
    """Handle `cyberboard completion <shell>` — print the script to stdout."""
    from cyberboard import completion

    if len(rest) != 1 or rest[0] not in completion.SHELLS:
        print(f"usage: cyberboard completion {{{','.join(completion.SHELLS)}}}",
              file=sys.stderr)
        return 2
    commands = [(name, help_text) for name, (_, _, help_text) in COMMANDS.items()]
    commands.append(("completion", _COMPLETION_HELP))
    print(completion.script(rest[0], commands, SUBCOMMANDS))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_usage())
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"cyberboard {_version()}")
        return 0

    cmd, rest = argv[0], argv[1:]
    if cmd == "completion":
        return _completion(rest)

    entry = COMMANDS.get(cmd)
    if entry is None:
        print(f"cyberboard: unknown command {cmd!r}\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2

    module, prepend, _ = entry
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))

    # A missing optional dep can surface either here (deps imported at module
    # top, e.g. pyserial in cb_device) or later inside main() (deps imported
    # lazily in a function, e.g. PIL in cb_led's render helpers) — handle both.
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        rc = _optional_dep_hint(cmd, exc)
        if rc is None:
            raise
        return rc

    saved = sys.argv
    sys.argv = [f"cyberboard {cmd}", *prepend, *rest]
    try:
        rc = mod.main()
    except ModuleNotFoundError as exc:
        rc = _optional_dep_hint(cmd, exc)
        if rc is None:
            raise
    finally:
        sys.argv = saved
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
