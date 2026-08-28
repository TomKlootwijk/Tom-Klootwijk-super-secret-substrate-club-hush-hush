#!/usr/bin/env python3
"""Derive UGTS named metrics, memory/compression tables, and charts.

The input is the direct Vulkan benchmark JSON. An optional ANGLE/SwiftShader
bootstrap-compiler JSON may be supplied with --bootstrap-json.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

MIB = 1024 * 1024


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(a: float, b: float) -> float:
    return a / b if b else math.inf


def human_bytes(n: float) -> str:
    if n >= MIB:
        return f"{n / MIB:.3f} MiB"
    if n >= 1024:
        return f"{n / 1024:.3f} KiB"
    return f"{n:.0f} B"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("vulkan_json", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--bootstrap-json", type=Path)
    args = ap.parse_args()

    data = load_json(args.vulkan_json)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    charts = out / "charts"
    charts.mkdir(exist_ok=True)

    rows = data["benchmarks"]
    programs = data["programs"]
    largest_n = max(r["candidates"] for r in rows)
    largest = [r for r in rows if r["candidates"] == largest_n]

    by_key = {(r["profile"], r["mode"], r["candidates"]): r for r in rows}
    g64_eval = by_key[("G64_E32", "evaluate", largest_n)]
    g64_commit = by_key[("G64_E32", "evaluate_commit", largest_n)]
    g32_eval = by_key[("G32_E16", "evaluate", largest_n)]
    g32_commit = by_key[("G32_E16", "evaluate_commit", largest_n)]

    # Memory and compression metrics are explicit about what is retained.
    g64_dense = largest_n * (64 + 32)
    g32_dense = largest_n * (32 + 16)
    g64_compact_events = g64_eval["counts"]["verified"] * 32
    g32_compact_events = g32_eval["counts"]["verified"] * 16
    g32_state_plus_compact = largest_n * 32 + g32_compact_events

    metrics = [
        {
            "metric": "Candidate Evaluation Rate",
            "symbol": "CER",
            "unit": "million candidates/s",
            "definition": "Candidate relations evaluated per second, using device timestamp p50.",
            "value": g64_eval["candidate_rate_mps"],
            "scope": f"G64_E32 evaluate, N={largest_n}",
        },
        {
            "metric": "Spherical Event Throughput",
            "symbol": "SET",
            "unit": "million verified events/s",
            "definition": "Verified support + compatibility + guard events per second.",
            "value": g64_eval["verified_event_rate_mps"],
            "scope": f"G64_E32 evaluate, N={largest_n}",
        },
        {
            "metric": "Effective Substrate Bandwidth",
            "symbol": "ESB",
            "unit": "GB/s",
            "definition": "Logical input plus output record bytes divided by device p50 time; not raw DRAM bandwidth.",
            "value": g64_eval["effective_bandwidth_gbps"],
            "scope": f"G64_E32 evaluate, N={largest_n}",
        },
        {
            "metric": "Support Rejection Gain",
            "symbol": "SRG",
            "unit": "x",
            "definition": "Input candidates divided by candidates admitted by radial-angular support.",
            "value": ratio(g64_eval["counts"]["candidates"], g64_eval["counts"]["supported"]),
            "scope": "G64_E32 deterministic corpus",
        },
        {
            "metric": "Compatibility Rejection Gain",
            "symbol": "CRG",
            "unit": "x",
            "definition": "Supported candidates divided by support-and-compatibility survivors.",
            "value": ratio(g64_eval["counts"]["supported"], g64_eval["counts"]["compatible"]),
            "scope": "G64_E32 deterministic corpus",
        },
        {
            "metric": "Event Yield",
            "symbol": "EY",
            "unit": "%",
            "definition": "Verified events divided by input candidates.",
            "value": 100.0 * ratio(g64_eval["counts"]["verified"], g64_eval["counts"]["candidates"]),
            "scope": "G64_E32 deterministic corpus",
        },
        {
            "metric": "State Compression Ratio",
            "symbol": "SCR",
            "unit": "x",
            "definition": "Dense G64_E32 bytes divided by dense packed G32_E16 bytes.",
            "value": ratio(g64_dense, g32_dense),
            "scope": f"N={largest_n}",
        },
        {
            "metric": "Event Compaction Ratio",
            "symbol": "ECR",
            "unit": "x",
            "definition": "Dense G32 E16 output bytes divided by verified-event-only E16 bytes.",
            "value": ratio(largest_n * 16, g32_compact_events),
            "scope": f"G32_E16 evaluate, N={largest_n}",
        },
        {
            "metric": "State-plus-Novelty Compression",
            "symbol": "SNC",
            "unit": "x",
            "definition": "Dense G64_E32 bytes divided by G32 state plus compact verified E16 event log.",
            "value": ratio(g64_dense, g32_state_plus_compact),
            "scope": f"N={largest_n}",
        },
        {
            "metric": "Commit Cost Factor",
            "symbol": "CCF",
            "unit": "x",
            "definition": "Evaluate+atomic-commit p50 divided by evaluate-only p50.",
            "value": ratio(g64_commit["device_dispatch_ms"]["p50"], g64_eval["device_dispatch_ms"]["p50"]),
            "scope": f"G64_E32, N={largest_n}",
        },
        {
            "metric": "Packed Compute Penalty",
            "symbol": "PCP",
            "unit": "x",
            "definition": "G32 evaluate p50 divided by G64 evaluate p50 on this validation device.",
            "value": ratio(g32_eval["device_dispatch_ms"]["p50"], g64_eval["device_dispatch_ms"]["p50"]),
            "scope": f"N={largest_n}; " + ("physical GPU" if data["physical_gpu_claim"] else "software Vulkan device"),
        },
    ]

    with (out / "metric_dictionary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["metric", "symbol", "unit", "definition", "value", "scope"])
        w.writeheader()
        w.writerows(metrics)

    memory_rows = [
        {
            "configuration": "G64_E32 dense",
            "candidates": largest_n,
            "bytes": g64_dense,
            "mib": g64_dense / MIB,
            "relative_to_g64_dense": 1.0,
            "retention": "all states + dense outputs",
        },
        {
            "configuration": "G32_E16 dense",
            "candidates": largest_n,
            "bytes": g32_dense,
            "mib": g32_dense / MIB,
            "relative_to_g64_dense": g32_dense / g64_dense,
            "retention": "all packed states + dense outputs",
        },
        {
            "configuration": "G32 state + compact E16 novelty log",
            "candidates": largest_n,
            "bytes": g32_state_plus_compact,
            "mib": g32_state_plus_compact / MIB,
            "relative_to_g64_dense": g32_state_plus_compact / g64_dense,
            "retention": "all packed states + verified events only",
        },
        {
            "configuration": "G32 compact E16 novelty log only",
            "candidates": largest_n,
            "bytes": g32_compact_events,
            "mib": g32_compact_events / MIB,
            "relative_to_g64_dense": g32_compact_events / g64_dense,
            "retention": "verified events only; state must be rebuildable",
        },
    ]
    with (out / "memory_compression.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=memory_rows[0].keys())
        w.writeheader(); w.writerows(memory_rows)

    perf_rows: list[dict[str, Any]] = []
    for r in rows:
        perf_rows.append({
            "profile": r["profile"],
            "mode": r["mode"],
            "candidates": r["candidates"],
            "device_p50_ms": r["device_dispatch_ms"]["p50"],
            "device_p95_ms": r["device_dispatch_ms"]["p95"],
            "device_p99_ms": r["device_dispatch_ms"]["p99"],
            "host_p50_ms": r["host_dispatch_ms"]["p50"],
            "candidate_rate_mps": r["candidate_rate_mps"],
            "verified_event_rate_mps": r["verified_event_rate_mps"],
            "effective_bandwidth_gbps": r["effective_bandwidth_gbps"],
            "support_rejection_gain": ratio(r["counts"]["candidates"], r["counts"]["supported"]),
            "compatibility_rejection_gain": ratio(r["counts"]["supported"], r["counts"]["compatible"]),
            "event_yield_percent": 100 * ratio(r["counts"]["verified"], r["counts"]["candidates"]),
        })
    with (out / "performance_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=perf_rows[0].keys())
        w.writeheader(); w.writerows(perf_rows)

    # Charts use matplotlib defaults deliberately, so they remain reproducible without a custom style.
    labels = sorted({(r["profile"], r["mode"]) for r in rows})
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    for profile, mode in labels:
        rr = sorted([r for r in rows if r["profile"] == profile and r["mode"] == mode], key=lambda x: x["candidates"])
        ax.plot([r["candidates"] for r in rr], [r["candidate_rate_mps"] for r in rr], marker="o", label=f"{profile} {mode}")
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Candidates per dispatch")
    ax.set_ylabel("CER — million candidates/s")
    ax.set_title("Native Vulkan Candidate Evaluation Rate")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(charts / "candidate_evaluation_rate.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    for profile, mode in labels:
        rr = sorted([r for r in rows if r["profile"] == profile and r["mode"] == mode], key=lambda x: x["candidates"])
        ax.plot([r["candidates"] for r in rr], [r["device_dispatch_ms"]["p50"] for r in rr], marker="o", label=f"{profile} {mode}")
    ax.set_xscale("log", base=2); ax.set_yscale("log")
    ax.set_xlabel("Candidates per dispatch"); ax.set_ylabel("Device p50 latency (ms)")
    ax.set_title("Native Vulkan Device Latency")
    ax.grid(True, alpha=0.25); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(charts / "device_latency.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    names = [r["configuration"] for r in memory_rows]
    values = [r["mib"] for r in memory_rows]
    bars = ax.bar(range(len(names)), values)
    ax.set_xticks(range(len(names)), names, rotation=20, ha="right")
    ax.set_ylabel("Memory (MiB)")
    ax.set_title(f"State and Event Memory at {largest_n:,} Candidates")
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width()/2, b.get_height(), f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout(); fig.savefig(charts / "memory_footprint.png", dpi=180); plt.close(fig)

    comp_names = ["SCR\npacked dense", "ECR\nevent compaction", "SNC\nstate+novelty"]
    comp_values = [
        ratio(g64_dense, g32_dense),
        ratio(largest_n * 16, g32_compact_events),
        ratio(g64_dense, g32_state_plus_compact),
    ]
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    bars = ax.bar(comp_names, comp_values)
    ax.set_ylabel("Compression ratio (x)")
    ax.set_title("UGTS Explicit Compression Metrics")
    for b, v in zip(bars, comp_values):
        ax.text(b.get_x() + b.get_width()/2, b.get_height(), f"{v:.2f}x", ha="center", va="bottom")
    fig.tight_layout(); fig.savefig(charts / "compression_metrics.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    pnames = [p["name"] for p in programs]
    cold = [p["cold_pipeline_create_ms"] for p in programs]
    cached = [p["cached_pipeline_create_ms"] for p in programs]
    x = list(range(len(pnames)))
    width = 0.38
    ax.bar([i - width/2 for i in x], cold, width=width, label="Cold pipeline")
    ax.bar([i + width/2 for i in x], cached, width=width, label="Cache-seeded")
    ax.set_xticks(x, pnames, rotation=20, ha="right")
    ax.set_ylabel("Pipeline creation latency (ms)")
    ax.set_title("Native Vulkan Pipeline Compilation")
    ax.legend(); fig.tight_layout(); fig.savefig(charts / "pipeline_compilation.png", dpi=180); plt.close(fig)

    summary = {
        "schema": "UGTS-DERIVED-METRICS-1.1",
        "source_benchmark": str(args.vulkan_json),
        "device": data["device"],
        "largest_candidate_batch": largest_n,
        "metrics": metrics,
        "memory": memory_rows,
        "notes": [
            "Rates use device timestamp p50.",
            "Effective Substrate Bandwidth is logical record traffic, not measured external DRAM bandwidth.",
            "Compact-event memory assumes non-events are discarded and state is either retained separately or rebuildable.",
            "Inspect physical_gpu_claim and device type before generalizing beyond the named device.",
        ],
    }
    (out / "derived_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md = [
        "# UGTS GPU-Native Benchmark Summary",
        "",
        f"Validation device: **{data['device']['name']}** (Vulkan {data['device']['api_version']}; physical GPU claim: `{str(data['physical_gpu_claim']).lower()}`).",
        f"Largest batch: **{largest_n:,} candidates**.",
        "",
        "## Named performance metrics",
        "",
        "| Name | Symbol | Value | Unit | Scope |",
        "|---|---:|---:|---|---|",
    ]
    for m in metrics:
        md.append(f"| {m['metric']} | {m['symbol']} | {m['value']:.4f} | {m['unit']} | {m['scope']} |")
    md += ["", "## Memory configurations", "", "| Configuration | Memory | Fraction of G64 dense | Retention |", "|---|---:|---:|---|"]
    for r in memory_rows:
        md.append(f"| {r['configuration']} | {human_bytes(r['bytes'])} | {100*r['relative_to_g64_dense']:.3f}% | {r['retention']} |")
    interpretation = (
        "These measurements establish direct Vulkan performance on the named physical GPU only. "
        "They do not establish performance on other GPUs, ASICs, FPGAs, photonic, or optofluidic devices."
        if data["physical_gpu_claim"]
        else
        "These measurements validate the Vulkan execution path on the named software/CPU device. "
        "They do not establish physical-GPU, ASIC, FPGA, photonic, or optofluidic performance."
    )
    md += [
        "",
        "## Interpretation boundary",
        "",
        interpretation,
    ]
    (out / "benchmark_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if args.bootstrap_json and args.bootstrap_json.exists():
        shutil.copy2(args.bootstrap_json, out / "bootstrap_compiler_results.json")


if __name__ == "__main__":
    main()
