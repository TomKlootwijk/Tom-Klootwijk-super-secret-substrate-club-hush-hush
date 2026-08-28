#!/usr/bin/env python3
"""Validate the frozen native G24 code-8 VMM compression evidence chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path


PATTERN = "ugts_g24_floor70_code8"
SIZES = [4, 28, 32, 36, 38, 40, 48, 64, 96, 128, 160, 192, 208, 224, 240, 248]
PATHS = {"global_cg", "texture_object"}
MODES = {"non_compressible": 0, "generic_compressible": 1}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def repo_path(root: Path, value: str) -> Path:
    return root / Path(value.replace("\\", "/"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provenance",
        default="benchmarks/cuda_vmm_g24_code8_isolated/provenance.json",
    )
    args = parser.parse_args()

    provenance_path = Path(args.provenance).resolve()
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    root = provenance_path.parents[2]
    require(
        provenance["schema"] == "UGTS-CUDA-VMM-G24-CODE8-PROVENANCE-1.0",
        "unexpected provenance schema",
    )

    for name, artifact in provenance["artifacts"].items():
        path = repo_path(root, artifact["path"])
        require(path.is_file(), f"missing {name}: {path}")
        require(path.stat().st_size == artifact["bytes"], f"size mismatch: {path}")
        require(sha256(path) == artifact["sha256"], f"hash mismatch: {path}")

    aggregate_path = repo_path(root, provenance["artifacts"]["aggregate"]["path"])
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    require(
        aggregate["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0",
        "unexpected aggregate schema",
    )
    expected_device = provenance["device"]
    device = aggregate["device"]
    require(device["name"] == expected_device["name"], "device name mismatch")
    require(
        device["compute_capability"] == expected_device["compute_capability"],
        "compute capability mismatch",
    )
    require(device["l2_bytes"] == expected_device["l2_bytes"], "L2 mismatch")
    require(device["multiprocessors"] == expected_device["multiprocessors"], "SM mismatch")
    require(device["generic_compression_supported"], "compression support not recorded")
    require(
        set(device["occupancy_blocks_per_sm"].values())
        == {expected_device["occupancy_blocks_per_sm"]},
        "occupancy mismatch",
    )

    raw_rows = payloads = timed_lookups = invalid = mismatches = 0
    observed_orders: list[int] = []
    expected_raw_paths: list[str] = []
    for run_spec in provenance["runs"]:
        path = repo_path(root, run_spec["path"])
        require(path.is_file(), f"missing raw run: {path}")
        require(path.stat().st_size == run_spec["bytes"], f"raw size mismatch: {path}")
        require(sha256(path) == run_spec["sha256"], f"raw hash mismatch: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        require(raw["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-1.0", "raw schema mismatch")
        require(raw["device"]["name"] == expected_device["name"], "raw device mismatch")
        require(raw["device"]["l2_bytes"] == expected_device["l2_bytes"], "raw L2 mismatch")
        params = raw["run_parameters"]
        require(params["order"] == run_spec["order"], "run order mismatch")
        require(params["lookups_per_thread"] == 512, "lookup-step mismatch")
        require(params["eviction_bytes"] == 256 * 1024 * 1024, "eviction mismatch")
        require(params["warmup_sets"] == 2, "warmup mismatch")
        require(params["measured_sets"] == 10, "sample mismatch")
        require(params["compression_modes_alternate_per_sample"], "mode alternation absent")
        observed_orders.append(params["order"])
        expected_raw_paths.append(run_spec["path"].replace("/", "\\"))

        keys = set()
        for row in raw["results"]:
            raw_rows += 1
            require(row["pattern"] == PATTERN, "pattern mismatch")
            require(row["size_mib"] in SIZES, "size mismatch")
            require(row["path"] in PATHS, "path mismatch")
            require(row["warps"] == expected_device["total_warps"], "warp mismatch")
            require(row["compression"] in MODES, "compression label mismatch")
            requested = MODES[row["compression"]]
            require(row["requested_compression"] == requested, "requested property mismatch")
            require(row["effective_compression"] == requested, "effective property mismatch")
            require(row["bytes_per_code"] == 0.75, "packing density mismatch")
            key = (row["size_mib"], row["path"], row["compression"])
            require(key not in keys, f"duplicate row: {key}")
            keys.add(key)
            row_mismatches = sum(row["mismatch_totals"].values())
            row_valid = row["validation"] and row_mismatches == 0
            invalid += int(not row_valid)
            mismatches += row_mismatches
            payloads += sum(row["validated_payloads"].values())
            timed_lookups += (
                row["validated_payloads"]["cold"]
                + row["validated_payloads"]["hot"]
            ) * params["lookups_per_thread"]
        require(len(keys) == len(SIZES) * len(PATHS) * len(MODES), "raw coverage mismatch")

    require(observed_orders == [0, 1, 0, 1], "balanced process order mismatch")
    require(aggregate["observed_orders"] == observed_orders, "aggregate order mismatch")
    require(aggregate["inputs"] == expected_raw_paths, "aggregate input list mismatch")
    observed = {
        "raw_rows": raw_rows,
        "validated_payloads": payloads,
        "timed_gpu_lookups": timed_lookups,
        "invalid_rows": invalid,
        "mismatches": mismatches,
    }
    require(observed == provenance["validation"], "provenance totals mismatch")

    validation = aggregate["validation_summary"]
    require(validation["all_valid"], "aggregate validation failed")
    require(validation["raw_rows"] == raw_rows, "aggregate row total mismatch")
    require(validation["validated_payloads"] == payloads, "aggregate payload mismatch")
    require(validation["timed_gpu_lookups"] == timed_lookups, "aggregate lookup mismatch")
    require(validation["invalid_rows"] == invalid == 0, "invalid rows present")
    require(validation["paired_comparisons"] == 32, "paired comparison mismatch")

    comparisons = aggregate["compression_comparisons"]
    require(len(comparisons) == 32, "comparison coverage mismatch")
    require(
        {(row["size_mib"], row["path"]) for row in comparisons}
        == {(size, path) for size in SIZES for path in PATHS},
        "comparison key mismatch",
    )
    ratios = [row["paired_hot_ratio"] for row in comparisons]
    result = provenance["result"]
    require(statistics.median(ratios) == result["paired_hot_ratio_median"], "ratio median mismatch")
    require(min(ratios) == result["paired_hot_ratio_minimum"], "ratio minimum mismatch")
    require(max(ratios) == result["paired_hot_ratio_maximum"], "ratio maximum mismatch")

    summary_path = repo_path(root, provenance["artifacts"]["summary"]["path"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    require(summary["producer_mapping"]["quantized_code"] == 8, "producer code mismatch")
    require(
        summary["producer_mapping"]["packed_words_hex"]
        == ["0x08208208", "0x82082082", "0x20820820"],
        "packed words mismatch",
    )
    require(
        summary["paired_generic_to_non_compressible_hot_ratio"]["all_size_path_pairs"]["median"]
        == result["paired_hot_ratio_median"],
        "summary ratio mismatch",
    )
    for path in PATHS:
        endpoints = summary["full_rate_definition"]["result"][path]
        require(
            endpoints["non_compressible"]["last_size_mib"]
            == result["last_full_rate_mib_non_compressible"],
            "non-compressible endpoint mismatch",
        )
        require(
            endpoints["generic_compressible"]["last_size_mib"]
            == result["last_full_rate_mib_generic_compressible"],
            "generic endpoint mismatch",
        )
    require(
        summary["conclusion"]["compression_capacity_extension_observed"]
        == result["compression_capacity_extension_observed"],
        "capacity conclusion mismatch",
    )

    print(
        "PASS native G24 code8 evidence: "
        f"{raw_rows} rows, {payloads} payloads, {timed_lookups} timed lookups, "
        f"paired median={statistics.median(ratios):.6f}, capacity extension=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
