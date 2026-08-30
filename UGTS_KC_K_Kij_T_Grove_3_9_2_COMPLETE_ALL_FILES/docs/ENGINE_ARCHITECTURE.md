# UGTS Grove Engine Architecture

## Product rule

Ease of learning is the first design constraint. Runtime and project size come second. Performance
work is accepted when it preserves predictable behavior and editor clarity. A feature does not enter
the beginner surface merely because the substrate can represent it.

## Data flow

```text
editable project + scene objects + visual graphs + optional parent links/clips/population recipes
                     |
                     v
          validation and deterministic ordering
              /                 |                  \
     desktop ECS play    2D HTML5 graph VM      Mobile 3D compact build data
                                                     |
          KC3D392 + graph bytecode + optional KCHI392/KCAN392/KCSP392/KCPR392/KCRP392
                                                     |
                                    Android C++ / GLES 3 instanced player
```

The editor is not runtime authority. It writes the same records consumed by headless simulation and
export. This keeps projects recoverable and allows every important build step to run without the GUI.

## ECS composition

The 2D runtime uses entities, serializable components, typed queries and ordered system phases. The
desktop 3D oracle exposes the same transform/body/collider/render query and system facade while
retaining its compatible entity records. Visual graphs attach as ordinary systems. Packed polar
motion and bounded transform animation also attach as ordinary pre-physics systems; neither receives
a hidden privileged loop.

Optional desktop 3D components now have one world-owned sparse-pool authority. Each spawned
`EntityState3D.extra_components` is a live dict-compatible `MutableMapping` over those pools, so
ordinary assignment, replacement, deletion and bulk mapping mutators update membership immediately.
`GameWorld3D.compile_query` canonicalizes/deduplicates the requested component set and caches a live
plan; each execution starts from the smallest required sparse pool, preserves lexicographic entity
IDs, and evaluates mutable tags/alive/active at that moment. The virtual `polar_movement` query maps
to `packed_kinematic`, while snapshots, hashes and saved project JSON remain unchanged. This is not
yet a full archetype migration: built-in transform/body/collider/render values remain in the
compatibility record, and tag, spatial, graph-binding and render-batch indexes remain future work.

The Android graph VM operates on sparse graph bindings and explicit `NodeData` components. A portable
`body_physics` module now integrates every live, active dynamic node, applies floor/XZ-bounds response,
and resolves solid pairs in stable object-ID order using the same bounded-radius impulse equations as
the desktop oracle. Logic Blocks run before that generic pass, so an owner-bound **Apply Force** can
move an untagged crate. The touch-controlled Player remains deliberately excluded from generic
integration to avoid double movement, then participates in pair resolution after its legacy controller
runs. Inherited collectible/hazard/goal gameplay is still tag-specific, and Android does not yet emit
desktop-style collision/floor/bounds events or pack generic grounded state. Calling the native side a
complete general ECS or production physics engine would therefore still be inaccurate.

The retained transform hierarchy is another ordinary ECS adapter, not a second entity model. Root
transforms remain owned by their existing systems. A final `late` system captures immutable authored
child-local TRS and composes each attached child into world space after graph, physics and gameplay
writers finish. Child entities remain present in the normal component table for rendering, but this
first slice validates them as display-only so no child collider, tag, graph or transform controller
can observe or overwrite an ambiguous local/world pose.

The Mobile 3D Inspector translates **Off**, **Orbit**, **Spiral Out** and **Spiral In** into this same
component data. It keeps the packed words out of the beginner surface, presents radius, turn-speed and
start-angle controls, and records each edit through Undo/Redo. The control is disabled for dynamic
nodes so the editor cannot create two transform authorities.

## Compact kinematic representation

`PackedKinematicComponent` stores two unsigned 64-bit words:

- pose: 20-bit log radius, 18-bit angle, 14-bit tick and 12-bit heading;
- motion: four signed 16-bit fields for radial/angular velocity and acceleration.

The layout retains the bounded log-radius polar chart from UGTS SCLP 3.6.2 while giving it an explicit game
component contract. Position, Cartesian velocity and Cartesian acceleration use the chart Jacobian
and polar kinematic terms. Clamping and quantization domains are explicit.

`PolarLookupTable` can share 256 binary16 sine, cosine and scaled exponential-radius samples in 1,584
bytes. UGLUT2 stores one shared radius scale so the default `rho_max=12` range remains representable.
Linear interpolation is used for previews and compact deterministic adapters. Direct `sin`, `cos` and
`exp` remain available. The parent GPU evidence found that smaller records were valuable but that the
LUT itself was not universally faster, so selection must be measured on the target GPU.

`UGECS1` stores canonical ECS/project/graph JSON behind a length, CRC-32 and DEFLATE payload. Authored
JSON stays readable; a build can carry the smaller checked form.

Mobile 3D nodes can opt into the same component through metadata. Export emits a sparse optional
`packed_kinematics.kcpk` (`KCPK392`) asset containing only referenced node indices, two 64-bit words
per component and one shared UGLUT2 per profile. Its on-disk component record is exactly 24 bytes:
a 32-bit node index, 16-bit profile index, 16 reserved bits and the two unsigned 64-bit words. The
desktop preview composes the exact binary16-
roundtripped LUT before Ready graphs and advances it as an ordinary priority -100 pre-physics system;
the transform-animation adapter follows at priority -50, then graphs, bodies and gameplay; retained
children compose last. Native C++ keeps the same polar -> transform animation -> graph -> generic
body physics -> gameplay -> hierarchy order. Dynamic nodes are rejected because
two competing transform authorities would be ambiguous. Projects with no packed nodes emit no polar
asset or sparse records.

## Seeded polar display recipes

`polar_population` derives bounded Make Many display members by random access from one real packed
ECS prototype. The runtime stores recipes and prefix ranges, not copied ECS rows, matrices or poses.
Ring, Spiral and Polar Field retain their exact KCPR v1 encoding and golden hashes. **Radial Burst
(loops)** is the first KCPR v2-only preset; with Glow disabled, an asset remains v1 unless at least
one Burst recipe is present. One controlled standalone Burst sidecar is 240 bytes: a 32-byte header,
five 16-byte operator meanings and one 128-byte recipe.

**Glow by distance** is an optional material-field modifier on any of those four patterns, not a new
placement preset. It compiles child-facing Start distance, End distance and strength into a smooth
pulse in the same bounded log-radius chart. Zero Start maps to the profile-clamped explicit core, so
the pipeline never evaluates `log(0)`. Random-access lineage lane 5 supplies a count-independent
12-bit material phase. Glow changes the full content address but deliberately leaves the existing
spatial lineage namespace and placement prefix untouched.

KCPR v3 is selected only when at least one Glow modifier is enabled. Projects without it keep exact
v1/v2 bytes. V3 does not grow the 128-byte recipe record: its final 12 formerly reserved bytes become
binary32 center-rho, inverse half-width and strength. The minimal canonical operator table gains only
the log-radius pulse, seeded material phase and polar material Glow meanings. A mixed v3 asset may
contain unmodified recipes, whose 12-byte tails stay zero. At runtime no per-copy recipe or phase row
is serialized; only GPU-visible polar staging expands from 32 to 36 bytes per instance for one
32-bit attribute whose low 12 bits carry the derived phase.

Native parsing reconstructs the compiled interval and validates it against the profile-clamped core
and `rhoMax` before accepting the recipe. Startup reports KCPR format version, Glow recipe/instance
counts and the 36-byte GPU stride, making later on-device evidence fail closed on the intended path.

Burst derives a local packed radial displacement and compounds it with the prototype anchor through
the profile's log-encoded polar LUT semantics. It is a looping display effect, not a one-shot event
or a source of gameplay entities. The bounded contract allows 512 instances per Burst recipe,
16 Burst recipes and 2,048 Burst instances per project. Editor presentation retains at most 64
generated items globally. Native presentation additionally clips work to the quality tier's
maximum-visible limit and remaining particle budget.

Desktop stopped authoring omits a runtime tick and therefore displays the deterministic midpoint of
the loop. During Play, `EditorDocument` publishes only the real prototype's post-step fixed world
tick to the retained display-item sideband. The viewport updates those same items in place and does
not invent render interpolation. Android instead retains previous/current packed endpoints for its
presentation interpolation. Opcode 30 changes only an ephemeral recipe-visibility bit, leaving the
real prototype alive and visible.

## Visual graphs

Graph records are immutable data with typed flow/data ports, stable canonical hashes and a registry
of executable node definitions. Data dependencies use deterministic topological ordering derived from
the UGTS 4.2 ordering work. Runtime execution is traced and bounded.

Desktop Preview turns that existing runtime trace into a **Logic Trail**. The document keeps immutable
per-graph/per-owner snapshots for the current Preview, and the editor presents their step order,
values, chosen flow and errors in block badges and the **Last Run** list. The Logic tab remains
navigable but read-only during Play; Stop retains the latest trail for inspection. These snapshots are
presentation state, not graph state: they do not set project dirty state, are not serialized, and add
zero bytes to scene, graph, web, glTF or Android output. Starting a new Preview or project clears them.

Authoring context is selection-owned. Selecting a bound 2D entity, Mobile 3D node or World Logic
entry resolves only that owner's graph; the editor never borrows an unrelated project graph as a
fallback. An unbound object receives a transient blank `VisualGraph` that is absent from serialized
project data. Its first meaningful edit stores the graph and owner binding together, and the same
Undo command restores the exact unbound state. Ordered multi-bindings are exposed through an explicit
graph chooser. A Mobile 3D node with `scatter_population` cannot cross that transition: Populate Area
must be removed before the prototype can own a graph.

The vocabulary covers lifecycle/input events, branches, values, arithmetic, comparisons, world
state, components, portable nearest-tag sensing, emitted events, forces, activation and despawn.
It also includes a bounded world-axis radial/angular sensing query.
Arbitrary Python or native code is not embedded in a learner project.

Android exports an optional `visual_graphs.kcvg` (`KCVG001`) asset. Its native VM supports all 30
built-in Mobile 3D blocks: the portable 25-block desktop/web/native subset plus two animation, two
semantic Movement and one Make Many display-control block. This includes sparse node bindings, world bindings, 2D-XZ or 3D-XYZ Apply
Force, and Trigger Enter/Exit. Ready/tick/input/trigger roots, branches, values,
state/components, scalar math/comparisons, bounded event logging, activation and despawn retain the
same step/lifecycle rules as desktop. It still deliberately rejects mapping/nonempty event payloads,
connected event records, unmapped input names and component paths outside the native NodeData
whitelist rather than changing their meaning. Opcode 21 is the append-only **Repeatable Random
Number** value block: World number and Pick number are first canonicalized to binary32, then must be
whole numbers from 0 through 65,535,
Smallest/Largest and the result use binary32, and linked inputs follow the same checks as literals.
It has no clock, tick dependency or mutable random state. A fixed Logic Block namespace and the
existing SplitMix64 compatibility primitives therefore give desktop, browser and native Android the
same result bits for the same four inputs.

Opcode 22 is the append-only **Find Nearby Object** sensing block (`query.nearest_tag`). **Origin**
may use the graph's bound object or name another project object; a world graph must supply an explicit
origin because it has no owner entity. **Tag** is restricted to `player`, `collectible`, `goal`,
`decorative` or `hazard`, and **Radius** is a finite non-negative binary32 value whose boundary is
inclusive. The origin is excluded, as are dead, inactive, untagged or positionless candidates. The
VM returns the nearest remaining object using the shared binary32 distance schedule and breaks an
exact distance tie by UTF-8 object ID, plus `found`, nullable `entity` and nullable `distance`
outputs. Desktop, browser and native implementations share those rules; Mobile 3D itself still has
no browser player.

Opcode 23 is the append-only **When Timer Rings** event root (`event.timer`). Its **Seconds** and
**Repeat** settings are packed literals rather than dynamic ports. Seconds is canonical finite
positive binary32 through 86,400 and defaults to 1; Repeat is boolean and defaults to true. The
period is a whole number of fixed updates, rounded up so a timer never rings early. Each graph
binding owns one active-step counter. World bindings advance with the world, while an inactive or
dead entity owner pauses only that entity binding. Ready and restart reset the counter. A repeating
or one-shot timer emits at most one flow per update and reports binary32 `count`, `remaining` and the
bound `entity`; it does not catch up with a burst. The counter is runtime lifecycle state derived
from active updates—not a serialized clock, suspended graph, continuation or new project-schema
field. Editor authoring/save-load, desktop Preview, retained browser VM, KCVG packing and native C++
share validation and execution fixtures.

Opcode 24 is the append-only **Find Object Ahead** sensing block (`query.nearest_in_cone`). It takes
the same **Origin**, portable **Tag** and inclusive binary32 **Radius** as opcode 22, with identical
self/dead/inactive/position filters, nearest-distance selection, UTF-8 tie-break and
found/entity/distance outputs. Its fourth input is one Vector4: explicit world-axis X/Y/Z plus minimum
cosine in the inclusive range [-1, 1]. The runtime canonicalizes and normalizes any finite nonzero
axis using the specified round-after-each-operation binary32 schedule. Candidate direction divides
each displacement component by `max(distance, f32(1e-6))`, then the rounded dot is compared
inclusively with the saved minimum cosine. This is the source-aligned GSP4 cone: a coincident point
has cosine zero, runtime trigonometry is never used, and Origin rotation and scale are deliberately
irrelevant. The editor writes exact world-axis/width presets, but dynamic Vector4 links remain valid.

Opcode 25 is the append-only **When Message Heard** event root (`event.message`). Its exact portable
message ID is a saved literal rather than a dynamic input; outputs expose source, optional target and
the binding's entity before the flow continues. Existing **Send a Game Message** actions enqueue into
one per-world non-reentrant FIFO. Broadcast delivery visits active entity bindings by canonical scene
index then graph ID and visits world bindings last; targeted delivery reaches the target owner's
bindings plus world bindings. Nested sends are breadth-first, all Ready handlers finish before
Ready-time delivery, and the queue itself is not serialized. Each outer Ready/update/trigger batch
admits at most 64 queued events and 16,384 total initial-handler/message-handler node steps, failing
explicitly with `EventLimit` or `TotalStepLimit`.

Append-only opcodes 28 **Read Movement** (`value.polar_movement`) and 29 **Change Movement**
(`action.set_polar_movement`) are Mobile-3D-only semantic adapters. Their bytecode hardcodes the
virtual `polar_movement` component: each block exposes an entity, one of the seven friendly radius,
angle, facing, turn/growth speed or acceleration fields, and either a numeric fallback or new value.
Reads decode the packed words; writes preserve unrelated pose/motion/tick fields, validate the shared
profile, repack and compose authoritative state immediately. The fixed four-node conformance example
is 239 bytes/eight inputs versus 268 bytes/ten inputs for generic component access, a 29-byte saving
with no `polar_movement` string. Python/native packed-word and transform parity is tested. Browser
export rejects both blocks explicitly because its retained 25-block runtime has no Mobile 3D player.

Append-only opcode 30 **Show or Hide Extra Copies**
(`action.set_polar_population_visible`) targets one authored Make Many prototype through a saved
literal and changes only a dedicated runtime visibility bit. It never deactivates the prototype,
creates generated ECS rows, or mutates recipe bytes, addresses, snapshots or hashes. Native stores
all 64 bounded recipe flags in one `uint64_t`; desktop owns an equivalent ephemeral sidecar outside
the ECS component pools and `world.state`. Ready can hide copies before the first rendered frame,
and a new runtime restores all bits. The common CPU/Direct/LUT loop skips hidden recipes before any
random-access materialization or visible-node accounting.

The Mobile 3D First Steps project contains seven graphs, 27 nodes and seven bindings including four
world bindings. Its World Logic → **Hear the Dash Message** lesson is a real cross-graph path: the
Dash graph sends `player.dashed`, the separate `message_lesson` graph receives it, and World Logic
stores `heard_message=true`.

Trigger areas are non-physical sensor colliders. Desktop and native select the first active player,
perform matching scale-aware sphere/box overlap tests, emit exits before enters in deterministic sensor
order, and dispatch each transition to world graphs plus graphs bound to that sensor. The event roots
expose sensor/player/entity context. Both validation and native tracking cap a project at 4,096 active
sensors; the native VM additionally budgets 256 trigger transitions per fixed step. The beginner
surface is data-backed rather than a runtime shortcut: **+ Trigger Area** creates an ordinary static
sensor node, and **Use as Trigger** edits the selected node's Sphere/Radius or Box/Size X/Y/Z collider.
The same replacement command provides Undo/Redo and normal project save/load.

HTML5 exports for retained 2D projects precompile graph plans too. The browser VM executes the full
current 25-block vocabulary, including Repeatable Random Number, Find Nearby Object, Find Object Ahead,
When Timer Rings, When Message Heard and Trigger Enter/Exit sensor/player context. It preserves
entity/world binding ownership, sorts flow deterministically and enforces a 1,024-step ceiling.
Message outer batches additionally share the portable 64-event and 16,384-total-node-step ceilings.
Browser exports fail at build time for the Mobile-3D-only opcodes 26–30 or any future custom block
without a browser implementation; logic is never silently dropped. There is no browser Mobile 3D
player, so Mobile 3D graph execution and Populate Area currently have desktop/native Android paths,
not browser parity.

## Bounded relative transform clip libraries

`ugts_kc3.animation3d` is the Mobile 3D bridge between editable project metadata, the desktop ECS and
native Android. It deliberately does not expose the generic `ugts_kc3.animation` module's arbitrary
property, crossfade or state-machine surface. One eligible static node may store an ordered
`ugts-transform-animation-library-1` with 1–16 named `ugts-transform-animation-1` clips and zero or
one autoplay choice. Every key is a complete relative translation, quaternion and positive scale
multiplier; time-zero must be the exact identity. Moving, duplicating or saving the node therefore
keeps every clip attached to its authored base pose. The old `metadata.transform_animation` shape is
normalized to an implicit `main` / **Main** autoplay library without changing its saved data.

The bottom Animation dock projects quaternions into child-readable Turn degrees and saves whole-pose
keys. New/duplicate/rename/delete, autoplay, duration, loop mode, key and Arrival changes are atomic
Undo commands. Clip selection, Play, Stop and scrub use a detached full-node viewport overlay, so
preview does not alter the document, dirty state or undo history. Project Play instantiates the
actual quantized ECS controller. The panel, shared data and runtimes expose the same nine modes:
linear, ease-in, ease-out, ease-in-out, smoothstep, smootherstep, back-out, elastic-out and step, each
with a child-readable Arrival label.

`quantize_transform_animation` is the compatibility boundary used before desktop playback and native
packing. Duration round-trips through binary32; each key time becomes an unsigned-16 fraction of
duration; relative translation, hemisphere-aligned quaternion and scale round-trip through binary16.
Quaternion sampling uses the normalized shortest path. Validation also prevents a back/elastic scale
overshoot from crossing zero. The project caps are 64 animated nodes, 16 clips per node, 256 clips,
128 keys per clip, 4,096 total keys and 120 seconds per clip. Dynamic nodes, Player, packed Movement
Pattern, Populate Area and nonzero angular velocity are rejected as conflicting transform owners.

`ugts_kc3.animationpack` emits optional sparse `transform_animations.kcan` data with `KCAN392` magic.
The 24-byte header and 24-byte key stay common. Exclusively legacy metadata selects byte-for-byte
compatible v1 with one 16-byte node binding and implicit `main` autoplay clip. Any library metadata
selects v2 for the whole asset: each 24-byte clip binding adds the stable unsigned-64 FNV-1a clip hash
and autoplay flag, and mixed legacy nodes become `main` autoplay bindings. No clips means no asset.
Python inspection and the native loader reject invalid versions, counts, references, duplicate clip
hashes per node, multiple autoplay flags, reserved fields, nonfinite/range-invalid values, truncation
and trailing bytes.

The desktop component and native runtime keep one mutable controller per animated node over immutable
clip/key data. `action.play_animation` and `action.stop_animation`—append-only KCVG opcodes 26 and
27—select/restart/resume or pause/hold/reset that controller. Native evaluation occurs after packed
polar composition and before visual graphs; inactive/dead clocks still advance but pose composition
is skipped, matching the desktop component.

This is not a general character-animation system. Current glTF export remains static. GLB animation
import, skeletal animation and retargeting, crossfades/layered blending and animation-state-machine
authoring remain future contracts.

## Bounded retained display hierarchy

`Node3DRecord.parent_id` adds an optional parent reference without changing parentless project output:
the key is omitted when unset. `ugts_kc3.hierarchy3d` validates a deterministic parent-before-child
graph and exposes `build_hierarchy3d`, `world_trs_by_id`, `compose_world_trs_3d`,
`local_trs_from_world_3d`, `reparent_node3d` and `remove_node3d_promote_children`. Missing parents,
cycles and depths beyond eight parent edges fail validation. Attaching, detaching and deleting an
ancestor preserve world pose by deriving the replacement local TRS before committing one editor
snapshot.

The TRS contract intentionally refuses shear. Every node that owns children must have positive
uniform authored scale. An animated ancestor is valid only while every saved relative scale keeps its
result uniform and positive. Children are display-only in this slice: they must be non-dynamic,
tagless, use a non-sensor None collider, have zero angular velocity, and own no visual graph, packed
movement, scatter population or transform animation. An unattached root remains an ordinary object
and may move through physics, angular velocity, packed movement, transform animation or graph-authored
transforms when otherwise valid. An attached intermediate parent remains subject to the child rules;
it carries descendants only through its inherited transform.

Graph validation closes the remaining runtime scale hole. `_hierarchy_graph_scale_messages` traces
`action.set_component` ownership/targets that can reach a hierarchy parent. A saved whole `scale`
Vector3 is accepted only when all three values are equal and positive; a complete Transform mapping
may omit scale or provide the same safe vector. Per-axis writes, dynamic values, dynamic targets and
unknown component/field choices fail as `hierarchy.parent_graph_scale` because they cannot prove the
parent will remain composable at every execution.

Studio projects this data directly. The dark Scene Tree nests ordinary attached rows and provides
contextual **Attach to…** / **Detach** actions with disabled explanations for unsafe candidates. A
child's Inspector says **Transform inside …** and edits its saved local values; the viewport and
translation gizmo resolve world TRS, convert the result back to local, and preview the moved node plus
its descendants. Linked Saved Scene rows remain a separate locked group surface and must be unlinked
before ordinary reparenting.

Desktop `TransformHierarchySystem3D` captures child locals, publishes the initial world poses, then
runs at the final `late` priority. `Mobile3DProject.to_scene()` emits parents before children with
local matrices, so static glTF retains its `children` arrays instead of baking the hierarchy flat.

Android leaves established KC3D392 node records alone: child records already contain their local TRS.
`ugts_kc3.hierarchypack` emits optional `hierarchies.kchi` with `KCHI392` magic, a 24-byte versioned
header and sorted 8-byte `(child_index, parent_index)` links. Flat projects return empty bytes and omit
the asset. The native loader captures each linked child's KC3D local TRS, validates references,
canonical ordering, cycles, the eight-edge limit and parent scale, then writes composed world TRS back
to flat `NodeData` after initial component composition, Ready and every fixed-step transform writer.
The renderer therefore needs no separate node ABI.

This is not a general scene-graph or physics hierarchy. It does not provide child collision, trigger,
gameplay-tag, graph-binding or independent-animation semantics, and it does not turn a linked Saved
Scene definition into a retained runtime prefab. `examples/parent_child_hierarchy_3d` is the bounded
acceptance: one moving/spinning root, two children and one grandchild, with deterministic desktop,
KC3D/KCHI and retained-glTF checks.

## Saved Objects and linked Saved Scenes

`ugts_kc3.reusable` provides the first bounded reusable-authoring slice for Mobile 3D. One
`ReusableObject3D` stores a validated `Node3DRecord` under project metadata. Saving the definition
does not expand `project.nodes`; placing it appends one ordinary flat node in deterministic scene
order. Meshes, materials, packed graph definitions and other project resources remain shared.

This makes the deployment boundary simple and auditable. An unused library entry changes the source
project fingerprint but adds no KC3D node and leaves KCVG/KCPK/KCAN/KCSP payload records unchanged. A
placed copy is already flat before Preview or export, so every existing compiler sees the same node
tuple and sidecar indices. No native C++, pack magic, opcode or Android parser changed.

Global resource tables are not reachability-pruned. If a Saved Object is the last authoring consumer
of a mesh, material or graph, that shared resource can still be emitted. The v1 guarantee is no extra
prefab/node/component record for an unplaced definition, not zero dependency bytes.

The v1 safety contract is explicit:

- at most 64 definitions, each containing exactly one mesh-bearing Mobile 3D node;
- deterministic collision-free IDs and the first unoccupied positive X/Z diagonal placement;
- one atomic node-plus-metadata Undo snapshot for save, place and remove;
- position, material binding and physics are independently editable after placement;
- the node/resource references are captured once; later source or placed-node edits do not propagate
  into the definition, and there is no hidden update/rename path;
- graph definitions remain project-global and shared across their bound owners, keeping bytecode
  compact; a literal `entity`/`origin`/`source`/`target` equal to the captured node is rejected in
  favor of owner-relative **This object**;
- Player nodes are rejected because the native runtime selects one player, and nodes with packed
  Movement Patterns are rejected because KCPK stores a world-centred orbit rather than an instance
  origin;
- removing a definition strips its presentation provenance from placed nodes but does not delete
  those nodes.

`ugts_kc3.saved_scene` adds the explicit authoring compiler needed for linked multi-object groups
without adding a retained prefab instance type. A `SavedScene3D` stores a deterministic
root-first tree of parent-local `SavedSceneNode3D` records plus captured relative graphs once. A
`SavedSceneInstance3D` stores only its stable ID, definition ID and one `Transform3DRecord`.

`materialize_saved_scenes(project)` is pure, deterministic and idempotent. It expands placements into
ordinary flat nodes, assigns the instance ID to the root and `<instance>__<local-id>` to children,
remaps internal entity constants and graph bindings, rebases leaf-animation translations, removes
authoring-only keys and returns a new project. Validation, desktop ECS, `to_scene`, packed ECS, KC3D,
KCVG, KCPK, KCSP, KCAN, glTF and Android all consume that same materialized order. Android performs
the expansion once before compiling every sparse sidecar; the build report retains separate
authoring and runtime hashes.

Graphs using only owner-relative values can be shared by every placement. Graphs with internal
`@root` / `@node/<id>` references are cloned and remapped per instance. The materializer never
changes the authoring project. Unlink/bake materializes one placement, strips runtime provenance and
commits one ordinary node/metadata Undo snapshot.

The bounded contract is 64 definitions, 64 nodes per definition, 1,024 definition nodes total, 256
instances and 4,096 materialized nodes. Nested Saved Scenes and the unique Player are rejected.
Because Saved Scene placements still materialize their captured tree to flat ordinary nodes, a
definition parent cannot be dynamic, spin, animate or allow Logic Blocks to write Transform.
Nonuniform parent scale before a rotated child is rejected as unrepresentable shear. Leaf animation
is supported. Definition edit-in-place, per-instance child overrides, prefab-local mutable state,
retained definition-level prefab instances and 2D Saved Scenes remain future work; authors may use
the separate ordinary display hierarchy after unlinking.

## Bounded decorative populations

**Populate Area** is a static render-decoration component, not a gameplay spawner. One ordinary
Mobile 3D node remains the authored prototype and stores one `metadata.scatter_population` recipe:
object count, World number, three-dimensional area size, minimum/maximum scale and optional random
yaw. The first-steps template demonstrates the feature with **Crystal Garden**: one saved crystal and
an 18-object deterministic garden.

Validation keeps the ownership model unambiguous. A prototype must be static, render-active and have
zero linear/angular velocity. It cannot have a collider or Trigger Area, a player/collectible/goal/
hazard gameplay tag, Logic Blocks, or a Movement Pattern. The generated copies are display transforms
only; they never become ECS/gameplay entities with independent collider, graph, movement, input or
state semantics.

Counts are bounded to 2–256 objects per group, including the authored prototype, with at most 64
groups and 1,024 population objects across a project. The optional `scatter_populations.kcsp`
(`KCSP392`) sidecar has one 24-byte header and one fixed 36-byte record per group; projects without a
population emit no sidecar. Each generated index uses a random-access SplitMix64-derived lineage and
binary32 transform schedule. The same prototype id, World number and index therefore produce the same
copy, and raising the count preserves every existing copy as a deterministic prefix.

The population and Repeatable Random Number seed behavior is a local compatibility reimplementation;
no parent-repository source file is vendored into this package. The inspected parent UGTS trees did
not expose an explicit license for their source, so compatibility here must not be read as a license
grant for unrelated parent code.

Adapters keep their different jobs explicit:

- The desktop Scene view shows at most 64 generated copies per group and 256 globally, while reporting
  the full generated count.
- glTF output bakes every generated copy as an explicit render-only node.
- Native C++ validates KCSP, regenerates the same matrices, uploads one matrix buffer per group and
  issues GLES `glDrawElementsInstanced` calls. If a quality tier's visible-node budget is exhausted,
  it draws a deterministic prefix rather than reshuffling the garden.

This narrow native instancing path is not a general visibility system or a measured performance
claim. Placement has no spacing or overlap avoidance, and generated copies currently have no
per-copy frustum culling, occlusion selection or LOD. Dense overlapping recipes can still waste fill
rate and geometry work within the safety caps.

## Owner-device deployment

The editor's **Deploy to Phone** operation is a single bounded pipeline, not three unrelated buttons.
It selects exactly one authorized ADB device before generation and retains that serial through build,
install and launch. Generated files stay under the saved project's
`.ugts-studio/deploy/<project-id>-android` path. The build result is paired with Gradle's
`output-metadata.json`; only its validated, flavor-aware `applicationId` is used to launch
`<applicationId>/android.app.NativeActivity`. Phase-aware completion preserves an already-built APK
when install fails and an already-installed APK when launch fails.

**Check Phone** (`Ctrl+Shift+P`) is a separate bounded observation pipeline. With the deployed game
running and its screen on, the editor profiles it on a worker thread for 30 seconds, leaving editing
responsive. It pins the selected authorized ADB serial, reads SurfaceFlinger frame cadence, process
PSS/RSS, Android thermal status, available GPU/battery temperature and the app's crash buffer.
Studio Output summarizes cadence, PSS, available GPU temperature, crash lines and warnings; CLI JSON
retains the complete available sample. Neither path injects input or changes game/device settings. The
profiler clears only SurfaceFlinger's diagnostic latency history between sample windows.
`profile-android` exposes the
same operation to non-GUI workflows.

## Rendering and the “AAA” boundary

Compact AAA-style presentation means good lighting/material choices, stable frame pacing, adaptive
resolution, careful effects, asset reuse and measured visibility—not enormous source files. Grove
currently provides GLES 3 depth/culling, a scaled framebuffer, post effects, particles, camera shake,
adaptive quality tiers and Poco-specific ARM64 policy.

The desktop Scene view remains a CPU QGraphics authoring renderer. Its optional **Device Look
(reference)** backend does not disguise that boundary: packed motion and Make Many positions still
come from the exact binary16 UGLUT2 CPU path, while a QOpenGLWidget copies the completed viewport and
runs the packaged native Bayer post shader at physical output pixels. The badge explicitly says
`CPU LUT`; Off skips the GL path, and capability/context/shader failures defer safely back to the
raster widget. Because the pass sees the completed authoring image, it also dithers the grid, labels,
and gizmos. Replacing painter geometry with the game's packed instanced GPU path remains separate
work and is required before claiming desktop/native render parity.

Desktop Play does consume live packed prototype state for the bounded Make Many preview. It updates
only the retained global maximum of 64 display items through KCPR random-access lineage, hides them
with a dead or inactive prototype, and rebuilds authored geometry on Stop. No copy becomes an ECS
row. Legacy recipes follow the current packed prototype endpoint. A stopped Radial Burst shows the
loop midpoint; during Play it uses the real post-step fixed world tick and current packed endpoint.
The editor has no render-accumulator alpha, so only Android currently interpolates previous/current
packed poses for presentation.

Glow by distance is evaluated from the packed/interpolated log radius and a lineage-shifted material
angle. Shared LUT calls the existing UGLUT2 direction lookup, Direct evaluates cosine, and CPU
fallback/reference deliberately uses the quantized UGLUT2 result rather than dropping the modifier.
The result is a clamped 0–4 scalar added to lighting as `base colour × field`; it does not change
material alpha. Radial Burst keeps its prototype in one polar draw group and its generated local-
displacement copies in a second group. A copy evaluates the band from its local packed rho before
that pose compounds with the prototype anchor; the real prototype evaluates its own packed rho. This
preserves local-effect composition without reconstructing a Cartesian distance or applying Burst
offset rules to the prototype. Non-Glow batching remains unchanged.

For compatible packed prototypes and generated members, Android Direct mode is the baseline vertex
reconstruction and LUT mode shares one uploaded binary16 profile texture. CPU composition remains
the fallback for unsupported or conflicting ownership. The ordered 8x8 Bayer choice remains a final
presentation pass after scene shading—including Glow by distance—and is not part of polar motion.
A separate build-only Burst
matrix is defined as 32/128/384 instances × CPU/Direct/LUT × Bayer Off/subtle (18 cases):

```powershell
python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
```

The preserved `built_only` run at
`build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de` completed 18/18 cases
in 272 seconds. Every case records a 1,690-byte KCPK, 240-byte KCPR and 32-byte KCRP, with APKs from
1,804,558 to 1,804,566 bytes. No matrix APK has been installed or executed on POCO/Mali; native-host
vectors and ARM64 builds do not establish device shader parity or performance.

The one-click `RUN_POLAR_GLOW_LAB.cmd` route generates the project if absent, then opens a
128-display Burst project with Shared LUT, subtle Bayer and Glow distance 0–4 at strength 1.25. It is
a compact manual acceptance scene, not physical POCO/Mali visual, timing, power or thermal evidence.

The fail-closed 15-case Glow matrix is defined but has not yet been executed or preserved:

```powershell
python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only
```

The Mobile 3D material path is now deliberately **PBR-lite** rather than flat Lambert shading. The
desktop polygon preview and GLES shader share normalized surface/light/view directions, saved
metallic/roughness, a fourth-to-sixteenth-power blended highlight, Schlick-style Fresnel, diffuse,
rim and emissive terms. The zero half-vector boundary is explicit, so an antiparallel light/view does
not throw or invoke undefined GLSL normalization. Android may animate emissive by ±25% as
presentation-only Grove pulse; at pulse zero the saved-material response matches desktop.

This costs no pack expansion. Each KC3D392 material still stores only id followed by 16-byte RGBA,
4-byte metallic, 4-byte roughness, 12-byte emissive and a 1-byte double-sided flag plus 3-byte
padding: 40 fixed value bytes. Material Look names are inferred editor presentation and are never
serialized. Shared authored materials are cloned only when necessary, preserving prototype/population
ownership and making the complete clone/rebind one Undo operation.

OBJ mesh import is now a bounded authoring-to-native-pack path, but Grove does **not** yet provide a
full AAA asset pipeline: GLB/skeletal animation, retargeting, crossfades, texture compression,
streaming LOD, occlusion, general-purpose batching, production physics and a Vulkan renderer remain
work. Populate Area's bounded static GLES instancing is the one narrow exception; it does not close
those broader gaps. Those gaps are tracked rather than hidden behind marketing language.

## Android target

Generated projects pin Gradle 8.13 by wrapper checksum, SDK/target 36, minimum SDK 26, NDK r29 and
CMake 3.22.1. The Poco X7 Pro flavor is ARM64 and selects the Mali-oriented adaptive profile. A
universal flavor retains ARM64, ARMv7 and x86_64 fallback profiles.

Model names and RAM are only hints. The current PBR-lite/opcode-25 Poco APK is locally built and
inspected at `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk`: 1,484,357 bytes, SHA-256
`B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`, package
`org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 / `3.9.2-poco-x7-pro`, minimum SDK 26,
target/compile SDK 36, GLES 3.0, ARM64-only, debug-certificate signed and APK Signature Scheme v2
verified. Its explicit `pbr-lite-op25-debug` copy is byte-identical, and embedded KCVG/KCPK/KCSP
assets hash-match the current source sidecars. The native library links KCAN, and the unanimated
starter emits no KCAN asset. The Poco is absent from ADB, so this `B9B1…` APK has
no install, launch, installed-byte hash match or physical profile claim. The preceding local
`message-op25-debug` / `message-op25-audit-fixed-debug` snapshot remains 1,451,149 bytes / `1003F061…`.

The last physically verified pre-audit opcode-25 APK is preserved at the
`message-op25-pre-audit-debug` path: 1,449,653 bytes with SHA-256
`FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`. Xiaomi `2412DPC0AG` /
`rodin` installed and cold-launched it; the pulled 1,449,653-byte base APK has the same SHA-256. Its
30-second profile measured 120.12 effective FPS, 8.372/10.183/12.641 ms p50/p95/p99, thermal status
0 and no crashes or warnings; the capture is `validation/device/opcode25-message-poco-profile.json`.

The preceding opcode-24 APK is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`, 1,460,361 bytes with SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`.

The preceding opcode-23 APK is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`; it is not the current source
artifact and has no fresh device claim.

An authorized `2412DPC0AG`/`rodin` with Mali-G720 MC7 previously accepted, launched and hash-matched
the preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk`. Its retained 30-second baseline reported
120.23 effective FPS, 10.118 ms p95, thermal status 0 and no crash lines or warnings; a still earlier
APK retains a separate 64.9-second idle baseline. Interaction-heavy/touch, unplugged and
long-duration thermal runs, explicit 60/90 Hz fallbacks and representative lower-tier devices remain
required; neither historical short baseline is a general performance guarantee or opcode-24 device
evidence. Those older results do not replace the opcode-25 physical snapshot or the pending
first post-audit device verification.
