# Packed Polar Substrate Lab (3D)

This is an editable, dark 3D showcase for UGTS's compact log-encoded polar movement and rendering substrate.
The checked-in `project.json` contains **64 real static ECS mover nodes**. Each mover has
its own `packed_kinematic` component; none of them is a scatter-generated visual copy.

All movers share:

- one five-vertex, six-triangle `orbit_shard` mesh and one `orbit_cyan` material, which is the
  batch-friendly render case;
- one log-encoded polar profile and one 256-entry binary16 LUT;
- one four-block VisualGraph definition, bound owner-relatively 64 times.

The shared graph is intentionally easy to read:

`Every 1 second → read This object's Turns per second → multiply by -1 → write it back`

That makes every orbit reverse without copying the graph definition or exposing the raw
64-bit packed words. Radius, angle, speed, scale, and starting tick come from deterministic
SplitMix64-style per-object seed derivation. Eight rings are stacked around the same vertical
axis. The floor, centre spire, cap, and two neon axes are ordinary non-polar environment nodes.

## Open and play

From the repository root, double-click `RUN_UGTS_STUDIO.cmd`, then open:

`examples/packed_polar_gpu_lab_3d/project.json`

Press **Play**. The cyan shards orbit and reverse direction once per second. Select a mover
such as `orbit_mover_0000` to edit the object, its Movement Pattern, or its shared Logic Blocks.

## Verify the substrate

Run from the repository root:

```powershell
python examples/packed_polar_gpu_lab_3d/verify_example.py
```

The verifier checks all of these claims:

- the project validates and has no scatter population;
- exactly one profile/LUT backs exactly 64, 256, or 1024 packed components;
- exactly one graph definition compiles with N owner bindings;
- recompiling produces the same project, KCPK, KCVG, and render-pack hashes;
- KCPK growth is exactly 24 bytes for each added packed component;
- the render-substrate pack is exactly 32 bytes;
- desktop `instantiate_world`, fixed ticking, string/type ECS queries, dedicated
  **Read Movement** / **Change Movement** turn-speed access, and timer reversal
  all execute without storing the `polar_movement` component name in KCVG.

## Generate device A/B variants

`project.json` is the only checked-in workload. The generator creates exact 64, 256, or 1024
real-ECS variants on demand, so the repository does not carry three redundant giant JSON files.

```powershell
# Refresh the checked-in 64-object default.
python examples/packed_polar_gpu_lab_3d/generate_variants.py

# A: force LUT polar rendering and disable Bayer, writing outside the example.
python examples/packed_polar_gpu_lab_3d/generate_variants.py `
  --count 1024 --polar-mode lut --bayer-mode off `
  --output build/polar-lab-A-lut-off.json

# B: direct polar path with a custom 24-level, 0.55-strength Bayer treatment.
python examples/packed_polar_gpu_lab_3d/generate_variants.py `
  --count 1024 --polar-mode direct --bayer-mode custom `
  --levels 24 --strength 0.55 `
  --output build/polar-lab-B-direct-custom.json
```

Supported polar modes are `auto`, `lut`, `direct`, and `cpu`. Supported Bayer modes are
`off`, `subtle`, `retro`, and `custom`. `--seed` accepts decimal or `0x...` uint64 values.

## Generate the compact recipe version

The authored-ECS generator above intentionally stores one 24-byte KCPK row per
mover so ECS scaling can be measured honestly. The companion recipe generator
tests the other half of the substrate: one real packed ECS prototype plus one
tiny KCPR recipe generates the remaining display-only members.

```powershell
python examples/packed_polar_gpu_lab_3d/generate_recipe_variants.py `
  --count 1024 --preset ring --polar-mode lut --bayer-mode subtle `
  --output build/polar-recipe-1024-lut-subtle.json
```

For Ring and Polar Field the KCPR asset is 240 bytes at 64, 256, and 1024
instances; Spiral adds one 16-byte operator descriptor. KCPK stays unchanged
because the project still owns exactly one real mover. The full recipe address
changes with the count, while its lineage namespace does not, so increasing
the count preserves every earlier generated member. Generated members are
render data, not selectable gameplay/ECS objects.

### Radial Burst (loops)

The same generator can create the bounded looping Burst workload. It still
owns exactly one real packed ECS prototype:

```powershell
python examples/packed_polar_gpu_lab_3d/generate_recipe_variants.py `
  --count 384 --preset burst --polar-mode direct --bayer-mode off `
  --output build/polar-burst-384-direct-off.json
```

Legacy-only Ring, Spiral and Polar Field assets remain byte-identical KCPR v1.
Burst selects KCPR v2; a standalone one-Burst asset is 240 bytes. Its local
packed displacement compounds with the prototype anchor through log-encoded
polar LUT semantics. Direct is the baseline path, LUT shares the profile, and
Bayer remains the final presentation pass. This is a looping display effect,
not a one-shot gameplay event or a source of generated ECS objects.

Burst permits 512 instances per recipe, 16 recipes and 2,048 Burst instances
per project. The editor retains at most 64 Make Many preview copies globally;
native work is also bounded by maximum-visible and the remaining particle
budget. Stopped desktop preview shows the loop midpoint, while Play uses the
real post-step fixed tick and exact endpoint without a synthetic alpha.

### Glow by distance

Any Make Many pattern can optionally add a seeded material glow band. This is
the first recipe modifier that uses the shared log-encoded polar LUT for a
material value instead of only reconstructing placement:

```powershell
python examples/packed_polar_gpu_lab_3d/generate_recipe_variants.py `
  --count 128 --preset burst --polar-mode lut --bayer-mode subtle `
  --glow-by-distance --glow-start-distance 0 --glow-end-distance 4 `
  --glow-strength 1.25 `
  --output build/polar-glow-lab/packed-polar-glow-burst-128-lut-subtle.json
```

Open that JSON in UGTS Studio to edit the three values in **Make Many → Glow
by distance**. Start distance zero means the Movement Pattern's explicit core.
The recipe seed supplies a repeatable 12-bit angular phase; LUT mode samples
the existing UGLUT2 direction lane, Direct uses cosine as its comparison path,
and the bounded result is added during lighting. Bayer remains the final
screen-space presentation pass.

The modifier keeps the recipe record at 128 bytes and does not change spatial
lineage. Its standalone Burst asset is 288 bytes because KCPR v3 advertises
three additional 16-byte operator meanings. CPU fallback implements the same
quantized-LUT reference instead of silently omitting the effect. Build/source
tests still are not physical POCO/Mali visual or performance evidence.

The dedicated build-only matrix is defined as 32/128/384 instances across
CPU/Direct/LUT and Bayer Off/subtle, for 18 cases:

```powershell
python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
```

The preserved build-only run at
`build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de`
completed 18/18 cases in 272 seconds. Each case contains a 1,690-byte KCPK,
240-byte KCPR and 32-byte KCRP; APK sizes range from 1,804,558 to 1,804,566
bytes. None was installed or run on POCO/Mali, so this example still makes no
physical rendering or performance claim.

## Honest evidence boundary

This project proves the **authoring and data substrate**: real ECS components, semantic graph
access, graph reuse, deterministic compact packs, and desktop execution. Its shared mesh and
material are the intended batch-friendly case.

It does **not** by itself prove that work ran on the GPU, that LUT beats direct math, or that
1024 movers hold a target frame rate on a POCO X7 Pro/Mali GPU. Those claims require exporting
the chosen A/B variants through the Android render path and measuring them on the connected
phone. Keep thermal state, resolution, camera, quality tier, and test duration equal when
comparing modes.
