#!/usr/bin/env python3
"""Reproduce the RTX packed-move throughput and CPU/CUDA parity evidence.

The native executable's timer measures move expansion only.  This runner also
records process-wall timings, the exact input and binary hashes, the corpus
recipe, device metadata, warmups, and every measured sample.  It refuses to
overwrite retained evidence unless ``--force`` is explicit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Callable, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts_chess.gpu_protocol import (  # noqa: E402
    INPUT_HEADER,
    MAX_MOVES,
    OUTPUT_HEADER,
    OUTPUT_MAGIC,
    encode_position_batch,
    executable_identity,
)
from ugts_chess.gpu_qualification import (  # noqa: E402
    DEFAULT_SEED,
    build_qualification_corpus,
    corpus_sha256,
)


DEFAULT_EXECUTABLE = ROOT / "cpp" / "build" / "rtx5070ti-release" / "ugts-chess-gpu.exe"
DEFAULT_OUTPUT_DIR = ROOT / "validation" / "device" / "throughput"
TARGET_DEVICE_LABEL = "NVIDIA GeForce RTX 5070 Ti (desktop or laptop)"
TARGET_COMPUTE_CAPABILITY = "12.0"
TARGET_DEVICE_NAME_PATTERN = re.compile(
    r"^NVIDIA\s+GeForce\s+RTX\s+5070\s+Ti(?:\s+Laptop)?(?:\s+GPU)?$",
    re.IGNORECASE,
)


class BenchmarkError(RuntimeError):
    """Raised when evidence cannot be produced without weakening a gate."""


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_identity(path: Path) -> dict[str, object]:
    """Hash one stable filesystem object and bind its resolved path and size."""

    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat()
        sha256 = _sha256_path(resolved)
        after = resolved.stat()
    except OSError as exc:
        raise BenchmarkError(f"cannot identify benchmark input {path}: {exc}") from exc
    before_marker = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_marker = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_marker != after_marker:
        raise BenchmarkError(f"benchmark input changed while it was being hashed: {resolved}")
    return {
        "path": str(resolved),
        "sha256": sha256,
        "size_bytes": after.st_size,
    }


def require_stable_input_identity(
    expected_identity: dict[str, object],
    input_path: Path,
) -> dict[str, object]:
    """Fail unless the unique input's exact path, bytes, and size are unchanged."""

    current_identity = _file_identity(input_path)
    if current_identity != expected_identity:
        raise BenchmarkError("benchmark input identity changed while evidence was being collected")
    return current_identity


def _create_unique_input_artifact(
    output_dir: Path,
    positions: Sequence[object],
) -> tuple[Path, dict[str, object]]:
    """Write a never-reused input file whose unpredictable name belongs to this run."""

    raw = encode_position_batch(positions)
    _magic, _version, record_size, count, _flags = INPUT_HEADER.unpack_from(raw)
    invocation_id = uuid.uuid4().hex
    input_path = output_dir / f"positions-{count}-{invocation_id}.ugcb"
    try:
        with input_path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise BenchmarkError(f"unique benchmark input unexpectedly already exists: {input_path}") from exc
    identity = _file_identity(input_path)
    expected_sha256 = hashlib.sha256(raw).hexdigest()
    if identity["sha256"] != expected_sha256 or identity["size_bytes"] != len(raw):
        input_path.unlink(missing_ok=True)
        raise BenchmarkError("new benchmark input does not match the bytes generated in memory")
    return input_path, {
        **identity,
        "count": count,
        "record_size": record_size,
        "invocation_id": invocation_id,
        "unique_per_invocation": True,
        "reused_existing_exact_file": False,
        "storage_semantics": "unique per invocation; never reused or overwritten",
    }


def _publish_report_atomically(
    report_path: Path,
    report: dict[str, object],
    *,
    force: bool,
    pre_publish_check: Callable[[], object] | None = None,
) -> None:
    """Publish complete JSON via a unique temporary file.

    Without ``force``, a hard-link publication provides atomic no-overwrite
    semantics even when two benchmark processes pass the early existence check.
    """

    temporary_handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{report_path.stem}-",
        suffix=".json.tmp",
        dir=report_path.parent,
        delete=False,
    )
    temporary_report = Path(temporary_handle.name)
    try:
        with temporary_handle:
            json.dump(report, temporary_handle, indent=2, sort_keys=True)
            temporary_handle.write("\n")
            temporary_handle.flush()
            os.fsync(temporary_handle.fileno())
        if pre_publish_check is not None:
            pre_publish_check()
        if force:
            os.replace(temporary_report, report_path)
        else:
            try:
                os.link(temporary_report, report_path)
            except FileExistsError as exc:
                raise BenchmarkError(
                    f"refusing to overwrite retained report published by another run: {report_path}; "
                    "pass --force explicitly"
                ) from exc
            except OSError as exc:
                raise BenchmarkError(
                    f"filesystem cannot atomically publish the benchmark report without overwrite: {exc}"
                ) from exc
            temporary_report.unlink()
    finally:
        temporary_report.unlink(missing_ok=True)


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise BenchmarkError("at least one timing sample is required")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: Sequence[float]) -> dict[str, object]:
    return {
        "sample_count": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "min": min(values),
        "max": max(values),
        "raw": list(values),
    }


def _run_checked(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BenchmarkError(f"command failed ({completed.returncode}): {' '.join(command)}\n{detail}")
    return completed


def _parse_native_result(
    stdout: str,
    *,
    expected_backend: str,
    expected_positions: int,
    expected_moves: int | None = None,
) -> dict[str, object]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"native output is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError("native output is not a JSON object")

    backend = payload.get("backend")
    positions = payload.get("positions")
    moves = payload.get("moves")
    seconds = payload.get("seconds")
    fallback = payload.get("cuda_fallback_reason")
    if backend != expected_backend:
        raise BenchmarkError(f"expected {expected_backend!r} backend, got {backend!r}")
    if positions != expected_positions:
        raise BenchmarkError(f"native position count {positions!r} != {expected_positions}")
    if isinstance(moves, bool) or not isinstance(moves, int) or moves < 0:
        raise BenchmarkError("native move count is not a non-negative integer")
    if expected_moves is not None and moves != expected_moves:
        raise BenchmarkError(f"native move count {moves} != parity count {expected_moves}")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise BenchmarkError("native timer is not numeric")
    seconds = float(seconds)
    if seconds <= 0.0 or not math.isfinite(seconds):
        raise BenchmarkError("native timer is not a positive finite duration")
    if not isinstance(fallback, str):
        raise BenchmarkError("native fallback reason is missing or non-text")
    if expected_backend == "cuda" and fallback.strip():
        raise BenchmarkError(f"CUDA reported a fallback reason: {fallback}")
    return {
        "backend": backend,
        "positions": positions,
        "moves": moves,
        "seconds": seconds,
        "cuda_fallback_reason": fallback,
    }


def _run_expansion(
    executable: Path,
    input_path: Path,
    output_path: Path | str,
    *,
    backend: str,
    device: int,
    expected_positions: int,
    expected_moves: int | None = None,
    expected_input_identity: dict[str, object] | None = None,
) -> dict[str, object]:
    if expected_input_identity is not None:
        require_stable_input_identity(expected_input_identity, input_path)
    command = [
        str(executable),
        "expand-batch",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--device",
        str(device),
    ]
    if backend == "cpu":
        command.append("--cpu")
    started = perf_counter()
    try:
        completed = _run_checked(command)
    finally:
        if expected_input_identity is not None:
            require_stable_input_identity(expected_input_identity, input_path)
    wall_seconds = perf_counter() - started
    parsed = _parse_native_result(
        completed.stdout.strip(),
        expected_backend=backend,
        expected_positions=expected_positions,
        expected_moves=expected_moves,
    )
    parsed["process_wall_seconds"] = wall_seconds
    return parsed


def _read_output(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) < OUTPUT_HEADER.size:
        raise BenchmarkError(f"truncated output: {path}")
    magic, version, move_size, max_moves, count, flags = OUTPUT_HEADER.unpack_from(raw)
    if magic != OUTPUT_MAGIC or version != 1 or move_size != 2 or max_moves != MAX_MOVES:
        raise BenchmarkError(f"unsupported output header: {path}")
    expected_size = OUTPUT_HEADER.size + count * 2 + count * MAX_MOVES * 2
    if len(raw) != expected_size:
        raise BenchmarkError(f"output size {len(raw)} != {expected_size}: {path}")
    counts_offset = OUTPUT_HEADER.size
    counts = struct.unpack_from(f"<{count}H", raw, counts_offset) if count else ()
    if any(value > MAX_MOVES for value in counts):
        raise BenchmarkError(f"output move count exceeds {MAX_MOVES}: {path}")
    semantic = raw[OUTPUT_HEADER.size :]
    return {
        "positions": count,
        "moves": sum(counts),
        "backend_flag": flags,
        "bytes": len(raw),
        "full_sha256": hashlib.sha256(raw).hexdigest(),
        "semantic_payload_sha256": hashlib.sha256(semantic).hexdigest(),
        "semantic_payload": semantic,
    }


def _capture_json(command: Sequence[str]) -> dict[str, object] | None:
    try:
        completed = _run_checked(command)
        payload = json.loads(completed.stdout)
        return payload if isinstance(payload, dict) else None
    except (BenchmarkError, json.JSONDecodeError):
        return None


def _capture_text(command: Sequence[str]) -> str | None:
    try:
        return _run_checked(command).stdout.strip()
    except BenchmarkError:
        return None


def _validate_range(name: str, value: int, lower: int, upper: int) -> None:
    if not lower <= value <= upper:
        raise BenchmarkError(f"{name} must be in [{lower}, {upper}], got {value}")


def validate_rtx5070ti_device_info(payload: object, *, expected_device_index: int) -> dict[str, object]:
    """Validate the native device claim required by this target-specific benchmark.

    The native executable controls this payload.  These checks prevent an
    accidental benchmark on a differently named/capable CUDA device, but they
    are not independent hardware attestation against a malicious executable.
    """

    is_object = isinstance(payload, dict)
    device_info = payload if is_object else {}
    name = device_info.get("name")
    compute_capability = device_info.get("compute_capability")
    reported_index = device_info.get("device_index")
    total_memory = device_info.get("total_memory_bytes")
    multiprocessors = device_info.get("multiprocessors")
    error = device_info.get("error")
    checks = {
        "payload_is_object": is_object,
        "cuda_compiled": device_info.get("cuda_compiled") is True,
        "device_available": device_info.get("device_available") is True,
        "device_index_matches": (
            not isinstance(reported_index, bool)
            and isinstance(reported_index, int)
            and reported_index == expected_device_index
        ),
        "device_name_matches_rtx5070ti": (
            isinstance(name, str) and TARGET_DEVICE_NAME_PATTERN.fullmatch(" ".join(name.split())) is not None
        ),
        "compute_capability_matches": compute_capability == TARGET_COMPUTE_CAPABILITY,
        "total_memory_is_positive": (
            not isinstance(total_memory, bool) and isinstance(total_memory, int) and total_memory > 0
        ),
        "multiprocessor_count_is_positive": (
            not isinstance(multiprocessors, bool) and isinstance(multiprocessors, int) and multiprocessors > 0
        ),
        "device_info_error_empty": isinstance(error, str) and not error,
    }
    failure_names = {
        "payload_is_object": "device_info_not_object",
        "cuda_compiled": "cuda_not_compiled",
        "device_available": "cuda_device_unavailable",
        "device_index_matches": "device_index_mismatch",
        "device_name_matches_rtx5070ti": "device_name_not_rtx5070ti",
        "compute_capability_matches": "compute_capability_not_12_0",
        "total_memory_is_positive": "total_memory_invalid",
        "multiprocessor_count_is_positive": "multiprocessor_count_invalid",
        "device_info_error_empty": "device_info_error_present",
    }
    failures = [failure_names[key] for key, passed in checks.items() if not passed]
    return {
        "valid": not failures,
        "failures": failures,
        "checks": checks,
        "target_device": TARGET_DEVICE_LABEL,
        "target_name_pattern": TARGET_DEVICE_NAME_PATTERN.pattern,
        "expected_compute_capability": TARGET_COMPUTE_CAPABILITY,
        "expected_device_index": expected_device_index,
        "reported_name": name,
        "reported_compute_capability": compute_capability,
        "reported_device_index": reported_index,
        "claim_source": "benchmarked_executable_device_info_self_report",
        "independent_hardware_attestation": False,
    }


def require_stable_executable_identity(
    initial_identity: dict[str, object],
    final_identity: dict[str, object],
) -> None:
    """Fail unless the exact executable path, bytes, and size stayed unchanged."""

    if final_identity != initial_identity:
        raise BenchmarkError("benchmark executable identity changed while evidence was being collected")


def benchmark(args: argparse.Namespace) -> dict[str, object]:
    executable = args.executable.resolve()
    output_dir = args.output_dir.resolve()
    if not executable.is_file():
        raise BenchmarkError(f"executable not found: {executable}")
    initial_executable_identity = executable_identity(executable)
    executable = Path(str(initial_executable_identity["path"]))
    _validate_range("positions", args.positions, 1, 1_000_000)
    _validate_range("random-count", args.random_count, 0, 100_000)
    _validate_range("max-plies", args.max_plies, 1, 1_000)
    _validate_range("cuda-runs", args.cuda_runs, 1, 100)
    _validate_range("cpu-runs", args.cpu_runs, 1, 100)
    _validate_range("warmups", args.warmups, 0, 20)
    _validate_range("device", args.device, 0, 64)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"benchmark-{args.positions}.json"
    if report_path.exists() and not args.force:
        raise BenchmarkError(f"refusing to overwrite retained report: {report_path}; pass --force explicitly")

    base_corpus = build_qualification_corpus(
        seed=args.seed,
        random_positions=args.random_count,
        max_plies=args.max_plies,
    )
    positions = [base_corpus[index % len(base_corpus)].position for index in range(args.positions)]
    input_path, input_meta = _create_unique_input_artifact(output_dir, positions)
    initial_input_identity = {
        key: input_meta[key]
        for key in ("path", "sha256", "size_bytes")
    }
    require_stable_input_identity(initial_input_identity, input_path)

    device_info = _capture_json([str(executable), "device-info", "--device", str(args.device)])
    target_device_validation = validate_rtx5070ti_device_info(
        device_info,
        expected_device_index=args.device,
    )
    if not target_device_validation["valid"]:
        failures = ", ".join(str(item) for item in target_device_validation["failures"])
        raise BenchmarkError(f"device-info does not match the RTX 5070 Ti benchmark target: {failures}")

    smi = shutil.which("nvidia-smi")
    smi_command = [
        smi,
        "--query-gpu=timestamp,name,driver_version,pstate,temperature.gpu,power.draw,power.limit,memory.total,memory.used",
        "--format=csv,noheader,nounits",
        "--id",
        str(args.device),
    ] if smi else []
    pre_smi = _capture_text(smi_command) if smi_command else None
    powercfg = shutil.which("powercfg") or shutil.which("powercfg.exe")
    power_scheme = _capture_text([powercfg, "/getactivescheme"]) if powercfg else None

    with tempfile.TemporaryDirectory(prefix="ugts-benchmark-", dir=output_dir) as temp_name:
        temp_dir = Path(temp_name)
        cuda_output = temp_dir / "moves-cuda.ugmv"
        cpu_output = temp_dir / "moves-cpu.ugmv"
        cuda_parity_run = _run_expansion(
            executable,
            input_path,
            cuda_output,
            backend="cuda",
            device=args.device,
            expected_positions=args.positions,
            expected_input_identity=initial_input_identity,
        )
        cpu_parity_run = _run_expansion(
            executable,
            input_path,
            cpu_output,
            backend="cpu",
            device=args.device,
            expected_positions=args.positions,
            expected_moves=int(cuda_parity_run["moves"]),
            expected_input_identity=initial_input_identity,
        )
        cuda_file = _read_output(cuda_output)
        cpu_file = _read_output(cpu_output)
        if cuda_file["positions"] != args.positions or cpu_file["positions"] != args.positions:
            raise BenchmarkError("parity output position count does not match the input")
        if cuda_file["moves"] != cuda_parity_run["moves"] or cpu_file["moves"] != cpu_parity_run["moves"]:
            raise BenchmarkError("parity output counts do not match native stdout")
        if cuda_file["backend_flag"] != 1 or cpu_file["backend_flag"] != 0:
            raise BenchmarkError("parity output backend flags do not identify CUDA and CPU")
        if cuda_file.pop("semantic_payload") != cpu_file.pop("semantic_payload"):
            raise BenchmarkError("CPU and CUDA semantic output payloads differ")

        sink = os.devnull
        warmup_records: list[dict[str, object]] = []
        for backend in ("cuda", "cpu"):
            for _ in range(args.warmups):
                warmup_records.append(
                    _run_expansion(
                        executable,
                        input_path,
                        sink,
                        backend=backend,
                        device=args.device,
                        expected_positions=args.positions,
                        expected_moves=int(cuda_parity_run["moves"]),
                        expected_input_identity=initial_input_identity,
                    )
                )

        cuda_runs = [
            _run_expansion(
                executable,
                input_path,
                sink,
                backend="cuda",
                device=args.device,
                expected_positions=args.positions,
                expected_moves=int(cuda_parity_run["moves"]),
                expected_input_identity=initial_input_identity,
            )
            for _ in range(args.cuda_runs)
        ]
        cpu_runs = [
            _run_expansion(
                executable,
                input_path,
                sink,
                backend="cpu",
                device=args.device,
                expected_positions=args.positions,
                expected_moves=int(cuda_parity_run["moves"]),
                expected_input_identity=initial_input_identity,
            )
            for _ in range(args.cpu_runs)
        ]

    post_smi = _capture_text(smi_command) if smi_command else None
    final_executable_identity = executable_identity(executable)
    require_stable_executable_identity(initial_executable_identity, final_executable_identity)
    final_input_identity = require_stable_input_identity(initial_input_identity, input_path)
    input_meta["final_identity"] = final_input_identity
    input_meta["identity_stable_through_benchmark"] = True
    cuda_native = [float(run["seconds"]) for run in cuda_runs]
    cpu_native = [float(run["seconds"]) for run in cpu_runs]
    cuda_wall = [float(run["process_wall_seconds"]) for run in cuda_runs]
    cpu_wall = [float(run["process_wall_seconds"]) for run in cpu_runs]
    cuda_p50 = _percentile(cuda_native, 0.50)
    cpu_p50 = _percentile(cpu_native, 0.50)
    moves = int(cuda_parity_run["moves"])
    report: dict[str, object] = {
        "schema": "ugts-chess-rtx-batch-benchmark-v4",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reproduction": {
            "script": str(Path(__file__).resolve()),
            "script_sha256": _sha256_path(Path(__file__).resolve()),
            "arguments": {
                "positions": args.positions,
                "seed": args.seed,
                "random_count": args.random_count,
                "max_plies": args.max_plies,
                "cuda_runs": args.cuda_runs,
                "cpu_runs": args.cpu_runs,
                "warmups_per_backend": args.warmups,
                "device": args.device,
            },
        },
        "executable": {
            **initial_executable_identity,
            "final_identity": final_executable_identity,
            "identity_stable_through_benchmark": True,
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "power_scheme": power_scheme,
        },
        "device": {
            "device_info": device_info,
            "target_validation": target_device_validation,
            "identity_claim_source": "benchmarked_executable_device_info_self_report",
            "independent_hardware_attestation": False,
            "nvidia_smi_before": pre_smi,
            "nvidia_smi_after": post_smi,
        },
        "corpus": {
            "generator": "splitmix64-v1/sorted-legal-uci-index",
            "seed": args.seed,
            "fixture_count": sum(1 for item in base_corpus if item.source != "seeded_random_reachable"),
            "random_position_count": args.random_count,
            "max_random_plies": args.max_plies,
            "base_position_count": len(base_corpus),
            "base_corpus_sha256": corpus_sha256(base_corpus),
            "expansion": "repeat ordered base corpus cyclically, truncate to positions",
        },
        "input": input_meta,
        "parity": {
            "positions": args.positions,
            "moves": moves,
            "semantic_payload_identical": True,
            "comparison": "counts and all 256 move slots per position; excludes 64-byte header backend flag",
            "cuda_run": cuda_parity_run,
            "cpu_run": cpu_parity_run,
            "cuda_output": cuda_file,
            "cpu_output": cpu_file,
        },
        "warmups": warmup_records,
        "measured_runs": {
            "cuda": cuda_runs,
            "cpu": cpu_runs,
        },
        "native_seconds": {
            "cuda": _distribution(cuda_native),
            "cpu": _distribution(cpu_native),
        },
        "process_wall_seconds": {
            "cuda": _distribution(cuda_wall),
            "cpu": _distribution(cpu_wall),
        },
        "throughput_at_native_p50": {
            "cuda_positions_per_second": args.positions / cuda_p50,
            "cuda_moves_per_second": moves / cuda_p50,
            "cpu_positions_per_second": args.positions / cpu_p50,
            "cpu_moves_per_second": moves / cpu_p50,
            "cuda_speedup_over_cpu": cpu_p50 / cuda_p50,
        },
        "measurement_boundary": (
            "The native timer excludes input parsing, host output assembly, and file I/O. The CUDA path includes "
            "cudaSetDevice, device allocation/free, H2D, kernel execution/synchronization, and D2H. Process-wall "
            "samples include process startup, input parsing, and output handling to the OS null device."
        ),
        "timing_isolation": {
            "exclusive_gpu_access_enforced": False,
            "concurrent_workloads_monitored": False,
            "interpretation": (
                "Timing samples are a local snapshot and may be perturbed by concurrent GPU, CPU, thermal, or "
                "power-management activity. Artifact isolation does not provide workload isolation."
            ),
        },
        "claim_boundary": (
            "This is a local packed-move microbenchmark and exact CPU/CUDA payload comparison, not sustained "
            "thermal evidence, playing-strength evidence, or a chess solution. Device name and compute capability "
            "are self-reported by the content-hashed executable and are checked for target consistency, but do not "
            "independently attest which hardware performed the expansion."
        ),
    }
    _publish_report_atomically(
        report_path,
        report,
        force=args.force,
        pre_publish_check=lambda: require_stable_input_identity(initial_input_identity, input_path),
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--positions", type=int, default=131_072)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--random-count", type=int, default=512)
    parser.add_argument("--max-plies", type=int, default=80)
    parser.add_argument("--cuda-runs", type=int, default=30)
    parser.add_argument("--cpu-runs", type=int, default=10)
    parser.add_argument("--warmups", type=int, default=2, help="unmeasured warmups per backend")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--force", action="store_true", help="replace same-name report evidence")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = benchmark(args)
    except BenchmarkError as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "parity_passed": bool(report["parity"]["semantic_payload_identical"]),
                "gpu_execution_independently_attested": False,
                "report": str(args.output_dir.resolve() / f"benchmark-{args.positions}.json"),
                "input_sha256": report["input"]["sha256"],
                "executable_sha256": report["executable"]["sha256"],
                "throughput_at_native_p50": report["throughput_at_native_p50"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
