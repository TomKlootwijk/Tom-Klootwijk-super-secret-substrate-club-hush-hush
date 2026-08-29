"""Deterministic CUDA move-generator qualification against the Python oracle.

This module is deliberately a gate, not a benchmark claim.  The measured wall
time includes protocol I/O and the exact Python verification performed by
``gpu_protocol.run_batch``.  A run qualifies only when every proposed move set
matches the oracle and every batch makes an allowlisted, internally consistent
CUDA claim with no fallback reason.  This is not independent GPU-execution
attestation because the executable controls its device and backend reports.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable

from .gpu_protocol import executable_identity, probe_cuda_device, run_batch
from .position import Position, START_FEN
from .rules import apply_move, legal_moves

DEFAULT_SEED = 0xC02026
DEFAULT_RANDOM_POSITIONS = 64
DEFAULT_MAX_PLIES = 80
DEFAULT_CHUNK_SIZE = 32
CUDA_BACKEND_ALLOWLIST = frozenset({"cuda", "cuda-packed-candidate-sm-runtime"})


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
            "output_sha256": output_sha256,
            "output_semantic_payload_sha256": output_semantic_sha256,
            "output_backend_flag": output_backend_flag,
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
    return {
        "schema": "ugts-chess-cuda-movegen-qualification-v1",
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
