#!/usr/bin/env python3
"""Run the literal UGTS-KC 3.6.2 SCLP reference pipeline."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts36 import SCLPRuntime, Substrate  # noqa: E402

substrate = Substrate.load(ROOT / "examples/ugts_kc_3_6_2_sclp_example.json")
trace = SCLPRuntime(substrate).execute(
    "sclp362:pipeline:reference-certificate-v1",
    "sclp362:instance:reference-query-v1",
)
print(json.dumps([{"step_id": x.step_id, "kind": x.kind, "output": x.output} for x in trace], indent=2))
