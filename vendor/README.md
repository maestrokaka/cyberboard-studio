Vendored Cyberboard CLI
======================

Source: https://github.com/GeneralD/cyberboard-cli, published version 0.1.2.
License: MIT; the original license is retained in
cyberboard-cli/cyberboard_cli-0.1.2.dist-info/licenses/LICENSE.

This copy contains the previously verified AM01R6 identity compatibility patch,
Windows COM enumeration, cross-platform per-device file locking, Windows
LOCALAPPDATA store selection and platform-aware doctor diagnostics. The original
0.1.2 schema, aliases and bundled MIT pixel font are included. The schema was
restored from the matching v0.1.2 upstream tag because that wheel omitted it.

Only reusable source/metadata/public data are vendored. No user's current.json,
history, baseline, USB identity data, private state, venv or compiled binaries
are included. requirements-cli.txt pins core, LED, schema-check and timezone
dependencies. Optional terminal TUI/MCP dependencies are not required by the GUI.

licenses/pyserial-BSD-3-Clause.txt supplements the pyserial 3.5 wheel, whose source
headers identify its copyright and SPDX license but omit a standalone LICENSE.
