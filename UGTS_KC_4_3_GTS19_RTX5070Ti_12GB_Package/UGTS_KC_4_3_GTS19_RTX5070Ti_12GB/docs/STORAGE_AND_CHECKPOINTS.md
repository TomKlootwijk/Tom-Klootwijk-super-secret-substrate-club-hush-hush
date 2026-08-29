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

The Python `ProofNumberDAG` itself still stores flat histories and its graph
lives in one host-local JSON file. It does not yet consume the persistent components below.
See `schemas/pndag_checkpoint.schema.json`.

### Native bounded PNDAG checkpoint

`cpp/src/pndag_checkpoint.cpp` adds a separate deterministic binary full
snapshot for the native 1×1-through-19×19 host-memory DAG. It deliberately does
not reuse the Python checkpoint formats. Every resume requires both an explicit
path and an externally retained SHA-256 of the complete file; there is no
`CURRENT` pointer or newest-file scan. The strict loader caps declarations
before allocation, rebuilds exact states and parents, regenerates every expanded
node's complete legal edge set, recomputes proof caches/status and graph/run/root
hashes, and rejects any mismatch. It follows only hash-derived sibling filenames
and validates the complete predecessor chain back to generation one; all linked
artifacts must therefore remain beside the selected tip. The default chain cap
is 1,024 generations and is explicitly configurable. Continuations must publish
back into the predecessor's same normalized content-addressed store; cross-store
requests fail before writing.

Files are immutable `checkpoints/<full-file-sha256>.pndag` objects. Publication
flushes a temporary, installs without overwrite, flushes the installed file and
directories where supported, and reopens through the strict loader before
returning a tip. Continuations also reopen and verify the supplied predecessor
tip and require an unchanged exact-node prefix and committed edges. A failure
after installation can leave an unreported content-addressed orphan; it does
not roll back the prior externally retained pin, and no orphan is adopted
automatically. Windows does not provide the claimed POSIX directory-fsync
barrier. The codec materializes the full snapshot in memory and does not bound
the live DAG, and complete-chain validation repeatedly loads historical full
snapshots, so it is a restartable bounded milestone rather than a campaign-scale
storage layer. See `schemas/native_pndag_checkpoint_v1.md`.

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
transposition DAG or production DFPN. Its resource limit counts expansions,
not all generated node objects; a budget stop remains `UNKNOWN`.

`src/ugts_go19/persistent_pndag.py` is the restartable transposition-DAG bridge
over these roots. Its v2 semantic state excludes campaign-only `ply`; live nodes
retain the immutable history root rather than a serialized history artifact.
Exact legacy v2 state bytes are regenerated transiently for digests, checkpoints,
graph hashes, and external pins, preserving the prior wire format. State lookup
uses digest buckets followed by exact scalar and collision-independent trie
comparison, audits every expanded legal edge, and independently recomputes proof
numbers on load. Both complete 2×2 threshold fixtures resume to the same graph,
counts, and proof numbers as uninterrupted runs. Its strict JSON checkpoint
schema is `schemas/persistent_pndag_checkpoint.schema.json`; the compact gate is
`evidence/local_m2_persistent_pndag_gate.json`. On the measured 20-expansion,
63-node fixture, 3,544,779 legacy state bytes are transient and zero are retained
by proof nodes. This is still a host-RAM fixture: the complete board/trie/proof
graph remains resident, checkpoints fully materialize JSON, and live records do
not use immutable segments. The v2
gate separately treats a compact snapshot as one opaque segment object, forces
lazy spill, reopens under an external manifest pin, and strictly recovers the
identical `UNKNOWN` graph; it does not page live DAG records. The single-file
save API also needs an externally managed immutable generation/tip pin to detect a
valid rollback; an older internally valid file cannot forge proof truth because
the loader recomputes it, but it can silently lose completed work.

`src/ugts_go19/persistent_pndag_compact_checkpoint.py` is a separate bounded
codec that replaces the repeated per-state history artifacts on disk with one
ordered shared forest. On a 20-expansion 2×2 fixture this reduced 7,104,362
legacy bytes to 350,147 bytes. Load reconstructs canonical legacy state bytes
and delegates every semantic, edge, proof-cache, status, and graph check to the
existing strict loader; exact reserialization binds the returned DAG to those
reconstructed bytes across the temporary-path boundary. It then clones the
validated graph onto the validated ordered forest roots and repeats structure,
cache, graph, and byte checks, preserving physical trie sharing. The measured
fixture returns 1,163 physical nodes versus 6,558 summed root references. This
saves durable and retained duplicate-history bytes, but serialization still
materializes the legacy payload and load holds the compact JSON, forest,
reconstructed artifacts, legacy checkpoint, and validated graphs. It is a full
standalone snapshot with no rollback
protection unless placed under an externally pinned generation/segment layer.
Its schema is `schemas/persistent_pndag_compact_checkpoint.schema.json`.
The archived v2 gate's two seven-expansion cases each reduce 2,615,463 legacy
bytes to 229,187 compact bytes before the segment-backed restart.

`src/ugts_go19/persistent_pndag_checkpoint_store.py` supplies the bounded legacy
generation layer. `first_open` refuses any prior artifact lineage; each
generation installs an immutable full checkpoint and chained canonical manifest
before atomically replacing `CURRENT`. `resume` has no unpinned mode: callers
must retain and supply the complete tip, including generation, manifest,
checkpoint-file, semantic-checkpoint, run, graph, and work-count hashes. The
manifest stores the exact root bytes and full rules/algorithm envelope. Adjacent
generations must preserve an ID-stable exact node prefix, all committed
expansions and edges, and any solved status; a larger counter cannot replace a
different frontier. Verified loader output is exactly reserialized before use.

For an unambiguous external-tip handoff, `prepare` fsyncs the immutable next
generation without touching `CURRENT`; the caller must durably journal the
returned preparation outside the store before `commit_prepared`.
`recover_prepared` then idempotently finishes with either the exact predecessor
or exact intended `CURRENT` visible, including genesis. `commit_prepared` also
accepts an exact direct retry after a post-replace failure; if it cannot
affirmatively distinguish the predecessor from the intended tip, it raises a
dedicated uncertain exception carrying the preparation. The one-call `publish`
is only a bounded same-process convenience and cannot make an unjournaled hard
crash recoverable. Preparation failure before its record reaches the caller may
leave unreachable immutable orphans, which are never inferred as committed.
The store remains full-checkpoint and resource-unbounded: repeated complete-chain
validation is superlinear, SHA-256 is the anti-rollback assumption, paths are
assumed trusted and symlink-free, exactly one writer is externally enforced,
and Windows has no directory-fsync guarantee.

Injected digest callbacks are test-only and must be deterministic. Merkle and
artifact hashes are integrity locators, not set equality: same-store
`roots_equal` and cross-store `roots_exactly_equal` compare exact member bytes.
A proof-authoritative load must supply a trusted `expected_root_sha256`; an
unpinned self-hashed artifact can only prove internal consistency. Root artifacts
use unique temporary files, file fsync, sequential atomic replacement, and POSIX
directory fsync. JSON loading remains fully materialized and resource-unbounded,
so it is not the large-campaign storage path.

`UGTS-PY-PERSISTENT-PSK-FOREST-v1` serializes an ordered sequence of roots with
one globally deduplicated exact board/node table. Canonical node IDs are derived
bottom-up from exact board IDs and exact child IDs, never Merkle equality. Load
validates each fixed-depth radix record compositionally, performs one union
reachability traversal, and then adopts a single shared node DAG. Unique branch
slots plus exact derived prefixes make repeated nodes or boards within one root
structurally impossible. The loader rejects duplicate, unreachable, missing,
cyclic, and wrong-prefix records and accepts ordered root/artifact integrity pins.
In a bounded nine-version fixture the forest occupied 84,262 bytes versus
388,763 bytes for nine separate root artifacts. It is still canonical JSON
materialized in RAM. Loading is linear in the shared record/reference tables,
but serialization still validates each supplied root separately, so creating a
long chain of growing roots can revisit shared subtries quadratically. Its
artifact/root pins are hash-only anti-substitution checks and retain the same
SHA-256 collision-resistance assumption as other integrity pins; internal set
validation itself remains exact-byte based.

### Immutable exact-object segments

`src/ugts_go19/segment_store.py` stores exact typed board/history bytes in
canonical big-endian binary segments. Fixed SHA-256 names segments and manifests;
object index collisions retain exact-byte buckets and ambiguous digest-only reads
fail closed. Append-only self-hashed manifests lead to an atomically replaced
`CURRENT` pointer, and restart revalidates the complete manifest chain, every
segment hash, every object digest, exact duplicate exclusion, and declared
counts. Lazy mode replaces published payload objects with read-only mmap offsets;
each returned mapped payload is copied and the backing segment is rehashed so a
normal post-open backing-file mutation fails closed. A caller may pin the
expected manifest hash at startup to detect rollback to an older, internally
valid `CURRENT`. Persistent-history artifacts have a tested pinned round trip
through this layer.

`staged_memory_limit_bytes` bounds retained staged payload bytes and forces real
segment publication; `resident_payload_bytes == 0` after a lazy spill means no
complete published payload is retained as a Python `bytes` object. Segment
sealing streams headers and payloads through one fsynced temporary file while
incrementally hashing, and existing immutable targets are compared in bounded
chunks rather than full-read. A local 16 MiB fixture measured about 2.1 MiB of
additional traced Python peak after staging. That measurement is not a peak-RSS,
mmap-page, handle, metadata, incoming-buffer, or total-campaign bound. A measured
32 MiB lazy fixture retained zero Python payload bytes after spill while touched
mmap pages kept roughly 32 MiB in the process working set until close. The store
keeps one mapping per segment, reuses existing mappings during append, verifies
the current pathname independently, and revalidates every historical segment.
Cumulative manifests have quadratic on-disk metadata across generations and
repeated publication has superlinear validation work. The store assumes an
externally enforced single writer and immutable/exclusive backing files. An
active transient writer can evade the copy-then-rehash window, POSIX truncation
of a live mmap can fault outside Python, and Windows cannot directory-fsync
through this interface. Fixed SHA-256 segment/manifest names are integrity
assumptions rather than collision-independent exact identity pins. There is no
WAL/orphan-recovery workflow, compaction, garbage collector, distributed merge,
production proof-DAG integration, or 19×19 proof certificate. Consequently the
campaign-level "NVMe spill and restart" milestone remains open.

`scripts/storage_gate.py` archives a deterministic bounded acceptance exercise
in `evidence/local_m2_storage_gate.json`. It checks the canonical empty 19×19
board plus one center move, exact flat/persistent transition parity, two pinned
history-root rehydrates, forced lazy spills, externally pinned fresh restart,
and exact reads through a deliberately colliding index. The evidence explicitly
keeps the 19×19 root `UNKNOWN`; it performs no search.

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
