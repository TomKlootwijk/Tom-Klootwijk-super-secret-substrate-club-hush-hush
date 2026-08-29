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

## Important entry points

- Human overview: `README.md`
- Mathematical target: `docs/FORMAL_SPEC.md`
- Optimization rules: `docs/EXACTNESS_CONTRACT.md`
- Codex instructions: `codex/AGENTS.md` and `codex/PROMPT_FOR_CODEX.md`
- Acceptance gate: `codex/acceptance.sh` or `codex/acceptance.ps1`
- Canonical configuration: `configs/go19_canonical.toml`
- Laptop configuration: `configs/rtx5070ti_laptop_12gb.toml`
- Validation summary: `evidence/validation_summary.json`

## First target-laptop action

Run the acceptance gate and hardware probe. Then implement M1, cross-language
semantic parity, before expanding the CUDA proof path.
