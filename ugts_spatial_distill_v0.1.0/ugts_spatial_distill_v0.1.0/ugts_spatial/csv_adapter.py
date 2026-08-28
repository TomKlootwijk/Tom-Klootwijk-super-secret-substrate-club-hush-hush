"""Generic CSV point adapter for user-controlled geospatial assets."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .features import compose_node_features, deterministic_teacher_embedding
from .graph import GraphBuilder
from .ontology import Ontology
from .spatial import SpatialIndexer


@dataclass(frozen=True)
class CSVConfig:
    id_column: str = "id"
    lat_column: str = "lat"
    lon_column: str = "lon"
    alt_column: str = "alt"
    text_column: str = "text"
    type_column: str = "type"
    feature_dim: int = 32
    teacher_dim: int = 64


def ingest_csv(input_csv: str | Path, ontology_path: str | Path, output_dir: str | Path, config: CSVConfig = CSVConfig()) -> Path:
    ontology = Ontology.load(ontology_path)
    nt = ontology.node_by_name; rel = ontology.rel_by_name
    builder = GraphBuilder(config.feature_dim)
    indexer = SpatialIndexer(prefer_h3=True)
    cell_nodes: dict[str, int] = {}
    with Path(input_csv).open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV has no rows")
    for row in rows:
        node_type = row.get(config.type_column, "spatial_entity") or "spatial_entity"
        if node_type not in nt:
            raise ValueError(f"unknown node type {node_type!r}")
        lat = float(row[config.lat_column]); lon = float(row[config.lon_column]); alt = float(row.get(config.alt_column, 0.0) or 0.0)
        text = row.get(config.text_column, "") or f"CSV geospatial point {row[config.id_column]}"
        feat = compose_node_features(text=text, node_type=nt[node_type].id, lat=lat, lon=lon, alt=alt, dim=config.feature_dim)
        node = builder.add_node("csv", row[config.id_column], nt[node_type].id, lat, lon, alt, feat, text)
        builder.set_teacher_vector(node, deterministic_teacher_embedding(text, config.teacher_dim))
        cell_id = indexer.cell(lat, lon)
        if cell_id not in cell_nodes:
            ctext = f"Spatial broad-phase cell {cell_id}."
            cfeat = compose_node_features(text=ctext, node_type=nt["spatial_cell"].id, lat=lat, lon=lon, alt=0.0, dim=config.feature_dim)
            cell = builder.add_node("spatial-cell", cell_id, nt["spatial_cell"].id, lat, lon, 0.0, cfeat, ctext)
            builder.set_teacher_vector(cell, deterministic_teacher_embedding(ctext, config.teacher_dim))
            cell_nodes[cell_id] = cell
        builder.add_edge(node, cell_nodes[cell_id], rel["located_in"].id, 0.0, 1.0)
        builder.add_edge(cell_nodes[cell_id], node, rel["contains"].id, 0.0, 1.0)
    for i in range(len(builder.nodes)):
        builder.add_edge(i, i, rel["self"].id, 0.0, 1.0)
    builder.metadata.update({"source": str(input_csv), "source_kind": "generic CSV", "no_frame_padding": True, "teacher_kind": "deterministic_hash_fallback", "event_types": ["external_novelty"], "max_time_hours": 0.0})
    return builder.build().save(output_dir)
