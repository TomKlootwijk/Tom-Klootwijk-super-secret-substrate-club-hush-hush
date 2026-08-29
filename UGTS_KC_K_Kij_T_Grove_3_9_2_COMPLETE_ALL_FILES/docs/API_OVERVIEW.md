# UGTS-KC Grove 3.9.2 API Overview

## Vector authoring - `ugts_kc3.vector2d`

`GradientStop`, `LinearGradient`, `RadialGradient`, `VectorPaint`, `PathCommand`, `VectorPathBuilder`, `VectorPath`, `VectorAsset2D`, `VectorLibrary`, `polygon_path`, `rectangle_asset`, `circle_asset`, `star_asset`, `vector_asset_to_svg`, `write_vector_svg` and `write_vector_library_json`.

## Collision - `ugts_kc3.collision2d`

`AABB2`, `Circle2`, `ConvexPolygon2`, `CollisionFilter`, `CollisionManifold`, `SweepHit`, `SpatialHash2D`, vector helpers, `shape_bounds`, `shape_from_dict`, `translate_shape`, `collide`, `sweep_aabb` and `resolve_velocity`.

## Input - `ugts_kc3.game_input`

`InputBinding`, `ActionDefinition`, `RawInputState`, `InputFrame`, `InputMap` and `InputRecorder`.

## Animation - `ugts_kc3.animation`

`Keyframe`, `AnimationTrack`, `AnimationClip`, `AnimationPlayer`, `AnimationTransition`, `AnimationStateMachine`, `easing`, `interpolate`, `blend_samples` and `apply_animation_sample`.

## Tilemaps - `ugts_kc3.tilemap`

`TileDefinition`, `TileLayer` and `TileMap` with ASCII import, world/grid conversion, solidity, A*, flood reachability and collision-box merging.

## Audio - `ugts_kc3.audio`

`Envelope`, `SoundCue`, `SequenceNote`, `MusicSequence`, `AudioBank` and `note_frequency`.

## Game runtime - `ugts_kc3.game`

Core components: `Transform2D`, `Body2D`, `Collider2D`, `VectorRenderer2D`, `Camera2D`, `Lifetime2D`, `Health2D`, `BoundsConstraint2D`, `PlayerController2D`, `Collectible2D`, `Hazard2D`.

Runtime records and services: `GameEvent`, `GameEntity`, `GameWorld`, `component_name`, `component_to_dict`, `component_from_dict`.

## Projects - `ugts_kc3.project`

`ProjectMetadata`, `DisplaySettings`, `EntitySpec`, `GameSceneSpec`, `ProjectIssue`, `ProjectValidationReport` and `GameProject`.

## Browser output - `ugts_kc3.webexport`

`Html5BuildResult` and `build_html5`.

## Templates and CLI

`first_steps_project`, `blank_vector_game_project`, `elizabeth_vector_quest_project`, `write_template`, `python -m ugts_kc3` and installed command `ugts-kc`.

The package root re-exports the retained KC 3.0 APIs and all 3.9 APIs for concise exploratory use. Production code may prefer module-qualified imports.

## Mobile 3D / Android additions

- `mobile3d`: project/assets/nodes/camera/light/world records, primitives, device profiles,
  adaptive quality and deterministic `GameWorld3D`.
- `templates3d`: phone-ready First Steps, blank and Tom Signature Arena projects. First Steps includes
  the world-bound **Find the Goal** graph (`Player` origin, `goal` tag, 9 m radius, `nearby_goal`
  state result) and **Count the Timer Rings** (a repeating one-second world timer writing
  `timer_rings`), plus **Find the Goal Ahead** (saved 3D Forward world axis, Normal width,
  `goal_ahead` state result).
- `visual_graph`: typed graph records, registry, validation and bounded desktop runtime. The current
  24-block registry includes `query.nearest_tag` / **Find Nearby Object** with an explicit origin,
  five portable gameplay tags, inclusive-radius nearest selection, active/alive filtering and a
  deterministic ID tie-break. `query.nearest_in_cone` / **Find Object Ahead** preserves that contract
  and adds a required Vector4 of world-axis X/Y/Z plus minimum cosine. Its finite nonzero axis and
  candidate direction follow the source-aligned binary32 GSP4 schedule; comparison is inclusive,
  runtime trigonometry is absent, and Origin rotation/scale are irrelevant. It also includes
  `event.timer` / **When Timer Rings** with literal-only
  `seconds` (finite positive binary32 through 86,400, default 1) and `repeat` (boolean, default true),
  plus `count`, `remaining` and `entity` outputs. Timer progress is a binding-local active fixed-step
  count reset by Ready/restart; inactive entity ownership pauses that binding while the world runs,
  and no suspended execution state is serialized.
- `graphpack`: compact `KCVG001` graph compilation and inspection; **Find Nearby Object** remains
  append-only opcode 22, **When Timer Rings** is append-only opcode 23, and **Find Object Ahead** is
  append-only opcode 24. All follow the same deterministic contracts in the native VM; a timer emits
  at most one ring per update.
- `packed_kinematics`: compact log-polar pose/motion components, shared LUTs and UGECS1 files.
- `polarpack`: sparse `KCPK392` compiler/inspector for native Mobile3D packed components.
- `scatter` / `scatterpack`: validated deterministic decorative population recipes, generated transform
  parity and the sparse `KCSP392` compiler/inspector.
- `androidexport` / `androidbuild`: KC3D392 compiler/inspector, graph pack, glTF adapter,
  native Android source builder, Gradle APK build, owner-device ADB installation and exact-package
  `NativeActivity` launch, plus non-invasive SurfaceFlinger/frame-cadence, process-memory,
  thermal/GPU and crash-buffer profiling through `AndroidProfileResult` and `profile_android_app`.
- CLI: `editor`, `new-3d`, `validate-3d`, `simulate-3d`, `pack-3d`, `export-gltf3d`,
  `build-android`, `android-devices`, `profile-android`, `pack-ecs`, `unpack-ecs`, `make-polar-lut`.

UGTS Studio's `EditorDocument` resolves Logic Blocks from the selected 2D/3D owner. An unbound object
receives a transient blank authoring context; the first meaningful edit persists and binds it, while
Undo restores the exact unbound state. Multiple authored bindings remain explicit choices, and a
Populate Area prototype cannot create a binding. The document also exposes runtime-only Logic Trail
snapshots for Preview. They are presentation state, not project schema or export API data.

The Logic Blocks editor exposes **When Timer Rings** as an Events root with bounded Seconds and
Repeat property controls rather than connectable settings. Save/load and Undo/Redo preserve those
literals, and editor validation agrees with desktop, retained web, graph-pack and native validation.
**Find Object Ahead** remains directly linkable as a Vector4 for advanced graphs, while its child-safe
property editor writes exact Direction and Width presets: 2D insertion starts at world Right (+X),
3D at world Forward (-Z), and Normal uses the binary32 cosine of 45 degrees. These saved values do not
follow later Origin rotation.

The GUI exposes the same phone profiler as **Check Phone** (`Ctrl+Shift+P`): a background 30-second
check of a running deployed game with the screen on. It does not mutate project/game settings or
inject input; it clears only SurfaceFlinger's diagnostic latency history between windows.
