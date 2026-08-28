from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping
import zipfile

from .graph import GraphPackage
from .novelty import NoveltyLog
from .utils import canonical_json, safe_torch_load, sha256_bytes, sha256_file, write_json


@dataclass(frozen=True)
class DeploymentSummary:
    path: str
    graph_schema_hash: str
    files: int
    bytes: int
    terminal_novelty_hash: int


def _default_ontology() -> dict[str, Any]:
    from .schema import (
        NODE_TYPE_NAMES,
        NODE_TYPE_URIS,
        RELATION_SPECS,
        RELATION_TYPE_NAMES,
        RELATION_TYPE_URIS,
    )

    return {
        "format": "UGTS-GEO-ONTOLOGY-1",
        "ontology_version": "ugts-geo-ontology-v1",
        "node_types": [
            {
                "id": value,
                "name": NODE_TYPE_NAMES[value],
                "uri": NODE_TYPE_URIS[value],
            }
            for value in sorted(NODE_TYPE_NAMES)
        ],
        "relations": [
            {
                "id": value,
                "name": RELATION_TYPE_NAMES[value],
                "uri": RELATION_TYPE_URIS[value],
                "source_types": [int(item) for item in RELATION_SPECS[value].source_types],
                "target_types": [int(item) for item in RELATION_SPECS[value].target_types],
                "symmetric": RELATION_SPECS[value].symmetric,
                "requires_geometry": RELATION_SPECS[value].requires_geometry,
                "requires_guard": RELATION_SPECS[value].requires_guard,
            }
            for value in sorted(RELATION_TYPE_NAMES)
        ],
        "authority": {
            "gnn": "semantic proposal and ranking",
            "spatial_index": "broad-phase support only",
            "ugts_guard": "deterministic event authority",
            "novelty_log": "durable exogenous changes and verified events",
        },
    }


def build_deployment(
    output_path: str | Path,
    graph_path: str | Path,
    *,
    model_path: str | Path | None = None,
    novelty_path: str | Path | None = None,
    ontology_path: str | Path | None = None,
    attribution: Mapping[str, Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    extra_files: Mapping[str, str | Path] | None = None,
) -> DeploymentSummary:
    output_path = Path(output_path)
    graph_path = Path(graph_path)
    graph = GraphPackage.load(graph_path)
    paths: dict[str, Path] = {"graph.ugkg": graph_path}
    if model_path is not None:
        model = Path(model_path)
        checkpoint = safe_torch_load(model, map_location="cpu")
        if checkpoint.get("schema_hash") != graph.schema_hash:
            raise ValueError("model/graph schema hash mismatch")
        paths["student_model.pt"] = model
    terminal_hash = 0
    if novelty_path is not None:
        novelty = Path(novelty_path)
        novelty_summary = NoveltyLog(novelty).validate()
        terminal_hash = int(novelty_summary["terminal_hash"])
        paths["novelty.ugnl"] = novelty
    if ontology_path is not None:
        paths["ontology.json"] = Path(ontology_path)
        ontology_bytes = paths["ontology.json"].read_bytes()
    else:
        ontology_bytes = canonical_json(_default_ontology()) + b"\n"
    if extra_files:
        for arcname, local_path in extra_files.items():
            clean = str(arcname).replace("\\", "/").lstrip("/")
            if ".." in Path(clean).parts or not clean:
                raise ValueError(f"unsafe deployment archive path: {arcname}")
            paths[clean] = Path(local_path)

    runtime = {
        "format": "UGTS-SPATIAL-RUNTIME-1",
        "query_order": [
            "local_support",
            "compatibility",
            "guard_crossing",
            "semantic_student_score",
            "verified_event",
            "route_transition",
            "lineage_novelty_append",
        ],
        "model_role": "offline-distilled HGT/TGN student; no edge LLM required",
        "precision_rule": "coordinate/axis/radius/guard error must remain below event margin",
        "recommended_device": "cuda",
        **dict(runtime_config or {}),
    }
    attribution_value = {
        "substrate": "UGTS-GN 1.1",
        "substrate_author": "Tom Klootwijk",
        "author_identifier": "NL200678942",
        "author_date": "1990-07-10",
        "provenance_status": "user-supplied authorship/provenance; not independently adjudicated",
        **dict(attribution or {}),
    }

    generated: dict[str, bytes] = {
        "runtime.json": json.dumps(runtime, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "attribution.json": json.dumps(
            attribution_value, indent=2, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        + b"\n",
    }
    if ontology_path is None:
        generated["ontology.json"] = ontology_bytes
    file_rows: dict[str, dict[str, Any]] = {}
    for arcname, path in paths.items():
        file_rows[arcname] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    for arcname, payload in generated.items():
        file_rows[arcname] = {"sha256": sha256_bytes(payload), "bytes": len(payload)}

    manifest = {
        "format": "UGTS-SPATIAL-DEPLOYMENT-1",
        "graph_schema_hash": graph.schema_hash,
        "graph_summary": graph.summary(),
        "terminal_novelty_hash": terminal_hash,
        "files": file_rows,
        "portable_contract": [
            "graph schema and ontology",
            "student checkpoint",
            "runtime query order",
            "novelty hash chain",
        ],
        "performance_boundary": (
            "Throughput and energy must be measured on the named physical GPU; "
            "this bundle does not encode a hardware-speed claim."
        ),
    }
    manifest_bytes = json.dumps(
        manifest, indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8") + b"\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        for arcname, path in paths.items():
            zf.write(path, arcname)
        for arcname, payload in generated.items():
            zf.writestr(arcname, payload)
        zf.writestr("manifest.json", manifest_bytes)
    return DeploymentSummary(
        path=str(output_path),
        graph_schema_hash=graph.schema_hash,
        files=len(file_rows),
        bytes=output_path.stat().st_size,
        terminal_novelty_hash=terminal_hash,
    )


def validate_deployment(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        if "manifest.json" not in names:
            raise ValueError("deployment has no manifest.json")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != "UGTS-SPATIAL-DEPLOYMENT-1":
            raise ValueError("unsupported deployment format")
        for arcname, expected in manifest.get("files", {}).items():
            if arcname not in names:
                raise ValueError(f"deployment is missing {arcname}")
            payload = zf.read(arcname)
            if len(payload) != int(expected["bytes"]):
                raise ValueError(f"size mismatch for {arcname}")
            if sha256_bytes(payload) != expected["sha256"]:
                raise ValueError(f"SHA-256 mismatch for {arcname}")
        with tempfile.TemporaryDirectory(prefix="ugts-deploy-") as temp_dir:
            temp = Path(temp_dir)
            graph_local = temp / "graph.ugkg"
            graph_local.write_bytes(zf.read("graph.ugkg"))
            graph = GraphPackage.load(graph_local)
            if graph.schema_hash != manifest.get("graph_schema_hash"):
                raise ValueError("deployment graph schema hash mismatch")
            model_valid = None
            if "student_model.pt" in names:
                model_local = temp / "student_model.pt"
                model_local.write_bytes(zf.read("student_model.pt"))
                checkpoint = safe_torch_load(model_local, map_location="cpu")
                model_valid = checkpoint.get("schema_hash") == graph.schema_hash
                if not model_valid:
                    raise ValueError("deployment model is incompatible with graph")
            novelty_summary = None
            if "novelty.ugnl" in names:
                novelty_local = temp / "novelty.ugnl"
                novelty_local.write_bytes(zf.read("novelty.ugnl"))
                novelty_summary = NoveltyLog(novelty_local).validate()
                if int(novelty_summary["terminal_hash"]) != int(
                    manifest.get("terminal_novelty_hash", 0)
                ):
                    raise ValueError("deployment novelty terminal hash mismatch")
    return {
        "valid": True,
        "path": str(path),
        "bytes": path.stat().st_size,
        "graph_schema_hash": manifest["graph_schema_hash"],
        "model_valid": model_valid,
        "novelty": novelty_summary,
        "file_count": len(manifest.get("files", {})),
    }
