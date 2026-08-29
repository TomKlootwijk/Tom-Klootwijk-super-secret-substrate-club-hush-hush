# Release Notes — 3.9.2

**K-Kij-T / Grove**

3.9.2 is an additive creation-engine upgrade of 3.9.1 focused on a learnable desktop workflow and a
compact Mali-G720 MC7 Android result. It adds UGTS Studio, typed Logic Blocks, ECS composition,
log-polar packed kinematics, direct Poco APK tooling, the Grove juice controller, GLES post composite,
shockwave/flash/bloom response, device tuning and KC3D392 assets.

The beginner editor supports undoable object creation, copying, deletion and existing picture,
shape and material assignment. Logic-block creation is re-entrancy safe. On Android, touch roles are
tracked by pointer ID so a left movement thumb and right dash/look thumb work together without being
swapped by pointer ordering.

Grove's phone player is native C++/GLES rather than an HTML wrapper. The retained 2D project model
still exports HTML5, and its visual graphs now execute in a bounded browser VM. The Android exporter
currently consumes the separate Mobile3D project model. PCG remains a future TODO.
