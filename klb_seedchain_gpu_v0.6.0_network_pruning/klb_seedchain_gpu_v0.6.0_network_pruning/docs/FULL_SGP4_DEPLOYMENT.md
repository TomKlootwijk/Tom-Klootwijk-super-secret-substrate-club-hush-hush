# Full-SGP4 seed-chain deployment

## Practical objective

The useful workload is a queryable satellite visibility/event archive. Stable
object identity and OMM mean elements are stored once; full SGP4/SDP4 state is
reconstructed only at requested times. Acquisition/loss events are compacted as
the novelty/event output.

```text
KSGP1 compact seeds + timeline lineage
    -> SGP4/SDP4 initialization
    -> requested TEME state
    -> GMST+DUT1 TEME-to-PEF rotation
    -> radial support
    -> route compatibility
    -> elevation guard crossing
    -> acquisition/loss event + lineage
```

This is a direct implementation of the substrate’s query-first sequence rather
than a renderer or mandatory frame loop.

## What is stored

For each object, the 128-byte seed retains identity and every OMM field required
by the propagator: epoch, `BSTAR`, mean-motion derivatives, inclination, RAAN,
eccentricity, argument of perigee, mean anomaly, mean motion, element/revolution
metadata, PRN, route, and string-table references.

The initialized coefficient record is about 1.4 KiB and is compiled at load
time. It is intentionally not persisted in KSGP1. Seven 64-byte timeline nodes
bound the included seven-day query horizon and carry parent/self lineage hashes.

## GPU execution paths

`src/sgp4_bench.cu` contains three comparable paths:

1. **Direct seed:** load an initialized coefficient record, run full SGP4 at the
   requested interval endpoints, rotate to PEF, and evaluate the event guard.
2. **Materialize:** reconstruct every endpoint into a dense `double4` position
   array.
3. **Dense query:** evaluate the same support/guard/event logic against the
   materialized array.

The benchmark first checks CPU/GPU propagation state, then a CPU/GPU prefix
oracle, then direct/dense counters, and finally sorted compact event payloads.
Only after those checks does it report sustained timing.

## Included workload

```text
Objects                       32
Timeline                      604,800 seconds
Sample spacing                1 second
Candidate intervals           19,353,600
Acquisition/loss events       717
Propagation failures          0
KSGP1 file                    5,793 bytes
Dense float4 comparison       309,658,112 bytes
Dense position+velocity       928,974,336 bytes
```

The resulting 53,453.84× and 160,361.53× figures are horizon-relative avoided
materialization ratios. They are not conventional lossless-file compression
ratios. Their validity depends on reconstructibility and event correctness.

## Why the earlier predictor was removed

The old Kepler-plus-secular-J2 predictor differed from full SGP4 by 18.083609 km
RMS and 50.072351 km maximum across the included matched sample set. It remains
only as a baseline showing that the storage architecture can survive a predictor
upgrade while the predictor itself must meet the application’s error budget.

## Precision and frame boundary

The full propagation core uses binary64. The CUDA acceptance threshold is 10 mm
maximum position delta and 0.01 mm/s maximum velocity delta relative to the CPU
implementation for the validation states. Direct/dense event identity must be
exact after sorting.

The ground query uses TEME-to-PEF rotation with GMST and configurable DUT1. It
does not apply polar motion or a complete Earth-orientation model, so the pass
schedule is an engineering benchmark, not an operational navigation product.

## Target acceptance commands

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\demo_sgp4_windows.ps1 -Preset smoke
powershell -ExecutionPolicy Bypass -File .\scripts\demo_sgp4_windows.ps1 -Preset file
powershell -ExecutionPolicy Bypass -File .\scripts\demo_sgp4_windows.ps1 -Preset laptop
```

The file preset automatically compares the GPU compact events with the included
717-event CPU schedule.
