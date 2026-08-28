from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import time
from typing import Any

import torch
import torch.nn.functional as F

from .edge_teacher import TeacherEdgeSet
from .graph import GraphPackage
from .model import ModelConfig, UGTSSpatialModel
from .schema import NodeType, RelationType
from .spatial import pair_edge_attr_torch
from .utils import safe_torch_load, seed_everything, torch_device, write_json


@dataclass(frozen=True)
class TrainConfig:
    hidden_dim: int = 128
    heads: int = 4
    layers: int = 3
    dropout: float = 0.10
    epochs: int = 40
    learning_rate: float = 2.0e-3
    weight_decay: float = 1.0e-4
    link_weight: float = 1.0
    node_teacher_weight: float = 0.50
    edge_teacher_weight: float = 0.35
    type_weight: float = 0.15
    temporal_weight: float = 0.20
    negatives_per_positive: int = 1
    max_edges_per_epoch: int = 50_000
    max_encoder_edges: int = 250_000
    max_teacher_edges_per_epoch: int = 20_000
    temporal_edges_per_epoch: int = 4096
    early_stopping_patience: int = 12
    seed: int = 20260710
    device: str = "auto"
    precision: str = "float32"
    compile_model: bool = False

    def validate(self) -> None:
        if self.hidden_dim <= 0 or self.heads <= 0 or self.hidden_dim % self.heads:
            raise ValueError("hidden_dim must be positive and divisible by heads")
        if self.layers <= 0 or self.epochs <= 0:
            raise ValueError("layers and epochs must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0,1)")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("invalid optimizer parameters")
        if self.negatives_per_positive <= 0:
            raise ValueError("negatives_per_positive must be positive")
        if self.precision not in {"float32", "float16", "bf16"}:
            raise ValueError("precision must be float32, float16 or bf16")


@dataclass
class TrainingResult:
    checkpoint_path: str
    metrics_path: str
    final_metrics: dict[str, float]
    history: list[dict[str, float]]


def _filtered_graph_tensors(
    graph: dict[str, torch.Tensor], edge_positions: torch.Tensor
) -> dict[str, torch.Tensor]:
    result = dict(graph)
    result["edge_index"] = graph["edge_index"][:, edge_positions]
    for key in ("edge_type", "edge_time", "edge_weight", "edge_attr"):
        result[key] = graph[key][edge_positions]
    return result


def _sample_positions(
    positions: torch.Tensor, maximum: int, generator: torch.Generator
) -> torch.Tensor:
    if maximum > 0 and positions.numel() > maximum:
        order = torch.randperm(
            positions.numel(), generator=generator, device=positions.device
        )[:maximum]
        return positions[order]
    return positions


def _negative_edges(
    graph: dict[str, torch.Tensor],
    positive_index: torch.Tensor,
    positive_type: torch.Tensor,
    *,
    multiplier: int,
    generator: torch.Generator,
) -> tuple[torch.Tensor, torch.Tensor]:
    source = positive_index[0].repeat_interleave(multiplier)
    relation = positive_type.repeat_interleave(multiplier)
    positive_target = positive_index[1].repeat_interleave(multiplier)
    target_type = graph["node_type"][positive_target]
    sampled_target = torch.empty_like(positive_target)
    for type_value in torch.unique(target_type).tolist():
        rows = torch.nonzero(target_type == int(type_value), as_tuple=False).flatten()
        candidates = torch.nonzero(graph["node_type"] == int(type_value), as_tuple=False).flatten()
        if candidates.numel() == 0:
            raise RuntimeError(f"no nodes for negative target type {type_value}")
        choices = torch.randint(
            candidates.numel(),
            (rows.numel(),),
            generator=generator,
            device=candidates.device,
        )
        sampled_target[rows] = candidates[choices]
    for row in torch.nonzero(sampled_target == positive_target, as_tuple=False).flatten().tolist():
        candidates = torch.nonzero(graph["node_type"] == target_type[row], as_tuple=False).flatten()
        if candidates.numel() <= 1:
            continue
        matching = torch.nonzero(candidates == positive_target[row], as_tuple=False).flatten()
        current = int(matching[0].item()) if matching.numel() else 0
        sampled_target[row] = candidates[(current + 1) % candidates.numel()]
    return torch.stack((source, sampled_target), dim=0), relation


def _autocast_context(device: torch.device, precision: str):
    if device.type != "cuda" or precision == "float32":
        return nullcontext()
    dtype = torch.float16 if precision == "float16" else torch.bfloat16
    return torch.autocast(device_type="cuda", dtype=dtype)


def _evaluate_split(
    model: UGTSSpatialModel,
    encoded: torch.Tensor,
    graph: dict[str, torch.Tensor],
    split_value: int,
    generator: torch.Generator,
) -> dict[str, float]:
    source_split = graph["split"][graph["edge_index"][0]]
    target_split = graph["split"][graph["edge_index"][1]]
    positions = torch.nonzero(
        (source_split == split_value) | (target_split == split_value), as_tuple=False
    ).flatten()
    if positions.numel() == 0:
        return {
            "link_accuracy": float("nan"),
            "link_margin": float("nan"),
            "teacher_cosine": float("nan"),
        }
    positions = positions[: min(10_000, positions.numel())]
    positive_index = graph["edge_index"][:, positions]
    positive_type = graph["edge_type"][positions]
    positive_attr = graph["edge_attr"][positions]
    negative_index, negative_type = _negative_edges(
        graph,
        positive_index,
        positive_type,
        multiplier=1,
        generator=generator,
    )
    negative_attr = pair_edge_attr_torch(graph, negative_index)
    positive_score = model.score_edges(
        encoded, positive_index, positive_type, positive_attr
    )
    negative_score = model.score_edges(
        encoded, negative_index, negative_type, negative_attr
    )
    accuracy = (
        (positive_score > 0).float().mean()
        + (negative_score < 0).float().mean()
    ) * 0.5
    margin = positive_score.mean() - negative_score.mean()
    teacher_mask = (graph["split"] == split_value) & graph["teacher_mask"]
    if model.config.teacher_dim > 0 and teacher_mask.any():
        predicted = model.predict_teacher(encoded[teacher_mask])
        target = F.normalize(graph["teacher_x"][teacher_mask], dim=-1)
        cosine = F.cosine_similarity(predicted, target, dim=-1).mean()
        teacher_cosine = float(cosine.item())
    else:
        teacher_cosine = float("nan")
    return {
        "link_accuracy": float(accuracy.item()),
        "link_margin": float(margin.item()),
        "teacher_cosine": teacher_cosine,
    }


def train_model(
    package: GraphPackage,
    checkpoint_path: str | Path,
    *,
    metrics_path: str | Path | None = None,
    config: TrainConfig | None = None,
    teacher_edges: TeacherEdgeSet | None = None,
) -> TrainingResult:
    config = config or TrainConfig()
    config.validate()
    seed_everything(config.seed)
    device = torch_device(config.device)
    graph = package.to_torch(device)

    edge_teacher = None
    teacher_relation_count = 0
    if teacher_edges is not None:
        teacher_edges.validate(package)
        edge_teacher = teacher_edges.to_torch(device)
        if edge_teacher["edge_type"].numel():
            teacher_relation_count = int(edge_teacher["edge_type"].max().item()) + 1

    model_config = ModelConfig(
        input_dim=package.input_dim,
        teacher_dim=package.teacher_dim,
        edge_dim=package.edge_dim,
        num_node_types=max(package.num_node_types, len(NodeType)),
        num_relations=max(package.num_relations, teacher_relation_count, len(RelationType)),
        hidden_dim=config.hidden_dim,
        num_heads=config.heads,
        num_layers=config.layers,
        dropout=config.dropout,
    )
    model: UGTSSpatialModel | Any = UGTSSpatialModel(model_config).to(device)
    if config.compile_model:
        if not hasattr(torch, "compile"):
            raise RuntimeError("this PyTorch build has no torch.compile")
        model = torch.compile(model)

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    use_scaler = device.type == "cuda" and config.precision == "float16"
    scaler = torch.amp.GradScaler("cuda", enabled=use_scaler)
    generator = torch.Generator(device=device)
    generator.manual_seed(config.seed)

    source_split = graph["split"][graph["edge_index"][0]]
    target_split = graph["split"][graph["edge_index"][1]]
    train_edge_positions = torch.nonzero(
        (source_split == 0) & (target_split == 0), as_tuple=False
    ).flatten()
    if train_edge_positions.numel() == 0:
        raise ValueError("graph has no train-to-train edges")
    encoder_positions = _sample_positions(
        train_edge_positions, config.max_encoder_edges, generator
    )
    encoder_graph = _filtered_graph_tensors(graph, encoder_positions)
    train_nodes = graph["split"] == 0
    node_teacher_rows = train_nodes & graph["teacher_mask"]
    temporal_positions_all = train_edge_positions[
        graph["edge_time"][train_edge_positions] > 0
    ]

    if edge_teacher is not None and edge_teacher["edge_type"].numel():
        teacher_source_split = graph["split"][edge_teacher["edge_index"][0]]
        teacher_target_split = graph["split"][edge_teacher["edge_index"][1]]
        teacher_positions_all = torch.nonzero(
            (teacher_source_split == 0) & (teacher_target_split == 0), as_tuple=False
        ).flatten()
    else:
        teacher_positions_all = torch.zeros(0, dtype=torch.int64, device=device)

    history: list[dict[str, float]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_score = -float("inf")
    best_epoch = 0
    start_time = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    for epoch in range(1, config.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        positive_positions = _sample_positions(
            train_edge_positions, config.max_edges_per_epoch, generator
        )
        positive_index = graph["edge_index"][:, positive_positions]
        positive_type = graph["edge_type"][positive_positions]
        positive_attr = graph["edge_attr"][positive_positions]
        negative_index, negative_type = _negative_edges(
            graph,
            positive_index,
            positive_type,
            multiplier=config.negatives_per_positive,
            generator=generator,
        )
        negative_attr = pair_edge_attr_torch(graph, negative_index)

        with _autocast_context(device, config.precision):
            outputs = model(encoder_graph)
            state = outputs["node_state"]
            positive_score = model.score_edges(
                state, positive_index, positive_type, positive_attr
            )
            negative_score = model.score_edges(
                state, negative_index, negative_type, negative_attr
            )
            positive_rows = F.binary_cross_entropy_with_logits(
                positive_score, torch.ones_like(positive_score), reduction="none"
            )
            positive_weight = graph["edge_weight"][positive_positions].to(
                positive_rows.dtype
            ).clamp(0.05, 1.0)
            link_loss = (
                positive_rows * positive_weight
            ).sum() / positive_weight.sum().clamp_min(1.0)
            link_loss = link_loss + F.binary_cross_entropy_with_logits(
                negative_score, torch.zeros_like(negative_score)
            )

            type_loss = F.cross_entropy(
                outputs["type_logits"][train_nodes], graph["node_type"][train_nodes]
            )

            if package.teacher_dim > 0 and node_teacher_rows.any():
                predicted_teacher = outputs["teacher_embedding"][node_teacher_rows]
                target_teacher = F.normalize(
                    graph["teacher_x"][node_teacher_rows], dim=-1
                )
                node_teacher_loss = (
                    1.0
                    - F.cosine_similarity(
                        predicted_teacher, target_teacher, dim=-1
                    )
                ).mean()
            else:
                node_teacher_loss = state.new_zeros(())

            if teacher_positions_all.numel() and edge_teacher is not None:
                teacher_positions = _sample_positions(
                    teacher_positions_all,
                    config.max_teacher_edges_per_epoch,
                    generator,
                )
                teacher_index = edge_teacher["edge_index"][:, teacher_positions]
                teacher_type = edge_teacher["edge_type"][teacher_positions]
                teacher_probability = edge_teacher["probability"][teacher_positions]
                teacher_weight = edge_teacher["weight"][teacher_positions].clamp_min(0.0)
                teacher_attr = pair_edge_attr_torch(graph, teacher_index)
                teacher_score = model.score_edges(
                    state, teacher_index, teacher_type, teacher_attr
                )
                teacher_rows = F.binary_cross_entropy_with_logits(
                    teacher_score, teacher_probability, reduction="none"
                )
                edge_teacher_loss = (
                    teacher_rows * teacher_weight
                ).sum() / teacher_weight.sum().clamp_min(1.0)
            else:
                edge_teacher_loss = state.new_zeros(())

            if temporal_positions_all.numel() >= 2:
                temporal_positions = _sample_positions(
                    temporal_positions_all, config.temporal_edges_per_epoch, generator
                )
                event_index = graph["edge_index"][:, temporal_positions]
                event_type = graph["edge_type"][temporal_positions]
                event_time = graph["edge_time"][temporal_positions]
                event_value = graph["edge_weight"][temporal_positions]
                event_attr = graph["edge_attr"][temporal_positions]
                order = torch.argsort(event_time)
                cut = max(1, order.numel() // 2)
                context_rows = order[:cut]
                target_rows = order[cut:]
                memory = model.update_memory(
                    state,
                    None,
                    event_index[:, context_rows],
                    event_type[context_rows],
                    event_time[context_rows],
                    event_value[context_rows],
                    event_attr[context_rows],
                    event_time[context_rows].min(),
                )
                temporal_state = state + memory
                if target_rows.numel():
                    temporal_positive_index = event_index[:, target_rows]
                    temporal_positive_type = event_type[target_rows]
                    temporal_positive_attr = event_attr[target_rows]
                    temporal_negative_index, temporal_negative_type = _negative_edges(
                        graph,
                        temporal_positive_index,
                        temporal_positive_type,
                        multiplier=1,
                        generator=generator,
                    )
                    temporal_negative_attr = pair_edge_attr_torch(
                        graph, temporal_negative_index
                    )
                    temporal_positive_score = model.score_edges(
                        temporal_state,
                        temporal_positive_index,
                        temporal_positive_type,
                        temporal_positive_attr,
                    )
                    temporal_negative_score = model.score_edges(
                        temporal_state,
                        temporal_negative_index,
                        temporal_negative_type,
                        temporal_negative_attr,
                    )
                    temporal_loss = F.binary_cross_entropy_with_logits(
                        temporal_positive_score,
                        torch.ones_like(temporal_positive_score),
                    ) + F.binary_cross_entropy_with_logits(
                        temporal_negative_score,
                        torch.zeros_like(temporal_negative_score),
                    )
                else:
                    temporal_loss = state.new_zeros(())
            else:
                temporal_loss = state.new_zeros(())

            loss = (
                config.link_weight * link_loss
                + config.node_teacher_weight * node_teacher_loss
                + config.edge_teacher_weight * edge_teacher_loss
                + config.type_weight * type_loss
                + config.temporal_weight * temporal_loss
            )

        if use_scaler:
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()

        model.eval()
        with torch.no_grad(), _autocast_context(device, config.precision):
            evaluation_state = model(encoder_graph)["node_state"]
            validation = _evaluate_split(
                model, evaluation_state, graph, 1, generator
            )
            training = _evaluate_split(model, evaluation_state, graph, 0, generator)
        score = validation["link_margin"]
        if math.isnan(score):
            score = -float(loss.item())
        if score > best_score:
            best_score = score
            best_epoch = epoch
            base_model = model._orig_mod if hasattr(model, "_orig_mod") else model
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in base_model.state_dict().items()
            }

        history.append(
            {
                "epoch": float(epoch),
                "loss": float(loss.item()),
                "link_loss": float(link_loss.item()),
                "node_teacher_loss": float(node_teacher_loss.item()),
                "edge_teacher_loss": float(edge_teacher_loss.item()),
                "type_loss": float(type_loss.item()),
                "temporal_loss": float(temporal_loss.item()),
                "train_link_accuracy": training["link_accuracy"],
                "train_link_margin": training["link_margin"],
                "validation_link_accuracy": validation["link_accuracy"],
                "validation_link_margin": validation["link_margin"],
                "validation_teacher_cosine": validation["teacher_cosine"],
            }
        )
        if (
            config.early_stopping_patience > 0
            and epoch - best_epoch >= config.early_stopping_patience
        ):
            break

    base_model = model._orig_mod if hasattr(model, "_orig_mod") else model
    if best_state is not None:
        base_model.load_state_dict(best_state)
    base_model.eval()
    with torch.no_grad(), _autocast_context(device, config.precision):
        final_state = base_model(encoder_graph)["node_state"]
        validation = _evaluate_split(base_model, final_state, graph, 1, generator)
        test = _evaluate_split(base_model, final_state, graph, 2, generator)
    elapsed = time.perf_counter() - start_time
    final_metrics = {
        "elapsed_s": float(elapsed),
        "epochs_completed": float(len(history)),
        "best_epoch": float(best_epoch),
        "best_validation_link_margin": float(best_score),
        "validation_link_accuracy": validation["link_accuracy"],
        "validation_link_margin": validation["link_margin"],
        "validation_teacher_cosine": validation["teacher_cosine"],
        "test_link_accuracy": test["link_accuracy"],
        "test_link_margin": test["link_margin"],
        "test_teacher_cosine": test["teacher_cosine"],
        "device_cuda": float(device.type == "cuda"),
        "peak_cuda_memory_bytes": float(
            torch.cuda.max_memory_allocated(device) if device.type == "cuda" else 0
        ),
    }

    checkpoint_path = Path(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = base_model.checkpoint(
        schema_hash=package.schema_hash,
        extra={
            "train_config": asdict(config),
            "final_metrics": final_metrics,
            "graph_summary": package.summary(),
            "teacher_edge_summary": (
                teacher_edges.summary() if teacher_edges is not None else None
            ),
            "encoder_edges": int(encoder_positions.numel()),
        },
    )
    torch.save(checkpoint, checkpoint_path)
    metrics_path = (
        Path(metrics_path)
        if metrics_path is not None
        else checkpoint_path.with_suffix(".metrics.json")
    )
    write_json(
        metrics_path,
        {
            "format": "UGTS-SPATIAL-TRAINING-METRICS-2",
            "graph_schema_hash": package.schema_hash,
            "train_config": asdict(config),
            "model_config": model_config.to_dict(),
            "final_metrics": final_metrics,
            "history": history,
        },
    )
    return TrainingResult(
        checkpoint_path=str(checkpoint_path),
        metrics_path=str(metrics_path),
        final_metrics=final_metrics,
        history=history,
    )


def load_model_for_graph(
    package: GraphPackage,
    checkpoint_path: str | Path,
    *,
    device: str = "auto",
) -> tuple[UGTSSpatialModel, torch.device, dict[str, Any]]:
    selected = torch_device(device)
    checkpoint = safe_torch_load(checkpoint_path, map_location=selected)
    model = UGTSSpatialModel.from_checkpoint(
        checkpoint, expected_schema_hash=package.schema_hash
    )
    model.to(selected).eval()
    return model, selected, checkpoint
