"""Task and distillation objectives."""
from __future__ import annotations

from dataclasses import dataclass

import torch
from torch.nn import functional as F


@dataclass(frozen=True)
class LossWeights:
    task: float = 1.0
    teacher_probability: float = 0.5
    teacher_embedding: float = 0.25
    confidence_margin: float = 0.05


def binary_distillation_loss(
    outputs: dict[str, torch.Tensor],
    labels: torch.Tensor,
    teacher_prob: torch.Tensor,
    example_mask: torch.Tensor,
    teacher_embeddings: torch.Tensor | None,
    teacher_mask: torch.Tensor | None,
    weights: LossWeights,
) -> tuple[torch.Tensor, dict[str, float]]:
    logits = outputs["link_logits"][example_mask]
    y = labels[example_mask]
    t = teacher_prob[example_mask].clamp(1e-4, 1.0 - 1e-4)
    task = F.binary_cross_entropy_with_logits(logits, y)
    soft = F.binary_cross_entropy_with_logits(logits, t)
    embedding = logits.new_zeros(())
    if teacher_embeddings is not None and teacher_mask is not None and torch.any(teacher_mask):
        student = F.normalize(outputs["teacher_embedding"][teacher_mask].float(), dim=-1)
        teacher = F.normalize(teacher_embeddings[teacher_mask].float(), dim=-1)
        embedding = (1.0 - (student * teacher).sum(dim=-1)).mean()
    # Penalize overconfident divergence from the teacher around uncertain examples.
    prob = torch.sigmoid(logits)
    uncertain = 1.0 - (t - 0.5).abs() * 2.0
    margin = (uncertain * (prob - t).abs()).mean()
    total = weights.task * task + weights.teacher_probability * soft + weights.teacher_embedding * embedding + weights.confidence_margin * margin
    return total, {
        "loss": float(total.detach()),
        "task": float(task.detach()),
        "teacher_probability": float(soft.detach()),
        "teacher_embedding": float(embedding.detach()),
        "confidence_margin": float(margin.detach()),
    }
