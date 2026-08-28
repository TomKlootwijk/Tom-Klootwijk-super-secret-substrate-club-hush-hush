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

## Browser persistence

Local storage keys are namespaced by `project.metadata.id`. Save data is intended for convenience, not security. Changing the project ID creates a separate storage namespace.

## Debug API

The page exposes `window.KCGame` for inspection and automation. The exact surface is a reference-runtime interface and may grow within compatible 3.9 patch releases. Use F3 for the built-in diagnostics overlay.

## Accessibility and input

The canvas is keyboard focusable, touch gestures are disabled at the browser level for the game area, and touch controls are conditionally shown when touch points are available. Authors should provide readable HUD contrast and avoid action designs that require only one device type.

## Hosting

The single-file output can open from local storage and can be hosted on any static server. No network dependency is introduced by the generated runtime. A restrictive Content Security Policy may require bundle mode or a policy that permits the emitted inline script/style.
