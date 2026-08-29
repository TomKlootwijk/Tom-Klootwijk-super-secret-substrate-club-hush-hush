# UGTS-KC Chess 2.0 - Classical Game-Theoretic Campaign

Canonical component identity: `ugts.application.chess-proof@2.0.0`

## Dedication

This proof campaign is dedicated to **Anna Cramling and the Cow Opening**.
The dedication may guide campaign lineage and work priority, but never changes
the proof standard: all twenty initial legal moves remain quantified
obligations, and incomplete evidence remains `UNKNOWN`.
The scheduler gives the transpositional Cow starts `1.d3` and `1.e3` equal,
modest priority; this is a queue-order hint only.

This package is an upgraded proof foundation for an **attempted game-theoretic solution of classical chess**. It turns the initial position into twenty independently checkable root obligations, preserves exact legal and history state, supplies bounded WIN/LOSS/DRAW certificates, retains exact KQK/KRK tablebases, and adds two native C++20 programs with optional CUDA 12.8+ backends for an NVIDIA GeForce RTX 5070 Ti Laptop GPU with 12 GB VRAM.

The captured result is **UNKNOWN for the orthodox initial position**. That is a valid proof status, not a draw claim. The package does not present engine strength, a principal variation, or a finite search cutoff as a solution.

## Exact and proof-oriented parts

- Strict FEN and full orthodox legal-move generation: castling, en-passant, promotion and king safety.
- Checkmate, stalemate, automatic fivefold/75-move draws, and a conservative built-in dead-position certificate subset.
- Threefold and 50-move claims represented as optional actions, including claims made by declaring an intended move.
- History-correct state hashes using exact repetition-count records; 64-bit keys remain cache keys only.
- Bounded WDL proof nodes: WIN needs one certified LOSS child; LOSS needs complete successor coverage; DRAW needs complete no-win coverage plus a draw strategy or closed complement; cutoffs remain UNKNOWN.
- SQLite proof-campaign ledger with twenty root shards, leases, candidate records, replayed certificate verification and a hash-chained event journal.
- Append-only, checksummed frontier records binding canonical FEN, exact repetition history, lineage and the canonical rules profile.
- A crash-recoverable SQLite transposition/DAG index derived from that frontier; exact state stays authoritative and indexed WDL remains `UNKNOWN` until a verified-certificate layer is added.
- Exact KQK and KRK WDL/DTM tables and retained forced-mate certificates.
- Native C++ legality, alpha-beta, mate proof and fixed-point demonstration.
- Optional CUDA proposal/fixed-point kernels. CUDA does not bypass the independent verifier.

## RTX 5070 Ti Laptop handoff

Two native executables are built:

- `ugts-chess2`: rules, perft, bounded search, mate proof, root sharding and a finite WDL fixed-point demonstration.
- `ugts-chess-gpu`: 64-byte packed position / 16-bit move protocol, CPU fallback, CUDA batch move expansion and device inspection.

The checked-in RTX preset requests CUDA architecture `120` (`sm_120`). Runtime device inspection is authoritative: laptop power limits, free VRAM, driver/toolkit compatibility and thermal behavior vary by system.

The latest physical-device run and its explicit claim boundary are summarized
in [`validation/device/README.md`](validation/device/README.md).

```powershell
# Windows PowerShell from the package root
powershell -ExecutionPolicy Bypass -File scripts/build_rtx5070ti.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_codex_campaign.ps1
```

```bash
# Linux / WSL host validation
bash scripts/build_host.sh
PYTHONPATH=src python -m ugts_chess campaign-init \
  --out-dir examples/campaign --force
PYTHONPATH=src python -m ugts_chess campaign-verify examples/campaign/initial.sqlite3
```

## Quick exact checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m ugts_chess perft --depth 4
PYTHONPATH=src python -m ugts_chess bounded-wdl \
  --fen "8/8/8/1Q6/8/8/k7/2K5 w - - 100 2" --plies 1
cpp/build/host-release/ugts-chess2 selftest
cpp/build/host-release/ugts-chess-gpu self-test
```

## Proof campaign rule

A worker may propose `win`, `draw` or `loss` for one root shard. It becomes authoritative only after a separate checker validates the rule profile, complete legal successor obligations, repetition and move-count history, certificate hashes and terminal proof. A GPU hash, cache hit or score is never enough.

## Known proof gaps

- The initial 32-piece value is unresolved.
- The built-in dead-position recognizer certifies a common exact subset; a global classical proof requires a complete dead-position oracle or certificate mechanism.
- KQK/KRK are bundled, not the full external 3- through 7-piece corpus.
- The disk-backed DAG currently provides exact storage, transpositions and auditing; it does not yet validate chess-transition semantics for every edge or promote proof certificates into node values.
- The local device gate compiled real `sm_120` CUDA with `nvcc` 12.8 and compared 4,112 deterministic fixture/reachable positions against the exact Python oracle with zero move-set mismatches or fallbacks; this validates that captured corpus, not all chess states.
- Large-batch measurements show a local throughput benefit, but no sustained thermal, battery or playing-strength advantage is claimed; the laptop was measured on its Balanced power plan.

## Package map

- `src/ugts_chess/` - Python rule oracle, WDL proof semantics, campaign ledger, tablebases and CLI.
- `cpp/` - C++20 host solvers, compact proposal protocol, CPU fixed point and optional CUDA kernels.
- `examples/campaign/` - root database, twenty shard records and exact depth-four workload evidence.
- `spec/` - formal definition, schemas, RTX profile, source register and mechanism catalog.
- `scripts/` - Codex-oriented Windows and host build/run scripts.
- `tests/` and `validation/` - captured tests, perft, native builds, protocol differential checks, schemas and hashes.
- `report/` - upgraded foundational report and editable DOCX source.

See `docs/CODEX_HANDOFF.md` first on the target laptop.
