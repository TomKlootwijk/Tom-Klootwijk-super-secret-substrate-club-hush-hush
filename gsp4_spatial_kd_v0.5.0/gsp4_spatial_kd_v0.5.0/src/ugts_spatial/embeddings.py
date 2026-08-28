from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import re
from typing import Any, Iterable, Protocol, Sequence
from urllib import error as urlerror
from urllib import request as urlrequest

import numpy as np

from .utils import batched, l2_normalize_np, stable_u64

_TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


class Embedder(Protocol):
    name: str
    dimensions: int

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


@dataclass
class HashEmbedder:
    """Dependency-free deterministic lexical smoke-test embedder.

    It is intentionally not a language model. It allows the complete graph and
    distillation path to be tested before a real teacher is downloaded.
    """

    dimensions: int = 64
    name: str = "hash-lexical-v1"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if self.dimensions <= 0:
            raise ValueError("dimensions must be positive")
        out = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = [token.casefold() for token in _TOKEN_RE.findall(text)]
            if not tokens:
                tokens = ["<empty>"]
            for position, token in enumerate(tokens):
                for ngram in (token, f"{token[:3]}#", f"#{token[-3:]}"):
                    h = stable_u64(ngram, namespace="ugts-hash-embedding")
                    index = h % self.dimensions
                    sign = 1.0 if ((h >> 63) & 1) == 0 else -1.0
                    weight = 1.0 / math.sqrt(position + 1.0)
                    out[row, index] += sign * weight
        return l2_normalize_np(out)


@dataclass
class OpenAICompatibleEmbedder:
    """Embedding client for llama.cpp or another OpenAI-compatible endpoint."""

    base_url: str = "http://127.0.0.1:8080/v1"
    model: str = "Qwen3-Embedding-0.6B-GGUF"
    dimensions: int = 256
    batch_size: int = 32
    timeout_s: float = 120.0
    api_key: str | None = None
    instruction: str = (
        "Represent this Dutch or multilingual geospatial entity for ontology "
        "classification, spatial relation prediction and temporal knowledge transfer."
    )
    name: str = "openai-compatible-embedding"

    def _request(self, texts: Sequence[str]) -> np.ndarray:
        endpoint = self.base_url.rstrip("/") + "/embeddings"
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [f"Instruct: {self.instruction}\nInput: {text}" for text in texts],
            "encoding_format": "float",
        }
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        token = self.api_key or os.getenv("UGTS_TEACHER_API_KEY")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urlrequest.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as response:
                raw = response.read()
        except urlerror.URLError as exc:
            raise RuntimeError(f"embedding request failed for {endpoint}: {exc}") from exc
        parsed = json.loads(raw.decode("utf-8"))
        data = sorted(parsed.get("data", []), key=lambda row: int(row.get("index", 0)))
        vectors = np.asarray([row["embedding"] for row in data], dtype=np.float32)
        if vectors.shape[0] != len(texts):
            raise RuntimeError(f"embedding server returned {vectors.shape[0]} rows for {len(texts)} inputs")
        if self.dimensions > 0 and vectors.shape[1] != self.dimensions:
            if vectors.shape[1] < self.dimensions:
                raise RuntimeError(
                    f"server returned {vectors.shape[1]} dimensions, fewer than requested {self.dimensions}"
                )
            # Matryoshka-compatible models support prefixes; truncation also
            # keeps the adapter usable when a server ignores `dimensions`.
            vectors = vectors[:, : self.dimensions]
        return l2_normalize_np(vectors)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        outputs: list[np.ndarray] = []
        for batch in batched(list(texts), self.batch_size):
            outputs.append(self._request(batch))
        if not outputs:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return np.concatenate(outputs, axis=0)


@dataclass
class SentenceTransformerEmbedder:
    model_path: str
    dimensions: int = 256
    batch_size: int = 32
    device: str = "auto"
    instruction: str = (
        "Represent this Dutch or multilingual geospatial entity for ontology "
        "classification, spatial relation prediction and temporal knowledge transfer."
    )
    name: str = "sentence-transformers-local"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "SentenceTransformer backend requires `pip install .[local-embeddings]`"
            ) from exc
        device = None if self.device == "auto" else self.device
        model = SentenceTransformer(self.model_path, device=device, trust_remote_code=True)
        prompted = [f"Instruct: {self.instruction}\nInput: {text}" for text in texts]
        vectors = np.asarray(
            model.encode(
                prompted,
                batch_size=self.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=True,
            ),
            dtype=np.float32,
        )
        if self.dimensions > 0:
            if vectors.shape[1] < self.dimensions:
                raise RuntimeError(
                    f"model emitted {vectors.shape[1]} dimensions, fewer than requested {self.dimensions}"
                )
            vectors = vectors[:, : self.dimensions]
        return l2_normalize_np(vectors)


def make_embedder(
    backend: str,
    *,
    dimensions: int = 256,
    base_url: str = "http://127.0.0.1:8080/v1",
    model: str = "Qwen3-Embedding-0.6B-GGUF",
    model_path: str | None = None,
    batch_size: int = 32,
    device: str = "auto",
) -> Embedder:
    backend = backend.lower()
    if backend == "hash":
        return HashEmbedder(dimensions=dimensions)
    if backend in {"http", "llama", "openai-compatible"}:
        return OpenAICompatibleEmbedder(
            base_url=base_url,
            model=model,
            dimensions=dimensions,
            batch_size=batch_size,
        )
    if backend in {"sentence-transformers", "st"}:
        if not model_path:
            raise ValueError("--model-path is required for sentence-transformers backend")
        return SentenceTransformerEmbedder(
            model_path=model_path,
            dimensions=dimensions,
            batch_size=batch_size,
            device=device,
        )
    raise ValueError(f"unknown embedding backend: {backend}")
