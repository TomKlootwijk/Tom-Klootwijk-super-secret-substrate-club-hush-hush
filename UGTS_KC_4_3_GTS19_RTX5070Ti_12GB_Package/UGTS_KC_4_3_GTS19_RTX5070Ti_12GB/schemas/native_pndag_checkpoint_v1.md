# `UGTS-CPP-PNDAG-CHECKPOINT-v1`

This document is the normative schema for the bounded native C++ proof-number
DAG checkpoint. It is a deterministic binary full snapshot, not JSON and not a
Python persistent-history checkpoint. All multi-byte integers are fixed-width
little-endian. Signed integers use two's-complement representation. Counts and
IDs are unsigned 64-bit values unless the table says otherwise.

The format reuses the proof-authoritative semantics of `UGTS-GO-STATE-v1` and
the exact graph identity `UGTS-CPP-PNDAG-GRAPH-v1`. It does not reuse
`UGTS-GO-PNDAG-CHECKPOINT-v1` or any `UGTS-GO-PERSISTENT-PNDAG-*` wire format.

## File envelope

| Field | Encoding | Constraint |
| --- | --- | --- |
| magic | ASCII plus NUL | `UGTS-CPP-PNDAG-CHECKPOINT-v1\0` |
| endian | `u8` | `1` (little-endian) |
| flags | `u8` | zero |
| reserved | `u16` | zero |
| board size | `u32` | 1 through 19; must match the expected run |
| komi2 | `i32` | must match the expected run |
| allow suicide | `u8` | canonical Boolean, 0 or 1 |
| scoring | `u8` | `1` (area) |
| repetition | `u8` | `1` (positional superko) |
| symmetry | `u8` | `0` (none) |
| passes to end | `u32` | `2` in the current native DAG |
| threshold2 | `i64` | must match the expected run |
| generation | `u64` | at least 1 |
| predecessor present | `u8` | canonical Boolean |
| predecessor file SHA-256 | 32 raw bytes | present exactly when generation is greater than 1 |
| committed expansions | `u64` | exactly the number of expanded nodes |
| root ID | `u64` | zero |
| node count | `u64` | positive and within the configured decoder cap |
| edge count | `u64` | within the configured decoder cap |
| history-member count | `u64` | sum of every node's seen-board count, within cap |
| run SHA-256 | 32 raw bytes | hash of the run framing below |
| root state object ID | 32 raw bytes | SHA-256 of exact regenerated `UGTS-GO-STATE-v1` bytes |
| graph SHA-256 | 32 raw bytes | exact `UGTS-CPP-PNDAG-GRAPH-v1` hash |
| nodes | repeated records | exactly `node count` ordered records |
| payload SHA-256 | 32 raw bytes | SHA-256 of every preceding file byte; no trailing bytes |

The externally retained checkpoint pin is SHA-256 of the complete file,
including the payload-hash footer. A loader requires that full-file hash as an
argument; the self-hash alone is not an anti-rollback pin.

## Node record

| Field | Encoding | Constraint |
| --- | --- | --- |
| node ID | `u64` | contiguous, ordered, beginning at zero |
| board | `size * size` raw bytes | each point is 0, 1, or 2 |
| player to move | `u8` | 1 or 2 |
| consecutive passes | `u32` | at most `passes to end` |
| previous-board present | `u8` | canonical Boolean |
| previous board | `size * size` raw bytes | present only when marked |
| seen-board count | `u64` | positive for reachable Go states and within aggregate cap |
| seen boards | concatenated raw boards | strictly lexicographically ordered and unique |
| semantic rank | `u64` | exactly `2 * seen-board count + passes` |
| expansion | `u8` | 0 unexpanded, 1 expanded, 2 terminal |
| cached proof | `u64` | derived cache, independently recomputed |
| cached disproof | `u64` | derived cache, independently recomputed |
| child count | `u64` | zero except for expanded nodes; at most points plus pass |
| children | repeated edge records | exactly `child count` records |

An edge is `(move i32, child_id u64)`. Moves are strictly increasing, with pass
encoded as -1 and placements as 0 through `size * size - 1`. Parent indexes are
not serialized; they are rebuilt exactly.

`ply` is campaign metadata and is absent. On load it is normalized to zero.

## Run hash framing

The run hash is SHA-256 over the following deterministic little-endian framing:

1. `UGTS-CPP-PNDAG-RUN-v1\0`;
2. `u64` byte length plus bytes for, in order:
   `exact-pndag-bounded-v1`,
   `unresolved-pns-pn-dn-move-statebytes-v1`,
   `numeric-pass-minus-one-statebytes-v1`,
   `UGTS-GO-STATE-v1`, and `UGTS-CPP-PNDAG-GRAPH-v1`;
3. proof width `u8 = 64`, endian `u8 = 1`, infinity `u64 = 2^64 - 1`;
4. the semantic rule fields in the same widths as the file envelope;
5. threshold `i64`;
6. `u64` byte length plus the exact canonical root-state JSON bytes.

Hashes protect artifacts and select expected runs. They never replace raw
state equality or exact legal-edge regeneration.

## Mandatory semantic validation

A valid external hash and payload self-hash are necessary but insufficient.
The loader reconstructs every state, rejects duplicate exact state bytes,
checks rank and terminal markers, rebuilds parents and reachability, regenerates
the complete legal child set of every expanded node, recomputes all proof and
disproof values with uint64 saturation, derives root status, and recomputes the
root object ID, run hash, and graph hash. No serialized cache or hash establishes
game truth by itself. Configured file, node, edge, and aggregate history caps are
checked before allocation. Declared node, history-board, and edge byte minima
must also fit in the unread payload before any count-derived `reserve`.

## Publication and recovery

Published files are immutable and named
`checkpoints/<full-file-sha256>.pndag`. A fsynced temporary is installed without
overwriting an existing target; an equal existing file is accepted only after
exact byte comparison. Publication reopens the installed file through the
strict semantic loader before reporting success.

For generation two and later, publication first reopens the supplied
predecessor path using its supplied full-file SHA pin, verifies every tip field
against the decoded artifact, and requires an ID-stable exact node prefix with
all previously committed expansion markers and edges unchanged. Load follows
each predecessor hash to the exact sibling
`<predecessor-full-sha256>.pndag`, validates every generation back to generation
one, and checks the same exact-prefix relation at each link. This is deterministic
hash-derived lookup, not a directory scan. The default lineage cap is 1,024
generations and callers must retain all linked files or explicitly raise the cap.
Continuation publication must target the same normalized store and canonical
hash filename as its predecessor, so a cross-store request fails before any
write. The API does not trust a caller-constructed predecessor tip.

There is deliberately no `CURRENT` pointer and no newest-generation scan. The
last file path and full-file SHA retained outside the store are authoritative.
A crash before that new pin is retained resumes the older pin. A crash or
post-install flush/reopen failure may leave an unreported content-addressed
orphan; it is never adopted automatically and does not roll back or overwrite
the prior checkpoint.

This is a single-writer, trusted, symlink-free local-filesystem slice. Windows
uses `FlushFileBuffers` and same-volume `MoveFileExW` with
`MOVEFILE_WRITE_THROUGH`; it does not claim a portable directory-fsync
guarantee. Network filesystems, hostile concurrent mutation, garbage
collection, delta snapshots, and campaign-scale memory bounds are outside v1.
On POSIX, successful publication fsyncs the checkpoint directory and, when they
were newly created, the store root and its immediate parent; the caller must
provide a durable pre-existing parent for the store root. Encode and load each
materialize the complete binary artifact in RAM in addition to the live DAG.
During complete-chain validation, load can transiently retain the selected DAG,
an adjacent descendant DAG, an ancestor DAG under validation, and one complete
file buffer. The lineage cap makes work finite but is not a practical peak-RSS
or cumulative recovery-I/O bound.
