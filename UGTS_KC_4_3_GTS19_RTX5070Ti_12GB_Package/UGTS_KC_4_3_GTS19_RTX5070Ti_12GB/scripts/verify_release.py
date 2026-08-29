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


def is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def require_sha256_attestation(label: str, value: object) -> str:
    if not is_sha256(value):
        raise SystemExit(f"{label} is missing or malformed")
    assert isinstance(value, str)
    return value


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
        "cpp/tests/cuda_local_transition_scale.cu",
        "cpp/tests/cuda_local_transition_scale.py",
        "cpp/tests/cuda_local_transition_scale_sanitizer.py",
        "schemas/pndag_checkpoint.schema.json",
        "schemas/native_pndag_checkpoint_v1.md",
        "schemas/cuda_local_transition_scale_v1.md",
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
        "evidence/local_m4_cuda_local_transition_scale_10m.json",
        "evidence/local_m4_cuda_local_transition_scale_sanitizer.json",
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

    scale_path = ROOT / "evidence" / "local_m4_cuda_local_transition_scale_10m.json"
    scale = json.loads(scale_path.read_text(encoding="utf-8"))
    scale_production_pins = scale.pop("production_source_sha256", None)
    scale_gate_pins = scale.pop("gate_source_sha256", None)
    scale_reference_pins = scale.pop("reference_source_sha256", None)
    require_sha256_attestation(
        "CUDA scale runner executable SHA-256",
        scale.pop("scale_runner_executable_sha256", None),
    )
    scale_modes = scale.pop("modes", None)
    companion = scale.pop("cross_language_companion", None)
    expected_scale = {
        "additional_stream_mode_recomputed_point_slots": 10_000_303,
        "batch_state_limit": 16,
        "build_configuration": "Release",
        "compiler": {"cuda": "NVCC-12.8.61", "host": "MSVC-194435221"},
        "corpus_entries": 27_716,
        "corpus_sha256": (
            "515841557eb7abc055ba41e6d6d4e6f5e020c1779f31c6c2947671124e46d0d1"
        ),
        "cuda_driver_version": 13_010,
        "cuda_runtime_version": 12_080,
        "device": {
            "compute_capability": "12.0",
            "name": "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
            "total_global_memory_bytes": 12_820_480_000,
        },
        "evidence_publication": (
            "same-directory temporary file, fsync, atomic replace"
        ),
        "format": "ugts-go19-cuda-local-transition-scale-v1",
        "measurement_label": (
            "hardware-specific non-proof end-to-end adapter verification and "
            "summary consumption"
        ),
        "mismatches": 0,
        "negative_fail_closed_checks": 7,
        "python_compared_point_slots": 0,
        "primary_unique_mode_cpp_cuda_cpu_recomputed_point_slots": 10_000_303,
        "root_status": "UNKNOWN",
        "scope": (
            "C++/CUDA pre-superko local point transitions; CPU ApplyMove "
            "authority; no proof-search integration"
        ),
        "seed": 88_442_398_638_062,
        "stream_modes": ["default", "nondefault"],
        "target_unique_corpus_point_slots": 10_000_000,
        "total_cpp_cuda_cpu_recomputed_point_slots_across_modes": 20_000_606,
        "unique_corpus_point_slots": 10_000_303,
        "unique_semantic_states": 27_716,
    }
    if scale != expected_scale:
        raise SystemExit("CUDA local-transition 10m scale evidence is invalid")
    if (
        type(companion) is not dict
        or companion.get("evidence")
        != "evidence/local_m4_cuda_local_transition_parity.json"
        or companion.get("scope")
        != (
            "retained 25k Python/C++/CUDA exact comparison; not included in "
            "the 10m count"
        )
        or companion.get("sha256") != sha256(transition_path)
    ):
        raise SystemExit("CUDA scale companion evidence pin is invalid")
    validate_source_pins(
        "CUDA local-transition 10m production evidence",
        scale_production_pins,
        (
            "cpp/cuda/packed_kernels.cu",
            "cpp/cuda/packed_kernels.cuh",
            "cpp/cuda/cuda_verified_expander.cu",
            "cpp/include/ugts_go19/cuda_verified_expander.hpp",
        ),
    )
    validate_source_pins(
        "CUDA local-transition 10m gate evidence",
        scale_gate_pins,
        (
            "cpp/CMakeLists.txt",
            "cpp/tests/cuda_local_transition_scale.cu",
            "cpp/tests/cuda_local_transition_scale.py",
        ),
    )
    validate_source_pins(
        "CUDA local-transition 10m reference evidence",
        scale_reference_pins,
        (
            "cpp/include/ugts_go19/go_state.hpp",
            "cpp/include/ugts_go19/sha256.hpp",
            "cpp/src/go_state.cpp",
            "cpp/src/sha256.cpp",
        ),
    )
    expected_scale_mode = {
        "adapter_batch_calls": 1_737,
        "capture_slots": 283_758,
        "captured_stones": 857_069,
        "compared_child_words": 18_650_596,
        "globally_legal_children": 1_553_936,
        "high_water_requested_device_bytes": 585_700,
        "local_candidates": 1_554_347,
        "maximum_capture": 360,
        "occupied_slots": 8_375_988,
        "point_slots": 10_000_303,
        "result_sha256": (
            "9fe1962ed876017f312a3602f74f1af23076294377ac0dae094bad26662930e1"
        ),
        "semantic_state_visits": 27_716,
        "slots_by_board_size": {
            "1": 1,
            "2": 4,
            "3": 81,
            "5": 75,
            "9": 81,
            "19": 10_000_061,
        },
        "slots_by_category": {
            "adversarial-19x19": 361,
            "adversarial-medium": 81,
            "adversarial-small": 23,
            "campaign-shaped-19x19": 554_496,
            "capture-fixture": 61,
            "capture-fixture-19x19": 361,
            "ko-psk-fixture": 59,
            "pass-metadata-fixture": 9,
            "randomized-ordinal-dense-19x19": 9_296_472,
            "randomized-ordinal-psk-19x19": 147_649,
            "suicide-fixture": 9,
            "suicide-fixture-19x19": 361,
            "word-tail-fixture-19x19": 361,
        },
        "suicide_slots": 69_968,
        "superko_rejections": 411,
    }
    if type(scale_modes) is not dict or set(scale_modes) != {
        "default",
        "nondefault",
    }:
        raise SystemExit("CUDA scale stream-mode evidence is malformed")
    for mode_name in ("default", "nondefault"):
        mode = scale_modes[mode_name]
        if type(mode) is not dict:
            raise SystemExit(f"CUDA scale {mode_name} mode is malformed")
        elapsed = mode.pop("elapsed_seconds", None)
        throughput = mode.pop("slots_per_second", None)
        minimum_free = mode.pop("minimum_free_device_bytes_before_batch", None)
        minimum_budget = mode.pop("minimum_adapter_workspace_budget_bytes", None)
        if mode != expected_scale_mode:
            raise SystemExit(f"CUDA scale {mode_name} exact counters are invalid")
        if (
            type(elapsed) not in {int, float}
            or isinstance(elapsed, bool)
            or elapsed <= 0
            or type(throughput) not in {int, float}
            or isinstance(throughput, bool)
            or throughput <= 0
            or type(minimum_free) is not int
            or minimum_free <= 0
            or type(minimum_budget) is not int
            or minimum_budget < expected_scale_mode["high_water_requested_device_bytes"]
        ):
            raise SystemExit(f"CUDA scale {mode_name} resource/timing data is invalid")
        measured = expected_scale_mode["point_slots"] / elapsed
        if abs(measured - throughput) > 1.0:
            raise SystemExit(f"CUDA scale {mode_name} throughput is inconsistent")

    scale_sanitizer_path = (
        ROOT / "evidence" / "local_m4_cuda_local_transition_scale_sanitizer.json"
    )
    scale_sanitizer = json.loads(scale_sanitizer_path.read_text(encoding="utf-8"))
    scale_sanitizer_pins = scale_sanitizer.pop("source_sha256", None)
    sanitizer_transcript_sha256 = scale_sanitizer.pop(
        "sanitizer_transcript_sha256", None
    )
    require_sha256_attestation(
        "CUDA memcheck scale runner executable SHA-256",
        scale_sanitizer.pop("memcheck_scale_runner_executable_sha256", None),
    )
    expected_scale_sanitizer = {
        "batch_state_limit": 8,
        "compute_capability": "12.0",
        "corpus_sha256": (
            "077360dda6924d29f6d47e2d3361248eb368b8cd1159d960b2152f898ba720bf"
        ),
        "device_name": "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
        "error_exitcode": 99,
        "format": "ugts-go19-cuda-local-transition-scale-sanitizer-v1",
        "limitations": [
            "bounded representative memcheck, not a sanitizer run over all 10m slots",
            "the 10m count is C++/CUDA with CPU ApplyMove authority, not Python comparison",
            "the local transition slice is not integrated into proof search",
            "zero sanitizer errors do not establish the unrestricted 19x19 result",
        ],
        "memcheck": {
            "adapter_batch_calls_across_modes": 102,
            "error_summary": 0,
            "exit_code": 0,
            "mismatches": 0,
            "result_sha256": (
                "da2a44d03024f8374d438341003de5f970cdd9cb52060d6206bd8aeca5b109c7"
            ),
            "stream_modes": ["default", "nondefault"],
            "target_unique_corpus_point_slots": 50_000,
            "unique_corpus_point_slots": 128_758,
            "verified_point_slots_across_modes": 257_516,
        },
        "root_status": "UNKNOWN",
        "sanitizer": (
            "NVIDIA (R) Compute Sanitizer Copyright (c) 2020-2025 NVIDIA "
            "Corporation Version 2025.1.0.0 (build 35351055) (public-release)"
        ),
        "seed": 88_442_398_638_062,
    }
    if scale_sanitizer != expected_scale_sanitizer or not is_sha256(
        sanitizer_transcript_sha256
    ):
        raise SystemExit("CUDA scale sanitizer evidence is invalid")
    validate_source_pins(
        "CUDA local-transition scale sanitizer evidence",
        scale_sanitizer_pins,
        (
            "cpp/cuda/packed_kernels.cu",
            "cpp/cuda/packed_kernels.cuh",
            "cpp/cuda/cuda_verified_expander.cu",
            "cpp/include/ugts_go19/cuda_verified_expander.hpp",
            "cpp/tests/cuda_local_transition_scale.cu",
            "cpp/tests/cuda_local_transition_scale.py",
            "cpp/tests/cuda_local_transition_scale_sanitizer.py",
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
