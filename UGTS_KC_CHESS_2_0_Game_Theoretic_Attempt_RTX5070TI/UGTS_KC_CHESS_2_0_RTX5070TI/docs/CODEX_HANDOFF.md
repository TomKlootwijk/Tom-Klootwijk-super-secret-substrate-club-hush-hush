# Codex handoff - RTX 5070 Ti Laptop 12 GB

## Objective

Build and measure the supplied foundation, then extend it only through proof-preserving interfaces. The target is not "play strong chess"; it is to close content-addressed WDL obligations for the classical initial position while returning `UNKNOWN` whenever a proof is incomplete.

## First run

1. Record `nvidia-smi`, driver version, exact GPU name, total/free VRAM, laptop power mode, OS and CUDA toolkit.
2. Run `scripts/build_rtx5070ti.ps1` from a Visual Studio x64 developer environment or equivalent CMake/Ninja shell.
3. Run both native self-tests and the Python test suite.
4. Run `ugts-chess-gpu device-info`. Confirm the runtime compute capability is 12.0 before using the `sm_120` preset.
5. Run `scripts/run_codex_campaign.ps1`; retain all JSON output under `validation/device/`.

## Non-negotiable proof boundaries

- Candidate generation may be parallel, approximate or GPU-accelerated.
- Legal move verification, state transition, repetition identity and proof obligation checking remain deterministic and independently replayed.
- A root is WIN only if one verified child is LOSS from the child's perspective.
- A root is LOSS only if every legal action is covered and every child is verified WIN.
- A root is DRAW only after complete no-win coverage and a verified draw action/closed complement argument.
- A budget stop, cache miss, hash collision risk, unverified tablebase probe or finite horizon is UNKNOWN.
- Claimable draws are player actions. They are not forced terminals.
- Checkmate is terminal before an automatic 75-move draw.

## Suggested Codex engineering sequence

1. Make the CUDA build pass without changing the host oracle.
2. Differential-test every CUDA-generated move list against `ugts_chess.rules.legal_moves` on all packaged fixtures and a seeded random legal corpus.
3. Benchmark CPU versus CUDA batch expansion with equal exact outputs.
4. Add an append-only binary frontier format with full reconstructibility, CRC/SHA checks and a versioned rule-profile ID.
5. Add a disk-backed transposition/proof DAG. A 64-bit key may index records but may not replace the full state/history identity.
6. Integrate external endgame partitions through an adapter whose results are rechecked and profile-labeled.
7. Implement complete dead-position certificates or keep affected nodes UNKNOWN.
8. Close root shards independently; merge only verifier-accepted certificates.

## Required device evidence

Capture p50/p95/p99 batch latency, positions/s, moves/s, peak VRAM, host RAM, storage bytes per verified node, 5/15/30-minute clocks/temperature/power behavior, CUDA fallback reasons, and differential mismatch count. Any mismatch blocks proof use.
