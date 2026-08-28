"""Conversion between on-disk NumPy graph arrays and PyTorch tensors."""
from __future__ import annotations

from typing import Any

import numpy as np
import torch

from .graph import SparseTemporalGraph


def graph_to_tensors(graph: SparseTemporalGraph, device: torch.device | str = "cpu") -> dict[str, torch.Tensor]:
    device = torch.device(device)
    def t(a: np.ndarray, dtype: torch.dtype | None = None) -> torch.Tensor:
        # Copy memory-mapped/read-only arrays to avoid undefined writable warnings.
        arr = np.asarray(a)
        out = torch.from_numpy(arr.copy() if not arr.flags.writeable else arr)
        if dtype is not None:
            out = out.to(dtype=dtype)
        return out.to(device)
    batch: dict[str, torch.Tensor] = {
        "node_features": t(graph.node_features, torch.float32),
        "node_type": t(graph.node_types, torch.long),
        "edge_src": t(graph.edge_src, torch.long),
        "edge_dst": t(graph.edge_dst, torch.long),
        "edge_type": t(graph.edge_type, torch.long),
        "edge_time": t(graph.edge_time, torch.float32),
        "edge_weight": t(graph.edge_weight, torch.float32),
        "event_entity": t(graph.event_entity, torch.long),
        "event_type": t(graph.event_type, torch.long),
        "event_time": t(graph.event_time, torch.float32),
        "event_value": t(graph.event_value, torch.float32),
        "ex_src": t(graph.ex_src, torch.long),
        "ex_dst": t(graph.ex_dst, torch.long),
        "ex_relation": t(graph.ex_relation, torch.long),
        "ex_label": t(graph.ex_label, torch.float32),
        "ex_teacher_prob": t(graph.ex_teacher_prob, torch.float32),
        "ex_time": t(graph.ex_time, torch.float32),
        "ex_distance_m": t(graph.ex_distance_m, torch.float32),
        "ex_split": t(graph.ex_split, torch.long),
    }
    if graph.teacher_embeddings is not None:
        batch["teacher_embeddings"] = t(graph.teacher_embeddings, torch.float32)
        batch["teacher_mask"] = t(graph.teacher_mask, torch.bool)
    return batch


def batch_device_summary(batch: dict[str, torch.Tensor]) -> dict[str, Any]:
    bytes_total = sum(x.numel() * x.element_size() for x in batch.values())
    return {"device": str(next(iter(batch.values())).device), "tensor_bytes": bytes_total, "tensor_mib": bytes_total / (1024 * 1024)}
