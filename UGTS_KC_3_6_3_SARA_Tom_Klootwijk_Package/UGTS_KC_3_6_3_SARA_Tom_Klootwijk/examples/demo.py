#!/usr/bin/env python3
"""Run the literal referential number-to-geometry example."""

from __future__ import annotations

import json
from pathlib import Path

from ugts36 import Runtime, Substrate


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    substrate = Substrate.load(ROOT / "examples" / "ugts_kc_3_6_example.json")
    runtime = Runtime(substrate)
    result = {
        "schema_version": substrate.schema_version,
        "substrate_id": substrate.substrate_id,
        "definition_order": list(substrate.definition_order()),
        "traces": {},
    }
    for instance_id in ("number:19", "number:23"):
        trace = runtime.execute("pipeline:number-to-geometry", instance_id)
        result["traces"][instance_id] = [
            {"step_id": item.step_id, "kind": item.kind, "output": item.output}
            for item in trace
        ]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
