# Known limits

- The unrestricted empty 19×19 root is `UNKNOWN` in this release.
- The Python engine is a correctness oracle, not a performant 19×19 solver.
- The included proof-number searches use bounded host-memory tree/DAG storage;
  there is no production transposition database or DFPN coordinator.
- The CUDA code now implements a bounded pre-superko placement transition slice:
  occupancy, deterministic groups/liberties, simultaneous captures,
  post-capture own-liberty/no-suicide rejection, and fixed-slot child bitplanes.
  The CPU recomputes every point and remains authoritative for pass, exact PSK,
  metadata, and proof updates; the slice is not integrated into proof search.
- CUDA 12.8 compiles on the target NVIDIA GeForce RTX 5070 Ti Laptop GPU at
  compute capability 12.0. The occupancy gate passed 13 deterministic cases,
  13,038 Python/CUDA and 33,580,510 total C++/CUDA exact word comparisons,
  33,606,586 input-immutability comparisons, 320 canary checks, and 12 negative
  checks. It crosses the real grid-stride cap, tests permitted input aliasing and
  pre-enqueued dual streams, and passes Compute Sanitizer with zero
  mismatches/errors. This is functional parity evidence, not a 19×19
  certificate. The cross-language local-transition v1 gate covers 25,281 unique
  point slots (50,562 across default/nondefault parity modes). A separate
  C++/CUDA breadth gate now covers 10,000,303 slots from 27,716 exact-distinct
  states once per stream mode, including 554,496 reachable campaign-shaped and
  9,444,121 ordinal-injective randomized 19×19 slots, with zero mismatches. Its
  measured 155,493/165,556 slots/s are hardware-specific and non-proof; Python
  was not run across that 10m corpus. The dense 19×19 output costs 36,606 device
  bytes per state, rejects an over-budget batch rather than resizing it, and
  still has no production proof-coordinator integration.
- The C++ reference currently pins positional superko and area scoring. It now
  shares a canonical semantic-state object with Python, but does not implement
  the Python engine's optional simple-ko, situational-superko, or no-superko
  profiles.
- M1 Python/C++ v2 parity passed 1,000,007 deterministic legal transitions and
  13,187,153 authoritative comparisons with zero mismatches, including
  minimized snapback, ko, multi-capture, edge, suicide, pass, and terminal
  cases, byte-exact canonical JSON, and portable SHA-256 state-object IDs. This
  validates the tested transition core; it is not a 19×19 proof or a substitute
  for collision-checked equality.
- `ProofNumberDAG` is deliberately restricted to host-local 1×1/2×2 PSK games.
  Its own nodes still have exact flat histories and atomic single-file
  checkpoints; it does not yet consume the separate persistent-root/segment
  path and has no production DFPN, symmetry, or standalone certificate
  extraction.
- The native `ugts_go19::ProofNumberDAG` accepts 1×1 through 19×19 and its exact
  state-byte map, deterministic selection, saturating recurrence, and complete
  2×2 graph fingerprints match the Python oracle. Its canonical two-expansion
  19×19 preflight is exactly `UNKNOWN`, not progress toward a solved claim. It
  now has a bounded native full-snapshot checkpoint/resume codec with mandatory
  external full-file SHA pins, strict semantic reload, exact-prefix lineage, and
  immutable content-addressed publication. It still copies complete flat
  histories; holds the complete DAG in RAM; materializes a complete checkpoint
  buffer on save/load; and has no bound-record TT, certificate extraction,
  score-interval pruning, CUDA expansion, multi-writer coordination, garbage
  collection, or practical campaign-scale resource bound. Windows has no
  portable directory-fsync guarantee, and a post-install flush/reopen failure
  can leave an unreported orphan that is never auto-selected. Strict resume
  revalidates every hash-linked full generation up to a default 1,024-generation
  cap; this can become superlinear across repeated resumes and is not a compact
  production journal. Chain validation can transiently retain the selected DAG,
  two adjacent historical DAGs, and a full decoded file buffer.
- The bounded `PersistentHistory`/`persistent_engine` path provides canonical
  structurally shared PSK roots and exact transitions through 19×19-shaped
  records. `PersistentProofNumberDAG` carries those roots through a restartable
  1×1/2×2 transposition graph. Live proof nodes now retain only immutable
  history-root handles and regenerate unchanged legacy state bytes transiently;
  a 63-node fixture retained zero serialized state/history bytes instead of
  3,544,779. Boards, trie nodes, proof nodes, and fully materialized checkpoint
  data remain in host RAM. The optional immutable
  checkpoint-generation store requires a complete externally retained tip,
  exact-prefix-validates adjacent graphs, and rejects rollback relative to that
  tip. Its recoverable two-phase handoff, subject to the stated filesystem
  durability assumptions, requires callers to externally journal a
  `prepare` record before `commit_prepared`; the one-call convenience API cannot
  repair a hard crash without that record. It repeatedly materializes and
  revalidates every historical full checkpoint, has no resource cap or writer
  lock, assumes SHA-256 collision resistance for anti-rollback, and follows
  symlinks/reparse points under a trusted-root assumption. The raw single-file
  API remains rollback-blind when used alone. Neither path is campaign-scale.
- The compact persistent-history forest removes duplicate immutable trie/board
  records across many roots and preserves structural sharing after load, but it
  is still a fully materialized JSON artifact. Forest loading is linear in the
  shared record/reference tables; serialization validates each supplied root
  separately and can revisit a growing version chain quadratically. Its external
  artifact/root pins assume SHA-256 collision resistance.
- The compact persistent-PNDAG codec stores one ordered forest instead of one
  history artifact per state and reduced a bounded 20-expansion fixture by
  95.1%. After strict legacy validation it rebinds the returned DAG to the
  validated shared forest: the measured fixture retained 1,163 physical trie
  nodes versus 6,558 summed per-root references. It still reconstructs and
  reserializes a full legacy checkpoint, so peak RAM/CPU are non-production. Its standalone save is
  sequential-writer and valid-old-file rollback-blind, with the same SHA pin,
  post-rename durability, parent-directory, and Windows directory-fsync limits.
  The live DAG still holds the entire forest in host RAM and is not paged from
  segment handles.
- The persistent-root tree PNS is a bounded 1×1/2×2 semantic fixture, not a
  certificate or production scheduler. Its configured `node_budget` counts
  expansions; generated node objects can exceed it. Saturated selection now
  excludes solved children, including a forced-small-infinity regression.
- The immutable segment store is single-writer and restart-verifying. Lazy mode
  proves zero retained Python payload bytes after bounded spills, streams
  segment sealing without a second full-segment value, rehashes a mapped
  segment before returning copied bytes, and can reject a restart that misses
  an externally pinned manifest tip. Existing mappings are reused only after
  independently verifying the current pathname, but one mapping remains open
  per segment and every historical segment is rehashed. It does not bound peak
  RSS, mmap/handle/metadata growth, or complete-lineage validation work;
  cumulative manifests grow quadratically across generations. It assumes
  immutable/exclusive files and externally enforced single-writer access, uses
  fixed SHA-256 as the segment/manifest integrity assumption, and has no WAL,
  orphan recovery, compaction, garbage collection, or distributed merge.
  Windows cannot directory-fsync through the portable Python interface. This
  is not yet evidence of campaign-scale NVMe spill.
- Tiny recomputation certificates require rerunning the solver; they are not a
  compact standalone 19×19 strategy proof.
- No neural model is included. Future neural ordering must remain heuristic.
- The canonical rules profile is one explicit interpretation of “standard.”
  Changing komi, scoring, suicide, superko, or termination defines a different
  game and invalidates the root digest.
