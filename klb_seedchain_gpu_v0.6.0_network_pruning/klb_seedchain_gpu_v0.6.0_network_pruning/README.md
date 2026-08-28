# KLB SeedChain GPU 0.6.0 — mixed-orbit network pruning challenge

Version 0.6.0 preserves the validated full SGP4/SDP4 seed-reconstruction path
from 0.5.0 and adds the next substrate challenge: **mixed orbit classes,
multiple typed station policies, conservative support pruning, compatibility
pruning, grouped state reconstruction, and an external SP3 comparison tool**.

The target remains an NVIDIA RTX 5070 Ti Laptop GPU with 12 GB VRAM. The CUDA
build emits native `sm_120` plus `compute_120` PTX and requires CUDA Toolkit
12.8 or newer.

## New challenge in one diagram

```text
58 compact SGP4 seeds
        |
        +--> static support envelope ---------+
        |                                     |
        +--> orbit/service/route compatibility+
                                              |
16 station-policy profiles -------------------+
                                              v
                           reconstruct object state once
                                              |
                              evaluate selected stations
                                              |
                       elevation guard -> AOS/LOS event
                                              |
                                    route + lineage output
```

This addresses the principal weakness of the preceding one-station GPS test:
nearly every relation survived support and compatibility. The new dataset
contains LEO, MEO, GEO, and HEO objects and station profiles with different
orbit and service masks.

## Delivered components

```text
include/klb/network.hpp
src/network.cpp
src/network_main.cpp
src/network_bench.cu
tests/test_network.cpp

tools/tle_to_omm_csv.py
tools/merge_omm_csv.py
tools/compare_sp3.py

data/network/celestrak_mixed_58obj_7d_60s.ksgp
data/network/benchmark_station_network.csv
data/network/mixed_network_pair_plan.csv
data/network/mixed_network_7d_60s_events.csv
```

Detailed design and interpretation:

```text
docs/NETWORK_PRUNING_CHALLENGE.md
docs/SP3_REFERENCE_CHALLENGE.md
docs/FULL_SGP4_DEPLOYMENT.md
docs/VALIDATION.md
```

## Included mixed data

```text
Objects                         58
GPS Operational records        32
TDRSS-group records             26
Station policy profiles         16
Orbit classes                   LEO=11, MEO=32, GEO=8, HEO=7
Container bytes                 9,581
Reference epoch                 2026-08-16T05:33:12.693024Z
Declared horizon                604,800 seconds
Declared sample step            60 seconds
```

The 26-record TDRSS group is intentionally heterogeneous; it includes relay,
low-Earth science/observation, and high-eccentricity science objects. Each seed
retains its own source epoch.

The station table is a benchmark policy network. Its geographic coordinates
and masks are useful for workload construction, not claims about real station
ownership, authorization, antennas, or services.

## Static relation plan

```text
All object-station pairs        928
Support-possible pairs          711
Policy-compatible pairs         438
Support rejection gain          1.305204x
Compatibility gain              1.623288x
Total relation reduction        2.118721x
```

Every decision is auditable in:

```text
data/network/mixed_network_pair_plan.csv
```

## CPU oracle result

The delivered seven-day, one-minute test produced:

```text
Time intervals                  10,080
Object propagations             584,640
All relation intervals          9,354,240
Active relation intervals       4,415,040
Visible endpoints               1,101,511
Acquisition events              4,653
Loss events                     4,682
Total events                    9,335
Propagation failures            0
```

Acceptance:

```text
all/support event identity      PASS
all/active event identity       PASS
support survivor equality       PASS
active compatible equality      PASS
relation work reduction          2.118721x
```

The CPU timing in the included log is environment-specific. Event identity and
counts are the portable result.

## CUDA paths

`klb_network_bench` benchmarks:

```text
pair_all             propagation repeated for every unpruned pair
pair_support         propagation repeated for support pairs
pair_active          propagation repeated for active pairs
grouped_all          one propagation per object/time, then all stations
grouped_active       one propagation per object/time, then active stations
materialize_dense    dense double4 PEF position buffer
query_dense_active   resident dense active query
```

The grouped path is the intended practical implementation. It prevents the
network relation count from multiplying the SGP4 propagation count.

## Windows build

Open an **x64 Native Tools Command Prompt for Visual Studio 2022** in the
extracted directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

The script now explicitly checks every native command exit code and verifies
that the SGP4 and network CPU/CUDA executables were created.

Expected new executables:

```text
build\Release\klb_network.exe
build\Release\klb_network_bench.exe
```

## First run

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\demo_network_windows.ps1 `
  -Preset file
```

This first regenerates the complete CPU oracle, then runs the GPU file preset.

Run the sustained laptop preset:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\stress_network_windows.ps1
```

Profile the grouped kernel:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\profile_network_windows.ps1
```

## GPU acceptance

The network result is accepted only when:

```text
pair-all GPU events equal CPU all-pairs events
pair-active GPU events equal CPU active events
pair-active and grouped-active event streams match
pair-active and grouped-active counters match
grouped-active and dense-active event streams match when enabled
grouped-active and dense-active counters match
propagation failures are zero
no event buffer truncation occurs
```

Only after those checks should the pair/grouped/dense timings be interpreted.

## External precise-orbit challenge

`tools/compare_sp3.py` compares GPS samples against an independently downloaded
IGS SP3 orbit product. It supports `.sp3` and `.sp3.gz` and reports RMS,
median, p95, and maximum position differences.

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\compare_sp3_windows.ps1 `
  -Sp3File .\external_data\orbit.SP3.gz
```

Use an SP3 product whose epochs overlap a freshly packed GPS OMM snapshot. The
reported difference combines model, element-age, frame, DUT1, and omitted EOP
terms; it is not pure SGP4 arithmetic error.

## CPU-only validation build

```bash
cmake -S . -B build-cpu \
  -DCMAKE_BUILD_TYPE=Release \
  -DKLB_BUILD_CUDA=OFF
cmake --build build-cpu -j
ctest --test-dir build-cpu --output-on-failure
./build-cpu/klb_network verify \
  data/network/celestrak_mixed_58obj_7d_60s.ksgp \
  data/network/benchmark_station_network.csv \
  --hours 168 --step-seconds 60
```

## Validation boundary

Completed here:

```text
clean C++20 build               PASS
CTest                           4/4 PASS
mixed KSGP1 hashes              PASS
all/support/active CPU oracle   PASS
CUDA host/device syntax         PASS
CUDA device LLVM generation     PASS
SP3 adapter self-test           PASS
```

Still requiring the physical laptop:

```text
native nvcc 12.8+ sm_120 build
new GPU event/counter acceptance
pair versus grouped crossover
resident dense crossover
Nsight Compute measurements
power and thermal steady state
external SP3 result using overlapping real products
```

The v0.5 physical RTX results remain useful evidence for the full-SGP4 core.
They do not substitute for execution of the new network kernel.

## Attribution and evidence boundary

The requester-supplied substrate attribution is recorded in
`AUTHORSHIP_NOTICE.md`. SGP4 provenance is recorded in `NOTICE_SGP4.md`.
Public-data provenance and refresh limits are recorded in
`THIRD_PARTY_DATA.md` and `data/network/source/source_manifest.json`.

Lineage hashes are deterministic routing/integrity values, not cryptographic
identity or proof of authorship. Storage ratios are avoided-materialization
comparisons and not claims that arbitrary dense files were losslessly
compressed.
