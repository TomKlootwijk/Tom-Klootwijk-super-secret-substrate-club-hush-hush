# Elizabeth's Vector Garden

This is the complete editable demonstration for UGTS-KC 3.9 KC Elizabeth.

## Play

Open `dist/index.html` in a modern browser.

- Move: WASD, arrow keys, gamepad left stick or touch joystick.
- Dash: Space, Left Shift, gamepad button 0 or touch dash.
- Pause: P or Escape. Restart: R. Save: K. Load: L. Mute: M. Diagnostics: F3.

## Rebuild

```bash
PYTHONPATH=../../src python -m ugts_kc3 validate project.json
PYTHONPATH=../../src python -m ugts_kc3 build-web project.json dist
PYTHONPATH=../../src python -m ugts_kc3 export-svg project.json assets_svg
```

The browser build is self-contained and uses no network assets.
