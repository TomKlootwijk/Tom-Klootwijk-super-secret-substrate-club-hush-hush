"""Typed literal-definition records for UGTS-KC 3.6."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .canonical import verify_content_hash
from .topology import topological_order


@dataclass(frozen=True)
class DefinitionNode:
    id: str
    kind: str
    domain: str
    codomain: str
    dependencies: tuple[str, ...]
    evaluation_phase: int
    record: Mapping[str, Any]

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "DefinitionNode":
        required = ("id", "kind", "domain", "codomain", "evaluation_phase", "content_hash")
        missing = [field for field in required if field not in record]
        if missing:
            raise ValueError(f"definition missing fields: {', '.join(missing)}")
        if not verify_content_hash(record):
            raise ValueError(f"invalid content hash for {record['id']}")
        return cls(
            id=str(record["id"]),
            kind=str(record["kind"]),
            domain=str(record["domain"]),
            codomain=str(record["codomain"]),
            dependencies=tuple(record.get("dependencies", ())),
            evaluation_phase=int(record["evaluation_phase"]),
            record=dict(record),
        )


@dataclass
class Substrate:
    schema_version: str
    substrate_id: str
    definitions: dict[str, DefinitionNode]
    instances: list[dict[str, Any]]
    pipelines: list[dict[str, Any]]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Substrate":
        definitions: dict[str, DefinitionNode] = {}
        for record in raw.get("definitions", []):
            node = DefinitionNode.from_record(record)
            if node.id in definitions:
                raise ValueError(f"duplicate definition id: {node.id}")
            definitions[node.id] = node
        substrate = cls(
            schema_version=str(raw["schema_version"]),
            substrate_id=str(raw["substrate_id"]),
            definitions=definitions,
            instances=[dict(item) for item in raw.get("instances", [])],
            pipelines=[dict(item) for item in raw.get("pipelines", [])],
            raw=dict(raw),
        )
        substrate.validate_references()
        return substrate

    @classmethod
    def load(cls, path: str | Path) -> "Substrate":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def validate_references(self) -> None:
        for node in self.definitions.values():
            unknown = [dep for dep in node.dependencies if dep not in self.definitions]
            if unknown:
                raise KeyError(f"{node.id} has unknown dependencies: {unknown}")
        for instance in self.instances:
            ref = instance.get("definition_ref")
            if ref not in self.definitions:
                raise KeyError(f"instance {instance.get('id')} references unknown definition {ref}")
        for pipeline in self.pipelines:
            for ref in pipeline.get("steps", []):
                if ref not in self.definitions:
                    raise KeyError(f"pipeline {pipeline.get('id')} references unknown definition {ref}")
        self.definition_order()

    def definition_order(self) -> tuple[str, ...]:
        ids = tuple(self.definitions)
        deps = {node.id: node.dependencies for node in self.definitions.values()}
        return topological_order(ids, deps)

    def definition(self, definition_id: str) -> DefinitionNode:
        return self.definitions[definition_id]
