# UGTS-KC 4.3 GTS-19

**Exactness-first game-theoretic search foundation for unrestricted 19×19 Go**  
**Target deployment:** one laptop with an NVIDIA RTX 5070 Ti Laptop GPU and 12 GB VRAM  
**Package status:** implementation foundation and bounded attempt; **the empty 19×19 root is not solved by this release**

This package upgrades the UGTS-KC 4.2 Go solver into a hardware-aware proof-search campaign. It defines one exact game, preserves the complete superko context in proof-authoritative state identity, provides a deterministic Python reference engine, a C++17 CPU core, optional CUDA scaffolding, compact encodings, proof-number semantics, checkpoint/certificate contracts, and a staged task plan for Codex.

## The exact proof target

Profile `UGTS-GO19-AREA-PSK-K7.5-v1` is:

- 19×19 board, Black to play from empty;
- deterministic area scoring;
- 7.5 komi, stored as integer `komi2 = 15`;
- positional superko;
- suicide illegal;
- two consecutive passes terminate;
- no move limit or search-depth limit in the mathematical game.

A practical run may have a node, time, RAM, VRAM, or disk budget. A budget stop returns `UNKNOWN`; it never converts an estimate into a proof.

## Delivered result

The package performs three different jobs and labels them separately:

1. **Exact miniature regression.** The Python reference solver exhaustively solves tiny boards and emits recomputation certificates.
2. **Exact 19×19 formulation.** Score thresholds are represented as AND/OR propositions with proof and disproof numbers. The 19×19 state includes the full repetition context.
3. **Bounded 19×19 attempt.** The included preflight expands a small proof-number frontier and is expected to return `UNKNOWN`. This validates dataflow, not the game-theoretic value.

No neural evaluation, rollout, heuristic, transposition collision, or incomplete GPU guard is allowed to produce `PROVEN` or `DISPROVEN`.

## Quick start: Python reference

```bash
cd UGTS_KC_4_3_GTS19_RTX5070Ti_12GB
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
ugts-go19 selftest
ugts-go19 solve-tiny --size 2 --komi2 1 \
  --certificate evidence/local_2x2_certificate.json
ugts-go19 verify evidence/local_2x2_certificate.json
ugts-go19 attempt19 --threshold2 1 --node-budget 64 \
  --output evidence/local_19x19_attempt.json
```

`threshold2 = 1` asks whether Black can force a strictly positive final score after 7.5 komi. Because score is represented in half-points, there is no floating-point comparison.

## Quick start: C++ CPU core

```bash
cmake -S cpp -B build-cpu -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-cpu --config Release
ctest --test-dir build-cpu --output-on-failure
```

## Configure the optional CUDA scaffolding

The build deliberately uses `native` architecture detection rather than assuming a compute capability from a marketing name.

```bash
cmake -S cpp -B build-cuda \
  -DUGTS_ENABLE_CUDA=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build build-cuda --config Release
./build-cuda/ugts_go19_gpu_probe
```

On Windows, run the probe from the selected configuration directory if the generator places executables under `Release/`.

The CUDA kernel currently computes batched empty-point masks from packed bitplanes. It is a validated accelerator boundary, **not** yet a complete proof-authoritative legality kernel. Candidate moves must still pass capture, own-liberty, suicide, and exact-superko guards.

## Laptop-safe memory policy

Do not allocate against the nominal 12 GB value. Query free VRAM at runtime and preserve a safety reserve. The default planner uses the free amount it is given, holds back 18%, and divides the remainder among:

- GPU transposition cache: 46%;
- frontier: 23%;
- batch workspace: 16%;
- proof staging: 8%;
- optional ordering heuristic: 7%.

The exact transposition store is expected to spill to host RAM and then content-addressed NVMe segments. The GPU is a hot cache and batch engine, not the sole database.

The current bounded persistence vertical slice is available as `pndag-tiny` for
1×1/2×2 only. It can create or resume a collision-checked, self-validating JSON
checkpoint; for example:

```text
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 1 \
  --additional-expansions 64 --checkpoint evidence/tiny-pndag.json
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 1 \
  --additional-expansions 10000 --checkpoint evidence/tiny-pndag.json --resume
```

This command rejects boards above 2×2 and is not the production 19×19 search or
a standalone proof certificate.

The next M2 storage primitives are also present as bounded Python components:
`PersistentHistory` supplies canonical structurally shared PSK roots,
`persistent_engine` applies exact moves without rebuilding flat repetition sets,
`PersistentProofNumberSearch` proves the complete 1×1/2×2 threshold fixtures on
those roots, and `ImmutableSegmentStore` publishes exact board/history bytes
through immutable binary segments and append-only manifests. Tests cover fresh-store order
independence, injected index collisions, pinned restart, torn/corrupt files, and
19×19-shaped one-move state data. These components are not yet wired into
`ProofNumberDAG` and do not make the 19×19 root solved.

```bash
ugts-go19 plan-memory --free-vram-gib 10
python scripts/hardware_probe.py
```

## What Codex should do first

Read these files in order:

1. `codex/AGENTS.md`
2. `docs/EXACTNESS_CONTRACT.md`
3. `docs/FORMAL_SPEC.md`
4. `docs/GPU_ARCHITECTURE.md`
5. `codex/TASKS.md`
6. `codex/PROMPT_FOR_CODEX.md`

Then run `codex/acceptance.sh`. The first implementation goal is not “solve 19×19.” It is **bit-for-bit equivalence** between Python and C++ transitions on randomized legal traces, followed by a full CUDA legality batch that is checked against both references.

## Proof-status vocabulary

- `PROVEN`: the threshold proposition is established under the serialized rules and exact state identity.
- `DISPROVEN`: its negation is established.
- `EXACT`: a complete minimax score is computed for a fixture.
- `UNKNOWN`: the run stopped before either proof number reached zero.
- `HEURISTIC`: ordering or estimation only; never proof-authoritative.

## Repository map

```text
src/ugts_go19/       collision-free Python rules/search reference
cpp/                 C++17 engine and optional CUDA batch scaffolding
configs/             laptop campaign settings
schemas/             certificate/checkpoint contracts
docs/                mathematics, exactness, GPU, storage, campaign plan
codex/               agent instructions, work packages, acceptance gate
scripts/             validation, hardware probe, estimates, release tooling
tests/               deterministic regression tests
fixtures/            generated tiny-board certificates and results
evidence/            captured validation outputs for this release
baseline/            preserved KC 4.2 artifacts when available
report/              source used to build the accompanying PDF
```

## Non-negotiable claim boundary

This release does not contain a game-theoretic solution of unrestricted standard 19×19 Go. It contains a precise target, a sound proof-search kernel, exact small-board evidence, an initial bounded 19×19 run, and an implementation plan designed for the specified laptop. A 19×19 solved claim is permitted only after an independent verifier, from a clean checkout, accepts a complete certificate whose rules/root digests match the canonical profile.
