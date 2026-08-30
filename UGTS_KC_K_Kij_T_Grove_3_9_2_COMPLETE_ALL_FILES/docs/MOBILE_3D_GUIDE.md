# Mobile 3D Creation Guide

Create and inspect a project:

```bash
PYTHONPATH=src python -m ugts_kc3 new-3d my_arena   --template signature-arena --author "Tom Klootwijk" --android
PYTHONPATH=src python -m ugts_kc3 validate-3d my_arena/project.json
PYTHONPATH=src python -m ugts_kc3 simulate-3d my_arena/project.json   --steps 480 --move-z -1 --json
PYTHONPATH=src python -m ugts_kc3 pack-3d my_arena/project.json   my_arena/signature_scene.kc3d --inspect
PYTHONPATH=src python -m ugts_kc3 export-gltf3d my_arena/project.json   my_arena/signature_scene.gltf
```

Author meshes and materials with stable IDs, then reference them from nodes. Gameplay tags currently
recognized by the oracle and native demo are `player`, `collectible`, `goal`, `hazard` and
`decorative`. Those are also the five portable choices in **Find Nearby Object**: choose an explicit
or bound origin and inclusive radius to receive the nearest active/alive match, with deterministic ID
ties. First Steps demonstrates the block in **World Logic → Find the Goal** using Player, Goal, 9 m
and `nearby_goal`.

In Studio, **Appearance → Material Look** offers Matte, Toy Plastic, Metal and Crystal Glow while
keeping the selected object's colour. Shared authored materials are safely cloned only for that
prototype (and therefore its Populate Area copies); Undo/Redo restores the exact node/material
snapshot. The look name is never serialized. Desktop Preview and native GLES shade the saved
metallic/roughness/emissive values through the same compact PBR-lite surface response, with Android's
emissive pulse retained as presentation-only juice.

Above the Scene Tree, **Save Object** captures one safe flat object into **Saved Objects**. The saved
node values are a one-time snapshot; later source or placed-copy edits do not update the entry.
**+ Saved Object…** appends an ordinary node at the first deterministic mesh/collider-footprint-free
diagonal position. Shape/look/physics can then differ, while changing the shared Logic Blocks changes
every owner of those same blocks. Material Look copy-on-write treats a saved definition as another
consumer, so changing a source look cannot silently mutate the saved snapshot. **Remove Saved…**
keeps already placed nodes. Player, Movement Pattern, Populate Area and literal-self graph cases are
rejected because the frozen native formats cannot give those cases safe instance-local semantics.
The placed copy is selected for immediate dragging; a very large copy's first collision-safe spot can
be outside the gameplay bounds.

For a linked group, Ctrl-select two or more ordinary nodes and choose **Save Together**. The primary
selection becomes the root. **+ Saved Scene…** places one linked group transform while the definition
keeps its parent-local nodes, relative graphs and leaf animations once. Child rows are readable but
locked; transform the whole placement through the Inspector or choose **Unlink** to bake ordinary
editable nodes. Every runtime/export path sees the same deterministic flat materialization, so the
feature adds no new Android prefab record. Parents must remain static transform anchors; nested
Saved Scenes, Player, parent Animation/dynamics/spin/transform-writing logic and shear-producing
scale/rotation combinations are rejected. Definitions are snapshots and cannot yet be edited in
place or given per-instance child overrides.

Ordinary scene objects have a separate retained display hierarchy. In the dark Scene Tree,
right-click a safe display object and choose **Attach to…**; right-click an attached row and choose
**Detach**. The row nests under its parent, the operation preserves its world pose, and Undo/Redo
reverses the whole attachment. The child Inspector changes its heading to **Transform inside …**:
those saved Position, Turn and Size values are local to the parent. The viewport and X/Y/Z move gizmo
remain world-space and convert a committed move back to the correct local value, so attaching,
detaching or dragging should not make an object jump.

This is a bounded visual attachment, not child physics. A child must have Dynamic off, Collision None
and non-sensor, empty tags, zero Spin, and no Logic Blocks, Movement Pattern, Populate Area or
Transform Animation. An unattached root may move through otherwise-valid physics, spin, Movement
Pattern, Animation or Logic Blocks and its descendants follow. An attached intermediate parent moves
only by following its own parent. Every parent that owns children must keep the same positive Scale
X/Y/Z, and a chain may contain at most eight parent edges. Unsafe **Attach to…**
choices are disabled with an explanation.
Logic Blocks that can change a hierarchy parent's scale must save one complete positive uniform XYZ
vector. Per-axis or runtime-selected scale writes are rejected because they cannot prove the child
composition will remain valid on every tick.

Desktop Play composes attached children last in the fixed update; native Android does the same after
Ready and the ordinary transform writers. Static glTF preserves the children. Flat projects emit no
new asset; a hierarchy emits optional `hierarchies.kchi` (`KCHI392`) with a 24-byte header and one
8-byte child/parent KC3D index pair per link. Open
`examples/parent_child_hierarchy_3d/project.json` for a carrier with Arm/Mast children and a Beacon
grandchild, then run `python examples/parent_child_hierarchy_3d/verify_example.py` from the repository
root. The verifier is source/host evidence only and is not an install, launch or Mali performance
claim. Separately, the exact 1,565,171-byte `813D290E…` hierarchy APK has installed and cold-launched
on the authorized `2412DPC0AG` / `rodin_eea` Poco. Its bounded five-node 15-second profile observed
120.15 effective FPS and 9.959 ms p95 with thermal status 0 and no crashes/warnings. That tiny scene
does not establish interaction-heavy, large-game/AAA or sustained performance.

The bottom **Animation** panel gives an eligible static node up to 16 named relative transform clips.
Create **Main**, move Time, edit Position offset / Turn / Size multiplier, and save a whole-pose key.
Use New, Duplicate, Rename and Delete Clip to manage the library, and select zero or one clip to play
when the game starts. The identity key at 0 seconds is protected so every clip starts from the
authored node pose. Length and Once/Repeat/Back and forth are saved; timeline Play/Stop, clip
selection and scrub preview in the viewport without changing the project. Library, key, length, loop,
autoplay and Arrival edits are atomic Undo/Redo operations.

Arrival exposes all nine shared modes: Straight (`linear`), Start gently (`ease_in`), Stop gently
(`ease_out`), Gently at both ends (`ease_in_out`), Smooth (`smoothstep`), Extra smooth
(`smootherstep`), Slight overshoot (`back_out`), Springy (`elastic_out`) and Jump (`step`). Desktop
Play first round-trips duration, normalized key times and transform values through the compact phone
quantization. Android uses the same quantized clips and emits `transform_animations.kcan` only when
animations exist. Old one-clip metadata retains exact KCAN v1 output and appears as an implicit
`main` autoplay clip; libraries use KCAN v2 clip hashes and autoplay flags. Dynamic nodes, Player,
packed Movement Pattern, Populate Area and nonzero spin velocity are rejected to prevent two systems
from owning one transform.

Mobile 3D Logic Blocks provide **Play an Animation** and **Stop an Animation**. Choose this or another
animated object and a clip; Restart begins at zero, while Restart off resumes that same held clip.
Stop can hold the current pose or Reset to the authored pose. Known missing targets/clips are rejected
while authoring; dynamic choices fail clearly at runtime. Current glTF export remains static. GLB
animation import, skeletal animation/retargeting, crossfades/layered blending and animation-state-
machine authoring remain outside this slice.

**Find Object Ahead** adds a world-space view cone to those same rules. Its one Vector4 is explicit
world-axis X/Y/Z plus minimum cosine; the runtime normalizes the axis with source-aligned binary32
GSP4 math and performs no trigonometry. Origin rotation and scale are ignored, so choose the saved
world direction you intend. In 3D the child presets are Forward -Z, Back +Z, Right +X, Left -X, Up
+Y and Down -Y; First Steps uses Forward with Normal width and writes `goal_ahead`.

The Events block **When Timer Rings** provides periodic or one-shot logic without an Every Frame
counter. Save a positive **Seconds** value through 86,400 on the block (default 1) and choose whether
**Repeat** stays on (default true). Each binding advances on its own active fixed updates, pauses with
an inactive owner while the world continues, and resets at Ready/restart. It produces at most one
ring per update plus Count, Remaining and Entity outputs; no timer clock or suspended graph is saved.
First Steps demonstrates it in **World Logic → Count the Timer Rings**, writing the one-second repeat
count to `timer_rings`.

**When Message Heard** receives an exact saved portable message name and exposes source, optional
target and bound entity. **Send a Game Message** uses a bounded non-reentrant FIFO: broadcasts visit
active object bindings in canonical scene/graph order before World Logic, targeted sends reach the
target owner plus World Logic, and nested sends wait breadth-first. First Steps demonstrates this in
World Logic → **Hear the Dash Message**: the Dash graph sends `player.dashed`, and the separate
`message_lesson` graph receives it and writes `heard_message=true`. The current starter contains
seven graphs, 27 nodes and seven bindings, including four world bindings. The timer, cone query and
message event have
editor/desktop/retained-web/KCVG/native parity.

Logic Blocks follows the selected node. An unbound node shows a blank graph until its first edit
creates and binds one undoably; multi-bindings have an exact chooser. A Populate Area prototype
cannot own Logic Blocks. Use simple sphere/box colliders for mobile-friendly broad behavior.

Quality tiers are ordered from most expensive to safest. Android profiles choose a starting tier;
the runtime may descend under sustained low FPS or thermal pressure and recover conservatively.
