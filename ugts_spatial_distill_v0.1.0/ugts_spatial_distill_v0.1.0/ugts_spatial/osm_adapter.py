"""Optional OpenStreetMap PBF adapter backed by pyosmium.

`osmium` is deliberately optional because its native wheel compatibility can lag
new Python/CUDA environments. The core project and GeoNames path do not require
it. This module stores only selected tagged features and never pads time frames.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np

from .features import compose_node_features, deterministic_teacher_embedding
from .graph import GraphBuilder
from .ontology import Ontology
from .spatial import SpatialIndexer, haversine_m


@dataclass(frozen=True)
class OSMConfig:
    max_features: int = 100_000
    feature_dim: int = 32
    teacher_dim: int = 64
    near_radius_m: float = 3_000.0
    negative_radius_m: float = 12_000.0
    seed: int = 200678942


_INTERESTING = {"amenity", "shop", "tourism", "historic", "natural", "man_made", "place", "public_transport", "railway", "waterway", "highway", "building", "landuse"}


def _selected_tags(tags: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in tags:
        if tag.k in _INTERESTING or tag.k in {"name", "ref", "operator"}:
            out[str(tag.k)] = str(tag.v)
    return out


def ingest_osm_pbf(input_pbf: str | Path, ontology_path: str | Path, output_dir: str | Path, config: OSMConfig = OSMConfig()) -> Path:
    try:
        import osmium  # type: ignore
    except Exception as exc:
        raise RuntimeError("OSM PBF ingestion requires the optional 'osmium' package: python -m pip install osmium") from exc

    ontology = Ontology.load(ontology_path)
    nt = ontology.node_by_name; rel = ontology.rel_by_name
    records: list[tuple[str, str, float, float, dict[str, str], str]] = []

    class Handler(osmium.SimpleHandler):
        def node(self, node):
            if len(records) >= config.max_features:
                return
            tags = _selected_tags(node.tags)
            if not tags or not any(k in tags for k in _INTERESTING):
                return
            try:
                lat, lon = float(node.location.lat), float(node.location.lon)
            except Exception:
                return
            records.append(("osm-node", str(node.id), lat, lon, tags, "spatial_entity"))

        def way(self, way):
            if len(records) >= config.max_features:
                return
            tags = _selected_tags(way.tags)
            if not tags or not any(k in tags for k in _INTERESTING):
                return
            coords = []
            for n in way.nodes:
                try:
                    if n.location.valid():
                        coords.append((float(n.location.lat), float(n.location.lon)))
                except Exception:
                    continue
            if not coords:
                return
            lat = sum(x[0] for x in coords) / len(coords)
            lon = sum(x[1] for x in coords) / len(coords)
            node_type = "route" if "highway" in tags or "railway" in tags or "waterway" in tags else "spatial_entity"
            records.append(("osm-way", str(way.id), lat, lon, tags, node_type))

    Handler().apply_file(str(input_pbf), locations=True)
    if not records:
        raise ValueError("no selected OSM features were found")

    builder = GraphBuilder(config.feature_dim)
    indexer = SpatialIndexer(prefer_h3=True)
    cells: dict[str, int] = {}
    feature_nodes: list[int] = []
    coords: dict[int, tuple[float, float]] = {}
    center_lat = float(np.mean([x[2] for x in records])); center_lon = float(np.mean([x[3] for x in records]))
    for namespace, external_id, lat, lon, tags, node_type in records:
        label = tags.get("name") or tags.get("ref") or f"{namespace}/{external_id}"
        tag_text = "; ".join(f"{k}={v}" for k, v in sorted(tags.items()))
        text = f"OpenStreetMap feature {label}. {tag_text}."
        feat = compose_node_features(text=text, node_type=nt[node_type].id, lat=lat, lon=lon, alt=0.0, numeric=[len(tags) / 20.0], dim=config.feature_dim, center_lat=center_lat, center_lon=center_lon)
        node = builder.add_node(namespace, external_id, nt[node_type].id, lat, lon, 0.0, feat, text)
        builder.set_teacher_vector(node, deterministic_teacher_embedding(text, config.teacher_dim))
        feature_nodes.append(node); coords[node] = (lat, lon)
        cell_id = indexer.cell(lat, lon)
        if cell_id not in cells:
            ctext = f"Spatial broad-phase cell {cell_id} for OSM features."
            cfeat = compose_node_features(text=ctext, node_type=nt["spatial_cell"].id, lat=lat, lon=lon, alt=0.0, dim=config.feature_dim, center_lat=center_lat, center_lon=center_lon)
            cell = builder.add_node("spatial-cell", cell_id, nt["spatial_cell"].id, lat, lon, 0.0, cfeat, ctext)
            builder.set_teacher_vector(cell, deterministic_teacher_embedding(ctext, config.teacher_dim))
            cells[cell_id] = cell
        builder.add_edge(node, cells[cell_id], rel["located_in"].id, 0.0, 1.0)
        builder.add_edge(cells[cell_id], node, rel["contains"].id, 0.0, 1.0)

    for i in range(len(builder.nodes)):
        builder.add_edge(i, i, rel["self"].id, 0.0, 1.0)
    # A bounded near-relation training sample; avoid O(N^2) on large extracts by
    # comparing each source with a deterministic subset.
    rng = np.random.default_rng(config.seed)
    sample_sources = feature_nodes if len(feature_nodes) <= 10_000 else rng.choice(feature_nodes, size=10_000, replace=False).tolist()
    lon_values = np.asarray([coords[i][1] for i in sample_sources]); q1, q2 = np.quantile(lon_values, [0.6, 0.8])
    pool_array = np.asarray(feature_nodes, dtype=np.int64)
    for source in sample_sources:
        lat, lon = coords[source]
        sample_size = min(256, len(pool_array))
        targets = rng.choice(pool_array, size=sample_size, replace=False)
        pairs = sorted((haversine_m(lat, lon, *coords[int(t)]), int(t)) for t in targets if int(t) != source)
        positives = [x for x in pairs if x[0] <= config.near_radius_m][:2]
        negatives = [x for x in reversed(pairs) if x[0] >= config.negative_radius_m][:2]
        split = 0 if lon <= q1 else (1 if lon <= q2 else 2)
        for d, target in positives:
            builder.add_example(source, target, rel["near"].id, 1.0, 0.9, 0.0, d, split)
        for d, target in negatives:
            builder.add_example(source, target, rel["near"].id, 0.0, 0.1, 0.0, d, split)

    builder.metadata.update({
        "source": str(input_pbf), "source_kind": "OpenStreetMap PBF", "feature_count": len(records),
        "osm_attribution_required": True, "teacher_kind": "deterministic_hash_fallback", "teacher_dim": config.teacher_dim,
        "spatial_index_runtime_backend": indexer.backend, "no_frame_padding": True,
        "event_types": ["external_novelty"], "max_time_hours": 0.0,
    })
    return builder.build().save(output_dir)
