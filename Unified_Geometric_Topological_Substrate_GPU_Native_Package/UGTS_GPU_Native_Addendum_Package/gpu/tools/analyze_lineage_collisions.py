#!/usr/bin/env python3
"""Measure collisions in the benchmark's structured 32-bit lineage preimage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


MASK32 = (1 << 32) - 1
SEED_MULTIPLIER = 2654435761


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=int, default=4_194_304)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.candidates <= 1 << 32:
        parser.error("--candidates must be in [1, 2^32]")

    first_seen: dict[int, int] = {}
    multiplicity: dict[int, int] = {}
    first_pair: tuple[int, int, int] | None = None
    extra_candidates = 0
    for index in range(args.candidates):
        preimage = (((index * SEED_MULTIPLIER) & MASK32) ^ index) & MASK32
        prior = first_seen.get(preimage)
        if prior is None:
            first_seen[preimage] = index
            continue
        if first_pair is None:
            first_pair = (prior, index, preimage)
        multiplicity[preimage] = multiplicity.get(preimage, 1) + 1
        extra_candidates += 1

    result = {
        "schema": "UGTS-LINEAGE-COLLISION-1.0",
        "candidates": args.candidates,
        "lineage_seed_formula": "uint32(index * 2654435761)",
        "mix_input_formula": "lineage_seed ^ uint32(index)",
        "unique_mix_inputs": len(first_seen),
        "collision_keys": len(multiplicity),
        "extra_candidates_on_collision_keys": extra_candidates,
        "collision_candidate_fraction": extra_candidates / args.candidates,
        "maximum_key_multiplicity": max(multiplicity.values(), default=1),
        "first_collision": (
            {
                "first_index": first_pair[0],
                "second_index": first_pair[1],
                "mix_input": first_pair[2],
            }
            if first_pair
            else None
        ),
        "interpretation": "mix32 is bijective over uint32, so collisions in its input remain collisions in the emitted lineage word.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
