from __future__ import annotations

from dataclasses import dataclass
import csv
import math
from pathlib import Path
import zipfile
from typing import Iterable, Iterator

import numpy as np

from .builder import GraphBuilder
from .geocell import decode_morton_cell, encode_morton_cell, haversine_m, morton_grid_disk
from .graph import GraphPackage
from .schema import NodeType, RelationType
from .utils import sha256_file, stable_u64


@dataclass(frozen=True)
class GeoNamesRow:
    geoname_id: str
    name: str
    ascii_name: str
    latitude: float
    longitude: float
    feature_class: str
    feature_code: str
    country_code: str
    admin1: str
    population: int
    elevation: float
    timezone: str


def _iter_text_lines(path: Path) -> Iterator[str]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            members = [name for name in zf.namelist() if name.lower().endswith(".txt")]
            if not members:
                raise ValueError("GeoNames ZIP contains no .txt member")
            # Country dumps normally contain exactly one matching text file.
            with zf.open(sorted(members)[0], "r") as fh:
                for raw in fh:
                    yield raw.decode("utf-8", errors="replace").rstrip("\n\r")
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line.rstrip("\n\r")


def iter_geonames(path: str | Path) -> Iterator[GeoNamesRow]:
    path = Path(path)
    for line in _iter_text_lines(path):
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < 19:
            continue
        try:
            yield GeoNamesRow(
                geoname_id=fields[0],
                name=fields[1],
                ascii_name=fields[2],
                latitude=float(fields[4]),
                longitude=float(fields[5]),
                feature_class=fields[6] or "?",
                feature_code=fields[7] or "UNKNOWN",
                country_code=fields[8] or "??",
                admin1=fields[10] or "",
                population=int(fields[14] or 0),
                elevation=float(fields[15] or fields[16] or 0.0),
                timezone=fields[17] or "",
            )
        except (ValueError, OverflowError):
            continue


def _cell_split(cell_id: int) -> int:
    bucket = stable_u64(str(cell_id), namespace="ugts-spatial-split") % 10
    return 0 if bucket < 7 else 1 if bucket == 7 else 2


def ingest_geonames(
    source_path: str | Path,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = 10_000,
    min_population: int = 0,
    morton_resolution: int = 14,
    near_per_node: int = 3,
) -> GraphPackage:
    """Convert a GeoNames country dump into a sparse UGKG1 graph.

    bbox order is (min_lat, min_lon, max_lat, max_lon). The converter retains
    named places as persistent entities and builds cell and ontology nodes; it
    does not manufacture padded frames.
    """
    source_path = Path(source_path)
    rows: list[GeoNamesRow] = []
    for row in iter_geonames(source_path):
        if row.population < min_population:
            continue
        if bbox is not None:
            min_lat, min_lon, max_lat, max_lon = bbox
            if not (min_lat <= row.latitude <= max_lat and min_lon <= row.longitude <= max_lon):
                continue
        rows.append(row)
    rows.sort(key=lambda value: (-value.population, value.geoname_id))
    if limit > 0:
        rows = rows[:limit]
    if not rows:
        raise ValueError("no GeoNames rows survived the filters")

    center_lat = float(np.mean([row.latitude for row in rows]))
    center_lon = float(np.mean([row.longitude for row in rows]))
    builder = GraphBuilder(
        name=f"geonames-{source_path.stem}",
        source=str(source_path.name),
        morton_resolution=morton_resolution,
        input_dim=32,
        teacher_dim=64,
        metadata={
            "converter": "ugts_spatial.ingest_geonames",
            "source_sha256": sha256_file(source_path),
            "license_note": "GeoNames attribution required; source file is not redistributed by this package",
            "filters": {
                "bbox": bbox,
                "limit": limit,
                "min_population": min_population,
            },
            "split_policy": "stable spatial cell hash",
        },
    )

    # Global class concepts are in the training partition so held-out place
    # rows can still be assessed against a stable ontology vocabulary.
    feature_classes = sorted({row.feature_class for row in rows})
    feature_codes = sorted({row.feature_code for row in rows})
    for value in feature_classes:
        builder.add_node(
            f"concept:feature-class:{value}",
            NodeType.CONCEPT,
            f"GeoNames feature class {value}",
            latitude=center_lat,
            longitude=center_lon,
            split=0,
        )
    for value in feature_codes:
        builder.add_node(
            f"concept:feature-code:{value}",
            NodeType.CONCEPT,
            f"GeoNames feature code {value}",
            latitude=center_lat,
            longitude=center_lon,
            split=0,
        )

    cell_to_node: dict[int, int] = {}
    cell_to_entities: dict[int, list[int]] = {}
    for row in rows:
        cell_id = encode_morton_cell(row.latitude, row.longitude, morton_resolution)
        split = _cell_split(cell_id)
        if cell_id not in cell_to_node:
            cell_lat, cell_lon, _ = decode_morton_cell(cell_id)
            cell_to_node[cell_id] = builder.add_node(
                f"cell:{cell_id}",
                NodeType.SPATIAL_CELL,
                f"Morton broad-phase cell {cell_id} containing GeoNames entities",
                latitude=cell_lat,
                longitude=cell_lon,
                cell_id=cell_id,
                split=split,
            )
            cell_to_entities[cell_id] = []
        population_feature = math.log1p(max(0, row.population)) / 20.0
        entity = builder.add_node(
            f"geonames:{row.geoname_id}",
            NodeType.SPATIAL_ENTITY,
            (
                f"GeoNames place {row.name}; feature class {row.feature_class}; "
                f"feature code {row.feature_code}; country {row.country_code}; "
                f"admin1 {row.admin1}; timezone {row.timezone}"
            ),
            latitude=row.latitude,
            longitude=row.longitude,
            elevation=row.elevation,
            cell_id=cell_id,
            split=split,
            value=population_feature,
            metadata={
                "geoname_id": row.geoname_id,
                "feature_class": row.feature_class,
                "feature_code": row.feature_code,
                "population": row.population,
            },
        )
        cell_to_entities[cell_id].append(entity)
        builder.add_edge(entity, cell_to_node[cell_id], RelationType.LOCATED_IN)
        builder.add_edge(entity, f"concept:feature-class:{row.feature_class}", RelationType.HAS_PROPERTY)
        builder.add_edge(entity, f"concept:feature-code:{row.feature_code}", RelationType.INSTANCE_OF)

    existing_cells = set(cell_to_node)
    seen_pairs: set[tuple[int, int]] = set()
    for cell_id, cell_node in cell_to_node.items():
        for neighbor in morton_grid_disk(cell_id, 1):
            if neighbor == cell_id or neighbor not in existing_cells:
                continue
            pair = tuple(sorted((cell_id, neighbor)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            builder.add_edge(cell_node, cell_to_node[neighbor], RelationType.ADJACENT_TO, symmetric=True)

    for cell_id, entity_indices in cell_to_entities.items():
        for source in entity_indices:
            choices: list[tuple[float, int]] = []
            for target in entity_indices:
                if source == target:
                    continue
                distance = haversine_m(
                    builder.nodes[source].latitude,
                    builder.nodes[source].longitude,
                    builder.nodes[target].latitude,
                    builder.nodes[target].longitude,
                )
                choices.append((distance, target))
            for distance, target in sorted(choices)[: max(0, near_per_node)]:
                if source < target:
                    builder.add_edge(
                        source,
                        target,
                        RelationType.NEAR,
                        weight=float(math.exp(-distance / 10_000.0)),
                        symmetric=True,
                    )
                    builder.add_edge(source, target, RelationType.SAME_CELL, symmetric=True)

    graph = builder.build()
    graph.metadata["source_rows"] = len(rows)
    graph.metadata["source_cells"] = len(cell_to_node)
    return graph
