# Mixed-orbit network challenge data

## Reproducible source snapshots

```text
source/gps_ops_2026-08-16_omm.csv
  32 CelesTrak GPS Operational OMM-style CSV records inherited from the
  validated v0.5 package.

source/tdrss_mixed_2026-07-29.tle
  26 three-line records from the CelesTrak TDRSS group. The group includes
  relay, low-Earth science/observation, and high-eccentricity science objects.

source/tdrss_mixed_2026-07-29_omm.csv
  dependency-free conversion of that 3LE snapshot to the OMM-style CSV fields
  consumed by KSGP1.

source/celestrak_mixed_gps_tdrss_2026-08-16_omm.csv
  58-record deduplicated merge used to build the included KSGP1 file.
```

The source epochs are not identical. Each SGP4 seed carries its own epoch, so
this is valid for a mixed-catalog propagation benchmark. It is not a single
simultaneous tracking observation.

## Station policy table

```text
benchmark_station_network.csv
```

The 16 rows are synthetic benchmark profiles at plausible geographic
coordinates. Service and orbit masks are deliberately varied to exercise
compatibility pruning. They are not claims about actual station ownership,
coverage, authorization, antenna performance, or operational service.

## Packed seed file

```text
celestrak_mixed_58obj_7d_60s.ksgp
```

```text
Objects                         58
Compact seed bytes              58 × 128
Container bytes                 9,581
Timeline                        7 days at declared 60-second sampling
Near-Earth                      11
Deep non-resonant               36
Synchronous resonance           11
Half-day resonance              0
```

The inherited Vallado branch-vector data under `data/sgp4/` continues to cover
the half-day branch.

## Included oracle outputs

```text
mixed_network_pair_plan.csv
  all 928 static pair decisions

mixed_network_7d_60s_events.csv
  9,335 AOS/LOS events from the active relation set

mixed_network_7d_60s_cpu_metrics.csv
  all/support/active counts and timings

mixed_network_7d_60s_verify.summary.txt
  human-readable CPU acceptance record
```

## Refresh boundary

`scripts/refresh_network_data_windows.ps1` downloads only the GPS-OPS and TDRSS
CSV groups, checks native command exit codes, merges them, and repacks KSGP1.
It refuses to overwrite an existing refresh output unless `-Force` is supplied.
Do not poll CelesTrak repeatedly; use a cached snapshot by default.
