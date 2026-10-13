# Preview assets and offline fixtures

`designs/` contains the three creative lighting works. `photos/` contains the
perspective calibration and physical LED zones for the unchanged photographs
in `web/assets/`. `keymap-layout.json` contains physical geometry and standard
base-layer labels; it contains no captured device identity, firmware, port,
read timestamps or custom Fn-layer assignments.

Run `python scripts/prepare-data.py` from this repository to rebuild
`web/data.js` and `web/assets/keymap-layout.json`. The generated bundle has no
trusted device baseline or synchronization snapshot. Personal device records
remain in the per-user CLI store.

`test-fixtures.cjs` generates a complete synthetic configuration with
`_fixture: true` for offline tests. Its custom LED pages use the creative works,
and its seven key layers repeat standard base labels. It is never loaded by
the App or used to initialize, migrate, or write a real keyboard.
