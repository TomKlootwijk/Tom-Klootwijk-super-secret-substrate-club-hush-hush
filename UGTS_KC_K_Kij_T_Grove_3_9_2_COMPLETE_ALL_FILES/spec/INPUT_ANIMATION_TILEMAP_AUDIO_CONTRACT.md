# Input, Animation, Tilemap and Audio Contract

## Input

An action has an ID, bindings, deadzone, threshold and optional clamping. A binding identifies a device kind, code, scale and optional device index. Raw input is resolved into an `InputFrame` containing current and previous values. Edge queries use the action threshold.

## Animation

Keyframe times are strictly increasing within a track. A track targets a property path and interpolates scalar or equal-length vector values. Clips define duration and playback mode. Crossfades blend complete sampled property maps. State-machine transitions are evaluated in declared order.

The Mobile 3D adapter is a separate bounded rigid-transform contract. New authoring stores an ordered
`ugts-transform-animation-library-1` under `metadata.transform_animation_library`. A library contains
1–16 clips with unique stable IDs, child-readable labels and one optional autoplay clip ID. A clip ID
matches `[a-z][a-z0-9_.-]{0,31}`; its portable cross-pack identity is unsigned 64-bit FNV-1a over its
ASCII ID. The earlier `metadata.transform_animation` form remains valid and is normalized at runtime
to one `main` / **Main** autoplay clip. The legacy and library metadata keys are mutually exclusive.

Every clip uses the existing `ugts-transform-animation-1` whole-pose contract: each key contains
time, translation offset, relative quaternion, positive scale multiplier and arrival easing. The
first key is at time zero and is the exact relative identity. Playback modes are once, loop and
ping-pong. Easing is one of linear, step, ease-in, ease-out, ease-in-out, smoothstep, smootherstep,
back-out or elastic-out. The Studio timeline exposes all nine with child-readable labels, supports
New/Duplicate/Rename/Delete and one optional autoplay selection, and records authored changes through
Undo/Redo. Selecting or scrubbing a clip and its preview clock are presentation state only.

The adapter rejects dynamic nodes, Player, packed Movement Pattern, Populate Area and nonzero angular
velocity. A project has at most 64 animated nodes, 16 clips per node, 256 clips and 4,096 keys total;
one clip has at most 128 keys and a duration from 1/60 through 120 seconds. Each relative translation
component stays within ±4,096; each scale multiplier stays from 1/1,024 through 64 and remains
positive through any easing overshoot; key times must stay unique after compact normalization.

Before desktop execution or Android packing, duration round-trips through binary32, key times through
an unsigned-16 fraction of duration, and relative translation/quaternion/scale through binary16.
Successive quaternion hemispheres are aligned and sampling uses normalized shortest-path
interpolation. Runtime composition order is packed polar motion, transform animation, visual graphs,
then physics/gameplay. Each animated node owns one small mutable controller: zero or one active clip,
one elapsed clock and one playing flag. Clips and packed keys remain immutable.

Mobile 3D Logic Blocks expose `action.play_animation` and `action.stop_animation`, append-only
`KCVG001` opcodes 26 and 27. Play takes an entity, clip ID and boolean Restart. Restart true—or
selecting a different clip—sets elapsed time to zero and composes the identity first pose; Restart
false resumes the same paused clip. Stop takes an entity and boolean Reset. Reset false pauses at the
current pose and clock; Reset true clears the active clip, zeroes the clock and restores the authored
base pose. A statically known target must have an animation and a statically known Play clip must
exist on it. Dynamically selected entities and clip IDs are checked by the desktop/native runtime and
fail explicitly if the controller or clip is missing.

The optional `transform_animations.kcan` asset keeps `KCAN392\0` magic and a 24-byte header in both
versions. KCAN v1 is the exact legacy ABI: exclusively legacy metadata emits one implicit `main`
autoplay clip per node with one 16-byte node binding and unchanged 24-byte keys. Given unchanged
legacy project data, compilation is byte-for-byte identical to the prior implementation. KCAN v2 is
selected when any placed node uses the library metadata form. It stores one 24-byte binding per clip:
scene-node index, unsigned-64 clip hash, binary32 duration, first-key index, key count, loop mode and
an autoplay flag. Legacy nodes in a mixed v2 asset are encoded as `main` with autoplay set. Bindings
are canonical by `(scene_node_index, clip_hash)`; at most one binding per node may carry autoplay.
Projects without a clip emit no asset. Native readers accept both versions and normalize v1 to the
same controller model.

This adapter now defines named rigid-transform clip libraries and direct graph Play/Stop control,
but it does not define GLB import/animation authoring, skeletal animation/retargeting, crossfades or
layered blending, animation-state-machine authoring, or animated glTF export. The current glTF adapter
remains static. The generic property-animation API above does not silently grant those features to
Mobile 3D or native Android.

## Tilemaps

Tile layers share map dimensions and tile size. A tile definition may mark solidity and movement cost. A* paths operate on in-bounds non-solid cells and return an empty path when the goal is unreachable or an endpoint is blocked. Collision rectangles merge only contiguous compatible solid cells.

## Audio

A sound cue defines oscillator type, frequency/sweep, duration, volume, noise and ADSR envelope. Notes use equal temperament relative to configurable A4. A sequence schedules cue IDs at non-negative beats within a declared length. The Python layer is data/validation only; the HTML5 exporter realizes cues through Web Audio.
