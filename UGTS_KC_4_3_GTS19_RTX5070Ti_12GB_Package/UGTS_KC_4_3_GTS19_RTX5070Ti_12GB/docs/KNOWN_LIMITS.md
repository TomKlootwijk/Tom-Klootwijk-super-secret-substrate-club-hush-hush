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
- M1 Python/C++ parity passed 1,000,006 deterministic legal transitions and
  10,093,588 authoritative field comparisons with zero mismatches, including
  minimized snapback, ko, multi-capture, edge, suicide, pass, and terminal
  cases. This validates the tested transition core; it is not a 19×19 proof or
  a substitute for persistent collision-checked proof storage.
- Tiny recomputation certificates require rerunning the solver; they are not a
  compact standalone 19×19 strategy proof.
- No neural model is included. Future neural ordering must remain heuristic.
- The canonical rules profile is one explicit interpretation of “standard.”
  Changing komi, scoring, suicide, superko, or termination defines a different
  game and invalidates the root digest.
