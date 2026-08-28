"""Command-line interface for the UGTS spatial distillation launchpad."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import torch

from .benchmark import benchmark_checkpoint
from .csv_adapter import CSVConfig, ingest_csv
from .demo_data import DemoConfig, save_demo_graph
from .geonames import GeoNamesConfig, save_geonames_graph
from .graph import SparseTemporalGraph
from .ontology import Ontology
from .osm_adapter import OSMConfig, ingest_osm_pbf
from .substrate import SpatialQuery, append_verified_novelty, query_from_checkpoint
from .teacher_client import OpenAICompatibleClient, attach_teacher_embeddings, export_relation_tasks, import_relation_labels
from .training import TrainConfig, load_checkpoint, train_model
from .ugts_bridge import export_candidate_abi


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resource(name: str) -> Path:
    """Return a resource path that works in editable and wheel installs."""
    bundled = Path(__file__).resolve().parent / "resources" / name
    if bundled.exists():
        return bundled
    # Source-tree fallback for intentionally minimal editable checkouts.
    source_candidates = {
        "ugts_geo_ontology.json": _root() / "ontology" / "ugts_geo_ontology.json",
        "knowledge_catalog.json": _root() / "vendor" / "ugts_gn_1_1" / "knowledge_catalog.json",
        "ugts_reference.py": _root() / "vendor" / "ugts_gn_1_1" / "ugts_reference.py",
    }
    candidate = source_candidates[name]
    if not candidate.exists():
        raise FileNotFoundError(f"required package resource is missing: {name}")
    return candidate


def _default_ontology() -> Path:
    return _resource("ugts_geo_ontology.json")


def _default_catalog() -> Path:
    return _resource("knowledge_catalog.json")


def _default_reference() -> Path:
    return _resource("ugts_reference.py")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False))


def _resolve_node(graph: SparseTemporalGraph, value: str) -> int:
    try:
        index = int(value, 10)
        if 0 <= index < graph.num_nodes:
            return index
    except ValueError:
        pass
    if value.lower().startswith("0x"):
        wanted = int(value, 16)
        matches = np.flatnonzero(graph.node_ids == wanted)
        if len(matches) == 1:
            return int(matches[0])
        raise ValueError(f"node id not found: {value}")
    matches = [i for i, text in enumerate(graph.texts) if value.casefold() in text.casefold()]
    if not matches:
        raise ValueError(f"no node text contains {value!r}")
    if len(matches) > 1:
        examples = ", ".join(f"{i}:{graph.texts[i][:50]}" for i in matches[:5])
        raise ValueError(f"node selector is ambiguous ({len(matches)} matches): {examples}")
    return matches[0]


def _resolve_relation(ontology: Ontology, value: str) -> int:
    if value.isdigit():
        relation = int(value)
        if relation not in ontology.rel_by_id:
            raise ValueError(f"unknown relation id: {relation}")
        return relation
    if value not in ontology.rel_by_name:
        raise ValueError(f"unknown relation name: {value}")
    return ontology.rel_by_name[value].id


def cmd_demo(args: argparse.Namespace) -> int:
    config = DemoConfig(
        seed=args.seed,
        feature_dim=args.feature_dim,
        teacher_dim=args.teacher_dim,
        sensors_per_area=args.sensors_per_area,
        entities_per_area=args.entities_per_area,
    )
    path = save_demo_graph(args.output, args.ontology, args.catalog, config)
    graph = SparseTemporalGraph.load(path, verify_hashes=True)
    _json_print({"graph": str(path), "nodes": graph.num_nodes, "edges": graph.num_edges, "events": graph.num_events, "examples": graph.num_examples, "metadata": graph.metadata})
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    graph = SparseTemporalGraph.load(args.graph, mmap=True, verify_hashes=args.verify_hashes)
    manifest = json.loads((Path(args.graph) / "manifest.json").read_text(encoding="utf-8"))
    split_counts = {str(int(k)): int(v) for k, v in zip(*np.unique(graph.ex_split, return_counts=True))}
    relation_counts = {str(int(k)): int(v) for k, v in zip(*np.unique(graph.ex_relation, return_counts=True))}
    event_counts = {str(int(k)): int(v) for k, v in zip(*np.unique(graph.event_type, return_counts=True))}
    _json_print({
        "manifest": manifest,
        "split_counts": split_counts,
        "example_relation_counts": relation_counts,
        "event_type_counts": event_counts,
        "array_bytes": int(sum(np.asarray(getattr(graph, name)).nbytes for name in (
            "node_ids", "node_types", "node_coords", "node_features", "lineage_seed", "edge_src", "edge_dst", "edge_type",
            "edge_time", "edge_weight", "edge_flags", "event_entity", "event_time", "event_type", "event_value", "event_flags",
            "ex_src", "ex_dst", "ex_relation", "ex_label", "ex_teacher_prob", "ex_time", "ex_distance_m", "ex_split"
        ))),
    })
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    config = TrainConfig.load(args.config)
    overrides = asdict(config)
    for name in ("device", "epochs", "hidden_dim", "heads", "layers", "memory_dim", "learning_rate", "patience"):
        value = getattr(args, name, None)
        if value is not None:
            overrides[name] = value
    report = train_model(args.graph, args.ontology, args.output, TrainConfig(**overrides))
    _json_print(report)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    graph = SparseTemporalGraph.load(args.graph, mmap=False, verify_hashes=True)
    ontology = Ontology.load(args.ontology)
    source = _resolve_node(graph, args.source)
    relation = _resolve_relation(ontology, args.relation)
    query_time = float(args.query_time if args.query_time is not None else graph.metadata.get("max_time_hours", 0.0))
    semantic_threshold = args.semantic_threshold
    if semantic_threshold is None:
        checkpoint_meta = torch.load(Path(args.checkpoint), map_location="cpu", weights_only=False)
        semantic_threshold = float(
            checkpoint_meta.get("calibration", {}).get("by_relation", {}).get(str(relation), {}).get(
                "threshold", checkpoint_meta.get("calibration", {}).get("overall", {}).get("threshold", 0.5)
            )
        )
    query = SpatialQuery(
        source_index=source,
        relation_id=relation,
        radius_m=args.radius_m,
        cone_axis_enu=tuple(args.axis),
        cone_cos=args.cone_cos,
        epsilon_m=args.epsilon_m,
        semantic_threshold=semantic_threshold,
        query_time=query_time,
        max_results=args.max_results,
        broad_phase=not args.no_broad_phase,
    )
    events = query_from_checkpoint(args.graph, args.ontology, args.checkpoint, query, args.device)
    selected = [x for x in events if x.verified] if args.verified_only else events
    if args.output:
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="\n") as f:
            for event in selected:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    appended = 0
    if args.novelty_log:
        appended = append_verified_novelty(args.novelty_log, events, checkpoint_sha256=_sha256(Path(args.checkpoint)))
    _json_print({
        "query": asdict(query),
        "source_text": graph.texts[source],
        "relation": ontology.rel_by_id[relation].name,
        "candidate_results": len(events),
        "verified": sum(int(x.verified) for x in events),
        "novelty_appended": appended,
        "results": [x.to_dict() for x in selected],
    })
    return 0



def cmd_benchmark(args: argparse.Namespace) -> int:
    report = benchmark_checkpoint(args.graph, args.checkpoint, device=args.device, warmup=args.warmup, repeats=args.repeats, amp=not args.no_amp, output_json=args.output)
    _json_print(report)
    return 0

def cmd_embed(args: argparse.Namespace) -> int:
    client = OpenAICompatibleClient(args.base_url, args.api_key, args.timeout)
    output = attach_teacher_embeddings(args.graph, args.output, client, model=args.model, batch_size=args.batch_size, target_dim=args.target_dim, prefix=args.prefix)
    print(output)
    return 0


def cmd_export_teacher_tasks(args: argparse.Namespace) -> int:
    count = export_relation_tasks(args.graph, args.ontology, args.output, splits=args.splits, max_records=args.max_records)
    _json_print({"output": str(args.output), "records": count})
    return 0


def cmd_import_teacher_labels(args: argparse.Namespace) -> int:
    output = import_relation_labels(args.graph, args.labels, args.output)
    print(output)
    return 0


def cmd_export_ugts(args: argparse.Namespace) -> int:
    graph = SparseTemporalGraph.load(args.graph, mmap=True, verify_hashes=True)
    ontology = Ontology.load(args.ontology)
    source = _resolve_node(graph, args.source)
    relation = _resolve_relation(ontology, args.relation)
    candidates = None
    if args.max_candidates:
        allowed = ontology.rel_by_id[relation].target_types
        candidates = [i for i, t in enumerate(graph.node_types) if int(t) in allowed and i != source][: args.max_candidates]
    manifest = export_candidate_abi(
        args.graph, args.ontology, args.reference, args.output,
        source_index=source, relation_id=relation, candidate_indices=candidates,
        radius_m=args.radius_m, guard_epsilon_m=args.epsilon_m,
        cone_cos=args.cone_cos, query_time=args.query_time, confidence_floor=args.confidence_floor,
    )
    _json_print(manifest)
    return 0


def cmd_ingest_geonames(args: argparse.Namespace) -> int:
    config = GeoNamesConfig(
        admin1_code=None if args.admin1.lower() == "all" else args.admin1,
        max_records=args.max_records,
        min_population=args.min_population,
        feature_dim=args.feature_dim,
        teacher_dim=args.teacher_dim,
    )
    path = save_geonames_graph(args.input, args.ontology, args.output, config)
    print(path)
    return 0


def cmd_ingest_csv(args: argparse.Namespace) -> int:
    config = CSVConfig(feature_dim=args.feature_dim, teacher_dim=args.teacher_dim)
    print(ingest_csv(args.input, args.ontology, args.output, config))
    return 0



def cmd_ingest_osm(args: argparse.Namespace) -> int:
    config = OSMConfig(max_features=args.max_features, feature_dim=args.feature_dim, teacher_dim=args.teacher_dim)
    print(ingest_osm_pbf(args.input, args.ontology, args.output, config))
    return 0

def cmd_verify(args: argparse.Namespace) -> int:
    graph = SparseTemporalGraph.load(args.graph, mmap=False, verify_hashes=True)
    result: dict[str, Any] = {"graph": "ok", "nodes": graph.num_nodes, "edges": graph.num_edges, "events": graph.num_events, "examples": graph.num_examples}
    if args.checkpoint:
        model, payload = load_checkpoint(args.checkpoint, "cpu")
        result.update({"checkpoint": "ok", "checkpoint_format": payload.get("format"), "parameters": sum(p.numel() for p in model.parameters()), "checkpoint_sha256": _sha256(Path(args.checkpoint))})
    _json_print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ugts-spatial", description="Sparse temporal geospatial GNN distillation and UGTS event gate")
    parser.add_argument("--version", action="version", version="ugts-spatial 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("demo", help="generate the deterministic no-download Flevoland-like graph")
    p.add_argument("output"); p.add_argument("--ontology", default=str(_default_ontology())); p.add_argument("--catalog", default=str(_default_catalog()))
    p.add_argument("--seed", type=int, default=200678942); p.add_argument("--feature-dim", type=int, default=32); p.add_argument("--teacher-dim", type=int, default=64)
    p.add_argument("--sensors-per-area", type=int, default=10); p.add_argument("--entities-per-area", type=int, default=16); p.set_defaults(func=cmd_demo)

    p = sub.add_parser("inspect", help="inspect a sparse graph directory")
    p.add_argument("graph"); p.add_argument("--verify-hashes", action="store_true"); p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("train", help="train the HGT/TGN-style student")
    p.add_argument("graph"); p.add_argument("output"); p.add_argument("--ontology", default=str(_default_ontology())); p.add_argument("--config")
    p.add_argument("--device"); p.add_argument("--epochs", type=int); p.add_argument("--hidden-dim", type=int); p.add_argument("--heads", type=int); p.add_argument("--layers", type=int); p.add_argument("--memory-dim", type=int); p.add_argument("--learning-rate", type=float); p.add_argument("--patience", type=int)
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("query", help="run support→compatibility→guard→event over model candidates")
    p.add_argument("graph"); p.add_argument("checkpoint"); p.add_argument("--ontology", default=str(_default_ontology()))
    p.add_argument("--source", required=True, help="node index, 0x stable id, or unique text substring")
    p.add_argument("--relation", default="near"); p.add_argument("--radius-m", type=float, default=10000.0); p.add_argument("--axis", nargs=3, type=float, default=(0.0, 1.0, 0.0)); p.add_argument("--cone-cos", type=float, default=-1.0); p.add_argument("--epsilon-m", type=float, default=1.0); p.add_argument("--semantic-threshold", type=float, help="override validation-calibrated relation threshold"); p.add_argument("--query-time", type=float); p.add_argument("--max-results", type=int, default=32); p.add_argument("--device", default="auto"); p.add_argument("--no-broad-phase", action="store_true"); p.add_argument("--verified-only", action="store_true"); p.add_argument("--output"); p.add_argument("--novelty-log"); p.set_defaults(func=cmd_query)

    p = sub.add_parser("benchmark", help="benchmark full sparse student inference on CPU or CUDA")
    p.add_argument("graph"); p.add_argument("checkpoint"); p.add_argument("--device", default="auto"); p.add_argument("--warmup", type=int, default=5); p.add_argument("--repeats", type=int, default=30); p.add_argument("--no-amp", action="store_true"); p.add_argument("--output"); p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("embed", help="attach embeddings from an OpenAI-compatible local/hosted endpoint")
    p.add_argument("graph"); p.add_argument("output"); p.add_argument("--base-url", default="http://127.0.0.1:8080/v1"); p.add_argument("--api-key", default="local"); p.add_argument("--model", default="local-embedding"); p.add_argument("--batch-size", type=int, default=32); p.add_argument("--target-dim", type=int, default=256); p.add_argument("--timeout", type=float, default=120.0); p.add_argument("--prefix", default="Represent this geospatial or ontological entity for relation reasoning: "); p.set_defaults(func=cmd_embed)

    p = sub.add_parser("export-teacher-tasks", help="export structured relation-labeling JSONL")
    p.add_argument("graph"); p.add_argument("output"); p.add_argument("--ontology", default=str(_default_ontology())); p.add_argument("--splits", nargs="+", type=int, default=[0]); p.add_argument("--max-records", type=int, default=0); p.set_defaults(func=cmd_export_teacher_tasks)

    p = sub.add_parser("import-teacher-labels", help="import example probabilities from JSONL")
    p.add_argument("graph"); p.add_argument("labels"); p.add_argument("output"); p.set_defaults(func=cmd_import_teacher_labels)

    p = sub.add_parser("export-ugts", help="export graph candidates to the uploaded G64/G32/E32/E16 ABI")
    p.add_argument("graph"); p.add_argument("output"); p.add_argument("--source", required=True); p.add_argument("--relation", default="near"); p.add_argument("--ontology", default=str(_default_ontology())); p.add_argument("--reference", default=str(_default_reference())); p.add_argument("--max-candidates", type=int, default=1024); p.add_argument("--radius-m", type=float, default=10000.0); p.add_argument("--epsilon-m", type=float, default=10.0); p.add_argument("--cone-cos", type=float, default=-1.0); p.add_argument("--query-time", type=float, default=0.0); p.add_argument("--confidence-floor", type=float, default=0.0); p.set_defaults(func=cmd_export_ugts)

    p = sub.add_parser("ingest-geonames", help="convert a manually downloaded GeoNames country ZIP/TXT")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--ontology", default=str(_default_ontology())); p.add_argument("--admin1", default="16"); p.add_argument("--max-records", type=int, default=0); p.add_argument("--min-population", type=int, default=0); p.add_argument("--feature-dim", type=int, default=32); p.add_argument("--teacher-dim", type=int, default=64); p.set_defaults(func=cmd_ingest_geonames)

    p = sub.add_parser("ingest-csv", help="convert an id,lat,lon,text,type CSV")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--ontology", default=str(_default_ontology())); p.add_argument("--feature-dim", type=int, default=32); p.add_argument("--teacher-dim", type=int, default=64); p.set_defaults(func=cmd_ingest_csv)

    p = sub.add_parser("ingest-osm", help="convert a Geofabrik OSM PBF using optional pyosmium")
    p.add_argument("input"); p.add_argument("output"); p.add_argument("--ontology", default=str(_default_ontology())); p.add_argument("--max-features", type=int, default=100000); p.add_argument("--feature-dim", type=int, default=32); p.add_argument("--teacher-dim", type=int, default=64); p.set_defaults(func=cmd_ingest_osm)

    p = sub.add_parser("verify", help="verify graph hashes and optionally a checkpoint")
    p.add_argument("graph"); p.add_argument("--checkpoint"); p.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, RuntimeError, OSError, IndexError) as exc:
        parser.error(str(exc))
        return 2
