from __future__ import annotations

import hashlib
import json
import math
import os
import random
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np
import torch


def stable_u64(value: str | bytes, *, namespace: str = "ugts") -> int:
    """Return a deterministic unsigned 64-bit identifier."""
    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    digest = hashlib.blake2b(namespace.encode("utf-8") + b"\0" + data, digest_size=8).digest()
    return int.from_bytes(digest, "little", signed=False)


def stable_u32(value: str | bytes, *, namespace: str = "ugts") -> int:
    return stable_u64(value, namespace=namespace) & 0xFFFFFFFF


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_json(path: str | os.PathLike[str], value: Any, *, indent: int = 2) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, sort_keys=True, indent=indent)
        fh.write("\n")


def read_json(path: str | os.PathLike[str]) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def batched(items: Sequence[Any] | np.ndarray, batch_size: int) -> Iterator[Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def human_bytes(value: int | float) -> str:
    x = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(x) < 1024.0 or unit == units[-1]:
            return f"{x:.3f} {unit}"
        x /= 1024.0
    return f"{x:.3f} TiB"


def l2_normalize_np(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(norms, eps)


def angular_difference_radians(a: float, b: float) -> float:
    return (a - b + math.pi) % (2.0 * math.pi) - math.pi


def torch_device(requested: str = "auto") -> torch.device:
    requested = requested.lower()
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    return torch.device(requested)


def safe_torch_load(path: str | os.PathLike[str], *, map_location: str | torch.device = "cpu") -> Any:
    # The package only loads checkpoints it produced itself. `weights_only=False`
    # is explicit because the checkpoint contains small JSON-like configuration.
    return torch.load(path, map_location=map_location, weights_only=False)
