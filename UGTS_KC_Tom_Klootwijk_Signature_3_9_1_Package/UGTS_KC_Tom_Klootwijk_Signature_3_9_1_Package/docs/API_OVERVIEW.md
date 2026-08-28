# KC Elizabeth 3.9 API Overview

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

`blank_vector_game_project`, `elizabeth_vector_quest_project`, `write_template`, `python -m ugts_kc3` and installed command `ugts-kc`.

The package root re-exports the retained KC 3.0 APIs and all 3.9 APIs for concise exploratory use. Production code may prefer module-qualified imports.

## Mobile 3D / Android additions

- `mobile3d`: project/assets/nodes/camera/light/world records, primitives, device profiles,
  adaptive quality and deterministic `GameWorld3D`.
- `templates3d`: blank and Tom Signature Arena projects.
- `androidexport`: KC3D391 compiler/inspector, glTF adapter and native Android source builder.
- CLI: `new-3d`, `validate-3d`, `simulate-3d`, `pack-3d`, `export-gltf3d`, `build-android`.
