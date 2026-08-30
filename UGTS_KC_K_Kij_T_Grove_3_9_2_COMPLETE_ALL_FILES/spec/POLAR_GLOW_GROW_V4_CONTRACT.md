# KCPR v4 Grow Glowing Copies Contract

Status: frozen implementation contract, 2026-08-30.

## Purpose and boundary

`Grow glowing copies` is a second presentation consumer of the existing
Glow-by-distance field. It is deliberately not physics, collision, gameplay
scale, LOD, or a Seeded Grove implementation.

Only generated Make Many display copies may grow. The authored prototype keeps
its ECS transform, collider, picking shape, graph state, snapshots and hashes.
Generated members remain render-only and receive no ECS identity.

## Authored data

The optional v3 Glow object keeps its three required binary32 values and gains
one optional Boolean:

```json
{
  "glow_by_distance": {
    "start_distance": 0.0,
    "end_distance": 4.0,
    "strength": 1.25,
    "grow_copies": true
  }
}
```

`grow_copies` defaults to `false` and is omitted when false. It cannot exist
without the containing Glow object. No independent size value is added.

## Field and scale schedule

The existing field remains authoritative. Every intermediate operation follows
the frozen binary32 schedule used by Glow:

```text
u         = clamp(abs((rho - center_rho) * inverse_half_width), 0, 1)
pulse     = 1 - u*u*(3 - 2*u)
direction = 0.5 + 0.5*D(theta + phase12*tau/4096)
F         = clamp((strength * pulse) * direction, 0, 4)
```

`D` is cosine in Direct mode, the shared seam-safe UGLUT2 direction lane in LUT
mode, and the quantized UGLUT2 reference in CPU/editor mode.

When enabled for a generated copy:

```text
display_scale_multiplier = clamp(1 + F, 1, 5)
```

The multiplier is uniform. Normal Make Many copies apply it after authored
seeded scale. Radial Burst applies authored scale, then its life envelope, then
this multiplier. The same `F` drives lighting and size; it must not be evaluated
as two subtly different fields. Bayer remains the final presentation pass.

## KCPR v4 binary compatibility

- Header, operator and recipe layouts stay 32, 16 and 128 bytes respectively.
- Operator `0x0053`, slot 12, arity 2, name
  `polar_display_scale_from_glow` owns mask bit `0x1000`; its frozen 64-bit
  meaning hash is `0x1d558c07b7a6796b`.
- Its meaning is
  `generated-display-scale*=clamp(1+glow_field,1,5);prototype-gameplay-unchanged;final-bayer-only.v1`.
- V4 is selected only when at least one recipe enables `grow_copies`.
- A grow recipe must also carry all three existing Glow operator bits and the
  same three binary32 Glow parameters in the existing 12-byte recipe tail.
- Mixed v4 packs may contain legacy, Burst-only or Glow-only recipes. Their
  record masks and tails retain their existing meanings.
- Packs without grow remain byte-for-byte v1, v2 or v3 as before. Their content
  addresses must also remain exact.
- Enabling grow changes only the full recipe content identity. The spatial
  lineage namespace excludes this modifier, so count-prefix placement and
  phase derivation remain unchanged.
- V4 is invalid unless at least one recipe uses the slot-12 operator. Grow is
  invalid in v1-v3, without the complete Glow mask, or with non-canonical
  operator metadata, tail values, reserved bytes or content address.

## Native and GPU representation

- The visible instance stride remains 36 bytes: the prior 32 spatial bytes plus
  one 32-bit phase/flags lane.
- Low 12 bits preserve the seeded material phase. A high generated-copy flag
  gates growth so a GPU group may safely contain the real prototype and copies.
- Existing `uGlowMode` becomes a bitfield for field lighting and copy growth;
  no new uniform, texture, LUT, instance lane or draw batch is introduced.
- CPU fallback applies the multiplier to a local display copy only and never
  writes it back to authoritative `NodeData` or an ECS pool.
- Runtime logs must distinguish grow recipe/copy counts while continuing to
  prove `ecs_generated=false` and a 36-byte instance stride.

## Required evidence boundary

Completion requires strict Python/native pack rejection tests, frozen v1-v3
fixtures, a v4 golden fixture, shared field vectors, desktop stopped/Play
preview tests, native host and shader checks, fail-closed benchmark inspection,
and a fresh ARM64 build. Those establish source and packaging behavior only.
Visual quality, Mali execution, frame timing, power and thermals require a
connected POCO run and must remain explicitly unclaimed until measured.
