# Three Linked Glow Gates

This playable Mobile 3D example stores one three-object **Saved Scene** and places it three times. Each linked placement contains only an ID, the Saved Scene ID, and one group transform. At runtime UGTS materializes the compact authoring data into ordinary flat ECS nodes for desktop play, Android, packed assets, and glTF.

The authored scene keeps four normal objects: a floor, a cyan Player, a green Goal, and a small blue orbit marker. The Saved Scene library stores the teal arch, gold lantern, and pink sparkle recipe once. Three compact descriptors place `gate_east`, `gate_north`, and `gate_west`, producing nine uniquely named runtime nodes.

## Try it in the editor

1. Double-click `RUN_UGTS_STUDIO.cmd` at the repository root.
2. Open `examples/linked_saved_scenes_3d/project.json`.
3. Expand a linked gate in the Scene Tree. Clicking any linked child selects the whole group.
4. Move the group in the Inspector, or choose **Unlink** to bake that one placement into ordinary editable objects.
5. Press Play. Use WASD, arrow/touch movement, or the on-screen controls to move the cyan Player through the gates to the green Goal.

The lanterns bob while you play. The blue marker uses compact polar movement, and each pink sparkle is the prototype for a tiny deterministic render-only population.

## What is genuinely authored

Everything is editable data in `project.json`; there is no code-created scene or runtime bootstrap.

- `metadata.saved_scenes[0]` is schema `ugts-studio-saved-scene-2` and contains exactly three parent-local object records.
- `metadata.saved_scene_instances` contains three schema-valid descriptors. None contains copied nodes or graphs.
- The static arch is the group root. Saved Scene parents must remain transform-stable because the phone runtime is intentionally flat.
- The lantern is a leaf, so its `bob` transform Animation is safe.
- `reveal_lantern` names another member of the Saved Scene. Capture turns that reference into `@node/lantern`, then materialization remaps it to each placement's unique lantern ID.
- `keep_bobbing` uses `entity: null`, meaning “This object.” It remains owner-relative and can be shared by all three lanterns.
- The sparkle uses Populate Area. Those extra sparkles are render-only, not gameplay ECS objects.

Linked children intentionally stay read-only until **Unlink**. This is an honest constraint, not a missing hidden hierarchy: the authoring model is compact and linked, while deployed runtime data is deterministic and flat.

## Compact result

| Stage | Stored/result objects |
|---|---:|
| Ordinary authoring nodes | 4 |
| Saved Scene definition nodes, stored once | 3 |
| Compact placement descriptors | 3 |
| Materialized runtime ECS nodes | 13 |
| glTF nodes including render-only sparkle copies | 22 |

The project targets the POCO X7 Pro 12 GB profile with Mali-G720, arm64-v8a, GLES 3, and the 120 Hz `signature_ultra` tier.

## Verify it

From the repository root:

```powershell
python examples/linked_saved_scenes_3d/verify_example.py
```

The verifier loads the checked-in JSON with `Mobile3DProject`, validates the real authoring schemas, proves materialization purity/idempotence and unique IDs, checks per-instance and owner-relative graph remapping, runs the bobbing Animation, and drives the Player to the Goal. It compiles every asset twice and compares authoring versus already-materialized output:

- **KC3D392**: 13 flat scene nodes.
- **KCVG001**: four graphs and six node bindings.
- **KCAN392 v2**: three animated lantern bindings and nine keys.
- **KCSP392**: three sparkle groups and nine generated render copies.
- **KCPK392**: one packed polar movement component.
- **glTF 2.0**: 22 uniquely named nodes, including the scatter copies.

It also round-trips the flat `.kcec` deployment project and prints current byte counts and SHA-256 hashes. The verifier uses temporary output only; it does not build an APK or leave generated files behind.
