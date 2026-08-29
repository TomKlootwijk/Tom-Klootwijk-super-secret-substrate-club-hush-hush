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
Deploy now pins the
sole authorized device, builds below `.ugts-studio/deploy`, installs, reads Gradle's exact flavor-aware
`applicationId`, and opens `android.app.NativeActivity` on that same device. Its messages distinguish
build, install and launch failures. On Android, touch roles are tracked by pointer ID so a left
movement thumb and right dash/look thumb work together without being swapped by pointer ordering.

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
graphs, 27 nodes and seven bindings including four world bindings. Focused opcode-25 parity checks
pass; the full suite is green: 510 passed, 100 subtests passed in 66.69s. Its 1,265-byte `KCVG001` has SHA-256
`363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`; the unchanged 914-byte KCPK
(`8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`) and 60-byte KCSP
(`E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`) bring the compact total to
2,239 bytes. Fresh idle execution has state SHA-256
`a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; after dash, state includes
`heard_message=true` and `score=1`.

The post-audit canonical opcode-25 Poco APK is locally built and inspected at 1,451,149 bytes with
SHA-256 `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`. The canonical,
`message-op25` and `message-op25-audit-fixed` paths are byte-identical; their embedded current
KCVG/KCPK/KCSP assets are unchanged. Local `aapt`/`apksigner`
inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES 3.0, ARM64-only native code, the
debug certificate and APK Signature Scheme v2. The Poco disconnected before final installation, so
this `1003…` build has no install, launch, installed-byte hash match or physical profile claim.

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
UGTS is not yet a complete Godot-like engine: reusable scenes/prefabs, animation workflows, richer
physics/content pipelines, production distribution and Vulkan remain incomplete.

The preceding opcode-23 artifact is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.
