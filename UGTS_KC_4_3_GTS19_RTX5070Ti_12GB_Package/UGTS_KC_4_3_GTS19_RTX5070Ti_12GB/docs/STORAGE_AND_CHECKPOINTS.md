# Content-addressed storage and checkpoints

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
