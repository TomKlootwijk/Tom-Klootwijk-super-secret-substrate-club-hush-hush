# Ready-to-paste Codex prompt

Work inside this repository as an exact-game solver engineer. Begin by reading
`AGENTS.md`, `codex/AGENTS.md`, `docs/EXACTNESS_CONTRACT.md`, and
`docs/FORMAL_SPEC.md`. Run `codex/acceptance.sh` and summarize any failing gate.

The long-term target is a game-theoretic solution of the empty 19×19 state for
profile `UGTS-GO19-AREA-PSK-K7.5-v1` on a laptop with 12 GB VRAM. The current
root status is UNKNOWN. Do not claim otherwise.

Implement **M1 — C++ semantic parity** from `codex/TASKS.md` first. Keep the
Python engine as oracle. Add a deterministic cross-language trace format and a
randomized differential harness that checks legal actions, captures, exact
board transitions, player/pass state, positional-superko rejection, terminal
state, and area score. Minimize any mismatch into a fixture. Do not start CUDA
proof work before this gate passes.

Requirements:

- no board-only transposition key;
- no heuristic may alter truth;
- deterministic seeds and serialized evidence;
- Windows and Linux build instructions;
- tests and documentation updated with every semantic change;
- resource exhaustion always returns UNKNOWN;
- preserve the claim boundary in README and KNOWN_LIMITS.

After M1 passes, report measured results and propose the smallest auditable M2
implementation. Make actual code changes and run the gates; do not provide only
a design essay.
