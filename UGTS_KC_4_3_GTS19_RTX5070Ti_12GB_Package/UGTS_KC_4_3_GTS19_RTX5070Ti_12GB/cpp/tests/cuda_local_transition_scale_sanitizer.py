#!/usr/bin/env python3
"""Record a bounded Compute Sanitizer run of the scale-gate boundary."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import cuda_local_transition_scale as scale

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SANITIZER_TARGET_SLOTS = 50_000
ERROR_SUMMARY = re.compile(r"ERROR SUMMARY:\s+(\d+)\s+errors?", re.IGNORECASE)


def sanitizer_version(executable: Path) -> str:
    process = subprocess.run(
        [str(executable), "--version"],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"compute-sanitizer --version failed: {process.stderr.strip()}"
        )
    version = " ".join((process.stdout + " " + process.stderr).split())
    if "Compute Sanitizer" not in version:
        raise AssertionError("unexpected Compute Sanitizer version output")
    return version


def run_memcheck(
    sanitizer: Path,
    runner: Path,
    *,
    target_unique_corpus_slots: int,
    batch_states: int,
    seed: int,
) -> tuple[dict[str, object], str, str]:
    command = [
        str(sanitizer),
        "--tool",
        "memcheck",
        "--error-exitcode",
        "99",
        str(runner),
        "--target-unique-corpus-slots",
        str(target_unique_corpus_slots),
        "--batch-states",
        str(batch_states),
        "--seed",
        str(seed),
    ]
    runner_sha256_before = scale.file_sha256(runner)
    process = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=3_600,
        check=False,
    )
    runner_sha256_after = scale.file_sha256(runner)
    if runner_sha256_after != runner_sha256_before:
        raise RuntimeError("memcheck scale runner executable changed during execution")
    if process.returncode != 0:
        raise RuntimeError(
            f"scale memcheck failed with {process.returncode}: {process.stderr.strip()}"
        )
    combined = process.stdout + "\n" + process.stderr
    summaries = ERROR_SUMMARY.findall(combined)
    if summaries != ["0"]:
        raise AssertionError(f"unexpected memcheck summaries: {summaries!r}")
    json_lines = [
        line.strip()
        for line in combined.splitlines()
        if line.strip().startswith("{") and line.strip().endswith("}")
    ]
    if len(json_lines) != 1:
        raise AssertionError("sanitized runner did not emit one JSON record")
    try:
        decoded = json.loads(json_lines[0])
    except json.JSONDecodeError as error:
        raise AssertionError("sanitized runner emitted invalid JSON") from error
    validated = scale.validate_result(
        decoded,
        target_unique_corpus_slots=target_unique_corpus_slots,
        batch_states=batch_states,
        seed=seed,
    )
    transcript_without_result = " ".join(
        line for line in combined.splitlines() if line.strip() != json_lines[0]
    )
    return validated, transcript_without_result, runner_sha256_before


def build_evidence(
    sanitizer: Path,
    runner: Path,
    *,
    target_unique_corpus_slots: int,
    batch_states: int,
    seed: int,
) -> dict[str, object]:
    result, transcript, runner_executable_sha256 = run_memcheck(
        sanitizer,
        runner,
        target_unique_corpus_slots=target_unique_corpus_slots,
        batch_states=batch_states,
        seed=seed,
    )
    sources = (
        "cpp/cuda/packed_kernels.cu",
        "cpp/cuda/packed_kernels.cuh",
        "cpp/cuda/cuda_verified_expander.cu",
        "cpp/include/ugts_go19/cuda_verified_expander.hpp",
        "cpp/tests/cuda_local_transition_scale.cu",
        "cpp/tests/cuda_local_transition_scale.py",
        "cpp/tests/cuda_local_transition_scale_sanitizer.py",
    )
    modes = result["modes"]
    assert isinstance(modes, dict)
    default = modes["default"]
    nondefault = modes["nondefault"]
    assert isinstance(default, dict) and isinstance(nondefault, dict)
    return {
        "batch_state_limit": batch_states,
        "compute_capability": result["device"]["compute_capability"],
        "corpus_sha256": result["corpus_sha256"],
        "device_name": result["device"]["name"],
        "error_exitcode": 99,
        "format": "ugts-go19-cuda-local-transition-scale-sanitizer-v1",
        "limitations": [
            "bounded representative memcheck, not a sanitizer run over all 10m slots",
            "the 10m count is C++/CUDA with CPU ApplyMove authority, not Python comparison",
            "the local transition slice is not integrated into proof search",
            "zero sanitizer errors do not establish the unrestricted 19x19 result",
        ],
        "memcheck": {
            "adapter_batch_calls_across_modes": default["adapter_batch_calls"]
            + nondefault["adapter_batch_calls"],
            "error_summary": 0,
            "exit_code": 0,
            "mismatches": result["mismatches"],
            "result_sha256": default["result_sha256"],
            "stream_modes": result["stream_modes"],
            "target_unique_corpus_point_slots": target_unique_corpus_slots,
            "unique_corpus_point_slots": result["unique_corpus_point_slots"],
            "verified_point_slots_across_modes": result[
                "total_cpp_cuda_cpu_recomputed_point_slots_across_modes"
            ],
        },
        "memcheck_scale_runner_executable_sha256": runner_executable_sha256,
        "root_status": "UNKNOWN",
        "sanitizer": sanitizer_version(sanitizer),
        "sanitizer_transcript_sha256": __import__("hashlib")
        .sha256(transcript.encode("utf-8"))
        .hexdigest(),
        "seed": seed,
        "source_sha256": {
            relative: scale.file_sha256(ROOT / relative) for relative in sources
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compute-sanitizer", required=True, type=Path)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument(
        "--target-unique-corpus-slots",
        type=int,
        default=DEFAULT_SANITIZER_TARGET_SLOTS,
    )
    parser.add_argument("--batch-states", type=int, default=8)
    parser.add_argument("--seed", type=int, default=scale.DEFAULT_SEED)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.compute_sanitizer.is_file():
        raise FileNotFoundError(
            f"compute-sanitizer not found: {args.compute_sanitizer}"
        )
    if not args.runner.is_file():
        raise FileNotFoundError(f"scale runner not found: {args.runner}")
    result = build_evidence(
        args.compute_sanitizer.resolve(),
        args.runner.resolve(),
        target_unique_corpus_slots=args.target_unique_corpus_slots,
        batch_states=args.batch_states,
        seed=args.seed,
    )
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if args.output is not None:
        scale.atomic_write(args.output.resolve(), encoded)
    print(encoded)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - standalone gate fails closed.
        print(
            f"cuda_local_transition_scale_sanitizer: {error}",
            file=__import__("sys").stderr,
        )
        raise SystemExit(1) from error
