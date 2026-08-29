# Content-addressed storage and checkpoints

## Implemented bounded vertical slices

### Tiny proof DAG

`src/ugts_go19/pndag.py` implements `UGTS-GO-PNDAG-CHECKPOINT-v1` for exact
1×1/2×2 positional-superko validation. It stores byte-exact
`UGTS-GO-STATE-v1` objects, collision buckets with raw-byte fallback, complete
deterministic edge sets, cached uint64 proof numbers, and a canonical self-hash.
`checkpoint_sha256` is SHA-256 of the sorted-key, whitespace-free UTF-8 JSON
object with that field omitted; the on-disk file is the complete canonical object
plus one newline. `graph_sha256` hashes the normalized graph payload, excluding
filesystem paths and timing.
On load it independently reconstructs every expanded node's legal children,
reverse parents, reachability, rank ordering, proof/disproof values, root status,
and graph hash. Callers may pin expected rules, root, and threshold; mismatches
refuse resume. Single-writer publication uses a unique same-directory temporary
file, fsyncs its contents, atomically replaces the destination, and fsyncs the
containing directory on POSIX. It preserves the preceding checkpoint when
replacement fails. Windows replacement is atomic for the supported sequential
writer, but the bounded slice does not claim a directory-durability guarantee or
coordinate multiple writers.

The legacy claim-root digest and the SHA-256 content ID of the canonical
semantic state are separate fields. The latter's one-byte-per-point JSON is a
semantic interchange encoding; the canonical configuration's `2bit-row-major`
setting remains the intended physical binary segment encoding.

`ProofNumberDAG` itself still stores flat histories and its graph lives in one
host-local JSON file. It does not yet consume the persistent components below.
See `schemas/pndag_checkpoint.schema.json`.

### Persistent host-RAM PSK history

`src/ugts_go19/persistent_history.py` implements a fixed-depth immutable radix
trie over 256-bit index digests. Every leaf retains sorted exact board bytes;
digest matches only select a bucket. Insertions path-copy 32 nodes and share
untouched subtries. The canonical Merkle root and serialization are independent
of insertion/allocation order, and strict load reconstructs the trie from exact
members before accepting it. `src/ugts_go19/persistent_engine.py` uses these
roots for PSK membership and insertion directly, without recreating a flat set,
and differentially matches the flat reference on bounded fixtures.
`src/ugts_go19/persistent_pns.py` carries those roots through complete 1×1/2×2
tree-PNS threshold proofs without calling `members`; it is not the restartable
transposition DAG or production DFPN.

Injected digest callbacks are test-only and must be deterministic. Merkle and
artifact hashes are integrity locators, not set equality: same-store
`roots_equal` and cross-store `roots_exactly_equal` compare exact member bytes.
A proof-authoritative load must supply a trusted `expected_root_sha256`; an
unpinned self-hashed artifact can only prove internal consistency. Root artifacts
use unique temporary files, file fsync, sequential atomic replacement, and POSIX
directory fsync. JSON loading remains fully materialized and resource-unbounded,
so it is not the large-campaign storage path.

### Immutable exact-object segments

`src/ugts_go19/segment_store.py` stores exact typed board/history bytes in
canonical big-endian binary segments. Fixed SHA-256 names segments and manifests;
object index collisions retain exact-byte buckets and ambiguous digest-only reads
fail closed. Append-only self-hashed manifests lead to an atomically replaced
`CURRENT` pointer, and restart revalidates the complete manifest chain, every
segment hash, every object digest, exact duplicate exclusion, and declared
counts. Persistent-history artifacts have a tested pinned round trip through
this layer.

The segment store currently assumes one writer and is a bounded validation
component. Until disk-backed resident-memory limits are complete, it must not be
called NVMe spill. There is no WAL, compaction, garbage collector, distributed
merge, production proof-DAG integration, or 19×19 proof certificate.

## Persistent history

Copying a full superko set into every 19×19 node is infeasible. The production
implementation should use an immutable persistent set:

```text
history_root(parent) + inserted_board_digest -> history_root(child)
```

The digest indexes a collision-checked node. Exact board bytes are retained in
immutable segments so any membership decision can be audited.

Recommended layers:

1. GPU hot membership cache;
2. host-RAM persistent-set nodes;
3. memory-mapped immutable NVMe segments;
4. append-only write-ahead log for uncommitted updates.

## Node record separation

Separate hot and cold fields.

Hot record:

- compact board or board handle;
- player/pass flags;
- history-root handle;
- proof/disproof numbers;
- expansion state;
- child range or generator cursor;
- checksum/version.

Cold record:

- exact board bytes;
- exact history-node payload;
- parent/move lineage;
- terminal scoring witness;
- certificate links;
- diagnostics.

## Checkpoint transaction

1. stop selecting new expansion batches;
2. finish or discard uncommitted GPU batches;
3. flush proof deltas to the write-ahead log;
4. seal immutable segment files;
5. write a canonical manifest with segment hashes;
6. atomically rename the new checkpoint pointer;
7. reopen and sample-verify records;
8. resume.

A checkpoint is valid only if its manifest, rules digest, root digest, and every
referenced segment hash verify.

## Compression

Allowed lossless methods:

- 2-bit board packing;
- bitplanes;
- parent-plus-move lineage;
- varint move streams;
- delta-coded sorted child IDs;
- content deduplication;
- immutable block compression with per-block hashes;
- deterministic dictionary seeds stored in the manifest.

Forbidden for proof-authoritative data:

- lossy board compression;
- dropping history members;
- collision-only identity;
- non-deterministic serialization whose hash changes across runs.
