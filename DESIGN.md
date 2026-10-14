# Cyberboard Studio

Desktop lighting studio for macOS and Windows, with restrained charcoal surfaces
and a layout informed by the Linear design language.

The keyboard is the subject. Real calibrated photography occupies the main canvas;
interface chrome uses quiet charcoal surfaces and sparse lavender actions. LED colors
belong to the design data and never to a decorative UI gradient.

## Tokens

Canvas #010102; sidebar #0f1011; panels #141516; hover #18191a.
Hairline #23252a; strong border #34343a; text #f7f8f8;
secondary #8a8f98; tertiary #62666d; primary #5e6ad2;
primary hover #828fff; verified success #27a644.

System SF Pro on macOS and Segoe UI on Windows, 13px body / 12px metadata / 22px page title.
SF Mono or Menlo only for time, frame, hex and device identifiers.
4px spacing unit; 6–8px controls; 12px panels; no atmospheric gradients.
Sidebar 184px, inspector 280px. Native titlebar with real window controls.
Preview/photo keeps its calibrated aspect ratio. Minimum window 1120×760;
prioritize a single-screen workbench at this size and wider desktop windows.
Long content and narrow layouts may scroll within their regions rather than
clipping controls. Narrow inspector becomes 250px.

## Components and behavior

Navigation: six destinations, active lifted surface, descriptive icon and label.
Preview: isolated front keyboard photo, separate top and key LED canvas, frame
scrubber, reference-appearance thumbnail rail and LED rendering controls.
Inspector: compact work parameters edit real brightness, speed and naming,
with a read-only target slot and fixed assignment/sync actions.
Changes require explicit assignment to the selected target's draft before sync.
Slots: three cards below the main preview, showing name, real 40×5 frame, frame
count, pending or last-sync status. Clicking a card selects the assignment target
without loading a different work. A secondary Preview action loads that slot's
content; pending cards offer Undo Draft. Keep advanced actions on the device page.
Single-slot sync uses the selected target's prepared draft. The workbench shows
Sync All only when multiple drafts are pending; untouched slots never join it.
Sync sheet: concrete merged plan before execution; measured transfer progress;
device acknowledgement and keymap verification are separate claims.
AI composer: always visible in the workbench beneath the main preview, beside
the three-slot region on desktop. Keep the editable brief, reference images,
exportable prompt and template variants directly available. Model status is
explicit. No simulated AI service or simulated USB success.

Keyboard focus uses 2px lavender outline. Buttons have at least 32px height.
Reduced motion pauses the player by default and removes ornamental transitions.
Source labels distinguish bundled examples, CLI last-written data and live keymap.
Imported files contribute LED frames only and do not replace keyboard bindings.

## Visual refinement · 2026-10-12

The front whole-keyboard preview uses the enclosure outline to clip the three canvas
layers, removing surroundings and reflection without editing the photograph or
LED data. A flat #111315 stage centers the keyboard and fits its full enclosure
to the available width and height, limiting side whitespace without stretching
or cropping the physical keyboard. All selectable appearances use this clean
front presentation.

Frequently used preview controls are 11–12px, with secondary metadata at 10px.
The inspector retains major group separators rather than drawing a rule under
every control block. Remove the Logo review page, candidate selectors and temporary
sidebar-logo actions; keep the approved formal brand and native application icon.

The formal icon is an orange rounded tile with a white, proportionate keyboard
enclosure, a correctly placed display opening, and the approved cat paw. Only
the paw is rotated 180 degrees; the keyboard and tile keep their orientation.
The same approved raster asset drives the sidebar, macOS ICNS, and Windows ICO.

## Interaction and visual review · 2026-10-14

The workbench center contains the large preview above a lower row with the always
visible AI composer and three-slot region side by side on desktop; allot roughly
60% of this row to AI creation and 40% to slots. The right inspector holds compact
parameters and fixed assignment/sync actions. Keep ordinary preview, creation and
assignment operations in one screen at the 1120×760 desktop minimum and wider.
Long content, added references and narrow windows can use contained scrolling.
Avoid positional nth-of-type styling: groups retain explicit borders.
Common controls use at least 32px targets; ordinary small text uses #858b94 or
lighter on charcoal surfaces. Long names and dual-stream progress may wrap.
Frame labels distinguish top, key LEDs and the common loop when lengths differ.
The common 10–100ms slider sits beside an exact 1–32767ms number input; imported
timings are never silently clamped. AI generation retains its narrower range.

Modal sheets have fixed headings and actions, a scrolling body, contained Tab
focus and return focus on dismissal. Background content is inert while open.
Reduced-motion behavior and the approved product icon remain unchanged.

Support is an optional page below the primary navigation. Use the approved
orange icon and a short, static amber pixel line, with restrained charcoal
surfaces and generous space. The original payment JPEG stays byte-exact; crop
only through CSS and keep a white quiet zone around the QR. Display the author
as Kakà and the contact as maestrokaka@gmail.com. No payment amount, tracking or
automatic transaction belongs in the app. The README ends with the original QR
and playful copy, without an App screenshot or support entries in release notes.

## Model services and official appearances · 2026-10-14

Model configuration supports Kimi Code, Kimi Open Platform, MiniMax and DeepSeek.
Each service keeps its own endpoint, model and system-protected credential.
Selecting a form option does not change the active creative service until saved.
The API Key field starts hidden. An adjacent Show/Hide action reveals the current
typed value or explicitly reads the selected service's saved key, without another
confirmation step. Switching services or leaving model configuration restores the
hidden state; hiding preserves a newly typed draft. Existing system credential
storage remains unchanged.
Show model-specific reference-image support and real credential errors; a failed
or unavailable model-list check must never imply successful generation access.
Creation and library labels identify the actual service while retaining old Kimi works.

The preview has a reference-appearance thumbnail rail on the left of the main
keyboard canvas. Each choice shows a small, background-free front keyboard photo
and a short one-line label such as "R6「Vision」" or "R4「Fluo Free」", omitting
the repeated CYBERBOARD prefix. Use 11px labels and a 160px rail at regular desktop
widths. Keep full names in the catalog and main preview. Clicking a
choice switches the main preview. Use a restrained
lavender border and selected marker for the current choice, with distinct hover
and keyboard-focus states. The rail scrolls independently, keeping all eight
choices reachable; at narrow widths it becomes a horizontally scrolling image
strip. Show the current photo model and source with the main preview. Do not use
a text dropdown for appearance selection. Original photos and official R4/R6 photos retain their
pixels. Offer eight appearances named exactly "CYBERBOARD R6「Vision」",
"CYBERBOARD R4「Fluo Free」", "CYBERBOARD R4「Bebop」", "CYBERBOARD R4「Gangstar」",
"CYBERBOARD R4「Cloud White V2」", "CYBERBOARD R4「Stone Face」",
"CYBERBOARD R4「Paisley」" and "CYBERBOARD R4「Vision」". Keep R4 and R6 Vision
as separate model-specific choices. The R6 appearance uses the user's earliest
front photograph; seven R4 appearances use official site or store images,
including qualified images of sold-out colorways. Each shows the entire keyboard from the
front, clipped along the physical enclosure on the same quiet stage. Do not offer
desk, oblique, scene-background or alternate-framing controls. Opaque keycaps
receive restrained light in the key gaps,
while transparent keycaps retain their transmission treatment. Remember the
selected appearance without changing LED data, slot drafts or connected-device identity.
