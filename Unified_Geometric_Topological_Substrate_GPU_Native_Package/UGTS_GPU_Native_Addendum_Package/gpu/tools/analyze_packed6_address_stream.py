#!/usr/bin/env python3
"""Replay the compression-LUT address generator and quantify line coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


LCG_MUL = np.uint32(1664525)
LCG_ADD = np.uint32(1013904223)


def mix32(values: np.ndarray | np.uint32) -> np.ndarray:
    x = np.asarray(values, dtype=np.uint32).copy()
    with np.errstate(over="ignore"):
        x ^= x >> np.uint32(16)
        x *= np.uint32(0x7FEB352D)
        x ^= x >> np.uint32(15)
        x *= np.uint32(0x846CA68B)
        x ^= x >> np.uint32(16)
    return x


def analyze(size_mib: int, group_trim: int, warps: int, steps: int) -> dict[str, object]:
    allocation_bytes = size_mib * 1024 * 1024
    groups = allocation_bytes // 12 - group_trim
    entries = groups * 16
    if groups <= 0 or entries > 0xFFFFFFFF:
        raise ValueError("invalid packed table geometry")
    threads = warps * 32
    warp = np.repeat(np.arange(warps, dtype=np.uint32), 32)
    lane = np.tile(np.arange(32, dtype=np.uint32), warps)
    sample_seed = mix32(np.uint32(3) * np.uint32(0xC2B2AE35))[()]
    with np.errstate(over="ignore"):
        seeds = mix32(
            sample_seed
            ^ (warp * np.uint32(0x9E3779B9))
            ^ (lane * np.uint32(0x85EBCA6B))
        )
    state = seeds.copy()
    word_count = groups * 3
    sector_count = (word_count + 7) // 8
    line_count = (word_count + 31) // 32
    seen_sectors = np.zeros(sector_count, dtype=np.bool_)
    seen_lines = np.zeros(line_count, dtype=np.bool_)
    unique_sectors_per_warp_step = 0
    unique_lines_per_warp_step = 0
    immediate_line_reuse = 0
    previous_line: np.ndarray | None = None
    out_of_bounds = 0
    straddles = 0
    for _ in range(steps):
        with np.errstate(over="ignore"):
            state = state * LCG_MUL + LCG_ADD
        index = ((state.astype(np.uint64) * np.uint64(entries)) >> np.uint64(32)).astype(
            np.uint32
        )
        bit = index.astype(np.uint64) * np.uint64(6)
        word = (bit >> np.uint64(5)).astype(np.int64)
        shift = bit & np.uint64(31)
        high = word + (shift > 26)
        out_of_bounds += int(np.count_nonzero(high >= word_count))
        straddles += int(np.count_nonzero(shift > 26))
        sector = word // 8
        line = word // 32
        seen_sectors[sector] = True
        seen_lines[line] = True
        sector_by_warp = np.sort(sector.reshape(warps, 32), axis=1)
        line_by_warp = np.sort(line.reshape(warps, 32), axis=1)
        unique_sectors_per_warp_step += int(
            warps + np.count_nonzero(sector_by_warp[:, 1:] != sector_by_warp[:, :-1])
        )
        unique_lines_per_warp_step += int(
            warps + np.count_nonzero(line_by_warp[:, 1:] != line_by_warp[:, :-1])
        )
        if previous_line is not None:
            immediate_line_reuse += int(np.count_nonzero(line == previous_line))
        previous_line = line
    lookups = threads * steps
    warp_steps = warps * steps
    return {
        "size_mib": size_mib,
        "group_trim": group_trim,
        "allocation_bytes": allocation_bytes,
        "groups": groups,
        "entries": entries,
        "table_bytes": groups * 12,
        "threads": threads,
        "steps": steps,
        "lookups": lookups,
        "out_of_bounds": out_of_bounds,
        "straddle_fraction": straddles / lookups,
        "unique_32b_sectors": int(np.count_nonzero(seen_sectors)),
        "total_32b_sectors": sector_count,
        "visited_32b_sector_fraction": float(np.count_nonzero(seen_sectors) / sector_count),
        "unique_128b_lines": int(np.count_nonzero(seen_lines)),
        "total_128b_lines": line_count,
        "visited_128b_line_fraction": float(np.count_nonzero(seen_lines) / line_count),
        "mean_unique_32b_sectors_per_warp_step": unique_sectors_per_warp_step / warp_steps,
        "mean_unique_128b_lines_per_warp_step": unique_lines_per_warp_step / warp_steps,
        "immediate_same_128b_line_fraction": immediate_line_reuse / (threads * (steps - 1)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True, help="SIZE_MIB:GROUP_TRIM")
    parser.add_argument("--warps", type=int, default=1104)
    parser.add_argument("--steps", type=int, default=512)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = []
    for value in args.case:
        size_text, trim_text = value.split(":", 1)
        rows.append(analyze(int(size_text), int(trim_text), args.warps, args.steps))
    document = {
        "schema": "UGTS-PACKED6-ADDRESS-REPLAY-1.0",
        "scope": "CPU replay of the exact native CUDA lookup address arithmetic; no GPU timing",
        "cases": rows,
    }
    rendered = json.dumps(document, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
