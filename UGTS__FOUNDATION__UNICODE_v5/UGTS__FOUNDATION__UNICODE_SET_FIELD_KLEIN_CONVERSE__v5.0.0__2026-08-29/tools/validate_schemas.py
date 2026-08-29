#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec"
PAIRS = [
    ("ugts5_operator_atlas.schema.json", "operator_atlas.json"),
    ("ugts5_hot_codebook.schema.json", "hot_codebook_set_core_16.json"),
    ("ugts5_release_record.schema.json", "release_record.json"),
]

results = []
for schema_name, instance_name in PAIRS:
    schema = json.loads((SPEC / schema_name).read_text(encoding="utf-8"))
    instance = json.loads((SPEC / instance_name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(e.path))
    results.append({
        "schema": schema_name,
        "instance": instance_name,
        "errors": [e.message for e in errors],
        "status": "PASS" if not errors else "FAIL",
    })
print(json.dumps(results, indent=2, ensure_ascii=False))
raise SystemExit(0 if all(r["status"] == "PASS" for r in results) else 1)
