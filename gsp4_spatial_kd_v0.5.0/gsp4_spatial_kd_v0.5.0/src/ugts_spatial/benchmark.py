from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, dataclass
import platform
from pathlib import Path
import statistics
import time
from typing import Any, Callable

import numpy as np
import torch

from .graph import GraphPackage
from .model import UGTSSpatialModel
from .utils import human_bytes, write_json


@dataclass(frozen=True)
class BenchmarkConfig:
    warmup: int = 5
    repeats: int = 20
    scoring_batch: int = 65_536
    precision: str = "float32"
    device: str = "auto"

    def validate(self) -> None:
        if self.warmup < 0 or self.repeats <= 0:
            raise ValueError("warmup must be nonnegative and repeats positive")
        if self.scoring_batch <= 0:
            raise ValueError("scoring_batch must be positive")
        if self.precision not in {"float32", "float16", "bf16"}:
            raise ValueError("precision must be float32, float16 or bf16")


def _quantile(values: list[float], q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), q))


def _summary_ms(values: list[float]) -> dict[str, float]:
    return {
        "minimum_ms": float(min(values)),
        "p50_ms": float(statistics.median(values)),
        "p95_ms": _quantile(values, 0.95),
        "p99_ms": _quantile(values, 0.99),
        "maximum_ms": float(max(values)),
        "mean_ms": float(statistics.fmean(values)),
    }


def _autocast(device: torch.device, precision: str):
    if device.type != "cuda" or precision == "float32":
        return nullcontext()
    dtype = torch.float16 if precision == "float16" else torch.bfloat16
    return torch.autocast("cuda", dtype=dtype)


def _timed(
    fn: Callable[[], Any],
    *,
    device: torch.device,
    warmup: int,
    repeats: int,
) -> tuple[list[float], Any]:
    result: Any = None
    for _ in range(warmup):
        result = fn()
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    samples: list[float] = []
    for _ in range(repeats):
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        start = time.perf_counter()
        result = fn()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples, result


def benchmark_model(
    graph: GraphPackage,
    model: UGTSSpatialModel,
    *,
    config: BenchmarkConfig = BenchmarkConfig(),
    checkpoint_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Measure the named graph-encoding and relation-scoring workloads."""
    config.validate()
    device = (
        torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if config.device == "auto"
        else torch.device(config.device)
    )
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    if device.type == "cpu" and config.precision != "float32":
        raise ValueError("CPU benchmark requires float32")

    model = model.to(device).eval()
    tensors = graph.to_torch(device)
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)

    def encode_once() -> torch.Tensor:
        with torch.inference_mode(), _autocast(device, config.precision):
            return model(tensors)["node_state"]

    encode_samples, state = _timed(
        encode_once, device=device, warmup=config.warmup, repeats=config.repeats
    )
    if graph.num_edges <= 0:
        raise ValueError("benchmark graph must contain at least one edge")

    batch = int(config.scoring_batch)
    positions_np = np.arange(batch, dtype=np.int64) % graph.num_edges
    positions = torch.as_tensor(positions_np, device=device)
    edge_index = tensors["edge_index"][:, positions]
    edge_type = tensors["edge_type"][positions]
    edge_attr = tensors["edge_attr"][positions]

    def score_once() -> torch.Tensor:
        with torch.inference_mode(), _autocast(device, config.precision):
            return model.score_edges(state, edge_index, edge_type, edge_attr).float()

    score_samples, scores = _timed(
        score_once, device=device, warmup=config.warmup, repeats=config.repeats
    )
    encode_stats = _summary_ms(encode_samples)
    score_stats = _summary_ms(score_samples)
    encode_seconds = encode_stats["p50_ms"] / 1000.0
    score_seconds = score_stats["p50_ms"] / 1000.0
    parameters = int(sum(parameter.numel() for parameter in model.parameters()))
    checkpoint_bytes = (
        Path(checkpoint_path).stat().st_size
        if checkpoint_path is not None and Path(checkpoint_path).exists()
        else None
    )

    cuda: dict[str, Any] = {
        "available": bool(torch.cuda.is_available()),
        "torch_cuda_version": torch.version.cuda,
    }
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(device)
        cuda.update(
            {
                "device_name": torch.cuda.get_device_name(device),
                "compute_capability": list(torch.cuda.get_device_capability(device)),
                "total_vram_bytes": int(props.total_memory),
                "total_vram_human": human_bytes(int(props.total_memory)),
                "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
                "peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
            }
        )

    result = {
        "format": "UGTS-SPATIAL-BENCHMARK-1",
        "config": asdict(config),
        "graph": {
            "schema_hash": graph.schema_hash,
            "nodes": graph.num_nodes,
            "edges": graph.num_edges,
            "input_dim": graph.input_dim,
            "teacher_dim": graph.teacher_dim,
            "array_bytes": graph.summary()["array_bytes"],
        },
        "model": {
            "parameters": parameters,
            "checkpoint_bytes": checkpoint_bytes,
            "checkpoint_human": None
            if checkpoint_bytes is None
            else human_bytes(checkpoint_bytes),
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "device": str(device),
            "cuda": cuda,
        },
        "node_encoding": {
            **encode_stats,
            "nodes_per_second_at_p50": float(
                graph.num_nodes / max(encode_seconds, 1e-12)
            ),
            "edges_per_second_at_p50": float(
                graph.num_edges / max(encode_seconds, 1e-12)
            ),
        },
        "relation_scoring": {
            **score_stats,
            "batch_edges": batch,
            "candidate_scores_per_second_at_p50": float(
                batch / max(score_seconds, 1e-12)
            ),
            "score_checksum": float(scores.sum().detach().cpu().item()),
        },
        "measurement_boundary": (
            "workload throughput only; not raw DRAM bandwidth and not a "
            "physical-GPU claim beyond the named device/run"
        ),
    }
    if output_path is not None:
        write_json(output_path, result)
    return result



def benchmark_student(
    graph: GraphPackage,
    checkpoint_path: str | Path,
    *,
    config: BenchmarkConfig = BenchmarkConfig(),
    output_path: str | Path | None = None,
    query_config: "QueryConfig | None" = None,
) -> dict[str, Any]:
    """Load a student checkpoint and benchmark encoding, scoring and a cached query.

    Query timings deliberately exclude novelty-log writes.  The optional cached-state
    query measures broad-phase lookup, deterministic support/compatibility/guard logic
    and student relation scoring after one graph encoding has been materialized.
    """
    from .query import QueryConfig, encode_graph, execute_query
    from .training import load_model_for_graph

    model, device, checkpoint = load_model_for_graph(
        graph, checkpoint_path, device=config.device
    )
    result = benchmark_model(
        graph,
        model,
        config=config,
        checkpoint_path=checkpoint_path,
        output_path=None,
    )
    result["format"] = "UGTS-SPATIAL-BENCHMARK-2"
    result["model"]["checkpoint_format"] = checkpoint.get("format")

    if query_config is not None:
        if not isinstance(query_config, QueryConfig):
            raise TypeError("query_config must be QueryConfig or None")
        encoded_state = encode_graph(
            graph, model, device, precision=query_config.precision
        )

        def query_once():
            return execute_query(
                graph,
                query_config,
                model=model,
                device=device,
                encoded_state=encoded_state,
                novelty_log=None,
            )

        query_samples, query_result = _timed(
            query_once,
            device=device,
            warmup=config.warmup,
            repeats=config.repeats,
        )
        stats = _summary_ms(query_samples)
        seconds = stats["p50_ms"] / 1000.0
        candidate_count = int(query_result.summary.get("candidates", 0))
        verified_count = int(query_result.summary.get("verified", 0))
        event_checksum = int(
            sum(int(event["lineage_hash"]) for event in query_result.events)
            & 0xFFFFFFFFFFFFFFFF
        )
        result["cached_query"] = {
            **stats,
            "query": asdict(query_config),
            "candidates": candidate_count,
            "verified_events": verified_count,
            "candidates_per_second_at_p50": float(
                candidate_count / max(seconds, 1e-12)
            ),
            "event_lineage_checksum_u64": event_checksum,
            "timing_scope": (
                "candidate lookup + deterministic UGTS gates + student scoring; "
                "graph encoding and novelty-log writes excluded"
            ),
        }

    if output_path is not None:
        write_json(output_path, result)
    return result
