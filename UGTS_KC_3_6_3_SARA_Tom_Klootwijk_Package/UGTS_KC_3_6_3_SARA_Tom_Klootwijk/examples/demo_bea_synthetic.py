#!/usr/bin/env python3
"""Run the literal UGTS-KC 3.6.1 BEA course-corrected example."""

from __future__ import annotations

import json
from pathlib import Path

from ugts36.bea_runtime import SyntheticBEARuntime
from ugts36.model import Substrate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "ugts_kc_3_6_1_bea_synthetic_example.json"

substrate = Substrate.load(EXAMPLE)
trace = SyntheticBEARuntime(substrate).execute_pair(
    "bea361:pipeline:course-corrected-certificate-v2",
    "repr:negentien",
    "repr:no-neg-moat",
)
print(json.dumps([{"step_id": item.step_id, "kind": item.kind, "output": item.output} for item in trace], indent=2))
