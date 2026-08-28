from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import io
import math
from pathlib import Path
from typing import Any, Iterable, Iterator
import zipfile

import numpy as np

from .embeddings import HashEmbedder
from .geocell import SpatialIndex, haversine_m, make_spatial_index
from .graph import GraphPackage
from .spatial import pair_edge_attr_numpy
from .schema import (
    NODE_TYPE_NAMES,
    RELATION_TYPE_NAMES,
    NodeType,
    RelationType,
    node_compatibility_mask,
)
from .utils import stable_u64

FEATURE_DIM = 16
FEATURE_SCHEMA = "ugts-spatial-feature-v1"


def _bounded_hash_feature(value: str, namespace: str) -> float:
    return ((stable_u64(value, namespace=namespace) & 0xFFFF) / 32767.5) - 1.0


def make_feature_vector(
    *,
    latitude: float,
    longitude: float,
    elevation: float = 0.0,
    timestamp: float = 0.0,
    magnitude: float = 0.0,
    value: float = 0.0,
    uncertainty: float = 0.0,
    active: float = 1.0,
    feature_class: str = "",
    feature_code: str = "",
    admin_code: str = "",
) -> np.ndarray:
    """Create the stable 16-scalar feature profile used by UGKG1."""
    lat_r = math.radians(float(latitude))
    lon_r = math.radians(float(longitude))
    day = float(timestamp) / 86_400.0 if timestamp else 0.0
    return np.asarray(
        [
            float(latitude) / 90.0,
            float(longitude) / 180.0,
            math.sin(lat_r),
            math.cos(lat_r),
            math.sin(lon_r),
            math.cos(lon_r),
            math.tanh(float(elevation) / 1000.0),
            math.tanh(math.log1p(max(0.0, float(magnitude))) / 16.0),
            math.sin(2.0 * math.pi * day),
            math.cos(2.0 * math.pi * day),
            math.tanh(float(value)),
            min(1.0, max(0.0, float(uncertainty))),
            min(1.0, max(0.0, float(active))),
            _bounded_hash_feature(feature_class, "ugts-feature-class"),
            _bounded_hash_feature(feature_code, "ugts-feature-code"),
            _bounded_hash_feature(admin_code, "ugts-admin-code"),
        ],
        dtype=np.float32,
    )


def parse_timestamp(value: str | float | int | None) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (float, int)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def split_for_cell(cell_id: int, *, train_percent: int = 80, validation_percent: int = 10) -> int:
    if train_percent <= 0 or validation_percent < 0 or train_percent + validation_percent >= 100:
        raise ValueError("invalid split percentages")
    value = stable_u64(str(int(cell_id)), namespace="ugts-spatial-split") % 100
    if value < train_percent:
        return 0
    if value < train_percent + validation_percent:
        return 1
    return 2


@dataclass
class GraphAssembler:
    spatial_index: SpatialIndex
    metadata: dict[str, Any] = field(default_factory=dict)
    features: list[np.ndarray] = field(default_factory=list)
    node_type: list[int] = field(default_factory=list)
    node_id: list[int] = field(default_factory=list)
    latitude: list[float] = field(default_factory=list)
    longitude: list[float] = field(default_factory=list)
    elevation: list[float] = field(default_factory=list)
    node_time: list[float] = field(default_factory=list)
    cell_id: list[int] = field(default_factory=list)
    split: list[int] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    edge_source: list[int] = field(default_factory=list)
    edge_target: list[int] = field(default_factory=list)
    edge_type: list[int] = field(default_factory=list)
    edge_time: list[float] = field(default_factory=list)
    edge_weight: list[float] = field(default_factory=list)
    id_to_index: dict[int, int] = field(default_factory=dict)
    cell_nodes: dict[int, int] = field(default_factory=dict)
    concepts: dict[str, int] = field(default_factory=dict)
    _edge_keys: set[tuple[int, int, int, int]] = field(default_factory=set)

    def add_node(
        self,
        *,
        node_id: int,
        node_type: NodeType | int,
        latitude: float,
        longitude: float,
        elevation: float,
        timestamp: float,
        cell_id: int,
        split: int,
        text: str,
        feature: np.ndarray,
    ) -> int:
        node_id = int(node_id) & 0xFFFFFFFFFFFFFFFF
        if node_id in self.id_to_index:
            raise ValueError(f"duplicate node_id {node_id}")
        feature = np.asarray(feature, dtype=np.float32)
        if feature.shape != (FEATURE_DIM,):
            raise ValueError(f"feature must have shape [{FEATURE_DIM}]")
        index = len(self.features)
        self.id_to_index[node_id] = index
        self.features.append(feature)
        self.node_type.append(int(node_type))
        self.node_id.append(node_id)
        self.latitude.append(float(latitude))
        self.longitude.append(float(longitude))
        self.elevation.append(float(elevation))
        self.node_time.append(float(timestamp))
        self.cell_id.append(int(cell_id) & 0xFFFFFFFFFFFFFFFF)
        self.split.append(int(split))
        self.texts.append(str(text))
        return index

    def add_edge(
        self,
        source: int,
        target: int,
        relation: RelationType | int,
        *,
        timestamp: float = 0.0,
        weight: float = 1.0,
        deduplicate: bool = True,
    ) -> None:
        relation_value = int(relation)
        key = (int(source), int(target), relation_value, int(round(timestamp * 1000.0)))
        if deduplicate and key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edge_source.append(int(source))
        self.edge_target.append(int(target))
        self.edge_type.append(relation_value)
        self.edge_time.append(float(timestamp))
        self.edge_weight.append(float(weight))

    def add_symmetric_edge(
        self,
        source: int,
        target: int,
        relation: RelationType | int,
        *,
        timestamp: float = 0.0,
        weight: float = 1.0,
    ) -> None:
        self.add_edge(source, target, relation, timestamp=timestamp, weight=weight)
        self.add_edge(target, source, relation, timestamp=timestamp, weight=weight)

    def get_or_add_cell(self, cell_id: int) -> int:
        cell_id = int(cell_id)
        existing = self.cell_nodes.get(cell_id)
        if existing is not None:
            return existing
        latitude, longitude = self.spatial_index.center(cell_id)
        split = split_for_cell(cell_id)
        index = self.add_node(
            node_id=stable_u64(str(cell_id), namespace="ugts-cell-node"),
            node_type=NodeType.SPATIAL_CELL,
            latitude=latitude,
            longitude=longitude,
            elevation=0.0,
            timestamp=0.0,
            cell_id=cell_id,
            split=split,
            text=f"spatial cell {self.spatial_index.name}:{cell_id}",
            feature=make_feature_vector(
                latitude=latitude,
                longitude=longitude,
                feature_class="cell",
                feature_code=self.spatial_index.name,
            ),
        )
        self.cell_nodes[cell_id] = index
        return index

    def get_or_add_concept(self, key: str, *, description: str | None = None) -> int:
        normalized = key.strip().casefold()
        existing = self.concepts.get(normalized)
        if existing is not None:
            return existing
        index = self.add_node(
            node_id=stable_u64(normalized, namespace="ugts-concept-node"),
            node_type=NodeType.CONCEPT,
            latitude=0.0,
            longitude=0.0,
            elevation=0.0,
            timestamp=0.0,
            cell_id=0,
            split=0,
            text=description or f"ontology concept {key}",
            feature=make_feature_vector(
                latitude=0.0,
                longitude=0.0,
                feature_class="concept",
                feature_code=normalized,
            ),
        )
        self.concepts[normalized] = index
        return index

    def connect_cells(self) -> None:
        present = set(self.cell_nodes)
        for cell_id, source in list(self.cell_nodes.items()):
            for neighbor in self.spatial_index.neighbors(cell_id, 1):
                if neighbor == cell_id or neighbor not in present:
                    continue
                target = self.cell_nodes[neighbor]
                self.add_symmetric_edge(source, target, RelationType.CONNECTED_TO)

    def add_near_edges(self, node_indices: Iterable[int], *, radius_m: float, neighbors_per_node: int) -> None:
        indices = list(dict.fromkeys(int(value) for value in node_indices))
        if neighbors_per_node <= 0 or len(indices) < 2:
            return
        for source in indices:
            distances: list[tuple[float, int]] = []
            for target in indices:
                if source == target:
                    continue
                distance = haversine_m(
                    self.latitude[source],
                    self.longitude[source],
                    self.latitude[target],
                    self.longitude[target],
                )
                if distance <= radius_m:
                    distances.append((distance, target))
            distances.sort(key=lambda item: (item[0], item[1]))
            for distance, target in distances[:neighbors_per_node]:
                weight = math.exp(-distance / max(1.0, radius_m))
                self.add_edge(source, target, RelationType.NEAR, weight=weight)

    def finalize(self) -> GraphPackage:
        edge_index = np.asarray([self.edge_source, self.edge_target], dtype=np.int64)
        if edge_index.size == 0:
            edge_index = np.zeros((2, 0), dtype=np.int64)
        metadata = {
            "node_types": {str(key): value for key, value in NODE_TYPE_NAMES.items()},
            "relation_types": {str(key): value for key, value in RELATION_TYPE_NAMES.items()},
            "ontology_version": "ugts-geo-ontology-v1",
            "coordinate_reference": "WGS84+local-ENU",
            "feature_schema": FEATURE_SCHEMA,
            "spatial_index": {
                "backend": self.spatial_index.name,
                "resolution": self.spatial_index.resolution,
            },
            **self.metadata,
        }
        latitude = np.asarray(self.latitude, dtype=np.float64)
        longitude = np.asarray(self.longitude, dtype=np.float64)
        elevation = np.asarray(self.elevation, dtype=np.float32)
        node_time = np.asarray(self.node_time, dtype=np.float64)
        edge_attr = pair_edge_attr_numpy(
            latitude, longitude, elevation, node_time, edge_index
        )
        return GraphPackage(
            x=np.asarray(self.features, dtype=np.float32),
            node_type=np.asarray(self.node_type, dtype=np.int64),
            node_id=np.asarray(self.node_id, dtype=np.uint64),
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
            node_time=node_time,
            cell_id=np.asarray(self.cell_id, dtype=np.uint64),
            split=np.asarray(self.split, dtype=np.int8),
            sheet=np.zeros(len(self.node_type), dtype=np.uint8),
            orientation=np.zeros(len(self.node_type), dtype=np.uint8),
            compatibility_mask=np.asarray(
                [node_compatibility_mask(value) for value in self.node_type],
                dtype=np.uint16,
            ),
            edge_index=edge_index,
            edge_type=np.asarray(self.edge_type, dtype=np.int64),
            edge_time=np.asarray(self.edge_time, dtype=np.float64),
            edge_weight=np.asarray(self.edge_weight, dtype=np.float32),
            edge_attr=edge_attr,
            texts=self.texts,
            metadata=metadata,
        )


def _add_located_and_type_edges(
    assembler: GraphAssembler,
    node_index: int,
    cell_id: int,
    concept_keys: Iterable[str],
) -> None:
    cell_index = assembler.get_or_add_cell(cell_id)
    assembler.add_edge(node_index, cell_index, RelationType.LOCATED_IN)
    for key in concept_keys:
        concept = assembler.get_or_add_concept(key)
        assembler.add_edge(node_index, concept, RelationType.INSTANCE_OF)


def build_demo_graph(
    *,
    seed: int = 20260710,
    spatial_backend: str = "morton",
    spatial_resolution: int | None = 12,
    teacher_dimensions: int = 64,
) -> GraphPackage:
    """Create a deterministic variable-length Flevoland-style pilot graph."""
    rng = np.random.default_rng(seed)
    spatial_index = make_spatial_index(spatial_backend, spatial_resolution)
    assembler = GraphAssembler(
        spatial_index,
        metadata={
            "dataset": "synthetic-flevoland-variable-event-pilot",
            "seed": int(seed),
            "authorship_basis": "UGTS-GN 1.1 user-supplied architecture",
        },
    )

    anchors = [
        ("Lelystad", 52.5185, 5.4714),
        ("Almere", 52.3508, 5.2647),
        ("Dronten", 52.5250, 5.7181),
        ("Emmeloord", 52.7108, 5.7486),
        ("Zeewolde", 52.3300, 5.5417),
        ("Urk", 52.6625, 5.6014),
    ]
    entity_kinds = ["city", "road segment", "water body", "building", "farm", "nature area"]
    property_kinds = ["traffic flow", "water level", "air temperature", "air quality"]

    spatial_nodes: list[int] = []
    entity_nodes_by_anchor: dict[int, list[int]] = {index: [] for index in range(len(anchors))}
    for number in range(96):
        anchor_index = number % len(anchors)
        anchor_name, anchor_latitude, anchor_longitude = anchors[anchor_index]
        latitude = anchor_latitude + float(rng.normal(0.0, 0.035))
        longitude = anchor_longitude + float(rng.normal(0.0, 0.050))
        kind = entity_kinds[number % len(entity_kinds)]
        population_or_size = float(rng.lognormal(mean=7.0, sigma=1.1))
        elevation = float(rng.normal(-1.0, 4.0))
        cell_id = spatial_index.cell(latitude, longitude)
        node_id = stable_u64(f"demo:entity:{number}", namespace="ugts-demo")
        node_index = assembler.add_node(
            node_id=node_id,
            node_type=NodeType.SPATIAL_ENTITY,
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
            timestamp=0.0,
            cell_id=cell_id,
            split=split_for_cell(cell_id),
            text=(
                f"{kind} near {anchor_name}, Flevoland; persistent spatial entity; "
                f"synthetic magnitude {population_or_size:.1f}"
            ),
            feature=make_feature_vector(
                latitude=latitude,
                longitude=longitude,
                elevation=elevation,
                magnitude=population_or_size,
                feature_class="spatial_entity",
                feature_code=kind,
                admin_code="FL",
            ),
        )
        spatial_nodes.append(node_index)
        entity_nodes_by_anchor[anchor_index].append(node_index)
        _add_located_and_type_edges(assembler, node_index, cell_id, [kind, "spatial entity"])

    sensor_nodes: list[int] = []
    observations_by_sensor: dict[int, list[int]] = {}
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    for sensor_number in range(24):
        anchor_index = sensor_number % len(anchors)
        anchor_name, anchor_latitude, anchor_longitude = anchors[anchor_index]
        latitude = anchor_latitude + float(rng.normal(0.0, 0.020))
        longitude = anchor_longitude + float(rng.normal(0.0, 0.030))
        property_name = property_kinds[sensor_number % len(property_kinds)]
        cell_id = spatial_index.cell(latitude, longitude)
        sensor_id = stable_u64(f"demo:sensor:{sensor_number}", namespace="ugts-demo")
        sensor_index = assembler.add_node(
            node_id=sensor_id,
            node_type=NodeType.SENSOR,
            latitude=latitude,
            longitude=longitude,
            elevation=0.0,
            timestamp=0.0,
            cell_id=cell_id,
            split=split_for_cell(cell_id),
            text=f"sensor {sensor_number} near {anchor_name}; observes {property_name}",
            feature=make_feature_vector(
                latitude=latitude,
                longitude=longitude,
                feature_class="sensor",
                feature_code=property_name,
                admin_code="FL",
            ),
        )
        sensor_nodes.append(sensor_index)
        observations_by_sensor[sensor_index] = []
        _add_located_and_type_edges(assembler, sensor_index, cell_id, ["sensor"])
        property_concept = assembler.get_or_add_concept(property_name)
        assembler.add_edge(sensor_index, property_concept, RelationType.OBSERVES)

        # Different sensors emit different counts: no fixed frame dimension.
        observation_count = int(rng.integers(2, 11))
        previous_observation: int | None = None
        for ordinal in range(observation_count):
            timestamp = base_time + float(ordinal * 900 + sensor_number * 37 + rng.integers(0, 120))
            value = float(
                math.sin(ordinal * 0.7 + sensor_number * 0.2)
                + rng.normal(0.0, 0.08)
                + (sensor_number % 4) * 0.2
            )
            uncertainty = float(rng.uniform(0.01, 0.12))
            observation_id = stable_u64(
                f"demo:observation:{sensor_number}:{ordinal}", namespace="ugts-demo"
            )
            observation_index = assembler.add_node(
                node_id=observation_id,
                node_type=NodeType.OBSERVATION,
                latitude=latitude,
                longitude=longitude,
                elevation=0.0,
                timestamp=timestamp,
                cell_id=cell_id,
                split=split_for_cell(cell_id),
                text=(
                    f"{property_name} observation from sensor {sensor_number}; "
                    f"value {value:.5f}; uncertainty {uncertainty:.5f}"
                ),
                feature=make_feature_vector(
                    latitude=latitude,
                    longitude=longitude,
                    timestamp=timestamp,
                    value=value,
                    uncertainty=uncertainty,
                    feature_class="observation",
                    feature_code=property_name,
                    admin_code="FL",
                ),
            )
            observations_by_sensor[sensor_index].append(observation_index)
            assembler.add_edge(
                observation_index,
                sensor_index,
                RelationType.MADE_BY_SENSOR,
                timestamp=timestamp,
                weight=max(0.0, 1.0 - uncertainty),
            )
            assembler.add_edge(
                observation_index,
                property_concept,
                RelationType.HAS_PROPERTY,
                timestamp=timestamp,
            )
            nearest_entity = min(
                entity_nodes_by_anchor[anchor_index],
                key=lambda index: haversine_m(
                    latitude,
                    longitude,
                    assembler.latitude[index],
                    assembler.longitude[index],
                ),
            )
            assembler.add_edge(
                observation_index,
                nearest_entity,
                RelationType.AFFECTS,
                timestamp=timestamp,
                weight=max(0.05, 1.0 - uncertainty),
            )
            if previous_observation is not None:
                assembler.add_edge(
                    observation_index,
                    previous_observation,
                    RelationType.DESCENDS_FROM,
                    timestamp=timestamp,
                )
                assembler.add_edge(
                    observation_index,
                    previous_observation,
                    RelationType.SUPERSEDES,
                    timestamp=timestamp,
                )
            previous_observation = observation_index

    event_nodes: list[int] = []
    previous_event: int | None = None
    lineage_nodes: dict[int, int] = {}
    for event_number in range(18):
        anchor_index = event_number % len(anchors)
        target = entity_nodes_by_anchor[anchor_index][event_number % len(entity_nodes_by_anchor[anchor_index])]
        timestamp = base_time + 7200.0 + event_number * 1300.0
        latitude = assembler.latitude[target]
        longitude = assembler.longitude[target]
        cell_id = assembler.cell_id[target]
        lineage_group = event_number % 3
        if lineage_group not in lineage_nodes:
            lineage_nodes[lineage_group] = assembler.add_node(
                node_id=stable_u64(f"demo:lineage:{lineage_group}", namespace="ugts-demo"),
                node_type=NodeType.LINEAGE_STATE,
                latitude=latitude,
                longitude=longitude,
                elevation=0.0,
                timestamp=timestamp,
                cell_id=cell_id,
                split=assembler.split[target],
                text=f"lineage state {lineage_group} for verified spatial transitions",
                feature=make_feature_vector(
                    latitude=latitude,
                    longitude=longitude,
                    timestamp=timestamp,
                    feature_class="lineage",
                    feature_code=str(lineage_group),
                ),
            )
        event_index = assembler.add_node(
            node_id=stable_u64(f"demo:event:{event_number}", namespace="ugts-demo"),
            node_type=NodeType.EVENT,
            latitude=latitude,
            longitude=longitude,
            elevation=0.0,
            timestamp=timestamp,
            cell_id=cell_id,
            split=assembler.split[target],
            text=f"verified guard event {event_number} affecting node {assembler.node_id[target]}",
            feature=make_feature_vector(
                latitude=latitude,
                longitude=longitude,
                timestamp=timestamp,
                value=float(event_number % 4) / 3.0,
                uncertainty=0.03,
                feature_class="event",
                feature_code="guard crossing",
            ),
        )
        event_nodes.append(event_index)
        assembler.add_edge(event_index, target, RelationType.CROSSED_GUARD, timestamp=timestamp)
        assembler.add_edge(event_index, target, RelationType.AFFECTS, timestamp=timestamp)
        assembler.add_edge(
            event_index,
            lineage_nodes[lineage_group],
            RelationType.TRANSITIONED_TO,
            timestamp=timestamp,
        )
        if previous_event is not None:
            assembler.add_edge(event_index, previous_event, RelationType.DESCENDS_FROM, timestamp=timestamp)
        previous_event = event_index

    assembler.connect_cells()
    assembler.add_near_edges(spatial_nodes + sensor_nodes, radius_m=12_000.0, neighbors_per_node=4)
    graph = assembler.finalize()
    if teacher_dimensions > 0:
        embedder = HashEmbedder(dimensions=teacher_dimensions)
        embeddings = embedder.encode(graph.texts)
        graph = graph.with_teacher_embeddings(
            embeddings,
            teacher_metadata={
                "backend": embedder.name,
                "dimensions": teacher_dimensions,
                "purpose": "deterministic smoke-test; replace with a real embedding teacher",
            },
        )
    return graph


def _open_geonames_text(path: str | Path) -> tuple[io.TextIOBase, Any]:
    source = Path(path)
    if source.suffix.lower() == ".zip":
        archive = zipfile.ZipFile(source, "r")
        names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if not names:
            archive.close()
            raise ValueError("GeoNames ZIP contains no .txt file")
        raw = archive.open(names[0], "r")
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        return text, archive
    text = open(source, "r", encoding="utf-8", errors="replace", newline="")
    return text, text


def iter_geonames(path: str | Path) -> Iterator[dict[str, Any]]:
    text, owner = _open_geonames_text(path)
    try:
        for line_number, line in enumerate(text, start=1):
            columns = line.rstrip("\n\r").split("\t")
            if len(columns) < 19:
                raise ValueError(f"GeoNames line {line_number} has {len(columns)} columns, expected 19")
            yield {
                "geonameid": int(columns[0]),
                "name": columns[1],
                "asciiname": columns[2],
                "alternatenames": columns[3],
                "latitude": float(columns[4]),
                "longitude": float(columns[5]),
                "feature_class": columns[6],
                "feature_code": columns[7],
                "country_code": columns[8],
                "admin1": columns[10],
                "admin2": columns[11],
                "admin3": columns[12],
                "admin4": columns[13],
                "population": int(columns[14] or 0),
                "elevation": float(columns[15] or columns[16] or 0.0),
                "timezone": columns[17],
                "modification_date": columns[18],
            }
    finally:
        text.close()
        if owner is not text:
            owner.close()


def _load_observation_rows(path: str | Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"sensor_id", "latitude", "longitude", "property", "timestamp", "value"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"observation CSV is missing columns: {sorted(missing)}")
        return [{str(key): str(value or "") for key, value in row.items()} for row in reader]


def build_geonames_graph(
    path: str | Path,
    *,
    observations_csv: str | Path | None = None,
    max_rows: int = 0,
    min_population: int = 0,
    country_code: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    spatial_backend: str = "morton",
    spatial_resolution: int | None = 13,
    near_radius_m: float = 8_000.0,
    neighbors_per_node: int = 3,
    teacher_dimensions: int = 0,
) -> GraphPackage:
    """Compile a GeoNames country dump into a sparse typed UGKG1 graph."""
    spatial_index = make_spatial_index(spatial_backend, spatial_resolution)
    assembler = GraphAssembler(
        spatial_index,
        metadata={
            "dataset": "GeoNames gazetteer",
            "source_path": str(path),
            "source_license": "CC BY 4.0",
            "source_attribution": "GeoNames (https://www.geonames.org/)",
        },
    )
    spatial_nodes: list[int] = []
    geoname_to_index: dict[int, int] = {}
    accepted = 0
    for row in iter_geonames(path):
        if country_code and row["country_code"].casefold() != country_code.casefold():
            continue
        if bbox is not None:
            min_lat, min_lon, max_lat, max_lon = bbox
            if not (min_lat <= float(row["latitude"]) <= max_lat and min_lon <= float(row["longitude"]) <= max_lon):
                continue
        if int(row["population"]) < int(min_population):
            continue
        if max_rows > 0 and accepted >= max_rows:
            break
        accepted += 1
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        elevation = float(row["elevation"])
        cell_id = spatial_index.cell(latitude, longitude)
        split = split_for_cell(cell_id)
        alternate = str(row["alternatenames"])
        if len(alternate) > 280:
            alternate = alternate[:277] + "..."
        text = (
            f"GeoNames place {row['name']} ({row['asciiname']}); feature "
            f"{row['feature_class']}.{row['feature_code']}; country {row['country_code']}; "
            f"admin {row['admin1']}/{row['admin2']}; population {row['population']}; "
            f"alternate names {alternate}"
        )
        index = assembler.add_node(
            node_id=int(row["geonameid"]),
            node_type=NodeType.SPATIAL_ENTITY,
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
            timestamp=0.0,
            cell_id=cell_id,
            split=split,
            text=text,
            feature=make_feature_vector(
                latitude=latitude,
                longitude=longitude,
                elevation=elevation,
                magnitude=float(row["population"]),
                feature_class=str(row["feature_class"]),
                feature_code=str(row["feature_code"]),
                admin_code=f"{row['country_code']}.{row['admin1']}.{row['admin2']}",
            ),
        )
        geoname_to_index[int(row["geonameid"])] = index
        spatial_nodes.append(index)
        _add_located_and_type_edges(
            assembler,
            index,
            cell_id,
            [
                f"geonames feature class {row['feature_class']}",
                f"geonames feature code {row['feature_class']}.{row['feature_code']}",
                "spatial entity",
            ],
        )

    observation_rows = _load_observation_rows(observations_csv)
    sensor_indices: dict[str, int] = {}
    previous_observation: dict[str, int] = {}
    for row_number, row in enumerate(observation_rows):
        sensor_external_id = row["sensor_id"].strip()
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        property_name = row["property"].strip() or "unknown property"
        timestamp = parse_timestamp(row["timestamp"])
        value = float(row["value"])
        uncertainty = float(row.get("uncertainty", "0") or 0.0)
        unit = row.get("unit", "")
        cell_id = spatial_index.cell(latitude, longitude)
        split = split_for_cell(cell_id)
        sensor_index = sensor_indices.get(sensor_external_id)
        if sensor_index is None:
            sensor_index = assembler.add_node(
                node_id=stable_u64(sensor_external_id, namespace="ugts-sensor-external"),
                node_type=NodeType.SENSOR,
                latitude=latitude,
                longitude=longitude,
                elevation=float(row.get("elevation", "0") or 0.0),
                timestamp=0.0,
                cell_id=cell_id,
                split=split,
                text=f"sensor {sensor_external_id}; observes {property_name}",
                feature=make_feature_vector(
                    latitude=latitude,
                    longitude=longitude,
                    feature_class="sensor",
                    feature_code=property_name,
                ),
            )
            sensor_indices[sensor_external_id] = sensor_index
            _add_located_and_type_edges(assembler, sensor_index, cell_id, ["sensor"])
            property_concept = assembler.get_or_add_concept(property_name)
            assembler.add_edge(sensor_index, property_concept, RelationType.OBSERVES)
        property_concept = assembler.get_or_add_concept(property_name)
        observation_index = assembler.add_node(
            node_id=stable_u64(
                f"{sensor_external_id}:{timestamp:.6f}:{row_number}",
                namespace="ugts-observation-external",
            ),
            node_type=NodeType.OBSERVATION,
            latitude=latitude,
            longitude=longitude,
            elevation=float(row.get("elevation", "0") or 0.0),
            timestamp=timestamp,
            cell_id=cell_id,
            split=split,
            text=(
                f"observation {property_name}={value} {unit}; sensor {sensor_external_id}; "
                f"uncertainty {uncertainty}"
            ),
            feature=make_feature_vector(
                latitude=latitude,
                longitude=longitude,
                timestamp=timestamp,
                value=value,
                uncertainty=uncertainty,
                feature_class="observation",
                feature_code=property_name,
            ),
        )
        assembler.add_edge(
            observation_index,
            sensor_index,
            RelationType.MADE_BY_SENSOR,
            timestamp=timestamp,
            weight=max(0.0, 1.0 - uncertainty),
        )
        assembler.add_edge(
            observation_index,
            property_concept,
            RelationType.HAS_PROPERTY,
            timestamp=timestamp,
        )
        affected_id = row.get("affected_geoname_id", "").strip()
        if affected_id:
            target = geoname_to_index.get(int(affected_id))
            if target is not None:
                assembler.add_edge(
                    observation_index,
                    target,
                    RelationType.AFFECTS,
                    timestamp=timestamp,
                    weight=max(0.0, 1.0 - uncertainty),
                )
        previous = previous_observation.get(sensor_external_id)
        if previous is not None:
            assembler.add_edge(
                observation_index,
                previous,
                RelationType.DESCENDS_FROM,
                timestamp=timestamp,
            )
            assembler.add_edge(
                observation_index,
                previous,
                RelationType.SUPERSEDES,
                timestamp=timestamp,
            )
        previous_observation[sensor_external_id] = observation_index

    assembler.connect_cells()
    assembler.add_near_edges(
        spatial_nodes + list(sensor_indices.values()),
        radius_m=near_radius_m,
        neighbors_per_node=neighbors_per_node,
    )
    graph = assembler.finalize()
    graph.metadata.update(
        {
            "accepted_geonames_rows": accepted,
            "observation_rows": len(observation_rows),
            "bbox": list(bbox) if bbox is not None else None,
        }
    )
    if teacher_dimensions > 0:
        embedder = HashEmbedder(dimensions=teacher_dimensions)
        graph = graph.with_teacher_embeddings(
            embedder.encode(graph.texts),
            teacher_metadata={
                "backend": embedder.name,
                "dimensions": teacher_dimensions,
                "purpose": "deterministic smoke-test; replace with a real embedding teacher",
            },
        )
    return graph
