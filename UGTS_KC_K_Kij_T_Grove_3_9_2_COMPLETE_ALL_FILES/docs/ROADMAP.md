# Post-3.9.2 Production Roadmap

UGTS now has a useful child-facing editor/ECS/graph/native-Android slice, but it is not yet a complete
Godot-like engine. The roadmap below remains required work, not a claim of finished parity.

1. Install, cold-launch, pull/hash-match and profile the locally inspected PBR-lite seven-graph
   opcode-25/animation-runtime APK (1,484,357 bytes, SHA-256
   `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`); the Poco is currently absent
   from ADB. The preserved pre-audit 1,449,653-byte FBCB artifact already installs,
   cold-launches and profiles on Xiaomi `2412DPC0AG` / `rodin` at 120.12 effective FPS, thermal status
   0 and no crashes/warnings, but that physical evidence does not transfer to `B9B1…` or the
   animation-bearing `43D1…` demo. Add
   interaction-heavy/touch and unplugged long-duration runs, explicit 60/90 Hz fallbacks, and
   representative lower-tier devices.
2. Add Android Game Development Kit frame pacing and ADPF integrations behind tested adapters.
3. Add a Vulkan renderer only after GLES3 parity fixtures and fallback behavior are proven.
4. Add texture and font pipelines, GLB/skeletal animation and retargeting, crossfades/layered
   blending, character sweep, joints and richer physics records. Generic untagged Android bodies now
   integrate and resolve bounded contacts after Logic Blocks; next unify Player with that path, expose
   collision/floor/bounds events and grounded state, then add sweep/CCD only with cross-runtime
   fixtures. The shipped eight-edge hierarchy is display-only; general child colliders, triggers,
   gameplay tags, graph ownership and independent transform controllers require an explicit
   cross-runtime scene-graph/physics design rather than relaxing those guards piecemeal.
5. Add chunk/LOD/occlusion streaming and measured visible-node budgets.
6. Add Android asset compression/pipeline policies and Play Asset Delivery adapters.
7. Add reproducible release signing hooks without embedding private keys.
8. Extend the data-backed editor with Saved Scene definition-edit mode and per-instance child
   overrides, animation state machines, crossfade/blend authoring and skeletal-animation authoring,
   rotation/scale gizmos, richer portable sensing queries and advanced graph debugging such as
   breakpoints and watches without making the GUI state authority. Selection-owned Logic Blocks,
   their multi-graph chooser, Find Nearby Object, Find Object Ahead, When Timer Rings, When Message
   Heard, the First Steps **Hear the Dash Message** lesson, X/Y/Z translation gizmo and read-only
   Logic Trail, single-node authoring-time **Saved Objects**, compact linked multi-object **Saved
   Scenes**, the dark Scene Tree's world-pose-preserving **Attach to…** / **Detach** display hierarchy,
   and bounded named rigid-transform clip
   libraries are already shipped. Each eligible static node has up to 16 clips, one optional
   autoplay choice, whole-pose keys, scrub/playback/Undo, nine child-facing/runtime Arrival modes,
   direct Logic Blocks Play/Stop and KCAN v1/v2 native parity. This is not GLB/skeletal, crossfade or
   state-machine authoring. Ordinary attached objects store local TRS, follow moving ancestors on
   desktop/native, retain glTF children and use optional compact KCHI links, but children remain
   display-only and chains stop at eight parent edges. Saved Scenes separately store parent-local
   static groups once and each placement as one transform, then deterministically flatten for every
   runtime/compiler. They do not yet provide nested scenes, retained definition-level prefab
   instances, live definition editing or per-instance child overrides.
9. Add server-authoritative replication, rollback and mobile network impairment tests.
10. Explore the 4D contract only after selecting spacetime gameplay or four-spatial geometry;
    do not allocate M450 until an implementation and tests exist.
