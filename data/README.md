# Preview assets and offline fixtures

`designs/` contains the three creative lighting works. `photos/` contains the
active front-view calibration, appearance catalog and physical LED zones for
the unchanged photographs in `web/assets/`. The runtime catalog has eight
front views: R6 Vision and seven R4 colorways, including R4 Vision. Cropping
and background removal happen in the preview renderer; the source image
pixels remain unchanged. Official provenance and search coverage are recorded
in `photos/official-photo-sources.json`.

`photos/source-archive/` and `photos/excluded-photo-calibration.json` retain
public source material and calibration for excluded angles. They are used by
source-fidelity checks and the provenance manifest, not loaded into the App
gallery or generated `web/data.js`. The archived desk photograph was previously
the public `web/assets/desk.jpg`; personal recordings, demo videos and private
reference-image sessions are not part of this directory.

`keymap-layout.json` contains physical geometry and standard
base-layer labels; it contains no captured device identity, firmware, port,
read timestamps or custom Fn-layer assignments.

Run `python scripts/prepare-data.py` from this repository to rebuild
`web/data.js` and `web/assets/keymap-layout.json`. The generated bundle has no
trusted device baseline or synchronization snapshot. Personal device records
remain in the per-user CLI store.

`builtin-default-pages.json` contains only pages 0–4 from the official DIY
CYBERBOARD template, with the public JavaScript URL, source SHA-256 and extracted
page checksum. It contains no keymap, private record or custom lighting slots.
The generic standard enables battery, mosaic and clock, while keeping text
and streaming modes disabled; it is not a captured factory configuration for
a particular keyboard. `prepare-data.py` copies it
byte-for-byte to `web/assets/` for the device-mode recovery and first setup.
Recovery applies only explicitly selected builtin pages after configuration
loading and plan review. A new first setup initializes the full configuration
with current readable keycodes and explicitly selected custom-slot drafts;
it cannot preserve or back up unknown old LED pixels.

`test-fixtures.cjs` generates a complete synthetic configuration with
`_fixture: true` for offline tests. Its custom LED pages use the creative works,
and its seven key layers repeat standard base labels. It is never loaded by
the App or used to initialize, migrate, or write a real keyboard.
