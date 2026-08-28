# Operational mapping from the proposed architecture to KLB37

The source description combines real GPU techniques with speculative claims. This document defines a concrete testable interpretation. It does not claim that NVIDIA hardware natively implements this format or topology.

| Source phrase | KLB37 operational definition | Measured or checked by |
|---|---|---|
| Raw `uint32` bit-vectors | A host-created `std::vector<uint32_t>` copied to a raw CUDA allocation | Container bytes, payload hash, kernel timing |
| Packing without clear LUT boundaries | Fixed-width 37-bit records concatenated without byte/word alignment; record reads may cross three words | Cross-boundary unit tests, 4.625 payload bytes/point |
| Log-encoded polar LUT | Log-spherical point code: 11-bit log radius, 12-bit azimuth, 10-bit elevation | RMS/max reconstruction error, decode throughput |
| Swizzling / unswizzling | Morton sort for spatial order; self-inverse 16×16 XOR tile map for physical record order | Involution unit test; `u64` versus packed equality |
| L-system bifurcation on parity bits | Three-bit symbol plus stored even-parity bit; each traversal level derives a branch and updates turtle state | Exact branch hash and traversal throughput |
| Binary search tree | An implicit binary child recurrence. It is a workload generator, not a sorted-key lookup structure | Configurable `--depth`, deterministic checksum |
| Klein bottle | A discrete 2D quotient: x is periodic; crossing the y seam reflects x | Seam identity unit tests and forced seam crossings in the kernel |
| Cone lower-case phi sweep | Analytic infinite-cone signed field `r*cos(phi) - y*sin(phi)` | Accumulated query result and timing |
| Delta and change-of-change | `phase += velocity; velocity += acceleration` each level | `--time`, `--delta`, `--delta-delta` |
| Boundaryless memory loop | Legal in-bounds indexing on the discrete Klein domain; no out-of-buffer access is permitted | CPU reference, CUDA error checks, optional Compute Sanitizer |

## Record layout

```text
bit  0..10   q_rho     11-bit log radius
bit 11..22   q_theta   12-bit cyclic azimuth
bit 23..32   q_phi     10-bit elevation
bit 33..35   symbol     3-bit procedural/L-system symbol
bit 36       parity     parity of bits 0..35, producing even parity overall
```

The stream is:

```text
record0[37] record1[37] record2[37] ...
```

There is no byte or `uint32_t` alignment between records. The file contains two guard words so a branch-free decoder may safely fetch three adjacent words at the end of the payload.

## Spatial encoding

For point `p`, the packer computes a bounding-box center `c`, radius scale `s`, and:

```text
r     = length(p - c) / s
rho   = log(1 + k*r) / log(1 + k)
theta = atan2(z, x)
phi   = asin(y / length(p - c))
```

The default `k` is 15. `rho`, `theta`, and `phi` are quantized into the bit fields above. The decoded position is a point approximation; triangle connectivity, normals, colors, and material data are not stored.

## Two separate swizzles

1. **Morton ordering** sorts logical points by a 30-bit 3D Morton key. This improves spatial locality but changes point order.
2. **XOR tile swizzle** maps each logical 16×16 tile from `(row, col)` to `(row, col XOR row)`. Applying the same function again restores the logical index.

KLB37 does not claim control over NVIDIA's undocumented physical VRAM/texture tiling. It only controls addresses within its own global-memory buffer.

## Discrete Klein quotient

For logical grid dimensions `W × H`:

```text
K(x + W, y) = K(x, y)
K(x, y + H) = K(W - 1 - x, y)
```

This is a finite discrete analogue of one common square identification for a Klein bottle. It is not a claim that the memory itself has non-orientable physical topology.

## Per-query pipeline

Simplified pseudocode:

```text
key, node, phase, velocity, acceleration = seed(query)
for level in traversal_depth:
    x, y       = node coordinates plus key-derived seam jump
    logical    = klein_wrap(x, y)
    physical   = xor_swizzle(logical)              # packed mode
    code       = extract_37_bits(raw_uint32_stream)
    point, tag = log_spherical_decode(code)
    branch     = parity(key XOR tag XOR level)
    turtle     = lsystem_update(turtle, branch, symbol)
    phi        = sweep(phase, symbol, branch)
    sum       += cone_signed_field(point, phi)
    node       = binary_child(node, branch, symbol, key)
    phase     += velocity
    velocity  += acceleration
write(sum, branch_hash)
```

## Baselines and isolation

- `float` removes bit extraction and log-spherical decode while preserving topology, parity traversal, cone field, and turtle update.
- `u64` preserves log-spherical decode but stores one code per aligned 64-bit slot.
- `packed` adds continuous extraction and XOR physical mapping.

This separation helps identify whether compression saves enough memory traffic to pay for extraction and decode ALU.

## Metrics that matter

1. **Correctness:** payload hash, record parity, exact branch hash, exact `u64`/packed GPU result, CPU/GPU tolerance.
2. **Storage:** file bytes, padded records, bytes/input point, ratio against `float3`, reconstruction RMS/max error.
3. **Kernel performance:** milliseconds, queries/s, nominal bytes/s.
4. **Hardware counters:** DRAM/L2 throughput, cache hit rate, warp stall reasons, achieved occupancy, register count, instruction mix, and roofline position from Nsight Compute.
5. **Power sensitivity:** repeat under a fixed laptop power/performance mode and report the mode, because laptop GPU clocks and power limits vary by system.

## Claims this implementation cannot establish by construction

- It cannot prove 50:1–500:1 compression; the fixed record is 37 bits.
- It cannot force the complete scene into L2 or registers.
- It cannot bypass legal allocation boundaries or CUDA's memory model.
- It does not use Tensor Cores; this workload is scalar integer/FP32 address and field arithmetic.
- The cone function is an infinite-cone signed field, not an exact distance to a finite capped cone.
- The implicit binary traversal is not an ordered search over keys and therefore should not be described as an `O(log n)` lookup benchmark.
- The Stanford adapter drops faces, so source-file compression ratios are not equivalent mesh-codec ratios.

These limits make the experiment narrower, but also reproducible and falsifiable.


# KLSC1 SeedChain extension

Version 0.2.0 adds a persistence/deployment layer above the KLB37 record stream.

| Unified substrate mechanism | KLSC1 realization | Test/metric |
|---|---|---|
| Coordinates are not identity | Stable logical point index, base record metadata, node index, route, symbol, and ordered chain path remain distinct from reconstructed position | CPU oracle and lineage comparison |
| Closed dynamics may be recomputed | Per-node seed, finite grammar, cone phase, branch amplitude, absolute similarity predictor | `create` and `create-ply` chains |
| External novelty must be stored | Sparse signed residual records with point index and event seed | Novelty density and fitted-sequence verifier |
| Seed+grammar+log rebuild | Embedded KLB37 base + node table + bounded checkpoint/delta walk | Random-access reconstruction tests |
| Earliest/local event architecture | Direct point reconstruction followed by cone/radius support, route compatibility, and sphere-SDF guard | `klb_seedchain_bench --mode seed` |
| Compact verified event log | One 16-byte event per verified point using atomic append | Event yield and compact output bytes |
| Precision contract | Base quantization plus residual threshold/quantum must stay below event guard | RMS/max sequence error and CPU/GPU tolerance |
| Lineage checksum is not durable identity | 32-bit lineage remains a compact check; full node order and novelty records are retained separately | Hash/link validation |
| Novelty-proportional retention | File growth is driven by sparse residual snapshots/deltas rather than dense frames | Bytes/point-frame and ratio versus dense sequence |
| Kill criteria | Dense novelty, error, chain stalls, and atomic cost can invalidate the design | Deployment document and profiler scripts |

## SeedChain reconstruction

```text
base point code
    -> log-spherical decode
    -> parity grammar and one-bit route
    -> Klein seam orientation and phase
    -> optional generated cone deformation
    -> absolute node predictor
    -> checkpoint snapshot + parent-linked novelty deltas
    -> reconstructed state
```

The frame predictor is absolute rather than incrementally accumulated. This avoids long floating-point drift and makes random access independent of motion replay. The residual correction is chain-linked, because each non-checkpoint stores a delta from the preceding residual state and each checkpoint stores a current sparse snapshot.

## Practical event deployment

The direct kernel is a compact state-and-event application rather than a renderer:

```text
reconstruct point at selected node
-> reject outside radial/angular support
-> reject incompatible route
-> evaluate sphere SDF guard band
-> append verified compact event
```

Projection to PLY is optional and performed only by `klb_seedchain export`.

## Compression interpretation

For `P` points, `F` frames, `N` novelty records, and `W` base words:

```text
KLSC1 bytes = 256 + 96*F + 16*N + 4*W
float3 sequence bytes = 12*P*F
```

A large ratio is meaningful only when the sequence is reconstructible under the declared predictor and error budget. The included 207.321330× result is a generated-chain measurement, while `fit-sequence` is the test for externally supplied motion.
