#!/usr/bin/env python3
"""Exact Python/C++/CUDA gate for pre-superko local point transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ugts_go19.constants import BLACK, PASS, WHITE  # noqa: E402
from ugts_go19.engine import (  # noqa: E402
    IllegalMove,
    apply_move,
    apply_move_detailed,
    legal_moves,
    play_sequence,
)
from ugts_go19.rules import Rules  # noqa: E402
from ugts_go19.state import State  # noqa: E402

STATUS_OCCUPIED = 1
STATUS_SUICIDE = 2
STATUS_CANDIDATE = 3
UINT64_MASK = (1 << 64) - 1
DEFAULT_TARGET_SLOTS = 25_000
SEEDS = (0x5EED19, 0xC0FFEE, 0x5070_19)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Case:
    identifier: int
    label: str
    rules: Rules
    state: State


@dataclass(slots=True)
class SplitMix64:
    state: int

    def next_uint64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & UINT64_MASK
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & UINT64_MASK
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & UINT64_MASK
        return value ^ (value >> 31)

    def choice(self, values: list[int]) -> int:
        return values[self.next_uint64() % len(values)]


def rules_for(size: int) -> Rules:
    return Rules(
        size=size,
        komi2=15 if size == 19 else 1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id=f"cuda-local-transition-{size}",
    )


def explicit_state(
    rules: Rules,
    board: bytes,
    *,
    to_play: int,
    seen: frozenset[bytes] | None = None,
    previous_board: bytes | None = None,
    passes: int = 0,
    ply: int = 0,
) -> State:
    state = State(
        board=board,
        to_play=to_play,
        passes=passes,
        seen=seen if seen is not None else frozenset((board,)),
        previous_board=previous_board,
        ply=ply,
    )
    state.validate(rules)
    return state


def adversarial_cases() -> list[tuple[str, Rules, State]]:
    result: list[tuple[str, Rules, State]] = []
    rules1 = rules_for(1)
    result.append(("one-point-suicide", rules1, State.initial(rules1)))

    rules2 = rules_for(2)
    result.append(("two-by-two-empty", rules2, State.initial(rules2)))

    rules3 = rules_for(3)
    initial3 = State.initial(rules3)
    single_capture_board = bytes(
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
        ]
    )
    result.append(
        (
            "single-capture",
            rules3,
            explicit_state(rules3, single_capture_board, to_play=WHITE),
        )
    )
    multi_capture_board = bytes(
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
        ]
    )
    result.append(
        (
            "multi-capture",
            rules3,
            explicit_state(rules3, multi_capture_board, to_play=BLACK),
        )
    )
    suicide_board = bytes(
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
        ]
    )
    result.append(
        (
            "suicide",
            rules3,
            explicit_state(rules3, suicide_board, to_play=BLACK),
        )
    )
    ring_board = bytes([WHITE, WHITE, WHITE, WHITE, 0, WHITE, WHITE, WHITE, WHITE])
    result.append(
        (
            "same-group-four-adjacencies",
            rules3,
            explicit_state(rules3, ring_board, to_play=BLACK),
        )
    )
    repeated_child = apply_move(initial3, 1, rules3)
    poisoned = explicit_state(
        rules3,
        initial3.board,
        to_play=BLACK,
        seen=initial3.seen | frozenset((repeated_child.board,)),
    )
    result.append(("same-board-clean-history", rules3, initial3))
    result.append(("same-board-poisoned-history", rules3, poisoned))
    result.append(("one-pass-nonterminal", rules3, apply_move(initial3, PASS, rules3)))
    snapback_before = play_sequence(initial3, [0, 3, 5, 4, 7, 2], rules3)
    snapback_after = apply_move(snapback_before, 1, rules3)
    result.append(("snapback-before", rules3, snapback_before))
    result.append(("snapback-after", rules3, snapback_after))

    rules5 = rules_for(5)
    initial5 = State.initial(rules5)
    ko_before = play_sequence(initial5, [1, 2, 3, 6, 20, 8, 24, 12], rules5)
    ko_after = apply_move(ko_before, 7, rules5)
    result.append(("ko-before", rules5, ko_before))
    result.append(("ko-after-psk", rules5, ko_after))
    four_capture = bytearray(25)
    for point in (7, 11, 13, 17):
        four_capture[point] = WHITE
    for point in (2, 6, 8, 10, 14, 16, 18, 22):
        four_capture[point] = BLACK
    result.append(
        (
            "four-distinct-groups",
            rules5,
            explicit_state(rules5, bytes(four_capture), to_play=BLACK),
        )
    )

    rules19 = rules_for(19)
    result.append(("nineteen-empty", rules19, State.initial(rules19)))
    max_capture = bytearray([WHITE] * 361)
    max_capture[360] = 0
    result.append(
        (
            "capture-360-tail-point",
            rules19,
            explicit_state(rules19, bytes(max_capture), to_play=BLACK),
        )
    )
    max_suicide = bytearray([BLACK] * 361)
    max_suicide[360] = 0
    result.append(
        (
            "suicide-361-group",
            rules19,
            explicit_state(rules19, bytes(max_suicide), to_play=BLACK),
        )
    )
    boundaries = bytearray(361)
    for point in (0, 63, 64, 127, 128, 319, 320, 360):
        boundaries[point] = BLACK
    for point in (1, 62, 65, 126, 129, 318, 321, 359):
        boundaries[point] = WHITE
    result.append(
        (
            "word-and-tail-boundaries",
            rules19,
            explicit_state(rules19, bytes(boundaries), to_play=WHITE),
        )
    )
    return result


def build_cases(target_slots: int) -> list[Case]:
    if target_slots < 1:
        raise ValueError("target_slots must be positive")
    raw = adversarial_cases()
    slot_count = sum(rules.size * rules.size for _, rules, _ in raw)
    episode = 0
    schedule = (2, 3, 5, 9, 19, 19, 19, 19)
    generators = [SplitMix64(seed) for seed in SEEDS]
    while slot_count < target_slots:
        size = schedule[episode % len(schedule)]
        rules = rules_for(size)
        state = State.initial(rules)
        generator = generators[episode % len(generators)]
        depth = min(12, max(2, size + 1))
        for ply in range(depth):
            points = [move for move in legal_moves(state, rules) if move != PASS]
            if not points:
                break
            state = apply_move(state, generator.choice(points), rules)
            raw.append((f"random-{episode}-{size}-{ply + 1}", rules, state))
            slot_count += size * size
            if slot_count >= target_slots:
                break
        episode += 1
    return [
        Case(identifier=index, label=label, rules=rules, state=state)
        for index, (label, rules, state) in enumerate(raw)
    ]


def encode_batch(cases: list[Case]) -> str:
    if not cases:
        raise AssertionError("cannot encode an empty batch")
    rules = cases[0].rules
    if any(case.rules != rules for case in cases):
        raise AssertionError("batch rules are not homogeneous")
    lines = [
        "UGTS_CUDA_LOCAL_INPUT_V1",
        f"RULES {rules.size} {rules.komi2} {rules.passes_to_end}",
        f"COUNT {len(cases)}",
    ]
    for case in cases:
        state = case.state
        state.validate(rules)
        previous = (
            state.previous_board.hex() if state.previous_board is not None else "-"
        )
        seen = ",".join(board.hex() for board in sorted(state.seen))
        lines.append(
            f"STATE {case.identifier} {state.to_play} {state.passes} {state.ply} "
            f"{state.board.hex()} {previous} {seen}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


def expected_slot(case: Case, move: int) -> tuple[str, dict[str, int]]:
    state = case.state
    rules = case.rules
    if state.board[move] != 0:
        return (
            f"SLOT {case.identifier} {move} {STATUS_OCCUPIED} 0 0 0 0 -",
            {"occupied": 1},
        )
    local_state = State(
        board=state.board,
        to_play=state.to_play,
        passes=state.passes,
        seen=frozenset((state.board,)),
        previous_board=None,
        ply=state.ply,
    )
    try:
        local = apply_move_detailed(local_state, move, rules)
    except IllegalMove:
        try:
            apply_move_detailed(state, move, rules)
        except IllegalMove:
            pass
        else:
            raise AssertionError("global CPU accepted a local suicide")
        return (
            f"SLOT {case.identifier} {move} {STATUS_SUICIDE} 0 0 0 0 -",
            {"suicides": 1},
        )

    repeated = local.state.board in state.seen
    globally_legal = not repeated
    try:
        global_result = apply_move_detailed(state, move, rules)
    except IllegalMove:
        if not repeated:
            raise AssertionError("global CPU rejected a non-repeating candidate")
    else:
        if repeated:
            raise AssertionError("global CPU accepted an exact PSK repetition")
        if (
            global_result.state.board != local.state.board
            or global_result.captured != local.captured
            or global_result.self_captured != local.self_captured
        ):
            raise AssertionError("Python local/global transition mismatch")
    return (
        f"SLOT {case.identifier} {move} {STATUS_CANDIDATE} "
        f"{local.captured} {local.self_captured} {int(repeated)} "
        f"{int(globally_legal)} {local.state.board.hex()}",
        {
            "local_candidates": 1,
            "superko_rejections": int(repeated),
            "globally_legal": int(globally_legal),
        },
    )


def expected_records(cases: list[Case]) -> tuple[list[str], dict[str, int]]:
    records: list[str] = []
    totals = {
        "occupied": 0,
        "suicides": 0,
        "local_candidates": 0,
        "superko_rejections": 0,
        "globally_legal": 0,
    }
    for case in cases:
        for move in range(case.rules.size * case.rules.size):
            record, delta = expected_slot(case, move)
            records.append(record)
            for key, value in delta.items():
                totals[key] += value
    return records, totals


def run_evaluator(evaluator: Path, protocol: str, mode: str) -> list[str]:
    process = subprocess.run(
        [str(evaluator), "--stream", mode],
        input=protocol,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"evaluator {mode} failed with {process.returncode}: "
            f"{process.stderr.strip()}"
        )
    return process.stdout.splitlines()


def parse_and_compare(
    lines: list[str], cases: list[Case], mode: str
) -> tuple[str, str, dict[str, int]]:
    cursor = 0

    def take() -> str:
        nonlocal cursor
        if cursor >= len(lines):
            raise AssertionError("truncated evaluator output")
        value = lines[cursor]
        cursor += 1
        return value

    if take() != "UGTS_CUDA_LOCAL_OUTPUT_V1":
        raise AssertionError("unexpected evaluator output header")
    device_fields = take().split()
    if len(device_fields) != 4 or device_fields[0] != "DEVICE":
        raise AssertionError("invalid DEVICE record")
    compute_capability = f"{int(device_fields[1])}.{int(device_fields[2])}"
    try:
        device_name = bytes.fromhex(device_fields[3]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise AssertionError("invalid device name") from error
    if take() != f"MODE {mode}":
        raise AssertionError("stream mode mismatch")

    records, totals = expected_records(cases)
    for expected in records:
        actual = take()
        if actual != expected:
            raise AssertionError(
                f"exact Python/C++/CUDA mismatch:\n{actual}\n{expected}"
            )
    summary_fields = take().split()
    if len(summary_fields) != 11 or summary_fields[0] != "SUMMARY":
        raise AssertionError("invalid SUMMARY record")
    size = cases[0].rules.size
    slots = len(cases) * size * size
    words = (size * size + 63) // 64
    expected_summary = [
        "SUMMARY",
        str(len(cases)),
        str(slots),
        str(totals["occupied"]),
        str(totals["suicides"]),
        str(totals["local_candidates"]),
        str(totals["superko_rejections"]),
        str(totals["globally_legal"]),
        str(totals["local_candidates"] * 2 * words),
        "10",
        "0",
    ]
    if summary_fields != expected_summary:
        raise AssertionError(
            f"summary mismatch: {summary_fields!r} != {expected_summary!r}"
        )
    if take() != "END" or cursor != len(lines):
        raise AssertionError("invalid evaluator terminator")
    totals["slots"] = slots
    totals["compared_child_words"] = totals["local_candidates"] * 2 * words
    return device_name, compute_capability, totals


def run_guard_evaluator(
    evaluator: Path, expected_compute_capability: str
) -> dict[str, object]:
    outputs: list[str] = []
    for _ in range(2):
        process = subprocess.run(
            [str(evaluator)],
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"guard evaluator failed with {process.returncode}: "
                f"{process.stderr.strip()}"
            )
        outputs.append(process.stdout.strip())
    if outputs[0] != outputs[1]:
        raise AssertionError("whole-run low-level guard output is nondeterministic")
    parsed = json.loads(outputs[0])
    expected = {
        "aliased_input_launches": 1,
        "canary_checks": 100,
        "child_word_comparisons": 21_660,
        "compute_capability": expected_compute_capability,
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
        "root_status": "UNKNOWN",
    }
    if not isinstance(parsed, dict) or parsed != expected:
        raise AssertionError("low-level guard summary failed its exact invariants")
    parsed["repeat_process_runs"] = 2
    return parsed


def run_gate(
    evaluator: Path, guard_evaluator: Path, target_slots: int
) -> dict[str, object]:
    cases = build_cases(target_slots)
    groups: dict[tuple[int, int, int], list[Case]] = {}
    for case in cases:
        key = (case.rules.size, case.rules.komi2, case.rules.passes_to_end)
        groups.setdefault(key, []).append(case)

    corpus = hashlib.sha256()
    aggregate = {
        "occupied": 0,
        "suicides": 0,
        "local_candidates": 0,
        "superko_rejections": 0,
        "globally_legal": 0,
        "slots": 0,
        "compared_child_words": 0,
    }
    device_name: str | None = None
    compute_capability: str | None = None
    process_runs = 0
    negative_checks = 0
    for key in sorted(groups):
        batch = groups[key]
        protocol = encode_batch(batch)
        corpus.update(protocol.encode("ascii"))
        default_lines = run_evaluator(evaluator, protocol, "default")
        default_device, default_capability, totals = parse_and_compare(
            default_lines, batch, "default"
        )
        nondefault_lines = run_evaluator(evaluator, protocol, "nondefault")
        nondefault_device, nondefault_capability, repeat_totals = parse_and_compare(
            nondefault_lines, batch, "nondefault"
        )
        if totals != repeat_totals:
            raise AssertionError("stream-mode summaries differ")
        normalized_default = [
            "MODE normalized" if line == "MODE default" else line
            for line in default_lines
        ]
        normalized_nondefault = [
            "MODE normalized" if line == "MODE nondefault" else line
            for line in nondefault_lines
        ]
        if normalized_default != normalized_nondefault:
            raise AssertionError("stream-mode output is nondeterministic")
        if (
            default_device != nondefault_device
            or default_capability != nondefault_capability
        ):
            raise AssertionError("device identity changed between stream modes")
        if device_name is None:
            device_name = default_device
            compute_capability = default_capability
        elif device_name != default_device or compute_capability != default_capability:
            raise AssertionError("device identity changed between board-size batches")
        for field in aggregate:
            aggregate[field] += totals[field]
        process_runs += 2
        negative_checks += 20

    if aggregate["slots"] < target_slots:
        raise AssertionError("gate did not reach its requested point-slot target")
    production_sources = (
        "cpp/cuda/packed_kernels.cu",
        "cpp/cuda/packed_kernels.cuh",
        "cpp/cuda/cuda_verified_expander.cu",
        "cpp/include/ugts_go19/cuda_verified_expander.hpp",
    )
    gate_sources = (
        "cpp/tests/cuda_local_transition_eval.cu",
        "cpp/tests/cuda_local_transition_guards.cu",
        "cpp/tests/cuda_local_transition_parity.py",
    )
    reference_sources = (
        "cpp/include/ugts_go19/go_state.hpp",
        "cpp/src/go_state.cpp",
        "src/ugts_go19/constants.py",
        "src/ugts_go19/engine.py",
        "src/ugts_go19/rules.py",
        "src/ugts_go19/state.py",
    )
    return {
        "adversarial_cases": len(adversarial_cases()),
        "board_sizes": sorted({case.rules.size for case in cases}),
        "compute_capability": compute_capability,
        "corpus_sha256": corpus.hexdigest(),
        "cpp_cuda_compared_child_words_across_streams": (
            aggregate["compared_child_words"] * 2
        ),
        "cpp_cuda_recomputed_point_slots_across_streams": aggregate["slots"] * 2,
        "device_name": device_name,
        "dense_device_bytes_per_19x19_state": 36_606,
        "format": "ugts-go19-cuda-local-transition-parity-v1",
        "gate_source_sha256": {
            relative: file_sha256(ROOT / relative) for relative in gate_sources
        },
        "low_level_guards": run_guard_evaluator(
            guard_evaluator, str(compute_capability)
        ),
        "maximum_capture_fixture_stones": 360,
        "mismatches": 0,
        "negative_argument_checks_across_processes": negative_checks,
        "nonterminal_one_pass_states": sum(case.state.passes == 1 for case in cases),
        "per_stream_globally_legal_children": aggregate["globally_legal"],
        "per_stream_local_candidates": aggregate["local_candidates"],
        "per_stream_occupied_slots": aggregate["occupied"],
        "per_stream_suicide_slots": aggregate["suicides"],
        "per_stream_superko_rejections": aggregate["superko_rejections"],
        "per_stream_verified_point_slots": aggregate["slots"],
        "production_source_sha256": {
            relative: file_sha256(ROOT / relative) for relative in production_sources
        },
        "parity_evaluator_process_runs": process_runs,
        "python_cuda_compared_point_slots_across_streams": aggregate["slots"] * 2,
        "reference_source_sha256": {
            relative: file_sha256(ROOT / relative) for relative in reference_sources
        },
        "root_status": "UNKNOWN",
        "scope": "pre-superko-local-point-transitions; CPU-authoritative",
        "stream_modes": ["default", "nondefault", "dual-reverse-sync"],
        "unique_corpus_point_slots": aggregate["slots"],
        "unique_corpus_states": len(cases),
        "verified_point_slots_across_streams": aggregate["slots"] * 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator", required=True, type=Path)
    parser.add_argument("--guard-evaluator", required=True, type=Path)
    parser.add_argument("--target-slots", type=int, default=DEFAULT_TARGET_SLOTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.evaluator.is_file():
        raise FileNotFoundError(f"evaluator not found: {args.evaluator}")
    if not args.guard_evaluator.is_file():
        raise FileNotFoundError(f"guard evaluator not found: {args.guard_evaluator}")
    result = run_gate(
        args.evaluator.resolve(), args.guard_evaluator.resolve(), args.target_slots
    )
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - standalone gate fails closed.
        print(f"cuda_local_transition_parity: {error}", file=sys.stderr)
        raise SystemExit(1) from error
