# Current deployment analysis: why the v0.2 test did not yet find the useful bottleneck

## Executive finding

The uploaded RTX 5070 Ti Laptop results prove that the original KLB37/KLSC1 path runs correctly on compute capability 12.0 and that compressed and dense event results agree. They do **not** yet show a throughput advantage. The test is dominated by a 65,536-candidate, single-frame dispatch whose kernels complete in roughly 0.01–0.05 ms. At that size the reported billions of candidates per second are useful as a correctness smoke test, but they are too close to launch/timestamp granularity to establish a sustained crossover.

The practical failure is not the 37-bit packing itself. It is a workload/predictor mismatch:

- the synthetic sequence is highly reconstructible, so its 207.32x storage ratio is real for that generated sequence;
- the runtime still queries only one 65,536-point frame at a time;
- parent-chain depth and novelty lookup add work before each point query;
- the fitted real PLY sequence is not explained well by the current global scale/Y-rotation/translation predictor, so residual novelty becomes dense;
- the benchmark compares a reconstructed query against a dense frame already in VRAM, but does not force the dense path to carry a large multi-time working set or include materialization cost.

Version 0.3 therefore keeps KLSC1 for its intended sparse-deformation niche and adds a different application whose state is genuinely seed-reconstructible: orbital state and ground-visibility events.

## Evidence from the uploaded RTX 5070 Ti Laptop run

The raw files are preserved under `benchmarks/rtx5070ti_v0.2/`.

| Case | Direct compressed | Dense query | Direct/dense | Storage result |
|---|---:|---:|---:|---:|
| Synthetic frame 239, 65,536 points | 0.041238 ms | 0.013246 ms | 3.11x slower | 207.32x smaller than all dense float3 frames |
| Synthetic, chain depth 0 | 0.014519 ms | 0.011493 ms | 1.26x slower | same container |
| Synthetic, chain depth 15 | 0.039117 ms | 0.012319 ms | 3.18x slower | same container |
| Fitted bunny sequence, first fit | 0.051279 ms | 0.012492 ms | 4.10x slower | 0.79x: the chain is larger than dense float3 |
| Fitted bunny sequence, tuned fit | 0.045071 ms | 0.012072 ms | 3.73x slower | 1.70x smaller |

The depth sweep is especially informative. Moving from a checkpoint/root frame to a depth-15 frame raises direct query time by about 2.69x, while the dense query remains nearly flat. This is the expected cost of bounded parent traversal and novelty lookup; it is not a GPU memory-bandwidth win by itself.

The 100%-event-yield test also completes in roughly 0.041 ms. That means the old test still does not provide a long enough interval to characterize compaction/atomic contention or thermal steady state.

## Root causes in v0.2

### 1. Too few candidates per timed interval

A 65,536-point launch does not fill a sustained benchmark window on this GPU. The measured kernels complete in tens of microseconds. A useful test should run tens to hundreds of milliseconds per sample or automatically repeat kernels inside each timed sample.

### 2. Storage ratio and query-time workload are different denominators

The 207.32x ratio compares one compressed chain against all 240 dense frames. The runtime comparison reads only one frame. The dense path therefore receives the storage disadvantage in the ratio but not the transfer/materialization disadvantage in the timed query.

### 3. The predictor is too narrow for arbitrary deformation

The fitter models uniform scale, one-axis rotation and translation. Real vertex motion outside that family becomes sparse residuals only when the motion is actually sparse. Otherwise the novelty log can equal or exceed dense storage.

### 4. Parent-linked novelty is paid per reconstructed point

At depth 15 the kernel performs the base decode, grammar/topology work, transform, and a bounded set of novelty searches. This is sensible for random access to sparse corrections, but not for a workload where nearly every point changes unpredictably.

### 5. The test does not isolate the real decision

The practical decision is not “is procedural arithmetic faster than reading a float4 already in VRAM?” It is:

```text
store and read a large dense time series
versus
retain compact seeds and reconstruct only the requested state/events
```

The new benchmark reports direct seed query, dense materialization, dense query, and materialization-plus-query separately.

## v0.3 corrective application

Version 0.3 packs an actual CelesTrak GPS operational OMM CSV snapshot into KLOC1:

- 32 operational GPS objects;
- 64-byte mean-element seed records;
- seven 64-byte hash-linked daily timeline nodes;
- a 7-day, 1-second query horizon;
- direct ground visibility and elevation-guard crossing events;
- a 3,809-byte container representing a reconstructible 309,658,112-byte dense float4 position working set for that declared horizon.

The last number is a **horizon-relative model expansion ratio**, not lossless compression of a pre-existing trajectory file. It is meaningful because both paths answer the same declared state/event query under the same bundled predictor.

## Benchmark changes that remove the self-imposed bottleneck

`klb_orbit_bench` adds:

- 19.35 million candidates for the actual 7-day file preset;
- 33.55 million candidates and about 512 MiB of dense positions for the laptop preset;
- 134.22 million candidates and about 2 GiB of dense positions for the VRAM preset;
- automatic inner repeats so every distribution sample runs for at least 150 ms by default;
- p50, p95 and p99 timing instead of a single micro-dispatch number;
- direct seed, dense materialization, dense query, and end-to-end dense modes;
- block-reduced counters instead of one global atomic for every candidate;
- optional warp-aggregated compact event output;
- exact direct-versus-dense counter comparison and a CPU oracle prefix;
- a VRAM safety check before allocating the dense baseline.

The laptop and VRAM presets repeat the bounded seven-day timeline to create load. They are stress tests, not longer physical predictions.

## Promotion criteria

Promote the orbit-seed path only when all of the following hold on the laptop:

1. CPU, direct GPU and dense GPU counters match exactly for the same predictor.
2. Compacted direct and dense event sets match by epoch, NORAD ID, event type and lineage.
3. Direct seed query plus its small resident seed set beats or justifies the dense materialization/storage path at the target query frequency.
4. The predictor error is below the application’s event margin.
5. The SGP4 reference comparison, when added, does not change pass/event ordering beyond the declared budget.
6. Nsight Compute shows that register pressure, transcendental throughput, atomics or occupancy do not erase the memory advantage.

Do not promote it when the dense path is cheaper at equal error, when the model is not reconstructible, or when the required accuracy is navigation-grade without an SGP4/precise-ephemeris predictor.
