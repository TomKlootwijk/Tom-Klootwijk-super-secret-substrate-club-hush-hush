#!/usr/bin/env python3
"""Validate the frozen exhaustive uniform packed6 native GPU evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FULL_RATE_FRACTION = 0.99
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


def code_from_pattern(pattern: str) -> int:
    require(pattern.startswith("uniform6_"), f"unexpected pattern: {pattern}")
    code = int(pattern.removeprefix("uniform6_"))
    require(0 <= code <= 63, f"code out of range: {code}")
    return code


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


def full_endpoint(aggregate: dict, code: int, sizes: list[int]) -> int:
    rows = {
        row["size_mib"]: row
        for row in aggregate["aggregate_rows"]
        if code_from_pattern(row["pattern"]) == code
        and row["compression"] == "generic_compressible"
    }
    require(set(rows) == set(sizes), f"endpoint coverage mismatch for code {code}")
    best = max(row["hot_glookups_s"] for row in rows.values())
    return max(
        size for size, row in rows.items() if row["hot_glookups_s"] >= FULL_RATE_FRACTION * best
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provenance",
        default="benchmarks/cuda_vmm_uniform6_exact/provenance.json",
    )
    args = parser.parse_args()
    provenance_path = Path(args.provenance).resolve()
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    root = provenance_path.parents[2]
    require(
        provenance["schema"] == "UGTS-CUDA-VMM-UNIFORM6-PROVENANCE-1.0",
        "unexpected provenance schema",
    )

    for name, artifact in provenance["artifacts"].items():
        path = repo_path(root, artifact["path"])
        require(path.is_file(), f"missing {name}: {path}")
        require(path.stat().st_size == artifact["bytes"], f"size mismatch: {path}")
        require(sha256(path) == artifact["sha256"], f"hash mismatch: {path}")

    expected_device = provenance["device"]
    combined = {
        "runs": 0,
        "raw_rows": 0,
        "validated_payloads": 0,
        "timed_gpu_lookups": 0,
        "invalid_rows": 0,
        "mismatches": 0,
    }
    aggregates = {}
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

        observed_orders = []
        aggregate_inputs = []
        raw_rows = payloads = timed = invalid = mismatches = 0
        expected_codes = set(range(64)) if corpus["name"] == "all_code_screen" else {0, 21, 42, 63}
        expected_sizes = set(corpus["sizes_mib"])
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
            aggregate_inputs.append(run_spec["path"].replace("/", "\\"))

            keys = set()
            for row in raw["results"]:
                raw_rows += 1
                code = code_from_pattern(row["pattern"])
                require(code in expected_codes, "raw code mismatch")
                require(row["size_mib"] in expected_sizes, "raw size mismatch")
                require(row["path"] == "global_cg", "rejected path entered retained corpus")
                require(row["warps"] == expected_device["total_warps"], "warp mismatch")
                require(row["compression"] in MODES, "mode label mismatch")
                requested = MODES[row["compression"]]
                require(row["requested_compression"] == requested, "requested property mismatch")
                require(row["effective_compression"] == requested, "effective property mismatch")
                require(row["bytes_per_code"] == 0.75, "packing density mismatch")
                key = (code, row["size_mib"], row["compression"])
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
                len(keys) == len(expected_codes) * len(expected_sizes) * len(MODES),
                "raw coverage mismatch",
            )

        require(observed_orders == [0, 1, 0, 1], "balanced order mismatch")
        require(aggregate["observed_orders"] == observed_orders, "aggregate order mismatch")
        require(aggregate["inputs"] == aggregate_inputs, "aggregate inputs mismatch")
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

    screen = aggregates["all_code_screen"]
    refinement = aggregates["midpattern_refinement"]
    screen_sizes = provenance["corpora"][0]["sizes_mib"]
    refinement_sizes = provenance["corpora"][1]["sizes_mib"]
    screen_endpoints = {code: full_endpoint(screen, code, screen_sizes) for code in range(64)}
    require([code for code, endpoint in screen_endpoints.items() if endpoint == 240] == [0, 63], "240 class mismatch")
    require([code for code, endpoint in screen_endpoints.items() if endpoint == 64] == [21, 42], "screen mid class mismatch")
    require(sum(endpoint == 36 for endpoint in screen_endpoints.values()) == 60, "ordinary class mismatch")
    require(full_endpoint(refinement, 21, refinement_sizes) == 70, "code 21 refinement mismatch")
    require(full_endpoint(refinement, 42, refinement_sizes) == 70, "code 42 refinement mismatch")

    identical_codes = [code for code in range(64) if len(set(packed_words(code))) == 1]
    require(identical_codes == [0, 21, 42, 63], "packing classification mismatch")
    require(
        identical_codes == [code for code, endpoint in screen_endpoints.items() if endpoint > 36],
        "packing/capacity correlation mismatch",
    )

    map_path = repo_path(root, provenance["artifacts"]["map"]["path"])
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    require(mapping["mathematical_layout"]["identical_packed_word_codes"] == identical_codes, "map word class mismatch")
    require(mapping["observed_capacity_classes"]["240_mib_address_limited"] == [0, 63], "map 240 class mismatch")
    require(mapping["observed_capacity_classes"]["70_mib_refined_endpoint"] == [21, 42], "map 70 class mismatch")
    require(len(mapping["observed_capacity_classes"]["36_mib_no_extension"]) == 60, "map 36 class mismatch")
    require(mapping["validation"]["combined"] == {key: value for key, value in combined.items() if key != "mismatches"}, "map totals mismatch")

    rejection_path = repo_path(root, provenance["artifacts"]["texture_rejection"]["path"])
    rejection = json.loads(rejection_path.read_text(encoding="utf-8"))
    rejection_rows = rejection["results"]
    bad = [row for row in rejection_rows if not row["validation"]]
    bad_mismatches = sum(sum(row["mismatch_totals"].values()) for row in rejection_rows)
    zero_texture_valid = sum(
        row["validation"] and row["pattern"] == "uniform6_0" and row["path"] == "texture_object"
        for row in rejection_rows
    )
    texture_spec = provenance["texture_rejection"]
    require(len(rejection_rows) == texture_spec["raw_rows"], "rejection row mismatch")
    require(len(bad) == texture_spec["invalid_nonzero_texture_rows"], "rejection invalid count mismatch")
    require(bad_mismatches == texture_spec["decoded_mismatches"], "rejection mismatch total disagreement")
    require(zero_texture_valid == texture_spec["zero_texture_rows_that_falsely_validate"], "zero sentinel mismatch")
    require({row["path"] for row in bad} == {"texture_object"}, "unexpected invalid path")
    require({row["pattern"] for row in bad} == {"uniform6_1", "uniform6_8", "uniform6_63"}, "unexpected invalid patterns")
    require(not texture_spec["included_in_capacity_evidence"], "rejected texture included")

    print(
        "PASS uniform6 native map: "
        f"64 codes, {combined['raw_rows']} rows, {combined['validated_payloads']} payloads, "
        f"{combined['timed_gpu_lookups']} timed lookups; endpoints 36/70/240 MiB = 60/2/2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
