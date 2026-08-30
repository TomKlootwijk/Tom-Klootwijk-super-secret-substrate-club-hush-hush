# UGTS source-to-engine mechanism map

Updated: 2026-08-30

This map answers a deliberately strict question: is a UGTS mechanism actually
used by the engine, merely planned, or inappropriate for this workload?  A
feature is not marked retained just because a similarly named class exists.

Status vocabulary:

- **Retained**: the source meaning and bounded representation are present and
  verified in an engine runtime.
- **Translated**: the source idea is used through a different representation
  suited to this engine, with the translation stated explicitly.
- **Active**: implementation exists in the worktree but final integration or
  target-device evidence is still running.
- **Deferred**: useful and in scope, but not implemented yet.
- **Rejected here**: forcing the mechanism into this application would make the
  engine less correct, less compact, or less usable.

| Source mechanism | Status | Engine application | Boundary / next evidence |
| --- | --- | --- | --- |
| SCLP bounded log-radius chart with an explicit core | **Retained** | `LogPolarProfile`, KCPK validation, UGLUT2, and one shared seven-case Python/native artifact cover the explicit core plus lower/middle/upper radius cases. Glow by distance translates a child-authored zero start to this clamped core instead of evaluating `log(0)`. | The physical LUT path now runs on Mali, but the exact seven-case values have not been read back from that driver. |
| Periodic polar angle and heading | **Retained on CPU/native host; Active on the GPU target** | theta18 and heading12 wrap canonically. Shared vectors cover both seams, and LUT shader source now reuses the same seam-safe log-encoded polar LUT direction lookup for packed heading while Direct keeps its trig baseline. | Host source/link checks do not prove Mali interpolation or seam appearance. |
| Packed pose and derivatives | **Retained** | One 64-bit pose plus one 64-bit motion word; sparse KCPK records cost 24 bytes including node/profile references. The vectors also freeze packed next-pose/next-motion evolution. | The target executed one exact KCPK workload; whole-process memory is measured, but representation-specific resident memory is not isolated. |
| Shared binary16 log-encoded polar LUT | **Retained on CPU/host and one physical GPU target slice** | UGLUT2 is generated once per profile and used by desktop/native CPU composition. GLES uploads each referenced RGBA16F profile once and reuses its direction samples for theta, heading and the seeded Glow material angle; Direct retains its cosine baseline and CPU fallback/reference uses quantized UGLUT2. | POCO telemetry proved effective LUT mode, one uploaded profile, 128 GPU instances and zero fallback at 120.33 FPS. Direct/LUT visual parity, seam-specific imagery and a full performance matrix remain open. |
| Bounded log-radius material field | **Translated and retained in one physical target slice** | Optional Make Many Glow by distance compiles Start/End/strength into a smooth log-radius pulse, combines it with a lineage-shifted periodic direction, and adds bounded `base colour × field` during scene lighting. Grow v4 consumes that exact field again as a 1x..5x generated-copy scale multiplier without changing placement or ECS identity. | The POCO screenshot/profile and telemetry prove Glow/Grow execution. Broader art-quality, Direct/LUT parity, electrical power and statistically isolated overhead remain open. |
| Analytic Cartesian velocity/acceleration from rho/theta derivatives | **Retained on CPU/native host; device parity unverified** | The shared seven-vector Python/native pass covers Direct/LUT position, velocity, acceleration, heading, clamps, seams, and fixed-step evolution; desktop 3D preserves authored Y. | Shader formula parity is source-only. Add physical target rendering and moving-body collision proof. |
| Metric, gradient, and exact radial differential operators | **Deferred** | Suitable for steering, collision gradients and richer procedural fields. Glow by distance is only a bounded smooth pulse in log radius; it does not claim the SCLP metric, Jacobian gradient or exact radial differential operator. | Define typed operator contracts before exposing beginner blocks. |
| Topological wrap and chart transition rules | **Partly retained** | Periodic angle wrap is retained; general multi-chart/topological transitions are not. | Needed before using the substrate for worlds that cross more than one bounded chart. |
| Morton/spatial address packing | **Deferred** | A candidate for spatial queries, streaming, field tiles, and recipe cache locality. | Do not mix it into pose packing until an actual query/streaming benchmark needs it. |
| UGTS 4.1 SplitMix64 random-access lineage | **Retained in bounded generators** | Populate Area, repeatable random Logic Blocks, and native KCPR Ring/Spiral/Polar Field/Radial Burst members use random-access lineage. Count is excluded only from the lineage namespace, so increasing a recipe count preserves its existing prefix. Glow reuses lane 5 for a count-independent 12-bit material phase without changing the spatial lineage namespace. | Publish broader cross-runtime vectors before reusing the scheme for other recipe families. |
| Foundation 5.0 content-addressed operators | **Retained for bounded KCPR; deferred generally** | KCPR392 stores a minimal canonical operator table plus full 128-bit recipe, profile, prototype, mesh, material and dependency addresses rather than per-copy graph blobs. V1/v2 stay byte-identical, Glow opts into v3, and Grow adds frozen code `0x0053` in v4 while retaining the 128-byte recipe and all prior identities. | General render/field operator schemas, migrations and reusable Saved Object/Scene recipes remain deferred. |
| GPU Native Addendum locality/line-pressure evidence | **Translated into strict acceptance gates with one physical baseline** | Direct and LUT share batching; runtime proof rejects wrong modes/counts, fallback, wrong Bayer settings, and unbounded materialization. The POCO Grow run reported 128 LUT GPU instances, two batches and zero CPU fallbacks at 120.33 FPS. | The driver exposed no usable timer query. Run repeated Direct/LUT/Bayer Off/Subtle cases before making GPU-cost, power or default-mode claims. |
| Bayer Direct 3.9.4 canonical 8x8 threshold order | **Retained in one physical target slice** | The final full-color GLES ordered-dither source and host shader-link checks use the canonical top-origin order. Glow/Grow resolve before this unchanged final pass; the POCO telemetry and screenshot prove Subtle/64/0.3 execution. | Rotation/orientation stability, Off-versus-Subtle cost, temporal crawling and intentional low-palette art direction remain open. |
| Bayer Direct CPU ANativeWindow RGB565/four-level hot path | **Rejected here** | The 3D engine keeps its GLES PBR/post path; only the threshold order and presentation-only authority rule are portable. | A Retro preset may deliberately reduce levels, but it must not be mislabeled RGB565. |
| Polar encoding for arbitrary topology, text, UI, and ordinary object metadata | **Rejected here** | Those domains retain representations that match their actual structure. | Use log-radius polar data for radial geometry, kinematics, fields, particles, materials, and scale-space operations where composition is real. |

## Required compact render chain

The target chain is:

`seed + bounded operator recipe + packed ECS state -> shared log-encoded polar
LUT -> instanced/procedural GPU work -> final Bayer projection`

The source and host evidence now cover packed ECS state, CPU log-encoded polar
LUT reconstruction, semantic graph access, the 32-byte seed/render-settings record, strict native
KCPR parsing/random access, and total-count-independent bounded visible staging.
KCPR feeds the Direct/LUT instancing and Bayer source paths, and the editor's
Make Many Inspector exposes Off plus the four non-Off patterns Ring, Spiral,
Polar Field, and **Radial Burst (loops)**, each with optional **Glow by distance**, without making
generated members selectable ECS entities. Its preview is globally capped at
64 generated copies and now follows the real packed prototype during desktop
Play by regenerating only those retained random-access items. It does not add
desktop interpolation or generated ECS state.

Glow by distance is the first bounded material application of this chain. It
is a modifier, not a renamed placement operator: Start/End compile to binary32
center-rho and inverse-half-width pulse lanes, strength is the third binary32
lane, and SplitMix lineage lane 5 derives one
repeatable 12-bit material phase. Enabling it preserves the spatial lineage
namespace while changing the full content address. KCPR v3 is emitted only
when the modifier is present; v1/v2 remain byte-identical, and the 128-byte
recipe record reuses its final 12 reserved bytes. Native visible-instance
staging adds one 32-bit phase attribute (32 to 36 bytes), not a stored matrix or
phase row for every requested copy.

Shared LUT samples the existing UGLUT2 direction for the shifted material
angle, Direct uses cosine, and CPU fallback/reference evaluates the quantized
UGLUT2 form. The bounded result is added as `base colour × field` during scene
lighting, with alpha untouched, before the unchanged final Bayer projection.
For Burst copies the band evaluates the copy's local packed rho before that
local pose compounds with the prototype anchor; the real prototype evaluates
its own packed rho. Separate native prototype/copy groups preserve that
composition instead of recomputing a Cartesian distance.

Radial Burst is bounded looping display data around one real ECS prototype,
not a one-shot gameplay event. Its local packed displacement compounds with
the prototype's packed anchor through log-encoded polar LUT semantics. Stopped
desktop authoring shows the deterministic midpoint; Play uses the real
post-step world tick and fixed endpoint without a synthetic alpha. Direct is
the baseline reconstruction path, LUT shares the profile upload, and Bayer is
still the final presentation pass. Burst limits are 512 instances per recipe,
16 recipes and 2,048 instances per project; native materialization is also
bounded by maximum-visible and the remaining particle budget. Opcode 30 hides
only the extra display copies.

Runtime copy visibility is a separate bounded control layer: opcode 30 changes
one bit in an eight-byte native mask and an equivalent desktop sidecar. It skips
a hidden KCPR recipe before random-access materialization while preserving its
content address, lineage, prefix and active ECS prototype.

The original nested-workspace CMake failure remains preserved evidence. The
benchmark harness now builds in a short system-temporary workspace, preserves
numbered attempts and exact outputs, and validates the flavor-suffixed AGP
application ID. Explicit SHA-1 build IDs plus normalized DWARF prefixes produced
byte-identical APK/native artifacts in two independent clean workspaces. The
current source also completed a unified 15-case 64/256/1024 CPU/Direct/LUT and
Bayer Off/Subtle build-only matrix.

A separate Burst matrix is defined as 32/128/384 × CPU/Direct/LUT × Bayer
Off/subtle, for 18 cases:

```powershell
python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
```

The preserved `built_only` run at
`build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de`
completed all 18 cases in 272 seconds. Each case records a 1,690-byte KCPK,
240-byte KCPR and 32-byte KCRP; APKs range from 1,804,558 to 1,804,566 bytes.
None was installed or executed on POCO/Mali, so physical rendering and all
performance comparisons remain unavailable.

`RUN_POLAR_GLOW_LAB.cmd` provides the shortest manual authoring/desktop check by
generating the project if absent, then opening a 128-display Burst/LUT/subtle-Bayer project with Glow
distance 0–4 and strength 1.25. Its exact v3 APK was later used as the same-phone
30-second A/B control and held 120.33 FPS; that single run is not a full Glow matrix or power study.

`RUN_POLAR_GROW_LAB.cmd` is the separate compounded-field check. Its v4 recipe reuses the exact
seeded log-radius Glow result as `clamp(1 + glow, 1, 5)` for generated display scale after ordinary
or Burst scaling. It adds no parameter lane, texture, LUT, GPU-instance bytes or ECS rows. The real
prototype is still Glow-lit but never grown. The generated manual project has one ECS prototype, 127
derived displays and a 304-byte KCPR with nine operator meanings. This is retained rendering
composition, not LOD and not connected Seeded Grove geometry.

The earlier preserved 15-case recipe run is still only build evidence: all its cases have null
FPS/profile fields and all 12 comparisons are unavailable. The separate 15-case Glow matrix is
defined but has not been executed or preserved:

```powershell
python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only
```

The v4 Grow matrix is likewise defined but has not been physically run in full:

```powershell
python validation/benchmark_polar_render_poco.py --workload grow --include-cpu --build-only
```

One representative v4 case is now physical evidence: the exact 128-display
Burst/LUT/Subtle APK ran on `2412DPC0AG` / Mali at 120.33 FPS with zero fallback,
KCPR v4, 127 grown GPU copies, a retained screenshot, bounded memory/CPU/thermal
samples and no crash. The driver reported timer queries unsupported, and no
Direct/LUT/Bayer comparison matrix or electrical power measurement exists. General
content-addressed operator systems beyond bounded KCPR also remain deferred;
KCRP settings alone do not reconstruct an entire scene.

## Acceptance rule

A mechanism moves to **Retained** only when its serialized meaning, desktop
behavior, native behavior, failure bounds, and evidence are all named.  Smaller
files alone do not prove substrate use, and visual similarity alone does not
prove deterministic parity.
