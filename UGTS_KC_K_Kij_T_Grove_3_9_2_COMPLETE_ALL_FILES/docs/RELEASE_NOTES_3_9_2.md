# Release Notes — 3.9.2

**K-Kij-T / Grove**

3.9.2 is an additive creation-engine upgrade of 3.9.1 focused on a learnable desktop workflow and a
compact Mali-G720 MC7 Android result. It adds UGTS Studio, typed Logic Blocks, ECS composition,
log-polar packed kinematics, direct Poco APK tooling, the Grove juice controller, GLES post composite,
shockwave/flash/bloom response, device tuning and KC3D392 assets.

The beginner editor supports undoable object creation, copying, deletion and existing picture,
shape and material assignment, plus bounded undoable Wavefront OBJ import. Logic-block creation is
re-entrancy safe and finite properties use contextual child-facing choices. Logic Blocks now follows
the selected 2D/3D owner: an unbound object shows a blank graph, its first meaningful edit creates and
binds it in one undoable operation, and an intentional multi-binding exposes an exact chooser.
Undo restores the unbound state, while Populate Area prototypes are refused as graph owners. A
one-click Windows launcher and a prominent ADB **Deploy to Phone** action remove command-line steps.

Mobile 3D **Saved Objects** add the first reusable-authoring slice. **Save Object** captures one safe
flat node, **+ Saved Object…** appends an ordinary deterministic ECS copy, and **Remove Saved…**
removes the library entry while preserving placed objects. Definitions remain authoring metadata and
add no native record until placed. Resources and Logic Block bytecode stay shared; placement/look/
physics can differ. The snapshot does not follow later edits. Player nodes, world-centred Movement
Patterns, Populate Area recipes and literal self-target graph properties are rejected with
child-readable explanations.

Linked multi-object **Saved Scenes** build on that boundary without changing native pack ABIs.
Ctrl-selected static objects can be saved together, placed as one linked transform and unlinked into
ordinary nodes with atomic Undo/Redo. Definitions store parent-local ECS snapshots/graphs once;
instances store only ID, definition and group transform. A pure deterministic compiler flattens the
links before desktop runtime, KC3D and every sparse Android sidecar assign indices. Static parent
anchors and leaf Animation are supported; nested scenes, runtime-moving parents, live definition
editing and per-instance child overrides are not claimed.

Ordinary Mobile 3D nodes now have a separate retained display-transform hierarchy. Right-click a row
in the dark Scene Tree and choose **Attach to…** or **Detach**. Rows nest immediately, world pose is
preserved, and the whole operation is one Undo/Redo edit. Attached objects show **Transform inside
…** in the Inspector because their saved Position/Turn/Size are parent-local; the viewport and
translation gizmo still operate in world space.

The hierarchy accepts no missing parent, loop or chain deeper than eight parent edges. An attached
child is deliberately a display object: Dynamic is off, Collision is None and non-sensor, tags and
spin are empty, and Logic Blocks, Movement Pattern, Populate Area and Transform Animation are absent.
An unattached root may still move through otherwise-valid physics, spin, packed movement, animation
or graph transforms, and its descendants follow; an attached intermediate parent moves only through
its inherited transform. A parent with children must keep a positive uniform scale, including through
any parent animation or graph change, so the runtime never silently approximates shear.
`hierarchy.parent_graph_scale` rejects a per-axis, runtime-selected or otherwise unprovable Logic
Block scale write to a hierarchy parent; a complete saved uniform-positive XYZ vector remains valid.

Desktop ECS recomposes children in its final late phase. Android keeps KC3D node records unchanged
and emits optional `hierarchies.kchi` (`KCHI392`): a 24-byte header plus one 8-byte child/parent index
link, with no file for a flat project. Native C++ captures child-local KC3D transforms and publishes
world transforms after Ready and fixed-step transform writers. Static glTF retains the same children.
`examples/parent_child_hierarchy_3d` verifies a moving/spinning carrier, two children, one grandchild,
desktop following, a three-link 48-byte KCHI and retained glTF. Its ARM64/GLES 3 APK is
`build/UGTS-Parent-Child-Hierarchy-3.9.2-Poco-X7-Pro-debug.apk`: 1,565,171 bytes, SHA-256
`813D290E2B89973FE4C429BF58FAD7F50BFB156C42EACB665A7ABB1B4BF36E20`, v2 debug-signed and 16 KiB
aligned. Authorized `2412DPC0AG` / `rodin_eea` installed it and cold-launched status OK in 448 ms;
PID 25992 became resumed/visible/fullscreen and runtime logs selected Mali-G720 MC7 with the Poco
profile. A bounded 15-second/five-sample capture observed 630 intervals at 120.15 effective FPS,
8.376/9.959/10.473 ms p50/p95/p99, thermal status 0 and no crashes/warnings. The five-node/~60-
triangle scene is not a hierarchy interaction, large-game/AAA or sustained-thermal benchmark.

Native Android now advances ordinary dynamic Mobile 3D objects, not only the tagged Player. A
portable body module runs after Logic Blocks, applies gravity/fixed-step translation, floor and X/Z
bounds response, then resolves non-sensor solid pairs in deterministic object-ID order. The
`dynamic_crate_parity_3d` example binds **When Game Starts → Push an Object** to an untagged crate;
the C++ host acceptance consumes its generated KC3D/KCVG and reaches exact X `1.375` after 600 steps.
Player intentionally stays on its existing touch controller, and native contact events/grounded state
are not part of this slice.

UGTS Studio now opens in an unmistakable near-black/navy viewport-first theme. Scene Tree and
Resources share the left tab strip, Output and Animation stay closed until needed, Logic Blocks can
take the full right side, and the compact toolbar keeps Play, Stop, Build and Deploy visible at
smaller desktop widths.
Deploy now pins the
sole authorized device, builds below `.ugts-studio/deploy`, installs, reads Gradle's exact flavor-aware
`applicationId`, and opens `android.app.NativeActivity` on that same device. Its messages distinguish
build, install and launch failures. On Android, touch roles are tracked by pointer ID so a left
movement thumb and right dash/look thumb work together without being swapped by pointer ordering.

Mobile 3D Appearance also offers four child-facing **Material Look** choices: Matte, Toy Plastic,
Metal and Crystal Glow. They preserve colour and double-sided state. A shared authored material is
cloned only for the selected prototype, whose Populate Area copies continue to use it; the complete
change is one save-safe Undo command. Looks are inferred from normal material values, so no preset
field or extra KC3D392 byte is exported. Desktop Preview and GLES now use a compact multiply-only
PBR-lite response; native emissive pulse remains presentation-only Grove juice.

The bottom **Animation** dock now gives each eligible static Mobile 3D node a bounded library of up to
16 named transform clips. Children use New, Duplicate, Rename and Delete Clip, choose zero or one clip
to play when the game starts, author complete relative Position/Turn/Size poses, scrub without
mutating the project, preview a selected clip, and choose Once, Repeat or Back and forth. Library,
length, repeat, whole-pose key and Arrival changes are atomic Undo/Redo commands. The panel and shared
runtime expose the same nine easing codes with child-readable Arrival names. Every clip's time-zero
key is a protected relative identity, so moving, duplicating or saving the object keeps its motion
attached to the object's base pose.

Mobile 3D Logic Blocks add **Play an Animation** and **Stop an Animation**. Play chooses this or
another animated object, a named clip and whether to restart; Restart off resumes the same paused
clip. Stop either holds the current pose/clock or resets to the authored pose. Literal targets and
clip choices are checked before play/export, while graph-selected runtime values report a precise
missing-controller or missing-clip issue.

Desktop Play quantizes every clip through the same binary32 duration, unsigned-16 normalized times
and binary16 relative transforms used by Android. Projects using only old
`metadata.transform_animation` retain byte-for-byte **KCAN v1**: a 24-byte header, one 16-byte node
binding, unchanged 24-byte whole-pose keys and one implicit `main` autoplay clip. New
`metadata.transform_animation_library` data selects **KCAN v2** for the complete asset. Its header
and keys are unchanged; each 24-byte clip binding adds the stable unsigned-64 FNV-1a clip hash and
autoplay flag. Mixed legacy nodes become `main` autoplay bindings. Native C++ composes packed polar,
then animation, then graphs, generic bodies and gameplay, with shortest-path normalized quaternion
interpolation.
Dynamic objects, Player, Movement Pattern, Populate Area and spin velocity are rejected as
conflicting transform owners.

This is rigid-transform multi-clip and direct Play/Stop control, not a full character-animation
system. Current glTF remains static; GLB animation import, skeletal animation/retargeting,
crossfades/layered blending and animation-state-machine authoring remain future work.

With a deployed game already running and the screen on, GUI **Check Phone** (`Ctrl+Shift+P`) performs
a nonblocking 30-second ADB observation. It reports SurfaceFlinger frame cadence, process PSS,
GPU temperature when Android exposes it and app crash-buffer warnings without injecting input or
changing project/game/device settings. The CLI exposes the same bounded operation as
`profile-android` and retains additional available RSS/battery/thermal fields in JSON; only
SurfaceFlinger's diagnostic latency history is cleared between windows.

The Mobile 3D Inspector adds child-readable **Off**, **Orbit**, **Spiral Out** and **Spiral In** movement
presets with radius, turn speed and start angle controls. The generated ECS data remains compact: two
unsigned 64-bit log-polar words per mover, a shared binary16 UGLUT2 per profile, and one exact 24-byte
sparse Android record per moving node. Dynamic nodes are guarded because their transforms belong to
physics.

KCVG001 now carries sparse world graphs as well as entity graphs, and desktop, retained HTML5 and
native Android execute the full current 25-block vocabulary. Append-only opcode 21 is **Repeatable
Random Number**. Opcode 22 is **Find Nearby Object**, a Sensing block that starts from an explicit
or bound origin, accepts only Player/Collectible/Goal/Decorative/Hazard, uses an inclusive radius,
filters the origin plus dead/inactive candidates, selects the nearest match and breaks an exact tie
by deterministic object ID.

Append-only opcode 23 is the child-facing **When Timer Rings** event. **Seconds** is saved directly on
the block as a finite positive binary32 value through 86,400 and defaults to 1; **Repeat** is a saved
boolean and defaults to true. A binding advances only on its own active fixed updates, so disabling
an entity pauses its timer without pausing the world. Ready or restart resets the binding counter.
Each update can produce at most one ring, with count, remaining fixed-step seconds and bound-entity
outputs; there is no serialized clock, suspended graph or catch-up burst. The editor controls,
desktop Preview, retained HTML5 VM, compact pack and native Android VM share these rules. Sensor
entry/exit has matching desktop/native sphere/box overlap,
non-physical transitions, sensor/player/entity graph context, world-or-matching-sensor dispatch and
explicit sensor/dispatch caps.

Append-only opcode 24 is **Find Object Ahead**. It preserves opcode 22's tag/radius filters, nearest
selection, UTF-8 tie-break and nullable outputs, then applies an inclusive source-aligned binary32
GSP4 cone. One Vector4 stores explicit world-axis X/Y/Z plus minimum cosine. Runtime normalization
uses no trigonometry, and Origin rotation and scale are deliberately irrelevant.

Append-only opcode 25 is the child-facing **When Message Heard** event. Its exact portable message
name is saved on the receiver block; outputs expose source, optional target and bound entity. Existing
**Send a Game Message** actions enter one non-reentrant FIFO. Broadcasts visit active entity bindings
by canonical scene index then graph ID and world bindings last; targeted sends reach the target owner
plus world logic. Nested sends are breadth-first. Ready handlers finish before delivery, and explicit
64-event / 16,384-total-step limits stop cascades. No payload or queue is serialized.

Desktop Preview now exposes a read-only Logic Trail. Numbered block badges and the Last Run list show
execution order, values, chosen flow and errors without mutating or serializing the project; the latest
trail remains visible after Stop and adds zero export bytes.

The child-facing Trigger Area3D workflow is included: **+ Trigger Area** adds a ready-made sensor, and
the Inspector's **Use as Trigger** control offers Sphere/Radius or Box/Size X/Y/Z. The Scene Tree and
Resources panel identify Trigger Areas, and edits support Undo/Redo and save/load.

Grove's phone player is native C++/GLES rather than an HTML wrapper. The retained 2D project model
still exports HTML5, and its bounded browser VM executes the same current 25-block vocabulary,
including Repeatable Random Number, Find Nearby Object, Find Object Ahead, When Timer Rings, When
Message Heard and one-shot Trigger Enter/Exit lifecycle and sensor/player context. The Android exporter
currently consumes the separate Mobile3D project model.

The first-steps Mobile 3D project also ships **World Logic → Find the Goal**. Its explicit Player
origin searches for Goal through an inclusive 9 m radius and stores `found` as `nearby_goal`, keeping
the world graph independent of an implicit object owner. It also ships Crystal Garden and bounded
Populate Area recipes. One
authored safe static prototype can represent 2–256 deterministic display objects; projects are capped
at 64 groups and 1,024 objects. A group costs 36 bytes under one shared 24-byte `KCSP392` header,
glTF bakes the copies, and native GLES regenerates the same ordered prefix for instanced drawing.
Generated copies deliberately have no gameplay, collider, movement or Logic Block identity. This is
compact decorative population, not a general gameplay-PCG system; overlap avoidance, per-copy culling,
LOD and a Mobile 3D browser runtime are not claimed.

First Steps now adds **World Logic → Count the Timer Rings**: a repeating one-second timer writes its
count to `timer_rings`, replacing a difficult Every Frame counter. **Find the Goal Ahead** uses the
saved 3D Forward world axis and Normal width and writes `goal_ahead`. The **First Steps** editor tab
also adds World Logic → **Hear the Dash Message**: the Dash graph sends `player.dashed`, and the
separate `message_lesson` graph receives it and sets `heard_message=true`. The project has seven
graphs, 27 nodes and seven bindings including four world bindings. Focused opcode-25/PBR-lite parity
checks pass; the full suite is green: 596 passed, 135 subtests passed in 127.49s. Its
1,265-byte `KCVG001` has SHA-256
`363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`; the unchanged 914-byte KCPK
(`8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`) and 60-byte KCSP
(`E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`) bring the compact total to
2,239 bytes. Fresh idle execution has state SHA-256
`a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; after dash, state includes
`heard_message=true` and `score=1`.

The current PBR-lite/opcode-25/animation-runtime Poco APK is locally built and inspected at 1,484,357
bytes with SHA-256 `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The canonical and
explicit `pbr-lite-op25` paths are byte-identical; their embedded current KCVG/KCPK/KCSP assets are
unchanged. Local shader linking and `aapt`/`apksigner`
inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES 3.0, ARM64-only native code, the
debug certificate and APK Signature Scheme v2. Its native library contains KCAN runtime markers; the
unanimated starter correctly omits the optional KCAN asset. The Poco is absent from ADB, so this
`B9B1…` build
has no install, launch, installed-byte hash match or physical profile claim. The preceding local
`message-op25` / `message-op25-audit-fixed` snapshot remains 1,451,149 bytes / `1003F061…`.

The separate animation-bearing Poco APK is 1,483,820 bytes with SHA-256
`43D197ECF62F73349859FFED9D167BCA64BBFA092A6080BC03151E8B8F5B4E0F`. Its 88-byte KCAN asset
contains one binding and two ping-pong keys. It is locally built and inspected only.

The linked Saved Scene acceptance APK at
`build/UGTS-Saved-Scenes-3.9.2-Poco-X7-Pro-debug.apk` is 1,505,487 bytes with SHA-256
`70FD18B26DB7D41167E32EBD27088DC02474479F240B6A5DBF2654A6B36ED291`. Local inspection verifies
the exact ARM64/GLES 3/v2-signed Poco package and byte-matched KC3D/KCVG/KCAN/KCSP/KCPK assets. Its
authoring links are not packaged as runtime JSON. ADB reports no connected device, so this artifact
has no install, launch, pull-back hash or phone-profile claim.

The last physically verified pre-audit opcode-25 APK is preserved explicitly at the
`message-op25-pre-audit-debug` path: 1,449,653 bytes with SHA-256
`FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`. Xiaomi `2412DPC0AG` /
`rodin` installed and cold-launched it; the pulled 1,449,653-byte base APK has the same SHA-256. Its
30-second profile measured 120.12 effective FPS, 8.372/10.183/12.641 ms p50/p95/p99, thermal status
0 and no crashes or warnings; evidence is saved at
`validation/device/opcode25-message-poco-profile.json`. This physical evidence belongs only to FBCB.

The preceding opcode-24 build is preserved at
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`, 1,460,361 bytes with SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`. Interaction-heavy/touch,
unplugged, long-duration thermal, explicit 60/90 Hz fallback, lower-tier and first post-audit device
runs remain open.
UGTS is not yet a complete Godot-like engine: bounded visual parent-following now exists, but a
general gameplay/physics scene graph, live Saved Scene definition editing/overrides, GLB/skeletal
animation and retargeting, crossfades/layered blending, animation-state-machine authoring, unified
Player physics, native contact events, richer physics/content pipelines, production distribution and
Vulkan remain incomplete.

The preceding opcode-23 artifact is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.
