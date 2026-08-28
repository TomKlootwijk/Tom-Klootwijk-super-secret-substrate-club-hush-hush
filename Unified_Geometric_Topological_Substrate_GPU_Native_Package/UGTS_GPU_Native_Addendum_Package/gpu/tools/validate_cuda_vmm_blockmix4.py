#!/usr/bin/env python3
"""Validate the frozen native packed6 four-symbol block-mixture evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FULL_RATE_FRACTION = 0.99
MODES = {"non_compressible": 0, "generic_compressible": 1}
EXPECTED_ENDPOINTS = {
    "blockmix6_0_21_42_63_g1": (40, 42),
    "blockmix6_0_21_42_63_hash": (52, 54),
    "blockmix6_0_21_42_63_g2": (60, 62),
    "blockmix6_0_21_42_63_g4": (70, 72),
    "blockmix6_0_21_42_63_g8": (72, 74),
    "blockmix6_0_21_42_63_g16": (82, 84),
    "blockmix6_0_21_42_63_g32": (120, 124),
    "blockmix6_0_21_42_63_g64": (168, 172),
    "blockmix6_0_21_42_63_g128": (140, 144),
    "blockmix6_0_21_42_63_g256": (148, 152),
    "blockmix6_0_21_42_63_g512": (120, 124),
    "blockmix6_0_21_42_63_g1024": (124, 128),
}


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
        default="benchmarks/cuda_vmm_blockmix4_exact/provenance.json",
    )
    args = parser.parse_args()
    provenance_path = Path(args.provenance).resolve()
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    root = provenance_path.parents[2]
    require(
        provenance["schema"] == "UGTS-CUDA-VMM-BLOCKMIX4-PROVENANCE-1.0",
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
        "kBlockMixCompressibleFourPatternBase",
        "blockmix6_0_21_42_63_hash",
        "((group >> run_exponent) & 3u) * 21u",
        "mix32(group ^ 0xa54ff53au)",
        "ld.global.cg.u32",
    ):
        require(marker in source, f"frozen source marker missing: {marker}")
    expected_packed = {
        0: [0x00000000] * 3,
        21: [0x55555555] * 3,
        42: [0xAAAAAAAA] * 3,
        63: [0xFFFFFFFF] * 3,
    }
    for code, words in expected_packed.items():
        require(packed_words(code) == words, f"code-{code} packing mismatch")
    for exponent in range(11):
        run_groups = 1 << exponent
        observed = [(((group >> exponent) & 3) * 21) for group in range(run_groups * 4)]
        require(
            observed
            == [0] * run_groups + [21] * run_groups + [42] * run_groups + [63] * run_groups,
            f"four-symbol cycle mismatch: g{run_groups}",
        )

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

    selected = {
        "short_refinement": {
            pattern: aggregates["short_refinement"]
            for pattern in EXPECTED_ENDPOINTS
            if pattern.endswith("_hash") or pattern.rsplit("_g", 1)[-1] in {"1", "2", "4", "8", "16"}
        },
        "long_refinement": {
            pattern: aggregates["long_refinement"]
            for pattern in EXPECTED_ENDPOINTS
            if pattern.rsplit("_g", 1)[-1] in {"32", "128", "256", "512", "1024"}
        },
        "g64_extension": {
            "blockmix6_0_21_42_63_g64": aggregates["g64_extension"]
        },
    }
    corpus_sizes = {
        corpus["name"]: corpus["sizes_mib"] for corpus in provenance["corpora"]
    }
    for corpus_name, patterns in selected.items():
        for pattern, aggregate in patterns.items():
            require(
                endpoint(aggregate, pattern, corpus_sizes[corpus_name]) == EXPECTED_ENDPOINTS[pattern],
                f"endpoint mismatch: {pattern}",
            )

    map_path = repo_path(root, provenance["artifacts"]["map"]["path"])
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    require(mapping["schema"] == "UGTS-CUDA-VMM-BLOCKMIX4-MAP-1.0", "map schema mismatch")
    require(mapping["layout"]["logical_codes"] == [0, 21, 42, 63], "map code list mismatch")
    require(
        mapping["layout"]["packed_words"]
        == ["0x00000000", "0x55555555", "0xAAAAAAAA", "0xFFFFFFFF"],
        "map packed words mismatch",
    )
    expected_endpoint_values = {pattern: values[0] for pattern, values in EXPECTED_ENDPOINTS.items()}
    require(mapping["reported_endpoints_mib"] == expected_endpoint_values, "map endpoint mismatch")
    require(provenance["result"]["reported_endpoints_mib"] == expected_endpoint_values, "provenance endpoint mismatch")
    require(
        mapping["validation"]["combined"]
        == {key: value for key, value in combined.items() if key != "mismatches"},
        "map totals mismatch",
    )
    map_rows = {row["pattern"]: row for row in mapping["per_pattern"]}
    require(set(map_rows) == set(EXPECTED_ENDPOINTS), "map pattern coverage mismatch")
    for pattern, (reported, first_below) in EXPECTED_ENDPOINTS.items():
        require(map_rows[pattern]["reported_99pct_endpoint_mib"] == reported, f"map endpoint row mismatch: {pattern}")
        require(map_rows[pattern]["first_below_99pct_mib"] == first_below, f"map first-below mismatch: {pattern}")

    print(
        "PASS native blockmix4 evidence: "
        f"{combined['raw_rows']} rows, {combined['validated_payloads']} payloads, "
        f"{combined['timed_gpu_lookups']} timed lookups; endpoints 40-168 MiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
