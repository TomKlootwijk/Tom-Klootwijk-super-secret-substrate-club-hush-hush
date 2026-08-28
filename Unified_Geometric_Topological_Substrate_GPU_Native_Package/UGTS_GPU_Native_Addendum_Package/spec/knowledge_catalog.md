# UGTS 1.1 Mechanism Catalog

**211 normalized mechanisms** extracted or technically translated from the corpus. Duplicate source variants are counted once.

## Architecture

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M116 | Query-first, no mandatory frame loop | RETAIN | S03 pp.1,5–12 |
| M117 | Optional projection | RETAIN | S03 pp.1,9–10; S04 |
| M120 | Schema-bound one-bit semantics | RETAIN | S05 p.7 |

## Audit

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M184 | 100% does not ordinarily equal 36 | CORRECTED | S01 pp.7–8 |
| M185 | 100101 versus 100100 inconsistency | CORRECTED | S01 pp.3–9 |
| M186 | Information entropy is not automatically heat | REJECT | S01 pp.17–24 |
| M187 | Absolute single vacuum claim | CORRECTED | S01 pp.25–29 |
| M188 | Zero-cost chromatic correction | REJECT | S04 pp.7–8 |
| M189 | Perfect alias elimination | REJECT | S04 pp.4–6 |
| M190 | Universal O(1) | BOUNDED | S03 pp.7–8; S08 pp.15–35 |
| M191 | Zero memory/latency/heat | REJECT | S05 pp.2,10; S08 |
| M192 | Perfect determinism/exact chaos | REJECT | S03 pp.8–11; S08 |
| M193 | One bit as complete state | REJECT | S05 pp.2,7; S08 |
| M194 | No broad phase ever | CORRECTED | S08 pp.28–35 |
| M195 | General AI/world replacement | REJECT | S03 pp.1,7–12; S05 p.10 |
| M196 | Biological one-bit equivalence | DEMOTE | S06/S07/S10 pp.13–24 |
| M197 | Physical-GPU benchmark boundary | RETAIN | Package benchmark |

## Complexity

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M113 | Horizon-independent closed expression | BOUNDED | S03 p.8 |

## Coordinate geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M049 | Base-2 log-radius | RETAIN | S01 pp.16–17; S04 pp.1–2 |
| M050 | Local spherical chart | RETAIN | S03 pp.5–7; S05 p.3 |

## Event calculus

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M087 | Relation surface | RETAIN | S03 pp.5–7 |
| M088 | Support predicate | RETAIN | S03 pp.5–7; S05 pp.3,6 |
| M089 | Compatibility predicate | RETAIN | S03 pp.5–7; S05 p.7 |
| M090 | Earliest valid event | RETAIN | S03 pp.5–7 |
| M091 | Transition operator | RETAIN | S03 pp.5–7 |
| M100 | Finite guard band | RETAIN | S05 pp.5–7; benchmark |
| M101 | Confidence threshold | RETAIN | S05 pp.3,6–7 |
| M102 | Hysteresis/debounce | RETAIN | S05 p.10; S01 pp.27–29 |
| M118 | Bounded Compatibility Event | RETAIN | S05 pp.3,5–7 |

## Field algebra

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M105 | SDF zero as event boundary | RETAIN | S03 pp.6–7; S06 pp.7–8 |
| M106 | CSG union | RETAIN | S04 p.2 |
| M107 | CSG intersection | RETAIN | S04 p.2; S02 pp.18–19 |
| M108 | CSG subtraction | RETAIN | S04 p.2 |
| M109 | SDF gradient orientation | RETAIN | S04 pp.2,4,9 |
| M110 | Parity-conditioned field blend | TRANSLATE | S06/S07/S10 pp.7–8 |

## Field geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M036 | Global hinge everywhere | TRANSLATE | S06/S07/S10 pp.7–8 |
| M063 | Cone SDF | RETAIN | S06/S07/S10 pp.7–8 |
| M064 | Sphere SDF | RETAIN | S03/S05; benchmark |

## Fluid threshold

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M058 | Pythagorean-cup trigger | RETAIN | S01 pp.27–29 |
| M059 | Greedy reset cycle | TRANSLATE | S01 pp.27–29 |

## GPU-native

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M125 | GLSL-to-SPIR-V compilation | RETAIN | Package gpu/shaders + gpu/spirv |
| M126 | Direct Vulkan compute runtime | RETAIN | Package gpu/src/ugts_vulkan_bench.cpp |
| M127 | Descriptor ABI | RETAIN | Package shader manifest |
| M128 | 256-thread workgroup | RETAIN | SPIR-V manifest |
| M129 | G64 authoritative state record | RETAIN | Package spec |
| M130 | E32 full event record | RETAIN | Package spec |
| M131 | G32 packed state record | RETAIN | Package spec |
| M132 | E16 packed event record | RETAIN | Package spec |
| M133 | Evaluate mode | RETAIN | Benchmark |
| M134 | Evaluate+commit mode | RETAIN | Benchmark |
| M135 | Device timestamp measurement | RETAIN | Benchmark |
| M136 | Pipeline cache artifact | RETAIN | Benchmark |
| M137 | SPIR-V module manifest | RETAIN | Package gpu/spirv/spirv_manifest.json |
| M138 | Lineage hash | RETAIN | Shader code |
| M139 | Dense output path | RETAIN | Benchmark |
| M140 | Verified-event compaction | TRANSLATE | Spec/derived metrics |
| M141 | Structure-of-arrays option | OPTIONAL | Spec |
| M142 | Memory coalescing contract | RETAIN | Spec |
| M143 | FP16 error contract | RETAIN | Spec/tests |
| M144 | Cold versus cache-seeded compilation | RETAIN | Benchmark |
| M145 | CPU reference oracle | RETAIN | Benchmark/tests |
| M146 | Deterministic benchmark corpus | RETAIN | Benchmark |
| M147 | No Unity/Godot target layer | RETAIN | User requirement |

## Glyph encoder

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M014 | Standard percent semantics boundary | RETAIN | S01 pp.1,7–8 |
| M015 | Percent loop decomposition | TRANSLATE | S01 pp.2–4 |
| M016 | Slash/phi removal operator | TRANSLATE | S01 pp.2–4 |
| M017 | Open-loop terminal suppression | BOUNDED | S01 pp.6–9 |
| M018 | 100100 concatenation | RETAIN | S01 pp.6–9 |
| M019 | Two-pulse timeline | TRANSLATE | S01 pp.9–10 |
| M020 | Pulse superposition by OR | RETAIN | S01 pp.6–10 |

## Glyph geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M028 | D-to-R cut and unroll | RETAIN | S06/S07/S10 pp.1–2 |
| M029 | B-to-R lower-loop unfurl | RETAIN | S06/S07/S10 p.1 |
| M030 | Phi loop-plus-stem decomposition | RETAIN | S06/S07/S10 pp.1–2 |
| M060 | Inward G/shelf transform | OPTIONAL | S06/S07/S10 pp.30–31 |

## Governance

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M124 | Query authority and policy | RETAIN | S03 pp.6,11 |

## Identity

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M075 | Lineage-based identity | RETAIN | S03 pp.5–8,11–12 |
| M076 | Split/merge lineage | RETAIN | S03 pp.8,11–12 |

## Indexing

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M111 | Log-polar LUT | RETAIN | S01 pp.16–22; S04 pp.1–8 |
| M112 | BST-to-flat-table translation | CORRECTED | S01 pp.15–22; S06/S07/S10 pp.5–6 |

## Information architecture

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M083 | Finite grammar | RETAIN | S03 pp.5–7,12 |
| M084 | L-system production | TRANSLATE | S06/S07/S10 pp.5–6 |
| M085 | Projective-phase state manifold | RETAIN | S03 pp.5–7 |
| M086 | Typed state tuple | RETAIN | S03 pp.5–7 |

## Kinematics

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M031 | Stem as cutting/rotation axis | RETAIN | S06/S07/S10 pp.1–2 |
| M032 | Side-view pyramid as delta triangle | TRANSLATE | S06/S07/S10 p.2 |
| M033 | Delta-T changing axis | TRANSLATE | S06/S07/S10 pp.2–4 |
| M034 | Loop-to-line release | RETAIN | S06/S07/S10 pp.2–4 |
| M035 | Localized parity hinge | RETAIN | S06/S07/S10 pp.3–4 |
| M037 | Split zero-centered oval | RETAIN | S02 pp.10–12 |
| M038 | Antisymmetric torsional wave | TRANSLATE | S02 pp.12–13 |
| M039 | 2π unrolled into two π arches | RETAIN | S02 pp.13–15 |
| M040 | 1:1 arch balance | BOUNDED | S02 pp.13–15 |
| M048 | Logarithmic spiral step law | TRANSLATE | S06/S07/S10 pp.5–6 |

## Memory

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M114 | Novelty-proportional retention | BOUNDED | S03 pp.8,11–12 |

## Metric geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M045 | Scaled 5–12–13 triangle | RETAIN | S01 p.5 |
| M046 | Leg ratio 2.4 | RETAIN | S01 pp.5,15 |
| M047 | Torque-cone angle | RETAIN | S01 pp.15–16 |

## Networking

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M121 | Deterministic rollback/replay | TRANSLATE | S08 pp.27–31; S03 pp.7–12 |

## Numeric/encoding

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M001 | Radix digit threshold | RETAIN | S09 pp.1–3 |
| M002 | Positional power weighting | RETAIN | S09 pp.1–4 |
| M003 | Literal binary glyph parse | RETAIN | S01 pp.2–4; S09 pp.3–4 |
| M004 | Left-shift pulse placement | RETAIN | S01 pp.4–9 |
| M005 | Zero-based offset/ordinal distinction | RETAIN | S02 pp.1–4 |
| M006 | Active-bit filtering | RETAIN | S09 pp.4–6 |
| M007 | Zero as inactive/silence metadata | TRANSLATE | S09 pp.4–5 |
| M008 | Binary 19 decomposition | RETAIN | S09 pp.3–5 |
| M009 | Phonetic-to-active-count map | BOUNDED | S09 pp.4–7 |
| M021 | Explicit-width complement | TRANSLATE | S01 pp.18–22 |
| M022 | Fractional scale correction | CORRECTED | S01 pp.11–16 |
| M023 | Packed fixed-width record | TRANSLATE | S06 pp.27–34; S07 pp.26–34 |
| M024 | Fixed-point financial boundary | RETAIN | S06 pp.27–30 |

## Numeric/fractal

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M010 | Pascal parity recurrence | RETAIN | S09 pp.6–9 |
| M011 | Sierpiński generation | RETAIN | S09 pp.6–14 |
| M012 | Combination count C(5,3) | RETAIN | S09 p.6 |
| M013 | Power-of-two scale boundary | RETAIN | S09 pp.1–9 |

## Numerics

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M103 | Certified/bracketed root solve | RETAIN | S03 pp.8–9,11–12 |
| M104 | Tangency and degeneracy handling | RETAIN | S03 pp.8–11; S05 p.10 |

## Overlap geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M041 | Lens intersection region | RETAIN | S02 pp.16–19 |
| M042 | Constructive interference interpretation | TRANSLATE | S02 p.18 |
| M043 | Tolerance/phase-slip buffer | TRANSLATE | S02 p.18 |
| M044 | Mutual-information domain | CORRECTED | S02 pp.18–19 |

## Persistence

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M092 | External novelty log | RETAIN | S03 pp.5–8,11–12 |
| M115 | Seed+grammar+log rebuild | RETAIN | S03 pp.7–12 |
| M119 | Event lineage record | RETAIN | S03 pp.5–8; S05 p.7 |

## Performance/cache

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M198 | Native device-clock L2 boundary | RETAIN | Package physical-GPU shader-clock runs |
| M199 | Native CUDA L2 cycle control | RETAIN | Package physical-GPU CUDA clock64 runs |
| M200 | Native CUDA L2 concurrency curve | RETAIN | Package physical-GPU CUDA concurrency runs |
| M201 | Native CUDA texture-path capacity control | RETAIN | Package physical-GPU CUDA texture/global runs |
| M202 | Dense 6-bit CUDA log-LUT packing | RETAIN | Package physical-GPU CUDA packed-log-LUT runs |
| M203 | Native CUDA sparse-stride effective residency | RETAIN | Package physical-GPU CUDA sparse-stride runs |
| M204 | Packed-LUT neighborhood occupancy curve | RETAIN | Package physical-GPU CUDA LUT line-occupancy runs |
| M205 | Sparse-LUT residency decomposition | RETAIN | Package physical-GPU CUDA sparse-address and one-code refinement runs |
| M206 | Sparse-LUT page-spaced address reach | RETAIN | Package physical-GPU CUDA page-span and page-stride runs |
| M207 | Sparse-LUT exact-stride alias control | RETAIN | Package physical-GPU CUDA non-power-of-two stride-skew runs |
| M208 | VMM-isolated virtual address reach | RETAIN | Package physical-GPU CUDA VMM-alias runs |
| M209 | Content-sensitive CUDA VMM compression | RETAIN | Package physical-GPU CUDA VMM compression probe and packed6 runs |
| M210 | Constant-pattern CUDA VMM compression | RETAIN | Package physical-GPU CUDA all-one VMM compression runs |
| M211 | Zero-sentinel texture validation guard | RETAIN | Package physical-GPU texture alignment and constant mismatch controls |

## Physical hardware

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M161 | Liquid overclad | RETAIN | S05 p.4 |
| M162 | Liquid-core guide | OPTIONAL | S05 p.4 |
| M163 | Input liquid lens | RETAIN | S05 p.4 |
| M164 | Solid photonic substrate | RETAIN | S05 pp.4,8 |
| M165 | 2×2 interferometric kernel | RETAIN | S05 pp.4,9 |
| M166 | Balanced detection | RETAIN | S05 pp.4,9 |
| M167 | Spherical-to-mode overlap | RETAIN | S05 p.5 |
| M168 | Coupled-mode evolution | RETAIN | S05 p.5 |
| M169 | Young–Laplace curvature | RETAIN | S05 p.5 |
| M170 | Maxwell field boundary | RETAIN | S05 p.5 |
| M171 | Actuation modes | RETAIN | S05 pp.4,8 |
| M172 | Measured B.C.E. guard | RETAIN | S05 pp.3,5–7 |
| M173 | Calibration and drift state | RETAIN | S05 pp.6–10 |
| M174 | Events per joule | RETAIN | S05 p.6 |
| M175 | Optical insertion loss | RETAIN | S05 pp.6,10 |
| M176 | Packaging failure controls | RETAIN | S05 pp.8,10 |
| M177 | Digital commit sidecar | RETAIN | S05 pp.4,7,9 |
| M178 | Fixed-function support engine | TRANSLATE | Derived architecture |
| M179 | Compatibility mask engine | TRANSLATE | Derived architecture |
| M180 | Event FIFO and lineage commit | TRANSLATE | Derived architecture |
| M181 | Fluidic threshold/reset endpoint | BOUNDED | S01 pp.27–29 |
| M182 | Explicit topology transfer map | RETAIN | S05 p.5 |
| M183 | Failure/kill criteria | RETAIN | S05 p.10 |

## Projection

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M148 | Cartesian-to-log-polar mapping | RETAIN | S04 pp.1–2 |
| M149 | One-bit sector activation | RETAIN | S04 pp.1–2 |
| M150 | Phasor coverage accumulation | CORRECTED | S04 pp.2–3 |
| M151 | Subpixel gradient alignment | TRANSLATE | S04 pp.4–6 |
| M152 | Pulse-density modulation | RETAIN | S04 pp.4–6 |
| M153 | Anisotropic delta-sigma | TRANSLATE | S04 pp.5–6 |
| M154 | Chromatic log-radius offset | RETAIN | S04 pp.7–8 |
| M155 | Wavelength-dependent phase | TRANSLATE | S04 pp.7–8 |
| M156 | Seeded stochastic blend | RETAIN | S04 pp.7–10 |
| M157 | Log-polar blue-noise screening | TRANSLATE | S04 pp.8–10 |
| M158 | SDF edge lock | TRANSLATE | S04 pp.9–10 |
| M159 | Dot-gain compensation | RETAIN | S04 p.10 |
| M160 | CMYK angular separation | RETAIN | S04 pp.9–10 |

## Pruning

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M098 | Support rejection | RETAIN | S03 pp.7–8; S05 p.6 |
| M099 | Compatibility rejection | RETAIN | S03 pp.6–8; S05 pp.6–7 |

## Query architecture

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M093 | state_at(t) | RETAIN | S03 pp.6–8 |
| M094 | next_event | RETAIN | S03 pp.6–8 |
| M095 | events_in_cone | RETAIN | S03 pp.6–7,11–12 |
| M096 | reachable relation query | RETAIN | S03 pp.6–7 |
| M097 | identity reconstruction | RETAIN | S03 pp.7–12 |

## Risk

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M122 | Algebraic closure | RETAIN | S03 pp.8,11 |
| M123 | Event/branch explosion | RETAIN | S03 pp.8,11 |

## Routing geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M053 | Four-chamber hourglass | TRANSLATE | S03 p.6; S08 pp.23–26 |
| M054 | Pinch event locus | RETAIN | S03 p.6; S05 pp.2–5 |
| M055 | Invariant eigen-axis | TRANSLATE | S03 p.6; S08 pp.21–25 |
| M056 | Swept phase arc | TRANSLATE | S03 p.6; S08 pp.23–25 |
| M057 | Trident 3-to-1 convergence | TRANSLATE | S01 pp.25–27 |

## Support geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M051 | Cone support | RETAIN | S03 pp.5–7; S08 pp.15–18 |
| M052 | Nested shell support | RETAIN | S03 pp.3–6 |

## Topology

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M065 | Möbius orientation reversal | TRANSLATE | S06/S07/S10 pp.4–6; S08 pp.10–14 |
| M066 | Klein gluing map | TRANSLATE | S03 pp.2,6; S05 p.5; S08 pp.7–14 |
| M067 | Same coordinate, different sheet | RETAIN | S03 p.6; S08 pp.15–19 |
| M068 | Non-orientable orientation bit | RETAIN | S03 pp.5–7 |
| M069 | Projected self-intersection | CORRECTED | S06/S07/S10 pp.5–10 |
| M070 | Double vacuum as incompatibility | RETAIN | S03 p.6; S08 pp.6–18 |
| M071 | Phase-separated co-location | RETAIN | S03 p.6 |
| M072 | Four-way routing partition | TRANSLATE | S03 pp.6–7 |
| M073 | Portal/gluing transition | RETAIN | S03 pp.5–7 |
| M074 | Branch transition | RETAIN | S03 pp.5–8 |
| M077 | Toroidal/poloidal chart labels | TRANSLATE | S01 pp.18–26 |
| M078 | Re-entry map | TRANSLATE | S01 pp.18–28 |
| M079 | Parity-controlled open/closed boundary | RETAIN | S06/S07/S10 pp.3–8 |
| M080 | Sphere eversion analogy | DEMOTE | S08 pp.10–12 |
| M081 | Physical Klein self-assembly | REJECT | S06/S07/S10 pp.9–12 |
| M082 | Topology-powered energy recycling | REJECT | S01 pp.25–29 |

## Topology geometry

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M061 | Lemniscate crossing | TRANSLATE | S09 pp.18–25 |
| M062 | Escher-style shrink to crossing | CORRECTED | S09 pp.20–27 |

## Topology/control

| ID | Mechanism | Status | Source basis |
|---|---|---|---|
| M025 | One-bit parity narrow role | RETAIN | S05 pp.2,7; S03 pp.5–7 |
| M026 | One-bit support mask | RETAIN | S04 pp.1–2 |
| M027 | Deterministic jitter seed | TRANSLATE | S04 pp.7–10 |
