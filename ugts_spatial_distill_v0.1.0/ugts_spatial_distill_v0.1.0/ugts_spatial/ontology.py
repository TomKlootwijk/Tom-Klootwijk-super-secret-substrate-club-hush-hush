"""Compact typed ontology used by the sparse student and UGTS gate."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NodeType:
    id: int
    name: str
    sheet: int
    description: str = ""


@dataclass(frozen=True)
class RelationType:
    id: int
    name: str
    source_types: tuple[int, ...]
    target_types: tuple[int, ...]
    mode_bit: int
    symmetric: bool = False
    inverse: str | None = None
    guard: str = "semantic"
    description: str = ""


class Ontology:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.schema = str(payload.get("schema", "UGTS-SPATIAL-ONTOLOGY-1"))
        self.node_types = [NodeType(**x) for x in payload["node_types"]]
        self.relations = [
            RelationType(
                id=int(x["id"]),
                name=str(x["name"]),
                source_types=tuple(int(v) for v in x["source_types"]),
                target_types=tuple(int(v) for v in x["target_types"]),
                mode_bit=int(x["mode_bit"]),
                symmetric=bool(x.get("symmetric", False)),
                inverse=x.get("inverse"),
                guard=str(x.get("guard", "semantic")),
                description=str(x.get("description", "")),
            )
            for x in payload["relations"]
        ]
        self.node_by_name = {x.name: x for x in self.node_types}
        self.node_by_id = {x.id: x for x in self.node_types}
        self.rel_by_name = {x.name: x for x in self.relations}
        self.rel_by_id = {x.id: x for x in self.relations}
        if len(self.node_by_name) != len(self.node_types) or len(self.rel_by_name) != len(self.relations):
            raise ValueError("duplicate ontology names")
        if sorted(self.node_by_id) != list(range(len(self.node_types))):
            raise ValueError("node type ids must be contiguous from zero")
        if sorted(self.rel_by_id) != list(range(len(self.relations))):
            raise ValueError("relation ids must be contiguous from zero")

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls(json.load(f))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def compatible(self, relation_id: int, source_type: int, target_type: int) -> bool:
        rel = self.rel_by_id[int(relation_id)]
        return source_type in rel.source_types and target_type in rel.target_types

    def compatibility_mask_for_source(self, source_type: int) -> int:
        mask = 0
        for rel in self.relations:
            if source_type in rel.source_types:
                mask |= 1 << rel.mode_bit
        return mask & 0xFFFF

    @property
    def num_node_types(self) -> int:
        return len(self.node_types)

    @property
    def num_relations(self) -> int:
        return len(self.relations)
