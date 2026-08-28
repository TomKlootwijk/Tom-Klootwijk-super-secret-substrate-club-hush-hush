# Migration from KC Two Hands 3.0 to KC Elizabeth 3.9

## Compatibility position

The 3.0 Python modules, examples, shaders, specifications and 117 tests are retained. Existing imports from `ugts_kc3.math3d`, `geometry`, `spatial`, `materials`, `scene`, `hands`, `runtime`, `replay`, `render`, `export` and `diagnostics` continue to work.

## Version changes

- Distribution name: `ugts-kc-elizabeth`.
- Runtime version: `3.9.0`.
- Project schema: `ugts-kc-game-project-3.9`.
- New command entry point: `ugts-kc` or `python -m ugts_kc3`.

## Additive modules

`vector2d`, `collision2d`, `game_input`, `animation`, `tilemap`, `audio`, `game`, `project`, `webexport`, `templates`, `cli` and `version` are new.

## Turning a 3.0 scene into a game project

1. Keep the 3.0 scene/runtime as an authoritative content or editor layer where needed.
2. Create a `VectorLibrary` for 2D render assets or retain 3.0 mesh/export assets for separate workflows.
3. Define device-independent actions in an `InputMap`.
4. Convert playable objects into `EntitySpec` component records.
5. Place entities in a `GameSceneSpec` with explicit rules and initial state.
6. Wrap everything in `GameProject`, validate it and build HTML5 output.
7. Use 3.0 replay/event facilities for higher-level authoring workflows and the 3.9 `GameWorld` snapshot/hash for the 2D game loop.

## Canonical numbers

Project and game-world hashes normalize integral JSON numbers, so `1` and `1.0` have the same canonical identity. This removes hash drift after JSON save/load while preserving non-integral values.

## Legacy evidence

The original validation capture is preserved under `validation/legacy_3_0/`. The original 3.0 report files are retained as historical references in `report/legacy_3_0/`.
