#!/usr/bin/env python3
"""Validate the frozen exact-binary sparse VMM-compression evidence chain."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


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
        default="benchmarks/cuda_vmm_sparse_exact/provenance.json",
    )
    args = parser.parse_args()

    provenance_path = Path(args.provenance).resolve()
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    root = provenance_path.parents[2]

    for name, artifact in provenance["artifacts"].items():
        path = repo_path(root, artifact["path"])
        require(path.is_file(), f"missing {name}: {path}")
        require(path.stat().st_size == artifact["bytes"], f"size mismatch: {path}")
        require(sha256(path) == artifact["sha256"], f"hash mismatch: {path}")

    expected_device = provenance["device"]
    combined = {
        "runs": 0,
        "raw_rows": 0,
        "validated_rows": 0,
        "validated_payloads": 0,
        "timed_gpu_lookups": 0,
        "invalid_rows": 0,
        "mismatches": 0,
    }

    for corpus in provenance["corpora"]:
        aggregate_path = repo_path(root, corpus["aggregate"])
        require(aggregate_path.is_file(), f"missing aggregate: {aggregate_path}")
        require(
            sha256(aggregate_path) == corpus["aggregate_sha256"],
            f"aggregate hash mismatch: {aggregate_path}",
        )
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        raw_inputs = aggregate["inputs"]
        require(len(raw_inputs) == corpus["runs"], f"run count mismatch: {aggregate_path}")

        observed_orders: list[int] = []
        rows = payloads = timed = invalid = mismatches = 0
        for raw_value in raw_inputs:
            raw_path = repo_path(root, raw_value)
            require(raw_path.is_file(), f"missing raw input: {raw_path}")
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            device = raw["device"]
            require(device["name"] == expected_device["name"], "device-name mismatch")
            require(
                device["compute_capability"] == expected_device["compute_capability"],
                "compute-capability mismatch",
            )
            require(device["l2_bytes"] == expected_device["l2_bytes"], "L2 mismatch")
            require(
                device["multiprocessors"] == expected_device["multiprocessors"],
                "SM-count mismatch",
            )
            observed_orders.append(raw["run_parameters"]["order"])
            steps = raw["run_parameters"]["lookups_per_thread"]
            for row in raw["results"]:
                rows += 1
                mismatch = sum(row["mismatch_totals"].values())
                valid = (
                    row["validation"]
                    and mismatch == 0
                    and row["requested_compression"] == row["effective_compression"]
                )
                invalid += int(not valid)
                mismatches += mismatch
                payloads += sum(row["validated_payloads"].values())
                timed += (
                    row["validated_payloads"]["cold"]
                    + row["validated_payloads"]["hot"]
                ) * steps

        require(observed_orders == [0, 1, 0, 1], f"order mismatch: {observed_orders}")
        require(rows == corpus["raw_rows"], f"raw-row mismatch: {aggregate_path}")
        require(payloads == corpus["validated_payloads"], f"payload mismatch: {aggregate_path}")
        require(timed == corpus["timed_gpu_lookups"], f"lookup mismatch: {aggregate_path}")
        require(invalid == corpus["invalid_rows"] == 0, f"invalid rows: {aggregate_path}")
        require(mismatches == 0, f"mismatches: {aggregate_path}")

        validation = aggregate["validation_summary"]
        require(validation["all_valid"], f"aggregate validation failed: {aggregate_path}")
        require(validation["raw_rows"] == rows, f"aggregate row disagreement: {aggregate_path}")
        require(
            validation["validated_payloads"] == payloads,
            f"aggregate payload disagreement: {aggregate_path}",
        )
        require(
            validation["timed_gpu_lookups"] == timed,
            f"aggregate lookup disagreement: {aggregate_path}",
        )

        combined["runs"] += len(raw_inputs)
        combined["raw_rows"] += rows
        combined["validated_rows"] += rows - invalid
        combined["validated_payloads"] += payloads
        combined["timed_gpu_lookups"] += timed
        combined["invalid_rows"] += invalid
        combined["mismatches"] += mismatches

    require(combined == provenance["combined"], "combined provenance totals disagree")

    summary_spec = provenance["summary"]
    summary_path = repo_path(root, summary_spec["path"])
    require(sha256(summary_path) == summary_spec["sha256"], "summary hash mismatch")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    require(len(summary["thresholds"]) == summary_spec["sparse_patterns"], "pattern count mismatch")
    require(summary["retained_fraction"] == summary_spec["retained_rate_fraction"], "retained-rate mismatch")
    fitted = summary["fitted_boundaries"]["format_series_observed_compression_cliffs"]
    require(
        fitted["minimum_nonzero_exceptions_at_limit"]
        == summary_spec["observed_cliff_exception_minimum"],
        "cliff minimum mismatch",
    )
    require(
        fitted["median_nonzero_exceptions_at_limit"]
        == summary_spec["observed_cliff_exception_median"],
        "cliff median mismatch",
    )
    require(
        fitted["maximum_nonzero_exceptions_at_limit"]
        == summary_spec["observed_cliff_exception_maximum"],
        "cliff maximum mismatch",
    )

    print(
        "PASS exact-binary sparse evidence: "
        f"{combined['raw_rows']} rows, "
        f"{combined['validated_payloads']} payloads, "
        f"{combined['timed_gpu_lookups']} timed lookups, "
        f"{len(summary['thresholds'])} thresholds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
