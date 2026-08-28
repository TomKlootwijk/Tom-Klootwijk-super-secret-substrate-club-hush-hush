"""Training and evaluation for the sparse UGTS spatial student."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import time
from typing import Any

import numpy as np
import torch

from .graph import SparseTemporalGraph
from .losses import LossWeights, binary_distillation_loss
from .metrics import best_f1_threshold, binary_metrics
from .model import ModelConfig, UGTSSpatialStudent
from .ontology import Ontology
from .tensor_data import batch_device_summary, graph_to_tensors


@dataclass(frozen=True)
class TrainConfig:
    hidden_dim: int = 64
    heads: int = 4
    layers: int = 2
    memory_dim: int = 32
    dropout: float = 0.10
    epochs: int = 30
    learning_rate: float = 2e-3
    weight_decay: float = 1e-4
    patience: int = 8
    grad_clip: float = 1.0
    seed: int = 200678942
    device: str = "auto"
    amp: bool = True
    compile_model: bool = False
    threshold: float = 0.5
    num_threads: int = 0
    task_weight: float = 1.0
    teacher_probability_weight: float = 0.5
    teacher_embedding_weight: float = 0.25
    confidence_margin_weight: float = 0.05

    @classmethod
    def load(cls, path: str | Path | None) -> "TrainConfig":
        if path is None:
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _choose_device(requested: str) -> torch.device:
    if requested != "auto":
        device = torch.device(requested)
        if device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
        return device
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _set_determinism(seed: int, device: torch.device, num_threads: int = 0) -> None:
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    if num_threads > 0:
        torch.set_num_threads(num_threads)


def _split_metrics(logits: torch.Tensor, batch: dict[str, torch.Tensor], split: int, threshold: float) -> dict[str, Any]:
    mask = batch["ex_split"] == split
    if not torch.any(mask):
        return {"count": 0}
    result = binary_metrics(logits[mask], batch["ex_label"][mask], threshold)
    result["split"] = split
    # Per-relation detail makes ontology failures visible instead of averaging
    # geometry and semantic tasks together.
    by_relation: dict[str, Any] = {}
    for relation in torch.unique(batch["ex_relation"][mask]).tolist():
        rel_mask = mask & (batch["ex_relation"] == int(relation))
        by_relation[str(int(relation))] = binary_metrics(logits[rel_mask], batch["ex_label"][rel_mask], threshold)
    result["by_relation"] = by_relation
    return result


def _model_parameter_summary(model: torch.nn.Module) -> dict[str, Any]:
    parameters = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    bytes_fp32 = parameters * 4
    return {"parameters": parameters, "trainable_parameters": trainable, "fp32_mib": bytes_fp32 / (1024 * 1024)}


def load_checkpoint(path: str | Path, device: str | torch.device = "cpu") -> tuple[UGTSSpatialStudent, dict[str, Any]]:
    payload = torch.load(Path(path), map_location=torch.device(device), weights_only=False)
    config = ModelConfig(**payload["model_config"])
    model = UGTSSpatialStudent(config)
    model.load_state_dict(payload["model_state"])
    model.to(device)
    model.eval()
    return model, payload


def train_model(
    graph_dir: str | Path,
    ontology_path: str | Path,
    output_dir: str | Path,
    config: TrainConfig = TrainConfig(),
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    device = _choose_device(config.device)
    _set_determinism(config.seed, device, config.num_threads)

    graph = SparseTemporalGraph.load(graph_dir, mmap=False, verify_hashes=True)
    ontology = Ontology.load(ontology_path)
    batch = graph_to_tensors(graph, device)
    query_time = float(graph.metadata.get("max_time_hours", float(graph.event_time.max(initial=0.0))))
    teacher_dim = int(graph.teacher_embeddings.shape[1]) if graph.teacher_embeddings is not None else 64
    num_event_types = max(1, len(graph.metadata.get("event_types", [])), int(graph.event_type.max(initial=0)) + 1)
    model_config = ModelConfig(
        feature_dim=graph.feature_dim,
        num_node_types=ontology.num_node_types,
        num_relations=ontology.num_relations,
        num_event_types=num_event_types,
        hidden_dim=config.hidden_dim,
        heads=config.heads,
        layers=config.layers,
        memory_dim=config.memory_dim,
        teacher_dim=teacher_dim,
        dropout=config.dropout,
    )
    model = UGTSSpatialStudent(model_config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    use_amp = bool(config.amp and device.type == "cuda")
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    if config.compile_model:
        if not hasattr(torch, "compile"):
            raise RuntimeError("torch.compile is unavailable")
        model = torch.compile(model)  # type: ignore[assignment]

    weights = LossWeights(
        task=config.task_weight,
        teacher_probability=config.teacher_probability_weight,
        teacher_embedding=config.teacher_embedding_weight,
        confidence_margin=config.confidence_margin_weight,
    )
    train_mask = batch["ex_split"] == 0
    if not torch.any(train_mask):
        raise ValueError("graph contains no training examples (split 0)")

    history: list[dict[str, Any]] = []
    best_value = -float("inf")
    best_epoch = -1
    no_improve = 0
    start = time.perf_counter()
    best_path = output / "checkpoint.pt"

    for epoch in range(1, config.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        epoch_start = time.perf_counter()
        with torch.amp.autocast(device_type=device.type, enabled=use_amp, dtype=torch.float16):
            outputs = model(batch, query_time)
            loss, parts = binary_distillation_loss(
                outputs, batch["ex_label"], batch["ex_teacher_prob"], train_mask,
                batch.get("teacher_embeddings"), batch.get("teacher_mask"), weights,
            )
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        grad_norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), config.grad_clip))
        scaler.step(optimizer)
        scaler.update()

        model.eval()
        with torch.no_grad():
            with torch.amp.autocast(device_type=device.type, enabled=use_amp, dtype=torch.float16):
                eval_outputs = model(batch, query_time)
            logits = eval_outputs["link_logits"].float()
            train_metrics = _split_metrics(logits, batch, 0, config.threshold)
            val_metrics = _split_metrics(logits, batch, 1, config.threshold)
            test_metrics = _split_metrics(logits, batch, 2, config.threshold)
        monitor = val_metrics.get("average_precision", val_metrics.get("f1", -float("inf")))
        if not isinstance(monitor, (float, int)) or not np.isfinite(monitor):
            monitor = val_metrics.get("f1", -float("inf"))
        elapsed = time.perf_counter() - epoch_start
        row = {
            "epoch": epoch,
            "seconds": elapsed,
            "grad_norm": grad_norm,
            **parts,
            "train_f1": train_metrics.get("f1"),
            "train_ap": train_metrics.get("average_precision"),
            "val_f1": val_metrics.get("f1"),
            "val_ap": val_metrics.get("average_precision"),
            "test_f1": test_metrics.get("f1"),
            "test_ap": test_metrics.get("average_precision"),
        }
        history.append(row)

        if float(monitor) > best_value + 1e-6:
            best_value = float(monitor)
            best_epoch = epoch
            no_improve = 0
            underlying = getattr(model, "_orig_mod", model)
            payload = {
                "format": "UGTS-SPATIAL-STUDENT-CHECKPOINT-1",
                "package_version": "0.1.0",
                "created_unix": time.time(),
                "model_config": model_config.to_dict(),
                "train_config": asdict(config),
                "model_state": underlying.state_dict(),
                "best_epoch": best_epoch,
                "best_validation_average_precision": best_value,
                "query_time": query_time,
                "ontology_schema": ontology.schema,
                "ontology_payload": ontology.payload,
                "graph_metadata": graph.metadata,
                "graph_manifest_sha256": _sha256(Path(graph_dir) / "manifest.json"),
            }
            torch.save(payload, best_path)
        else:
            no_improve += 1
            if no_improve >= config.patience:
                break

    # Reload best model for final metrics so the report and checkpoint agree.
    best_model, checkpoint = load_checkpoint(best_path, device)
    with torch.no_grad():
        final_outputs = best_model(batch, query_time)
    final_logits = final_outputs["link_logits"].float()
    final_metrics = {
        "train": _split_metrics(final_logits, batch, 0, config.threshold),
        "validation": _split_metrics(final_logits, batch, 1, config.threshold),
        "test": _split_metrics(final_logits, batch, 2, config.threshold),
    }
    validation_mask = batch["ex_split"] == 1
    calibration: dict[str, Any] = {"selection_split": "validation", "overall": best_f1_threshold(final_logits[validation_mask], batch["ex_label"][validation_mask]), "by_relation": {}}
    for relation in torch.unique(batch["ex_relation"][validation_mask]).tolist():
        relation_mask = validation_mask & (batch["ex_relation"] == int(relation))
        calibration["by_relation"][str(int(relation))] = best_f1_threshold(final_logits[relation_mask], batch["ex_label"][relation_mask])
    # Add the validation-only calibration to the checkpoint after selecting the
    # best epoch. This keeps query-time thresholds versioned with the weights.
    checkpoint["calibration"] = calibration
    torch.save(checkpoint, best_path)
    total_seconds = time.perf_counter() - start
    report = {
        "format": "UGTS-SPATIAL-TRAIN-REPORT-1",
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_runtime": torch.version.cuda,
        "amp_used": use_amp,
        "query_time": query_time,
        "epochs_completed": len(history),
        "best_epoch": best_epoch,
        "best_validation_average_precision": best_value,
        "total_seconds": total_seconds,
        "model": _model_parameter_summary(best_model),
        "tensors": batch_device_summary(batch),
        "graph_counts": {
            "nodes": graph.num_nodes,
            "edges": graph.num_edges,
            "events": graph.num_events,
            "examples": graph.num_examples,
        },
        "metrics": final_metrics,
        "calibration": calibration,
        "checkpoint_sha256": _sha256(best_path),
        "notes": [
            "The demonstration teacher vectors are deterministic hash fallbacks unless graph metadata states otherwise.",
            "Spatial holdout is defined by complete named areas, not random example rows.",
            "A learned probability proposes compatibility; deterministic support and guard logic remains authoritative for committed events.",
        ],
    }
    (output / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (output / "history.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(history[0].keys()) if history else ["epoch"])
        writer.writeheader(); writer.writerows(history)
    (output / "model_config.json").write_text(json.dumps(model_config.to_dict(), indent=2) + "\n", encoding="utf-8")
    (output / "train_config.json").write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    return report
