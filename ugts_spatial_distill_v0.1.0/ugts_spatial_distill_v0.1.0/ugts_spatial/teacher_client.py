"""Offline teacher adapters for embeddings and structured relation labels.

The deployment student never requires an LLM at query time. These helpers call
an OpenAI-compatible local or hosted endpoint only while preparing supervision,
then persist compact embeddings/probabilities in the sparse graph directory.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

from .features import random_projection
from .graph import SparseTemporalGraph
from .ontology import Ontology


class TeacherEndpointError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080/v1", api_key: str = "local", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TeacherEndpointError(f"teacher HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TeacherEndpointError(f"teacher endpoint failed: {exc}") from exc

    def embeddings(self, texts: list[str], model: str = "local-embedding") -> np.ndarray:
        result = self._post("embeddings", {"model": model, "input": texts, "encoding_format": "float"})
        data = sorted(result.get("data", []), key=lambda x: int(x.get("index", 0)))
        if len(data) != len(texts):
            raise TeacherEndpointError(f"embedding count mismatch: expected {len(texts)}, received {len(data)}")
        vectors = np.asarray([x["embedding"] for x in data], dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            raise TeacherEndpointError("invalid embedding matrix returned by teacher")
        return vectors

    def chat_json(self, messages: list[dict[str, str]], model: str = "local-chat", temperature: float = 0.0) -> dict[str, Any]:
        result = self._post("chat/completions", {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        })
        try:
            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as exc:
            raise TeacherEndpointError(f"teacher did not return parseable JSON: {result}") from exc


def attach_teacher_embeddings(
    graph_dir: str | Path,
    output_dir: str | Path,
    client: OpenAICompatibleClient,
    *,
    model: str = "local-embedding",
    batch_size: int = 32,
    target_dim: int = 256,
    prefix: str = "Represent this geospatial or ontological entity for relation reasoning: ",
) -> Path:
    graph = SparseTemporalGraph.load(graph_dir, mmap=False, verify_hashes=True)
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    chunks: list[np.ndarray] = []
    for start in range(0, graph.num_nodes, batch_size):
        texts = [prefix + text for text in graph.texts[start:start + batch_size]]
        chunks.append(client.embeddings(texts, model=model))
    vectors = np.concatenate(chunks, axis=0)
    source_dim = int(vectors.shape[1])
    if target_dim:
        vectors = random_projection(vectors, target_dim)
    mask = np.ones(graph.num_nodes, dtype=np.bool_)
    metadata = dict(graph.metadata)
    metadata.update({
        "teacher_kind": "openai_compatible_embedding_endpoint",
        "teacher_model": model,
        "teacher_endpoint": client.base_url,
        "teacher_source_dim": source_dim,
        "teacher_dim": int(vectors.shape[1]),
        "teacher_projection": "seeded Gaussian JL" if source_dim != vectors.shape[1] else "identity",
        "teacher_embedded_unix": time.time(),
    })
    updated = replace(graph, teacher_embeddings=vectors.astype(np.float16), teacher_mask=mask, metadata=metadata)
    return updated.save(output_dir)


def export_relation_tasks(
    graph_dir: str | Path,
    ontology_path: str | Path,
    output_jsonl: str | Path,
    *,
    splits: Iterable[int] = (0,),
    max_records: int = 0,
) -> int:
    graph = SparseTemporalGraph.load(graph_dir, mmap=True, verify_hashes=True)
    ontology = Ontology.load(ontology_path)
    split_set = set(int(x) for x in splits)
    output = Path(output_jsonl)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8", newline="\n") as f:
        for i in range(graph.num_examples):
            if int(graph.ex_split[i]) not in split_set:
                continue
            relation = ontology.rel_by_id[int(graph.ex_relation[i])]
            task = {
                "example_index": i,
                "instruction": "Estimate whether the typed relation is semantically valid. Geometry is supplied as evidence but an exact geometric guard is evaluated separately. Return probability in [0,1] and a brief evidence field list.",
                "source": {"node_type": ontology.node_by_id[int(graph.node_types[graph.ex_src[i]])].name, "text": graph.texts[int(graph.ex_src[i])]},
                "target": {"node_type": ontology.node_by_id[int(graph.node_types[graph.ex_dst[i]])].name, "text": graph.texts[int(graph.ex_dst[i])]},
                "relation": relation.name,
                "distance_m": float(graph.ex_distance_m[i]),
                "required_output": {"example_index": i, "probability": "float 0..1", "evidence_fields": ["string"], "requires_geometric_verification": True},
            }
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
            count += 1
            if max_records and count >= max_records:
                break
    return count


def import_relation_labels(
    graph_dir: str | Path,
    labels_jsonl: str | Path,
    output_dir: str | Path,
) -> Path:
    graph = SparseTemporalGraph.load(graph_dir, mmap=False, verify_hashes=True)
    probabilities = graph.ex_teacher_prob.astype(np.float32, copy=True)
    changed = 0
    for line in Path(labels_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        index = int(row["example_index"])
        probability = float(row["probability"])
        if not 0 <= index < graph.num_examples:
            raise IndexError(f"example_index out of range: {index}")
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability out of range at example {index}")
        probabilities[index] = probability
        changed += 1
    metadata = dict(graph.metadata)
    metadata["teacher_relation_labels_imported"] = changed
    metadata["teacher_relation_labels_source"] = str(labels_jsonl)
    updated = replace(graph, ex_teacher_prob=probabilities, metadata=metadata)
    return updated.save(output_dir)
