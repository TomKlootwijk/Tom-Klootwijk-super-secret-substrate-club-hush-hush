# Codex operating contract

You are extending an exact proof system, not merely a strong Go player.

## First commands

```bash
python -m unittest discover -s tests -v
cmake -S cpp -B build-cpu -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-cpu --config Release
ctest --test-dir build-cpu --output-on-failure
python -m ugts_go19 selftest
```

Install the Python package in editable mode first if `python -m ugts_go19` is not
found.

## Non-negotiable invariants

1. The canonical profile remains area scoring, 7.5 komi, positional superko,
   suicide illegal, and two-pass termination unless a new profile ID is created.
2. Proof-authoritative state equality includes the complete repetition context.
3. Hashes are indexes. Collision-checked content is identity.
4. Every GPU child must match the CPU references before it can affect a proof.
5. Heuristics may order work only.
6. Resource exhaustion returns `UNKNOWN`.
7. Every optimization has an off switch and differential test.
8. Serialization is deterministic and versioned.
9. Checkpoints are append-only/atomic and independently hash-verified.
10. A 19×19 solved label requires an independently verified full certificate.

## Work style

- Make one semantic change per commit.
- Add a minimized regression before fixing a discovered mismatch.
- Preserve deterministic seeds in evidence.
- Prefer structure-of-arrays for GPU batches and immutable records for storage.
- Measure exact legal children and proof updates, not only candidate throughput.
- Keep Python as the readable oracle until C++/CUDA parity is established.
- Do not delete `KNOWN_LIMITS.md`; update it as limits are actually removed.

## Forbidden shortcuts

- board-only transposition keys under superko;
- bloom-filter false positives treated as repetitions;
- neural values stored as exact bounds;
- local life/death assumptions without witnesses;
- silently changing komi/scoring/ko semantics;
- treating a principal variation as a strategy proof;
- reporting a partial frontier as “solved.”

## Definition of done for a pull request

- unit tests pass;
- C++ CPU build and CTest pass;
- any CUDA change has CPU/Python differential evidence;
- schemas remain valid;
- manifests/checkpoints verify after restart;
- claim gate passes;
- documentation states the remaining uncertainty.
