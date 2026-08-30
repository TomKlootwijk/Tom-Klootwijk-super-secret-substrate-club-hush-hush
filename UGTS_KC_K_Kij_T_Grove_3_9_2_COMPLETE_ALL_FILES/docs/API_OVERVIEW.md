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
  adaptive quality and deterministic `GameWorld3D`. `Node3DRecord.parent_id` is optional and omitted
  from serialized parentless nodes. Optional runtime components live in world-owned sparse pools;
  each spawned `EntityState3D.extra_components` is a live dict-compatible `MutableMapping` over
  those pools. `GameWorld3D.compile_query` sorts/deduplicates requested component names into a cached
  `QueryPlan3D` with read-only `QueryPlanDiagnostics3D`: execution chooses the smallest required
  sparse pool, then evaluates tags/alive/active live and returns lexicographically ordered entities.
  Built-in component values remain in the compatibility record, and snapshots/project JSON/state
  hashes are unchanged.
- `hierarchy3d`: bounded retained local/world transform support through `Hierarchy3D`,
  `Hierarchy3DError`, `TransformTRS3D`, `TransformHierarchySystem3D`,
  `MAX_HIERARCHY_DEPTH_3D`, `build_hierarchy3d`, `hierarchy_issues3d`, `world_trs_by_id`,
  `compose_world_trs_3d`, `local_trs_from_world_3d`, `reparent_node3d`,
  `remove_node3d_promote_children` and `attach_transform_hierarchy_3d`. The first slice allows eight
  parent edges and display-only children under positive-uniform-scale parents. Project validation
  emits `hierarchy.parent_graph_scale` for per-axis/dynamic/unprovable parent scale writes and accepts
  only a complete saved uniform-positive scale (or a full Transform value whose scale is absent/safe).
- `hierarchypack`: optional sparse `KCHI392` compilation/inspection through
  `collect_hierarchy_links`, `compile_hierarchy_pack_bytes`, `write_hierarchy_pack` and
  `inspect_hierarchy_pack` (plus the explicit `transform_hierarchy` aliases). The format uses a
  24-byte header and fixed 8-byte KC3D child/parent index records; an unused hierarchy emits no asset.
- `animation3d`: bounded relative Mobile 3D animation through `TransformKey3D`,
  `TransformAnimation3D`, `TransformClip3D`, `TransformAnimationLibrary3D`,
  `TransformAnimationComponent3D`, `animation_clip_hash`, `collect_transform_animation_spec`,
  `quantize_transform_animation`, `sample_transform_animation` and
  `attach_transform_animations_3d`. The adapter supports up to 16 named whole-pose clips and one
  optional autoplay choice per eligible static node, plus play/pause/resume/reset control; it rejects
  conflicting Player/physics/packed-motion/population/spin ownership.
- `animationpack`: optional sparse `KCAN392` compilation/inspection through
  `compile_animation_pack_bytes`, `write_animation_pack` and `inspect_animation_pack`. Exact legacy
  v1 uses a 24-byte header, 16-byte node binding and 24-byte key. Library v2 keeps the header/key ABI
  and uses a 24-byte clip binding with a portable FNV-1a clip hash and autoplay flag. Both use shared
  binary32/binary16/u16-time quantization and nine runtime easing codes.
- `materials`: retained material/color helpers plus deterministic multiply-only `shade_pbr_lite`.
  UGTS Studio's Material Look choices classify and update ordinary `Material3DRecord` values; no
  preset schema field exists and KC3D392 keeps its fixed material payload.
- `templates3d`: phone-ready First Steps, blank and Tom Signature Arena projects. First Steps includes
  the world-bound **Find the Goal** graph (`Player` origin, `goal` tag, 9 m radius, `nearby_goal`
  state result) and **Count the Timer Rings** (a repeating one-second world timer writing
  `timer_rings`), plus **Find the Goal Ahead** (saved 3D Forward world axis, Normal width,
  `goal_ahead` state result) and **Hear the Dash Message** (the Dash graph sends `player.dashed` to
  the separate `message_lesson` world graph, which writes `heard_message=true`). First Steps has
  seven graphs, 27 nodes and seven bindings including four world bindings.
- `visual_graph`: typed graph records, registry, validation and bounded desktop runtime. The current
  Mobile 3D registry contains 30 blocks; the portable desktop/web/native subset remains 25. It
  includes `query.nearest_tag` / **Find Nearby Object** with an explicit origin,
  five portable gameplay tags, inclusive-radius nearest selection, active/alive filtering and a
  deterministic ID tie-break. `query.nearest_in_cone` / **Find Object Ahead** preserves that contract
  and adds a required Vector4 of world-axis X/Y/Z plus minimum cosine. Its finite nonzero axis and
  candidate direction follow the source-aligned binary32 GSP4 schedule; comparison is inclusive,
  runtime trigonometry is absent, and Origin rotation/scale are irrelevant. It also includes
  `event.timer` / **When Timer Rings** with literal-only
  `seconds` (finite positive binary32 through 86,400, default 1) and `repeat` (boolean, default true),
  plus `count`, `remaining` and `entity` outputs. Timer progress is a binding-local active fixed-step
  count reset by Ready/restart; inactive entity ownership pauses that binding while the world runs,
  and no suspended execution state is serialized. `event.message` / **When Message Heard** stores an
  exact portable message name and exposes source, optional target and bound entity. Message sends use
  a non-reentrant FIFO with deterministic target/broadcast routing, breadth-first nesting, a 64-event
  cap and a 16,384-total-node-step outer-batch cap; no queue state is serialized. Mobile 3D adds
  `action.play_animation` / **Play an Animation** and `action.stop_animation` / **Stop an Animation**
  with explicit entity, clip, restart and reset inputs. It also adds `value.polar_movement` /
  **Read Movement** and `action.set_polar_movement` / **Change Movement**. These hardcode the virtual
  `polar_movement` component and expose only an entity, one of its seven friendly fields, and a
  numeric fallback or value. `action.set_polar_population_visible` / **Show or Hide Extra Copies**
  changes only the ephemeral visibility of one authored Make Many recipe's generated display data;
  it does not deactivate the real ECS prototype or rewrite KCPR. All five Mobile 3D-only blocks are
  hidden for 2D projects and rejected explicitly by browser export.
- `graphpack`: compact `KCVG001` graph compilation and inspection; **Find Nearby Object** remains
  append-only opcode 22, **When Timer Rings** is append-only opcode 23, and **Find Object Ahead** is
  append-only opcode 24. **When Message Heard** is append-only opcode 25; **Play Animation** and
  **Stop Animation** are append-only opcodes 26 and 27; **Read Movement** and **Change Movement** are
  append-only opcodes 28 and 29. **Show or Hide Extra Copies** is append-only opcode 30 with a
  literal entity target, Boolean value, no data output and one `out` flow. The movement opcodes share Python/native packed-word and transform
  parity. In the fixed four-node comparison, their KCVG is 239 bytes with eight inputs versus 268
  bytes and ten inputs for generic component blocks, and contains no `polar_movement` string.
  Animation clip strings map to the same unsigned-64 FNV-1a IDs as KCAN v2.
- `packed_kinematics`: compact packed polar pose/motion components, shared log-encoded polar LUTs and
  UGECS1 files.
- `polarpack`: sparse `KCPK392` compiler/inspector for native Mobile3D packed components.
- `polar_population` / `polar_population_pack`: bounded, random-access Ring, Spiral, Polar Field and
  **Radial Burst (loops)** display recipes plus the content-addressed `KCPR392` sidecar.
  `PolarGlowByDistance` is the optional material-field modifier serialized below a recipe as
  `glow_by_distance: {start_distance, end_distance, strength}`. Start zero means the Movement
  profile's clamped explicit core, End must be greater and within that profile, and strength is a
  canonical binary32 value from 0 through 4. `polar_glow_by_distance_operator_parameters`,
  `polar_glow_phase12`, `polar_glow_by_distance_sample` and `polar_population_glow_sample` expose the
  compiled three-lane field, seeded 12-bit phase and quantized-UGLUT2 CPU reference without exposing
  native buffer offsets.

  No-Glow legacy packs remain byte-identical v1 and no-Glow Burst packs remain byte-identical v2.
  A pack uses v3 only when at least one Glow modifier is present; mixed v3 packs may retain other
  recipes with a zero tail. The fixed recipe record remains 128 bytes because v3 reuses the final 12
  reserved bytes for binary32 center-rho, inverse half-width and strength. Enabling Glow changes the
  recipe content address but preserves its spatial lineage namespace and count-stable placement
  prefix. The native staged instance adds one 32-bit integer attribute whose low 12 bits hold the
  derived phase; it is not a serialized per-copy row.

  Burst is a looping display effect whose local packed displacement compounds with the prototype's
  packed anchor using the same log-encoded polar LUT semantics.
  `polar_population_instance(..., fixed_tick=None)` gives the stopped midpoint preview; passing the
  real post-step world tick gives an exact fixed endpoint, with no synthetic interpolation alpha.
  Limits are 512 instances per Burst recipe, 16 Burst recipes and 2,048 Burst instances per project.
- `scatter` / `scatterpack`: validated deterministic decorative population recipes, generated transform
  parity and the sparse `KCSP392` compiler/inspector.
- `reusable`: authoring-only `ReusableObject3D` definitions, canonical metadata parsing, safe capture,
  flat `Node3DRecord` instantiation and source provenance. Definitions do not enter native packs;
  placed nodes use the existing KC3D/KCVG/KCPK/KCAN/KCSP paths.
- `androidexport` / `androidbuild`: KC3D392 compiler/inspector, graph, transform-animation and
  transform-hierarchy packs, retained static glTF adapter,
  native Android source builder, Gradle APK build, owner-device ADB installation and exact-package
  `NativeActivity` launch, plus non-invasive SurfaceFlinger/frame-cadence, process-memory,
  thermal/GPU and crash-buffer profiling through `AndroidProfileResult` and `profile_android_app`.
- The generated Android C++ API includes `body_physics.hpp`: `bodyBoundingRadius`,
  `bodyVerticalExtent`, `integrateDynamicBodies`, `constrainDynamicBodies` and
  `resolveDynamicBodyPairs`. These operate on packed `NodeData`, preserve Player exclusion when
  requested, and provide the generic fixed-step/contact slice used by `Engine` and host acceptance.
- The generated Android C++ API also includes `transform_hierarchy.hpp`.
  `TransformHierarchy::load` validates/captures KCHI child-local transforms and
  `TransformHierarchy::compose` publishes parent-before-child world TRS into ordinary `NodeData`.
- CLI: `editor`, `new-3d`, `validate-3d`, `simulate-3d`, `pack-3d`, `export-gltf3d`,
  `build-android`, `android-devices`, `profile-android`, `pack-ecs`, `unpack-ecs`, `make-polar-lut`.

UGTS Studio's `EditorDocument` resolves Logic Blocks from the selected 2D/3D owner. An unbound object
receives a transient blank authoring context; the first meaningful edit persists and binds it, while
Undo restores the exact unbound state. Multiple authored bindings remain explicit choices, and a
Populate Area prototype cannot create a binding. The document also exposes runtime-only Logic Trail
snapshots for Preview. They are presentation state, not project schema or export API data.

The Make Many sideband retains and updates only the existing global maximum of 64 display items;
it creates no generated ECS rows. Radial Burst authoring omits a tick and therefore previews the
midpoint of the loop. During Play, `make_many_fixed_tick` is transient presentation state sourced
from the prototype's real post-step world tick. Visibility, current packed component, height and
scale come from the real prototype; Stop returns to authored preview. Opcode 30 changes only the
runtime copy-visibility bit, so the real prototype remains visible. When Glow by distance is enabled,
the desktop sideband also evaluates the same lineage-derived phase and quantized UGLUT2 material
field for its retained preview items; it does not promote the field into an ECS component.

On Android, Shared LUT samples the existing UGLUT2 direction for the shifted material angle, Direct
uses cosine, and the ordinary CPU fallback uses the quantized LUT reference. The field is clamped to
0–4 and added during scene lighting as `base colour × field`; material alpha is unchanged and the
existing Bayer pass remains the final presentation step. A Burst Glow recipe uses one draw group for
the real prototype and a separate group for the locally displaced generated copies. Each copy samples
its local packed rho before anchor composition; the prototype samples its own packed rho. Neither path
recomputes a Cartesian distance.

`ugts_kc3.editor.device_look` provides the optional desktop presentation reference:
`native_post_shader_source` reads the packaged Android Bayer shaders,
`shader_source_for_context` changes only their GLSL dialect preamble,
`bayer_reference_rgb` / `bayer_reference_fragment_rgb` lock formula and physical-pixel phase
semantics, and `DeviceLookOpenGLViewport` owns the context-bound copy/post resources. The Scene
viewport exposes a child-readable toggle and always labels this as CPU LUT composition. It is not an
API for native polar GPU rendering or device measurement.

For the selected Mobile 3D node, `EditorDocument.animation_authoring_problem`,
`transform_animation_library_data`, `animation_timeline_clip`, `animation_from_timeline_clip`,
`set_transform_animation_library`, `collision_free_animation_clip_id` and
`animation_preview_state` back the bottom **Animation** dock. Authored library/clip changes enter the
shared Undo stack; selected clip, scrub and playhead state do not. The child panel and shared
data/KCAN/native runtime expose the same nine Arrival modes: linear, ease-in, ease-out, ease-in-out,
smoothstep, smootherstep, back-out, elastic-out and step. The retained
`transform_animation_data`/`set_transform_animation` methods are the one-clip compatibility view.
This API does not add GLB animation import, skeletal animation, crossfades/layered blending or
animation-state-machine authoring.

For Mobile 3D, `EditorDocument.reusable_objects`,
`reusable_object_metadata_snapshot`, `instantiate_reusable_object_record` and
`remove_reusable_object_snapshot` back the child-facing **Saved Objects** controls. Logic Block
resources remain shared; node/material/physics records are ordinary editable copies. The v1 API is a
single-object authoring stamp.

For ordinary Mobile 3D attachments, `EditorDocument.node_hierarchy`, `node_child_ids`,
`reparent_node_snapshot`, `delete_node_snapshot`, `node_world_trs`,
`local_transform_for_world_translation` and `preview_world_trs_after_translation` back the nested
dark Scene Tree, contextual **Attach to…** / **Detach**, local-valued Inspector and world-space
viewport/gizmo. Reparent/delete snapshots preserve world pose and use the shared Undo stack. Linked
Saved Scene rows stay outside this API until unlinked.

`ugts_kc3.saved_scene` supplies the linked group layer through `SavedScene3D`,
`SavedSceneNode3D`, `SavedSceneInstance3D`, `make_saved_scene`, `instantiate_saved_scene`,
`materialize_saved_scenes`, `bake_saved_scene_instance` and the metadata helpers. The editor backs
**Save Together**, **+ Saved Scene…** and **Unlink** with atomic node-plus-metadata snapshots. The
materializer is the single boundary used by validation, desktop ECS and every compiler/exporter; it
returns an ordinary flat `Mobile3DProject` and never mutates the authored links.

The Logic Blocks editor exposes **When Timer Rings** as an Events root with bounded Seconds and
Repeat property controls rather than connectable settings. Save/load and Undo/Redo preserve those
literals, and editor validation agrees with desktop, retained web, graph-pack and native validation.
**Find Object Ahead** remains directly linkable as a Vector4 for advanced graphs, while its child-safe
property editor writes exact Direction and Width presets: 2D insertion starts at world Right (+X),
3D at world Forward (-Z), and Normal uses the binary32 cosine of 45 degrees. These saved values do not
follow later Origin rotation.

The editor exposes **When Message Heard** as an Events root whose **Message** property defaults to
`graph_event` and accepts only portable saved identifiers. Its flow output is followed by Source,
Target and Entity data outputs; the receiver name is deliberately not connectable at runtime.

For a selected Mobile 3D node, the Inspector exposes Matte, Toy Plastic, Metal and Crystal Glow as
presentation-only Material Looks. A shared authored material is cloned and only the selected
prototype is rebound; population copies remain attached to it. The operation is one Undo command
and follows QUndoStack's saved clean index, so save/undo/redo cannot suppress a required save prompt.

The GUI exposes the same phone profiler as **Check Phone** (`Ctrl+Shift+P`): a background 30-second
check of a running deployed game with the screen on. It does not mutate project/game settings or
inject input; it clears only SurfaceFlinger's diagnostic latency history between windows.
