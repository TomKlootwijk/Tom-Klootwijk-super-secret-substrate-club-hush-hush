"""Repeatable student inference benchmark for CPU or CUDA."""
from __future__ import annotations

import json
import math
from pathlib import Path
import statistics
import time
from typing import Any

import numpy as np
import torch

from .graph import SparseTemporalGraph
from .tensor_data import batch_device_summary, graph_to_tensors
from .training import load_checkpoint


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def benchmark_checkpoint(
    graph_dir: str | Path,
    checkpoint_path: str | Path,
    *,
    device: str = "auto",
    warmup: int = 5,
    repeats: int = 30,
    amp: bool = True,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    chosen = torch.device("cuda" if device == "auto" and torch.cuda.is_available() else ("cpu" if device == "auto" else device))
    if chosen.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA benchmark requested but CUDA is unavailable")
    graph = SparseTemporalGraph.load(graph_dir, mmap=False, verify_hashes=True)
    batch = graph_to_tensors(graph, chosen)
    model, payload = load_checkpoint(checkpoint_path, chosen)
    query_time = float(payload.get("query_time", graph.metadata.get("max_time_hours", 0.0)))
    use_amp = bool(amp and chosen.type == "cuda")
    if chosen.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(chosen)

    def run_once() -> torch.Tensor:
        with torch.no_grad(), torch.amp.autocast(device_type=chosen.type, enabled=use_amp, dtype=torch.float16):
            return model(batch, query_time)["link_logits"]

    for _ in range(max(0, warmup)):
        logits = run_once()
    if chosen.type == "cuda":
        torch.cuda.synchronize(chosen)
    timings_ms: list[float] = []
    checksum = 0.0
    for _ in range(repeats):
        if chosen.type == "cuda":
            start = torch.cuda.Event(enable_timing=True); end = torch.cuda.Event(enable_timing=True)
            start.record(); logits = run_once(); end.record(); end.synchronize()
            elapsed_ms = float(start.elapsed_time(end))
        else:
            start_t = time.perf_counter(); logits = run_once(); elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        checksum += float(logits.float().sum().cpu())
        timings_ms.append(elapsed_ms)
    p50 = statistics.median(timings_ms)
    p95 = _percentile(timings_ms, 95)
    p99 = _percentile(timings_ms, 99)
    seconds = p50 / 1000.0
    report = {
        "format": "UGTS-SPATIAL-BENCHMARK-1",
        "device": str(chosen),
        "device_name": torch.cuda.get_device_name(chosen) if chosen.type == "cuda" else "CPU",
        "torch_version": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "amp": use_amp,
        "warmup": warmup,
        "repeats": repeats,
        "counts": {"nodes": graph.num_nodes, "edges": graph.num_edges, "events": graph.num_events, "examples": graph.num_examples},
        "latency_ms": {"p50": p50, "p95": p95, "p99": p99, "min": min(timings_ms), "max": max(timings_ms)},
        "rates_at_p50": {
            "nodes_per_s": graph.num_nodes / seconds,
            "edge_messages_per_s": graph.num_edges / seconds,
            "temporal_events_per_s": graph.num_events / seconds,
            "candidate_examples_per_s": graph.num_examples / seconds,
        },
        "tensor_storage": batch_device_summary(batch),
        "checksum": checksum,
        "finite_logits": bool(torch.isfinite(logits).all()),
        "checkpoint_best_epoch": payload.get("best_epoch"),
        "notes": [
            "This times full-graph event aggregation, typed message passing and candidate scoring together.",
            "The rate is not raw DRAM bandwidth and must not be compared with UGTS CER/SET unless workload and gate are identical.",
        ],
    }
    if chosen.type == "cuda":
        report["cuda_memory"] = {
            "allocated_peak_mib": torch.cuda.max_memory_allocated(chosen) / (1024 * 1024),
            "reserved_peak_mib": torch.cuda.max_memory_reserved(chosen) / (1024 * 1024),
        }
    if output_json is not None:
        Path(output_json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
