"""Small dependency-free binary classification metrics."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import torch


def _as_numpy(x: torch.Tensor | np.ndarray) -> np.ndarray:
    if isinstance(x, torch.Tensor):
        return x.detach().float().cpu().numpy()
    return np.asarray(x)


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    y = np.asarray(labels, dtype=np.int8)
    s = np.asarray(scores, dtype=np.float64)
    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=np.float64)
    i = 0
    while i < len(s):
        j = i + 1
        while j < len(s) and s[order[j]] == s[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        ranks[order[i:j]] = rank
        i = j
    rank_sum = ranks[y == 1].sum()
    return float((rank_sum - pos * (pos + 1) / 2.0) / (pos * neg))


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    y = np.asarray(labels, dtype=np.int8)
    s = np.asarray(scores, dtype=np.float64)
    pos = int((y == 1).sum())
    if pos == 0:
        return float("nan")
    order = np.argsort(-s, kind="mergesort")
    ranked = y[order]
    tp = np.cumsum(ranked == 1)
    precision = tp / np.arange(1, len(y) + 1)
    return float(precision[ranked == 1].sum() / pos)


def expected_calibration_error(labels: np.ndarray, probs: np.ndarray, bins: int = 10) -> float:
    y = np.asarray(labels, dtype=np.float64)
    p = np.asarray(probs, dtype=np.float64)
    total = max(1, len(y))
    ece = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for i in range(bins):
        if i == bins - 1:
            mask = (p >= edges[i]) & (p <= edges[i + 1])
        else:
            mask = (p >= edges[i]) & (p < edges[i + 1])
        if mask.any():
            ece += mask.sum() / total * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(ece)


def binary_metrics(logits: torch.Tensor | np.ndarray, labels: torch.Tensor | np.ndarray, threshold: float = 0.5) -> dict[str, Any]:
    log = _as_numpy(logits).reshape(-1)
    y = _as_numpy(labels).reshape(-1).astype(np.int8)
    p = 1.0 / (1.0 + np.exp(-np.clip(log, -40.0, 40.0)))
    pred = p >= threshold
    tp = int(((pred == 1) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "count": int(len(y)),
        "positives": int((y == 1).sum()),
        "accuracy": float((pred == y).mean()) if len(y) else float("nan"),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "roc_auc": roc_auc(y, p),
        "average_precision": average_precision(y, p),
        "brier": float(np.mean((p - y) ** 2)) if len(y) else float("nan"),
        "ece_10": expected_calibration_error(y, p, 10) if len(y) else float("nan"),
        "threshold": float(threshold),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def best_f1_threshold(logits: torch.Tensor | np.ndarray, labels: torch.Tensor | np.ndarray) -> dict[str, float]:
    """Choose a validation-only probability threshold maximizing F1.

    Ties prefer the threshold closest to 0.5, then the larger threshold. The
    selected value must be recorded with the checkpoint; it is not a universal
    property of a relation.
    """
    log = _as_numpy(logits).reshape(-1)
    y = _as_numpy(labels).reshape(-1).astype(np.int8)
    if len(y) == 0:
        return {"threshold": 0.5, "f1": float("nan")}
    p = 1.0 / (1.0 + np.exp(-np.clip(log, -40.0, 40.0)))
    candidates = np.unique(np.concatenate(([0.0, 0.5, 1.0], p)))
    best = (-1.0, float("inf"), -1.0)
    best_t = 0.5
    for threshold in candidates:
        pred = p >= threshold
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        f1 = 2 * precision * recall / max(1e-12, precision + recall)
        key = (f1, -abs(float(threshold) - 0.5), float(threshold))
        if key > best:
            best = key
            best_t = float(threshold)
    return {"threshold": best_t, "f1": float(best[0])}
