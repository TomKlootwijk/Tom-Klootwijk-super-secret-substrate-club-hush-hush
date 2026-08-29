# Release Notes — 3.9.2

**K-Kij-T / Grove**

3.9.2 is an additive creation-engine upgrade of 3.9.1 focused on a learnable desktop workflow and a
compact Mali-G720 MC7 Android result. It adds UGTS Studio, typed Logic Blocks, ECS composition,
log-polar packed kinematics, direct Poco APK tooling, the Grove juice controller, GLES post composite,
shockwave/flash/bloom response, device tuning and KC3D392 assets.

The beginner editor supports undoable object creation, copying, deletion and existing picture,
shape and material assignment, plus bounded undoable Wavefront OBJ import. Logic-block creation is
re-entrancy safe and finite properties use contextual child-facing choices. A one-click Windows
launcher and a prominent ADB **Deploy to Phone** action remove command-line steps. On Android, touch roles are
tracked by pointer ID so a left movement thumb and right dash/look thumb work together without being
swapped by pointer ordering.

KCVG001 now carries sparse world graphs as well as entity graphs, and the native VM executes all 18
current Logic Blocks, including Apply Force, with the same active-owner rule as desktop.

Grove's phone player is native C++/GLES rather than an HTML wrapper. The retained 2D project model
still exports HTML5, and its visual graphs now execute in a bounded browser VM. The Android exporter
currently consumes the separate Mobile3D project model. PCG remains a future TODO.
