# Practical Game-Creation Guide

## Project anatomy

A project contains metadata, display settings, an input map, vector assets, an audio bank, optional tilemaps, one or more scenes, a start scene and build settings. The same `project.json` feeds Python validation/simulation and the HTML5 build.

## Vector assets

A `VectorAsset2D` owns a logical size, pivot, named gradients and ordered paths. Paths use `M`, `L`, `Q`, `C` and `Z` commands. Paint can reference a color directly or a named gradient with `@gradient_id`.

```python
from ugts_kc3 import GradientStop, LinearGradient, VectorAsset2D
from ugts_kc3 import VectorPaint, VectorPathBuilder

path = (VectorPathBuilder("ship")
        .move_to(28, 0).line_to(-20, -18)
        .line_to(-8, 0).line_to(-20, 18)
        .close().build(VectorPaint(fill="@hull", stroke="#ffffff")))
asset = VectorAsset2D(
    "ship", (64, 48), (0, 0), (path,),
    (LinearGradient("hull", (-24, -18), (28, 18),
                    (GradientStop(0, "#64e9ff"), GradientStop(1, "#5068ff"))),),
)
```

Use `write_vector_svg` for inspection or `export-svg` for a whole project.

## Input actions

Gameplay consumes logical actions rather than device-specific keys. One action may combine keyboard, gamepad and touch bindings. Axis actions sum signed bindings, apply deadzones and clamp to `[-1, 1]`. Input frames provide `value`, `down`, `pressed`, `released` and normalized two-action vectors.

Recommended base actions are `move_x`, `move_y`, `dash`, `pause`, `restart`, `save`, `load`, `mute` and `debug`.

## Entity composition

Each scene entity has an ID, tags, metadata and component records. Core components include:

- `transform`, `body`, `collider`, `vector_renderer` and `camera`.
- `player_controller`, `health`, `hazard` and `collectible`.
- `bounds_constraint` and `lifetime`.

The browser runtime also recognizes lightweight data-driven presentation/behavior records used by the example: `spin`, `pulse` and `patrol`. Unknown component records remain available to custom Python systems or future exporters rather than being discarded.

## Physics and collision

Bodies are `dynamic`, `kinematic` or `static`. The reference solver handles velocity integration, damping, gravity scale, maximum speed, penetration correction and impulse/friction response. Colliders support AABB, circle and convex polygon shapes. Layers and masks decide whether two colliders interact; sensors emit contacts without physical resolution.

The runtime emits deterministic `collision_enter`, `collision_stay` and `collision_exit` events. Collectibles and hazards are implemented on top of those contacts.

## Custom systems

Register deterministic systems in one of five ordered phases:

```python
world.add_system(my_input_system, phase="input", priority=10)
world.add_system(my_pre_physics, phase="pre_physics")
world.add_system(my_post_physics, phase="post_physics")
world.add_system(my_gameplay, phase="update")
world.add_system(my_camera_or_cleanup, phase="late")
```

Within a priority, system names provide stable ordering. Keep authoritative gameplay state in `world.state` or serializable components when save/replay behavior matters.

## Animation

Animation tracks target property paths such as `transform.rotation` or `vector_renderer.opacity`. Clips support once, loop and ping-pong modes. `AnimationPlayer` supports crossfades; `AnimationStateMachine` selects clips through predicate-driven transitions. Apply samples to nested dictionaries with `apply_animation_sample` or map them into typed components in a custom system.

## Tilemaps and pathfinding

A `TileMap` stores named definitions and layers. It can import compact ASCII layouts, convert between tile/world coordinates, test solid cells, compute A* paths, flood reachable cells and merge adjacent solid cells into larger collision rectangles. This keeps map authoring data-driven without requiring an image atlas.

## Audio

`SoundCue` records oscillator waveform, frequency/sweep, duration, volume, noise and ADSR envelope. `MusicSequence` schedules cue IDs on beats. The browser exporter realizes these records through Web Audio; the Python layer validates and serializes them without requiring an audio device.

## Win/lose and UI rules

The browser runtime reads scene rules such as `player_id`, `score_to_win`, sound IDs, background grid, music and vignette settings. UI text records support placeholders such as `{score}`, `{target}`, `{health}`, `{best}` and `{time}`.

## Saving and deterministic tests

`GameWorld.snapshot`, `save`, `load` and `state_hash` support reproducible headless tests. Save only JSON-compatible custom state. Feed the same project, fixed time step and input frames to compare state hashes.

## Deployment

The single-file build contains project data, runtime JavaScript and CSS. It uses no CDN or external asset. Browser local-file execution is supported for the included demo; hosting the same file on a static server is also valid. Browser storage is scoped by project ID.
