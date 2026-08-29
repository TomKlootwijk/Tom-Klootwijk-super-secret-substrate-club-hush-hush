#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts5.atlas import HotCodebook, OperatorAtlas
from ugts5.set_fields import FiniteSetField

atlas = OperatorAtlas.load(ROOT / "spec" / "operator_atlas.json")
codebook = HotCodebook.load(ROOT / "spec" / "hot_codebook_set_core_16.json", atlas)

universe = ("a", "b", "c", "d")
A = FiniteSetField.from_members(universe, ("a", "c"), label="A")
B = FiniteSetField.from_members(universe, ("a", "b", "c"), label="B")

rows = []
for literal, left, right in [
    ("∈", "a", A),
    ("∋", A, "a"),
    ("∉", "d", A),
    ("⊂", A, B),
    ("⊃", B, A),
    ("⊆", A, B),
    ("⊇", B, A),
]:
    cell = atlas.by_literal(literal)
    rows.append({
        "slot": codebook.slot_for_literal(literal),
        "literal": literal,
        "operator_id": cell.id,
        "kappa": cell.kappa,
        "result": cell.evaluate(left, right),
        "converse_literal": atlas.by_id(cell.converse_id).literal,
    })

print(json.dumps({
    "release": atlas.record["canonical_release"],
    "atlas_hash": atlas.atlas_hash,
    "rows": rows,
}, indent=2, ensure_ascii=False))
