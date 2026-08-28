# Graphics Runtime ABI and Backend Contract

## CPU reference

The bundled Python runtime is the correctness oracle for scene composition, geometry compilation, hand calculus, event ordering, replay, glTF/USDA export and SVG projection. It is not a throughput benchmark.

## GPU record concept

A production instance record should contain or reference:

```text
instance_id
pattern_opcode
mechanism_version
parameter_offset / parameter_count
world_transform
bounds
material_index
support_mask / compatibility_mask
derivative_flags
LOD policy
lineage checksum
```

A GPU event proposal should contain:

```text
proposal_id, entity_id, event_time, guard_status,
residual/error interval, confidence, source, priority,
requested patch reference, lineage label
```

## Commit boundary

Gameplay-critical GPU results are proposals. Authoritative commit performs:

```text
support -> compatibility -> accepted guard status -> confidence -> error margin
-> deterministic order -> conflict policy -> state patch -> lineage/event record
```

The reference order key is `(event_time, -priority, source, proposal_id)`.

## Backends

- **Vulkan profile**: native graphics/compute, explicit resources, timestamp queries and physical-device measurement.
- **WebGPU/WGSL profile**: portable compute and presentation layouts.
- **CPU/SVG profile**: deterministic regression and documentation preview.

This package supplies shader prototypes and an ABI contract. It does not contain compiled SPIR-V for the 3.0 renderer and does not claim a physical-GPU result.
