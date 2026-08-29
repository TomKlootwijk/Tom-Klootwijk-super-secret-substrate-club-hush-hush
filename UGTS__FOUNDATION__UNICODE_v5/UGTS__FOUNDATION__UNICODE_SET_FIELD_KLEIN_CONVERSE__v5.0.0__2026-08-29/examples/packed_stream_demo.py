#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts5.canonical import load_json
from ugts5.packing import PackedNode32, PackedNodeFields
from ugts5.stream import read_stream, write_stream

atlas = load_json(ROOT / "spec" / "operator_atlas.json")
codebook = load_json(ROOT / "spec" / "hot_codebook_set_core_16.json")
header = {
    "$schema": "../spec/ugts5_stream_header.schema.json",
    "schema_id": "ugts.packed-set-field-node-stream@5.0.0",
    "codebook_id": codebook["codebook_id"],
    "codebook_hash": codebook["codebook_hash"],
    "atlas_hash": atlas["atlas_hash"],
    "chart": {
        "rho_origin": -5.0,
        "theta_origin_code": 0,
        "theta_bins": 256,
        "wrap_profile": "reflective-klein-converse-v1",
    },
    "quantization": {
        "delta_rho_scale": 0.03125,
        "delta_rho_bias": 0,
        "theta_bin_degrees": 1.40625,
        "rounding": "nearest",
    },
    "error_contract": {
        "max_theta_error_degrees": 0.703125,
        "event_margin_rule": "numeric_error <= event_margin",
    },
    "grammar": {"path_bits": 8, "meaning": "bounded branch fragment"},
}

fields = [
    PackedNodeFields(0, 0, -5, 16, 0b00110101, 0, True),
    PackedNodeFields(0, 1, 3, 240, 0b00110101, 1, True),
    PackedNodeFields(3, 0, 0, 64, 0b11110000, 2, True),
    PackedNodeFields(3, 1, 0, 192, 0b11110000, 2, False),
]
words = [PackedNode32.pack(f) for f in fields]
path = ROOT / "examples" / "sample_nodes.ug5n"
write_stream(path, header, words)
loaded_header, loaded_words = read_stream(path)

summary = {
    "path": str(path.relative_to(ROOT)),
    "node_count": len(loaded_words),
    "words": [f"0x{w:08x}" for w in loaded_words],
    "decoded": [PackedNode32.unpack(w).__dict__ for w in loaded_words],
    "header": loaded_header,
}
(ROOT / "examples" / "sample_nodes_decoded.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
