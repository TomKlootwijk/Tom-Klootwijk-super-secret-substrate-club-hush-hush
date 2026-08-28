#!/usr/bin/env python3
"""Run the public-only UGTS-KC 3.6.3 SARA reference certificate."""

from __future__ import annotations

import json
from pathlib import Path

from ugts36.sara_runtime import SARARuntime

ROOT = Path(__file__).resolve().parents[1]
result = SARARuntime(ROOT / "data" / "bip39_english.txt").run_reference()
print(json.dumps(result, indent=2))
