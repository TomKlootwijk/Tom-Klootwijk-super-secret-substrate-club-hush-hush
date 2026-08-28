#!/usr/bin/env python3
"""Aggregate repeated physical-GPU UGTS and LUT-cache benchmark runs."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, action="append", default=[])
    parser.add_argument("--lut", type=Path, action="append", default=[])
    parser.add_argument("--semantic-check", type=Path, action="append", default=[])
    parser.add_argument("--compact", type=Path, action="append", default=[])
    parser.add_argument("--bounded-compact", type=Path, action="append", default=[])
    parser.add_argument("--capacity-sweep", type=Path, action="append", default=[])
    parser.add_argument("--prethreshold", type=Path, action="append", default=[])
    parser.add_argument("--hot-log-lut", type=Path, action="append", default=[])
    parser.add_argument("--hot-log-control", type=Path, action="append", default=[])
    parser.add_argument("--l2-boundary", type=Path, action="append", default=[])
    parser.add_argument("--cold-lineage", type=Path, action="append", default=[])
    parser.add_argument("--lut-pair", type=Path, action="append", default=[])
    parser.add_argument("--lut-path-control", type=Path, action="append", default=[])
    parser.add_argument("--l2-latency", type=Path)
    parser.add_argument("--cuda-l2-clock", type=Path)
    parser.add_argument("--cuda-l2-mlp", type=Path)
    parser.add_argument("--cuda-texture-lut", type=Path)
    parser.add_argument("--cuda-packed-log-lut", type=Path)
    parser.add_argument("--cuda-l2-stride", type=Path)
    parser.add_argument("--l2-bytes", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.core or not args.lut:
        parser.error("at least one --core and one --lut run are required")

    core_docs = [load(path) for path in args.core]
    lut_docs = [load(path) for path in args.lut]
    semantic_docs = [load(path) for path in args.semantic_check]
    compact_docs = [load(path) for path in args.compact]
    bounded_compact_docs = [load(path) for path in args.bounded_compact]
    capacity_sweep_docs = [load(path) for path in args.capacity_sweep]
    prethreshold_docs = [load(path) for path in args.prethreshold]
    hot_log_lut_docs = [load(path) for path in args.hot_log_lut]
    hot_log_control_docs = [load(path) for path in args.hot_log_control]
    l2_boundary_docs = [load(path) for path in args.l2_boundary]
    cold_lineage_docs = [load(path) for path in args.cold_lineage]
    lut_pair_docs = [load(path) for path in args.lut_pair]
    lut_path_docs = [load(path) for path in args.lut_path_control]
    l2_latency_doc = load(args.l2_latency) if args.l2_latency else None
    cuda_l2_clock_doc = load(args.cuda_l2_clock) if args.cuda_l2_clock else None
    cuda_l2_mlp_doc = load(args.cuda_l2_mlp) if args.cuda_l2_mlp else None
    cuda_texture_lut_doc = load(args.cuda_texture_lut) if args.cuda_texture_lut else None
    cuda_packed_log_lut_doc = load(args.cuda_packed_log_lut) if args.cuda_packed_log_lut else None
    cuda_l2_stride_doc = load(args.cuda_l2_stride) if args.cuda_l2_stride else None
    all_docs = core_docs + lut_docs + semantic_docs + compact_docs + bounded_compact_docs + capacity_sweep_docs + prethreshold_docs + hot_log_lut_docs + hot_log_control_docs + l2_boundary_docs + cold_lineage_docs + lut_pair_docs + lut_path_docs
    if l2_latency_doc:
        all_docs.append(l2_latency_doc)
    if cuda_l2_clock_doc:
        all_docs.append(cuda_l2_clock_doc)
    if cuda_l2_mlp_doc:
        all_docs.append(cuda_l2_mlp_doc)
    if cuda_texture_lut_doc:
        all_docs.append(cuda_texture_lut_doc)
    if cuda_packed_log_lut_doc:
        all_docs.append(cuda_packed_log_lut_doc)
    if cuda_l2_stride_doc:
        all_docs.append(cuda_l2_stride_doc)
    device_names = {doc["device"]["name"] for doc in all_docs}
    if len(device_names) != 1:
        raise SystemExit(f"runs contain multiple devices: {sorted(device_names)}")

    core_groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for doc in core_docs:
        for row in doc["benchmarks"]:
            core_groups[(row["profile"], row["mode"], row["candidates"])].append(row)

    core_rows: list[dict[str, Any]] = []
    for (profile, mode, candidates), rows in sorted(core_groups.items()):
        p50 = [row["device_dispatch_ms"]["p50"] for row in rows]
        rates = [row["candidate_rate_mps"] for row in rows]
        event_rates = [row["verified_event_rate_mps"] for row in rows]
        bandwidths = [row["effective_bandwidth_gbps"] for row in rows]
        confidence_max = [row.get("confidence_abs_error_max", 0.0) for row in rows]
        confidence_mean = [row.get("confidence_abs_error_mean", 0.0) for row in rows]
        working_set = rows[0]["total_buffer_bytes"]
        core_rows.append(
            {
                "profile": profile,
                "mode": mode,
                "candidates": candidates,
                "replicates": len(rows),
                "working_set_bytes": working_set,
                "working_set_l2_fraction": working_set / args.l2_bytes,
                "auxiliary_lut_bytes": rows[0].get("auxiliary_lut_bytes", 0),
                "device_p50_ms_median": median(p50),
                "device_p50_ms_min": min(p50),
                "device_p50_ms_max": max(p50),
                "candidate_rate_mps_median": median(rates),
                "candidate_rate_mps_min": min(rates),
                "candidate_rate_mps_max": max(rates),
                "verified_event_rate_mps_median": median(event_rates),
                "logical_bandwidth_gbps_median": median(bandwidths),
                "confidence_abs_error_max": max(confidence_max),
                "confidence_abs_error_mean_median": median(confidence_mean),
                "gpu_counts": rows[0]["counts"],
                "oracle_counts": rows[0]["oracle_counts"],
                "boundary_divergent_outputs": rows[0]["boundary_divergent_outputs"],
                "all_outputs_validated": all(
                    row["validated_outputs"] == candidates and row["sample_validation"]
                    for row in rows
                ),
                "all_commit_counters_validated": all(row["counter_validation"] for row in rows),
            }
        )

    paired_groups: dict[tuple[str, int], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for doc in core_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for (profile, mode, candidates), direct in by_key.items():
            if profile != "G32_E16":
                continue
            lut = by_key.get(("G32_E16_LUT", mode, candidates))
            if lut is not None:
                paired_groups[(mode, candidates)].append((direct, lut))

    semantic_hash_checks: dict[tuple[str, int], list[bool]] = defaultdict(list)
    for doc in semantic_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for (profile, mode, candidates), direct in by_key.items():
            if profile != "G32_E16":
                continue
            lut = by_key.get(("G32_E16_LUT", mode, candidates))
            if lut is not None and "discrete_semantic_hash" in direct and "discrete_semantic_hash" in lut:
                semantic_hash_checks[(mode, candidates)].append(
                    direct["discrete_semantic_hash"] == lut["discrete_semantic_hash"]
                )

    integrated_lut_rows: list[dict[str, Any]] = []
    for (mode, candidates), pairs in sorted(paired_groups.items()):
        rate_ratios = [lut["candidate_rate_mps"] / direct["candidate_rate_mps"] for direct, lut in pairs]
        latency_ratios = [lut["device_dispatch_ms"]["p50"] / direct["device_dispatch_ms"]["p50"] for direct, lut in pairs]
        hash_results = semantic_hash_checks.get((mode, candidates), [])
        integrated_lut_rows.append(
            {
                "mode": mode,
                "candidates": candidates,
                "state_event_bytes": pairs[0][0]["candidates"] * (pairs[0][0]["input_record_bytes"] + pairs[0][0]["output_record_bytes"]),
                "state_event_l2_fraction": pairs[0][0]["candidates"] * (pairs[0][0]["input_record_bytes"] + pairs[0][0]["output_record_bytes"]) / args.l2_bytes,
                "lut_bytes": pairs[0][1].get("auxiliary_lut_bytes", 0),
                "replicates": len(pairs),
                "direct_device_p50_ms_median": median([direct["device_dispatch_ms"]["p50"] for direct, _ in pairs]),
                "lut_device_p50_ms_median": median([lut["device_dispatch_ms"]["p50"] for _, lut in pairs]),
                "lut_to_direct_rate_ratio_median": median(rate_ratios),
                "lut_to_direct_rate_ratio_min": min(rate_ratios),
                "lut_to_direct_rate_ratio_max": max(rate_ratios),
                "lut_over_direct_rate_percent_median": (median(rate_ratios) - 1.0) * 100.0,
                "lut_to_direct_latency_ratio_median": median(latency_ratios),
                "direct_confidence_abs_error_max": max(direct.get("confidence_abs_error_max", 0.0) for direct, _ in pairs),
                "lut_confidence_abs_error_max": max(lut.get("confidence_abs_error_max", 0.0) for _, lut in pairs),
                "all_discrete_counts_match": all(direct["counts"] == lut["counts"] for direct, lut in pairs),
                "semantic_hash_checks": len(hash_results),
                "all_semantic_hashes_match": all(hash_results) if hash_results else None,
            }
        )

    paired_lut_groups: dict[tuple[str, int], list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in lut_pair_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            for mode in ("evaluate", "evaluate_commit"):
                keys = {
                    "direct": ("G32_E16", mode, candidates),
                    "two_fetch": ("G32_E16_LUT", mode, candidates),
                    "one_fetch": ("G32_E16_LUT_PAIR", mode, candidates),
                }
                if all(key in by_key for key in keys.values()):
                    paired_lut_groups[(mode, candidates)].append({name: by_key[key] for name, key in keys.items()})

    paired_lut_rows: list[dict[str, Any]] = []
    for (mode, candidates), groups in sorted(paired_lut_groups.items()):
        two_direct = [group["two_fetch"]["candidate_rate_mps"] / group["direct"]["candidate_rate_mps"] for group in groups]
        one_direct = [group["one_fetch"]["candidate_rate_mps"] / group["direct"]["candidate_rate_mps"] for group in groups]
        one_two = [group["one_fetch"]["candidate_rate_mps"] / group["two_fetch"]["candidate_rate_mps"] for group in groups]
        paired_lut_rows.append(
            {
                "mode": mode,
                "candidates": candidates,
                "state_event_l2_fraction": candidates * (groups[0]["direct"]["input_record_bytes"] + groups[0]["direct"]["output_record_bytes"]) / args.l2_bytes,
                "replicates": len(groups),
                "two_fetch_lut_bytes": groups[0]["two_fetch"]["auxiliary_lut_bytes"],
                "one_fetch_lut_bytes": groups[0]["one_fetch"]["auxiliary_lut_bytes"],
                "direct_p50_ms_median": median([group["direct"]["device_dispatch_ms"]["p50"] for group in groups]),
                "two_fetch_p50_ms_median": median([group["two_fetch"]["device_dispatch_ms"]["p50"] for group in groups]),
                "one_fetch_p50_ms_median": median([group["one_fetch"]["device_dispatch_ms"]["p50"] for group in groups]),
                "two_fetch_to_direct_rate_ratio_median": median(two_direct),
                "two_fetch_to_direct_rate_ratio_min": min(two_direct),
                "two_fetch_to_direct_rate_ratio_max": max(two_direct),
                "one_fetch_to_direct_rate_ratio_median": median(one_direct),
                "one_fetch_to_direct_rate_ratio_min": min(one_direct),
                "one_fetch_to_direct_rate_ratio_max": max(one_direct),
                "one_fetch_to_two_fetch_rate_ratio_median": median(one_two),
                "one_fetch_to_two_fetch_rate_ratio_min": min(one_two),
                "one_fetch_to_two_fetch_rate_ratio_max": max(one_two),
                "one_fetch_confidence_abs_error_max": max(group["one_fetch"]["confidence_abs_error_max"] for group in groups),
                "all_discrete_counts_match": all(group["direct"]["counts"] == group["two_fetch"]["counts"] == group["one_fetch"]["counts"] for group in groups),
                "all_outputs_validated": all(group[name]["sample_validation"] for group in groups for name in ("direct", "two_fetch", "one_fetch")),
            }
        )

    compact_groups: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in compact_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            keys = {
                "dense_evaluate": ("G32_E16", "evaluate", candidates),
                "dense_commit": ("G32_E16", "evaluate_commit", candidates),
                "compact_append": ("G32_E16_COMPACT", "append", candidates),
                "compact_append_counts": ("G32_E16_COMPACT", "append_counts", candidates),
            }
            if all(key in by_key for key in keys.values()):
                group = {name: by_key[key] for name, key in keys.items()}
                subgroup_keys = {
                    "subgroup_append": ("G32_E16_SUBGROUP_COMPACT", "append", candidates),
                    "subgroup_append_counts": ("G32_E16_SUBGROUP_COMPACT", "append_counts", candidates),
                }
                for name, key in subgroup_keys.items():
                    if key in by_key:
                        group[name] = by_key[key]
                compact_groups[candidates].append(group)

    compaction_rows: list[dict[str, Any]] = []
    for candidates, groups in sorted(compact_groups.items()):
        append_ratios = [group["compact_append"]["candidate_rate_mps"] / group["dense_evaluate"]["candidate_rate_mps"] for group in groups]
        counted_ratios = [group["compact_append_counts"]["candidate_rate_mps"] / group["dense_commit"]["candidate_rate_mps"] for group in groups]
        compact_events = groups[0]["compact_append"]["output_events"]
        dense_output_bytes = candidates * groups[0]["dense_evaluate"]["output_record_bytes"]
        compact_output_bytes = groups[0]["compact_append"]["logical_output_bytes"]
        state_bytes = candidates * groups[0]["dense_evaluate"]["input_record_bytes"]
        row = {
                "candidates": candidates,
                "replicates": len(groups),
                "verified_events": compact_events,
                "event_yield": compact_events / candidates,
                "dense_output_bytes": dense_output_bytes,
                "compact_output_bytes": compact_output_bytes,
                "output_compression_ratio": dense_output_bytes / compact_output_bytes,
                "state_plus_output_compression_ratio": (state_bytes + dense_output_bytes) / (state_bytes + compact_output_bytes),
                "dense_evaluate_p50_ms_median": median([group["dense_evaluate"]["device_dispatch_ms"]["p50"] for group in groups]),
                "compact_append_p50_ms_median": median([group["compact_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "compact_append_to_dense_rate_ratio_median": median(append_ratios),
                "compact_append_to_dense_rate_ratio_min": min(append_ratios),
                "compact_append_to_dense_rate_ratio_max": max(append_ratios),
                "dense_commit_p50_ms_median": median([group["dense_commit"]["device_dispatch_ms"]["p50"] for group in groups]),
                "compact_append_counts_p50_ms_median": median([group["compact_append_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "compact_append_counts_to_dense_commit_rate_ratio_median": median(counted_ratios),
                "compact_append_counts_to_dense_commit_rate_ratio_min": min(counted_ratios),
                "compact_append_counts_to_dense_commit_rate_ratio_max": max(counted_ratios),
                "all_compact_outputs_validated": all(
                    group[name]["validated_outputs"] == group[name]["output_events"]
                    and group[name]["sample_validation"]
                    for group in groups
                    for name in ("compact_append", "compact_append_counts")
                ),
                "all_compact_counters_validated": all(
                    group[name]["counter_validation"]
                    for group in groups
                    for name in ("compact_append", "compact_append_counts")
                ),
            }
        if all("subgroup_append" in group and "subgroup_append_counts" in group for group in groups):
            subgroup_append_ratios = [group["subgroup_append"]["candidate_rate_mps"] / group["dense_evaluate"]["candidate_rate_mps"] for group in groups]
            subgroup_counted_ratios = [group["subgroup_append_counts"]["candidate_rate_mps"] / group["dense_commit"]["candidate_rate_mps"] for group in groups]
            subgroup_vs_atomic = [group["subgroup_append"]["candidate_rate_mps"] / group["compact_append"]["candidate_rate_mps"] for group in groups]
            subgroup_counted_vs_atomic = [group["subgroup_append_counts"]["candidate_rate_mps"] / group["compact_append_counts"]["candidate_rate_mps"] for group in groups]
            row.update(
                {
                    "subgroup_append_p50_ms_median": median([group["subgroup_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                    "subgroup_append_to_dense_rate_ratio_median": median(subgroup_append_ratios),
                    "subgroup_append_to_dense_rate_ratio_min": min(subgroup_append_ratios),
                    "subgroup_append_to_dense_rate_ratio_max": max(subgroup_append_ratios),
                    "subgroup_append_to_atomic_append_rate_ratio_median": median(subgroup_vs_atomic),
                    "subgroup_append_counts_p50_ms_median": median([group["subgroup_append_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                    "subgroup_append_counts_to_dense_commit_rate_ratio_median": median(subgroup_counted_ratios),
                    "subgroup_append_counts_to_dense_commit_rate_ratio_min": min(subgroup_counted_ratios),
                    "subgroup_append_counts_to_dense_commit_rate_ratio_max": max(subgroup_counted_ratios),
                    "subgroup_append_counts_to_atomic_rate_ratio_median": median(subgroup_counted_vs_atomic),
                    "all_subgroup_outputs_validated": all(
                        group[name]["validated_outputs"] == group[name]["output_events"]
                        and group[name]["sample_validation"]
                        and group[name]["counter_validation"]
                        for group in groups
                        for name in ("subgroup_append", "subgroup_append_counts")
                    ),
                }
            )
        compaction_rows.append(row)

    bounded_groups: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in bounded_compact_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            keys = {
                "dense_evaluate": ("G32_E16", "evaluate", candidates),
                "dense_commit": ("G32_E16", "evaluate_commit", candidates),
                "subgroup_append": ("G32_E16_SUBGROUP_COMPACT", "append", candidates),
                "subgroup_append_counts": ("G32_E16_SUBGROUP_COMPACT", "append_counts", candidates),
            }
            if all(key in by_key for key in keys.values()):
                bounded_groups[candidates].append({name: by_key[key] for name, key in keys.items()})

    bounded_compaction_rows: list[dict[str, Any]] = []
    for candidates, groups in sorted(bounded_groups.items()):
        append_ratios = [group["subgroup_append"]["candidate_rate_mps"] / group["dense_evaluate"]["candidate_rate_mps"] for group in groups]
        counted_ratios = [group["subgroup_append_counts"]["candidate_rate_mps"] / group["dense_commit"]["candidate_rate_mps"] for group in groups]
        sample = groups[0]["subgroup_append"]
        dense_output_bytes = candidates * groups[0]["dense_evaluate"]["output_record_bytes"]
        state_bytes = candidates * groups[0]["dense_evaluate"]["input_record_bytes"]
        allocated_output_bytes = sample["allocated_output_bytes"]
        logical_output_bytes = sample["logical_output_bytes"]
        bounded_compaction_rows.append(
            {
                "candidates": candidates,
                "replicates": len(groups),
                "capacity_ratio": sample["output_capacity_events"] / candidates,
                "output_capacity_events": sample["output_capacity_events"],
                "verified_events": sample["counts"]["verified"],
                "event_yield": sample["counts"]["verified"] / candidates,
                "overflow_events": max(group["subgroup_append"]["overflow_events"] for group in groups),
                "dense_output_bytes": dense_output_bytes,
                "allocated_output_bytes": allocated_output_bytes,
                "logical_output_bytes": logical_output_bytes,
                "output_allocation_reduction_ratio": dense_output_bytes / allocated_output_bytes,
                "output_stream_reduction_ratio": dense_output_bytes / logical_output_bytes,
                "state_plus_allocated_reduction_ratio": (state_bytes + dense_output_bytes) / (state_bytes + allocated_output_bytes),
                "state_plus_logical_reduction_ratio": (state_bytes + dense_output_bytes) / (state_bytes + logical_output_bytes),
                "dense_evaluate_p50_ms_median": median([group["dense_evaluate"]["device_dispatch_ms"]["p50"] for group in groups]),
                "subgroup_append_p50_ms_median": median([group["subgroup_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "subgroup_append_to_dense_rate_ratio_median": median(append_ratios),
                "subgroup_append_to_dense_rate_ratio_min": min(append_ratios),
                "subgroup_append_to_dense_rate_ratio_max": max(append_ratios),
                "dense_commit_p50_ms_median": median([group["dense_commit"]["device_dispatch_ms"]["p50"] for group in groups]),
                "subgroup_append_counts_p50_ms_median": median([group["subgroup_append_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "subgroup_append_counts_to_dense_commit_rate_ratio_median": median(counted_ratios),
                "subgroup_append_counts_to_dense_commit_rate_ratio_min": min(counted_ratios),
                "subgroup_append_counts_to_dense_commit_rate_ratio_max": max(counted_ratios),
                "all_retained_outputs_validated": all(
                    group[name]["validated_outputs"] == group[name]["output_events"]
                    and group[name]["sample_validation"]
                    for group in groups
                    for name in ("subgroup_append", "subgroup_append_counts")
                ),
                "all_outputs_complete": all(
                    group[name]["completeness_validation"]
                    for group in groups
                    for name in ("subgroup_append", "subgroup_append_counts")
                ),
                "all_overflow_checks_validated": all(
                    group[name]["overflow_validation"]
                    for group in groups
                    for name in ("subgroup_append", "subgroup_append_counts")
                ),
                "all_counters_validated": all(
                    group[name]["counter_validation"]
                    for group in groups
                    for name in ("subgroup_append", "subgroup_append_counts")
                ),
            }
        )

    capacity_sweep_rows: list[dict[str, Any]] = []
    for doc in sorted(capacity_sweep_docs, key=lambda item: item["run_parameters"]["compact_capacity_ratio"]):
        ratio = doc["run_parameters"]["compact_capacity_ratio"]
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            append = by_key.get(("G32_E16_SUBGROUP_COMPACT", "append", candidates))
            counted = by_key.get(("G32_E16_SUBGROUP_COMPACT", "append_counts", candidates))
            dense = by_key.get(("G32_E16", "evaluate", candidates))
            if append is None or counted is None or dense is None:
                continue
            dense_output_bytes = candidates * dense["output_record_bytes"]
            capacity_sweep_rows.append(
                {
                    "candidates": candidates,
                    "capacity_ratio": ratio,
                    "capacity_events": append["output_capacity_events"],
                    "verified_demand": append["counts"]["verified"],
                    "retained_events": append["output_events"],
                    "headroom_events": append["output_capacity_events"] - append["counts"]["verified"],
                    "overflow_events": append["overflow_events"],
                    "allocated_output_bytes": append["allocated_output_bytes"],
                    "output_allocation_reduction_ratio": dense_output_bytes / append["allocated_output_bytes"],
                    "subgroup_append_p50_ms": append["device_dispatch_ms"]["p50"],
                    "subgroup_append_counts_p50_ms": counted["device_dispatch_ms"]["p50"],
                    "lossless_for_corpus": append["overflow_events"] == 0,
                    "retained_outputs_validated": append["sample_validation"] and counted["sample_validation"],
                    "overflow_demand_validated": append["overflow_validation"] and counted["overflow_validation"],
                    "completeness_validated": append["completeness_validation"] and counted["completeness_validation"],
                    "counters_validated": append["counter_validation"] and counted["counter_validation"],
                }
            )

    prethreshold_groups: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in prethreshold_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            keys = {
                "original_append": ("G32_E16_SUBGROUP_COMPACT", "append", candidates),
                "original_counts": ("G32_E16_SUBGROUP_COMPACT", "append_counts", candidates),
                "prethreshold_append": ("G32_E16_PRETHRESHOLD_SUBGROUP_COMPACT", "append", candidates),
                "prethreshold_counts": ("G32_E16_PRETHRESHOLD_SUBGROUP_COMPACT", "append_counts", candidates),
            }
            if all(key in by_key for key in keys.values()):
                prethreshold_groups[candidates].append({name: by_key[key] for name, key in keys.items()})

    prethreshold_rows: list[dict[str, Any]] = []
    for candidates, groups in sorted(prethreshold_groups.items()):
        append_ratios = [group["prethreshold_append"]["candidate_rate_mps"] / group["original_append"]["candidate_rate_mps"] for group in groups]
        counted_ratios = [group["prethreshold_counts"]["candidate_rate_mps"] / group["original_counts"]["candidate_rate_mps"] for group in groups]
        prethreshold_rows.append(
            {
                "candidates": candidates,
                "replicates": len(groups),
                "original_append_p50_ms_median": median([group["original_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "prethreshold_append_p50_ms_median": median([group["prethreshold_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "prethreshold_to_original_append_rate_ratio_median": median(append_ratios),
                "prethreshold_to_original_append_rate_ratio_min": min(append_ratios),
                "prethreshold_to_original_append_rate_ratio_max": max(append_ratios),
                "original_counts_p50_ms_median": median([group["original_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "prethreshold_counts_p50_ms_median": median([group["prethreshold_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "prethreshold_to_original_counts_rate_ratio_median": median(counted_ratios),
                "prethreshold_to_original_counts_rate_ratio_min": min(counted_ratios),
                "prethreshold_to_original_counts_rate_ratio_max": max(counted_ratios),
                "all_discrete_counts_match": all(
                    group["original_append"]["counts"] == group["prethreshold_append"]["counts"]
                    and group["original_counts"]["counts"] == group["prethreshold_counts"]["counts"]
                    for group in groups
                ),
                "all_outputs_validated": all(
                    group[name]["sample_validation"]
                    and group[name]["counter_validation"]
                    and group[name]["completeness_validation"]
                    and group[name]["overflow_validation"]
                    for group in groups
                    for name in ("original_append", "original_counts", "prethreshold_append", "prethreshold_counts")
                ),
            }
        )

    hot_log_groups: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in hot_log_lut_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            keys = {
                "g32_append": ("G32_E16_SUBGROUP_COMPACT", "append", candidates),
                "g32_counts": ("G32_E16_SUBGROUP_COMPACT", "append_counts", candidates),
                "g24_append": ("G24_E16_LOGTHRESH_SUBGROUP_COMPACT", "append", candidates),
                "g24_counts": ("G24_E16_LOGTHRESH_SUBGROUP_COMPACT", "append_counts", candidates),
            }
            if all(key in by_key for key in keys.values()):
                hot_log_groups[candidates].append({name: by_key[key] for name, key in keys.items()})

    hot_log_rows: list[dict[str, Any]] = []
    for candidates, groups in sorted(hot_log_groups.items()):
        append_ratios = [group["g24_append"]["candidate_rate_mps"] / group["g32_append"]["candidate_rate_mps"] for group in groups]
        counted_ratios = [group["g24_counts"]["candidate_rate_mps"] / group["g32_counts"]["candidate_rate_mps"] for group in groups]
        g32 = groups[0]["g32_append"]
        g24 = groups[0]["g24_append"]
        g32_resident_bytes = candidates * g32["input_record_bytes"] + g32["allocated_output_bytes"]
        g24_resident_bytes = candidates * g24["input_record_bytes"] + g24["allocated_output_bytes"] + g24["auxiliary_lut_bytes"]
        hot_log_rows.append(
            {
                "candidates": candidates,
                "replicates": len(groups),
                "g32_input_record_bytes": g32["input_record_bytes"],
                "g24_input_record_bytes": g24["input_record_bytes"],
                "state_record_reduction_ratio": g32["input_record_bytes"] / g24["input_record_bytes"],
                "log_threshold_lut_bytes": g24["auxiliary_lut_bytes"],
                "g32_state_plus_allocated_bytes": g32_resident_bytes,
                "g24_state_plus_allocated_lut_bytes": g24_resident_bytes,
                "resident_allocation_reduction_ratio": g32_resident_bytes / g24_resident_bytes,
                "g32_resident_l2_fraction": g32_resident_bytes / args.l2_bytes,
                "g24_resident_l2_fraction": g24_resident_bytes / args.l2_bytes,
                "g32_append_p50_ms_median": median([group["g32_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_append_p50_ms_median": median([group["g24_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_to_g32_append_rate_ratio_median": median(append_ratios),
                "g24_to_g32_append_rate_ratio_min": min(append_ratios),
                "g24_to_g32_append_rate_ratio_max": max(append_ratios),
                "g32_counts_p50_ms_median": median([group["g32_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_counts_p50_ms_median": median([group["g24_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_to_g32_counts_rate_ratio_median": median(counted_ratios),
                "g24_to_g32_counts_rate_ratio_min": min(counted_ratios),
                "g24_to_g32_counts_rate_ratio_max": max(counted_ratios),
                "g24_confidence_abs_error_max": max(group["g24_append"]["confidence_abs_error_max"] for group in groups),
                "all_discrete_counts_match": all(
                    group["g32_append"]["counts"] == group["g24_append"]["counts"]
                    and group["g32_counts"]["counts"] == group["g24_counts"]["counts"]
                    for group in groups
                ),
                "all_outputs_validated": all(
                    group[name]["sample_validation"]
                    and group[name]["counter_validation"]
                    and group[name]["completeness_validation"]
                    and group[name]["overflow_validation"]
                    for group in groups
                    for name in ("g32_append", "g32_counts", "g24_append", "g24_counts")
                ),
            }
        )

    hot_log_control_groups: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in hot_log_control_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            keys = {
                "g32_append": ("G32_E16_SUBGROUP_COMPACT", "append", candidates),
                "g32_counts": ("G32_E16_SUBGROUP_COMPACT", "append_counts", candidates),
                "direct_append": ("G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT", "append", candidates),
                "direct_counts": ("G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT", "append_counts", candidates),
                "lut_append": ("G24_E16_LOGTHRESH_SUBGROUP_COMPACT", "append", candidates),
                "lut_counts": ("G24_E16_LOGTHRESH_SUBGROUP_COMPACT", "append_counts", candidates),
            }
            if all(key in by_key for key in keys.values()):
                hot_log_control_groups[candidates].append({name: by_key[key] for name, key in keys.items()})

    hot_log_control_rows: list[dict[str, Any]] = []
    for candidates, groups in sorted(hot_log_control_groups.items()):
        direct_to_g32_append = [group["direct_append"]["candidate_rate_mps"] / group["g32_append"]["candidate_rate_mps"] for group in groups]
        lut_to_g32_append = [group["lut_append"]["candidate_rate_mps"] / group["g32_append"]["candidate_rate_mps"] for group in groups]
        lut_to_direct_append = [group["lut_append"]["candidate_rate_mps"] / group["direct_append"]["candidate_rate_mps"] for group in groups]
        direct_to_g32_counts = [group["direct_counts"]["candidate_rate_mps"] / group["g32_counts"]["candidate_rate_mps"] for group in groups]
        lut_to_g32_counts = [group["lut_counts"]["candidate_rate_mps"] / group["g32_counts"]["candidate_rate_mps"] for group in groups]
        lut_to_direct_counts = [group["lut_counts"]["candidate_rate_mps"] / group["direct_counts"]["candidate_rate_mps"] for group in groups]
        g32 = groups[0]["g32_append"]
        direct = groups[0]["direct_append"]
        lut = groups[0]["lut_append"]
        g32_resident_bytes = candidates * g32["input_record_bytes"] + g32["allocated_output_bytes"]
        direct_resident_bytes = candidates * direct["input_record_bytes"] + direct["allocated_output_bytes"]
        lut_resident_bytes = candidates * lut["input_record_bytes"] + lut["allocated_output_bytes"] + lut["auxiliary_lut_bytes"]
        names = ("g32_append", "g32_counts", "direct_append", "direct_counts", "lut_append", "lut_counts")
        hot_log_control_rows.append(
            {
                "candidates": candidates,
                "replicates": len(groups),
                "g32_input_record_bytes": g32["input_record_bytes"],
                "g24_input_record_bytes": direct["input_record_bytes"],
                "state_record_reduction_ratio": g32["input_record_bytes"] / direct["input_record_bytes"],
                "log_threshold_lut_bytes": lut["auxiliary_lut_bytes"],
                "g32_state_plus_allocated_bytes": g32_resident_bytes,
                "g24_direct_state_plus_allocated_bytes": direct_resident_bytes,
                "g24_lut_state_plus_allocated_lut_bytes": lut_resident_bytes,
                "direct_resident_allocation_reduction_ratio": g32_resident_bytes / direct_resident_bytes,
                "lut_resident_allocation_reduction_ratio": g32_resident_bytes / lut_resident_bytes,
                "g32_resident_l2_fraction": g32_resident_bytes / args.l2_bytes,
                "g24_direct_resident_l2_fraction": direct_resident_bytes / args.l2_bytes,
                "g24_lut_resident_l2_fraction": lut_resident_bytes / args.l2_bytes,
                "g32_append_p50_ms_median": median([group["g32_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_direct_append_p50_ms_median": median([group["direct_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_lut_append_p50_ms_median": median([group["lut_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "direct_to_g32_append_rate_ratio_median": median(direct_to_g32_append),
                "direct_to_g32_append_rate_ratio_min": min(direct_to_g32_append),
                "direct_to_g32_append_rate_ratio_max": max(direct_to_g32_append),
                "lut_to_g32_append_rate_ratio_median": median(lut_to_g32_append),
                "lut_to_g32_append_rate_ratio_min": min(lut_to_g32_append),
                "lut_to_g32_append_rate_ratio_max": max(lut_to_g32_append),
                "lut_to_direct_append_rate_ratio_median": median(lut_to_direct_append),
                "lut_to_direct_append_rate_ratio_min": min(lut_to_direct_append),
                "lut_to_direct_append_rate_ratio_max": max(lut_to_direct_append),
                "g32_counts_p50_ms_median": median([group["g32_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_direct_counts_p50_ms_median": median([group["direct_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_lut_counts_p50_ms_median": median([group["lut_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "direct_to_g32_counts_rate_ratio_median": median(direct_to_g32_counts),
                "direct_to_g32_counts_rate_ratio_min": min(direct_to_g32_counts),
                "direct_to_g32_counts_rate_ratio_max": max(direct_to_g32_counts),
                "lut_to_g32_counts_rate_ratio_median": median(lut_to_g32_counts),
                "lut_to_g32_counts_rate_ratio_min": min(lut_to_g32_counts),
                "lut_to_g32_counts_rate_ratio_max": max(lut_to_g32_counts),
                "lut_to_direct_counts_rate_ratio_median": median(lut_to_direct_counts),
                "lut_to_direct_counts_rate_ratio_min": min(lut_to_direct_counts),
                "lut_to_direct_counts_rate_ratio_max": max(lut_to_direct_counts),
                "g24_confidence_abs_error_max": max(group[name]["confidence_abs_error_max"] for group in groups for name in ("direct_append", "lut_append")),
                "all_discrete_counts_match": all(
                    group["g32_append"]["counts"] == group["direct_append"]["counts"] == group["lut_append"]["counts"]
                    and group["g32_counts"]["counts"] == group["direct_counts"]["counts"] == group["lut_counts"]["counts"]
                    for group in groups
                ),
                "all_outputs_validated": all(
                    group[name]["sample_validation"]
                    and group[name]["counter_validation"]
                    and group[name]["completeness_validation"]
                    and group[name]["overflow_validation"]
                    for group in groups
                    for name in names
                ),
            }
        )

    l2_boundary_groups: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in l2_boundary_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            keys = {
                "g32_counts": ("G32_E16_SUBGROUP_COMPACT", "append_counts", candidates),
                "direct_counts": ("G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT", "append_counts", candidates),
                "lut_counts": ("G24_E16_LOGTHRESH_SUBGROUP_COMPACT", "append_counts", candidates),
            }
            if all(key in by_key for key in keys.values()):
                l2_boundary_groups[candidates].append({name: by_key[key] for name, key in keys.items()})

    l2_boundary_rows: list[dict[str, Any]] = []
    for candidates, groups in sorted(l2_boundary_groups.items()):
        g32 = groups[0]["g32_counts"]
        direct = groups[0]["direct_counts"]
        lut = groups[0]["lut_counts"]
        g32_bytes = candidates * g32["input_record_bytes"] + g32["allocated_output_bytes"]
        direct_bytes = candidates * direct["input_record_bytes"] + direct["allocated_output_bytes"]
        lut_bytes = candidates * lut["input_record_bytes"] + lut["allocated_output_bytes"] + lut["auxiliary_lut_bytes"]
        direct_to_g32 = [group["direct_counts"]["candidate_rate_mps"] / group["g32_counts"]["candidate_rate_mps"] for group in groups]
        lut_to_direct = [group["lut_counts"]["candidate_rate_mps"] / group["direct_counts"]["candidate_rate_mps"] for group in groups]
        names = ("g32_counts", "direct_counts", "lut_counts")
        l2_boundary_rows.append(
            {
                "candidates": candidates,
                "replicates": len(groups),
                "g32_state_plus_allocated_bytes": g32_bytes,
                "g32_resident_l2_fraction": g32_bytes / args.l2_bytes,
                "g24_direct_state_plus_allocated_bytes": direct_bytes,
                "g24_direct_resident_l2_fraction": direct_bytes / args.l2_bytes,
                "g24_lut_state_plus_allocated_lut_bytes": lut_bytes,
                "g24_lut_resident_l2_fraction": lut_bytes / args.l2_bytes,
                "g32_counts_p50_ms_median": median([group["g32_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g32_counts_candidate_rate_mps_median": median([group["g32_counts"]["candidate_rate_mps"] for group in groups]),
                "g24_direct_counts_p50_ms_median": median([group["direct_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_direct_counts_candidate_rate_mps_median": median([group["direct_counts"]["candidate_rate_mps"] for group in groups]),
                "g24_lut_counts_p50_ms_median": median([group["lut_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g24_lut_counts_candidate_rate_mps_median": median([group["lut_counts"]["candidate_rate_mps"] for group in groups]),
                "direct_to_g32_counts_rate_ratio_median": median(direct_to_g32),
                "direct_to_g32_counts_rate_ratio_min": min(direct_to_g32),
                "direct_to_g32_counts_rate_ratio_max": max(direct_to_g32),
                "lut_to_direct_counts_rate_ratio_median": median(lut_to_direct),
                "all_discrete_counts_match": all(
                    group["g32_counts"]["counts"] == group["direct_counts"]["counts"] == group["lut_counts"]["counts"]
                    for group in groups
                ),
                "all_outputs_validated": all(
                    group[name]["sample_validation"]
                    and group[name]["counter_validation"]
                    and group[name]["completeness_validation"]
                    and group[name]["overflow_validation"]
                    for group in groups
                    for name in names
                ),
            }
        )

    for index, row in enumerate(l2_boundary_rows):
        if index == 0:
            row["g32_rate_ratio_vs_previous_size"] = None
            row["g24_direct_rate_ratio_vs_previous_size"] = None
            row["g24_lut_rate_ratio_vs_previous_size"] = None
        else:
            previous = l2_boundary_rows[index - 1]
            row["g32_rate_ratio_vs_previous_size"] = row["g32_counts_candidate_rate_mps_median"] / previous["g32_counts_candidate_rate_mps_median"]
            row["g24_direct_rate_ratio_vs_previous_size"] = row["g24_direct_counts_candidate_rate_mps_median"] / previous["g24_direct_counts_candidate_rate_mps_median"]
            row["g24_lut_rate_ratio_vs_previous_size"] = row["g24_lut_counts_candidate_rate_mps_median"] / previous["g24_lut_counts_candidate_rate_mps_median"]

    cold_lineage_groups: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in cold_lineage_docs:
        by_key = {
            (row["profile"], row["mode"], row["candidates"]): row
            for row in doc["benchmarks"]
        }
        for candidates in sorted({key[2] for key in by_key}):
            keys = {
                "g24_append": ("G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT", "append", candidates),
                "g24_counts": ("G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT", "append_counts", candidates),
                "g20_append": ("G20_E16_LOGTHRESH_DIRECT_COLD_LINEAGE_SUBGROUP_COMPACT", "append", candidates),
                "g20_counts": ("G20_E16_LOGTHRESH_DIRECT_COLD_LINEAGE_SUBGROUP_COMPACT", "append_counts", candidates),
            }
            if all(key in by_key for key in keys.values()):
                cold_lineage_groups[candidates].append({name: by_key[key] for name, key in keys.items()})

    cold_lineage_rows: list[dict[str, Any]] = []
    for candidates, groups in sorted(cold_lineage_groups.items()):
        g24 = groups[0]["g24_append"]
        g20 = groups[0]["g20_append"]
        g24_hot_bytes = candidates * g24["input_record_bytes"] + g24["allocated_output_bytes"]
        g20_hot_bytes = candidates * g20["input_record_bytes"] + g20["allocated_output_bytes"]
        g20_cold_bytes = g20["cold_lineage_bytes"]
        g20_total_bytes = g20_hot_bytes + g20_cold_bytes
        g24_total_bytes = g24_hot_bytes + g24.get("cold_lineage_bytes", 0)
        append_ratios = [group["g20_append"]["candidate_rate_mps"] / group["g24_append"]["candidate_rate_mps"] for group in groups]
        counted_ratios = [group["g20_counts"]["candidate_rate_mps"] / group["g24_counts"]["candidate_rate_mps"] for group in groups]
        names = ("g24_append", "g24_counts", "g20_append", "g20_counts")
        cold_lineage_rows.append(
            {
                "candidates": candidates,
                "replicates": len(groups),
                "verified_event_yield": g20["output_events"] / candidates,
                "g24_hot_record_bytes": g24["input_record_bytes"],
                "g20_hot_record_bytes": g20["input_record_bytes"],
                "hot_record_reduction_ratio": g24["input_record_bytes"] / g20["input_record_bytes"],
                "g20_cold_lineage_bytes": g20_cold_bytes,
                "allocated_output_bytes": g20["allocated_output_bytes"],
                "g24_state_plus_allocated_output_bytes": g24_hot_bytes,
                "g20_hot_state_plus_allocated_output_bytes": g20_hot_bytes,
                "declared_hot_allocation_reduction_ratio": g24_hot_bytes / g20_hot_bytes,
                "g24_declared_hot_l2_fraction": g24_hot_bytes / args.l2_bytes,
                "g20_declared_hot_l2_fraction": g20_hot_bytes / args.l2_bytes,
                "g24_total_allocated_bytes": g24_total_bytes,
                "g20_total_allocated_bytes": g20_total_bytes,
                "total_allocations_equal": g24_total_bytes == g20_total_bytes,
                "g20_total_allocated_l2_fraction": g20_total_bytes / args.l2_bytes,
                "g24_append_p50_ms_median": median([group["g24_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g20_append_p50_ms_median": median([group["g20_append"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g20_to_g24_append_rate_ratio_median": median(append_ratios),
                "g20_to_g24_append_rate_ratio_min": min(append_ratios),
                "g20_to_g24_append_rate_ratio_max": max(append_ratios),
                "g24_counts_p50_ms_median": median([group["g24_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g20_counts_p50_ms_median": median([group["g20_counts"]["device_dispatch_ms"]["p50"] for group in groups]),
                "g20_to_g24_counts_rate_ratio_median": median(counted_ratios),
                "g20_to_g24_counts_rate_ratio_min": min(counted_ratios),
                "g20_to_g24_counts_rate_ratio_max": max(counted_ratios),
                "all_discrete_counts_match": all(
                    group["g24_append"]["counts"] == group["g20_append"]["counts"]
                    and group["g24_counts"]["counts"] == group["g20_counts"]["counts"]
                    for group in groups
                ),
                "all_outputs_validated": all(
                    group[name]["sample_validation"]
                    and group[name]["counter_validation"]
                    and group[name]["completeness_validation"]
                    and group[name]["overflow_validation"]
                    for group in groups
                    for name in names
                ),
            }
        )

    pipeline_stat_groups: dict[tuple[str, str, int, str, int], list[int | float]] = defaultdict(list)
    pipeline_capture_documents = 0
    for doc in all_docs:
        if not doc.get("device", {}).get("pipeline_executable_capture", False):
            continue
        pipeline_capture_documents += 1
        for program in doc.get("programs", []):
            for executable in program.get("pipeline_executables", []):
                for statistic in executable.get("statistics", []):
                    key = (
                        program["name"],
                        executable["name"],
                        executable["subgroup_size"],
                        statistic["name"],
                        statistic["format"],
                    )
                    pipeline_stat_groups[key].append(statistic["value"])

    pipeline_stat_rows: list[dict[str, Any]] = []
    for (program, executable, subgroup_size, statistic, value_format), values in sorted(pipeline_stat_groups.items()):
        flagged_local_memory = statistic == "Local Memory Size" and min(values) >= 2**32
        pipeline_stat_rows.append(
            {
                "program": program,
                "executable": executable,
                "subgroup_size": subgroup_size,
                "statistic": statistic,
                "format": value_format,
                "replicates": len(values),
                "value_median": median(values),
                "value_min": min(values),
                "value_max": max(values),
                "all_values_equal": len(set(values)) == 1,
                "excluded_from_resource_interpretation": flagged_local_memory,
            }
        )

    lut_groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for doc in lut_docs:
        for row in doc["results"]:
            lut_groups[(row.get("source", "uniform_texel_buffer"), row["pattern"], row["table_bytes"])].append(row)

    lut_rows: list[dict[str, Any]] = []
    for (source, pattern, table_bytes), rows in sorted(lut_groups.items()):
        p50 = [row["device_ms"]["p50"] for row in rows]
        rates = [row["lookup_mps"] for row in rows]
        bandwidths = [row["logical_gbps"] for row in rows]
        lut_rows.append(
            {
                "source": source,
                "pattern": pattern,
                "table_bytes": table_bytes,
                "l2_fraction": table_bytes / args.l2_bytes,
                "candidates": rows[0]["candidates"],
                "replicates": len(rows),
                "device_p50_ms_median": median(p50),
                "device_p50_ms_min": min(p50),
                "device_p50_ms_max": max(p50),
                "lookup_mps_median": median(rates),
                "lookup_mps_min": min(rates),
                "lookup_mps_max": max(rates),
                "logical_bandwidth_gbps_median": median(bandwidths),
                "all_outputs_validated": all(row["validation"] for row in rows),
            }
        )

    lut_path_groups: dict[tuple[str, int], list[dict[str, dict[str, Any]]]] = defaultdict(list)
    for doc in lut_path_docs:
        by_key = {
            (row["source"], row["pattern"], row["logical_entries"]): row
            for row in doc["results"]
        }
        for pattern, entries in sorted({(key[1], key[2]) for key in by_key}):
            texture_key = ("uniform_texel_buffer", pattern, entries)
            ssbo_key = ("storage_buffer", pattern, entries)
            if texture_key in by_key and ssbo_key in by_key:
                lut_path_groups[(pattern, entries)].append(
                    {"texture": by_key[texture_key], "ssbo": by_key[ssbo_key]}
                )

    lut_path_rows: list[dict[str, Any]] = []
    for (pattern, entries), groups in sorted(lut_path_groups.items()):
        texture = groups[0]["texture"]
        ssbo = groups[0]["ssbo"]
        rate_ratios = [group["texture"]["lookup_mps"] / group["ssbo"]["lookup_mps"] for group in groups]
        lut_path_rows.append(
            {
                "pattern": pattern,
                "logical_entries": entries,
                "table_bytes": texture["table_bytes"],
                "table_l2_fraction": texture["table_bytes"] / args.l2_bytes,
                "candidates": texture["candidates"],
                "replicates": len(groups),
                "texture_p50_ms_median": median([group["texture"]["device_ms"]["p50"] for group in groups]),
                "ssbo_p50_ms_median": median([group["ssbo"]["device_ms"]["p50"] for group in groups]),
                "texture_to_ssbo_rate_ratio_median": median(rate_ratios),
                "texture_to_ssbo_rate_ratio_min": min(rate_ratios),
                "texture_to_ssbo_rate_ratio_max": max(rate_ratios),
                "all_outputs_validated": all(
                    group[source]["validation"]
                    and group[source]["validated_outputs"] == group[source]["candidates"]
                    for group in groups
                    for source in ("texture", "ssbo")
                ),
            }
        )

    result = {
        "schema": "UGTS-WINDOWS-PHYSICAL-GPU-AGGREGATE-1.17",
        "device": next(iter(device_names)),
        "l2_bytes": args.l2_bytes,
        "core_sources": [str(path) for path in args.core],
        "lut_sources": [str(path) for path in args.lut],
        "semantic_check_sources": [str(path) for path in args.semantic_check],
        "compact_sources": [str(path) for path in args.compact],
        "bounded_compact_sources": [str(path) for path in args.bounded_compact],
        "capacity_sweep_sources": [str(path) for path in args.capacity_sweep],
        "prethreshold_sources": [str(path) for path in args.prethreshold],
        "hot_log_lut_sources": [str(path) for path in args.hot_log_lut],
        "hot_log_control_sources": [str(path) for path in args.hot_log_control],
        "l2_boundary_sources": [str(path) for path in args.l2_boundary],
        "cold_lineage_sources": [str(path) for path in args.cold_lineage],
        "lut_pair_sources": [str(path) for path in args.lut_pair],
        "lut_path_control_sources": [str(path) for path in args.lut_path_control],
        "l2_latency_source": str(args.l2_latency) if args.l2_latency else None,
        "cuda_l2_clock_source": str(args.cuda_l2_clock) if args.cuda_l2_clock else None,
        "cuda_l2_mlp_source": str(args.cuda_l2_mlp) if args.cuda_l2_mlp else None,
        "cuda_texture_lut_source": str(args.cuda_texture_lut) if args.cuda_texture_lut else None,
        "cuda_packed_log_lut_source": str(args.cuda_packed_log_lut) if args.cuda_packed_log_lut else None,
        "cuda_l2_stride_source": str(args.cuda_l2_stride) if args.cuda_l2_stride else None,
        "lut_pair_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("lut_reverse", False) for doc in lut_pair_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("lut_reverse", False) for doc in lut_pair_docs),
        },
        "lut_path_control_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("reverse", False) for doc in lut_path_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("reverse", False) for doc in lut_path_docs),
        },
        "compact_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("compact_reverse", False) for doc in compact_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("compact_reverse", False) for doc in compact_docs),
        },
        "bounded_compact_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("compact_reverse", False) for doc in bounded_compact_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("compact_reverse", False) for doc in bounded_compact_docs),
        },
        "prethreshold_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("compact_reverse", False) for doc in prethreshold_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("compact_reverse", False) for doc in prethreshold_docs),
        },
        "hot_log_lut_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("compact_reverse", False) for doc in hot_log_lut_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("compact_reverse", False) for doc in hot_log_lut_docs),
        },
        "hot_log_control_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("compact_reverse", False) for doc in hot_log_control_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("compact_reverse", False) for doc in hot_log_control_docs),
        },
        "l2_boundary_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("compact_reverse", False) for doc in l2_boundary_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("compact_reverse", False) for doc in l2_boundary_docs),
        },
        "cold_lineage_order_balance": {
            "forward": sum(not doc.get("run_parameters", {}).get("compact_reverse", False) for doc in cold_lineage_docs),
            "reverse": sum(doc.get("run_parameters", {}).get("compact_reverse", False) for doc in cold_lineage_docs),
        },
        "core": core_rows,
        "lut": lut_rows,
        "integrated_lut_comparison": integrated_lut_rows,
        "paired_lut_comparison": paired_lut_rows,
        "compaction": compaction_rows,
        "bounded_compaction": bounded_compaction_rows,
        "capacity_sweep": capacity_sweep_rows,
        "prethreshold_comparison": prethreshold_rows,
        "hot_log_lut_comparison": hot_log_rows,
        "hot_log_control_comparison": hot_log_control_rows,
        "l2_boundary_comparison": l2_boundary_rows,
        "cold_lineage_comparison": cold_lineage_rows,
        "pipeline_executable_capture_documents": pipeline_capture_documents,
        "pipeline_executable_statistics": pipeline_stat_rows,
        "lut_path_comparison": lut_path_rows,
        "l2_latency_validation": l2_latency_doc.get("validation") if l2_latency_doc else None,
        "l2_latency_comparison": l2_latency_doc.get("results", []) if l2_latency_doc else [],
        "cuda_l2_clock_validation": cuda_l2_clock_doc.get("validation") if cuda_l2_clock_doc else None,
        "cuda_l2_clock_summary": cuda_l2_clock_doc.get("cross_size_summary") if cuda_l2_clock_doc else None,
        "cuda_l2_clock_comparison": cuda_l2_clock_doc.get("results", []) if cuda_l2_clock_doc else [],
        "cuda_l2_mlp_validation": cuda_l2_mlp_doc.get("validation") if cuda_l2_mlp_doc else None,
        "cuda_l2_mlp_summary": cuda_l2_mlp_doc.get("high_concurrency_summary") if cuda_l2_mlp_doc else None,
        "cuda_l2_mlp_comparison": cuda_l2_mlp_doc.get("results", []) if cuda_l2_mlp_doc else [],
        "cuda_texture_lut_validation": cuda_texture_lut_doc.get("validation") if cuda_texture_lut_doc else None,
        "cuda_texture_lut_concurrency_summary": cuda_texture_lut_doc.get("concurrency_summary") if cuda_texture_lut_doc else None,
        "cuda_texture_lut_full_occupancy_summary": cuda_texture_lut_doc.get("full_occupancy_summary") if cuda_texture_lut_doc else None,
        "cuda_texture_lut_comparison": cuda_texture_lut_doc.get("results", []) if cuda_texture_lut_doc else [],
        "cuda_packed_log_lut_validation": cuda_packed_log_lut_doc.get("validation") if cuda_packed_log_lut_doc else None,
        "cuda_packed_log_lut_capacity_summary": cuda_packed_log_lut_doc.get("capacity_summary") if cuda_packed_log_lut_doc else None,
        "cuda_packed_log_lut_full_occupancy_summary": cuda_packed_log_lut_doc.get("full_occupancy_summary", []) if cuda_packed_log_lut_doc else [],
        "cuda_packed_log_lut_packing_comparison": cuda_packed_log_lut_doc.get("packing_comparison", []) if cuda_packed_log_lut_doc else [],
        "cuda_packed_log_lut_texture_comparison": cuda_packed_log_lut_doc.get("texture_comparison", []) if cuda_packed_log_lut_doc else [],
        "cuda_packed_log_lut_comparison": cuda_packed_log_lut_doc.get("results", []) if cuda_packed_log_lut_doc else [],
        "cuda_l2_stride_validation": cuda_l2_stride_doc.get("validation") if cuda_l2_stride_doc else None,
        "cuda_l2_stride_line_model": cuda_l2_stride_doc.get("line_model") if cuda_l2_stride_doc else None,
        "cuda_l2_stride_comparison": cuda_l2_stride_doc.get("results", []) if cuda_l2_stride_doc else [],
        "notes": [
            "Medians aggregate independent process runs; min/max expose dynamic-clock and WDDM variability.",
            "Logical bandwidth counts declared input plus output record bytes, not external DRAM transactions.",
            "LUT results use R32_UINT uniform texel fetches containing two packed 16-bit log codes per word.",
            "Integrated LUT ratios are paired within each process before taking the median.",
            "The semantic hash covers discrete outputs and non-confidence scalar payload; confidence accuracy is reported separately.",
            "Compaction ratios compare verified-only atomic append against same-process dense G32 baselines.",
            "Subgroup compaction uses subgroup ballots and one workgroup range reservation, with full counters reduced per workgroup.",
            "Compaction aggregates include forward and reverse job orders to expose and counterbalance laptop clock-state hysteresis.",
            "Paired-LUT aggregates compare direct math, packed-adjacent two-fetch LUT, and duplicated-endpoint one-fetch LUT in balanced job orders.",
            "Bounded-compaction rows use a 6.25% event capacity, retain exact append demand in the GPU counter, and validate zero overflow plus dense-GPU count equality.",
            "Capacity-sweep headroom is signed: negative values are exact overflow demand; a corpus-tight lossless ratio is not a production guarantee.",
            "Pre-threshold rows compare the same-process subgroup kernel against a profile that stores the precomputed effective distance limit and materializes confidence only for retained events.",
            "Hot-log-LUT rows compare 32-byte G32 state against a fixed-query 24-byte state with a 6-bit log-threshold code and 128-byte packed texture-buffer LUT.",
            "Hot-log-control rows add a same-layout 24-byte direct-arithmetic threshold decoder, isolating record-footprint effects from the one-fetch 128-byte LUT.",
            "L2-boundary rows densely sample the full-counter G32/G24 compact paths around their calculated state-plus-bounded-output residency crossings; adjacent-size rate ratios expose the observed cliff without claiming a hardware-counter hit rate.",
            "Cold-lineage rows compare the G24 direct layout with a 20-byte hot geometry stream plus a separately allocated 4-byte lineage stream read only by retained lanes. The declared hot allocation excludes that cold buffer; total allocation is unchanged, and cache-line amplification is not directly measured.",
            "Pipeline executable statistics are driver-reported compiler metadata captured natively through VK_KHR_pipeline_executable_properties; they are not hardware performance counters.",
            "The NVIDIA driver reports Local Memory Size as 68719476736 bytes for every captured executable. This implausible per-thread value is flagged and excluded from resource or occupancy interpretation.",
            "LUT-path rows compare byte-identical packed uint payloads and indexing through a uniform texel buffer versus a storage buffer; ratios are paired within balanced processes.",
            "L2-latency rows are control-subtracted device-clock intervals for a saturated 512-step dependent SSBO chase. Shader-clock units are implementation-defined and the values include scheduler exposure; they are not raw cycles, nanoseconds, or cache-hit rates.",
            "CUDA L2-clock rows use one native sm_120 warp, clock64 cycle counters, and ld.global.cg loads. Cold follows a 256 MiB eviction pass and hot immediately repeats the same path; values are warp-exposed dependent-step cycles and still include time slicing.",
            "CUDA L2-MLP rows scale independent one-warp blocks from one total warp to the measured 24-warps-per-SM occupancy ceiling. Requested Gload/s is logical u32 request throughput, not physical cache-sector or DRAM traffic; clock64 rows include scheduling and memory-queue exposure.",
            "CUDA texture-LUT rows compare byte-identical dependent chains through native TLD texture-object instructions and native LDG L2/global instructions with independent eviction and balanced path order. Ratios near one do not imply identical front-end caches; they bound end-to-end capacity/throughput for this workload.",
            "CUDA packed-log-LUT rows compare two 16-bit code slots per word with sixteen 6-bit codes per three words through native LDG and TLD paths. Packed rates count decoded logical codes; the expected 1.125 word requests per packed lookup and all bandwidth-like rates remain logical rather than physical transactions.",
            "CUDA sparse-stride rows place one consumed dependent pointer u32 at 4-256 byte spacing with mixed filler in every gap. The 4:2:1 active-node capacity scaling at 32/64/128-byte spacing and saturated 128/256-byte curves bound dependent-pointer effective residency at 128 bytes for that workload; this is not a universal per-code cost or counter-derived physical line/sector claim.",
            "L2 size came from the local CUDA device-properties query; direct performance counters were permission-blocked.",
        ],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "aggregate_metrics.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    with (args.out_dir / "core_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        fieldnames = [key for key in core_rows[0] if key not in {"gpu_counts", "oracle_counts"}]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in core_rows:
            writer.writerow({key: row[key] for key in fieldnames})

    with (args.out_dir / "lut_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=lut_rows[0].keys())
        writer.writeheader()
        writer.writerows(lut_rows)

    if integrated_lut_rows:
        with (args.out_dir / "integrated_lut_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=integrated_lut_rows[0].keys())
            writer.writeheader()
            writer.writerows(integrated_lut_rows)

    if compaction_rows:
        with (args.out_dir / "compaction_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=compaction_rows[0].keys())
            writer.writeheader()
            writer.writerows(compaction_rows)

    if paired_lut_rows:
        with (args.out_dir / "paired_lut_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=paired_lut_rows[0].keys())
            writer.writeheader()
            writer.writerows(paired_lut_rows)

    if bounded_compaction_rows:
        with (args.out_dir / "bounded_compaction_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=bounded_compaction_rows[0].keys())
            writer.writeheader()
            writer.writerows(bounded_compaction_rows)

    if capacity_sweep_rows:
        with (args.out_dir / "capacity_sweep_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=capacity_sweep_rows[0].keys())
            writer.writeheader()
            writer.writerows(capacity_sweep_rows)

    if prethreshold_rows:
        with (args.out_dir / "prethreshold_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=prethreshold_rows[0].keys())
            writer.writeheader()
            writer.writerows(prethreshold_rows)

    if hot_log_rows:
        with (args.out_dir / "hot_log_lut_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=hot_log_rows[0].keys())
            writer.writeheader()
            writer.writerows(hot_log_rows)

    if hot_log_control_rows:
        with (args.out_dir / "hot_log_control_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=hot_log_control_rows[0].keys())
            writer.writeheader()
            writer.writerows(hot_log_control_rows)

    if l2_boundary_rows:
        with (args.out_dir / "l2_boundary_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=l2_boundary_rows[0].keys())
            writer.writeheader()
            writer.writerows(l2_boundary_rows)

    if cold_lineage_rows:
        with (args.out_dir / "cold_lineage_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=cold_lineage_rows[0].keys())
            writer.writeheader()
            writer.writerows(cold_lineage_rows)

    if pipeline_stat_rows:
        with (args.out_dir / "pipeline_executable_statistics.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=pipeline_stat_rows[0].keys())
            writer.writeheader()
            writer.writerows(pipeline_stat_rows)

    if lut_path_rows:
        with (args.out_dir / "lut_path_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=lut_path_rows[0].keys())
            writer.writeheader()
            writer.writerows(lut_path_rows)

    if l2_latency_doc and l2_latency_doc.get("results"):
        latency_rows = l2_latency_doc["results"]
        with (args.out_dir / "l2_latency_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=latency_rows[0].keys())
            writer.writeheader()
            writer.writerows(latency_rows)

    if cuda_l2_clock_doc and cuda_l2_clock_doc.get("results"):
        cuda_rows = cuda_l2_clock_doc["results"]
        with (args.out_dir / "cuda_l2_clock_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=cuda_rows[0].keys())
            writer.writeheader()
            writer.writerows(cuda_rows)

    if cuda_l2_mlp_doc and cuda_l2_mlp_doc.get("results"):
        cuda_mlp_rows = cuda_l2_mlp_doc["results"]
        with (args.out_dir / "cuda_l2_mlp_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=cuda_mlp_rows[0].keys())
            writer.writeheader()
            writer.writerows(cuda_mlp_rows)

    if cuda_texture_lut_doc and cuda_texture_lut_doc.get("results"):
        cuda_texture_rows = cuda_texture_lut_doc["results"]
        with (args.out_dir / "cuda_texture_lut_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=cuda_texture_rows[0].keys())
            writer.writeheader()
            writer.writerows(cuda_texture_rows)

    if cuda_packed_log_lut_doc:
        for name, key in (
            ("cuda_packed_log_lut_comparison.csv", "results"),
            ("cuda_packed_log_lut_packing_comparison.csv", "packing_comparison"),
            ("cuda_packed_log_lut_texture_comparison.csv", "texture_comparison"),
            ("cuda_packed_log_lut_full_occupancy.csv", "full_occupancy_summary"),
        ):
            cuda_packed_rows = cuda_packed_log_lut_doc.get(key, [])
            if cuda_packed_rows:
                with (args.out_dir / name).open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=cuda_packed_rows[0].keys())
                    writer.writeheader()
                    writer.writerows(cuda_packed_rows)

    if cuda_l2_stride_doc and cuda_l2_stride_doc.get("results"):
        cuda_stride_rows = cuda_l2_stride_doc["results"]
        with (args.out_dir / "cuda_l2_stride_comparison.csv").open(
            "w", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=cuda_stride_rows[0].keys())
            writer.writeheader()
            writer.writerows(cuda_stride_rows)

    print(args.out_dir / "aggregate_metrics.json")


if __name__ == "__main__":
    main()
