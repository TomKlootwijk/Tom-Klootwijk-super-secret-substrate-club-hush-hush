"""Deterministic CUDA move-generator qualification against the Python oracle.

This module is deliberately a gate, not a benchmark claim.  The measured wall
time includes protocol I/O and the exact Python verification performed by
``gpu_protocol.run_batch``.  A run qualifies only when every proposed move set
matches the oracle and every batch makes an allowlisted, internally consistent
CUDA claim with no fallback reason.  This is not independent GPU-execution
attestation because the executable controls its device and backend reports.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile
from time import perf_counter
from typing import Callable

from .gpu_protocol import (
    OUTPUT_HEADER,
    decode_move_batch,
    encode_position_batch,
    executable_identity,
    probe_cuda_device,
    run_batch,
)
from .position import Position, START_FEN
from .rules import apply_move, legal_moves

DEFAULT_SEED = 0xC02026
DEFAULT_RANDOM_POSITIONS = 64
DEFAULT_MAX_PLIES = 80
DEFAULT_CHUNK_SIZE = 32
CUDA_BACKEND_ALLOWLIST = frozenset({"cuda", "cuda-packed-candidate-sm-runtime"})
QUALIFICATION_SCHEMA = "ugts-chess-cuda-movegen-qualification-v2"
QUALIFICATION_PROFILE = "exact-binary-device-self-report-oracle-parity-v2"


class GPUQualificationRecordError(ValueError):
    """Raised when a retained qualification record is not proof-gating evidence."""


@dataclass(frozen=True, slots=True)
class Fixture:
    name: str
    category: str
    fen: str
    perft_depth: int | None = None
    perft_nodes: int | None = None


@dataclass(frozen=True, slots=True)
class CorpusPosition:
    label: str
    source: str
    position: Position
    requested_plies: int | None = None


# The six conventional Chess Programming Wiki perft roots exercise dense,
# sparse, castling, promotion and check-evasion move generation.  Expected
# counts document which fixture versions are used; qualification compares the
# complete legal move set at each root rather than recomputing deep perft.
PERFT_FIXTURES: tuple[Fixture, ...] = (
    Fixture("perft_initial", "perft", START_FEN, 4, 197281),
    Fixture(
        "perft_kiwipete",
        "perft",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        3,
        97862,
    ),
    Fixture("perft_position_3", "perft", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238),
    Fixture(
        "perft_position_4",
        "perft",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        3,
        9467,
    ),
    Fixture("perft_position_5", "perft", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3, 62379),
    Fixture("perft_position_6", "perft", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", 3, 89890),
)


EDGE_RULE_FIXTURES: tuple[Fixture, ...] = (
    Fixture("castle_white_both_wings", "edge_rule", "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"),
    Fixture("castle_black_both_wings", "edge_rule", "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"),
    Fixture("castle_through_attack", "edge_rule", "r3k2r/8/8/8/2b5/8/8/R3K2R w KQkq - 0 1"),
    Fixture("en_passant_white", "edge_rule", "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"),
    Fixture("en_passant_black", "edge_rule", "4k3/8/8/8/3Pp3/8/8/4K3 b - d3 0 1"),
    Fixture("en_passant_discovered_check", "edge_rule", "k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"),
    Fixture("promotion_white_quiet_and_capture", "edge_rule", "1r5k/P7/8/8/8/8/8/7K w - - 0 1"),
    Fixture("promotion_black_quiet_and_capture", "edge_rule", "7K/8/8/8/8/8/p6k/1R6 b - - 0 1"),
    Fixture("checkmate_zero_moves", "edge_rule", "k7/1Q6/2K5/8/8/8/8/8 b - - 0 1"),
    Fixture("stalemate_zero_moves", "edge_rule", "k7/2Q5/2K5/8/8/8/8/8 b - - 0 1"),
)

QUALIFICATION_FIXTURES = PERFT_FIXTURES + EDGE_RULE_FIXTURES


class _SplitMix64:
    """Small specified PRNG so corpus construction is Python-version neutral."""

    _MASK = (1 << 64) - 1

    def __init__(self, seed: int) -> None:
        self.state = seed & self._MASK

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & self._MASK
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & self._MASK
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & self._MASK
        return (value ^ (value >> 31)) & self._MASK

    def index(self, upper_bound: int) -> int:
        if upper_bound <= 0:
            raise ValueError("random choice requires a positive upper bound")
        return self.next_u64() % upper_bound


def build_qualification_corpus(
    *,
    seed: int = DEFAULT_SEED,
    random_positions: int = DEFAULT_RANDOM_POSITIONS,
    max_plies: int = DEFAULT_MAX_PLIES,
) -> list[CorpusPosition]:
    """Return fixtures followed by independently sampled reachable positions."""

    if random_positions < 0:
        raise ValueError("random_positions must be non-negative")
    if max_plies < 1:
        raise ValueError("max_plies must be at least 1")

    corpus = [
        CorpusPosition(label=fixture.name, source=fixture.category, position=Position.from_fen(fixture.fen))
        for fixture in QUALIFICATION_FIXTURES
    ]
    generator = _SplitMix64(seed)
    for sample_index in range(random_positions):
        requested_plies = 1 + generator.index(max_plies)
        position = Position.initial()
        actual_plies = 0
        for _ in range(requested_plies):
            # Do not depend on an implementation detail of the oracle.  The
            # corpus contract explicitly maps SplitMix output into UCI order.
            moves = sorted(legal_moves(position), key=lambda move: move.uci())
            if not moves:
                break
            position = apply_move(position, moves[generator.index(len(moves))])
            actual_plies += 1
        corpus.append(
            CorpusPosition(
                label=f"random_{sample_index:06d}_ply_{actual_plies:03d}",
                source="seeded_random_reachable",
                position=position,
                requested_plies=requested_plies,
            )
        )
    return corpus


def corpus_sha256(corpus: list[CorpusPosition]) -> str:
    """Hash the ordered, newline-terminated canonical FEN sequence."""

    digest = hashlib.sha256()
    for item in corpus:
        digest.update(item.position.to_fen().encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def parse_backend_evidence(stdout: str) -> dict[str, object]:
    """Parse backend, fallback and native timing evidence conservatively."""

    backend: str | None = None
    fallback_reason = ""
    native_positions: int | None = None
    native_moves: int | None = None
    native_seconds: float | None = None
    parse_error: str | None = None
    try:
        payload = json.loads(stdout)
        if not isinstance(payload, dict):
            raise ValueError("backend output is not a JSON object")
        raw_backend = payload.get("backend")
        if not isinstance(raw_backend, str) or not raw_backend.strip():
            raise ValueError("backend field is missing or empty")
        backend = raw_backend.strip()
        if "cuda_fallback_reason" in payload:
            raw_fallback = payload["cuda_fallback_reason"]
        elif "fallback_reason" in payload:
            raw_fallback = payload["fallback_reason"]
        else:
            raise ValueError("fallback-reason field is missing")
        if not isinstance(raw_fallback, str):
            raise ValueError("fallback-reason field is not a string")
        fallback_reason = raw_fallback

        raw_positions = payload.get("positions")
        raw_moves = payload.get("moves")
        raw_seconds = payload.get("seconds")
        if isinstance(raw_positions, bool) or not isinstance(raw_positions, int) or raw_positions < 0:
            raise ValueError("positions field is not a non-negative integer")
        if isinstance(raw_moves, bool) or not isinstance(raw_moves, int) or raw_moves < 0:
            raise ValueError("moves field is not a non-negative integer")
        if isinstance(raw_seconds, bool) or not isinstance(raw_seconds, (int, float)):
            raise ValueError("seconds field is not a non-negative finite number")
        native_seconds = float(raw_seconds)
        if native_seconds < 0.0 or not math.isfinite(native_seconds):
            raise ValueError("seconds field is not a non-negative finite number")
        if raw_positions > 0 and native_seconds <= 0.0:
            raise ValueError("seconds field must be positive for a non-empty batch")
        native_positions = raw_positions
        native_moves = raw_moves
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        parse_error = str(exc)
        native_positions = None
        native_moves = None
        native_seconds = None

    cuda_backend = backend in CUDA_BACKEND_ALLOWLIST
    fallback_detected = bool(fallback_reason.strip()) or not cuda_backend or parse_error is not None
    return {
        "backend": backend,
        "fallback_reason": fallback_reason,
        "parse_error": parse_error,
        "cuda_backend": cuda_backend,
        "fallback_detected": fallback_detected,
        "native_positions": native_positions,
        "native_moves": native_moves,
        "native_seconds": native_seconds,
    }


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_gpu_qualification_record_structure(record: Mapping[str, object]) -> bool:
    """Validate the v2 shape, deterministic corpus, and internal consistency.

    This deliberately does *not* prove that a run happened.  A retained record
    is replay-qualified only by :func:`verify_gpu_qualification_record`, which
    requires caller-selected executable bytes and the retained batch artifacts.
    """

    def reject(message: str) -> None:
        raise GPUQualificationRecordError(message)

    def require(condition: bool, message: str) -> None:
        if not condition:
            reject(message)

    def is_int(value: object, *, minimum: int = 0) -> bool:
        return not isinstance(value, bool) and isinstance(value, int) and value >= minimum

    def identity(value: object, label: str) -> Mapping[str, object]:
        require(isinstance(value, Mapping), f"{label} is not an object")
        assert isinstance(value, Mapping)
        require(isinstance(value.get("path"), str) and bool(str(value["path"])), f"{label}.path is invalid")
        require(_is_sha256(value.get("sha256")), f"{label}.sha256 is invalid")
        require(is_int(value.get("size_bytes"), minimum=1), f"{label}.size_bytes is invalid")
        return value

    require(isinstance(record, Mapping), "qualification record is not an object")
    require(record.get("schema") == QUALIFICATION_SCHEMA, "unsupported qualification schema")
    require(record.get("profile") == QUALIFICATION_PROFILE, "unsupported qualification profile")
    require(record.get("qualified") is True, "qualification record is not passing")
    require(record.get("authority") == "python_exact_oracle_via_gpu_protocol.run_batch", "authority is invalid")
    require(record.get("gpu_execution_independently_attested") is False, "attestation boundary is invalid")
    require(record.get("device_claim_source") == "same_executable_self_report", "device claim source is invalid")

    executable = identity(record.get("executable"), "executable")
    final_executable = identity(record.get("final_executable"), "final_executable")
    require(final_executable == executable, "final executable identity differs")
    require(record.get("executable_identity_stable") is True, "executable identity is not stable")
    require(record.get("executable_identity_failure_count") == 0, "executable identity failure count is nonzero")
    require(record.get("executable_identity_failures") == [], "executable identity failure list is nonempty")

    device_probe = record.get("device_probe")
    require(isinstance(device_probe, Mapping), "device_probe is not an object")
    assert isinstance(device_probe, Mapping)
    require(record.get("device_probe_valid") is True, "device probe is not valid")
    require(device_probe.get("valid") is True, "device probe payload is not valid")
    require(device_probe.get("validation_failures") == [], "device probe has failures")
    require(device_probe.get("claim_source") == "same_executable_self_report", "device probe claim source is invalid")
    require(device_probe.get("independent_hardware_attestation") is False, "device probe attestation is invalid")
    require(identity(device_probe.get("executable"), "device_probe.executable") == executable, "device probe executable differs")
    require(device_probe.get("returncode") == 0, "device probe return code is nonzero")
    require(device_probe.get("parse_error") is None, "device probe parse error is present")
    require(_is_sha256(device_probe.get("stdout_sha256")), "device probe stdout hash is invalid")
    device_payload = device_probe.get("payload")
    require(isinstance(device_payload, Mapping), "device probe payload is not an object")
    assert isinstance(device_payload, Mapping)
    require(device_payload.get("cuda_compiled") is True, "device probe says CUDA is not compiled")
    require(device_payload.get("device_available") is True, "device probe says CUDA is unavailable")
    require(device_payload.get("device_index") == device_probe.get("device_index"), "device indices differ")
    require(
        isinstance(device_payload.get("name"), str) and bool(str(device_payload["name"]).strip()),
        "device name is invalid",
    )
    capability = device_payload.get("compute_capability")
    require(
        isinstance(capability, str)
        and len(capability.split(".")) == 2
        and all(part.isdigit() for part in capability.split(".")),
        "compute capability is invalid",
    )
    require(is_int(device_payload.get("total_memory_bytes"), minimum=1), "device memory is invalid")
    require(is_int(device_payload.get("multiprocessors"), minimum=1), "multiprocessor count is invalid")
    require(device_payload.get("error") == "", "device probe error is nonempty")
    device_stdout = device_probe.get("stdout")
    require(isinstance(device_stdout, str), "device probe stdout is invalid")
    try:
        parsed_device_stdout = json.loads(device_stdout)
    except json.JSONDecodeError as exc:
        reject(f"device probe stdout is not JSON: {exc}")
    require(parsed_device_stdout == device_payload, "device probe stdout and payload differ")

    allowlist = sorted(CUDA_BACKEND_ALLOWLIST)
    require(record.get("cuda_backend_allowlist") == allowlist, "CUDA backend allowlist differs")
    require(record.get("failure_reasons") == [], "qualification has failure reasons")
    require(record.get("all_batches_cuda") is True, "not all batches are CUDA")
    require(record.get("all_batches_claim_allowlisted_cuda") is True, "a backend claim is not allowlisted")
    require(record.get("fallback_batches") == [], "qualification contains fallback batches")
    require(record.get("backend_evidence_count_consistent") is True, "backend counts are inconsistent")
    require(record.get("backend_evidence_failure_count") == 0, "backend failure count is nonzero")
    require(record.get("backend_evidence_failures") == [], "backend failures are present")
    require(record.get("artifact_evidence_consistent") is True, "artifact evidence is inconsistent")
    require(record.get("artifact_evidence_failure_count") == 0, "artifact failure count is nonzero")
    require(record.get("artifact_evidence_failures") == [], "artifact failures are present")
    require(record.get("mismatch_count") == 0, "oracle mismatch count is nonzero")
    require(record.get("mismatches") == [], "oracle mismatches are present")
    require(record.get("native_cuda_metrics_complete") is True, "native CUDA metrics are incomplete")

    batches = record.get("batches")
    require(isinstance(batches, list) and bool(batches), "batches must be a nonempty array")
    assert isinstance(batches, list)
    require(record.get("batch_count") == len(batches), "batch_count differs from batches")
    position_count = record.get("position_count")
    unique_position_count = record.get("unique_position_count")
    require(is_int(position_count, minimum=1), "position_count is invalid")
    require(is_int(unique_position_count, minimum=1), "unique_position_count is invalid")
    assert isinstance(position_count, int) and isinstance(unique_position_count, int)
    require(unique_position_count <= position_count, "unique_position_count exceeds position_count")
    seed = record.get("seed")
    random_position_count = record.get("random_position_count")
    max_random_plies = record.get("max_random_plies")
    chunk_size = record.get("chunk_size")
    require(is_int(seed), "seed is invalid")
    require(is_int(random_position_count), "random_position_count is invalid")
    require(is_int(max_random_plies, minimum=1), "max_random_plies is invalid")
    require(is_int(chunk_size, minimum=1), "chunk_size is invalid")
    assert isinstance(seed, int)
    assert isinstance(random_position_count, int)
    assert isinstance(max_random_plies, int)
    assert isinstance(chunk_size, int)
    require(record.get("generator") == "splitmix64-v1/sorted-legal-uci-index", "generator is invalid")
    require(record.get("corpus_hash_encoding") == "sha256(ordered canonical FEN + LF)", "corpus hash encoding differs")
    rebuilt_corpus = build_qualification_corpus(
        seed=seed,
        random_positions=random_position_count,
        max_plies=max_random_plies,
    )
    require(len(rebuilt_corpus) == position_count, "position_count differs from rebuilt corpus")
    require(
        len({item.position.to_fen() for item in rebuilt_corpus}) == unique_position_count,
        "unique_position_count differs from rebuilt corpus",
    )
    require(record.get("fixture_count") == len(QUALIFICATION_FIXTURES), "fixture_count differs")
    require(record.get("corpus_sha256") == corpus_sha256(rebuilt_corpus), "corpus_sha256 differs from recipe")
    expected_batch_count = (position_count + chunk_size - 1) // chunk_size
    require(len(batches) == expected_batch_count, "batch count differs from chunk recipe")

    expected_start = 0
    total_proposal_moves = 0
    total_verified_moves = 0
    parsed_backends: set[str] = set()
    for batch_index, batch_value in enumerate(batches):
        require(isinstance(batch_value, Mapping), f"batch {batch_index} is not an object")
        assert isinstance(batch_value, Mapping)
        batch = batch_value
        require(batch.get("batch_index") == batch_index, f"batch {batch_index} index is not canonical")
        batch_start = expected_start
        require(batch.get("global_start_index") == batch_start, f"batch {batch_index} start is not contiguous")
        positions = batch.get("positions")
        require(is_int(positions, minimum=1), f"batch {batch_index} position count is invalid")
        assert isinstance(positions, int)
        expected_start += positions
        require(batch.get("global_stop_index") == expected_start, f"batch {batch_index} stop is inconsistent")
        expected_entries = rebuilt_corpus[batch_start:expected_start]
        expected_input_bytes = encode_position_batch(entry.position for entry in expected_entries)
        expected_input_sha256 = hashlib.sha256(expected_input_bytes).hexdigest()

        proposal_moves = batch.get("proposal_move_count")
        verified_moves = batch.get("verified_move_count")
        require(is_int(proposal_moves), f"batch {batch_index} proposal count is invalid")
        require(is_int(verified_moves), f"batch {batch_index} verified count is invalid")
        assert isinstance(proposal_moves, int) and isinstance(verified_moves, int)
        require(verified_moves == proposal_moves, f"batch {batch_index} move counts differ")
        total_proposal_moves += proposal_moves
        total_verified_moves += verified_moves

        backend = batch.get("backend")
        require(isinstance(backend, str) and backend in CUDA_BACKEND_ALLOWLIST, f"batch {batch_index} backend is invalid")
        parsed_backends.add(backend)
        require(batch.get("cuda_backend") is True, f"batch {batch_index} is not CUDA")
        require(batch.get("fallback_detected") is False, f"batch {batch_index} reports fallback")
        require(batch.get("fallback_reason") == "", f"batch {batch_index} fallback reason is nonempty")
        require(batch.get("backend_parse_error") is None, f"batch {batch_index} backend evidence did not parse")
        require(batch.get("native_positions") == positions, f"batch {batch_index} native positions differ")
        require(batch.get("native_moves") == proposal_moves, f"batch {batch_index} native moves differ")
        native_seconds = batch.get("native_seconds")
        require(
            not isinstance(native_seconds, bool)
            and isinstance(native_seconds, (int, float))
            and math.isfinite(float(native_seconds))
            and float(native_seconds) > 0.0,
            f"batch {batch_index} native duration is invalid",
        )
        require(batch.get("native_positions_match_batch_size") is True, f"batch {batch_index} position flag differs")
        require(batch.get("native_moves_match_proposal_count") is True, f"batch {batch_index} proposal flag differs")
        require(batch.get("native_moves_match_verified_count") is True, f"batch {batch_index} verified flag differs")
        require(batch.get("native_count_consistent") is True, f"batch {batch_index} native counts are inconsistent")
        require(batch.get("backend_evidence_count_failures") == [], f"batch {batch_index} has count failures")
        require(batch.get("input_sha256") == expected_input_sha256, f"batch {batch_index} input hash differs from corpus")
        require(_is_sha256(batch.get("output_sha256")), f"batch {batch_index} output hash is invalid")
        require(
            _is_sha256(batch.get("output_semantic_payload_sha256")),
            f"batch {batch_index} semantic output hash is invalid",
        )
        require(batch.get("output_backend_flag") == 1, f"batch {batch_index} output is not tagged CUDA")
        require(identity(batch.get("executable"), f"batch {batch_index}.executable") == executable, f"batch {batch_index} executable differs")
        require(
            batch.get("executable_identity_matches_qualification") is True,
            f"batch {batch_index} executable-match flag differs",
        )
        require(batch.get("artifact_evidence_consistent") is True, f"batch {batch_index} artifact evidence differs")
        require(batch.get("artifact_evidence_failures") == [], f"batch {batch_index} artifact failures are present")

        invocation_id = batch.get("invocation_id")
        require(
            isinstance(invocation_id, str)
            and len(invocation_id) == 32
            and all(character in "0123456789abcdef" for character in invocation_id),
            f"batch {batch_index} invocation ID is invalid",
        )
        invocation_dir = batch.get("invocation_dir")
        require(isinstance(invocation_dir, str) and bool(invocation_dir), f"batch {batch_index} invocation dir is invalid")
        assert isinstance(invocation_dir, str)
        invocation_path = Path(invocation_dir).resolve()

        input_meta = batch.get("input")
        output_meta = batch.get("output")
        require(isinstance(input_meta, Mapping), f"batch {batch_index} input metadata is absent")
        require(isinstance(output_meta, Mapping), f"batch {batch_index} output metadata is absent")
        assert isinstance(input_meta, Mapping) and isinstance(output_meta, Mapping)
        input_path = input_meta.get("path")
        output_path = output_meta.get("path")
        require(isinstance(input_path, str), f"batch {batch_index} input path is invalid")
        require(isinstance(output_path, str), f"batch {batch_index} output path is invalid")
        assert isinstance(input_path, str) and isinstance(output_path, str)
        require(Path(input_path).resolve() == invocation_path / "positions.ugcb", f"batch {batch_index} input path escapes invocation dir")
        require(Path(output_path).resolve() == invocation_path / "moves.ugmv", f"batch {batch_index} output path escapes invocation dir")
        require(input_meta.get("count") == positions, f"batch {batch_index} input metadata count differs")
        require(input_meta.get("sha256") == expected_input_sha256, f"batch {batch_index} input metadata hash differs")
        require(output_meta.get("count") == positions, f"batch {batch_index} output metadata count differs")
        require(output_meta.get("backend_flag") == 1, f"batch {batch_index} output metadata flag differs")
        require(output_meta.get("backend") == "cuda", f"batch {batch_index} output metadata backend differs")
        require(output_meta.get("sha256") == batch.get("output_sha256"), f"batch {batch_index} output metadata hash differs")
        require(
            output_meta.get("semantic_payload_sha256") == batch.get("output_semantic_payload_sha256"),
            f"batch {batch_index} output semantic metadata hash differs",
        )
        require(is_int(output_meta.get("bytes"), minimum=1), f"batch {batch_index} output byte count is invalid")

        stdout = batch.get("executable_stdout")
        require(isinstance(stdout, str), f"batch {batch_index} stdout is invalid")
        assert isinstance(stdout, str)
        parsed_evidence = parse_backend_evidence(stdout)
        evidence_pairs = {
            "backend": "backend",
            "fallback_reason": "fallback_reason",
            "parse_error": "backend_parse_error",
            "cuda_backend": "cuda_backend",
            "fallback_detected": "fallback_detected",
            "native_positions": "native_positions",
            "native_moves": "native_moves",
            "native_seconds": "native_seconds",
        }
        for parsed_key, batch_key in evidence_pairs.items():
            require(
                parsed_evidence[parsed_key] == batch.get(batch_key),
                f"batch {batch_index} stdout contradicts {batch_key}",
            )

    require(expected_start == position_count, "batch positions do not cover the corpus")
    require(record.get("proposal_move_count") == total_proposal_moves, "proposal move total differs")
    require(record.get("verified_move_count") == total_verified_moves, "verified move total differs")
    require(record.get("native_cuda_position_count") == position_count, "native CUDA position total differs")
    require(record.get("native_cuda_move_count") == total_proposal_moves, "native CUDA move total differs")
    require(record.get("native_cuda_batch_count") == len(batches), "native CUDA batch total differs")
    require(record.get("parsed_backends") == sorted(parsed_backends), "parsed backend summary differs")
    return True


def verify_gpu_qualification_record(
    record: Mapping[str, object],
    expected_executable: str | Path,
    *,
    fresh_device_probe: bool = True,
) -> bool:
    """Replay a retained v2 qualification against caller-selected binary bytes.

    The deterministic corpus and every retained input/output artifact are
    reconstructed or reread exactly once.  The caller-selected executable is
    then run again on every batch in fresh isolated directories; its fresh
    exact outputs must match both the retained bytes and the Python legal-move
    oracle.  A fresh device probe is performed by default.  CUDA execution is
    still self-reported by the executable, not independently attested.
    """

    validate_gpu_qualification_record_structure(record)

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise GPUQualificationRecordError(message)

    initial_executable = executable_identity(expected_executable)
    require(initial_executable == record["executable"], "caller-selected executable identity differs")

    device_probe_record = record["device_probe"]
    assert isinstance(device_probe_record, Mapping)
    if fresh_device_probe:
        device_index = device_probe_record["device_index"]
        assert isinstance(device_index, int) and not isinstance(device_index, bool)
        fresh_probe = probe_cuda_device(str(initial_executable["path"]), device=device_index)
        require(fresh_probe.get("valid") is True, "fresh device probe failed")
        require(fresh_probe.get("executable") == initial_executable, "fresh device probe used different bytes")
        fresh_payload = fresh_probe.get("payload")
        retained_payload = device_probe_record.get("payload")
        require(isinstance(fresh_payload, Mapping), "fresh device payload is invalid")
        assert isinstance(fresh_payload, Mapping) and isinstance(retained_payload, Mapping)
        for key in ("cuda_compiled", "device_available", "device_index", "name", "compute_capability"):
            require(fresh_payload.get(key) == retained_payload.get(key), f"fresh device identity differs at {key}")

    seed = record["seed"]
    random_position_count = record["random_position_count"]
    max_random_plies = record["max_random_plies"]
    assert isinstance(seed, int) and not isinstance(seed, bool)
    assert isinstance(random_position_count, int) and not isinstance(random_position_count, bool)
    assert isinstance(max_random_plies, int) and not isinstance(max_random_plies, bool)
    corpus = build_qualification_corpus(
        seed=seed,
        random_positions=random_position_count,
        max_plies=max_random_plies,
    )

    batches = record["batches"]
    assert isinstance(batches, list)
    for batch_index, batch_value in enumerate(batches):
        assert isinstance(batch_value, Mapping)
        batch = batch_value
        start = batch["global_start_index"]
        stop = batch["global_stop_index"]
        assert isinstance(start, int) and isinstance(stop, int)
        positions = [entry.position for entry in corpus[start:stop]]
        expected_input = encode_position_batch(positions)

        input_meta = batch["input"]
        output_meta = batch["output"]
        assert isinstance(input_meta, Mapping) and isinstance(output_meta, Mapping)
        input_path = Path(str(input_meta["path"]))
        output_path = Path(str(output_meta["path"]))
        try:
            input_bytes = input_path.read_bytes()
            output_bytes = output_path.read_bytes()
        except OSError as exc:
            raise GPUQualificationRecordError(f"batch {batch_index} artifact read failed: {exc}") from exc

        require(input_bytes == expected_input, f"batch {batch_index} input bytes differ from deterministic corpus")
        require(
            hashlib.sha256(input_bytes).hexdigest() == batch["input_sha256"],
            f"batch {batch_index} retained input hash differs",
        )
        require(
            hashlib.sha256(output_bytes).hexdigest() == batch["output_sha256"],
            f"batch {batch_index} retained output hash differs",
        )
        require(
            hashlib.sha256(output_bytes[OUTPUT_HEADER.size :]).hexdigest()
            == batch["output_semantic_payload_sha256"],
            f"batch {batch_index} retained semantic hash differs",
        )
        require(len(output_bytes) == output_meta["bytes"], f"batch {batch_index} output byte size differs")
        try:
            proposed = decode_move_batch(output_bytes)
        except ValueError as exc:
            raise GPUQualificationRecordError(f"batch {batch_index} output cannot be decoded: {exc}") from exc
        require(len(proposed) == len(positions), f"batch {batch_index} output position count differs")
        _magic, _version, _move_size, _max_moves, _count, backend_flag = OUTPUT_HEADER.unpack_from(output_bytes, 0)
        require(backend_flag == 1, f"batch {batch_index} retained output is not tagged CUDA")

        proposal_count = 0
        for local_index, (position, proposal_moves) in enumerate(zip(positions, proposed, strict=True)):
            exact_moves = sorted(move.uci() for move in legal_moves(position))
            require(
                sorted(proposal_moves) == exact_moves,
                f"batch {batch_index} position {local_index} differs from Python oracle",
            )
            proposal_count += len(proposal_moves)
        require(proposal_count == batch["proposal_move_count"], f"batch {batch_index} proposal total differs")
        require(proposal_count == batch["verified_move_count"], f"batch {batch_index} verified total differs")

    with tempfile.TemporaryDirectory(prefix="ugts-gpu-qualification-replay-") as replay_root_name:
        replay_root = Path(replay_root_name)
        for batch_index, batch_value in enumerate(batches):
            assert isinstance(batch_value, Mapping)
            batch = batch_value
            start = batch["global_start_index"]
            stop = batch["global_stop_index"]
            assert isinstance(start, int) and isinstance(stop, int)
            positions = [entry.position for entry in corpus[start:stop]]
            try:
                fresh_result = run_batch(
                    str(initial_executable["path"]),
                    positions,
                    replay_root / f"batch-{batch_index:06d}",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise GPUQualificationRecordError(
                    f"batch {batch_index} fresh executable replay failed: {exc}"
                ) from exc

            require(fresh_result.get("executable") == initial_executable, f"batch {batch_index} fresh executable differs")
            require(fresh_result.get("mismatches") == [], f"batch {batch_index} fresh replay differs from oracle")
            require(fresh_result.get("positions") == len(positions), f"batch {batch_index} fresh position count differs")
            require(
                fresh_result.get("proposal_move_count") == batch["proposal_move_count"],
                f"batch {batch_index} fresh proposal count differs",
            )
            require(
                fresh_result.get("verified_move_count") == batch["verified_move_count"],
                f"batch {batch_index} fresh verified count differs",
            )
            require(fresh_result.get("input_sha256") == batch["input_sha256"], f"batch {batch_index} fresh input differs")
            require(fresh_result.get("output_sha256") == batch["output_sha256"], f"batch {batch_index} fresh output differs")
            require(
                fresh_result.get("output_semantic_payload_sha256")
                == batch["output_semantic_payload_sha256"],
                f"batch {batch_index} fresh semantic output differs",
            )
            require(fresh_result.get("output_backend_flag") == 1, f"batch {batch_index} fresh output is not CUDA-tagged")
            fresh_evidence = parse_backend_evidence(str(fresh_result.get("executable_stdout", "")))
            require(fresh_evidence["cuda_backend"] is True, f"batch {batch_index} fresh backend is not CUDA")
            require(fresh_evidence["fallback_detected"] is False, f"batch {batch_index} fresh replay reports fallback")
            require(fresh_evidence["native_positions"] == len(positions), f"batch {batch_index} fresh native positions differ")
            require(
                fresh_evidence["native_moves"] == batch["proposal_move_count"],
                f"batch {batch_index} fresh native moves differ",
            )

    final_executable = executable_identity(str(initial_executable["path"]))
    require(final_executable == initial_executable, "caller-selected executable changed during replay")
    return True


def qualify_gpu_move_generator(
    executable: str | Path,
    work_dir: str | Path,
    *,
    seed: int = DEFAULT_SEED,
    random_positions: int = DEFAULT_RANDOM_POSITIONS,
    max_plies: int = DEFAULT_MAX_PLIES,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    clock: Callable[[], float] = perf_counter,
) -> dict[str, object]:
    """Run the deterministic corpus and return a proof-gating JSON record.

    The record binds exact executable bytes and checks that the same executable
    reports an available CUDA device.  That report and the per-batch backend
    flag remain self-claims, not independent proof that a CUDA kernel ran.
    """

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    corpus = build_qualification_corpus(seed=seed, random_positions=random_positions, max_plies=max_plies)
    root = Path(work_dir)
    initial_executable = executable_identity(executable)
    resolved_executable = str(initial_executable["path"])
    device_probe = probe_cuda_device(resolved_executable, device=0)
    device_probe_valid = device_probe.get("valid") is True
    executable_identity_failures: list[dict[str, object]] = []
    if device_probe.get("executable") != initial_executable:
        executable_identity_failures.append(
            {
                "stage": "device_probe",
                "expected": initial_executable,
                "actual": device_probe.get("executable"),
            }
        )

    end_to_end_latencies: list[float] = []
    native_cuda_latencies: list[float] = []
    native_cuda_positions = 0
    native_cuda_moves = 0
    batches: list[dict[str, object]] = []
    mismatches: list[dict[str, object]] = []
    total_proposal_moves = 0
    total_verified_moves = 0
    fallback_batches: list[dict[str, object]] = []
    backend_count_failures: list[dict[str, object]] = []
    artifact_evidence_failures: list[dict[str, object]] = []

    for batch_index, start in enumerate(range(0, len(corpus), chunk_size)):
        entries = corpus[start : start + chunk_size]
        positions = [entry.position for entry in entries]
        started = clock()
        result = run_batch(resolved_executable, positions, root / f"batch_{batch_index:06d}")
        latency = max(0.0, clock() - started)
        end_to_end_latencies.append(latency)

        evidence = parse_backend_evidence(str(result.get("executable_stdout", "")))
        input_sha256 = result.get("input_sha256")
        output_sha256 = result.get("output_sha256")
        output_semantic_sha256 = result.get("output_semantic_payload_sha256")
        output_backend_flag = result.get("output_backend_flag")
        invocation_id = result.get("invocation_id")
        invocation_dir = result.get("invocation_dir")
        input_meta = result.get("input")
        output_meta = result.get("output")
        batch_executable = result.get("executable")
        batch_executable_identity_matches = batch_executable == initial_executable
        proposal_moves = int(result.get("proposal_move_count", 0))
        verified_moves = int(result.get("verified_move_count", 0))
        raw_mismatches = result.get("mismatches", [])
        if not isinstance(raw_mismatches, list):
            raise ValueError("run_batch returned a non-list mismatches field")
        total_proposal_moves += proposal_moves
        total_verified_moves += verified_moves

        native_positions = evidence["native_positions"]
        native_moves = evidence["native_moves"]
        native_seconds = evidence["native_seconds"]
        native_positions_match = len(entries) == native_positions if isinstance(native_positions, int) else None
        native_moves_match_proposal = proposal_moves == native_moves if isinstance(native_moves, int) else None
        native_moves_match_verified = (
            verified_moves == native_moves if not raw_mismatches and isinstance(native_moves, int) else None
        )
        count_consistency_failures: list[str] = []
        if native_positions_match is False:
            count_consistency_failures.append("native_positions_vs_batch_size")
        if native_moves_match_proposal is False:
            count_consistency_failures.append("native_moves_vs_proposal_count")
        if native_moves_match_verified is False:
            count_consistency_failures.append("native_moves_vs_verified_count")
        native_count_consistent: bool | None = (
            not count_consistency_failures
            if native_positions_match is not None and native_moves_match_proposal is not None
            else None
        )
        if count_consistency_failures:
            backend_count_failures.append(
                {
                    "batch_index": batch_index,
                    "failures": count_consistency_failures,
                    "native_positions": native_positions,
                    "expected_positions": len(entries),
                    "native_moves": native_moves,
                    "proposal_move_count": proposal_moves,
                    "verified_move_count": verified_moves,
                    "exact_batch": not raw_mismatches,
                }
            )

        artifact_failures: list[str] = []
        if not _is_sha256(input_sha256):
            artifact_failures.append("input_sha256_missing_or_invalid")
        if not _is_sha256(output_sha256):
            artifact_failures.append("output_sha256_missing_or_invalid")
        if not _is_sha256(output_semantic_sha256):
            artifact_failures.append("output_semantic_payload_sha256_missing_or_invalid")
        if (
            not isinstance(invocation_id, str)
            or len(invocation_id) != 32
            or any(character not in "0123456789abcdef" for character in invocation_id)
        ):
            artifact_failures.append("invocation_id_missing_or_invalid")
        if not isinstance(invocation_dir, str) or not invocation_dir:
            artifact_failures.append("invocation_dir_missing_or_invalid")
        if not isinstance(input_meta, Mapping):
            artifact_failures.append("input_metadata_missing_or_invalid")
        else:
            if input_meta.get("sha256") != input_sha256 or input_meta.get("count") != len(entries):
                artifact_failures.append("input_metadata_inconsistent")
        if not isinstance(output_meta, Mapping):
            artifact_failures.append("output_metadata_missing_or_invalid")
        else:
            if (
                output_meta.get("sha256") != output_sha256
                or output_meta.get("semantic_payload_sha256") != output_semantic_sha256
                or output_meta.get("count") != len(entries)
                or output_meta.get("backend_flag") != output_backend_flag
            ):
                artifact_failures.append("output_metadata_inconsistent")
        if (
            isinstance(output_backend_flag, bool)
            or not isinstance(output_backend_flag, int)
            or output_backend_flag not in (0, 1)
        ):
            artifact_failures.append("output_backend_flag_missing_or_invalid")
        elif evidence["backend"] is not None:
            expected_backend_flag = 1 if evidence["cuda_backend"] else 0
            if output_backend_flag != expected_backend_flag:
                artifact_failures.append("output_backend_flag_vs_stdout")
        if not batch_executable_identity_matches:
            executable_identity_failures.append(
                {
                    "stage": "batch",
                    "batch_index": batch_index,
                    "expected": initial_executable,
                    "actual": batch_executable,
                }
            )
        artifact_evidence_consistent = not artifact_failures
        if artifact_failures:
            artifact_evidence_failures.append(
                {
                    "batch_index": batch_index,
                    "failures": artifact_failures,
                    "stdout_backend": evidence["backend"],
                    "stdout_cuda_backend": evidence["cuda_backend"],
                    "output_backend_flag": output_backend_flag,
                    "input_sha256": input_sha256,
                    "output_sha256": output_sha256,
                    "output_semantic_payload_sha256": output_semantic_sha256,
                    "executable": batch_executable,
                }
            )

        if (
            evidence["cuda_backend"]
            and not evidence["fallback_detected"]
            and isinstance(native_seconds, float)
            and native_count_consistent is True
            and artifact_evidence_consistent
            and batch_executable_identity_matches
            and device_probe_valid
        ):
            native_cuda_latencies.append(native_seconds)
            native_cuda_positions += int(native_positions)
            native_cuda_moves += int(native_moves)

        batch_record: dict[str, object] = {
            "batch_index": batch_index,
            "invocation_id": invocation_id,
            "invocation_dir": invocation_dir,
            "global_start_index": start,
            "global_stop_index": start + len(entries),
            "positions": len(entries),
            "proposal_move_count": proposal_moves,
            "verified_move_count": verified_moves,
            "end_to_end_latency_ms": round(latency * 1000.0, 6),
            "backend": evidence["backend"],
            "fallback_reason": evidence["fallback_reason"],
            "backend_parse_error": evidence["parse_error"],
            "cuda_backend": evidence["cuda_backend"],
            "fallback_detected": evidence["fallback_detected"],
            "native_positions": native_positions,
            "native_moves": native_moves,
            "native_seconds": native_seconds,
            "native_positions_match_batch_size": native_positions_match,
            "native_moves_match_proposal_count": native_moves_match_proposal,
            "native_moves_match_verified_count": native_moves_match_verified,
            "native_count_consistent": native_count_consistent,
            "backend_evidence_count_failures": count_consistency_failures,
            "input_sha256": input_sha256,
            "input": input_meta,
            "output_sha256": output_sha256,
            "output_semantic_payload_sha256": output_semantic_sha256,
            "output_backend_flag": output_backend_flag,
            "output": output_meta,
            "executable": batch_executable,
            "executable_identity_matches_qualification": batch_executable_identity_matches,
            "artifact_evidence_consistent": artifact_evidence_consistent,
            "artifact_evidence_failures": artifact_failures,
            "native_cuda_latency_ms": round(native_seconds * 1000.0, 6)
            if evidence["cuda_backend"] and isinstance(native_seconds, float)
            else None,
            "executable_stdout": str(result.get("executable_stdout", "")),
        }
        batches.append(batch_record)
        if evidence["fallback_detected"]:
            fallback_batches.append(
                {
                    "batch_index": batch_index,
                    "backend": evidence["backend"],
                    "fallback_reason": evidence["fallback_reason"],
                    "parse_error": evidence["parse_error"],
                }
            )

        for raw_mismatch in raw_mismatches:
            if not isinstance(raw_mismatch, dict):
                raise ValueError("run_batch returned a non-object mismatch")
            local_index = int(raw_mismatch["index"])
            if not 0 <= local_index < len(entries):
                raise ValueError("run_batch mismatch index is outside its batch")
            global_index = start + local_index
            mismatch = dict(raw_mismatch)
            mismatch.update(
                {
                    "index": global_index,
                    "global_index": global_index,
                    "batch_index": batch_index,
                    "batch_local_index": local_index,
                    "corpus_label": corpus[global_index].label,
                    "corpus_source": corpus[global_index].source,
                }
            )
            mismatches.append(mismatch)

    final_executable = executable_identity(resolved_executable)
    if final_executable != initial_executable:
        executable_identity_failures.append(
            {
                "stage": "qualification_end",
                "expected": initial_executable,
                "actual": final_executable,
            }
        )

    end_to_end_elapsed = sum(end_to_end_latencies)
    native_cuda_elapsed = sum(native_cuda_latencies)
    all_cuda = not fallback_batches and all(bool(batch["cuda_backend"]) for batch in batches)
    qualified = (
        not mismatches
        and all_cuda
        and not backend_count_failures
        and not artifact_evidence_failures
        and device_probe_valid
        and not executable_identity_failures
    )
    failure_reasons: list[str] = []
    if mismatches:
        failure_reasons.append("move_set_mismatch")
    if not all_cuda:
        failure_reasons.append("non_cuda_or_fallback_batch")
    if backend_count_failures:
        failure_reasons.append("backend_evidence_count_mismatch")
    if artifact_evidence_failures:
        failure_reasons.append("backend_artifact_evidence_mismatch")
    if not device_probe_valid:
        failure_reasons.append("cuda_device_probe_failed")
    if executable_identity_failures:
        failure_reasons.append("executable_identity_mismatch")

    fixture_manifest = [
        {
            "global_index": index,
            "name": fixture.name,
            "category": fixture.category,
            "fen": fixture.fen,
            "perft_depth": fixture.perft_depth,
            "perft_nodes": fixture.perft_nodes,
        }
        for index, fixture in enumerate(QUALIFICATION_FIXTURES)
    ]
    backends = sorted({str(batch["backend"]) for batch in batches if batch["backend"] is not None})
    record: dict[str, object] = {
        "schema": QUALIFICATION_SCHEMA,
        "profile": QUALIFICATION_PROFILE,
        "qualified": qualified,
        "failure_reasons": failure_reasons,
        "authority": "python_exact_oracle_via_gpu_protocol.run_batch",
        "executable": initial_executable,
        "final_executable": final_executable,
        "executable_identity_stable": not executable_identity_failures,
        "executable_identity_failure_count": len(executable_identity_failures),
        "executable_identity_failures": executable_identity_failures,
        "device_probe": device_probe,
        "device_probe_valid": device_probe_valid,
        "device_claim_source": "same_executable_self_report",
        "cuda_backend_allowlist": sorted(CUDA_BACKEND_ALLOWLIST),
        "gpu_execution_independently_attested": False,
        "attestation_boundary": (
            "The exact executable bytes, device-info claim, output backend flag, stdout backend claim, counters, "
            "and oracle parity are bound and cross-checked. The executable controls both CUDA claims, so this "
            "record does not independently prove that its legal moves were computed on the GPU."
        ),
        "seed": seed,
        "generator": "splitmix64-v1/sorted-legal-uci-index",
        "corpus_sha256": corpus_sha256(corpus),
        "corpus_hash_encoding": "sha256(ordered canonical FEN + LF)",
        "position_count": len(corpus),
        "unique_position_count": len({item.position.to_fen() for item in corpus}),
        "fixture_count": len(QUALIFICATION_FIXTURES),
        "random_position_count": random_positions,
        "max_random_plies": max_plies,
        "fixtures": fixture_manifest,
        "chunk_size": chunk_size,
        "batch_count": len(batches),
        "end_to_end_batch_latency_ms": {
            "p50": round(_percentile(end_to_end_latencies, 0.50) * 1000.0, 6),
            "p95": round(_percentile(end_to_end_latencies, 0.95) * 1000.0, 6),
            "p99": round(_percentile(end_to_end_latencies, 0.99) * 1000.0, 6),
            "measurement": "end_to_end_run_batch_wall",
        },
        "end_to_end_elapsed_seconds": round(end_to_end_elapsed, 9),
        "end_to_end_positions_per_second": round(len(corpus) / end_to_end_elapsed, 3)
        if end_to_end_elapsed > 0.0
        else 0.0,
        "end_to_end_moves_per_second": round(total_proposal_moves / end_to_end_elapsed, 3)
        if end_to_end_elapsed > 0.0
        else 0.0,
        "native_cuda_latency_ms": {
            "p50": round(_percentile(native_cuda_latencies, 0.50) * 1000.0, 6),
            "p95": round(_percentile(native_cuda_latencies, 0.95) * 1000.0, 6),
            "p99": round(_percentile(native_cuda_latencies, 0.99) * 1000.0, 6),
            "measurement": "native_executable_reported_cuda_expand_batch",
        },
        "native_cuda_elapsed_seconds": round(native_cuda_elapsed, 9),
        "native_cuda_positions_per_second": round(native_cuda_positions / native_cuda_elapsed, 3)
        if native_cuda_elapsed > 0.0
        else 0.0,
        "native_cuda_moves_per_second": round(native_cuda_moves / native_cuda_elapsed, 3)
        if native_cuda_elapsed > 0.0
        else 0.0,
        "native_cuda_position_count": native_cuda_positions,
        "native_cuda_move_count": native_cuda_moves,
        "native_cuda_batch_count": len(native_cuda_latencies),
        "native_cuda_metrics_complete": len(native_cuda_latencies) == len(batches),
        "proposal_move_count": total_proposal_moves,
        "verified_move_count": total_verified_moves,
        "parsed_backends": backends,
        "all_batches_cuda": all_cuda,
        "all_batches_claim_allowlisted_cuda": all_cuda,
        "fallback_batches": fallback_batches,
        "backend_evidence_count_consistent": not backend_count_failures,
        "backend_evidence_failure_count": len(backend_count_failures),
        "backend_evidence_failures": backend_count_failures,
        "artifact_evidence_consistent": not artifact_evidence_failures,
        "artifact_evidence_failure_count": len(artifact_evidence_failures),
        "artifact_evidence_failures": artifact_evidence_failures,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "batches": batches,
    }
    return record
