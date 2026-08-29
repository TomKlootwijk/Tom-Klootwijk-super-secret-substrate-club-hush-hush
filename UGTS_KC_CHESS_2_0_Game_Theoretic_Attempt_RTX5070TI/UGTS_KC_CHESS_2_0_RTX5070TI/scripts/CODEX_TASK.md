# CODEX TASK: proof-preserving RTX 5070 Ti chess campaign

Read `docs/CODEX_HANDOFF.md`, `spec/CHESS_2_0_FORMAL_DEFINITION.md` and the report before editing.

1. Build the `rtx5070ti-release` preset with CUDA architecture 120.
2. Preserve the Python oracle and all exact perft outputs.
3. Run differential testing for the CUDA mover. Any extra/missing move is release-blocking.
4. Measure batch expansion and fixed-point demonstration on the physical laptop.
5. Implement a disk-backed content-addressed frontier/proof DAG without replacing full state/history by a 64-bit hash.
6. Add complete dead-position certificate handling or leave affected proof nodes UNKNOWN.
7. Integrate exact external tablebase partitions only through profile-labeled, independently verified adapters.
8. Work one root obligation at a time. Candidate WDL results remain non-authoritative until a separate checker record is attached.
9. Never report the initial position as WIN/DRAW/LOSS unless all corresponding quantified obligations are complete.
10. Commit device evidence under `validation/device/`; do not overwrite the supplied host evidence.
