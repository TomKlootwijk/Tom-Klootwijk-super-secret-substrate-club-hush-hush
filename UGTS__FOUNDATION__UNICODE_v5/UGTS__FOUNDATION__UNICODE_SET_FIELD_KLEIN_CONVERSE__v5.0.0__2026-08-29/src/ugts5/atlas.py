"""Unicode operator atlas and hot-codebook loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import content_hash, load_json, sha256_hex
from .set_fields import evaluate_relation


class AtlasError(ValueError):
    pass


@dataclass(frozen=True)
class OperatorCell:
    record: dict[str, Any]

    @property
    def literal(self) -> str:
        return self.record["unicode"]["literal"]

    @property
    def id(self) -> str:
        return self.record["id"]

    @property
    def converse_id(self) -> str | None:
        return self.record.get("converse_id")

    @property
    def kappa(self) -> int | None:
        return self.record.get("kappa")

    def evaluate(self, left: object, right: object) -> bool:
        kernel = self.record.get("semantic", {}).get("kernel")
        if kernel in {
            "membership", "nonmembership", "proper_subset", "subset_or_equal",
            "not_proper_subset", "not_subset_or_equal", "proper_subset_variant",
        }:
            return evaluate_relation(self.literal, left, right)
        raise AtlasError(f"operator {self.literal!r} has no boolean relation evaluator in the reference subset")


class OperatorAtlas:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        self._by_literal: dict[str, OperatorCell] = {}
        self._by_id: dict[str, OperatorCell] = {}
        for raw in record.get("operators", []):
            cell = OperatorCell(raw)
            if cell.literal in self._by_literal:
                raise AtlasError(f"duplicate literal {cell.literal!r}")
            if cell.id in self._by_id:
                raise AtlasError(f"duplicate id {cell.id!r}")
            self._by_literal[cell.literal] = cell
            self._by_id[cell.id] = cell

    @classmethod
    def load(cls, path: str | Path, *, verify_hashes: bool = True) -> "OperatorAtlas":
        record = load_json(path)
        atlas = cls(record)
        if verify_hashes:
            atlas.verify_hashes()
        return atlas

    def verify_hashes(self) -> None:
        for raw in self.record.get("operators", []):
            expected = raw.get("content_hash")
            actual = content_hash(raw)
            if expected != actual:
                raise AtlasError(f"content hash mismatch for {raw.get('id')}: {expected} != {actual}")
        expected_atlas = self.record.get("atlas_hash")
        actual_atlas = content_hash(self.record, excluded=("atlas_hash",))
        if expected_atlas != actual_atlas:
            raise AtlasError(f"atlas hash mismatch: {expected_atlas} != {actual_atlas}")

    def by_literal(self, literal: str) -> OperatorCell:
        try:
            return self._by_literal[literal]
        except KeyError as exc:
            raise AtlasError(f"unknown Unicode literal {literal!r}") from exc

    def by_id(self, operator_id: str) -> OperatorCell:
        try:
            return self._by_id[operator_id]
        except KeyError as exc:
            raise AtlasError(f"unknown operator id {operator_id!r}") from exc

    @property
    def atlas_hash(self) -> str:
        return self.record["atlas_hash"]

    @property
    def literals(self) -> tuple[str, ...]:
        return tuple(self._by_literal)


class HotCodebook:
    def __init__(self, record: dict[str, Any], atlas: OperatorAtlas) -> None:
        self.record = record
        self.atlas = atlas
        if record.get("atlas_hash") != atlas.atlas_hash:
            raise AtlasError("codebook atlas hash does not match loaded atlas")
        entries = record.get("entries")
        if not isinstance(entries, list) or len(entries) != 16:
            raise AtlasError("hot codebook must contain exactly 16 slots")
        self.entries = entries
        expected = record.get("codebook_hash")
        actual = content_hash(record, excluded=("codebook_hash",))
        if expected != actual:
            raise AtlasError("hot codebook hash mismatch")

    @classmethod
    def load(cls, path: str | Path, atlas: OperatorAtlas) -> "HotCodebook":
        return cls(load_json(path), atlas)

    def resolve_slot(self, slot: int) -> OperatorCell:
        if not 0 <= slot < 16:
            raise AtlasError("slot must be in [0,15]")
        entry = self.entries[slot]
        if entry is None:
            raise AtlasError(f"slot {slot} is reserved/unassigned")
        return self.atlas.by_id(entry["operator_id"])

    def slot_for_literal(self, literal: str) -> int:
        for index, entry in enumerate(self.entries):
            if entry and entry.get("literal") == literal:
                return index
        raise AtlasError(f"literal {literal!r} is not in this hot codebook")
