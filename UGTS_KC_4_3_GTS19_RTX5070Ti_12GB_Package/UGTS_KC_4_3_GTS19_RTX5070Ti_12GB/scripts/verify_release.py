#!/usr/bin/env python3
"""Check release structure, JSON evidence, and internal manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source_pins(
    label: str, pins: object, expected_paths: tuple[str, ...]
) -> None:
    if type(pins) is not dict or set(pins) != set(expected_paths):
        raise SystemExit(f"{label} source pins do not name the exact gate sources")
    for relative in expected_paths:
        expected = pins[relative]
        if type(expected) is not str:
            raise SystemExit(f"{label} source pin is malformed: {relative}")
        path = ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            raise SystemExit(f"{label} source mismatch: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--attempt",
        type=Path,
        help="bounded-attempt JSON to validate; relative paths resolve from the repository root",
    )
    args = parser.parse_args()

    required = [
        "README.md",
        "docs/FORMAL_SPEC.md",
        "docs/EXACTNESS_CONTRACT.md",
        "configs/go19_canonical.toml",
        "src/ugts_go19/engine.py",
        "src/ugts_go19/persistent_engine.py",
        "src/ugts_go19/persistent_history.py",
        "src/ugts_go19/persistent_pns.py",
        "src/ugts_go19/persistent_pndag.py",
        "src/ugts_go19/persistent_pndag_checkpoint_store.py",
        "src/ugts_go19/persistent_pndag_compact_checkpoint.py",
        "src/ugts_go19/pndag.py",
        "src/ugts_go19/segment_store.py",
        "cpp/include/ugts_go19/pndag.hpp",
        "cpp/include/ugts_go19/pndag_checkpoint.hpp",
        "cpp/cuda/gpu_probe.cu",
        "cpp/cuda/packed_kernels.cu",
        "cpp/cuda/packed_kernels.cuh",
        "cpp/cuda/cuda_verified_expander.cu",
        "cpp/include/ugts_go19/cuda_verified_expander.hpp",
        "cpp/src/go_state.cpp",
        "cpp/src/pndag.cpp",
        "cpp/src/pndag_checkpoint.cpp",
        "cpp/src/pndag_cli.cpp",
        "cpp/tests/pndag_checkpoint_cli_test.py",
        "cpp/tests/pndag_checkpoint_test.cpp",
        "cpp/tests/pndag_cli_test.py",
        "cpp/tests/pndag_test.cpp",
        "cpp/tests/cuda_empty_mask_eval.cu",
        "cpp/tests/cuda_empty_mask_parity.py",
        "cpp/tests/cuda_local_transition_eval.cu",
        "cpp/tests/cuda_local_transition_guards.cu",
        "cpp/tests/cuda_local_transition_parity.py",
        "schemas/pndag_checkpoint.schema.json",
        "schemas/native_pndag_checkpoint_v1.md",
        "schemas/persistent_pndag_checkpoint.schema.json",
        "schemas/persistent_pndag_compact_checkpoint.schema.json",
        "scripts/parity_gate.py",
        "scripts/storage_gate.py",
        "scripts/persistent_pndag_gate.py",
        "evidence/local_m1_cpp_python_parity_v2_1m.json",
        "evidence/local_m2_storage_gate.json",
        "evidence/local_m2_persistent_pndag_gate.json",
        "evidence/local_m4_cuda_empty_mask_parity.json",
        "evidence/local_m4_cuda_compute_sanitizer.json",
        "evidence/local_m4_cuda_local_transition_parity.json",
        "evidence/local_m4_cuda_local_transition_compute_sanitizer.json",
        "codex/AGENTS.md",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        raise SystemExit(f"missing release files: {missing}")

    cuda_evidence_path = ROOT / "evidence" / "local_m4_cuda_empty_mask_parity.json"
    cuda_evidence = json.loads(cuda_evidence_path.read_text(encoding="utf-8"))
    expected_cuda_evidence = {
        "aliased_input_launches": 2,
        "canary_checks": 320,
        "cases": 13,
        "compute_capability": "12.0",
        "cpp_cuda_compared_words": 33_580_510,
        "device_name": "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
        "format": "ugts-go19-cuda-empty-mask-parity-v2",
        "grid_stride_cpp_cuda_compared_words": 33_554_434,
        "grid_stride_extra_words": 257,
        "grid_stride_launches": 2,
        "input_immutability_compared_words": 33_606_586,
        "mismatches": 0,
        "negative_argument_checks": 12,
        "production_grid_capacity_words": 16_776_960,
        "protocol_cpp_cuda_compared_words": 26_076,
        "python_cuda_compared_words": 13_038,
        "root_status": "UNKNOWN",
        "stream_modes": ["default", "dual", "nondefault"],
    }
    if cuda_evidence != expected_cuda_evidence:
        raise SystemExit(
            "bounded CUDA occupancy evidence does not match its target gate"
        )

    sanitizer_path = ROOT / "evidence" / "local_m4_cuda_compute_sanitizer.json"
    sanitizer = json.loads(sanitizer_path.read_text(encoding="utf-8"))
    if (
        sanitizer.get("format") != "ugts-go19-cuda-compute-sanitizer-evidence-v1"
        or sanitizer.get("sanitizer_tool") != "memcheck"
        or sanitizer.get("error_summary") != 0
        or sanitizer.get("evaluator_exit_code") != 0
        or sanitizer.get("root_status") != "UNKNOWN"
        or sanitizer.get("device_name") != "NVIDIA GeForce RTX 5070 Ti Laptop GPU"
        or sanitizer.get("compute_capability") != "12.0"
    ):
        raise SystemExit("bounded CUDA sanitizer evidence has an invalid result")
    validate_source_pins(
        "bounded CUDA occupancy sanitizer evidence",
        sanitizer.get("source_sha256"),
        (
            "cpp/cuda/packed_kernels.cu",
            "cpp/cuda/packed_kernels.cuh",
            "cpp/tests/cuda_empty_mask_eval.cu",
            "cpp/tests/cuda_empty_mask_parity.py",
        ),
    )

    transition_path = ROOT / "evidence" / "local_m4_cuda_local_transition_parity.json"
    transition = json.loads(transition_path.read_text(encoding="utf-8"))
    transition_production_pins = transition.pop("production_source_sha256", None)
    transition_gate_pins = transition.pop("gate_source_sha256", None)
    transition_reference_pins = transition.pop("reference_source_sha256", None)
    expected_transition = {
        "adversarial_cases": 18,
        "board_sizes": [1, 2, 3, 5, 9, 19],
        "compute_capability": "12.0",
        "corpus_sha256": (
            "55b7bbfcd6eee3b467a919bd406c8b7f71c35de96081cd45ece003f9f7c1112e"
        ),
        "cpp_cuda_compared_child_words_across_streams": 541_184,
        "cpp_cuda_recomputed_point_slots_across_streams": 50_562,
        "dense_device_bytes_per_19x19_state": 36_606,
        "device_name": "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
        "format": "ugts-go19-cuda-local-transition-parity-v1",
        "low_level_guards": {
            "aliased_input_launches": 1,
            "canary_checks": 100,
            "child_word_comparisons": 21_660,
            "compute_capability": "12.0",
            "dirty_tail_states": 1,
            "dual_stream_launches": 2,
            "grid_stride_candidates": 524_533,
            "grid_stride_extra_candidates": 253,
            "grid_stride_slot_comparisons": 524_533,
            "input_immutability_comparisons": 18_993,
            "invalid_player_states": 1,
            "mismatches": 0,
            "overlapping_plane_states": 1,
            "production_grid_capacity_candidates": 524_280,
            "repeat_process_runs": 2,
            "reverse_sync_checks": 1,
            "root_status": "UNKNOWN",
        },
        "maximum_capture_fixture_stones": 360,
        "mismatches": 0,
        "negative_argument_checks_across_processes": 120,
        "nonterminal_one_pass_states": 1,
        "parity_evaluator_process_runs": 12,
        "per_stream_globally_legal_children": 23_899,
        "per_stream_local_candidates": 23_901,
        "per_stream_occupied_slots": 1_371,
        "per_stream_suicide_slots": 9,
        "per_stream_superko_rejections": 2,
        "per_stream_verified_point_slots": 25_281,
        "python_cuda_compared_point_slots_across_streams": 50_562,
        "root_status": "UNKNOWN",
        "scope": "pre-superko-local-point-transitions; CPU-authoritative",
        "stream_modes": ["default", "nondefault", "dual-reverse-sync"],
        "unique_corpus_point_slots": 25_281,
        "unique_corpus_states": 124,
        "verified_point_slots_across_streams": 50_562,
    }
    if transition != expected_transition:
        raise SystemExit(
            "bounded CUDA local-transition evidence does not match its target gate"
        )
    validate_source_pins(
        "bounded CUDA local-transition production evidence",
        transition_production_pins,
        (
            "cpp/cuda/packed_kernels.cu",
            "cpp/cuda/packed_kernels.cuh",
            "cpp/cuda/cuda_verified_expander.cu",
            "cpp/include/ugts_go19/cuda_verified_expander.hpp",
        ),
    )
    validate_source_pins(
        "bounded CUDA local-transition gate evidence",
        transition_gate_pins,
        (
            "cpp/tests/cuda_local_transition_eval.cu",
            "cpp/tests/cuda_local_transition_guards.cu",
            "cpp/tests/cuda_local_transition_parity.py",
        ),
    )
    validate_source_pins(
        "bounded CUDA local-transition reference evidence",
        transition_reference_pins,
        (
            "cpp/include/ugts_go19/go_state.hpp",
            "cpp/src/go_state.cpp",
            "src/ugts_go19/constants.py",
            "src/ugts_go19/engine.py",
            "src/ugts_go19/rules.py",
            "src/ugts_go19/state.py",
        ),
    )

    transition_sanitizer_path = (
        ROOT / "evidence" / "local_m4_cuda_local_transition_compute_sanitizer.json"
    )
    transition_sanitizer = json.loads(
        transition_sanitizer_path.read_text(encoding="utf-8")
    )
    transition_sanitizer_pins = transition_sanitizer.pop("source_sha256", None)
    expected_transition_sanitizer = {
        "compute_capability": "12.0",
        "cuda_compiler": "12.8.61",
        "device_name": "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
        "error_exitcode": 99,
        "format": ("ugts-go19-cuda-local-transition-compute-sanitizer-evidence-v1"),
        "guard_fixture": {
            "aliased_input_launches": 1,
            "canary_checks": 100,
            "child_word_comparisons": 21_660,
            "dirty_tail_states": 1,
            "dual_stream_launches": 2,
            "grid_stride_candidates": 524_533,
            "grid_stride_extra_candidates": 253,
            "grid_stride_slot_comparisons": 524_533,
            "input_immutability_comparisons": 18_993,
            "invalid_player_states": 1,
            "mismatches": 0,
            "overlapping_plane_states": 1,
            "production_grid_capacity_candidates": 524_280,
            "reverse_sync_checks": 1,
        },
        "limitations": [
            (
                "this is a bounded pre-superko local point-transition slice, "
                "not the 10,000,000-slot M4 gate"
            ),
            (
                "CPU recomputation remains authoritative for every point, pass, "
                "exact positional superko, metadata, and proof updates"
            ),
            (
                "the dense 19x19 device layout costs 36,606 bytes per state and "
                "no throughput claim is made"
            ),
            (
                "zero sanitizer errors and zero bounded parity mismatches do not "
                "establish the unrestricted 19x19 result"
            ),
        ],
        "root_status": "UNKNOWN",
        "runs": {
            "guard_initcheck": {"error_summary": 0, "exit_code": 0},
            "guard_memcheck": {"error_summary": 0, "exit_code": 0},
            "guard_racecheck": {
                "errors": 0,
                "exit_code": 0,
                "hazards": 0,
                "warnings": 0,
            },
            "nineteen_adversarial_evaluator_memcheck": {
                "candidate_slots": 707,
                "compared_child_words": 8_484,
                "error_summary": 0,
                "exit_code": 0,
                "fixture_labels": [
                    "nineteen-empty",
                    "capture-360-tail-point",
                    "suicide-361-group",
                    "word-and-tail-boundaries",
                ],
                "globally_legal_slots": 707,
                "negative_argument_checks": 10,
                "occupied_slots": 736,
                "protocol_bytes": 5_899,
                "protocol_sha256": (
                    "9695a6bcc4239615df870e6acf3eba59232a18fc7f4dd8f5b0ba09da2a7e03b7"
                ),
                "states": 4,
                "stream_mode": "nondefault",
                "suicide_slots": 1,
                "superko_rejections": 0,
                "verified_point_slots": 1_444,
            },
        },
        "sanitizer": "NVIDIA Compute Sanitizer 2025.1.0.0 build 35351055",
    }
    if transition_sanitizer != expected_transition_sanitizer:
        raise SystemExit("bounded CUDA local-transition sanitizer evidence is invalid")
    validate_source_pins(
        "bounded CUDA local-transition sanitizer evidence",
        transition_sanitizer_pins,
        (
            "cpp/cuda/packed_kernels.cu",
            "cpp/cuda/packed_kernels.cuh",
            "cpp/cuda/cuda_verified_expander.cu",
            "cpp/include/ugts_go19/cuda_verified_expander.hpp",
            "cpp/tests/cuda_local_transition_eval.cu",
            "cpp/tests/cuda_local_transition_guards.cu",
            "cpp/tests/cuda_local_transition_parity.py",
        ),
    )

    attempt_path = args.attempt
    if attempt_path is not None and not attempt_path.is_absolute():
        attempt_path = ROOT / attempt_path
    if attempt_path is None:
        acceptance_attempt = ROOT / "evidence" / "acceptance_19x19_bounded.json"
        legacy_attempt = ROOT / "evidence" / "attempt19_bounded.json"
        if acceptance_attempt.exists():
            attempt_path = acceptance_attempt
        elif legacy_attempt.exists():
            attempt_path = legacy_attempt

    attempt_status = None
    if args.attempt is not None and (
        attempt_path is None or not attempt_path.is_file()
    ):
        raise SystemExit(f"attempt file missing: {args.attempt}")
    if attempt_path is not None and attempt_path.exists():
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        if not isinstance(attempt, dict) or not isinstance(attempt.get("result"), dict):
            raise SystemExit(f"invalid attempt envelope: {attempt_path}")
        attempt_status = attempt["result"].get("status")
        if attempt_status not in {"PROVEN", "DISPROVEN", "UNKNOWN"}:
            raise SystemExit(f"invalid attempt status: {attempt_status}")

    manifest_path = ROOT / "SHA256SUMS.txt"
    if manifest_path.exists() and not args.quick:
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            expected, relative = line.split("  ", 1)
            path = ROOT / relative
            if not path.is_file():
                raise SystemExit(f"manifest file missing: {relative}")
            if sha256(path) != expected:
                raise SystemExit(f"manifest mismatch: {relative}")
    print(
        json.dumps(
            {
                "ok": True,
                "quick": args.quick,
                "root": str(ROOT),
                "attempt": str(attempt_path) if attempt_path is not None else None,
                "attempt_status": attempt_status,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
