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
`decorative`. Use simple sphere/box colliders for mobile-friendly broad behavior.

Quality tiers are ordered from most expensive to safest. Android profiles choose a starting tier;
the runtime may descend under sustained low FPS or thermal pressure and recover conservatively.
