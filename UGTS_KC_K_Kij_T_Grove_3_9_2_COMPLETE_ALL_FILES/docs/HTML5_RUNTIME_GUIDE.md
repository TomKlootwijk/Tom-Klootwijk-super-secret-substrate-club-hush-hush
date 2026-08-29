# HTML5 Runtime Guide

## Build forms

`build_html5(project, output_dir, single_file=True)` writes a self-contained `index.html`. With `single_file=False`, the JavaScript runtime is emitted as `kc-runtime.js` while project data remains embedded in the page.

Every build includes:

- `index.html` - entry point.
- `project.json` - canonical source snapshot.
- `README.txt` - launch and control notes.
- `build-report.json` - runtime/project version, project hash, file hashes and byte counts.
- `kc-runtime.js` - only in bundle mode.

## Runtime services

The generated game includes a fixed-step accumulator, Canvas vector rendering, gradients, transform/camera handling, broad-phase and narrow-phase collision, player controller, hazards, collectibles, particles, procedural audio/music, HUD, keyboard/gamepad/touch input, pause/restart/mute, local save/load, best score and F3 diagnostics.

The retained 2D browser VM executes the full current 25-block vocabulary. **Find Nearby Object** uses
the same explicit/bound origin, five portable tags, inclusive radius, active/alive nearest selection
and deterministic object-ID tie-break as desktop and native opcode 22. This parity covers the graph
operation; there is still no Mobile 3D browser player.

**Find Object Ahead** is append-only native-pack opcode 24 and runs in this retained browser VM too.
Its Vector4 stores world-axis X/Y/Z plus minimum cosine. Browser `Math.fround` follows the shared,
source-aligned GSP4 normalization and candidate-direction schedule before the inclusive cosine gate.
There is no runtime trigonometry; rotating or scaling Origin does not change the saved cone. In 2D,
the editor's Right/Left/Down/Up presets map to +X/-X/+Y/-Y in the canvas's Y-down world.

**When Timer Rings** is append-only opcode 23 in compact native packs and has the same browser
contract. **Seconds** is a literal finite positive binary32 value through 86,400 (default 1), and
**Repeat** is a literal boolean (default true). Every browser graph binding counts its own active
fixed updates. An inactive entity pauses that binding while the world keeps updating; Ready and game
restart reset it. The block rings at most once per update and exposes count, remaining fixed-step
seconds and bound entity. Browser save data does not serialize a timer clock or suspended graph, so a
restart begins the timer lifecycle again. Headless parity fixtures cover desktop, browser, KCVG and
native Android behavior.

**When Message Heard** is append-only opcode 25 and follows the same portable message contract. Its
saved receiver name is an exact short ID; Source, optional Target and bound Entity are data outputs.
**Send a Game Message** enters one non-reentrant FIFO. Broadcasts visit active entity bindings in
canonical scene/graph order before world bindings, targeted sends reach the target owner's bindings
plus world bindings, and nested sends wait breadth-first. Ready handlers all finish before Ready-time
messages drain. The browser rejects the 65th queued event with `EventLimit` and caps the whole outer
batch at 16,384 initial-handler/message-handler node steps with `TotalStepLimit`; no queue is saved.

## Browser persistence

Local storage keys are namespaced by `project.metadata.id`. Save data is intended for convenience, not security. Changing the project ID creates a separate storage namespace.

## Debug API

The page exposes `window.KCGame` for inspection and automation. The exact surface is a reference-runtime interface and may grow within compatible 3.9 patch releases. Use F3 for the built-in diagnostics overlay.

## Accessibility and input

The canvas is keyboard focusable, touch gestures are disabled at the browser level for the game area, and touch controls are conditionally shown when touch points are available. Authors should provide readable HUD contrast and avoid action designs that require only one device type.

## Hosting

The single-file output can open from local storage and can be hosted on any static server. No network dependency is introduced by the generated runtime. A restrictive Content Security Policy may require bundle mode or a policy that permits the emitted inline script/style.
