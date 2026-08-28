# OrbitSeed deployment: a practical chain-linked seed application

## Application

The KLOC1 application answers coarse satellite state and ground-visibility queries from compact orbital seeds instead of storing every satellite position at every time step.

The included source is a snapshot of CelesTrak's GPS Operational general-perturbations data in OMM-style CSV. The packed file contains 32 operational GPS records and a seven-day hash-linked timeline. The source is small enough to refresh manually and the adapter has no third-party parsing dependency.

This is useful for:

- GPU compression/crossover testing with real time-varying state;
- coarse visibility and acquisition/loss scheduling;
- testing event compaction, lineage and support/compatibility rejection;
- developing a later SGP4 GPU adapter without changing the KLOC1 container/query ABI.

It is **not** suitable for navigation, collision avoidance, safety of flight, antenna pointing with tight error budgets, or any use that requires authoritative ephemerides.

## Canonical substrate mapping

```text
OMM mean-element seed + stable NORAD identity
        |
        v
hash-linked daily timeline node
        |
        v
closed deterministic predictor at requested time
        |
        v
analytic slant-range support
        |
        v
optional route-sector compatibility
        |
        v
elevation guard: sin(mask) - sin(elevation)
        |
        v
bounded sign crossing
        |
        v
acquire/loss event + timeline lineage
```

The fields map to the query-first substrate as follows:

| Substrate stage | Orbit implementation |
|---|---|
| finite grammar / typed state | versioned OMM seed record and predictor model ID |
| support | maximum station-to-satellite slant range |
| compatibility | optional route-sector filter |
| relation guard | elevation-mask sine minus observed elevation sine |
| verified event | bounded sign change between adjacent samples |
| transition | acquisition or loss |
| lineage | hash of seed lineage, timeline node, epoch and event type |
| novelty | a refreshed external OMM element set; current v1 stores a new packed snapshot rather than an in-place delta append |

The six route sectors are deterministic RAAN bins used only as a compatibility/routing workload. They are **not** official GPS orbital-plane labels.

## Predictor

The included host/device predictor performs:

1. fixed-iteration Kepler equation solution;
2. precomputed secular J2 rates for RAAN, argument of perigee and mean anomaly;
3. perifocal-to-ECI rotation;
4. Earth rotation for the station frame;
5. slant range and elevation guard evaluation.

It uses fixed loop counts and the same float operations on CPU and CUDA to make oracle comparison deterministic. CelesTrak GP elements are designed for SGP4. The bundled predictor is deliberately labeled `kepler_j2_secular_coarse`; replacing it with SGP4 is the accuracy upgrade path.

## Included container

`data/orbit/gps_ops_2026-08-16_7d_1s.kloc`

```text
source records                 32
KLOC1 bytes                    3,809
seed bytes                     2,048
hash-linked nodes              7 x 64 bytes
reference epoch                2026-08-16T05:33:12.693024Z
timeline duration              604,800 seconds
timeline step                  1 second
state samples                  604,801
equivalent dense float4        309,658,112 bytes
horizon-relative ratio         81,296.432659x
source SHA-256                 f45d43705e1cdc9121eb17d15baa3bc0ad0d97e0c21e94a78c44d4ddd6ddb8fb
KLOC1 SHA-256                  fe0036df05ad0f4036f8cfcf489a3d371557924bd8868f00c8e525cf6d2c6f73
```

The ratio is relative to the declared dense reconstruction horizon. It does not mean an existing 295 MiB trajectory was losslessly compressed to 3.8 KiB.

## Included useful output

`data/orbit/gps_ops_2026-08-16_52N_5E_pass_events.csv` contains the coarse acquisition/loss schedule generated for:

```text
station latitude               52 degrees north
station longitude              5 degrees east
station altitude               0.05 km
elevation mask                 10 degrees
sampling step                  1 second
candidate intervals            19,353,600
visible sample states          5,498,030
acquisition/loss events        717
```

Reproduce it without CUDA:

```bash
./build/klb_orbit passes data/orbit/gps_ops_2026-08-16_7d_1s.kloc \
  --lat 52 --lon 5 --alt-km 0.05 \
  --elevation-deg 10 --crossing-band-deg 0.25 \
  --hours 168 --step-seconds 1 \
  --output pass_events.csv
```

## Repacking a manually downloaded snapshot

CelesTrak query:

```text
https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV
```

Pack it:

```bash
./build/klb_orbit pack-omm-csv gps_ops.csv gps_ops.kloc \
  --horizon-hours 168 \
  --step-seconds 1 \
  --tile-hours 24

./build/klb_orbit verify gps_ops.kloc
./build/klb_orbit inspect gps_ops.kloc
```

The fetch scripts refuse to overwrite an existing snapshot unless explicitly forced, to avoid unnecessary repeated requests.

## Sustained RTX benchmark

Actual seven-day horizon:

```bash
./build/klb_orbit_bench data/orbit/gps_ops_2026-08-16_7d_1s.kloc \
  --preset file --query crossing --mode all --write-events \
  --samples 9 --min-sample-ms 150 --csv orbit_file_results.csv
```

Laptop stress preset:

```bash
./build/klb_orbit_bench data/orbit/gps_ops_2026-08-16_7d_1s.kloc \
  --preset laptop --query crossing --mode all --write-events \
  --samples 9 --min-sample-ms 150 --csv orbit_laptop_results.csv
```

The laptop preset processes 33,554,432 satellite-time candidates and allocates about 512 MiB for the dense crossing baseline. The optional VRAM preset processes 134,217,728 candidates and allocates about 2 GiB. Both repeat the bounded timeline when their requested duration exceeds seven days.

## Metrics to use

Do not use the KLOC1 horizon ratio alone. Compare:

- direct seed query p50/p95/p99;
- dense materialization p50/p95/p99;
- dense query p50/p95/p99;
- materialization-plus-query p50/p95/p99;
- compact event output cost;
- candidates/s and verified events/s;
- actual DRAM/L2 traffic, occupancy and register pressure in Nsight Compute;
- event-order differences against an SGP4 reference;
- container bytes plus refreshed element history and caches.

## Accuracy upgrade path

The practical next predictor version is SGP4-compatible propagation with one of two implementations:

1. CPU conversion to compact per-arc coefficients, then GPU evaluation; or
2. a direct bounded SGP4 kernel with near-Earth/deep-space branches separated into homogeneous queues.

KLOC1 already stores the OMM fields needed to identify the source record and model. A future v2 can add model-specific coefficient blocks and external-update novelty nodes without changing the support/guard/event ABI.
