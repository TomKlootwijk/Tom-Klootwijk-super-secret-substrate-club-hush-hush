# KLOC1 binary format

KLOC1 is a little-endian, fixed-layout container for a compact orbital seed set, a hash-linked time partition and a UTF-8 string table.

## Canonical layout

```text
offset 0                              256-byte OrbitHeaderDisk
header.seeds_offset                   seed_count x 64-byte OrbitSeedDisk
header.nodes_offset                   node_count x 64-byte OrbitTimelineNodeDisk
header.strings_offset                 NUL-prefixed UTF-8 string table
end                                   exactly strings_offset + strings_bytes
```

No padding or optional sections are permitted in version 1. The loader checks every canonical offset and exact file length.

## Header: 256 bytes

Important fields:

| Field | Meaning |
|---|---|
| `magic` | `KLOC1` plus NUL padding |
| `version` | format version 1 |
| `flags` | hash-linked, string-table, OMM source, secular-J2, timeline, coarse-model bits |
| `seed_bytes` | must be 64 |
| `node_bytes` | must be 64 |
| `seed_count`, `node_count` | payload record counts |
| `seeds_offset`, `nodes_offset`, `strings_offset` | canonical absolute file offsets |
| `source_bytes`, `source_hash` | source CSV byte count and FNV-1a64 |
| `payload_hash` | FNV-1a64 over seeds, nodes and strings |
| `chain_hash` | final timeline-node self hash |
| `reference_unix_microseconds` | common time origin |
| Earth constants | predictor constants compiled into the file contract |
| `reference_gmst_rad` | station-frame rotation origin |
| timeline fields | start, step, duration and sample count |
| `predictor_model` | `kOrbitModelKeplerJ2Secular` in v1 |
| `source_format` | `kOrbitSourceOmmCsv` in v1 |
| `source_name` | bounded human-readable source label |

## Seed record: 64 bytes

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | NORAD catalog ID |
| 4 | 2 | parsed PRN, or zero |
| 6 | 1 | route sector 0..5 |
| 7 | 1 | flags |
| 8 | 4 | source epoch offset from reference, seconds |
| 12 | 4 | semi-major axis, km |
| 16 | 4 | eccentricity |
| 20 | 4 | `sqrt(1-e^2)` |
| 24 | 4 | inclination, radians |
| 28 | 4 | RAAN, radians |
| 32 | 4 | argument of perigee, radians |
| 36 | 4 | mean anomaly, radians |
| 40 | 4 | mean motion, radians/second |
| 44 | 4 | secular RAAN rate, radians/second |
| 48 | 4 | secular argument-of-perigee rate |
| 52 | 4 | secular mean-anomaly rate |
| 56 | 4 | deterministic lineage seed |
| 60 | 4 | offset into string table |

The route sector is a deterministic six-bin RAAN workload tag, not an authoritative constellation plane.

## Timeline node: 64 bytes

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | parent index; root is `0xffffffff` |
| 4 | 4 | node index |
| 8 | 4 | checkpoint/timeline flags |
| 12 | 4 | deterministic chain seed |
| 16 | 4 | node start, seconds from reference |
| 20 | 4 | node duration, seconds |
| 24 | 4 | sample step, seconds |
| 28 | 4 | reserved float, zero |
| 32 | 8 | parent hash |
| 40 | 8 | self hash |
| 48 | 8 | source hash |
| 56 | 4 | first sample index |
| 60 | 4 | interval/sample count for the tile |

Version 1 uses timeline nodes for bounded time addressing and lineage. It does not store per-node orbital corrections. A refreshed external OMM set is currently packed as a new KLOC1 snapshot.

## String table

Byte zero is NUL. Each seed `name_offset` points to a NUL-terminated UTF-8 string. The included adapter writes:

```text
OBJECT_NAME | OBJECT_ID
```

## Integrity chain

FNV-1a64 is used for deterministic corruption detection, not cryptographic authentication.

```text
seed_payload_hash = FNV1a64(all seed bytes)
root parent hash  = seed_payload_hash XOR source_hash
node self hash    = FNV1a64(node bytes with self_hash set to zero)
next parent hash  = previous node self hash
chain_hash        = final node self hash
payload_hash      = FNV1a64(seeds || nodes || strings)
```

The loader verifies:

- magic, version and record sizes;
- count/vector consistency;
- canonical offsets and exact file end;
- valid string offsets and terminators;
- finite/ranged orbital fields;
- sequential parent indices and parent hashes;
- every node self hash;
- terminal chain hash;
- total payload hash.

## GPU contract

The current CUDA path copies up to 256 seeds and 256 nodes into constant memory. It reconstructs state directly from a 64-byte seed and uses a timeline node only for lineage. Dense comparison state is `float4`/16 bytes per satellite-time sample.

KLOC1 stores no claim of navigation accuracy. The selected predictor model and accuracy boundary are part of the schema and must be preserved with benchmark results.
