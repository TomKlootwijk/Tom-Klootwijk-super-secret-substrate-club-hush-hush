"""Deterministic compact features and teacher-vector fallbacks.

The hash encoder is intentionally simple: it makes the demo and CPU tests fully
reproducible without pretending to replace a language model. Real embeddings can
be imported later through :mod:`ugts_spatial.teacher_client` without changing the
sparse graph format.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable

import numpy as np

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)


def _u64(data: bytes, person: bytes = b"UGTSFEAT") -> int:
    return int.from_bytes(hashlib.blake2b(data, digest_size=8, person=person[:16]).digest(), "little")


def tokens(text: str) -> list[str]:
    return [x.casefold() for x in _TOKEN_RE.findall(text)]


def hashed_text_embedding(text: str, dim: int, *, namespace: str = "text", normalize: bool = True) -> np.ndarray:
    """Feature-hash text into a signed dense vector.

    The function is a deterministic development fallback. It is useful for
    smoke tests and for constructing a graph before a real embedding teacher has
    been downloaded.
    """
    if dim <= 0:
        raise ValueError("dim must be positive")
    out = np.zeros(dim, dtype=np.float32)
    toks = tokens(text)
    if not toks:
        toks = ["<empty>"]
    # Unigrams and adjacent bigrams transfer a little local structure while
    # retaining a tiny implementation and deterministic storage contract.
    grams = toks + [f"{a}::{b}" for a, b in zip(toks, toks[1:])]
    for gram in grams:
        raw = f"{namespace}\0{gram}".encode("utf-8")
        h = _u64(raw)
        idx = h % dim
        sign = -1.0 if (h >> 63) else 1.0
        weight = 1.0 / math.sqrt(max(1.0, len(gram)))
        out[idx] += sign * weight
    if normalize:
        n = float(np.linalg.norm(out))
        if n > 0:
            out /= n
    return out


def deterministic_teacher_embedding(text: str, dim: int = 64) -> np.ndarray:
    """Reproducible synthetic teacher vector for a no-download first run."""
    base = hashed_text_embedding(text, dim, namespace="teacher", normalize=False)
    # Mix a second independent projection to avoid a single sparse hash pattern.
    base += 0.5 * hashed_text_embedding(text[::-1], dim, namespace="teacher-reverse", normalize=False)
    n = float(np.linalg.norm(base))
    return base / n if n > 0 else base


def random_projection(vectors: np.ndarray, target_dim: int, seed: int = 0x55475453) -> np.ndarray:
    """Project imported teacher vectors without storing a large learned adapter.

    A seeded Gaussian Johnson-Lindenstrauss projection is deterministic and is
    recorded in graph metadata. It is an engineering adapter, not model
    distillation by itself.
    """
    x = np.asarray(vectors, dtype=np.float32)
    if x.ndim != 2:
        raise ValueError("vectors must be a matrix")
    if target_dim <= 0:
        raise ValueError("target_dim must be positive")
    if x.shape[1] == target_dim:
        return x.copy()
    rng = np.random.default_rng(seed)
    matrix = rng.normal(0.0, 1.0 / math.sqrt(target_dim), size=(x.shape[1], target_dim)).astype(np.float32)
    out = x @ matrix
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(norms, 1e-12)


def compose_node_features(
    *,
    text: str,
    node_type: int,
    lat: float,
    lon: float,
    alt: float,
    numeric: Iterable[float] = (),
    dim: int = 32,
    center_lat: float = 52.5,
    center_lon: float = 5.5,
) -> np.ndarray:
    """Build a bounded numeric+hashed feature vector for the student."""
    if dim < 12:
        raise ValueError("feature dimension must be at least 12")
    out = np.zeros(dim, dtype=np.float32)
    vals = list(numeric)
    fixed_slots = min(16, dim // 2)
    fixed = [
        (lat - center_lat) / 1.5,
        (lon - center_lon) / 2.0,
        np.tanh(alt / 100.0),
        node_type / 16.0,
    ] + vals
    fixed = fixed[: min(len(fixed), fixed_slots)]
    out[: len(fixed)] = np.asarray(fixed, dtype=np.float32)
    hashed = hashed_text_embedding(text, dim - fixed_slots, namespace="node")
    out[fixed_slots:] = hashed
    return out
