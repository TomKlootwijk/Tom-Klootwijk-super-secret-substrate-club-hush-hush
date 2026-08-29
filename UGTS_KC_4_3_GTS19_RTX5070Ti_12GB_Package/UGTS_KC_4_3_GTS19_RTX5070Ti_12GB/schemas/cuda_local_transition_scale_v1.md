# CUDA local-transition scale evidence v1

`evidence/local_m4_cuda_local_transition_scale_10m.json` records a bounded,
source-pinned run of `VerifyCudaLocalPointTransitions`. It is functional and
hardware-specific evidence. It is not a proof certificate.

## Reproduction

Build `ugts_go_cuda_local_transition_scale` in Release mode with CUDA enabled,
then run from the repository root:

```text
python cpp/tests/cuda_local_transition_scale.py \
  --runner build-cuda/ugts_go_cuda_local_transition_scale \
  --target-unique-corpus-slots 10000000 \
  --batch-states 16 \
  --seed 88442398638062 \
  --output evidence/local_m4_cuda_local_transition_scale_10m.json
```

On a multi-configuration Windows generator, use the executable under its
`Release` directory. Evidence publication uses a same-directory temporary file,
flush, and atomic replacement.

`scale_runner_executable_sha256` is the lowercase SHA-256 digest of the exact
runner path supplied to the 10m wrapper. The wrapper hashes that executable
immediately before process launch and again immediately after it returns. A
missing runner or any digest change fails closed before evidence publication.

This field identifies the tested executable bytes observed at both boundaries.
The `production_source_sha256`, `gate_source_sha256`, and
`reference_source_sha256` maps separately pin source files. Neither the binary
digest nor those source pins prove that the executable was compiled from the
pinned sources; this artifact does not claim a reproducible-build or compiler
attestation.

The ordinary CUDA CTest suite runs a smaller structural invocation. That test
still traverses the complete deterministic corpus in both stream modes, but it
does not claim ten million slots. The full campaign is an explicit command.

## Count semantics

- `unique_semantic_states` is the exact number of distinct canonical semantic
  states in the corpus. The runner rejects duplicate canonical state bytes.
- `unique_corpus_point_slots` counts every board point over that exact-distinct
  corpus exactly once. It must independently reach the 10m breadth target.
- `primary_unique_mode_cpp_cuda_cpu_recomputed_point_slots` is the default-mode
  traversal of that complete corpus, with no repeated state visits.
- `additional_stream_mode_recomputed_point_slots` is a second complete traversal
  on a nondefault stream. It tests stream determinism but is not added to the
  unique-breadth claim.
- `total_cpp_cuda_cpu_recomputed_point_slots_across_modes` is the sum of both
  traversals. Every slot crossed the production adapter boundary and was
  recomputed by the C++ rules authority.
- `python_compared_point_slots` is zero. The separate 25k parity artifact remains
  the Python/C++/CUDA cross-language gate and is pinned as a companion; the 10m
  number must not be described as Python comparison.

The state corpus is deterministic from `seed`. It includes sizes 1, 2, 3, 5, 9,
and 19; capture, suicide, ko/PSK, pass-metadata, packed-word/tail fixtures;
randomized dense 19x19 states with injective base-3 ordinal bytes; and
exact-history snapshots obtained from deterministic 19x19 legal-play campaigns.
Canonical-byte duplicate rejection is independent of the ordinal construction.
Every 64th randomized state also carries one exact locally legal child in its
PSK set, producing hundreds of exact-history rejection checks. Category slot
maps expose all contributions.

## Required invariants

For each mode:

1. `point_slots = occupied_slots + suicide_slots + local_candidates`.
2. `local_candidates = superko_rejections + globally_legal_children`.
3. Every adapter summary equals a second count over its returned fixed slots.
4. Legal-child ordering, capture counts, and raw child boards match the verified
   slot payloads.
5. Default and nondefault modes have the same deterministic result digest and
   all exact counters.
6. `high_water_requested_device_bytes` does not exceed the minimum workspace
   budget computed with the production adapter's reserve policy.
7. Any CUDA, status, payload, count, stream, resource, or CPU replay mismatch
   exits nonzero before evidence is written.

Elapsed time and slots per second cover adapter calls plus streamed result
validation/digest consumption. They are non-proof, hardware-specific
measurements. Corpus generation and process startup are excluded.

`evidence/local_m4_cuda_local_transition_scale_sanitizer.json` records a bounded
representative Compute Sanitizer memcheck over the complete corpus and both
stream modes. It intentionally does not rerun all 10m slots under the sanitizer.
Its `memcheck_scale_runner_executable_sha256` field applies the same immediate
pre-launch and post-return stability check to the scale runner launched under
memcheck. It is deliberately distinct from the 10m artifact's
`scale_runner_executable_sha256`: each digest identifies the runner bytes tested
by that particular invocation. The memcheck field does not attest the Compute
Sanitizer executable itself; the artifact records that tool's reported version
separately.

## Scope limit

The GPU kernel stops before exact positional-superko authority. The adapter
performs exact raw-board PSK checks and returns CPU `ApplyMove` children. Pass,
metadata, proof propagation, and proof search remain outside this scale gate.
The unrestricted 19x19 root remains `UNKNOWN`.
