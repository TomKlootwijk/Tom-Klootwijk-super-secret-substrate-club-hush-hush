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
native Android execute the full current 24-block vocabulary. Append-only opcode 21 is **Repeatable
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

Desktop Preview now exposes a read-only Logic Trail. Numbered block badges and the Last Run list show
execution order, values, chosen flow and errors without mutating or serializing the project; the latest
trail remains visible after Stop and adds zero export bytes.

The child-facing Trigger Area3D workflow is included: **+ Trigger Area** adds a ready-made sensor, and
the Inspector's **Use as Trigger** control offers Sphere/Radius or Box/Size X/Y/Z. The Scene Tree and
Resources panel identify Trigger Areas, and edits support Undo/Redo and save/load.

Grove's phone player is native C++/GLES rather than an HTML wrapper. The retained 2D project model
still exports HTML5, and its bounded browser VM executes the same current 24-block vocabulary,
including Repeatable Random Number, Find Nearby Object, Find Object Ahead, When Timer Rings and one-shot Trigger Enter/Exit lifecycle and
sensor/player context. The Android exporter
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
saved 3D Forward world axis and Normal width and writes `goal_ahead`. The project has six graphs, 23
nodes and six bindings including three world bindings. Current verification passes 483 tests plus 87
subtests in 59.77 seconds; the focused opcode-24 slice passes 14 tests plus 25 subtests. Its 1,085-byte
`KCVG001` has SHA-256 `2c5c6edb0c804da7fb2b6edab8c6beab12ccd2dac8b4e743d03c6194aff4af27`;
the 914-byte KCPK (`8a45ddbf874d918cedaeb0161e80fef3314c2c2b0b21a45da90e22a18c4dd313`) and 60-byte KCSP
(`e95bde225571ab5f6eac3b9c04cb1bd332a0c95c740b377ac2dee30460dd2fd1`) bring the compact total to
2,059 bytes. Fresh execution sets `goal_ahead=true` and has state SHA-256
`71df205686c92c217c3b1e23ad00929a331d07b5bb43e64d27023ec17d490a9c`.

The canonical opcode-24 Poco APK is 1,460,361 bytes with SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`. Local `aapt`/`apksigner`
inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES 3.0, ARM64-only native code, the
debug certificate and APK Signature Scheme v2. Its embedded KCVG/KCPK/KCSP assets match the current
source sidecars exactly. ADB reported zero devices, so this opcode-24 artifact is not claimed as
installed, launched or profiled. Those physical-device claims and the 120.23-FPS 30-second result
remain attached to the preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk`; the 64.9-second idle
baseline belongs to a still earlier APK. Interaction-heavy/touch, unplugged, long-duration thermal,
explicit 60/90 Hz fallback and lower-tier device runs remain open.

The preceding opcode-23 artifact is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.
