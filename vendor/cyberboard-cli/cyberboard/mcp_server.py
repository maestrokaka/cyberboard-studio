"""MCP server for cyberboard — exposes the CLI's operations as MCP tools.

This wraps the **CLI core**: every tool shells out to `python -m cyberboard.cli`
(the same entry point a human uses) and returns its result, so the MCP surface
never diverges from the CLI's behaviour. No keyboard logic lives here — this is
purely the protocol adapter, matching the project's "CLI is the core; MCP and
skills call it" design.

Run it (after `pip install 'cyberboard-cli[mcp]'`):

    cyberboard-mcp

and point any MCP client (stdio transport) at that command.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    # ImportError (not just ModuleNotFoundError) so an incompatible `mcp`
    # (2.x renamed FastMCP -> MCPServer) is told apart from a missing one.
    # Anything unrelated to the SDK itself (e.g. a broken transitive
    # dependency) is re-raised untouched so its real cause stays visible.
    from importlib import metadata

    _name = exc.name or ""
    if not (_name == "mcp" or _name.startswith("mcp.") or "FastMCP" in str(exc)):
        raise
    try:
        _found = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        raise SystemExit(
            "cyberboard-mcp needs the MCP SDK: pip install 'cyberboard-cli[mcp]'"
        ) from exc
    try:
        _ver = tuple(int(p) for p in _found.split(".")[:2])
    except ValueError:
        _ver = None
    if _ver is not None and (1, 2) <= _ver < (2, 0):
        raise  # a supported mcp: this failure is something else
    raise SystemExit(
        f"cyberboard-mcp needs mcp>=1.2,<2 but found mcp {_found}: "
        "pip install 'mcp>=1.2,<2'"
    ) from exc

mcp = FastMCP("cyberboard")


def _run(args: list[str]) -> dict[str, Any]:
    """Run a cyberboard CLI command and return its result as structured data.

    Uses the current interpreter's `-m cyberboard.cli` so it works whether the
    package is installed as a console script or run from a checkout, and inherits
    whatever optional deps the environment has (a missing one yields the CLI's
    own clean hint in `stderr`, not a crash here).
    """
    proc = subprocess.run(
        [sys.executable, "-m", "cyberboard.cli", *args],
        capture_output=True,
        text=True,
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _run_json(args: list[str], field: str) -> dict[str, Any]:
    """Run a `--json` CLI command and parse stdout into `field` on success."""
    result = _run(args)
    if result["ok"]:
        try:
            result[field] = json.loads(result["stdout"])
        except json.JSONDecodeError as exc:
            result["ok"] = False
            # The CLI exited 0 but its output was unparseable — keep exit_code
            # consistent with ok=False so clients can treat it as a failure.
            result["exit_code"] = result["exit_code"] or 1
            result["error"] = f"could not parse CLI JSON output: {exc}"
    return result


# --- discovery / diagnostics (read-only, safe) ------------------------------


@mcp.tool()
def list_devices() -> dict[str, Any]:
    """List connected CyberBoard devices (port, product id, label)."""
    return _run_json(["devices", "--json"], "devices")


@mcp.tool()
def device_info(port: str = "") -> dict[str, Any]:
    """Show one device's detail (product id, version, pages). Auto-detects if `port` is empty."""
    return _run_json(["device", "info", *( [port] if port else [] ), "--json"], "device")


@mcp.tool()
def doctor() -> dict[str, Any]:
    """Run a non-destructive connectivity health check (writes nothing to the device)."""
    return _run(["doctor"])


@mcp.tool()
def verify(config_path: str) -> dict[str, Any]:
    """Validate an IR config JSON against the schema before writing it."""
    return _run(["verify", config_path])


# --- authoring (pure file -> file; LED tools need the [led] extra) ----------


@mcp.tool()
def build_keymap(out_path: str, keymap_toml: str, base: str = "") -> dict[str, Any]:
    """Build an IR config from a keymap.toml (LED is carried over from `base`)."""
    args = ["build", "-k", keymap_toml, "-o", out_path]
    if base:
        args += ["-b", base]
    return _run(args)


@mcp.tool()
def render_animation(recipe: str, base: str, out_path: str, gif: str = "") -> dict[str, Any]:
    """Render a declarative LED recipe into a base config's slot; optional GIF preview."""
    args = ["anim", "render", "-r", recipe, "-b", base, "-o", out_path]
    if gif:
        args += ["--gif", gif]
    return _run(args)


@mcp.tool()
def preview_animation(recipe: str, out_gif: str, scale: int = 16) -> dict[str, Any]:
    """Render a declarative LED recipe straight to a preview GIF (no base needed)."""
    return _run(["anim", "preview", "-r", recipe, "-o", out_gif, "--scale", str(scale)])


@mcp.tool()
def gif_to_ir(gif: str, base: str, slot: int, out_path: str, resample: str = "nearest") -> dict[str, Any]:
    """Downsample a GIF into a base config's display slot (1/2/3 = pages 5/6/7)."""
    return _run(
        ["led", "gif2ir", "-i", gif, "-b", base, "--slot", str(slot), "-o", out_path, "--resample", resample]
    )


@mcp.tool()
def ir_to_gif(config: str, slot: int, out_gif: str, scale: int = 16) -> dict[str, Any]:
    """Render a config's display slot to an animated GIF for visual inspection."""
    return _run(["led", "ir2gif", "-i", config, "--slot", str(slot), "-o", out_gif, "--scale", str(scale)])


# --- device I/O (read-back is safe; write mutates the board) -----------------


@mcp.tool()
def read_keymap(compare: str = "") -> dict[str, Any]:
    """Read the keymap back from the device.

    Without `compare`, returns the keymap as a structured `key_layer` JSON
    fragment (in the `keymap` field), like the other read-only tools. With
    `compare`, returns the human-readable diff against an IR config in `stdout`
    (the CLI's compare mode prints a diff, not JSON).
    """
    if compare:
        return _run(["read", "keymap", "--compare", compare])
    return _run_json(["read", "keymap", "--json"], "keymap")


@mcp.tool()
def write_config(config_path: str, execute: bool = False) -> dict[str, Any]:
    """Write an IR config to the device. DESTRUCTIVE: replaces the whole config.

    Defaults to a dry run (shows the frame plan, writes nothing). Pass
    `execute=True` to actually write — there is no partial write, so the config
    must be complete (keymap + LED). Run `verify` first.
    """
    args = ["write", config_path]
    if execute:
        args += ["--execute"]
    return _run(args)


def main() -> None:
    """Console-script entry point: serve over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
