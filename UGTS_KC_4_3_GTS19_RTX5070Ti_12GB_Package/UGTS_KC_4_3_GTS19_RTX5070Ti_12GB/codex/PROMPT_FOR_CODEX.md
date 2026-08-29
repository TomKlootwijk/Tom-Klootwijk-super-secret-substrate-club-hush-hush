# Ready-to-paste Codex prompt

Work inside this repository as an exact-game solver engineer. Begin by reading
`AGENTS.md`, `codex/AGENTS.md`, `docs/EXACTNESS_CONTRACT.md`, and
`docs/FORMAL_SPEC.md`. Run `codex/acceptance.sh` and summarize any failing gate.

The long-term target is a game-theoretic solution of the empty 19×19 state for
profile `UGTS-GO19-AREA-PSK-K7.5-v1` on a laptop with 12 GB VRAM. The current
root status is UNKNOWN. Do not claim otherwise.

M1 C++ semantic parity is complete and archived under the v2 evidence gate.
Continue **M2 — persistent exact history** from `codex/TASKS.md`. The bounded
canonical PSK trie, root-backed transition/tree-PNS adapters, and immutable
lazy segment/restart layer are implemented and tested. A bounded restartable
persistent-root PNDAG now matches uninterrupted 2×2 threshold proofs, but its
live state bytes duplicate complete history artifacts. A compact shared-forest
checkpoint codec, exact-prefix immutable generations, externally journaled
two-phase recovery, and bounded segment-backed rehydrate are implemented, but
they still fully materialize snapshots. The next task is to replace live
duplicates with disk-backed forest/segment handles and then bound peak RAM,
metadata growth, mmap handles, and recovery work. Keep the Python engine as
oracle. Do not start CUDA proof work before the integrated M2 identity and
persistence gates pass.

Requirements:

- no board-only transposition key;
- no heuristic may alter truth;
- deterministic seeds and serialized evidence;
- Windows and Linux build instructions;
- tests and documentation updated with every semantic change;
- resource exhaustion always returns UNKNOWN;
- preserve the claim boundary in README and KNOWN_LIMITS.

Report measured results for each bounded M2 increment. Make actual code changes
and run the gates; do not provide only a design essay.
