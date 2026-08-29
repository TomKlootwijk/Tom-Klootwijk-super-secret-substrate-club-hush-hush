# Post-3.9.2 Production Roadmap

1. Install, launch, hash-match and profile the locally built/inspected five-graph opcode-23 APK; ADB
   reported zero devices during its current verification. The preserved 1,441,929-byte opcode-22
   `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` owns the 30-second Poco result, while the retained 64.9-second idle 120 Hz
   baseline belongs to a still earlier APK. Add interaction-heavy/touch and unplugged long-duration
   runs, explicit 60/90 Hz fallbacks, and representative lower-tier devices.
2. Add Android Game Development Kit frame pacing and ADPF integrations behind tested adapters.
3. Add a Vulkan renderer only after GLES3 parity fixtures and fallback behavior are proven.
4. Add texture, font, skeletal animation, character sweep, joints and richer physics records.
5. Add chunk/LOD/occlusion streaming and measured visible-node budgets.
6. Add Android asset compression/pipeline policies and Play Asset Delivery adapters.
7. Add reproducible release signing hooks without embedding private keys.
8. Extend the data-backed editor with animation/timeline authoring, reusable scene/prefab workflows,
   rotation/scale gizmos, richer portable sensing queries and advanced graph debugging such as
   breakpoints and watches without making the GUI state authority. Selection-owned Logic Blocks,
   their multi-graph chooser, Find Nearby Object, When Timer Rings, the X/Y/Z translation gizmo and
   read-only Logic Trail are already shipped.
9. Add server-authoritative replication, rollback and mobile network impairment tests.
10. Explore the 4D contract only after selecting spacetime gameplay or four-spatial geometry;
    do not allocate M450 until an implementation and tests exist.
