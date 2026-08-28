"""Measure chosen-scalar timing only; never prints or stores key material."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from ugts36.sara363 import SECP256K1_N, compressed_public_key


OUTPUT = Path(__file__).with_name("side_channel_timing.json")
CASES = {
    "scalar_1_bitlength_1": 1,
    "scalar_single_high_bit_bitlength_256": 1 << 255,
    "scalar_n_minus_1_dense_bitlength_256": SECP256K1_N - 1,
}
ROUNDS = 9
CALLS_PER_ROUND = 20


def measure(scalar: int) -> list[float]:
    samples_ms: list[float] = []
    for _ in range(ROUNDS):
        start = time.perf_counter()
        for _ in range(CALLS_PER_ROUND):
            compressed_public_key(scalar)
        samples_ms.append((time.perf_counter() - start) * 1000.0 / CALLS_PER_ROUND)
    return samples_ms


def main() -> None:
    results: dict[str, object] = {
        "method": {
            "rounds": ROUNDS,
            "calls_per_round": CALLS_PER_ROUND,
            "chosen_public_test_scalars_only": True,
            "key_material_recorded": False,
        },
        "cases": {},
    }
    medians: dict[str, float] = {}
    for name, scalar in CASES.items():
        samples = measure(scalar)
        median_ms = statistics.median(samples)
        medians[name] = median_ms
        results["cases"][name] = {
            "bit_length": scalar.bit_length(),
            "population_count": scalar.bit_count(),
            "median_ms_per_call": median_ms,
            "min_ms_per_call": min(samples),
            "max_ms_per_call": max(samples),
        }

    shortest = medians["scalar_1_bitlength_1"]
    results["ratios_vs_scalar_1"] = {
        name: median / shortest for name, median in medians.items()
    }
    results["interpretation"] = (
        "Large chosen-input timing differences are consistent with variable-time "
        "double-and-add scalar multiplication. This is not a remote exploit by itself; "
        "risk requires use with real secrets plus a capable local/co-resident observer."
    )
    OUTPUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
