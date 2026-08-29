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

The native suite now includes an exact host-memory proof-number DAG for board
sizes 1×1 through 19×19. It uses complete canonical state bytes for identity,
deterministic most-proving selection, saturating 64-bit proof arithmetic, and
real transposition reuse. Its completed 2×2 threshold graphs match the Python
oracle's canonical SHA-256 graph regression fingerprints; those hashes pin the
tested artifacts but do not establish state identity. The native CLI exposes
bounded work directly:

```text
build-cpu/Release/ugts_go_pndag.exe 19 15 1 2
```

On the canonical empty root that two-expansion command returns `UNKNOWN` with
proof/disproof numbers `1/361`, 725 nodes, 724 edges, and graph SHA-256
`03dfd8263b423501147a0be09d2ccd1e23f51c2923992ed177da277740849618`.
Its canonical JSON labels itself a non-certificate bounded attempt. The native
DAG also has a separate bounded binary checkpoint mode:

```text
build-cpu/Release/ugts_go_pndag.exe 19 15 1 1 --checkpoint-dir campaign
build-cpu/Release/ugts_go_pndag.exe 19 15 1 1 --checkpoint-dir campaign \
  --resume-checkpoint campaign/checkpoints/<full-sha256>.pndag \
  --expected-checkpoint-sha256 <full-sha256>
```

Resume never scans for `CURRENT` or the newest file: retain the returned path
and complete-file SHA outside the store, then supply both, while keeping its
hash-linked predecessor files beside it and publishing continuations back to the
same store. Loading regenerates legal edges and
proof caches and validates the chain back to generation one before accepting the
graph; publication creates immutable content-addressed generations. The entire
DAG and full checkpoint buffer still live in host memory, and there are no
production TT bounds, CUDA expansion, or independent certificate extraction,
so this is not a 19×19 solution. A bounded budget stop remains `UNKNOWN`.

## Configure the optional CUDA scaffolding

The build deliberately uses `native` architecture detection rather than assuming a compute capability from a marketing name.

```bash
cmake -S cpp -B build-cuda \
  -DUGTS_ENABLE_CUDA=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build build-cuda --config Release
ctest --test-dir build-cuda -C Release --output-on-failure
./build-cuda/ugts_go19_gpu_probe
```

On Windows, run the probe from the selected configuration directory if the generator places executables under `Release/`.

The original CUDA API still computes batched empty-point masks from packed
bitplanes. Its target-laptop gate covers 13 deterministic protocol cases, genuinely
pre-enqueued dual streams, the 16,776,960-word production grid-stride boundary,
aliased inputs, input immutability, tail masking, canaries, and invalid arguments.
It completed 13,038 Python/CUDA and 33,580,510 total C++/CUDA exact word
comparisons, plus 33,606,586 input-immutability comparisons, with zero
mismatches; Compute Sanitizer reported zero errors. This validates the unchanged
occupancy primitive, not full legality.

A sibling asynchronous kernel now deterministically evaluates every fixed point
slot for groups, liberties, simultaneous captures, post-capture own liberty,
canonical no-suicide rejection, and child bitplanes. Its fail-closed adapter
does not trust either GPU accepts or rejects: after stream synchronization the
C++ rules engine recomputes every point, compares every local status/count/child
word, and alone applies exact positional superko and game metadata. Pass and
proof updates remain CPU-only. On the target GPU, the bounded independent gate
covered 124 states and 25,281 unique point slots across sizes 1, 2, 3, 5, 9,
and 19; the default/nondefault parity modes made 50,562 Python/C++/CUDA point
comparisons with zero mismatches. Low-level dual-stream guards crossed the
524,280-candidate production grid capacity with 524,533 exact slot comparisons,
and Compute Sanitizer memcheck, racecheck, and initcheck were clean.

The follow-on scale gate traversed 10,000,303 point slots from 27,716 exact-
distinct semantic states once on the default stream, then traversed the same
complete corpus on a nondefault stream for 20,000,606 total C++/CUDA checks.
The unique breadth includes 554,496 slots from reachable full-history 19×19
campaign snapshots and 9,444,121 from deterministic randomized 19×19 boards
with injective ordinal bytes. Canonical state bytes independently reject any
duplicate; 409 randomized states additionally poison an exact local child,
bringing each mode to 411 exact PSK rejections. Every slot—including occupied,
suicide, local candidate, capture, and PSK cases—was CPU-recomputed inside the
production adapter; both modes had the same result digest and zero mismatches.
The measured adapter-plus-validation rates were 157,735 and 197,008 slots/s on
this laptop. These are hardware-
specific, non-proof C++/CUDA measurements: Python was not run over the 10m
corpus, and proof-path integration and the unrestricted 19×19 result remain
open.

The target-run summary is archived at
`evidence/local_m4_cuda_empty_mask_parity.json`, and the source-pinned memcheck
result is `evidence/local_m4_cuda_compute_sanitizer.json`. The local-transition
counterparts are `evidence/local_m4_cuda_local_transition_parity.json` and
`evidence/local_m4_cuda_local_transition_compute_sanitizer.json`. Scale evidence
is `evidence/local_m4_cuda_local_transition_scale_10m.json`; its complete-corpus
representative memcheck is
`evidence/local_m4_cuda_local_transition_scale_sanitizer.json`.

Rerun the bounded parity gates with:

```bash
python cpp/tests/cuda_empty_mask_parity.py \
  --evaluator build-cuda/ugts_go_cuda_empty_mask_eval \
  --output evidence/local_m4_cuda_empty_mask_parity.json
python cpp/tests/cuda_local_transition_parity.py \
  --evaluator build-cuda/ugts_go_cuda_local_transition_eval \
  --guard-evaluator build-cuda/ugts_go_cuda_local_transition_guards \
  --output evidence/local_m4_cuda_local_transition_parity.json
python cpp/tests/cuda_local_transition_scale.py \
  --runner build-cuda/ugts_go_cuda_local_transition_scale \
  --target-unique-corpus-slots 10000000 \
  --batch-states 16 \
  --seed 88442398638062 \
  --output evidence/local_m4_cuda_local_transition_scale_10m.json
```

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

The M2 storage primitives are also present as bounded Python components:
`PersistentHistory` supplies canonical structurally shared PSK roots,
including a compact multi-root forest artifact that globally deduplicates exact
boards and immutable trie nodes,
`persistent_engine` applies exact moves without rebuilding flat repetition sets,
`PersistentProofNumberSearch` proves the complete 1×1/2×2 threshold fixtures on
those roots, `PersistentProofNumberDAG` checkpoints and resumes a transposition
DAG over the same exact roots without retaining per-node serialized history
artifacts, its compact checkpoint codec replaces repeated on-disk histories with
one shared forest and preserves that physical sharing after load, its
checkpoint-generation store adds
exact-prefix-validated immutable generations plus externally journalable
two-phase recovery, and
`ImmutableSegmentStore` publishes exact board/history bytes through immutable
binary segments and append-only manifests.
Tests cover
fresh-store order independence, injected index collisions, pinned restart,
post-open mapped-file mutation, torn/corrupt files, and 19×19-shaped one-move
state data. The command below deterministically reruns that bounded storage
evidence. Zero retained segment payload bytes after its spill and zero retained
serialized state/history bytes in live proof nodes are not peak-RSS or campaign
total-memory bounds: boards, trie nodes, proof nodes, and transient checkpoint
bytes remain in host RAM. The compact codec reduces durable duplication but
still reconstructs a fully materialized legacy checkpoint; live objects are not
paged from the segment store. The persistent-PNDAG gate stores each compact
snapshot as one opaque segment object, forces lazy spill and pinned restart,
and strictly reloads identical `UNKNOWN` graph facts; this is an adapter test,
not live-node paging. None of these bounded components makes the 19×19 root
solved.

```bash
python scripts/storage_gate.py --validate evidence/local_m2_storage_gate.json
python scripts/persistent_pndag_gate.py --validate evidence/local_m2_persistent_pndag_gate.json
```

```bash
ugts-go19 plan-memory --free-vram-gib 10
python scripts/hardware_probe.py
```

## Continuing the campaign with Codex

Read these files in order:

1. `codex/AGENTS.md`
2. `docs/EXACTNESS_CONTRACT.md`
3. `docs/FORMAL_SPEC.md`
4. `docs/GPU_ARCHITECTURE.md`
5. `codex/TASKS.md`
6. `codex/PROMPT_FOR_CODEX.md`

Then run `codex/acceptance.sh`. Python/C++ transition parity is complete. The
current priorities are to turn the audited bounded native full-snapshot restart
into resource-bounded live-DAG paging, add an independent certificate verifier,
and integrate verified CUDA batches into the proof coordinator without moving
exact PSK or truth authority to the GPU. None may convert a resource stop into a
solved claim.

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
