# Post-3.9.2 Production Roadmap

UGTS now has a useful child-facing editor/ECS/graph/native-Android slice, but it is not yet a complete
Godot-like engine. The roadmap below remains required work, not a claim of finished parity.

1. Install, cold-launch, pull/hash-match and profile the locally inspected post-audit seven-graph
   opcode-25 APK (1,451,149 bytes, SHA-256
   `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`); the Poco disconnected just
   before its final install. The preserved pre-audit 1,449,653-byte FBCB artifact already installs,
   cold-launches and profiles on Xiaomi `2412DPC0AG` / `rodin` at 120.12 effective FPS, thermal status
   0 and no crashes/warnings, but that physical evidence does not transfer to `1003…`. Add
   interaction-heavy/touch and unplugged long-duration runs, explicit 60/90 Hz fallbacks, and
   representative lower-tier devices.
2. Add Android Game Development Kit frame pacing and ADPF integrations behind tested adapters.
3. Add a Vulkan renderer only after GLES3 parity fixtures and fallback behavior are proven.
4. Add texture, font, skeletal animation, character sweep, joints and richer physics records.
5. Add chunk/LOD/occlusion streaming and measured visible-node budgets.
6. Add Android asset compression/pipeline policies and Play Asset Delivery adapters.
7. Add reproducible release signing hooks without embedding private keys.
8. Extend the data-backed editor with animation/timeline authoring, reusable scene/prefab workflows,
   rotation/scale gizmos, richer portable sensing queries and advanced graph debugging such as
   breakpoints and watches without making the GUI state authority. Selection-owned Logic Blocks,
   their multi-graph chooser, Find Nearby Object, Find Object Ahead, When Timer Rings, When Message
   Heard, the First Steps **Hear the Dash Message** lesson, X/Y/Z translation gizmo and read-only
   Logic Trail are already shipped.
9. Add server-authoritative replication, rollback and mobile network impairment tests.
10. Explore the 4D contract only after selecting spacetime gameplay or four-spatial geometry;
    do not allocate M450 until an implementation and tests exist.
