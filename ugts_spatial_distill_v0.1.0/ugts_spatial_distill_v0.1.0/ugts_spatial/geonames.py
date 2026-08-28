"""GeoNames country-dump adapter using only the Python standard library."""
from __future__ import annotations

from dataclasses import dataclass
import csv
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np

from .features import compose_node_features, deterministic_teacher_embedding
from .graph import GraphBuilder, SparseTemporalGraph
from .ontology import Ontology
from .spatial import SpatialIndexer, haversine_m


@dataclass(frozen=True)
class GeoNamesConfig:
    admin1_code: str | None = "16"
    max_records: int = 0
    min_population: int = 0
    feature_dim: int = 32
    teacher_dim: int = 64
    near_radius_m: float = 8_000.0
    negative_radius_m: float = 20_000.0
    seed: int = 200678942


def _open_country_text(path: Path) -> io.TextIOBase:
    if path.suffix.lower() == ".zip":
        archive = zipfile.ZipFile(path)
        members = [x for x in archive.namelist() if x.lower().endswith(".txt") and "readme" not in x.lower()]
        if not members:
            archive.close()
            raise ValueError("GeoNames ZIP contains no country .txt member")
        raw = archive.open(members[0], "r")
        # TextIOWrapper closes the member but not necessarily the archive; hold a
        # reference so it remains alive until the wrapper closes.
        wrapper = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        setattr(wrapper, "_ugts_zip", archive)
        return wrapper
    return path.open("r", encoding="utf-8", newline="")


def load_geonames_records(path: str | Path, config: GeoNamesConfig = GeoNamesConfig()) -> list[dict]:
    records: list[dict] = []
    with _open_country_text(Path(path)) as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 19:
                continue
            population = int(row[14] or 0)
            if config.admin1_code is not None and row[10] != config.admin1_code:
                continue
            if population < config.min_population:
                continue
            records.append({
                "geonameid": row[0], "name": row[1], "asciiname": row[2],
                "lat": float(row[4]), "lon": float(row[5]),
                "feature_class": row[6], "feature_code": row[7],
                "country": row[8], "admin1": row[10], "admin2": row[11],
                "population": population,
                "elevation": float(row[15] or row[16] or 0.0),
                "timezone": row[17], "modified": row[18],
            })
            if config.max_records and len(records) >= config.max_records:
                break
    return records


def build_geonames_graph(
    input_path: str | Path,
    ontology_path: str | Path,
    config: GeoNamesConfig = GeoNamesConfig(),
) -> SparseTemporalGraph:
    records = load_geonames_records(input_path, config)
    if not records:
        raise ValueError("no GeoNames records matched the filters")
    ontology = Ontology.load(ontology_path)
    nt = ontology.node_by_name; rel = ontology.rel_by_name
    builder = GraphBuilder(config.feature_dim)
    rng = np.random.default_rng(config.seed)
    indexer = SpatialIndexer(prefer_h3=True)
    center_lat = float(np.mean([r["lat"] for r in records])); center_lon = float(np.mean([r["lon"] for r in records]))

    cell_nodes: dict[str, int] = {}
    geo_nodes: list[int] = []
    coords: dict[int, tuple[float, float]] = {}
    for row in records:
        is_admin = row["feature_class"] == "A"
        node_type = "administrative_area" if is_admin else "spatial_entity"
        pop_feature = math.log1p(row["population"]) / 20.0
        text = f"GeoNames {row['feature_code']} feature {row['name']} ({row['asciiname']}) in {row['country']}; population {row['population']}; timezone {row['timezone']}."
        features = compose_node_features(
            text=text, node_type=nt[node_type].id, lat=row["lat"], lon=row["lon"], alt=row["elevation"],
            numeric=[pop_feature, ord(row["feature_class"][:1] or "?") / 128.0], dim=config.feature_dim,
            center_lat=center_lat, center_lon=center_lon,
        )
        node = builder.add_node("geonames", row["geonameid"], nt[node_type].id, row["lat"], row["lon"], row["elevation"], features, text)
        builder.set_teacher_vector(node, deterministic_teacher_embedding(text, config.teacher_dim))
        geo_nodes.append(node); coords[node] = (row["lat"], row["lon"])
        cell_id = indexer.cell(row["lat"], row["lon"])
        if cell_id not in cell_nodes:
            ctext = f"Spatial broad-phase cell {cell_id} for imported GeoNames features."
            cfeat = compose_node_features(text=ctext, node_type=nt["spatial_cell"].id, lat=row["lat"], lon=row["lon"], alt=0.0, numeric=[], dim=config.feature_dim, center_lat=center_lat, center_lon=center_lon)
            cnode = builder.add_node("spatial-cell", cell_id, nt["spatial_cell"].id, row["lat"], row["lon"], 0.0, cfeat, ctext)
            builder.set_teacher_vector(cnode, deterministic_teacher_embedding(ctext, config.teacher_dim))
            cell_nodes[cell_id] = cnode
        cell = cell_nodes[cell_id]
        builder.add_edge(node, cell, rel["located_in"].id, 0.0, 1.0)
        builder.add_edge(cell, node, rel["contains"].id, 0.0, 1.0)

    # Self loops and a modest link-prediction corpus. Split by longitude bands so
    # geographically adjacent rows are not randomly scattered across splits.
    for i in range(len(builder.nodes)):
        builder.add_edge(i, i, rel["self"].id, 0.0, 1.0)
    lon_values = np.asarray([coords[n][1] for n in geo_nodes])
    q1, q2 = np.quantile(lon_values, [0.60, 0.80])
    for source in geo_nodes:
        lat, lon = coords[source]
        candidates = [(haversine_m(lat, lon, *coords[target]), target) for target in geo_nodes if target != source]
        candidates.sort()
        if not candidates:
            continue
        split = 0 if lon <= q1 else (1 if lon <= q2 else 2)
        positives = [x for x in candidates if x[0] <= config.near_radius_m][:2]
        negatives = [x for x in reversed(candidates) if x[0] >= config.negative_radius_m][:2]
        for distance, target in positives:
            teacher = 0.55 + 0.44 / (1.0 + math.exp((distance - config.near_radius_m) / 1500.0))
            builder.add_example(source, target, rel["near"].id, 1.0, teacher, 0.0, distance, split)
        for distance, target in negatives:
            teacher = 0.01 + 0.2 / (1.0 + math.exp((distance - config.near_radius_m) / 1500.0))
            builder.add_example(source, target, rel["near"].id, 0.0, teacher, 0.0, distance, split)

    builder.metadata.update({
        "generator": "ugts_spatial.geonames.build_geonames_graph",
        "source": str(input_path),
        "source_kind": "GeoNames country dump",
        "record_count": len(records),
        "admin1_filter": config.admin1_code,
        "spatial_index_runtime_backend": indexer.backend,
        "teacher_kind": "deterministic_hash_fallback",
        "teacher_dim": config.teacher_dim,
        "no_frame_padding": True,
        "identity_contract": "GeoNames geonameid in namespace; coordinates are attributes",
        "event_types": ["external_novelty"],
        "max_time_hours": 0.0,
    })
    return builder.build()


def save_geonames_graph(input_path: str | Path, ontology_path: str | Path, output_dir: str | Path, config: GeoNamesConfig = GeoNamesConfig()) -> Path:
    return build_geonames_graph(input_path, ontology_path, config).save(output_dir)
