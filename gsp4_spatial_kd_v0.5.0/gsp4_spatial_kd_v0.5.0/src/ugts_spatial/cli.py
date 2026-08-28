from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .benchmark import BenchmarkConfig, benchmark_student
from .builders import build_demo_graph, build_geonames_graph
from .environment import gpu_environment_report
from .ingest_osm import ingest_osm
from .deployment import build_deployment, validate_deployment
from .distill import (
    embed_graph,
    generate_relation_candidates,
    merge_teacher_labels,
    read_relation_candidates,
    write_relation_candidates,
)
from .edge_teacher import (
    TeacherEdgeSet,
    export_ultra_triples,
    import_scored_triples,
    teacher_edges_from_labels,
)
from .embeddings import make_embedder
from .graph import GraphPackage
from .novelty import NoveltyLog, NoveltyRecord
from .query import QueryConfig, execute_query, relation_from_value
from .schema import NODE_TYPE_NAMES, NodeType, NoveltyOp, RelationType
from .synthetic import write_flevoland_pilot
from .teacher import (
    OpenAICompatibleChatTeacher,
    read_teacher_labels,
    write_teacher_labels,
)
from .training import TrainConfig, load_model_for_graph, train_model
from .ugts_bridge import export_ugts_candidates
from .utils import human_bytes, sha256_file, stable_u64, write_json

VERSION = "0.5.0"


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str))


def _node_id(graph: GraphPackage, value: str) -> int:
    lookup = graph.key_index()
    if value in lookup:
        return int(graph.node_id[lookup[value]])
    try:
        node_id = int(value, 0)
    except ValueError as exc:
        raise ValueError(f"unknown node key or integer ID: {value!r}") from exc
    graph.index_for(node_id)
    return node_id


def _node_types(values: list[str] | None) -> list[int] | None:
    if not values:
        return None
    by_name = {name: value for value, name in NODE_TYPE_NAMES.items()}
    result: list[int] = []
    for item in values:
        text = item.strip().lower()
        if text in by_name:
            result.append(int(by_name[text]))
        else:
            result.append(int(text, 0))
    return result


def _seed_novelty_from_graph(graph: GraphPackage, path: str | Path) -> NoveltyLog:
    log = NoveltyLog(path, seed=stable_u64(graph.schema_hash, namespace="ugts-novelty-seed"))
    log.create(overwrite=True)
    event_indices = [
        index
        for index, node_type in enumerate(graph.node_type.tolist())
        if int(node_type) == int(NodeType.EVENT)
    ]
    for event_index in event_indices:
        affected_edges = [
            position
            for position in range(graph.num_edges)
            if int(graph.edge_index[0, position]) == event_index
            and int(graph.edge_type[position])
            in {int(RelationType.AFFECTS), int(RelationType.CROSSED_GUARD)}
        ]
        target_index = (
            int(graph.edge_index[1, affected_edges[0]]) if affected_edges else event_index
        )
        lineage_hash = stable_u64(
            f"{graph.schema_hash}:{int(graph.lineage_seed[event_index])}:"
            f"{int(graph.lineage_seed[target_index])}:{float(graph.node_time[event_index]):.6f}",
            namespace="ugts-demo-lineage",
        )
        log.append(
            NoveltyRecord(
                sequence=log.next_sequence(),
                timestamp=float(graph.node_time[event_index]),
                op=int(NoveltyOp.VERIFIED_EVENT),
                relation=int(RelationType.CROSSED_GUARD),
                flags=int(lineage_hash & 0x3),
                source=int(graph.node_id[event_index]),
                target=int(graph.node_id[target_index]),
                value=0.0,
                confidence=0.97,
                lineage_hash=lineage_hash,
            )
        )
    return log


def _query_from_args(graph: GraphPackage, args: argparse.Namespace) -> QueryConfig:
    return QueryConfig(
        source_node_id=_node_id(graph, args.source),
        relation=relation_from_value(args.relation),
        radius_m=args.radius,
        bearing_degrees=args.bearing,
        half_angle_degrees=args.half_angle,
        guard_mode=args.guard_mode,
        epsilon_m=args.epsilon,
        confidence_min=args.confidence_min,
        max_candidates=args.max_candidates,
        max_events=args.max_events,
        timestamp=args.timestamp,
        require_same_sheet=not args.ignore_sheet,
        require_same_orientation=not args.ignore_orientation,
        precision=args.precision,
    )


def command_build_pilot(args: argparse.Namespace) -> int:
    result = write_flevoland_pilot(
        args.graph,
        args.novelty,
        seed=args.seed,
        time_steps=args.time_steps,
        entities_per_cell=args.entities_per_cell,
        overwrite=not args.no_overwrite,
    )
    novelty = NoveltyLog(args.novelty)
    _print_json(
        {
            "format": "GSP4-PILOT-BUILD-1",
            "graph_path": str(Path(args.graph).resolve()),
            "graph": result.graph.summary(),
            "observation_counts_per_window": list(result.observation_counts),
            "fixed_frame_padding_used": False,
            "novelty_path": str(Path(args.novelty).resolve()),
            "novelty": novelty.validate(),
        }
    )
    return 0


def command_build_demo(args: argparse.Namespace) -> int:
    graph = build_demo_graph(
        seed=args.seed,
        spatial_backend=args.spatial_backend,
        spatial_resolution=args.spatial_resolution,
        teacher_dimensions=args.teacher_dimensions,
    )
    graph.save(args.graph)
    novelty = _seed_novelty_from_graph(graph, args.novelty)
    _print_json(
        {
            "graph_path": str(Path(args.graph).resolve()),
            "graph": graph.summary(),
            "novelty_path": str(Path(args.novelty).resolve()),
            "novelty": novelty.validate(),
        }
    )
    return 0


def command_demo(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    graph_path = output / "flevoland_demo.ugkg"
    novelty_path = output / "flevoland_demo.ugnl"
    model_path = output / "flevoland_student.pt"
    metrics_path = output / "flevoland_student.metrics.json"
    query_path = output / "near_query.json"
    benchmark_path = output / "benchmark.json"
    deployment_path = output / "flevoland_demo.ugdeploy"

    graph = build_demo_graph(seed=args.seed, teacher_dimensions=args.teacher_dimensions)
    graph.save(graph_path)
    novelty = _seed_novelty_from_graph(graph, novelty_path)
    training = train_model(
        graph,
        model_path,
        metrics_path=metrics_path,
        config=TrainConfig(
            hidden_dim=args.hidden_dim,
            heads=args.heads,
            layers=args.layers,
            dropout=args.dropout,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            max_edges_per_epoch=args.max_edges,
            max_encoder_edges=args.max_encoder_edges,
            temporal_edges_per_epoch=args.temporal_edges,
            early_stopping_patience=args.early_stopping,
            seed=args.seed,
            device=args.device,
            precision=args.precision,
            compile_model=args.compile,
        ),
    )
    source_index = next(
        index
        for index, node_type in enumerate(graph.node_type.tolist())
        if int(node_type) == int(NodeType.SENSOR)
    )
    query_config = QueryConfig(
        source_node_id=int(graph.node_id[source_index]),
        relation=int(RelationType.NEAR),
        radius_m=args.query_radius,
        epsilon_m=args.query_epsilon,
        confidence_min=0.0,
        max_events=32,
        timestamp=float(graph.node_time.max(initial=0.0)) + 1.0,
        precision=args.precision,
    )
    model, selected, _ = load_model_for_graph(graph, model_path, device=args.device)
    query = execute_query(
        graph,
        query_config,
        model=model,
        device=selected,
        novelty_log=novelty,
    )
    query.save(query_path)
    benchmark = benchmark_student(
        graph,
        model_path,
        output_path=benchmark_path,
        config=BenchmarkConfig(
            device=args.device,
            precision=args.precision,
            warmup=args.warmup,
            repeats=args.repeats,
        ),
        query_config=query_config,
    )
    deployment = build_deployment(
        deployment_path,
        graph_path,
        model_path=model_path,
        novelty_path=novelty_path,
        runtime_config={
            "demo_query": asdict(query_config),
            "seed": args.seed,
            "teacher_mode": "deterministic hash smoke-test; replace via embed command",
        },
        extra_files={
            "results/training_metrics.json": metrics_path,
            "results/query.json": query_path,
            "results/benchmark.json": benchmark_path,
        },
    )
    validation = validate_deployment(deployment_path)
    summary = {
        "format": "UGTS-SPATIAL-DEMO-2",
        "graph": graph.summary(),
        "novelty": novelty.validate(),
        "training": training.final_metrics,
        "query": query.to_dict(),
        "benchmark": benchmark,
        "deployment": asdict(deployment),
        "deployment_validation": validation,
        "paths": {
            "graph": str(graph_path),
            "model": str(model_path),
            "novelty": str(novelty_path),
            "deployment": str(deployment_path),
        },
    }
    write_json(output / "demo_summary.json", summary)
    _print_json(summary)
    return 0


def command_inspect_graph(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    _print_json(
        {
            "path": str(Path(args.graph).resolve()),
            "bytes": Path(args.graph).stat().st_size,
            "human_bytes": human_bytes(Path(args.graph).stat().st_size),
            "sha256": sha256_file(args.graph),
            "summary": graph.summary(),
        }
    )
    return 0


def command_validate_novelty(args: argparse.Namespace) -> int:
    _print_json(NoveltyLog(args.novelty).validate())
    return 0


def command_embed(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    embedder = make_embedder(
        args.backend,
        dimensions=args.dimensions,
        base_url=args.base_url,
        model=args.model,
        model_path=args.model_path,
        batch_size=args.batch_size,
        device=args.device,
    )
    embedded = embed_graph(graph, embedder, node_types=_node_types(args.node_type))
    embedded.save(args.output)
    _print_json({"output": str(args.output), "summary": embedded.summary()})
    return 0


def command_candidates(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    candidates = generate_relation_candidates(
        graph,
        max_distance_m=args.max_distance,
        concepts_per_source=args.concepts_per_source,
        spatial_per_source=args.spatial_per_source,
        max_candidates=args.max_candidates,
    )
    count = write_relation_candidates(args.output, candidates)
    _print_json({"output": str(args.output), "candidates": count})
    return 0


def command_teacher_label(args: argparse.Namespace) -> int:
    candidates = read_relation_candidates(args.candidates)
    start = max(0, args.offset)
    stop = len(candidates) if args.limit <= 0 else min(len(candidates), start + args.limit)
    teacher = OpenAICompatibleChatTeacher(
        base_url=args.base_url,
        model=args.model,
        timeout_s=args.timeout,
        api_key=args.api_key,
    )
    labels = []
    for position, candidate in enumerate(candidates[start:stop], start=start):
        label = teacher.label(candidate)
        labels.append(label)
        if args.progress:
            print(
                f"{position + 1}/{stop} {candidate.candidate_id} "
                f"{label.relation} {label.confidence:.3f}",
                file=sys.stderr,
            )
    count = write_teacher_labels(args.output, labels)
    _print_json({"output": str(args.output), "labels": count, "model": args.model})
    return 0


def command_labels_to_edges(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    labels = read_teacher_labels(args.labels)
    edge_set = teacher_edges_from_labels(
        graph,
        [asdict(label) for label in labels],
        teacher_name=args.teacher_name,
    )
    edge_set.save(args.output)
    _print_json({"output": str(args.output), "summary": edge_set.summary()})
    return 0


def command_merge_labels(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    candidates = read_relation_candidates(args.candidates)
    labels = read_teacher_labels(args.labels)
    merged = merge_teacher_labels(
        graph, candidates, labels, minimum_confidence=args.minimum_confidence
    )
    merged.save(args.output)
    _print_json(
        {
            "output": str(args.output),
            "added_edges": merged.num_edges - graph.num_edges,
            "summary": merged.summary(),
        }
    )
    return 0


def command_inspect_teacher(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph) if args.graph else None
    edges = TeacherEdgeSet.load(args.teacher_edges, graph=graph)
    _print_json(edges.summary())
    return 0


def command_train(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    teacher_edges = (
        TeacherEdgeSet.load(args.teacher_edges, graph=graph)
        if args.teacher_edges
        else None
    )
    result = train_model(
        graph,
        args.output,
        metrics_path=args.metrics,
        teacher_edges=teacher_edges,
        config=TrainConfig(
            hidden_dim=args.hidden_dim,
            heads=args.heads,
            layers=args.layers,
            dropout=args.dropout,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            weight_decay=args.weight_decay,
            link_weight=args.link_weight,
            node_teacher_weight=args.node_teacher_weight,
            edge_teacher_weight=args.edge_teacher_weight,
            type_weight=args.type_weight,
            temporal_weight=args.temporal_weight,
            negatives_per_positive=args.negatives,
            max_edges_per_epoch=args.max_edges,
            max_encoder_edges=args.max_encoder_edges,
            max_teacher_edges_per_epoch=args.max_teacher_edges,
            temporal_edges_per_epoch=args.temporal_edges,
            early_stopping_patience=args.early_stopping,
            seed=args.seed,
            device=args.device,
            precision=args.precision,
            compile_model=args.compile,
        ),
    )
    _print_json(
        {
            "checkpoint": result.checkpoint_path,
            "metrics": result.metrics_path,
            "final_metrics": result.final_metrics,
        }
    )
    return 0


def command_query(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    config = _query_from_args(graph, args)
    model = None
    selected = args.device
    if args.model:
        model, device, _ = load_model_for_graph(graph, args.model, device=args.device)
        selected = device
    novelty = None
    if args.commit:
        novelty = NoveltyLog(args.commit)
        if not novelty.path.exists():
            novelty.create()
    result = execute_query(
        graph,
        config,
        model=model,
        device=selected,
        novelty_log=novelty,
    )
    if args.output:
        result.save(args.output)
    _print_json(result.to_dict())
    return 0


def command_package(args: argparse.Namespace) -> int:
    summary = build_deployment(
        args.output,
        args.graph,
        model_path=args.model,
        novelty_path=args.novelty,
        ontology_path=args.ontology,
    )
    _print_json({**asdict(summary), "validation": validate_deployment(args.output)})
    return 0


def command_validate_package(args: argparse.Namespace) -> int:
    _print_json(validate_deployment(args.bundle))
    return 0


def command_geonames(args: argparse.Namespace) -> int:
    bbox = tuple(args.bbox) if args.bbox else None
    graph = build_geonames_graph(
        args.source,
        observations_csv=args.observations,
        max_rows=args.limit,
        min_population=args.min_population,
        country_code=args.country_code,
        bbox=bbox,
        spatial_backend=args.spatial_backend,
        spatial_resolution=args.spatial_resolution,
        near_radius_m=args.near_radius,
        neighbors_per_node=args.neighbors,
        teacher_dimensions=args.teacher_dimensions,
    )
    graph.save(args.output)
    _print_json({"output": str(args.output), "summary": graph.summary()})
    return 0


def command_ingest_osm(args: argparse.Namespace) -> int:
    graph = ingest_osm(
        args.source,
        limit=args.limit,
        morton_resolution=args.spatial_resolution,
        near_per_node=args.neighbors,
    )
    graph.save(args.output)
    _print_json({"output": str(args.output), "summary": graph.summary()})
    return 0


def command_check_gpu(args: argparse.Namespace) -> int:
    report = gpu_environment_report(
        run_smoke=not args.no_smoke,
        requested_device=args.device,
        precision=args.precision,
    )
    if args.output:
        write_json(args.output, report)
    _print_json(report)
    return 0 if report.get("ready") else 2


def command_export_ultra(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    _print_json(export_ultra_triples(graph, args.output))
    return 0


def command_import_scores(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    edges = import_scored_triples(
        graph, args.scores, teacher_name=args.teacher_name
    )
    edges.save(args.output)
    _print_json({"output": str(args.output), "summary": edges.summary()})
    return 0


def command_export_ugts(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    source_index = graph.index_for(_node_id(graph, args.source))
    result = export_ugts_candidates(
        graph,
        args.output_prefix,
        latitude=float(graph.latitude[source_index]),
        longitude=float(graph.longitude[source_index]),
        origin_elevation_m=float(graph.elevation[source_index]),
        source_index=source_index,
        radius_m=args.radius,
        axis=(args.axis[0], args.axis[1], args.axis[2]),
        cone_half_angle_deg=args.half_angle,
        guard_epsilon_m=args.epsilon,
        confidence_floor=args.confidence_min,
        query_time=args.timestamp,
        mode_bit=relation_from_value(args.relation),
        maximum_candidates=args.max_candidates,
    )
    _print_json(result)
    return 0


def command_benchmark(args: argparse.Namespace) -> int:
    graph = GraphPackage.load(args.graph)
    query_config = _query_from_args(graph, args) if args.source else None
    result = benchmark_student(
        graph,
        args.model,
        output_path=args.output,
        config=BenchmarkConfig(
            device=args.device,
            precision=args.precision,
            warmup=args.warmup,
            repeats=args.repeats,
        ),
        query_config=query_config,
    )
    _print_json(result)
    return 0


def _add_training_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--layers", type=int, default=3)
    parser.add_argument("--dropout", type=float, default=0.10)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--learning-rate", type=float, default=2e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--link-weight", type=float, default=1.0)
    parser.add_argument("--node-teacher-weight", type=float, default=0.5)
    parser.add_argument("--edge-teacher-weight", type=float, default=0.35)
    parser.add_argument("--type-weight", type=float, default=0.15)
    parser.add_argument("--temporal-weight", type=float, default=0.2)
    parser.add_argument("--negatives", type=int, default=1)
    parser.add_argument("--max-edges", type=int, default=50_000)
    parser.add_argument("--max-encoder-edges", type=int, default=250_000)
    parser.add_argument("--max-teacher-edges", type=int, default=20_000)
    parser.add_argument("--temporal-edges", type=int, default=4096)
    parser.add_argument("--early-stopping", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260710)
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    parser.add_argument(
        "--precision", default="float32", choices=("float32", "float16", "bf16")
    )
    parser.add_argument("--compile", action="store_true")


def _add_query_arguments(parser: argparse.ArgumentParser, *, source_required: bool) -> None:
    parser.add_argument("--source", required=source_required, help="persistent node key or numeric ID")
    parser.add_argument("--relation", default="near")
    parser.add_argument("--radius", type=float, default=5000.0)
    parser.add_argument("--bearing", type=float)
    parser.add_argument("--half-angle", type=float, default=180.0)
    parser.add_argument("--guard-mode", choices=("inside", "shell"), default="inside")
    parser.add_argument("--epsilon", type=float, default=25.0)
    parser.add_argument("--confidence-min", type=float, default=0.5)
    parser.add_argument("--max-candidates", type=int, default=100_000)
    parser.add_argument("--max-events", type=int, default=256)
    parser.add_argument("--timestamp", type=float, default=0.0)
    parser.add_argument("--ignore-sheet", action="store_true")
    parser.add_argument("--ignore-orientation", action="store_true")
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    parser.add_argument(
        "--precision", default="float32", choices=("float32", "float16", "bf16")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gsp4",
        description=(
            "Sparse geospatial HGT/TGN knowledge transfer with UGTS deterministic "
            "support, compatibility, guard, event, lineage and novelty deployment."
        ),
    )
    parser.add_argument("--version", action="version", version=f"gsp4-ugts-spatial {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser(
        "build-pilot",
        help="create the canonical no-download sparse Flevoland variable-event pilot",
    )
    command.add_argument("graph")
    command.add_argument("novelty")
    command.add_argument("--seed", type=int, default=20260710)
    command.add_argument("--time-steps", type=int, default=8)
    command.add_argument("--entities-per-cell", type=int, default=4)
    command.add_argument("--no-overwrite", action="store_true")
    command.set_defaults(func=command_build_pilot)

    command = sub.add_parser("build-demo", help="create the no-download variable-event graph")
    command.add_argument("graph")
    command.add_argument("novelty")
    command.add_argument("--seed", type=int, default=20260710)
    command.add_argument("--spatial-backend", choices=("morton", "h3"), default="morton")
    command.add_argument("--spatial-resolution", type=int, default=12)
    command.add_argument("--teacher-dimensions", type=int, default=64)
    command.set_defaults(func=command_build_demo)

    command = sub.add_parser("demo", help="build, train, query, benchmark and bundle")
    command.add_argument("output")
    command.add_argument("--teacher-dimensions", type=int, default=64)
    command.add_argument("--query-radius", type=float, default=10_000.0)
    command.add_argument("--query-epsilon", type=float, default=25.0)
    command.add_argument("--warmup", type=int, default=2)
    command.add_argument("--repeats", type=int, default=5)
    _add_training_arguments(command)
    command.set_defaults(
        epochs=6,
        hidden_dim=64,
        layers=2,
        max_edges=20_000,
        max_encoder_edges=50_000,
        early_stopping=6,
        func=command_demo,
    )

    command = sub.add_parser("inspect-graph", help="inspect and hash a .ugkg graph")
    command.add_argument("graph")
    command.set_defaults(func=command_inspect_graph)

    command = sub.add_parser("validate-novelty", help="validate a .ugnl chain")
    command.add_argument("novelty")
    command.set_defaults(func=command_validate_novelty)

    command = sub.add_parser("embed", help="attach an offline embedding-teacher cache")
    command.add_argument("graph")
    command.add_argument("output")
    command.add_argument(
        "--backend",
        choices=("hash", "http", "llama", "openai-compatible", "sentence-transformers", "st"),
        default="hash",
    )
    command.add_argument("--dimensions", type=int, default=256)
    command.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    command.add_argument("--model", default="Qwen3-Embedding-0.6B-GGUF")
    command.add_argument("--model-path")
    command.add_argument("--batch-size", type=int, default=32)
    command.add_argument("--node-type", action="append")
    command.add_argument("--device", default="auto")
    command.set_defaults(func=command_embed)

    command = sub.add_parser("teacher-candidates", help="create bounded relation candidates")
    command.add_argument("graph")
    command.add_argument("output")
    command.add_argument("--max-distance", type=float, default=5000.0)
    command.add_argument("--concepts-per-source", type=int, default=8)
    command.add_argument("--spatial-per-source", type=int, default=4)
    command.add_argument("--max-candidates", type=int, default=20_000)
    command.set_defaults(func=command_candidates)

    command = sub.add_parser("teacher-label", help="label candidates via OpenAI-compatible teacher")
    command.add_argument("candidates")
    command.add_argument("output")
    command.add_argument("--base-url", default="http://127.0.0.1:8081/v1")
    command.add_argument("--model", required=True)
    command.add_argument("--api-key")
    command.add_argument("--timeout", type=float, default=240.0)
    command.add_argument("--offset", type=int, default=0)
    command.add_argument("--limit", type=int, default=0)
    command.add_argument("--progress", action="store_true")
    command.set_defaults(func=command_teacher_label)

    command = sub.add_parser("labels-to-edges", help="compile labels to soft .ugte supervision")
    command.add_argument("graph")
    command.add_argument("labels")
    command.add_argument("output")
    command.add_argument("--teacher-name", default="LLM relation teacher")
    command.set_defaults(func=command_labels_to_edges)

    command = sub.add_parser("merge-labels", help="merge confident labels into a training graph")
    command.add_argument("graph")
    command.add_argument("candidates")
    command.add_argument("labels")
    command.add_argument("output")
    command.add_argument("--minimum-confidence", type=float, default=0.70)
    command.set_defaults(func=command_merge_labels)

    command = sub.add_parser("inspect-teacher", help="inspect a .ugte edge-teacher set")
    command.add_argument("teacher_edges")
    command.add_argument("--graph")
    command.set_defaults(func=command_inspect_teacher)

    command = sub.add_parser("train", help="train the compact HGT/TGN student")
    command.add_argument("graph")
    command.add_argument("output")
    command.add_argument("--metrics")
    command.add_argument("--teacher-edges")
    _add_training_arguments(command)
    command.set_defaults(func=command_train)

    command = sub.add_parser("query", help="support → compatibility → guard → score → event")
    command.add_argument("graph")
    command.add_argument("--model")
    command.add_argument("--output")
    command.add_argument("--commit", metavar="NOVELTY.UGNL")
    _add_query_arguments(command, source_required=True)
    command.set_defaults(func=command_query)

    command = sub.add_parser("package", help="build a hash-verified .ugdeploy archive")
    command.add_argument("graph")
    command.add_argument("output")
    command.add_argument("--model")
    command.add_argument("--novelty")
    command.add_argument("--ontology")
    command.set_defaults(func=command_package)

    command = sub.add_parser("validate-package", help="validate deployment contents and hashes")
    command.add_argument("bundle")
    command.set_defaults(func=command_validate_package)

    command = sub.add_parser("ingest-geonames", help="convert GeoNames ZIP/TXT to sparse .ugkg")
    command.add_argument("source")
    command.add_argument("output")
    command.add_argument("--observations", help="optional variable-length sensor CSV")
    command.add_argument("--bbox", type=float, nargs=4, metavar=("MIN_LAT", "MIN_LON", "MAX_LAT", "MAX_LON"))
    command.add_argument("--limit", type=int, default=10_000)
    command.add_argument("--min-population", type=int, default=0)
    command.add_argument("--country-code")
    command.add_argument("--spatial-backend", choices=("morton", "h3"), default="morton")
    command.add_argument("--spatial-resolution", type=int, default=13)
    command.add_argument("--near-radius", type=float, default=8000.0)
    command.add_argument("--neighbors", type=int, default=3)
    command.add_argument("--teacher-dimensions", type=int, default=0)
    command.set_defaults(func=command_geonames)

    command = sub.add_parser("ingest-osm", help="convert a small OSM XML/PBF extract to sparse .ugkg")
    command.add_argument("source")
    command.add_argument("output")
    command.add_argument("--limit", type=int, default=10_000)
    command.add_argument("--spatial-resolution", type=int, default=14)
    command.add_argument("--neighbors", type=int, default=2)
    command.set_defaults(func=command_ingest_osm)

    command = sub.add_parser("check-gpu", help="verify CUDA/PyTorch primitives used by GSP4")
    command.add_argument("--no-smoke", action="store_true")
    command.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    command.add_argument(
        "--precision", choices=("float16", "bf16", "float32"), default="float16"
    )
    command.add_argument("--output")
    command.set_defaults(func=command_check_gpu)

    command = sub.add_parser("export-ultra", help="export train/valid/test triples")
    command.add_argument("graph")
    command.add_argument("output")
    command.set_defaults(func=command_export_ultra)

    command = sub.add_parser("import-scores", help="import ULTRA/external soft scores into .ugte")
    command.add_argument("graph")
    command.add_argument("scores")
    command.add_argument("output")
    command.add_argument("--teacher-name", default="ULTRA structural teacher")
    command.set_defaults(func=command_import_scores)

    command = sub.add_parser("export-ugts", help="export G64/G32 buffers for the base substrate")
    command.add_argument("graph")
    command.add_argument("output_prefix")
    command.add_argument("--source", required=True)
    command.add_argument("--relation", default="near")
    command.add_argument("--radius", type=float, default=5000.0)
    command.add_argument("--axis", type=float, nargs=3, default=(0.0, 0.0, 1.0))
    command.add_argument("--half-angle", type=float, default=180.0)
    command.add_argument("--epsilon", type=float, default=25.0)
    command.add_argument("--confidence-min", type=float, default=0.0)
    command.add_argument("--timestamp", type=float)
    command.add_argument("--max-candidates", type=int, default=1_048_576)
    command.set_defaults(func=command_export_ugts)

    command = sub.add_parser("benchmark", help="measure model encoding and optional query gate")
    command.add_argument("graph")
    command.add_argument("model")
    command.add_argument("--output")
    command.add_argument("--warmup", type=int, default=3)
    command.add_argument("--repeats", type=int, default=10)
    _add_query_arguments(command, source_required=False)
    command.set_defaults(func=command_benchmark)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
