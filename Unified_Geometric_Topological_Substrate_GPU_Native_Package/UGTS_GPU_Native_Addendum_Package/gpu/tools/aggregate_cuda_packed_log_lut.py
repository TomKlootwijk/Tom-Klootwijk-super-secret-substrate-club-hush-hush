#!/usr/bin/env python3
"""Aggregate isolated native CUDA slot16 versus packed6 log-LUT runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def median(values):
    return statistics.median(values)


def ordered_unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    documents = []
    run_metadata = []
    by_key = defaultdict(list)
    expected_keys = None
    for run_dir in args.runs:
        path = run_dir / "cuda_packed_log_lut_results.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema"] != "UGTS-CUDA-PACKED-LOG-LUT-1.0":
            raise ValueError(f"unexpected schema in {path}")
        documents.append(document)
        keys = set()
        for row in document["results"]:
            key = (row["path"], row["representation"], row["entries"], row["warps"])
            if key in keys:
                raise ValueError(f"duplicate key {key} in {path}")
            keys.add(key)
            by_key[key].append(row)
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise ValueError(f"matrix mismatch in {path}")
        run_metadata.append(
            {
                "directory": run_dir.as_posix(),
                "results_sha256": sha256(path),
                "rows": len(document["results"]),
                "latin_order": document["run_parameters"]["latin_order"],
                "entry_order": ordered_unique(row["entries"] for row in document["results"]),
                "warp_order": ordered_unique(row["warps"] for row in document["results"]),
            }
        )

    first = documents[0]
    for document in documents[1:]:
        if document["device"] != first["device"]:
            raise ValueError("device or occupancy mismatch across runs")
        for field in ("measured_sets", "lookups_per_thread", "eviction_bytes"):
            if document["run_parameters"][field] != first["run_parameters"][field]:
                raise ValueError(f"run parameter mismatch: {field}")

    aggregate_rows = []
    numeric_fields = (
        "table_bytes",
        "table_mib",
        "l2_fraction",
        "bytes_per_code",
        "expected_words_per_lookup",
        "threads",
        "samples",
        "cold_net_cycles_per_lookup",
        "hot_net_cycles_per_lookup",
        "cold_glookups_s",
        "hot_glookups_s",
        "cold_requested_word_gloads_s",
        "hot_requested_word_gloads_s",
    )
    for key in sorted(by_key, key=lambda item: (item[2], item[3], item[0], item[1])):
        rows = by_key[key]
        path, representation, entries, warps = key
        result = {
            "path": path,
            "representation": representation,
            "entries": entries,
            "warps": warps,
            "run_count": len(rows),
        }
        for field in numeric_fields:
            result[f"{field}_median"] = median([row[field] for row in rows])
        for prefix in ("control_cycles", "cold_cycles", "hot_cycles", "cold_kernel_us", "hot_kernel_us"):
            result[f"{prefix}_p50_median"] = median([row[prefix]["p50"] for row in rows])
        result["hot_glookups_s_min"] = min(row["hot_glookups_s"] for row in rows)
        result["hot_glookups_s_max"] = max(row["hot_glookups_s"] for row in rows)
        result["all_runs_valid"] = all(row["validation"] for row in rows)
        aggregate_rows.append(result)

    aggregate_index = {
        (row["path"], row["representation"], row["entries"], row["warps"]): row
        for row in aggregate_rows
    }

    packing_comparison = []
    texture_comparison = []
    for path in ("global_cg", "texture_object"):
        for entries in sorted({key[2] for key in by_key}):
            for warps in sorted({key[3] for key in by_key}):
                slot_raw = by_key[(path, "slot16", entries, warps)]
                packed_raw = by_key[(path, "packed6", entries, warps)]
                hot_ratios = [
                    packed["hot_glookups_s"] / slot["hot_glookups_s"]
                    for slot, packed in zip(slot_raw, packed_raw)
                ]
                cold_ratios = [
                    packed["cold_glookups_s"] / slot["cold_glookups_s"]
                    for slot, packed in zip(slot_raw, packed_raw)
                ]
                packing_comparison.append(
                    {
                        "path": path,
                        "entries": entries,
                        "warps": warps,
                        "slot16_table_bytes": slot_raw[0]["table_bytes"],
                        "packed6_table_bytes": packed_raw[0]["table_bytes"],
                        "density_ratio": slot_raw[0]["table_bytes"] / packed_raw[0]["table_bytes"],
                        "packed_to_slot_hot_rate_ratio_median": median(hot_ratios),
                        "packed_to_slot_hot_rate_ratio_min": min(hot_ratios),
                        "packed_to_slot_hot_rate_ratio_max": max(hot_ratios),
                        "packed_to_slot_cold_rate_ratio_median": median(cold_ratios),
                    }
                )

    for representation in ("slot16", "packed6"):
        for entries in sorted({key[2] for key in by_key}):
            for warps in sorted({key[3] for key in by_key}):
                global_raw = by_key[("global_cg", representation, entries, warps)]
                texture_raw = by_key[("texture_object", representation, entries, warps)]
                ratios = [
                    texture["hot_glookups_s"] / global_row["hot_glookups_s"]
                    for global_row, texture in zip(global_raw, texture_raw)
                ]
                texture_comparison.append(
                    {
                        "representation": representation,
                        "entries": entries,
                        "table_bytes": global_raw[0]["table_bytes"],
                        "warps": warps,
                        "texture_to_global_hot_rate_ratio_median": median(ratios),
                        "texture_to_global_hot_rate_ratio_min": min(ratios),
                        "texture_to_global_hot_rate_ratio_max": max(ratios),
                    }
                )

    full_warps = max(key[3] for key in by_key)
    full_occupancy = []
    for entries in sorted({key[2] for key in by_key}):
        row = {"entries": entries, "warps": full_warps}
        for path, path_short in (("global_cg", "global"), ("texture_object", "texture")):
            for representation in ("slot16", "packed6"):
                item = aggregate_index[(path, representation, entries, full_warps)]
                row[f"{representation}_table_bytes"] = item["table_bytes_median"]
                row[f"{path_short}_{representation}_hot_glookups_s"] = item[
                    "hot_glookups_s_median"
                ]
            row[f"{path_short}_packed_to_slot_hot_ratio"] = (
                row[f"{path_short}_packed6_hot_glookups_s"]
                / row[f"{path_short}_slot16_hot_glookups_s"]
            )
        row["packed6_texture_to_global_hot_ratio"] = (
            row["texture_packed6_hot_glookups_s"]
            / row["global_packed6_hot_glookups_s"]
        )
        full_occupancy.append(row)

    full_by_entries = {row["entries"]: row for row in full_occupancy}
    slot28, packed28 = 14_680_064, 39_146_832
    slot36, slot40 = 18_874_368, 20_971_520
    packed36, packed40 = 50_331_648, 55_924_048

    def drop(before, after, field):
        return 1.0 - full_by_entries[after][field] / full_by_entries[before][field]

    capacity = {
        "density_ratio": 8.0 / 3.0,
        "conservative_28_mib": {
            "slot16_entries": slot28,
            "packed6_measured_entries": packed28,
            "packed6_bytes": full_by_entries[packed28]["packed6_table_bytes"],
            "entry_ratio": packed28 / slot28,
        },
        "nominal_36_mib": {
            "slot16_entries": slot36,
            "packed6_entries": packed36,
            "entry_ratio": packed36 / slot36,
            "global_slot16_hot_glookups_s": full_by_entries[slot36]["global_slot16_hot_glookups_s"],
            "global_packed6_hot_glookups_s": full_by_entries[packed36]["global_packed6_hot_glookups_s"],
            "texture_slot16_hot_glookups_s": full_by_entries[slot36]["texture_slot16_hot_glookups_s"],
            "texture_packed6_hot_glookups_s": full_by_entries[packed36]["texture_packed6_hot_glookups_s"],
            "global_packed36_to_slot36_rate_ratio": full_by_entries[packed36]["global_packed6_hot_glookups_s"] / full_by_entries[slot36]["global_slot16_hot_glookups_s"],
            "texture_packed36_to_slot36_rate_ratio": full_by_entries[packed36]["texture_packed6_hot_glookups_s"] / full_by_entries[slot36]["texture_slot16_hot_glookups_s"],
        },
        "boundary_drop_36_to_40": {
            "global_slot16": drop(slot36, slot40, "global_slot16_hot_glookups_s"),
            "texture_slot16": drop(slot36, slot40, "texture_slot16_hot_glookups_s"),
            "global_packed6": drop(packed36, packed40, "global_packed6_hot_glookups_s"),
            "texture_packed6": drop(packed36, packed40, "texture_packed6_hot_glookups_s"),
        },
    }

    validation = {
        "all_rows_valid": all(row["validation"] for document in documents for row in document["results"]),
        "input_rows": sum(len(document["results"]) for document in documents),
        "aggregate_cases": len(aggregate_rows),
        "packing_paired_cases": len(packing_comparison),
        "texture_paired_cases": len(texture_comparison),
        "validated_payloads": sum(
            row["validated_control"] + row["validated_cold"] + row["validated_hot"]
            for document in documents
            for row in document["results"]
        ),
        "validated_lookup_payloads": sum(
            row["validated_cold"] + row["validated_hot"]
            for document in documents
            for row in document["results"]
        ),
        "per_load_code_checks": sum(
            (row["validated_cold"] + row["validated_hot"])
            * document["run_parameters"]["lookups_per_thread"]
            for document in documents
            for row in document["results"]
        ),
    }

    source = Path("gpu/src/ugts_cuda_packed_log_lut_bench.cu")
    executable = Path("gpu/build-windows/ugts_cuda_packed_log_lut_bench.exe")
    output = {
        "schema": "UGTS-CUDA-PACKED-LOG-LUT-AGGREGATE-1.0",
        "device": first["device"],
        "source": {"path": source.as_posix(), "sha256": sha256(source)},
        "executable": {
            "path": executable.as_posix(),
            "bytes": executable.stat().st_size,
            "sha256": sha256(executable),
        },
        "runs": run_metadata,
        "latin_order_balance": dict(sorted(Counter(run["latin_order"] for run in run_metadata).items())),
        "validation": validation,
        "capacity_summary": capacity,
        "full_occupancy_summary": full_occupancy,
        "packing_comparison": packing_comparison,
        "texture_comparison": texture_comparison,
        "results": aggregate_rows,
        "interpretation": {
            "density": "packed6 uses exactly 0.75 bytes/code versus 2.0 bytes/code for slot16, a 2.666667x entry-density increase.",
            "loads": "Packed extraction performs one u32 fetch for 14/16 code offsets and a second predicated fetch for 2/16 offsets; reported word-request rates are logical, not cache transactions.",
            "boundary": "Both representations are swept at physical 36 and approximately 40 MiB endpoints to test whether packing moves logical capacity without moving the cache boundary.",
            "bounds": "clock64 includes scheduling; CUDA-event rates include kernel overhead; privileged sector and DRAM counters remain unavailable.",
        },
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "cuda_packed_log_lut_aggregate.json"
    json_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    def write_csv(path, rows):
        if not rows:
            return
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write_csv(args.out_dir / "cuda_packed_log_lut_aggregate.csv", aggregate_rows)
    write_csv(args.out_dir / "cuda_packed_log_lut_packing_comparison.csv", packing_comparison)
    write_csv(args.out_dir / "cuda_packed_log_lut_texture_comparison.csv", texture_comparison)
    print(json_path)
    return 0 if validation["all_rows_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
