"""Bridge sparse graph candidates to the uploaded UGTS G64/E32 and G32/E16 ABI."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np

from .graph import SparseTemporalGraph
from .ontology import Ontology
from .spatial import LocalFrame


def _load_reference(path: str | Path):
    path = Path(path)
    spec = importlib.util.spec_from_file_location("ugts_vendored_reference", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load UGTS reference oracle: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses consult sys.modules while processing annotations.
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export_candidate_abi(
    graph_dir: str | Path,
    ontology_path: str | Path,
    reference_path: str | Path,
    output_dir: str | Path,
    *,
    source_index: int,
    relation_id: int,
    candidate_indices: list[int] | None = None,
    radius_m: float = 10_000.0,
    guard_epsilon_m: float = 10.0,
    cone_cos: float = -1.0,
    query_time: float = 0.0,
    confidence_floor: float = 0.0,
) -> dict[str, Any]:
    graph = SparseTemporalGraph.load(graph_dir, mmap=False, verify_hashes=True)
    ontology = Ontology.load(ontology_path)
    ref = _load_reference(reference_path)
    relation = ontology.rel_by_id[int(relation_id)]
    if not 0 <= source_index < graph.num_nodes:
        raise IndexError("source_index out of range")
    source_type = int(graph.node_types[source_index])
    if source_type not in relation.source_types:
        raise ValueError("source node type is incompatible with relation")
    if candidate_indices is None:
        candidate_indices = [i for i, t in enumerate(graph.node_types) if int(t) in relation.target_types and i != source_index]
    root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
    source_coord = graph.node_coords[source_index]
    frame = LocalFrame(*map(float, source_coord))
    target_sheet = ontology.node_by_id[relation.target_types[0]].sheet
    query = ref.Query(target_sheet=target_sheet, target_orientation=0, mode_bit=relation.mode_bit, commit=True)
    states = []
    for target in candidate_indices:
        p = frame.to_enu(*map(float, graph.node_coords[target]))
        states.append(ref.State(
            position=tuple(float(x) for x in p),
            time=float(query_time),
            axis=(0.0, 1.0, 0.0),
            radius=float(radius_m),
            cone_cos=float(cone_cos),
            phase=0.0,
            guard_epsilon=float(guard_epsilon_m),
            confidence_floor=float(confidence_floor),
            sheet=int(target_sheet),
            orientation=0,
            compatibility_mask=1 << relation.mode_bit,
            lineage_seed=int(graph.lineage_seed[target]),
        ))
    events, counters = ref.evaluate_many(states, query)
    files = {
        "states_g64.bin": b"".join(ref.pack_g64(s) for s in states),
        "states_g32.bin": b"".join(ref.pack_g32(s) for s in states),
        "events_e32.bin": b"".join(ref.pack_e32(e) for e in events),
        "events_e16.bin": b"".join(ref.pack_e16(e) for e in events),
        "candidate_indices.u64le": np.asarray(candidate_indices, dtype="<u8").tobytes(),
    }
    manifest_files: dict[str, Any] = {}
    for name, payload in files.items():
        path = root / name
        path.write_bytes(payload)
        manifest_files[name] = {"bytes": len(payload), "sha256": _sha256(path)}
    manifest = {
        "format": "UGTS-SPATIAL-ABI-EXPORT-1",
        "source_index": source_index,
        "source_node_id": f"0x{int(graph.node_ids[source_index]):016x}",
        "relation_id": relation.id,
        "relation": relation.name,
        "query": {"target_sheet": target_sheet, "target_orientation": 0, "mode_bit": relation.mode_bit, "commit": True},
        "candidate_count": len(states),
        "counters": counters,
        "record_sizes": {"G64": ref.G64_BYTES, "G32": ref.G32_BYTES, "E32": ref.E32_BYTES, "E16": ref.E16_BYTES},
        "files": manifest_files,
        "precision_note": "G32/E16 is a packed transport profile; event-order and guard-margin equivalence must be validated for the workload.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
