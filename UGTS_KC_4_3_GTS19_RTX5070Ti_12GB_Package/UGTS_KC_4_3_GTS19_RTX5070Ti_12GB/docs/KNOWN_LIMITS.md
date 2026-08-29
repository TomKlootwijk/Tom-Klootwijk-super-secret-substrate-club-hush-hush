# Known limits

- The unrestricted empty 19×19 root is `UNKNOWN` in this release.
- The Python engine is a correctness oracle, not a performant 19×19 solver.
- The included proof-number search has explicit-tree storage and no production
  transposition database.
- The CUDA code implements occupancy masks only; it is not a complete legal-move
  kernel and is not proof-authoritative without CPU verification.
- CUDA compilation and execution could not be validated on the artifact build
  host unless the evidence directory explicitly says otherwise.
- The C++ reference currently pins positional superko and area scoring; the
  Python baseline contains the clearer rule serialization.
- Tiny recomputation certificates require rerunning the solver; they are not a
  compact standalone 19×19 strategy proof.
- No neural model is included. Future neural ordering must remain heuristic.
- The canonical rules profile is one explicit interpretation of “standard.”
  Changing komi, scoring, suicide, superko, or termination defines a different
  game and invalidates the root digest.
