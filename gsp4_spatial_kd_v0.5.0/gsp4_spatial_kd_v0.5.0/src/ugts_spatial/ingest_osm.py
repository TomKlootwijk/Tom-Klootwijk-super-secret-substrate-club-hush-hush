from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Iterator

import numpy as np

from .builder import GraphBuilder
from .geocell import decode_morton_cell, encode_morton_cell, haversine_m, morton_grid_disk
from .graph import GraphPackage
from .schema import NodeType, RelationType
from .utils import sha256_file, stable_u64


_RELEVANT_KEYS = (
    "place",
    "amenity",
    "highway",
    "waterway",
    "natural",
    "building",
    "railway",
    "man_made",
    "tourism",
)


@dataclass(frozen=True)
class OSMFeature:
    osm_type: str
    osm_id: int
    latitude: float
    longitude: float
    kind: str
    value: str
    name: str
    tags: dict[str, str]


def _classify(tags: dict[str, str]) -> tuple[str, str] | None:
    for key in _RELEVANT_KEYS:
        value = tags.get(key)
        if value:
            return key, value
    return None


def _iter_osm_xml(path: Path, limit: int) -> Iterator[OSMFeature]:
    coordinates: dict[int, tuple[float, float]] = {}
    emitted = 0
    for event, elem in ET.iterparse(path, events=("end",)):
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag == "node":
            try:
                osm_id = int(elem.attrib["id"])
                latitude = float(elem.attrib["lat"])
                longitude = float(elem.attrib["lon"])
            except (KeyError, ValueError):
                elem.clear()
                continue
            coordinates[osm_id] = (latitude, longitude)
            tags = {
                child.attrib.get("k", ""): child.attrib.get("v", "")
                for child in elem
                if child.tag.rsplit("}", 1)[-1] == "tag"
            }
            classified = _classify(tags)
            if classified is not None:
                kind, value = classified
                yield OSMFeature(
                    "node",
                    osm_id,
                    latitude,
                    longitude,
                    kind,
                    value,
                    tags.get("name", f"{kind}={value}"),
                    tags,
                )
                emitted += 1
        elif tag == "way":
            tags = {
                child.attrib.get("k", ""): child.attrib.get("v", "")
                for child in elem
                if child.tag.rsplit("}", 1)[-1] == "tag"
            }
            classified = _classify(tags)
            if classified is not None:
                refs = [
                    int(child.attrib["ref"])
                    for child in elem
                    if child.tag.rsplit("}", 1)[-1] == "nd" and "ref" in child.attrib
                ]
                points = [coordinates[ref] for ref in refs if ref in coordinates]
                if points:
                    kind, value = classified
                    yield OSMFeature(
                        "way",
                        int(elem.attrib.get("id", 0)),
                        float(np.mean([point[0] for point in points])),
                        float(np.mean([point[1] for point in points])),
                        kind,
                        value,
                        tags.get("name", f"{kind}={value}"),
                        tags,
                    )
                    emitted += 1
        # Child <tag>/<nd> elements must remain populated until their parent
        # <node>/<way> end event is processed. Clearing every end event makes
        # the parent appear tagless. Clear only completed feature containers.
        if tag in {"node", "way", "relation"}:
            elem.clear()
        if limit > 0 and emitted >= limit:
            break


def _iter_osm_pbf(path: Path, limit: int) -> Iterator[OSMFeature]:
    try:
        import osmium  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PBF input requires pyosmium: install with `pip install .[osm]`, "
            "or convert a small extract to .osm XML"
        ) from exc

    features: list[OSMFeature] = []

    class Handler(osmium.SimpleHandler):  # type: ignore[misc]
        def node(self, node):
            if limit > 0 and len(features) >= limit:
                return
            tags = {tag.k: tag.v for tag in node.tags}
            classified = _classify(tags)
            if classified is None or not node.location.valid():
                return
            kind, value = classified
            features.append(
                OSMFeature(
                    "node",
                    int(node.id),
                    float(node.location.lat),
                    float(node.location.lon),
                    kind,
                    value,
                    tags.get("name", f"{kind}={value}"),
                    tags,
                )
            )

        def way(self, way):
            if limit > 0 and len(features) >= limit:
                return
            tags = {tag.k: tag.v for tag in way.tags}
            classified = _classify(tags)
            if classified is None:
                return
            points = [
                (float(node.lat), float(node.lon))
                for node in way.nodes
                if node.location.valid()
            ]
            if not points:
                return
            kind, value = classified
            features.append(
                OSMFeature(
                    "way",
                    int(way.id),
                    float(np.mean([point[0] for point in points])),
                    float(np.mean([point[1] for point in points])),
                    kind,
                    value,
                    tags.get("name", f"{kind}={value}"),
                    tags,
                )
            )

    handler = Handler()
    handler.apply_file(str(path), locations=True)
    yield from features[: None if limit <= 0 else limit]


def iter_osm_features(path: str | Path, *, limit: int = 10_000) -> Iterator[OSMFeature]:
    path = Path(path)
    if path.suffix.lower() == ".pbf":
        yield from _iter_osm_pbf(path, limit)
    else:
        yield from _iter_osm_xml(path, limit)


def _cell_split(cell_id: int) -> int:
    bucket = stable_u64(str(cell_id), namespace="ugts-spatial-osm-split") % 10
    return 0 if bucket < 7 else 1 if bucket == 7 else 2


def ingest_osm(
    source_path: str | Path,
    *,
    limit: int = 10_000,
    morton_resolution: int = 14,
    near_per_node: int = 2,
) -> GraphPackage:
    source_path = Path(source_path)
    features = list(iter_osm_features(source_path, limit=limit))
    if not features:
        raise ValueError("no relevant OSM features were found")
    center_lat = float(np.mean([feature.latitude for feature in features]))
    center_lon = float(np.mean([feature.longitude for feature in features]))
    builder = GraphBuilder(
        name=f"osm-{source_path.stem}",
        source=source_path.name,
        morton_resolution=morton_resolution,
        input_dim=32,
        teacher_dim=64,
        metadata={
            "converter": "ugts_spatial.ingest_osm",
            "source_sha256": sha256_file(source_path),
            "license_note": "OpenStreetMap data is ODbL; preserve attribution and share-alike obligations",
            "feature_limit": limit,
            "split_policy": "stable spatial cell hash",
        },
    )

    concepts = sorted({(feature.kind, feature.value) for feature in features})
    for kind, value in concepts:
        builder.add_node(
            f"concept:osm:{kind}:{value}",
            NodeType.CONCEPT,
            f"OpenStreetMap ontology tag {kind}={value}",
            latitude=center_lat,
            longitude=center_lon,
            split=0,
        )

    cell_nodes: dict[int, int] = {}
    cell_entities: dict[int, list[int]] = {}
    road_entities: dict[int, list[int]] = {}
    for feature in features:
        cell_id = encode_morton_cell(feature.latitude, feature.longitude, morton_resolution)
        split = _cell_split(cell_id)
        if cell_id not in cell_nodes:
            lat, lon, _ = decode_morton_cell(cell_id)
            cell_nodes[cell_id] = builder.add_node(
                f"cell:{cell_id}",
                NodeType.SPATIAL_CELL,
                f"Morton broad-phase cell {cell_id} containing OpenStreetMap features",
                latitude=lat,
                longitude=lon,
                cell_id=cell_id,
                split=split,
            )
            cell_entities[cell_id] = []
            road_entities[cell_id] = []
        selected_tags = ", ".join(
            f"{key}={feature.tags[key]}"
            for key in sorted(feature.tags)
            if key in _RELEVANT_KEYS or key in {"name", "operator", "ref"}
        )
        entity = builder.add_node(
            f"osm:{feature.osm_type}:{feature.osm_id}",
            NodeType.SPATIAL_ENTITY,
            f"OpenStreetMap {feature.osm_type} {feature.name}; {selected_tags}",
            latitude=feature.latitude,
            longitude=feature.longitude,
            cell_id=cell_id,
            split=split,
            metadata={
                "osm_type": feature.osm_type,
                "osm_id": feature.osm_id,
                "kind": feature.kind,
                "value": feature.value,
            },
        )
        cell_entities[cell_id].append(entity)
        if feature.kind == "highway":
            road_entities[cell_id].append(entity)
        builder.add_edge(entity, cell_nodes[cell_id], RelationType.LOCATED_IN)
        builder.add_edge(entity, f"concept:osm:{feature.kind}:{feature.value}", RelationType.INSTANCE_OF)

    existing_cells = set(cell_nodes)
    seen_pairs: set[tuple[int, int]] = set()
    for cell_id in existing_cells:
        for neighbor in morton_grid_disk(cell_id, 1):
            if neighbor == cell_id or neighbor not in existing_cells:
                continue
            pair = tuple(sorted((cell_id, neighbor)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            builder.add_edge(cell_nodes[cell_id], cell_nodes[neighbor], RelationType.ADJACENT_TO, symmetric=True)

    for cell_id, entities in cell_entities.items():
        for source in entities:
            candidates: list[tuple[float, int]] = []
            for target in entities:
                if source == target:
                    continue
                distance = haversine_m(
                    builder.nodes[source].latitude,
                    builder.nodes[source].longitude,
                    builder.nodes[target].latitude,
                    builder.nodes[target].longitude,
                )
                candidates.append((distance, target))
            for distance, target in sorted(candidates)[: max(0, near_per_node)]:
                if source < target:
                    builder.add_edge(
                        source,
                        target,
                        RelationType.NEAR,
                        weight=float(math.exp(-distance / 4000.0)),
                        symmetric=True,
                    )
                    builder.add_edge(source, target, RelationType.SAME_CELL, symmetric=True)
        roads = road_entities[cell_id]
        for first, second in zip(roads, roads[1:]):
            builder.add_edge(first, second, RelationType.CONNECTED_TO, symmetric=True)

    graph = builder.build()
    graph.metadata["source_features"] = len(features)
    graph.metadata["source_cells"] = len(cell_nodes)
    return graph
