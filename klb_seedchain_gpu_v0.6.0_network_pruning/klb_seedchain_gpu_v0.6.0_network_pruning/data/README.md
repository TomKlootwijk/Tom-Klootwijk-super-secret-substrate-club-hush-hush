# Included data

## `procedural_65536.klb`

A generated 65,536-point KLB37 base stream used by the original architecture benchmark.

- 37-bit continuous records in a `uint32_t` word stream.
- Log-spherical position quantization.
- Morton logical order and 16×16 XOR record swizzle.
- SHA-256 and detailed values are in `procedural_65536.manifest.json`.

## `procedural_65536_240f.klsc`

A 240-node KLSC1 deployment chain built from the KLB37 base.

- 16-frame checkpoint stride.
- Maximum novelty parent depth: 15.
- Deterministic predictor/grammar motion.
- Sparse generated novelty impulses and inverse events.
- 910,392-byte container.
- SHA-256 and detailed values are in `procedural_65536_240f.manifest.json`.

The reported 207.321330× ratio compares this reconstructible generated sequence against storing all 240 frames as dense `float3`. It is not an arbitrary animation compression claim.

Inspect without creating a large decoded file:

```bash
./build/klb_seedchain inspect data/procedural_65536_240f.klsc
```

Export a single frame only when needed:

```bash
./build/klb_seedchain export data/procedural_65536_240f.klsc 239 frame_0239.ply
```

Run the GPU deployment benchmark:

```bash
./build/klb_seedchain_bench data/procedural_65536_240f.klsc \
  --frame 239 --mode all --repeats 20
```

`*.build.txt` and `*.inspect.txt` capture the preparation-time CPU tool output for the included chain.

## `orbit/`

The practical v0.3 application uses an actual CelesTrak GPS Operational OMM CSV snapshot, a 3,809-byte KLOC1 orbital seed container, and a generated coarse pass-event schedule. See [`orbit/README.md`](orbit/README.md).

## `sgp4/`

The v0.5 application replaces the coarse KLOC1 orbit predictor with full
SGP4/SDP4 reconstruction from compact OMM mean-element seeds.

```text
gps_ops_2026-08-16_7d_1s.ksgp
  5,793-byte, 32-object KSGP1 seed container

gps_ops_2026-08-16_52N_5E_full_sgp4_pass_events.csv
  717 acquisition/loss events from a seven-day, one-second CPU query

gps_ops_2026-08-16_coarse_vs_full_sgp4.csv
  per-object comparison showing the removed v0.3 surrogate error

vallado_branch_vectors_24h_60s.ksgp
  five-object branch-coverage container: near, deep non-resonant,
  synchronous, half-day, and GPS-like
```

Inspect and verify:

```bash
./build/klb_sgp4 inspect data/sgp4/gps_ops_2026-08-16_7d_1s.ksgp
./build/klb_sgp4 verify data/sgp4/gps_ops_2026-08-16_7d_1s.ksgp
```

The `.sha256`, `.inspect.txt`, `.verify.txt`, and summary files are included so
the delivered data can be checked without relying on earlier chat claims.

## `network/`

Version 0.6.0 adds a mixed-orbit, multi-station relation-pruning challenge.
See [`network/README.md`](network/README.md).

Key files:

```text
celestrak_mixed_58obj_7d_60s.ksgp
benchmark_station_network.csv
mixed_network_pair_plan.csv
mixed_network_7d_60s_events.csv
mixed_network_7d_60s_cpu_metrics.csv
```
