#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts5.set_fields import FiniteSetField, field_truth_table

universe = tuple(range(8))
A = FiniteSetField.from_members(universe, {1, 2, 3, 6}, label="A")
B = FiniteSetField.from_members(universe, {3, 4, 5, 6}, label="B")

records = []
for x in universe:
    records.append({
        "x": x,
        "phi_A": A.value(x),
        "phi_B": B.value(x),
        **field_truth_table(A.value(x), B.value(x)),
    })

print(json.dumps({
    "A": sorted(A.members),
    "B": sorted(B.members),
    "union": sorted(A.union(B).members),
    "intersection": sorted(A.intersection(B).members),
    "A_minus_B": sorted(A.difference(B).members),
    "symmetric_difference": sorted(A.symmetric_difference(B).members),
    "records": records,
    "capability_note": "The finite field is exact as a signed membership field; min/max composition preserves sign, not a claim of Euclidean distance.",
}, indent=2))
