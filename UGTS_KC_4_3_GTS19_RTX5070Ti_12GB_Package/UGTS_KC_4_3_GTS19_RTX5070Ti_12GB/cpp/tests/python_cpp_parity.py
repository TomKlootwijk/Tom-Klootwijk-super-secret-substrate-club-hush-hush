#!/usr/bin/env python3
"""Deterministic Python/C++ differential corpus for UGTS_TRACE_V1."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ugts_go19.constants import BLACK, PASS, WHITE  # noqa: E402
from ugts_go19.digests import canonical_proof_state_payload  # noqa: E402
from ugts_go19.engine import (  # noqa: E402
    apply_move,
    apply_move_detailed,
    legal_moves,
    play_sequence,
)
from ugts_go19.rules import Rules  # noqa: E402
from ugts_go19.score import area_score2  # noqa: E402
from ugts_go19.state import State  # noqa: E402

PROTOCOL = "UGTS_TRACE_V1"
DEFAULT_SEEDS = (0x5EED19, 0xC0FFEE)
UINT64_MASK = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class Case:
    label: str
    rules: Rules
    state: State


@dataclass(frozen=True, slots=True)
class PreparedCase:
    case_id: int
    case: Case
    legal: tuple[int, ...]


@dataclass(slots=True)
class SplitMix64:
    """Small specified PRNG so corpus bytes do not depend on Python's RNG."""

    state: int

    def next_uint64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & UINT64_MASK
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & UINT64_MASK
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & UINT64_MASK
        return value ^ (value >> 31)

    def choice(self, values: list[int]) -> int:
        if not values:
            raise IndexError("cannot choose from an empty sequence")
        return values[self.next_uint64() % len(values)]


def parity_rules(size: int) -> Rules:
    return Rules(
        size=size,
        komi2=15 if size == 19 else 1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id=f"cpp-parity-{size}",
    )


def explicit_state(
    rules: Rules,
    board_values: list[int],
    *,
    to_play: int,
    seen_boards: tuple[bytes, ...] | None = None,
    previous_board: bytes | None = None,
    passes: int = 0,
    ply: int = 0,
) -> State:
    board = bytes(board_values)
    state = State(
        board=board,
        to_play=to_play,
        passes=passes,
        seen=frozenset(seen_boards if seen_boards is not None else (board,)),
        previous_board=previous_board,
        ply=ply,
    )
    state.validate(rules)
    return state


def focused_cases() -> list[Case]:
    rules = parity_rules(3)
    empty = bytes(9)
    initial = State.initial(rules)

    capture = explicit_state(
        rules,
        [
            0,
            0,
            0,
            WHITE,
            BLACK,
            WHITE,
            0,
            WHITE,
            0,
        ],
        to_play=WHITE,
        seen_boards=(empty, bytes([0, 0, 0, WHITE, BLACK, WHITE, 0, WHITE, 0])),
    )
    suicide = explicit_state(
        rules,
        [
            0,
            WHITE,
            0,
            WHITE,
            0,
            WHITE,
            0,
            WHITE,
            0,
        ],
        to_play=BLACK,
    )
    multi_capture = explicit_state(
        rules,
        [
            BLACK,
            WHITE,
            BLACK,
            WHITE,
            0,
            0,
            BLACK,
            0,
            0,
        ],
        to_play=BLACK,
    )

    repeated_child = apply_move(initial, 1, rules)
    superko = State(
        board=initial.board,
        to_play=initial.to_play,
        passes=0,
        seen=initial.seen | frozenset((repeated_child.board,)),
        previous_board=None,
        ply=0,
    )
    one_pass = apply_move(initial, PASS, rules)
    terminal = apply_move(one_pass, PASS, rules)

    # Reachable minimized tactical traces. These exercise edge topology, a true
    # PSK ko recapture, and snapback rather than only synthetic board fixtures.
    edge_capture = play_sequence(initial, [0, 1, 8], rules)

    rules5 = parity_rules(5)
    ko_before = play_sequence(
        State.initial(rules5), [1, 2, 3, 6, 20, 8, 24, 12], rules5
    )
    ko_capture = apply_move_detailed(ko_before, 7, rules5)
    ko_after = ko_capture.state

    snapback_before = play_sequence(initial, [0, 3, 5, 4, 7, 2], rules)
    snapback_capture = apply_move_detailed(snapback_before, 1, rules)
    snapback_after = snapback_capture.state
    snapback_recapture = apply_move_detailed(snapback_after, 2, rules)

    if apply_move_detailed(capture, 1, rules).captured != 1:
        raise AssertionError("focused single-capture state is not exercising capture")
    if apply_move_detailed(multi_capture, 4, rules).captured != 2:
        raise AssertionError("focused multi-capture state is not exercising capture")
    if 4 in legal_moves(suicide, rules):
        raise AssertionError("focused suicide point unexpectedly legal")
    if 1 in legal_moves(superko, rules):
        raise AssertionError("focused superko point unexpectedly legal")
    if not terminal.is_terminal(rules):
        raise AssertionError("focused terminal state is not terminal")
    if apply_move_detailed(edge_capture, 3, rules).captured != 1:
        raise AssertionError("focused edge capture is not exercising capture")
    if ko_capture.captured != 1 or 2 in legal_moves(ko_after, rules5):
        raise AssertionError("focused reachable ko is not rejecting recapture")
    if snapback_capture.captured != 1 or snapback_recapture.captured != 2:
        raise AssertionError("focused reachable snapback is not a snapback")

    rules19 = parity_rules(19)
    return [
        Case("initial-3", rules, initial),
        Case("single-capture", rules, capture),
        Case("multi-capture", rules, multi_capture),
        Case("suicide-rejection", rules, suicide),
        Case("superko-rejection", rules, superko),
        Case("one-pass", rules, one_pass),
        Case("two-pass-terminal", rules, terminal),
        Case("reachable-edge-capture", rules, edge_capture),
        Case("reachable-ko-before", rules5, ko_before),
        Case("reachable-ko-after", rules5, ko_after),
        Case("reachable-snapback-before", rules, snapback_before),
        Case("reachable-snapback-after", rules, snapback_after),
        Case("initial-19", rules19, State.initial(rules19)),
    ]


def randomized_cases(seeds: tuple[int, ...]) -> list[Case]:
    cases: list[Case] = []
    # (size, plies, sample interval) keeps CTest quick while covering topology
    # and packed 19x19-sized state/history payloads.
    specifications = ((3, 18, 3), (5, 16, 4), (9, 10, 5), (19, 4, 4))
    for seed in seeds:
        for size, plies, sample_interval in specifications:
            rules = parity_rules(size)
            state = State.initial(rules)
            generator = SplitMix64((seed << 8) ^ size)
            forced_pass_ply = max(1, plies // 3)
            for step in range(plies):
                moves = legal_moves(state, rules)
                if not moves:
                    break
                point_moves = [move for move in moves if move != PASS]
                if step == forced_pass_ply or not point_moves:
                    move = PASS
                else:
                    move = generator.choice(point_moves)
                state = apply_move(state, move, rules)
                if (step + 1) % sample_interval == 0:
                    cases.append(
                        Case(f"random-{seed:#x}-{size}-{step + 1}", rules, state)
                    )
                if state.is_terminal(rules):
                    break
    return cases


def campaign_cases(seeds: tuple[int, ...]) -> Iterator[Case]:
    """Yield an unbounded deterministic stream of shallow reachable states."""

    # Most transitions use small/medium boards for throughput. Every schedule
    # cycle still contains 19x19 states, while their depth is capped to keep the
    # exact raw history payload bounded.
    schedule = ((5, 8),) * 52 + ((9, 8),) * 10 + ((3, 8),) + ((19, 2),)
    generators = [
        SplitMix64((seed ^ 0xD1FF3A5E5EED0001) & UINT64_MASK) for seed in seeds
    ]
    episode = 0
    while True:
        size, depth = schedule[episode % len(schedule)]
        generator = generators[episode % len(generators)]
        rules = parity_rules(size)
        state = State.initial(rules)
        for step in range(depth):
            moves = legal_moves(state, rules)
            point_moves = [move for move in moves if move != PASS]
            if step == 2 and depth >= 4:
                move = PASS
            elif point_moves:
                move = generator.choice(point_moves)
            else:
                move = PASS
            state = apply_move(state, move, rules)
            yield Case(
                f"campaign-episode={episode}-seed={seeds[episode % len(seeds)]:#x}"
                f"-size={size}-ply={step + 1}",
                rules,
                state,
            )
            if state.is_terminal(rules):
                break
        episode += 1


def encode_case(case_id: int, case: Case) -> str:
    state = case.state
    rules = case.rules
    state.validate(rules)
    previous = state.previous_board.hex() if state.previous_board is not None else "-"
    seen = ",".join(token.hex() for token in sorted(state.seen)) or "-"
    return "|".join(
        (
            PROTOCOL,
            str(case_id),
            str(rules.size),
            str(rules.komi2),
            "1" if rules.allow_suicide else "0",
            str(rules.passes_to_end),
            str(state.to_play),
            str(state.passes),
            str(state.ply),
            state.board.hex(),
            previous,
            seen,
        )
    )


def state_record(
    case_id: int, state: State, rules: Rules, legal: tuple[int, ...]
) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "kind": "state",
        "id": case_id,
        "terminal": state.is_terminal(rules),
        "score2": area_score2(state.board, rules),
        "canonical_state": canonical_proof_state_payload(state, rules),
        "legal": list(legal),
    }


def move_record(
    case_id: int, move: int, state: State, rules: Rules
) -> dict[str, Any]:
    result = apply_move_detailed(state, move, rules)
    child = result.state
    return {
        "protocol": PROTOCOL,
        "kind": "move",
        "id": case_id,
        "move": move,
        "board": child.board.hex(),
        "captured": result.captured,
        "self_captured": result.self_captured,
        "to_play": child.to_play,
        "passes": child.passes,
        "previous_board": (
            child.previous_board.hex() if child.previous_board is not None else None
        ),
        "seen": [token.hex() for token in sorted(child.seen)],
        "canonical_state": canonical_proof_state_payload(child, rules),
        "ply": child.ply,
        "terminal": child.is_terminal(rules),
        "score2": area_score2(child.board, rules),
    }


def prepare_case(case_id: int, case: Case) -> PreparedCase:
    return PreparedCase(case_id, case, tuple(legal_moves(case.state, case.rules)))


def build_chunk(
    cases: list[PreparedCase],
) -> tuple[str, list[dict[str, Any]], list[str], int]:
    input_lines: list[str] = []
    expected: list[dict[str, Any]] = []
    contexts: list[str] = []
    transitions = 0
    for prepared in cases:
        case_id = prepared.case_id
        case = prepared.case
        input_lines.append(encode_case(case_id, case))
        summary = state_record(case_id, case.state, case.rules, prepared.legal)
        expected.append(summary)
        contexts.append(case.label)
        for move in summary["legal"]:
            expected.append(move_record(case_id, move, case.state, case.rules))
            contexts.append(f"{case.label}:move={move}")
            transitions += 1
    payload = "\n".join(input_lines) + "\n"
    return payload, expected, contexts, transitions


def parse_output(stdout: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(stdout.splitlines(), start=1):
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"invalid evaluator JSON on output line {line_number}: {error}"
            ) from error
        if not isinstance(record, dict):
            raise RuntimeError(f"non-object evaluator JSON on line {line_number}")
        records.append(record)
    return records


def compare_records(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]], contexts: list[str]
) -> None:
    if len(actual) != len(expected):
        raise AssertionError(
            f"record count mismatch: C++={len(actual)} Python={len(expected)}"
        )
    for index, (expected_record, actual_record) in enumerate(zip(expected, actual)):
        if actual_record != expected_record:
            detail = {
                "context": contexts[index],
                "record_index": index,
                "expected": expected_record,
                "actual": actual_record,
            }
            raise AssertionError(
                "Python/C++ semantic mismatch: "
                + json.dumps(detail, sort_keys=True, separators=(",", ":"))
            )


def evaluate_chunk(
    evaluator: Path,
    payload: str,
    expected: list[dict[str, Any]],
    contexts: list[str],
) -> None:
    try:
        process = subprocess.run(
            [str(evaluator)],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"native trace evaluator timed out: {error}") from error
    if process.returncode != 0:
        raise RuntimeError(
            f"native trace evaluator failed with {process.returncode}:\n"
            f"{process.stderr}"
        )
    if process.stderr.strip():
        raise RuntimeError(f"native trace evaluator wrote stderr:\n{process.stderr}")
    actual = parse_output(process.stdout)
    compare_records(expected, actual, contexts)


def parse_seed(value: str) -> int:
    return int(value, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator", required=True, type=Path)
    parser.add_argument(
        "--seed",
        action="append",
        type=parse_seed,
        help="fixed random seed; repeat to replace the default seed set",
    )
    parser.add_argument(
        "--target-transitions",
        type=int,
        help="campaign until at least this many complete legal transitions compare",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=10_000,
        help="approximate maximum transitions per evaluator subprocess",
    )
    parser.add_argument("--output", type=Path, help="write JSON evidence summary")
    args = parser.parse_args()

    if args.target_transitions is not None and args.target_transitions < 1:
        parser.error("--target-transitions must be positive")
    if args.chunk_size < 1:
        parser.error("--chunk-size must be positive")

    seeds = tuple(args.seed) if args.seed else DEFAULT_SEEDS
    focused = focused_cases()
    if args.target_transitions is None:
        selected_cases: Iterator[Case] = iter(focused + randomized_cases(seeds))
        mode = "quick"
    else:
        mode = "campaign"

        def campaign_with_focused() -> Iterator[Case]:
            yield from focused
            yield from campaign_cases(seeds)

        selected_cases = campaign_with_focused()

    pending: list[PreparedCase] = []
    pending_transitions = 0
    corpus_digest = hashlib.sha256()
    comparisons = 0
    field_comparisons = 0
    states = 0
    transitions = 0
    chunks = 0
    case_id = 0
    cases_by_size: dict[int, int] = {}
    max_seen_boards = 0
    started = time.perf_counter()

    def run_pending() -> None:
        nonlocal pending, pending_transitions
        nonlocal comparisons, field_comparisons, states, transitions, chunks
        nonlocal max_seen_boards
        if not pending:
            return
        payload, expected, contexts, chunk_transitions = build_chunk(pending)
        evaluate_chunk(args.evaluator, payload, expected, contexts)
        corpus_digest.update(payload.encode("ascii"))
        comparisons += len(expected)
        field_comparisons += len(pending) * 4 + chunk_transitions * 11
        states += len(pending)
        transitions += chunk_transitions
        chunks += 1
        for prepared in pending:
            size = prepared.case.rules.size
            cases_by_size[size] = cases_by_size.get(size, 0) + 1
            max_seen_boards = max(max_seen_boards, len(prepared.case.state.seen))
        pending = []
        pending_transitions = 0

    try:
        for case in selected_cases:
            prepared = prepare_case(case_id, case)
            case_id += 1
            pending.append(prepared)
            pending_transitions += len(prepared.legal)
            reached_chunk = pending_transitions >= args.chunk_size
            reached_target = (
                args.target_transitions is not None
                and transitions + pending_transitions >= args.target_transitions
            )
            if reached_chunk or reached_target:
                run_pending()
                if args.target_transitions is not None and (
                    chunks == 1 or chunks % 10 == 0 or reached_target
                ):
                    print(
                        json.dumps(
                            {
                                "chunks": chunks,
                                "states": states,
                                "transitions": transitions,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                if reached_target:
                    break
        run_pending()
    except (AssertionError, RuntimeError) as error:
        raise SystemExit(str(error)) from error

    elapsed_seconds = time.perf_counter() - started
    target = args.target_transitions if args.target_transitions is not None else transitions
    summary = {
        "cases_by_size": {str(key): value for key, value in sorted(cases_by_size.items())},
        "chunk_size": args.chunk_size,
        "chunks": chunks,
        "comparisons": comparisons,
        "corpus_sha256": corpus_digest.hexdigest(),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "evidence_format": "UGTS-M1-PARITY-EVIDENCE-v1",
        "field_comparisons": field_comparisons,
        "generator": "splitmix64-v1-shallow-reachable-psk",
        "hash_role": "corpus evidence only; exact raw fields establish equality",
        "max_seen_boards": max_seen_boards,
        "mismatches": 0,
        "mode": mode,
        "protocol": PROTOCOL,
        "root_status": "UNKNOWN",
        "seeds": list(seeds),
        "states": states,
        "target_met": transitions >= target,
        "target_transitions": target,
        "transitions": transitions,
        "transitions_per_second": round(transitions / elapsed_seconds, 3),
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
