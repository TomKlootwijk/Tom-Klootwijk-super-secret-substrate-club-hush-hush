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
