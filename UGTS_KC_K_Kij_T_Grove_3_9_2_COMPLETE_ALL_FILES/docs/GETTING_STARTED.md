# Getting Started with KC Elizabeth 3.9

## 1. Requirements

- Python 3.10 or newer for authoring, validation and headless simulation.
- A modern browser for the generated game.
- No third-party Python runtime package is required by the engine itself.

Run commands from the package root with `PYTHONPATH=src`, or install the package into an isolated environment.

## 2. Create a project

```bash
PYTHONPATH=src python -m ugts_kc3 new games/my_game \
  --title "My Vector Game" --author "Your Name" --build
```

This writes:

```text
games/my_game/
  project.json
  README.md
  dist/index.html
```

The output `index.html` is self-contained by default and can be opened directly.

## 3. Use the full demonstration template

```bash
PYTHONPATH=src python -m ugts_kc3 new games/vector_quest \
  --template elizabeth-quest --author "Your Name" --build
```

The same template is checked in under `examples/elizabeth_vector_quest/`.

## 4. Validate edits

```bash
PYTHONPATH=src python -m ugts_kc3 validate games/my_game/project.json
PYTHONPATH=src python -m ugts_kc3 validate games/my_game/project.json --json
```

Validation checks metadata, display settings, input actions, vector assets, audio, scenes, entity component records, start-scene references, vector-asset references, sound references and tilemap references.

## 5. Simulate headlessly

```bash
PYTHONPATH=src python -m ugts_kc3 simulate games/my_game/project.json \
  --steps 600 --move-x 1 --move-y 0 --dash-at 30 --json
```

The summary includes tick, time, entity count, state, event count and deterministic state hash. For programmatic tests, instantiate the `GameProject` and feed exact `InputFrame` sequences to `GameWorld.step`.

## 6. Build for the browser

```bash
# One self-contained HTML file
PYTHONPATH=src python -m ugts_kc3 build-web \
  games/my_game/project.json games/my_game/dist

# Separate JavaScript bundle
PYTHONPATH=src python -m ugts_kc3 build-web \
  games/my_game/project.json games/my_game/dist --bundle
```

The build also writes `project.json`, `README.txt` and `build-report.json` containing hashes and sizes.

## 7. Export vector source assets

```bash
PYTHONPATH=src python -m ugts_kc3 export-svg \
  games/my_game/project.json games/my_game/svg_assets
```

## 8. Run the full test suite

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

See `docs/GAME_CREATION_GUIDE.md` for project structure and gameplay composition.

## Native mobile 3D

```bash
PYTHONPATH=src python -m ugts_kc3 validate-3d   examples/tom_signature_arena_3d/project.json
PYTHONPATH=src python -m ugts_kc3 build-android   examples/tom_signature_arena_3d/project.json   build/UGTSKC391Signature
```

Open the generated directory in Android Studio. See `docs/ANDROID_NATIVE_GUIDE.md`.
