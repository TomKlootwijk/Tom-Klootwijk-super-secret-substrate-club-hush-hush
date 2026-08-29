"""Deterministic CUDA move-generator qualification against the Python oracle.

This module is deliberately a gate, not a benchmark claim.  The measured wall
time includes protocol I/O and the exact Python verification performed by
``gpu_protocol.run_batch``.  A run qualifies only when every proposed move set
matches the oracle and every batch reports an actual CUDA backend with no
fallback reason.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable

from .gpu_protocol import run_batch
from .position import Position, START_FEN
from .rules import apply_move, legal_moves

DEFAULT_SEED = 0xC02026
DEFAULT_RANDOM_POSITIONS = 64
DEFAULT_MAX_PLIES = 80
DEFAULT_CHUNK_SIZE = 32


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
            moves = legal_moves(position)
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
    """Parse the expander's JSON backend/fallback attestation conservatively."""

    backend: str | None = None
    fallback_reason = ""
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
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        parse_error = str(exc)

    normalized = backend.lower() if backend is not None else ""
    cuda_backend = (
        (normalized == "cuda" or normalized.startswith("cuda-"))
        and "fallback" not in normalized
        and "cpu" not in normalized
    )
    fallback_detected = bool(fallback_reason.strip()) or not cuda_backend or parse_error is not None
    return {
        "backend": backend,
        "fallback_reason": fallback_reason,
        "parse_error": parse_error,
        "cuda_backend": cuda_backend,
        "fallback_detected": fallback_detected,
    }


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
    """Run the deterministic corpus and return a proof-gating JSON record."""

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    corpus = build_qualification_corpus(seed=seed, random_positions=random_positions, max_plies=max_plies)
    root = Path(work_dir)

    latencies: list[float] = []
    batches: list[dict[str, object]] = []
    mismatches: list[dict[str, object]] = []
    total_proposal_moves = 0
    total_verified_moves = 0
    fallback_batches: list[dict[str, object]] = []

    for batch_index, start in enumerate(range(0, len(corpus), chunk_size)):
        entries = corpus[start : start + chunk_size]
        positions = [entry.position for entry in entries]
        started = clock()
        result = run_batch(executable, positions, root / f"batch_{batch_index:06d}")
        latency = max(0.0, clock() - started)
        latencies.append(latency)

        evidence = parse_backend_evidence(str(result.get("executable_stdout", "")))
        proposal_moves = int(result.get("proposal_move_count", 0))
        verified_moves = int(result.get("verified_move_count", 0))
        total_proposal_moves += proposal_moves
        total_verified_moves += verified_moves

        batch_record: dict[str, object] = {
            "batch_index": batch_index,
            "global_start_index": start,
            "global_stop_index": start + len(entries),
            "positions": len(entries),
            "proposal_move_count": proposal_moves,
            "verified_move_count": verified_moves,
            "latency_ms": round(latency * 1000.0, 6),
            "backend": evidence["backend"],
            "fallback_reason": evidence["fallback_reason"],
            "backend_parse_error": evidence["parse_error"],
            "cuda_backend": evidence["cuda_backend"],
            "fallback_detected": evidence["fallback_detected"],
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

        raw_mismatches = result.get("mismatches", [])
        if not isinstance(raw_mismatches, list):
            raise ValueError("run_batch returned a non-list mismatches field")
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

    elapsed = sum(latencies)
    all_cuda = not fallback_batches and all(bool(batch["cuda_backend"]) for batch in batches)
    qualified = not mismatches and all_cuda
    failure_reasons: list[str] = []
    if mismatches:
        failure_reasons.append("move_set_mismatch")
    if not all_cuda:
        failure_reasons.append("non_cuda_or_fallback_batch")

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
        "batch_latency_ms": {
            "p50": round(_percentile(latencies, 0.50) * 1000.0, 6),
            "p95": round(_percentile(latencies, 0.95) * 1000.0, 6),
            "p99": round(_percentile(latencies, 0.99) * 1000.0, 6),
            "measurement": "end_to_end_run_batch_wall",
        },
        "elapsed_batch_seconds": round(elapsed, 9),
        "positions_per_second": round(len(corpus) / elapsed, 3) if elapsed > 0.0 else 0.0,
        "moves_per_second": round(total_proposal_moves / elapsed, 3) if elapsed > 0.0 else 0.0,
        "proposal_move_count": total_proposal_moves,
        "verified_move_count": total_verified_moves,
        "parsed_backends": backends,
        "all_batches_cuda": all_cuda,
        "fallback_batches": fallback_batches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "batches": batches,
    }
