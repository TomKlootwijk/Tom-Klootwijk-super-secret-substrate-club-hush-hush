#!/usr/bin/env python3
"""Run and atomically record the bounded C++/CUDA 10m local-slot gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET_UNIQUE_CORPUS_SLOTS = 10_000_000
DEFAULT_BATCH_STATES = 16
DEFAULT_SEED = 0x507019C0FFEE


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_uint(value: object, label: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AssertionError(f"{label} must be an unsigned integer")
    if positive and value == 0:
        raise AssertionError(f"{label} must be positive")
    return value


def require_float(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise AssertionError(f"{label} must be a positive number")
    return float(value)


def validate_mode(mode: object, label: str) -> dict[str, Any]:
    if not isinstance(mode, dict):
        raise AssertionError(f"{label} mode is not an object")
    integer_fields = (
        "adapter_batch_calls",
        "compared_child_words",
        "globally_legal_children",
        "high_water_requested_device_bytes",
        "local_candidates",
        "maximum_capture",
        "minimum_adapter_workspace_budget_bytes",
        "minimum_free_device_bytes_before_batch",
        "occupied_slots",
        "point_slots",
        "semantic_state_visits",
        "suicide_slots",
        "superko_rejections",
    )
    for field in integer_fields:
        require_uint(mode.get(field), f"{label}.{field}", positive=True)
    require_float(mode.get("elapsed_seconds"), f"{label}.elapsed_seconds")
    require_float(mode.get("slots_per_second"), f"{label}.slots_per_second")
    result_sha256 = mode.get("result_sha256")
    if (
        not isinstance(result_sha256, str)
        or len(result_sha256) != 64
        or any(character not in "0123456789abcdef" for character in result_sha256)
    ):
        raise AssertionError(f"{label}.result_sha256 is invalid")
    if (
        mode["point_slots"]
        != mode["occupied_slots"] + mode["suicide_slots"] + mode["local_candidates"]
    ):
        raise AssertionError(f"{label} status counts do not partition point slots")
    if (
        mode["local_candidates"]
        != mode["superko_rejections"] + mode["globally_legal_children"]
    ):
        raise AssertionError(f"{label} candidate counts do not partition")
    if (
        mode["high_water_requested_device_bytes"]
        > mode["minimum_adapter_workspace_budget_bytes"]
    ):
        raise AssertionError(f"{label} exceeded the adapter VRAM budget")
    if mode["maximum_capture"] != 360:
        raise AssertionError(f"{label} did not exercise the 360-stone capture")
    for map_field in ("slots_by_board_size", "slots_by_category"):
        values = mode.get(map_field)
        if not isinstance(values, dict) or not values:
            raise AssertionError(f"{label}.{map_field} is invalid")
        if any(
            not isinstance(key, str)
            or require_uint(value, f"{label}.{map_field}.{key}") < 0
            for key, value in values.items()
        ):
            raise AssertionError(f"{label}.{map_field} is invalid")
        if sum(values.values()) != mode["point_slots"]:
            raise AssertionError(f"{label}.{map_field} does not total point slots")
    if set(mode["slots_by_board_size"]) != {"1", "2", "3", "5", "9", "19"}:
        raise AssertionError(f"{label} did not cover the exact board-size set")
    required_categories = {
        "campaign-shaped-19x19",
        "capture-fixture-19x19",
        "ko-psk-fixture",
        "randomized-ordinal-dense-19x19",
        "suicide-fixture-19x19",
        "word-tail-fixture-19x19",
    }
    if not required_categories.issubset(mode["slots_by_category"]):
        raise AssertionError(f"{label} is missing required corpus categories")
    return mode


def validate_result(
    result: object, *, target_unique_corpus_slots: int, batch_states: int, seed: int
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise AssertionError("scale runner output is not an object")
    if result.get("format") != "ugts-go19-cuda-local-transition-scale-v1":
        raise AssertionError("unexpected scale result format")
    exact_scalars = {
        "batch_state_limit": batch_states,
        "mismatches": 0,
        "negative_fail_closed_checks": 7,
        "python_compared_point_slots": 0,
        "root_status": "UNKNOWN",
        "seed": seed,
        "stream_modes": ["default", "nondefault"],
        "target_unique_corpus_point_slots": target_unique_corpus_slots,
    }
    for field, expected in exact_scalars.items():
        if result.get(field) != expected:
            raise AssertionError(f"unexpected {field}: {result.get(field)!r}")
    if result.get("scope") != (
        "C++/CUDA pre-superko local point transitions; CPU ApplyMove authority; "
        "no proof-search integration"
    ):
        raise AssertionError("scale scope is not exact")
    if result.get("measurement_label") != (
        "hardware-specific non-proof end-to-end adapter verification and "
        "summary consumption"
    ):
        raise AssertionError("measurement label is not exact")
    corpus_entries = require_uint(
        result.get("corpus_entries"), "corpus_entries", positive=True
    )
    if (
        require_uint(result.get("unique_semantic_states"), "unique_semantic_states")
        != corpus_entries
    ):
        raise AssertionError("unique semantic-state accounting is inconsistent")
    unique_corpus_slots = require_uint(
        result.get("unique_corpus_point_slots"),
        "unique_corpus_point_slots",
        positive=True,
    )
    if unique_corpus_slots < target_unique_corpus_slots:
        raise AssertionError("unique corpus did not reach its breadth target")
    corpus_sha256 = result.get("corpus_sha256")
    if (
        not isinstance(corpus_sha256, str)
        or len(corpus_sha256) != 64
        or any(character not in "0123456789abcdef" for character in corpus_sha256)
    ):
        raise AssertionError("invalid corpus SHA-256")
    device = result.get("device")
    if (
        not isinstance(device, dict)
        or not isinstance(device.get("name"), str)
        or not device["name"]
        or not isinstance(device.get("compute_capability"), str)
        or require_uint(
            device.get("total_global_memory_bytes"),
            "device.total_global_memory_bytes",
            positive=True,
        )
        <= 0
    ):
        raise AssertionError("invalid CUDA device metadata")
    require_uint(
        result.get("cuda_driver_version"), "cuda_driver_version", positive=True
    )
    require_uint(
        result.get("cuda_runtime_version"), "cuda_runtime_version", positive=True
    )
    compiler = result.get("compiler")
    if (
        not isinstance(compiler, dict)
        or not isinstance(compiler.get("cuda"), str)
        or not compiler["cuda"].startswith("NVCC-")
        or not isinstance(compiler.get("host"), str)
        or compiler["host"] == "unknown"
    ):
        raise AssertionError("invalid compiler metadata")
    if result.get("build_configuration") not in {"Debug", "Release"}:
        raise AssertionError("invalid build configuration")

    modes = result.get("modes")
    if not isinstance(modes, dict) or sorted(modes) != ["default", "nondefault"]:
        raise AssertionError("invalid stream-mode object")
    default = validate_mode(modes["default"], "default")
    nondefault = validate_mode(modes["nondefault"], "nondefault")
    nondeterministic_fields = {
        "elapsed_seconds",
        "slots_per_second",
        "minimum_free_device_bytes_before_batch",
        "minimum_adapter_workspace_budget_bytes",
    }
    for field in default:
        if field not in nondeterministic_fields and default[field] != nondefault[field]:
            raise AssertionError(f"stream modes differ in exact field {field}")
    primary = require_uint(
        result.get("primary_unique_mode_cpp_cuda_cpu_recomputed_point_slots"),
        "primary_unique_mode_cpp_cuda_cpu_recomputed_point_slots",
        positive=True,
    )
    additional = require_uint(
        result.get("additional_stream_mode_recomputed_point_slots"),
        "additional_stream_mode_recomputed_point_slots",
        positive=True,
    )
    total = require_uint(
        result.get("total_cpp_cuda_cpu_recomputed_point_slots_across_modes"),
        "total_cpp_cuda_cpu_recomputed_point_slots_across_modes",
        positive=True,
    )
    if primary != unique_corpus_slots or primary != default["point_slots"]:
        raise AssertionError("primary mode did not traverse every unique corpus slot")
    if additional != nondefault["point_slots"] or additional != unique_corpus_slots:
        raise AssertionError("additional stream mode did not traverse the corpus")
    if total != primary + additional:
        raise AssertionError("total point slots do not equal both stream modes")
    if target_unique_corpus_slots >= DEFAULT_TARGET_UNIQUE_CORPUS_SLOTS:
        campaign_slots = default["slots_by_category"]["campaign-shaped-19x19"]
        randomized_slots = default["slots_by_category"][
            "randomized-ordinal-dense-19x19"
        ]
        if campaign_slots < 500_000:
            raise AssertionError("10m gate has insufficient campaign-shaped coverage")
        if randomized_slots < 9_000_000:
            raise AssertionError("10m gate has insufficient randomized 19x19 coverage")
    return result


def run_runner(
    runner: Path, *, target_unique_corpus_slots: int, batch_states: int, seed: int
) -> dict[str, Any]:
    command = [
        str(runner),
        "--target-unique-corpus-slots",
        str(target_unique_corpus_slots),
        "--batch-states",
        str(batch_states),
        "--seed",
        str(seed),
    ]
    process = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=7_200,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"scale runner failed with {process.returncode}: {process.stderr.strip()}"
        )
    try:
        decoded = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError("scale runner emitted invalid JSON") from error
    return validate_result(
        decoded,
        target_unique_corpus_slots=target_unique_corpus_slots,
        batch_states=batch_states,
        seed=seed,
    )


def add_provenance(result: dict[str, Any]) -> dict[str, Any]:
    production_sources = (
        "cpp/cuda/packed_kernels.cu",
        "cpp/cuda/packed_kernels.cuh",
        "cpp/cuda/cuda_verified_expander.cu",
        "cpp/include/ugts_go19/cuda_verified_expander.hpp",
    )
    gate_sources = (
        "cpp/CMakeLists.txt",
        "cpp/tests/cuda_local_transition_scale.cu",
        "cpp/tests/cuda_local_transition_scale.py",
    )
    reference_sources = (
        "cpp/include/ugts_go19/go_state.hpp",
        "cpp/include/ugts_go19/sha256.hpp",
        "cpp/src/go_state.cpp",
        "cpp/src/sha256.cpp",
    )
    companion = ROOT / "evidence" / "local_m4_cuda_local_transition_parity.json"
    if not companion.is_file():
        raise FileNotFoundError(
            "the retained Python/C++/CUDA companion evidence is missing"
        )
    result["production_source_sha256"] = {
        relative: file_sha256(ROOT / relative) for relative in production_sources
    }
    result["gate_source_sha256"] = {
        relative: file_sha256(ROOT / relative) for relative in gate_sources
    }
    result["reference_source_sha256"] = {
        relative: file_sha256(ROOT / relative) for relative in reference_sources
    }
    result["cross_language_companion"] = {
        "evidence": "evidence/local_m4_cuda_local_transition_parity.json",
        "sha256": file_sha256(companion),
        "scope": "retained 25k Python/C++/CUDA exact comparison; not included in the 10m count",
    }
    result["evidence_publication"] = (
        "same-directory temporary file, fsync, atomic replace"
    )
    return result


def atomic_write(path: Path, encoded: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(encoded)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument(
        "--target-unique-corpus-slots",
        type=int,
        default=DEFAULT_TARGET_UNIQUE_CORPUS_SLOTS,
    )
    parser.add_argument("--batch-states", type=int, default=DEFAULT_BATCH_STATES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.runner.is_file():
        raise FileNotFoundError(f"scale runner not found: {args.runner}")
    if args.target_unique_corpus_slots <= 0:
        raise ValueError("target-unique-corpus-slots must be positive")
    if args.batch_states <= 0:
        raise ValueError("batch-states must be positive")
    if args.seed < 0:
        raise ValueError("seed must be nonnegative")
    result = add_provenance(
        run_runner(
            args.runner.resolve(),
            target_unique_corpus_slots=args.target_unique_corpus_slots,
            batch_states=args.batch_states,
            seed=args.seed,
        )
    )
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if args.output is not None:
        atomic_write(args.output.resolve(), encoded)
    print(encoded)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - standalone gate fails closed.
        print(f"cuda_local_transition_scale: {error}", file=os.sys.stderr)
        raise SystemExit(1) from error
