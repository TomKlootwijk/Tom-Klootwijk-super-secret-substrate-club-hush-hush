# Release Notes — 3.9.2

**K-Kij-T / Grove**

3.9.2 is an additive creation-engine upgrade of 3.9.1 focused on a learnable desktop workflow and a
compact Mali-G720 MC7 Android result. It adds UGTS Studio, typed Logic Blocks, ECS composition,
log-polar packed kinematics, direct Poco APK tooling, the Grove juice controller, GLES post composite,
shockwave/flash/bloom response, device tuning and KC3D392 assets.

The beginner editor supports undoable object creation, copying, deletion and existing picture,
shape and material assignment, plus bounded undoable Wavefront OBJ import. Logic-block creation is
re-entrancy safe and finite properties use contextual child-facing choices. A one-click Windows
launcher and a prominent ADB **Deploy to Phone** action remove command-line steps. Deploy now pins the
sole authorized device, builds below `.ugts-studio/deploy`, installs, reads Gradle's exact flavor-aware
`applicationId`, and opens `android.app.NativeActivity` on that same device. Its messages distinguish
build, install and launch failures. On Android, touch roles are tracked by pointer ID so a left
movement thumb and right dash/look thumb work together without being swapped by pointer ordering.

The Mobile 3D Inspector adds child-readable **Off**, **Orbit**, **Spiral Out** and **Spiral In** movement
presets with radius, turn speed and start angle controls. The generated ECS data remains compact: two
unsigned 64-bit log-polar words per mover, a shared binary16 UGLUT2 per profile, and one exact 24-byte
sparse Android record per moving node. Dynamic nodes are guarded because their transforms belong to
physics.

KCVG001 now carries sparse world graphs as well as entity graphs, and the native VM executes all 18
previous Logic Blocks plus Trigger Enter and Trigger Exit, including Apply Force, with the same
active-owner rule as desktop. Sensor entry/exit has matching desktop/native sphere/box overlap,
non-physical transitions, sensor/player/entity graph context, world-or-matching-sensor dispatch and
explicit sensor/dispatch caps.

The child-facing Trigger Area3D workflow is included: **+ Trigger Area** adds a ready-made sensor, and
the Inspector's **Use as Trigger** control offers Sphere/Radius or Box/Size X/Y/Z. The Scene Tree and
Resources panel identify Trigger Areas, and edits support Undo/Redo and save/load.

Grove's phone player is native C++/GLES rather than an HTML wrapper. The retained 2D project model
still exports HTML5, and its bounded browser VM executes the same current 20-block vocabulary,
including one-shot Trigger Enter/Exit lifecycle and sensor/player context. The Android exporter
currently consumes the separate Mobile3D project model. PCG remains a future TODO.
