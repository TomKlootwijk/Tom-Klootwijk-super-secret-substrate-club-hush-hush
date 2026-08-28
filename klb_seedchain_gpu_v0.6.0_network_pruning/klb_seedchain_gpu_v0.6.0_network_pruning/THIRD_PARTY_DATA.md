# Third-party data, algorithms, and reference products

## SGP4/SDP4

The propagator follows the Vallado/CSSI SGP4/SDP4 computational family. See
`NOTICE_SGP4.md` for provenance and warranty boundaries.

## CelesTrak GP/OMM data

Included reproducibility snapshots:

```text
data/network/source/gps_ops_2026-08-16_omm.csv
data/network/source/tdrss_mixed_2026-07-29.tle
data/network/source/tdrss_mixed_2026-07-29_omm.csv
data/network/source/celestrak_mixed_gps_tdrss_2026-08-16_omm.csv
```

CelesTrak GP data are Brouwer mean elements intended for SGP4 propagation. The
public query interface provides TLE and OMM-derived CSV/JSON/XML/KVN formats.
The refresh script requests only `GPS-OPS` and `TDRSS`, caches the output, and
refuses accidental overwrite unless explicitly forced.

Users are responsible for the current CelesTrak usage policy. Do not repeatedly
poll unchanged data; check HTTP status and retain the last successful snapshot.

## IGS SP3 products

No external SP3 product is redistributed in this package. The included adapter
accepts a manually downloaded IGS rapid, final, or ultra-rapid SP3 file. IGS
products are typically organized by GPS week and use SP3 for precise satellite
positions. Use an epoch-overlapping product and record whether an ultra-rapid
sample belongs to the observed or predicted half.

## Benchmark stations

`data/network/benchmark_station_network.csv` is authored benchmark input. Its
rows are policy profiles at geographic locations, not an operational network
registry or statement of access to real tracking stations.

## Stanford Bunny

Legacy scripts can fetch the Stanford Bunny for the earlier point-chain test.
No Stanford archive is bundled.
