# Scene and Asset Contract - KC Two Hands 3.0

## Authority boundary

The scene layer is a production-facing composition and query layer. It does not replace the UGTS event authority. A node transform, visibility state, parent, variant or asset binding changes authoritatively only when a verified event or an explicit authoring transaction commits the patch and appends lineage.

## Stable objects

- **Asset**: immutable or content-addressed geometry/material payload.
- **Scene node**: stable instance identity, local transform, parent, visibility, tags and lineage.
- **Layer opinion**: non-destructive override of declared node fields.
- **Derived representation**: mesh, collision proxy, LOD or preview generated under an error contract.

Coordinates are not identity. Reusing the same mesh or position does not merge node identities or lineage.

## Transform convention

Matrices are 4x4 row-major in the Python reference and multiply column vectors. World transforms are composed as:

```text
T_world(node) = T_world(parent(node)) * T_local(node)
```

Export adapters convert to the target convention; the glTF exporter emits column-major matrix arrays.

## Required metadata

Every scene declares schema version, units per meter, up axis, handedness, time unit, working color space and determinism profile. Assets may declare source pattern, schema hash, material binding and compilation metadata.

## Error contract

A derived geometry representation should declare at least:

```text
(world_error, collision_error, screen_space_error_pixels,
 normal_error_degrees, topology_preserved)
```

Presentation quality does not certify simulation or collision quality. The source pattern/field remains authoritative unless an application explicitly promotes a compiled representation under a validated error budget.
