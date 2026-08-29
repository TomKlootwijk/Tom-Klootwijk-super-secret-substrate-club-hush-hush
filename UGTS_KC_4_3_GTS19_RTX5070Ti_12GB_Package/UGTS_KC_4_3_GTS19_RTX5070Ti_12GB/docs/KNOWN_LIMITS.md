# Known limits

- The unrestricted empty 19×19 root is `UNKNOWN` in this release.
- The Python engine is a correctness oracle, not a performant 19×19 solver.
- The included proof-number search has explicit-tree storage and no production
  transposition database.
- The CUDA code implements occupancy masks only; it is not a complete legal-move
  kernel and is not proof-authoritative without CPU verification.
- CUDA 12.8 now compiles on the target laptop, and the device probe ran on an
  NVIDIA GeForce RTX 5070 Ti Laptop GPU at compute capability 12.0. The probe
  validates CUDA/device discovery only: the occupancy-mask kernel itself has not
  yet been executed against Python/C++ reference cases or benchmarked.
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
- The bounded `PersistentHistory`/`persistent_engine` path provides canonical
  structurally shared PSK roots and exact transitions through 19×19-shaped
  records, but it is not connected to the proof DAG. Its JSON loader fully
  materializes input and requires an externally trusted root pin for an
  authoritative restart.
- The immutable segment store is single-writer and restart-verifying. It has no
  WAL, compaction, garbage collection, distributed merge, or production
  recovery tool; Windows cannot directory-fsync through the portable Python
  interface. It is not yet evidence of campaign-scale NVMe spill.
- Tiny recomputation certificates require rerunning the solver; they are not a
  compact standalone 19×19 strategy proof.
- No neural model is included. Future neural ordering must remain heuristic.
- The canonical rules profile is one explicit interpretation of “standard.”
  Changing komi, scoring, suicide, superko, or termination defines a different
  game and invalidates the root digest.
