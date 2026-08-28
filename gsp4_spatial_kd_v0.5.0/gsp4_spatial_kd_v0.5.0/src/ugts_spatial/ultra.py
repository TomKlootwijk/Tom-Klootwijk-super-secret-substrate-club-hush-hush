from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from .graph import GraphPackage
from .schema import RELATION_TYPE_BY_NAME, RELATION_TYPE_NAMES, relation_is_type_compatible
from .spatial import pair_edge_attr_numpy


def _safe_token(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").strip()


def export_ultra(package: GraphPackage, output_dir: str | Path) -> dict[str, Any]:
    """Export graph triples in the simple text layout accepted by ULTRA/NBFNet tools."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    entity_tokens = [f"n{int(node_id):016x}" for node_id in package.node_id.tolist()]
    relation_tokens = [RELATION_TYPE_NAMES[index] for index in range(16)]
    with open(output_dir / "entities.dict", "w", encoding="utf-8", newline="\n") as fh:
        for index, token in enumerate(entity_tokens):
            fh.write(f"{index}\t{token}\n")
    with open(output_dir / "relations.dict", "w", encoding="utf-8", newline="\n") as fh:
        for index, token in enumerate(relation_tokens):
            fh.write(f"{index}\t{token}\n")
    handles = {
        "train": open(output_dir / "train.txt", "w", encoding="utf-8", newline="\n"),
        "valid": open(output_dir / "valid.txt", "w", encoding="utf-8", newline="\n"),
        "test": open(output_dir / "test.txt", "w", encoding="utf-8", newline="\n"),
    }
    counts = {key: 0 for key in handles}
    try:
        for source, target, relation in zip(
            package.edge_index[0].tolist(),
            package.edge_index[1].tolist(),
            package.edge_type.tolist(),
        ):
            source_split = int(package.split[source])
            target_split = int(package.split[target])
            split_name = (
                "test"
                if 2 in (source_split, target_split)
                else "valid"
                if 1 in (source_split, target_split)
                else "train"
            )
            handles[split_name].write(
                f"{entity_tokens[source]}\t{relation_tokens[int(relation)]}\t{entity_tokens[target]}\n"
            )
            counts[split_name] += 1
    finally:
        for handle in handles.values():
            handle.close()
    with open(output_dir / "entity_metadata.tsv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(["token", "node_id", "key", "type", "text"])
        for index, token in enumerate(entity_tokens):
            writer.writerow(
                [
                    token,
                    int(package.node_id[index]),
                    _safe_token(package.keys[index]),
                    int(package.node_type[index]),
                    _safe_token(package.texts[index]),
                ]
            )
    return {
        "format": "UGTS-ULTRA-EXPORT-1",
        "entities": package.num_nodes,
        "relations": 16,
        "triples": counts,
        "output_dir": str(output_dir),
    }


def import_scored_relations(
    package: GraphPackage,
    score_path: str | Path,
    *,
    minimum_score: float = 0.8,
) -> GraphPackage:
    """Import TSV rows: ``source_key relation target_key score``.

    Scores become edge supervision weights. Exact spatial/guarded relations are
    still re-checked at query time.
    """
    key_lookup = package.key_index()
    rows: list[tuple[int, int, int, float]] = []
    with open(score_path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        required = {"source_key", "relation", "target_key", "score"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"score TSV must contain columns {sorted(required)}")
        for row in reader:
            score = float(row["score"])
            if score < minimum_score:
                continue
            source = key_lookup[row["source_key"]]
            target = key_lookup[row["target_key"]]
            relation_text = row["relation"].strip().lower()
            relation = (
                int(relation_text)
                if relation_text.isdigit()
                else RELATION_TYPE_BY_NAME[relation_text]
            )
            if not relation_is_type_compatible(
                relation, int(package.node_type[source]), int(package.node_type[target])
            ):
                raise ValueError("ULTRA score violates ontology type compatibility")
            rows.append((source, target, relation, min(1.0, max(0.0, score))))
    if not rows:
        return package
    edge_index = np.asarray(
        [[row[0] for row in rows], [row[1] for row in rows]], dtype=np.int64
    )
    edge_type = np.asarray([row[2] for row in rows], dtype=np.int64)
    edge_weight = np.asarray([row[3] for row in rows], dtype=np.float32)
    edge_time = np.maximum(
        package.node_time[edge_index[0]], package.node_time[edge_index[1]]
    )
    edge_attr = pair_edge_attr_numpy(
        package.latitude,
        package.longitude,
        package.elevation,
        package.node_time,
        edge_index,
    )
    return package.append_edges(
        edge_index,
        edge_type,
        edge_time=edge_time,
        edge_weight=edge_weight,
        edge_attr=edge_attr,
        metadata_patch={
            "ultra_import": {
                "source": str(score_path),
                "minimum_score": minimum_score,
                "accepted": len(rows),
                "authority": "structural prior only",
            }
        },
    )
