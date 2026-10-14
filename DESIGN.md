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
content scrolls within each pane. Narrow inspector becomes 250px.

## Components and behavior

Navigation: six destinations, active lifted surface, descriptive icon and label.
Preview: real photo, separate top and key LED canvas, frame scrubber, view controls.
Inspector: real draft brightness, speed and target slot. Changes require assignment.
Slot: name, real 40×5 frame, frame count, pending or last-sync status.
Sync sheet: concrete merged plan before execution; measured transfer progress;
device acknowledgement and keymap verification are separate claims.
AI composer: editable brief, exportable prompt and template variants. Model status
is explicit. No simulated AI service or simulated USB success.

Keyboard focus uses 2px lavender outline. Buttons have at least 32px height.
Reduced motion pauses the player by default and removes ornamental transitions.
Source labels distinguish bundled examples, CLI last-written data and live keymap.
Imported files contribute LED frames only and do not replace keyboard bindings.

## Visual refinement · 2026-10-12

The front keyboard close-up uses the enclosure outline to clip the three canvas
layers, removing surroundings and reflection without editing the photograph or
LED data. A flat #111315 stage and 24–32px inset keep the keyboard centered.
Other photo views retain their original scenes.

Frequently used preview controls are 11–12px, with secondary metadata at 10px.
The inspector retains major group separators rather than drawing a rule under
every control block. Brand proposals are distinct editable monochrome SVG marks,
with lavender only as the optional interface treatment. The five-candidate page
allows temporary sidebar previews without replacing the formal brand or Mac icon.

The formal icon is an orange rounded tile with a white, proportionate keyboard
enclosure, a correctly placed display opening, and the approved cat paw. Only
the paw is rotated 180 degrees; the keyboard and tile keep their orientation.
The same approved raster asset drives the sidebar, macOS ICNS, and Windows ICO.
Legacy geometric marks remain temporary previews, not the product identity.

## Interaction and visual review · 2026-10-14

The workbench has two independently scrolling panes. The inspector keeps the
assignment and sync actions in a fixed bottom section at the 1120×760 desktop
minimum. Avoid positional nth-of-type styling: groups retain explicit borders.
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
automatic transaction belongs in the app. The README uses the same support
design and contact information.
