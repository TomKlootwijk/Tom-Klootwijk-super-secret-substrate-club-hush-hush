# Polar Material Coordinates and Bands Contract

## Scope and ownership

Polar Bands is a presentation-only consumer of the packed log-polar chart. It
does not create ECS entities, colliders, graph targets, gameplay fields, or
authoritative geometry. KCPR generated copies remain render data owned by one
real ECS prototype.

This mechanism is not Glow under another name. Glow remains the bounded scalar
field defined by KCPR v3/v4. Polar Bands exposes an independent coordinate:

```text
P = (q, direction_x, direction_y, phase)
q = clamp((rho - rho_min) / (rho_max - rho_min), 0, 1)
phase = phase12 / 4096
```

`rho` is the interpolated encoded log radius. In LUT mode, `direction` is the
same seam-safe normalized UGLUT2 direction already sampled to place the
instance. Direct mode uses its existing cosine/sine fallback. `phase12` is the
unchanged KCPR lineage lane-5 phase. The generated-copy marker stays in bit 31
and a presentation-valid marker uses bit 30; both are masked away from the low
12-bit phase.

Ordinary objects and packed-polar objects without a KCPR recipe carry an
invalid coordinate and are not modified.

## First consumer: Polar Bands

The first bounded consumer uses the following staged binary32 expression:

```text
c = bands*q + phase + 0.25*(1 + direction_x)
w = fract(c)
band = 1 - abs(2*w - 1)
multiplier = mix(1, 0.5 + band, strength)
base' = base * multiplier
```

`bands` is an integer from 1 through 32 and `strength` is finite in `[0,1]`.
The modified base colour enters PBR-lite first. Glow then adds `base' * F`.
Authored emissive remains separate. The existing full-screen Bayer pass remains
the final presentation operation.

The vertex shader must reuse the placement direction; Polar Bands must not add
another UGLUT2 texture fetch. CPU/native fallback and the Python reference use
the same coordinate and staged binary32 band formula.

## KCRP v1/v2 compatibility

KCPR v1-v4 bytes, operator meanings, content addresses, 128-byte recipe
records, and the 36-byte GPU instance stride are frozen by this feature.

KCRP v1 remains exactly 32 bytes and means Polar Material mode `off`. Existing
metadata containing none of the Polar Material keys continues to emit those
exact v1 bytes.

KCRP v2 is exactly 40 bytes. Its first 32 bytes retain the v1 field layout with
the version set to 2, followed by:

```text
offset  size  field
32      u8    polar material mode: 0=off, 1=bands
33      u8    radial band count: 1..32
34      u16   reserved, must be zero
36      f32   polar material strength: finite [0,1]
```

Mode `off` requires strength `+0.0`. A v1 header with a 40-byte body, a v2
header with a 32-byte body, unknown modes, nonzero reserved bytes, negative
zero, nonfinite values, truncation, and trailing bytes are rejected. An absent
KCRP asset retains the existing CPU/no-Bayer/no-Polar-Material fallback.

The authoring keys are `polar_material_mode`, `polar_material_bands`, and
`polar_material_strength` inside `project.metadata["substrate_render"]`. If any
one is present, all three are required so the v2 opt-in is explicit.

## Fallback and telemetry

GPU LUT and Direct variants evaluate the same fragment consumer. A GPU upload
failure or requested CPU polar mode supplies `P` through the ordinary vertex
path. Invalid coordinates fail closed to the authored material.

Render-substrate startup telemetry reports Polar Material mode, bands, and
strength separately from Glow, Grow, and Bayer. It must not report this feature
as LOD, connected geometry, or a gameplay field.
