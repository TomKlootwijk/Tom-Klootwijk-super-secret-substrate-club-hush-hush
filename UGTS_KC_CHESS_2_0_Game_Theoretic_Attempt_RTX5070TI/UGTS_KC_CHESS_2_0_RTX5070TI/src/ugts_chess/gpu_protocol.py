"""Binary exchange between the exact Python oracle and the optional CUDA mover.

GPU output is proposal-only.  Every returned move is independently re-parsed and
verified by the Python legal kernel before it may enter a proof certificate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
from typing import Iterable
import uuid

from .constants import WHITE
from .position import Position
from .rules import legal_moves, parse_uci_move

INPUT_MAGIC = b"UGTSCB20"
OUTPUT_MAGIC = b"UGTSMV20"
INPUT_HEADER = struct.Struct("<8sIIII40x")  # 64 bytes
OUTPUT_HEADER = struct.Struct("<8sIIIII36x")  # 64 bytes
PACKED_POSITION = struct.Struct("<4Q2QIHBBbBB5x")  # 64 bytes
MAX_MOVES = 256

PIECE_TO_CODE = {
    ".": 0,
    "P": 1,
    "N": 2,
    "B": 3,
    "R": 4,
    "Q": 5,
    "K": 6,
    "p": 9,
    "n": 10,
    "b": 11,
    "r": 12,
    "q": 13,
    "k": 14,
}
CODE_TO_PROMOTION = {0: "", 1: "n", 2: "b", 3: "r", 4: "q"}
PROMOTION_TO_CODE = {value: key for key, value in CODE_TO_PROMOTION.items()}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_executable(executable: str | Path) -> Path:
    """Resolve an executable once so later subprocesses cannot select another PATH entry."""

    requested = Path(executable)
    if requested.is_file():
        return requested.resolve(strict=True)
    located = shutil.which(str(executable))
    if located is None:
        raise FileNotFoundError(f"GPU batch executable not found: {executable}")
    resolved = Path(located).resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(f"GPU batch executable is not a regular file: {resolved}")
    return resolved


def executable_identity(executable: str | Path) -> dict[str, object]:
    """Return a content identity for the exact executable bytes to be launched."""

    resolved = resolve_executable(executable)
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "size_bytes": stat.st_size,
    }


def probe_cuda_device(executable: str | Path, *, device: int = 0) -> dict[str, object]:
    """Record the executable's CUDA device claim and bind it to exact binary bytes.

    This is a consistency check, not independent hardware attestation: the
    probed executable controls the returned JSON.
    """

    before = executable_identity(executable)
    resolved = str(before["path"])
    completed = subprocess.run(
        [resolved, "device-info", "--device", str(device)],
        check=False,
        capture_output=True,
        text=True,
    )
    after = executable_identity(resolved)
    failures: list[str] = []
    if before != after:
        failures.append("executable_changed_during_device_probe")

    stdout = completed.stdout.strip()
    payload: dict[str, object] | None = None
    parse_error: str | None = None
    try:
        raw_payload = json.loads(stdout)
        if not isinstance(raw_payload, dict):
            raise ValueError("device-info output is not a JSON object")
        payload = raw_payload
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        parse_error = str(exc)
        failures.append("device_info_json_invalid")

    if completed.returncode != 0:
        failures.append("device_info_nonzero_exit")
    if payload is not None:
        if payload.get("cuda_compiled") is not True:
            failures.append("cuda_not_compiled")
        if payload.get("device_available") is not True:
            failures.append("cuda_device_unavailable")
        reported_index = payload.get("device_index")
        if isinstance(reported_index, bool) or not isinstance(reported_index, int) or reported_index != device:
            failures.append("device_index_mismatch")
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            failures.append("device_name_missing")
        compute_capability = payload.get("compute_capability")
        if not isinstance(compute_capability, str) or re.fullmatch(r"[0-9]+\.[0-9]+", compute_capability) is None:
            failures.append("compute_capability_invalid")
        total_memory = payload.get("total_memory_bytes")
        if isinstance(total_memory, bool) or not isinstance(total_memory, int) or total_memory <= 0:
            failures.append("total_memory_invalid")
        multiprocessors = payload.get("multiprocessors")
        if isinstance(multiprocessors, bool) or not isinstance(multiprocessors, int) or multiprocessors <= 0:
            failures.append("multiprocessor_count_invalid")
        error = payload.get("error")
        if not isinstance(error, str) or error:
            failures.append("device_info_error_present")

    return {
        "valid": not failures,
        "validation_failures": failures,
        "device_index": device,
        "payload": payload,
        "parse_error": parse_error,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr": completed.stderr.strip(),
        "executable": after,
        "claim_source": "same_executable_self_report",
        "independent_hardware_attestation": False,
    }


def encode_move16(uci: str) -> int:
    if len(uci) not in (4, 5):
        raise ValueError(f"invalid UCI move {uci!r}")
    from_file = ord(uci[0]) - 97
    from_rank = ord(uci[1]) - 49
    to_file = ord(uci[2]) - 97
    to_rank = ord(uci[3]) - 49
    if not all(0 <= value < 8 for value in (from_file, from_rank, to_file, to_rank)):
        raise ValueError(f"invalid UCI squares {uci!r}")
    from_sq = from_rank * 8 + from_file
    to_sq = to_rank * 8 + to_file
    promo = PROMOTION_TO_CODE.get(uci[4].lower() if len(uci) == 5 else "")
    if promo is None:
        raise ValueError(f"invalid promotion {uci!r}")
    return from_sq | (to_sq << 6) | (promo << 12)


def decode_move16(value: int) -> str:
    from_sq = value & 63
    to_sq = (value >> 6) & 63
    promo = (value >> 12) & 7
    if promo not in CODE_TO_PROMOTION:
        raise ValueError(f"invalid packed promotion code {promo}")
    def sq_name(sq: int) -> str:
        return chr(97 + (sq & 7)) + chr(49 + (sq >> 3))
    return sq_name(from_sq) + sq_name(to_sq) + CODE_TO_PROMOTION[promo]


def pack_position(position: Position, *, parent: int = 0, key_lo: int = 0, key_hi: int = 0) -> bytes:
    cells = [0, 0, 0, 0]
    for sq, piece in enumerate(position.board):
        code = PIECE_TO_CODE[piece]
        word = sq // 16
        shift = (sq % 16) * 4
        cells[word] |= code << shift
    return PACKED_POSITION.pack(
        *cells,
        key_lo & ((1 << 64) - 1),
        key_hi & ((1 << 64) - 1),
        parent & 0xFFFFFFFF,
        min(position.fullmove_number, 0xFFFF),
        0 if position.turn == WHITE else 1,
        position.castling & 0xFF,
        position.ep_square,
        min(position.halfmove_clock, 150),
        0,
    )


def write_position_batch(path: str | Path, positions: Iterable[Position]) -> dict[str, object]:
    path = Path(path)
    records = list(positions)
    payload = b"".join(pack_position(position, parent=index) for index, position in enumerate(records))
    header = INPUT_HEADER.pack(INPUT_MAGIC, 1, PACKED_POSITION.size, len(records), 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + payload)
    return {
        "path": str(path),
        "count": len(records),
        "record_size": PACKED_POSITION.size,
        "sha256": hashlib.sha256(header + payload).hexdigest(),
    }


def read_move_batch(path: str | Path) -> list[list[str]]:
    raw = Path(path).read_bytes()
    if len(raw) < OUTPUT_HEADER.size:
        raise ValueError("truncated move batch")
    magic, version, move_size, max_moves, count, _flags = OUTPUT_HEADER.unpack_from(raw, 0)
    if magic != OUTPUT_MAGIC or version != 1 or move_size != 2 or max_moves != MAX_MOVES:
        raise ValueError("unsupported move-batch format")
    counts_offset = OUTPUT_HEADER.size
    counts_size = count * 2
    moves_offset = counts_offset + counts_size
    expected = moves_offset + count * MAX_MOVES * 2
    if len(raw) != expected:
        raise ValueError(f"move-batch size mismatch: {len(raw)} != {expected}")
    counts = struct.unpack_from(f"<{count}H", raw, counts_offset) if count else ()
    result: list[list[str]] = []
    for index, move_count in enumerate(counts):
        if move_count > MAX_MOVES:
            raise ValueError("move count exceeds protocol maximum")
        base = moves_offset + index * MAX_MOVES * 2
        values = struct.unpack_from(f"<{move_count}H", raw, base) if move_count else ()
        result.append([decode_move16(value) for value in values])
    return result


def run_batch(executable: str | Path, positions: list[Position], work_dir: str | Path) -> dict[str, object]:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    input_path = work_dir / "positions.ugcb"
    output_path = work_dir / "moves.ugmv"
    # A successful no-op process must never inherit a prior run's answer.
    # The unpredictable staging name also prevents accidental collisions with
    # another invocation before the result is atomically published.
    output_path.unlink(missing_ok=True)
    staged_output_path = work_dir / f".moves.{uuid.uuid4().hex}.ugmv"
    input_meta = write_position_batch(input_path, positions)
    executable_before = executable_identity(executable)
    resolved_executable = str(executable_before["path"])
    published = False
    try:
        completed = subprocess.run(
            [
                resolved_executable,
                "expand-batch",
                "--input",
                str(input_path),
                "--output",
                str(staged_output_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"GPU batch executable failed: {completed.stderr or completed.stdout}")
        if not staged_output_path.is_file():
            raise RuntimeError("GPU batch executable exited successfully without writing its requested output")
        staged_output_path.replace(output_path)
        published = True
    finally:
        staged_output_path.unlink(missing_ok=True)
        if not published:
            output_path.unlink(missing_ok=True)
    executable_after = executable_identity(resolved_executable)
    if executable_before != executable_after:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("GPU batch executable changed while the batch was running")
    proposed = read_move_batch(output_path)
    output_bytes = output_path.read_bytes()
    _magic, _version, _move_size, _max_moves, output_count, output_flags = OUTPUT_HEADER.unpack_from(
        output_bytes, 0
    )
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    output_semantic_sha256 = hashlib.sha256(output_bytes[OUTPUT_HEADER.size :]).hexdigest()
    output_meta = {
        "path": str(output_path),
        "count": output_count,
        "backend_flag": output_flags,
        "backend": "cuda" if output_flags == 1 else "cpu" if output_flags == 0 else "unknown",
        "bytes": len(output_bytes),
        "sha256": output_sha256,
        "semantic_payload_sha256": output_semantic_sha256,
    }
    verified: list[list[str]] = []
    mismatches: list[dict[str, object]] = []
    for index, (position, proposal_moves) in enumerate(zip(positions, proposed, strict=True)):
        exact_moves = sorted(move.uci() for move in legal_moves(position))
        proposal_sorted = sorted(proposal_moves)
        accepted: list[str] = []
        for uci in proposal_moves:
            try:
                parse_uci_move(position, uci)
            except ValueError:
                continue
            accepted.append(uci)
        verified.append(sorted(set(accepted)))
        if proposal_sorted != exact_moves:
            mismatches.append(
                {
                    "index": index,
                    "fen": position.to_fen(),
                    "missing": sorted(set(exact_moves) - set(proposal_sorted)),
                    "extra": sorted(set(proposal_sorted) - set(exact_moves)),
                }
            )
    return {
        "executable": executable_after,
        "executable_path": executable_after["path"],
        "executable_sha256": executable_after["sha256"],
        "executable_size_bytes": executable_after["size_bytes"],
        "input": input_meta,
        "output": output_meta,
        "input_sha256": input_meta["sha256"],
        "output_sha256": output_sha256,
        "output_semantic_payload_sha256": output_semantic_sha256,
        "output_backend_flag": output_flags,
        "executable_stdout": completed.stdout.strip(),
        "positions": len(positions),
        "proposal_move_count": sum(len(items) for items in proposed),
        "verified_move_count": sum(len(items) for items in verified),
        "mismatches": mismatches,
        "authority": "python_exact_oracle",
    }


def recommended_rtx5070ti_config() -> dict[str, object]:
    """Return a conservative runtime profile for the 12 GB laptop GPU.

    The 9 GiB solver budget deliberately leaves roughly 3 GiB for the display
    driver, desktop, CUDA context, code, allocator fragmentation, and thermal
    adaptation.  These are starting limits, not measured laptop performance.
    """

    mib = 1024**2
    allocation_mib = {
        "transposition_and_proof_index": 5120,
        "frontier_positions": 1024,
        "move_matrix_and_counts": 1024,
        "retrograde_edges_and_counters": 1024,
        "checkpoint_staging": 512,
        "scratch": 512,
    }
    return {
        "profile_id": "rtx5070ti-laptop-12gb-sm120-v2",
        "device_match": "GeForce RTX 5070 Ti Laptop GPU",
        "nominal_vram_mib": 12288,
        "reserved_headroom_mib": 3072,
        "solver_budget_mib": sum(allocation_mib.values()),
        "compile_architecture": "120",
        "cmake_cuda_architectures": "120",
        "ptx_fallback": "compute_120",
        "minimum_toolkit": "CUDA 12.8",
        "batch_positions_initial": 131072,
        "batch_positions_min": 16384,
        "max_moves_per_position": MAX_MOVES,
        "threads_per_block": 256,
        "streams_initial": 3,
        "allocation_mib": allocation_mib,
        "allocation_bytes": {key: value * mib for key, value in allocation_mib.items()},
        "adaptive_rules": [
            "halve the batch after any allocation failure",
            "checkpoint before changing memory tiers",
            "reduce streams or batch size if the laptop reports thermal throttling",
            "never relax legal-move or certificate-verification gates for speed",
        ],
        "correctness_boundary": (
            "CUDA produces move/frontier/retrograde proposal candidates only; the exact host verifier and "
            "content-addressed certificate chain remain authoritative."
        ),
        "measurement_boundary": (
            "Profile values are conservative configuration defaults, not physical benchmark results; bind device "
            "measurements to separate timestamped evidence."
        ),
    }
