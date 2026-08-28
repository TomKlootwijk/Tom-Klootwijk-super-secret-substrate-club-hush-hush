#!/usr/bin/env python3
"""Validate the frozen native packed6 code-0/63 block-mixture evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FULL_RATE_FRACTION = 0.99
MODES = {"non_compressible": 0, "generic_compressible": 1}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def repo_path(root: Path, value: str) -> Path:
    return root / Path(value.replace("\\", "/"))


def normalized(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def packed_words(code: int) -> list[int]:
    words = [0, 0, 0]
    for offset in range(16):
        bit = offset * 6
        word = bit >> 5
        shift = bit & 31
        words[word] = (words[word] | ((code << shift) & 0xFFFFFFFF)) & 0xFFFFFFFF
        if shift > 26:
            words[word + 1] |= code >> (32 - shift)
    return words


def endpoint(aggregate: dict, pattern: str, sizes: list[int]) -> tuple[int, int | None]:
    rows = {
        row["size_mib"]: row
        for row in aggregate["aggregate_rows"]
        if row["pattern"] == pattern and row["compression"] == "generic_compressible"
    }
    require(set(rows) == set(sizes), f"endpoint coverage mismatch: {pattern}")
    best = max(row["hot_glookups_s"] for row in rows.values())
    last = max(
        size
        for size, row in rows.items()
        if row["hot_glookups_s"] >= FULL_RATE_FRACTION * best
    )
    later = [size for size in sizes if size > last]
    return last, min(later) if later else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provenance",
        default="benchmarks/cuda_vmm_blockmix063_exact/provenance.json",
    )
    args = parser.parse_args()
    provenance_path = Path(args.provenance).resolve()
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    root = provenance_path.parents[2]
    require(
        provenance["schema"] == "UGTS-CUDA-VMM-BLOCKMIX063-PROVENANCE-1.0",
        "unexpected provenance schema",
    )

    for name, artifact in provenance["artifacts"].items():
        path = repo_path(root, artifact["path"])
        require(path.is_file(), f"missing {name}: {path}")
        require(path.stat().st_size == artifact["bytes"], f"size mismatch: {path}")
        require(sha256(path) == artifact["sha256"], f"hash mismatch: {path}")

    source_path = repo_path(root, provenance["artifacts"]["source"]["path"])
    source = source_path.read_text(encoding="utf-8")
    for marker in (
        "kBlockMixZeroOnesPatternBase",
        "blockmix6_0_63_hash",
        "group >> run_exponent",
        "ld.global.cg.u32",
    ):
        require(marker in source, f"frozen source marker missing: {marker}")
    require(packed_words(0) == [0, 0, 0], "code-0 packing mismatch")
    require(packed_words(63) == [0xFFFFFFFF] * 3, "code-63 packing mismatch")

    expected_device = provenance["device"]
    combined = {
        "runs": 0,
        "raw_rows": 0,
        "validated_payloads": 0,
        "timed_gpu_lookups": 0,
        "invalid_rows": 0,
        "mismatches": 0,
    }
    aggregates: dict[str, dict] = {}
    for corpus in provenance["corpora"]:
        aggregate_spec = provenance["artifacts"][corpus["aggregate_artifact"]]
        aggregate_path = repo_path(root, aggregate_spec["path"])
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        aggregates[corpus["name"]] = aggregate
        require(
            aggregate["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0",
            "aggregate schema mismatch",
        )
        device = aggregate["device"]
        require(device["name"] == expected_device["name"], "device name mismatch")
        require(device["compute_capability"] == expected_device["compute_capability"], "compute mismatch")
        require(device["l2_bytes"] == expected_device["l2_bytes"], "L2 mismatch")
        require(device["multiprocessors"] == expected_device["multiprocessors"], "SM mismatch")
        require(device["generic_compression_supported"], "compression support missing")

        expected_patterns = set(corpus["patterns"])
        expected_sizes = set(corpus["sizes_mib"])
        observed_orders = []
        aggregate_inputs = []
        raw_rows = payloads = timed = invalid = mismatches = 0
        for run_spec in corpus["runs"]:
            raw_path = repo_path(root, run_spec["path"])
            require(raw_path.is_file(), f"missing raw run: {raw_path}")
            require(raw_path.stat().st_size == run_spec["bytes"], f"raw size mismatch: {raw_path}")
            require(sha256(raw_path) == run_spec["sha256"], f"raw hash mismatch: {raw_path}")
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            require(raw["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-1.0", "raw schema mismatch")
            require(raw["device"]["name"] == expected_device["name"], "raw device mismatch")
            params = raw["run_parameters"]
            require(params["order"] == run_spec["order"], "raw order mismatch")
            require(params["lookups_per_thread"] == 512, "step mismatch")
            require(params["eviction_bytes"] == 256 * 1024 * 1024, "eviction mismatch")
            require(params["warmup_sets"] == 2 and params["measured_sets"] == 10, "sample mismatch")
            require(params["compression_modes_alternate_per_sample"], "mode alternation missing")
            observed_orders.append(params["order"])
            aggregate_inputs.append(normalized(run_spec["path"]))

            keys = set()
            for row in raw["results"]:
                raw_rows += 1
                require(row["pattern"] in expected_patterns, "raw pattern mismatch")
                require(row["size_mib"] in expected_sizes, "raw size mismatch")
                require(row["path"] == "global_cg", "unvalidated path entered corpus")
                require(row["warps"] == expected_device["total_warps"], "warp mismatch")
                require(row["compression"] in MODES, "mode label mismatch")
                requested = MODES[row["compression"]]
                require(row["requested_compression"] == requested, "requested property mismatch")
                require(row["effective_compression"] == requested, "effective property mismatch")
                require(row["bytes_per_code"] == 0.75, "packing density mismatch")
                require(row["entries"] == row["groups"] * 16, "entry/group mismatch")
                require(row["table_bytes"] == row["groups"] * 12, "byte/group mismatch")
                key = (row["pattern"], row["size_mib"], row["compression"])
                require(key not in keys, f"duplicate raw key: {key}")
                keys.add(key)
                row_mismatches = sum(row["mismatch_totals"].values())
                row_valid = row["validation"] and row_mismatches == 0
                invalid += int(not row_valid)
                mismatches += row_mismatches
                payloads += sum(row["validated_payloads"].values())
                timed += (
                    row["validated_payloads"]["cold"]
                    + row["validated_payloads"]["hot"]
                ) * params["lookups_per_thread"]
            require(
                len(keys) == len(expected_patterns) * len(expected_sizes) * len(MODES),
                "raw coverage mismatch",
            )

        require(observed_orders == [0, 1, 0, 1], "balanced order mismatch")
        require(aggregate["observed_orders"] == observed_orders, "aggregate order mismatch")
        require(
            [normalized(value) for value in aggregate["inputs"]] == aggregate_inputs,
            "aggregate inputs mismatch",
        )
        observed = {
            "raw_rows": raw_rows,
            "validated_payloads": payloads,
            "timed_gpu_lookups": timed,
            "invalid_rows": invalid,
            "mismatches": mismatches,
        }
        for key, value in observed.items():
            require(value == corpus[key], f"corpus {key} mismatch")
        validation = aggregate["validation_summary"]
        require(validation["all_valid"], "aggregate validation failed")
        require(validation["raw_rows"] == raw_rows, "aggregate row mismatch")
        require(validation["validated_payloads"] == payloads, "aggregate payload mismatch")
        require(validation["timed_gpu_lookups"] == timed, "aggregate lookup mismatch")
        require(validation["invalid_rows"] == invalid == 0, "invalid retained rows")

        combined["runs"] += len(corpus["runs"])
        for key in ("raw_rows", "validated_payloads", "timed_gpu_lookups", "invalid_rows", "mismatches"):
            combined[key] += observed[key]
    require(combined == provenance["combined"], "combined totals mismatch")

    screen = aggregates["capacity_screen"]
    refinement = aggregates["transition_refinement"]
    screen_sizes = provenance["corpora"][0]["sizes_mib"]
    refinement_sizes = provenance["corpora"][1]["sizes_mib"]
    for pattern in ("blockmix6_0_63_hash", "blockmix6_0_63_g1", "blockmix6_0_63_g2", "blockmix6_0_63_g4", "blockmix6_0_63_g8"):
        require(endpoint(refinement, pattern, refinement_sizes) == (72, 74), f"short endpoint mismatch: {pattern}")
    require(endpoint(refinement, "blockmix6_0_63_g16", refinement_sizes) == (88, 90), "g16 endpoint mismatch")
    for groups in (32, 64, 128, 256, 512, 1024):
        pattern = f"blockmix6_0_63_g{groups}"
        require(endpoint(screen, pattern, screen_sizes) == (240, 248), f"long endpoint mismatch: {pattern}")

    map_path = repo_path(root, provenance["artifacts"]["map"]["path"])
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    require(mapping["schema"] == "UGTS-CUDA-VMM-BLOCKMIX063-MAP-1.0", "map schema mismatch")
    require(mapping["layout"]["code_0_words"] == ["0x00000000"] * 3, "map code-0 mismatch")
    require(mapping["layout"]["code_63_words"] == ["0xFFFFFFFF"] * 3, "map code-63 mismatch")
    require(mapping["observed_capacity_classes"]["first_tested_run_span_full_through_240_mib"] == {"groups": 32, "codes": 512, "bytes": 384}, "map run-span mismatch")
    require(
        mapping["validation"]["combined"]
        == {key: value for key, value in combined.items() if key != "mismatches"},
        "map totals mismatch",
    )

    print(
        "PASS native blockmix063 evidence: "
        f"{combined['raw_rows']} rows, {combined['validated_payloads']} payloads, "
        f"{combined['timed_gpu_lookups']} timed lookups; endpoints 72/88/240 MiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
