# SeedChain deployment: direct compressed point-sequence queries

## 1. Practical application

The implemented application is a **time-varying point-cloud event server** for a CUDA GPU. A client selects a frame/node and asks which reconstructed points satisfy a local query:

```text
radial support
AND angular cone support
AND route compatibility
AND abs(sphere SDF) <= epsilon
```

Only verified points are appended to a compact event buffer. The complete dense sequence is never required in VRAM. This is useful as a test bed for:

- animated LiDAR or depth-scan point sets with stable correspondence;
- procedural vegetation, particles, branching structures, and repeated mechanical motion;
- spatial culling for downstream rendering, collision candidates, or local analysis;
- deterministic rollback/replay where closed motion is regenerated and external edits are logged;
- storage-limited laptop experiments where a multi-frame point sequence would otherwise consume substantial VRAM or disk.

It is not a complete mesh, video, Gaussian-splat, or general point-cloud codec. It currently preserves point positions only.

## 2. Mapping of the substrate to executable operations

| Substrate concept | Deployment operation |
|---|---|
| Seed + finite grammar | A base KLB37 stream plus a deterministic `chain_seed` and four-step pointer-free grammar in each frame query |
| Generative address | Stable point index, base record code, frame/node index, route, symbol, and ordered parent path |
| Log-polar/local spherical support | 11-bit log radius, 12-bit azimuth, and 10-bit elevation decoded around a stored center |
| Parity hinge | Stored parity and lineage-derived parity select a one-bit route during the grammar walk |
| Flat BST | Four direct bit decisions; no device pointers or heap traversal |
| Klein gluing | Azimuth wraps normally; crossing the elevation seam reflects azimuth and flips local orientation |
| Swept cone | A time/node phase and topology phase modulate an analytic cone field used for deformation |
| Transition/node | One 96-byte frame record containing predictor, seed, parent, checkpoint, and integrity metadata |
| Novelty log | Sorted 16-byte sparse residual records keyed by point index |
| Rebuild | Decode base, run grammar/topology/predictor, then accumulate novelty from the target node back to its checkpoint |
| Bounded event | Cone/radius support, route compatibility, SDF guard, then compact append |

The topology is a routing/address transform. It does not alter CUDA allocation boundaries and never permits out-of-bounds access.

## 3. Chain structure

A KLSC1 chain has four consecutive regions:

```text
[256-byte header]
[96-byte node 0][96-byte node 1] ...
[16-byte sparse novelty records ...]
[embedded KLB37 uint32 word stream]
```

Node `i` names node `i-1` as its parent, except node zero. `parent_hash` commits to the preceding node’s `self_hash`. The node hash includes the node fields, parent hash, and that node’s novelty records. This provides deterministic ordered integrity, not cryptographic authentication.

Motion/predictor fields are stored as absolute per-frame values. Sparse residual state is chain-linked:

- a checkpoint contains the current non-zero residual snapshot;
- a non-checkpoint contains only residual deltas introduced at that frame;
- reconstruction walks at most `checkpoint_stride - 1` parent links plus the checkpoint;
- the implementation caps checkpoint stride at 64.

This avoids unbounded replay while retaining most of the seed/log storage advantage.

## 4. GPU reconstruction path

For one point and one target node:

```text
logical point index
    -> optional XOR unswizzle
    -> extract continuous 37-bit base record
    -> log-spherical decode
    -> fixed four-level parity grammar
    -> discrete Klein coordinate and orientation
    -> swept cone/grammar deformation
    -> per-node scale + Y rotation + translation
    -> binary search target node's novelty range
    -> repeat novelty lookup through parents to checkpoint
    -> reconstructed position + compact lineage + route
```

Each novelty range is sorted by point index. The per-node lookup is therefore a binary search rather than a scan. The parent count is bounded by the checkpoint contract.

## 5. Query kernels

### 5.1 `decode`

`reconstruct_kernel` writes one `GpuPoint` per point:

```cpp
struct GpuPoint {
    float x, y, z;
    uint32_t lineage_and_route;
};
```

This isolates reconstruction cost and produces a reusable materialized frame.

### 5.2 `query_seedchain`

The kernel reconstructs the point and immediately evaluates:

```text
local      = position - center
r          = length(local)
cos_axis   = dot(local, axis) / r
support    = r <= support_radius && cos_axis >= cone_cos
compatible = route_filter == any || route == route_filter
sdf        = r - sphere_radius
guard      = abs(sdf) - epsilon
verified   = support && compatible && guard <= 0
```

A verified point atomically appends a 16-byte event:

```cpp
struct CompactEvent {
    uint32_t point_index;
    uint32_t lineage_and_route;
    float sdf;
    float guard;
};
```

This mode measures compressed reconstruction, event evaluation, and compact append together.

### 5.3 `query_dense_frame`

The same event test runs over an already materialized frame. Materialization is outside the timed section. Comparing this with `query_seedchain` gives the direct compressed-query penalty or advantage for the selected node, novelty density, checkpoint depth, and query yield.

With `--mode all`, the benchmark performs an untimed exact event-set check by downloading both compact outputs, sorting by point index, and requiring matching point identities, lineage/route values, and SDF/guard values within a small floating-point tolerance. `--verify-events N` bounds the number of events downloaded; the default is 1,048,576.

## 6. Included chain: what 207× means

The included 65,536-point, 240-frame sample occupies 910,392 bytes. A dense `float3` representation of every point in every frame would occupy:

```text
65,536 * 240 * 12 = 188,743,680 bytes
```

Therefore:

```text
188,743,680 / 910,392 = 207.321330x
```

The ratio comes from reconstructibility, not from fitting arbitrary frames:

- one base state is stored;
- each frame adds 96 bytes of deterministic node state;
- only 0.232054% of point-frames have a stored novelty record;
- checkpoint snapshots repeat only currently active residuals.

For an arbitrary sequence, the ratio can collapse toward or below 1× when residuals become dense. The fitted-sequence path is the required reality check.

## 7. Fitting actual data

### 7.1 Input contract

`fit-sequence` expects:

- one PLY file per frame;
- identical vertex counts;
- stable vertex order/correspondence;
- finite x/y/z values;
- frames listed in chronological order.

Faces and other PLY properties may exist but are ignored.

### 7.2 Current predictor

For each frame, the CPU fitter estimates:

```text
uniform scale
Y-axis rotation
translation x/y/z
```

The base is the decoded 37-bit representation of frame zero, not the original floating-point frame. This ensures CPU and GPU reconstruct the same predictor base.

For point `p_i` and target `q_i`, the residual is:

```text
residual_i = q_i - similarity_y(decoded_base_i)
```

Residuals at or below the configured threshold are omitted. Others are quantized to signed 16-bit x/y/z components using one global novelty quantum.

### 7.3 Error validation

The post-fit verifier reconstructs every point-frame and reports:

- global RMS Euclidean position error;
- maximum Euclidean position error;
- RMS and maximum error divided by base radius;
- worst frame and point index.

A useful acceptance test is:

```text
maximum reconstruction error < event guard margin
AND event order/classification matches the dense reference
```

Position error alone is not sufficient when two events are close in time or guard distance.

## 8. Checkpoint tuning

Let `C` be checkpoint stride, `S_f` be non-zero residuals at checkpoint `f`, and `D_f` be changed residuals at a non-checkpoint frame.

Approximate novelty records are:

```text
sum(checkpoint |S_f|) + sum(non-checkpoint |D_f|)
```

Maximum parent depth is:

```text
C - 1
```

Trade-off:

- lower `C`: more snapshots, fewer parent lookups;
- higher `C`: fewer snapshots, more binary searches and dependent node loads;
- high residual persistence favors larger `C`;
- high random-access/query frequency may favor smaller `C`.

Test at least `C = 4, 8, 16, 32, 64` on the target data and GPU.

## 9. Quantization tuning

`--novelty-quantum` is a ratio of base radius. World quantum is:

```text
quantum_world = base_radius * novelty_quantum_ratio
```

Each residual component must fit signed 16-bit range. If conversion reports overflow, increase the quantum or split the sequence into segments.

`--residual-threshold` is also a base-radius ratio. It controls sparsity, while quantum controls retained residual precision. They should be tuned independently.

Suggested sweep:

```text
quantum:   0.000025, 0.00005, 0.0001, 0.0002
threshold: 0, 0.0005, 0.001, 0.002, 0.004
```

For each pair, record file bytes, novelty density, RMS/max error, direct-query time, and event mismatches.

## 10. RTX 5070 Ti Laptop deployment sequence

1. Set the laptop to a fixed performance/power mode and connect AC power.
2. Record driver version, CUDA runtime version, power mode, ambient/starting temperature, and selected device.
3. Build with CUDA Toolkit 12.8+ and `sm_120` plus PTX fallback.
4. Run CPU tests.
5. Inspect the included chain.
6. Run `klb_seedchain_bench` with verification enabled.
7. Repeat at checkpoint depths 0, 7, 15, 31, and 63 where available.
8. Profile `seed` and `dense` separately with Nsight Compute.
9. Test real PLY geometry using `create-ply`.
10. Fit an actual stable-correspondence sequence and run `verify-sequence`.
11. Compare against dense storage and an appropriate conventional codec at equal error.
12. Apply the kill criteria before treating the result as a deployment win.

## 11. Metrics to record

### Storage

```text
container bytes
base-word bytes
node bytes
novelty bytes
bytes per point-frame
ratio versus dense float3/float4
ratio versus source PLY sequence, when fitted
novelty records per frame
novelty density
```

### Correctness

```text
base payload hash
terminal chain hash
CPU/GPU RMS and max difference
lineage/route mismatch count
fitted-sequence RMS and max error
exact compressed/dense event-set mismatches
```

### Performance

```text
decode point rate
compressed candidate query rate
dense-frame candidate query rate
verified event yield
compressed query / dense query time ratio
DRAM bytes and throughput
L2 hit rate
register count and occupancy
warp stall reasons
atomic serialization
power and temperature state
```

## 12. Expected bottlenecks

The direct kernel combines several expensive operations:

- cross-word bit extraction;
- exponentials and trigonometric reconstruction;
- parity-dependent control flow;
- binary searches in sparse ranges;
- dependent parent-node loads;
- transcendental procedural deformation;
- compact-output atomic appends.

The storage win can coexist with a compute loss. The application is successful only when the avoided dense storage/transfer/materialization is more valuable than these costs.

## 13. Kill criteria

Reject or redesign the deployment when:

- novelty density grows faster than avoided dense materialization;
- checkpoint snapshots dominate storage;
- maximum error exceeds the query guard margin;
- quantization changes event membership or ordering;
- direct query is too slow for the application latency budget;
- atomic compaction dominates the kernel;
- parent-chain dependency stalls dominate and cannot be hidden;
- input correspondence is unstable;
- topology changes need remeshing/reindexing that the current point-index model cannot represent;
- a conventional delta, geometry, point-cloud, or video codec is better at equal error and required access pattern.

## 14. Extensions with the highest practical value

The next useful engineering extensions are:

1. segment-level or cluster-level predictors instead of one global Y similarity;
2. arbitrary 3D rigid transform fitting with quaternions;
3. per-cluster quantization and residual bounds;
4. a GPU block/warp compactor using ballot and prefix allocation;
5. a structure-of-arrays novelty layout for cache locality;
6. event-order oracle comparison between compressed and dense paths;
7. optional face/index streams for stable-topology meshes;
8. cryptographic content hashes or signed manifests when provenance matters;
9. direct Vulkan/SPIR-V implementation sharing the KLSC1 ABI;
10. streaming chain segments from host storage for sequences larger than VRAM.
