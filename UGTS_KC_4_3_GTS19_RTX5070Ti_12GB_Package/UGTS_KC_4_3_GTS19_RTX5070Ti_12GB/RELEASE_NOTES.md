# Release notes — UGTS-KC 4.3.0 GTS-19

## Purpose

This release is a game-theoretic **attempt and implementation foundation** for
the empty unrestricted 19×19 game identified by
`UGTS-GO19-AREA-PSK-K7.5-v1`. It is packaged for continued work by Codex on a
user-specified RTX 5070 Ti Laptop GPU with 12 GB VRAM.

## Current determination

- Exact empty 2×2 regression: Black by 0.5 under the fixture profile.
- Empty 19×19 threshold `Black score2 >= 1`: **UNKNOWN** after the included
  bounded proof-number preflight.
- No 19×19 winner or exact margin is claimed.

## Verified implementation status

- M0 is complete on the target Windows laptop: the Python suite, deterministic
  1×1/2×2 fixture generation, fresh-process certificate verification, C++
  build/CTest, canonical bounded preflight, and hardware probe pass.
- Recomputations use `UGTS-GO-RECOMPUTE-CERT-v2`. Its hashed core is limited to
  deterministic proof-relevant rules/root/value fields; timing, search counters,
  and principal-variation diagnostics cannot perturb certificate identity.
- The Python exact oracle now validates state/history inputs, rejects profiles
  whose infinite-play utility is undefined, handles a completed root safely when
  principal-variation extraction reaches a budget, and retains differential
  off-switch coverage for pass-first ordering.
- C++ distinguishes rule-illegal moves from malformed inputs with the
  `IllegalMove` exception taxonomy, preventing invalid states from being silently
  reported as shorter legal masks.
- M1 C++ semantic parity is complete. The deterministic campaign compared
  1,000,006 legal transitions across 31,176 exact states, including adversarial
  snapback, ko, multi-capture, edge, suicide, pass, and terminal cases, with zero
  mismatches across 10,093,588 authoritative raw fields. The native core also
  has exact complete-history equality and shared `UGTS-GO-STATE-v1`
  serialization; hashes do not establish identity.
- CUDA 12.8 compiled the optional CUDA targets, and the runtime probe identified
  the NVIDIA GeForce RTX 5070 Ti Laptop GPU at compute capability 12.0. The
  occupancy kernel itself remains untested against the exact references and is
  not proof-authoritative.
- Acceptance is fail closed on Windows native-command failures and validates the
  canonical `UNKNOWN` preflight envelope before printing success.

## Important entry points

- Human overview: `README.md`
- Mathematical target: `docs/FORMAL_SPEC.md`
- Optimization rules: `docs/EXACTNESS_CONTRACT.md`
- Codex instructions: `codex/AGENTS.md` and `codex/PROMPT_FOR_CODEX.md`
- Acceptance gate: `codex/acceptance.sh` or `codex/acceptance.ps1`
- Canonical configuration: `configs/go19_canonical.toml`
- Laptop configuration: `configs/rtx5070ti_laptop_12gb.toml`
- M0 evidence: `evidence/local_m0_1x1_verify.json`,
  `evidence/local_m0_2x2_verify.json`, and
  `evidence/local_m0_hardware.json`
- M1 evidence: `evidence/local_m1_cpp_python_parity_1m.json`

## Next target-laptop action

Build the first bounded M2 persistent-history vertical slice: immutable exact
state/history records, collision fallback, atomic expansion records, and
restart verification on tractable boards. Keep CUDA outside the proof path until
those persistence and independent-recomputation invariants are established.
