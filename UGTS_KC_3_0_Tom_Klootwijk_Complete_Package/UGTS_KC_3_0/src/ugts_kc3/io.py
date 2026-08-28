"""Portable JSON I/O and capability-manifest helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from . import __version__
from .uncertainty import canonical_json_hash


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def capability_manifest(implemented_mechanisms: Sequence[str] | None = None,
                        precision: str = "float64-reference",
                        certification: str = "bounded-reference",
                        fallbacks: Mapping[str, str] | None = None) -> Dict[str, Any]:
    mechanisms = sorted(set(implemented_mechanisms or []))
    manifest: Dict[str, Any] = {
        "schema": "ugts-kc-capabilities/3.0",
        "package_version": __version__,
        "precision": precision,
        "certification": certification,
        "implemented_mechanisms": mechanisms,
        "fallbacks": dict(sorted((fallbacks or {}).items())),
    }
    manifest["manifest_hash"] = canonical_json_hash(manifest)
    return manifest


def validate_world_minimal(world: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if world.get("schema_version") != "3.0.0":
        errors.append("schema_version must equal 3.0.0")
    if not isinstance(world.get("metadata"), Mapping):
        errors.append("metadata object is required")
    states = world.get("states")
    if not isinstance(states, list) or not states:
        errors.append("nonempty states array is required")
    else:
        for i, state in enumerate(states):
            if not isinstance(state, Mapping):
                errors.append(f"states[{i}] must be an object")
                continue
            for key in ("id", "time", "position", "velocity", "phase", "sheet", "orientation", "lineage"):
                if key not in state:
                    errors.append(f"states[{i}].{key} is required")
            dims = [state.get(k) for k in ("position", "velocity", "acceleration", "jerk", "snap") if k in state]
            lengths = {len(v) for v in dims if isinstance(v, list)}
            if len(lengths) > 1:
                errors.append(f"states[{i}] derivative vectors must share a dimension")
    if "numeric_policy" not in world:
        errors.append("numeric_policy is required")
    return errors
