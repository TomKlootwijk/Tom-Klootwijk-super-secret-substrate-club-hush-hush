#!/usr/bin/env python3
"""Exact Python/C++/CUDA parity gate for the empty-mask kernel."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MASK64 = (1 << 64) - 1
TAIL_19X19 = (1 << 41) - 1
EMPTY_MASK_THREADS_PER_BLOCK = 256
EMPTY_MASK_MAXIMUM_BLOCKS = 65_535
PRODUCTION_GRID_CAPACITY_WORDS = (
    EMPTY_MASK_THREADS_PER_BLOCK * EMPTY_MASK_MAXIMUM_BLOCKS
)
GRID_STRIDE_EXTRA_WORDS = 257
GRID_STRIDE_REGRESSION_WORDS = (
    PRODUCTION_GRID_CAPACITY_WORDS + GRID_STRIDE_EXTRA_WORDS
)


@dataclass(frozen=True)
class Fixture:
    identifier: str
    states: int
    words_per_state: int
    tail_mask: int
    mode: str
    black: tuple[int, ...]
    white: tuple[int, ...]

    @property
    def words(self) -> int:
        return self.states * self.words_per_state


@dataclass(frozen=True)
class EvaluatorSummary:
    device_name: str
    compute_capability: str
    emitted_words: int
    protocol_output_comparisons: int
    negative_argument_checks: int
    grid_stride_launches: int
    grid_stride_words: int
    aliased_input_launches: int
    input_immutability_words: int
    canary_checks: int


def _splitmix64_words(seed: int, count: int) -> list[int]:
    words: list[int] = []
    value = seed & MASK64
    for _ in range(count):
        value = (value + 0x9E3779B97F4A7C15) & MASK64
        mixed = value
        mixed = ((mixed ^ (mixed >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        mixed = ((mixed ^ (mixed >> 27)) * 0x94D049BB133111EB) & MASK64
        words.append((mixed ^ (mixed >> 31)) & MASK64)
    return words


def _random_fixture(
    identifier: str,
    states: int,
    words_per_state: int,
    tail_mask: int,
    mode: str,
    seed: int,
) -> Fixture:
    values = _splitmix64_words(seed, states * words_per_state * 2)
    return Fixture(
        identifier=identifier,
        states=states,
        words_per_state=words_per_state,
        tail_mask=tail_mask,
        mode=mode,
        black=tuple(values[0::2]),
        white=tuple(values[1::2]),
    )


def _nineteen_by_nineteen_fixture() -> Fixture:
    states = 8
    words_per_state = 6
    black = [0] * (states * words_per_state)
    white = [0] * (states * words_per_state)

    def set_point(plane: list[int], state: int, point: int) -> None:
        plane[state * words_per_state + point // 64] |= 1 << (point % 64)

    # State 0 is completely empty. States 1 and 2 are monochrome valid boards.
    for word in range(words_per_state - 1):
        black[1 * words_per_state + word] = MASK64
        white[2 * words_per_state + word] = MASK64
    black[1 * words_per_state + 5] = TAIL_19X19
    white[2 * words_per_state + 5] = TAIL_19X19

    # State 3 is a valid checkerboard and pins the point-to-bit convention.
    for point in range(361):
        set_point(black if point % 2 == 0 else white, 3, point)

    # State 4 pins all 64-bit boundaries, including both ends of the tail word.
    for point in (0, 63, 64, 319, 320, 360):
        set_point(black, 4, point)
    for point in (1, 62, 65, 318, 321, 359):
        set_point(white, 4, point)

    # State 5 deliberately overlaps colors. The occupancy primitive is defined
    # as complement-of-union even for bitplanes that are not legal Go boards.
    for word in range(words_per_state):
        black[5 * words_per_state + word] = 0x0F0F0F0F0F0F0F0F
        white[5 * words_per_state + word] = 0x00FF00FF00FF00FF

    # State 6 has dirty unused bits in the final word. They must never leak into
    # the output above point 360.
    black[6 * words_per_state + 5] = MASK64 ^ TAIL_19X19
    white[6 * words_per_state + 5] = (1 << 63) | 1

    # State 7 combines alternating patterns and dirty tail bits.
    for word in range(words_per_state):
        black[7 * words_per_state + word] = (
            0xAAAAAAAAAAAAAAAA if word % 2 == 0 else 0x5555555555555555
        )
        white[7 * words_per_state + word] = (
            0x1111111111111111 if word % 2 == 0 else 0x8888888888888888
        )

    return Fixture(
        identifier="adversarial_19x19",
        states=states,
        words_per_state=words_per_state,
        tail_mask=TAIL_19X19,
        mode="default",
        black=tuple(black),
        white=tuple(white),
    )


def _ordered_fixture() -> Fixture:
    states = 257
    black = tuple((~index) & MASK64 for index in range(states))
    white = (0,) * states
    return Fixture(
        identifier="ordered_257x1",
        states=states,
        words_per_state=1,
        tail_mask=MASK64,
        mode="dual",
        black=black,
        white=white,
    )


def fixtures() -> tuple[Fixture, ...]:
    return (
        _nineteen_by_nineteen_fixture(),
        _random_fixture("tail_zero_1x3", 1, 3, 0, "nondefault", 0x1001),
        _random_fixture(
            "tail_high_low_2x2", 2, 2, 0x8000000000000001, "default", 0x2002
        ),
        _random_fixture(
            "tail_alternating_3x5", 3, 5, 0xAAAAAAAAAAAAAAAA, "nondefault", 0x3003
        ),
        _random_fixture("dual_42x6", 42, 6, TAIL_19X19, "dual", 0x4206),
        _random_fixture("dual_43x6", 43, 6, TAIL_19X19, "dual", 0x4306),
        _random_fixture("dual_85x6", 85, 6, TAIL_19X19, "dual", 0x8506),
        _random_fixture("dual_86x6", 86, 6, TAIL_19X19, "dual", 0x8606),
        _random_fixture("block_255x1", 255, 1, MASK64, "default", 0x2551),
        _random_fixture("block_256x1", 256, 1, MASK64, "nondefault", 0x2561),
        _ordered_fixture(),
        _random_fixture("dual_generic_7x7", 7, 7, 0x0123456789ABCDEF, "dual", 0x7007),
        _random_fixture("large_4096x1", 4096, 1, MASK64, "default", 0x40961),
    )


def expected_words(fixture: Fixture) -> tuple[int, ...]:
    output: list[int] = []
    for index, (black, white) in enumerate(
        zip(fixture.black, fixture.white, strict=True)
    ):
        value = (~(black | white)) & MASK64
        if index % fixture.words_per_state == fixture.words_per_state - 1:
            value &= fixture.tail_mask
        output.append(value)
    return tuple(output)


def encode_input(cases: tuple[Fixture, ...]) -> str:
    lines = ["UGTS_EMPTY_MASK_INPUT_V1", str(len(cases))]
    for fixture in cases:
        if fixture.words != len(fixture.black) or fixture.words != len(fixture.white):
            raise AssertionError(f"invalid local fixture shape: {fixture.identifier}")
        lines.append(
            "CASE "
            f"{fixture.identifier} {fixture.states} {fixture.words_per_state} "
            f"{fixture.tail_mask:016x} {fixture.mode}"
        )
        lines.extend(
            f"WORD {black:016x} {white:016x}"
            for black, white in zip(fixture.black, fixture.white, strict=True)
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


def _run_evaluator(evaluator: Path, protocol: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(evaluator)],
        input=protocol,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def parse_and_verify_output(
    output: str, cases: tuple[Fixture, ...]
) -> EvaluatorSummary:
    lines = output.splitlines()
    cursor = 0

    def take() -> str:
        nonlocal cursor
        if cursor >= len(lines):
            raise AssertionError("truncated evaluator output")
        line = lines[cursor]
        cursor += 1
        return line

    if take() != "UGTS_EMPTY_MASK_OUTPUT_V2":
        raise AssertionError("unexpected evaluator output header")
    device_fields = take().split()
    if len(device_fields) != 4 or device_fields[0] != "DEVICE":
        raise AssertionError("invalid DEVICE record")
    major = int(device_fields[1])
    minor = int(device_fields[2])
    if major < 1 or minor < 0:
        raise AssertionError("invalid CUDA compute capability")
    try:
        device_name = bytes.fromhex(device_fields[3]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise AssertionError("invalid CUDA device-name encoding") from error
    if not device_name:
        raise AssertionError("empty CUDA device name")

    compared_words = 0
    for fixture in cases:
        expected_case = (
            f"CASE {fixture.identifier} {fixture.states} {fixture.words_per_state} "
            f"{fixture.tail_mask:016x} {fixture.mode}"
        )
        if take() != expected_case:
            raise AssertionError(
                f"case metadata/order mismatch for {fixture.identifier}"
            )
        for index, expected in enumerate(expected_words(fixture)):
            expected_result = f"RESULT {fixture.identifier} {index} {expected:016x}"
            if take() != expected_result:
                raise AssertionError(
                    f"exact Python/CUDA mismatch for {fixture.identifier} word {index}"
                )
            compared_words += 1

    protocol_output_comparisons = compared_words * 2
    negative_argument_checks = 6
    grid_stride_launches = 1
    aliased_input_launches = 1
    input_immutability_words = compared_words * 4 + GRID_STRIDE_REGRESSION_WORDS
    canary_checks = len(cases) * 12 + 4
    expected_summary = (
        f"SUMMARY {len(cases)} {compared_words} "
        f"{protocol_output_comparisons} 0 0 0 {negative_argument_checks} "
        f"{grid_stride_launches} {GRID_STRIDE_REGRESSION_WORDS} "
        f"{aliased_input_launches} {input_immutability_words} {canary_checks}"
    )
    if take() != expected_summary:
        raise AssertionError("invalid evaluator summary")
    if take() != "END" or cursor != len(lines):
        raise AssertionError("invalid evaluator output terminator")
    return EvaluatorSummary(
        device_name=device_name,
        compute_capability=f"{major}.{minor}",
        emitted_words=compared_words,
        protocol_output_comparisons=protocol_output_comparisons,
        negative_argument_checks=negative_argument_checks,
        grid_stride_launches=grid_stride_launches,
        grid_stride_words=GRID_STRIDE_REGRESSION_WORDS,
        aliased_input_launches=aliased_input_launches,
        input_immutability_words=input_immutability_words,
        canary_checks=canary_checks,
    )


def run_gate(evaluator: Path) -> dict[str, object]:
    cases = fixtures()
    protocol = encode_input(cases)
    first = _run_evaluator(evaluator, protocol)
    if first.returncode != 0:
        raise RuntimeError(
            f"CUDA evaluator failed with exit {first.returncode}: {first.stderr.strip()}"
        )
    summary = parse_and_verify_output(first.stdout, cases)

    second = _run_evaluator(evaluator, protocol)
    if second.returncode != 0:
        raise RuntimeError(
            "repeat CUDA evaluator failed with exit "
            f"{second.returncode}: {second.stderr.strip()}"
        )
    if first.stdout != second.stdout:
        raise AssertionError("whole-run CUDA output is nondeterministic")
    repeat_summary = parse_and_verify_output(second.stdout, cases)
    if repeat_summary != summary:
        raise AssertionError("whole-run CUDA summary is nondeterministic")

    process_runs = 2
    protocol_cpp_cuda_words = summary.protocol_output_comparisons * process_runs
    grid_stride_cpp_cuda_words = summary.grid_stride_words * process_runs

    return {
        "aliased_input_launches": summary.aliased_input_launches * process_runs,
        "canary_checks": summary.canary_checks * process_runs,
        "cases": len(cases),
        "cpp_cuda_compared_words": (
            protocol_cpp_cuda_words + grid_stride_cpp_cuda_words
        ),
        "compute_capability": summary.compute_capability,
        "device_name": summary.device_name,
        "format": "ugts-go19-cuda-empty-mask-parity-v2",
        "grid_stride_cpp_cuda_compared_words": grid_stride_cpp_cuda_words,
        "grid_stride_extra_words": GRID_STRIDE_EXTRA_WORDS,
        "grid_stride_launches": summary.grid_stride_launches * process_runs,
        "input_immutability_compared_words": (
            summary.input_immutability_words * process_runs
        ),
        "mismatches": 0,
        "negative_argument_checks": (
            summary.negative_argument_checks * process_runs
        ),
        "production_grid_capacity_words": PRODUCTION_GRID_CAPACITY_WORDS,
        "protocol_cpp_cuda_compared_words": protocol_cpp_cuda_words,
        "python_cuda_compared_words": summary.emitted_words * process_runs,
        "root_status": "UNKNOWN",
        "stream_modes": ["default", "dual", "nondefault"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the exact target-run summary as formatted JSON evidence",
    )
    args = parser.parse_args()
    if not args.evaluator.is_file():
        raise FileNotFoundError(f"CUDA evaluator not found: {args.evaluator}")
    result = run_gate(args.evaluator.resolve())
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - standalone gate must fail closed.
        print(f"cuda_empty_mask_parity: {error}", file=sys.stderr)
        raise SystemExit(1) from error
