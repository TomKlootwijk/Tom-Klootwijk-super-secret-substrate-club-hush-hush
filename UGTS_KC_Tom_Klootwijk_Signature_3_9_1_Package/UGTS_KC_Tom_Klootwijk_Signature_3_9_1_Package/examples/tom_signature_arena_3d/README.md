# Tom Klootwijk Signature Arena 3D

Canonical files:

- `project.json` — editable 3D project;
- `signature_scene.kc3d` — compact native scene pack;
- `signature_scene.gltf` — interchange export;
- `scene-pack-inspection.json` — structural validation evidence.

Regenerate the native project from the package root with:

```bash
PYTHONPATH=src python -m ugts_kc3 build-android project.json ../../android/UGTSKC391Signature
```
