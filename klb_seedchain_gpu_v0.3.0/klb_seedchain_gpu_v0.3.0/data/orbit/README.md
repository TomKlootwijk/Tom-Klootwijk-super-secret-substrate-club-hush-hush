# Orbit application data

## Included source and packed form

`source/gps_ops_2026-08-16_omm.csv` is a 4,852-byte snapshot retrieved once from CelesTrak's `GPS-OPS` general-perturbations CSV endpoint. It contains 32 records.

`gps_ops_2026-08-16_7d_1s.kloc` is the ready-to-run KLOC1 container used by `klb_orbit_bench`. It contains:

- 32 versioned orbital mean-element seeds;
- seven hash-linked daily timeline nodes;
- a NUL-prefixed name/designator string table;
- a declared seven-day, one-second query horizon.

The container is 3,809 bytes.

Reproduce it:

```text
klb_orbit pack-omm-csv data/orbit/source/gps_ops_2026-08-16_omm.csv \
  data/orbit/gps_ops_2026-08-16_7d_1s.kloc \
  --horizon-hours 168 --step-seconds 1 --tile-hours 24
```

## Dense-equivalent boundary

The seven-day horizon contains 604,801 state samples. A dense `float4` position table for all 32 objects would occupy 309,658,112 bytes. The KLOC1 ratio against that *chosen reconstruction horizon* is therefore 81,296.43x.

This is model-based expansion from orbital elements, not lossless compression of a pre-existing 295 MiB trajectory file.

## Useful generated application output

`gps_ops_2026-08-16_52N_5E_pass_events.csv` contains 717 coarse acquisition/loss events for a 52°N, 5°E station with a 10° elevation mask, generated over all 19,353,600 satellite-time intervals.

`gps_ops_2026-08-16_52N_5E_pass_events.summary.txt` records the run counters.

Reproduce it:

```text
klb_orbit passes data/orbit/gps_ops_2026-08-16_7d_1s.kloc \
  --lat 52 --lon 5 --alt-km 0.05 \
  --elevation-deg 10 --crossing-band-deg 0.25 \
  --hours 168 --step-seconds 1 \
  --output pass_events.csv
```

## Accuracy boundary

The predictor is a deterministic Kepler solve with precomputed secular J2 rates. CelesTrak general-perturbations elements are intended for SGP4. The included predictor is for compression/performance experiments and coarse visibility scheduling only; it is not navigation-grade, safety-critical, or a replacement for SGP4/precise ephemerides.

The six route sectors in the packed seeds are deterministic RAAN bins for compatibility-query load. They are not official GPS orbital-plane labels.

## Source and integrity

See `gps_ops_2026-08-16.source.json` for the source URL, retrieval date and SHA-256 values. The fetch scripts refuse to overwrite an existing file unless explicitly forced. Respect CelesTrak's usage policy and do not poll the endpoint.
