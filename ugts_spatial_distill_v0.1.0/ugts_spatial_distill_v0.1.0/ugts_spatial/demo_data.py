"""Deterministic variable-length Flevoland-like demonstration graph.

The coordinates and observations are synthetic. Named municipalities are used as
spatial anchors so the graph has a meaningful Dutch geography, while no claim is
made that generated sensors, assets or readings are real.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .features import compose_node_features, deterministic_teacher_embedding
from .graph import GraphBuilder, SparseTemporalGraph
from .ontology import Ontology
from .spatial import SpatialIndexer, haversine_m


@dataclass(frozen=True)
class DemoConfig:
    seed: int = 200678942
    feature_dim: int = 32
    teacher_dim: int = 64
    sensors_per_area: int = 10
    entities_per_area: int = 16
    routes_per_area: int = 3
    cells_per_area: int = 4
    observation_nodes_per_area: int = 8
    min_events_per_sensor: int = 8
    max_events_per_sensor: int = 22
    max_time_hours: float = 168.0


AREA_ANCHORS: tuple[tuple[str, float, float, int], ...] = (
    ("Almere", 52.3508, 5.2647, 0),
    ("Lelystad", 52.5185, 5.4714, 0),
    ("Dronten", 52.5250, 5.7180, 0),
    ("Emmeloord", 52.7108, 5.7486, 1),
    ("Urk", 52.6625, 5.6014, 2),
    ("Zeewolde", 52.3311, 5.5419, 2),
)

PROPERTY_SPECS: tuple[tuple[str, str, float, float], ...] = (
    ("air_temperature", "Air temperature in degrees Celsius", 12.0, 8.0),
    ("nitrogen_dioxide", "Nitrogen dioxide concentration", 28.0, 12.0),
    ("traffic_flow", "Vehicle count or traffic flow", 420.0, 180.0),
    ("water_level", "Water level relative to local datum", 0.4, 0.3),
    ("soil_moisture", "Soil moisture fraction", 0.45, 0.18),
    ("wind_speed", "Wind speed in metres per second", 5.0, 3.0),
)

ENTITY_CATEGORIES = (
    "school", "bridge", "pumping station", "park", "industrial site",
    "waterway", "road junction", "public building", "charging site", "farm",
)

EVENT_TYPES = (
    "observation_update",
    "sensor_online",
    "sensor_offline",
    "threshold_cross",
    "external_novelty",
    "ontology_reclassification",
    "route_change",
    "calibration",
)


def _jitter_lat_lon(rng: np.random.Generator, lat: float, lon: float, radius_m: float) -> tuple[float, float]:
    angle = float(rng.uniform(0.0, math.tau))
    radius = float(radius_m * math.sqrt(rng.uniform(0.0, 1.0)))
    dlat = radius * math.cos(angle) / 111_320.0
    dlon = radius * math.sin(angle) / max(1.0, 111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _status_feature(status: str) -> float:
    return {"RETAIN": 1.0, "TRANSLATE": 0.75, "CORRECTED": 0.5, "BOUNDED": 0.25, "OPTIONAL": 0.1, "REJECT": -1.0, "DEMOTE": -0.5}.get(status, 0.0)


def build_demo_graph(
    ontology_path: str | Path,
    catalog_path: str | Path,
    config: DemoConfig = DemoConfig(),
) -> SparseTemporalGraph:
    ontology = Ontology.load(ontology_path)
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    rng = np.random.default_rng(config.seed)
    builder = GraphBuilder(feature_dim=config.feature_dim)
    nt = ontology.node_by_name
    rel = ontology.rel_by_name

    node_text: dict[int, str] = {}

    def add_node(namespace: str, external_id: str, node_type: str, lat: float, lon: float, alt: float, text: str, numeric: list[float]) -> int:
        features = compose_node_features(
            text=text, node_type=nt[node_type].id, lat=lat, lon=lon, alt=alt,
            numeric=numeric, dim=config.feature_dim,
        )
        idx = builder.add_node(namespace, external_id, nt[node_type].id, lat, lon, alt, features, text)
        node_text[idx] = text
        return idx

    # Ontology properties.
    properties: list[int] = []
    for i, (name, description, mean, scale) in enumerate(PROPERTY_SPECS):
        text = f"SOSA observable property: {name}. {description}."
        properties.append(add_node("property", name, "property", 52.5, 5.5, 0.0, text, [*(1.0 if j == i else 0.0 for j in range(len(PROPERTY_SPECS))), mean / 500.0, scale / 200.0]))

    # UGTS mechanism catalog as explicit concept nodes. The uploaded package
    # contains an extended catalog; its count is retained in graph metadata.
    concepts: dict[str, int] = {}
    domain_concepts: dict[str, int] = {}
    for mechanism in catalog["mechanisms"]:
        domain = str(mechanism["domain"])
        if domain not in domain_concepts:
            text = f"UGTS mechanism domain: {domain}."
            domain_concepts[domain] = add_node("ugts-domain", domain, "concept", 52.5, 5.5, 0.0, text, [0.0, 0.0, 0.0])
        mid = str(mechanism["mechanism_id"])
        text = (
            f"{mid} {mechanism['name']}. Domain {domain}. "
            f"{mechanism['normalized_technical_definition']} "
            f"GPU realization: {mechanism['gpu_native_realization']} "
            f"Status {mechanism['status']}; validation {mechanism['validation_state']}."
        )
        idx = add_node(
            "ugts-mechanism", mid, "concept", 52.5, 5.5, 0.0, text,
            [_status_feature(str(mechanism["status"])), int(mid[1:]) / max(1, int(catalog["count"])), 0.0],
        )
        concepts[mid] = idx
        builder.add_edge(idx, domain_concepts[domain], rel["subclass_of"].id, 0.0, 1.0)
        dep = str(mechanism.get("dependencies", "")).strip()
        if dep:
            for token in dep.replace(";", ",").split(","):
                token = token.strip()
                if token in concepts:
                    builder.add_edge(idx, concepts[token], rel["depends_on"].id, 0.0, 1.0)

    # A small relation from properties to UGTS typed-state/operator concepts.
    for prop in properties:
        if "M086" in concepts:
            builder.add_edge(prop, concepts["M086"], rel["governed_by"].id, 0.0, 1.0)

    areas: dict[str, int] = {}
    cells_by_area: dict[str, list[int]] = {}
    cell_coords: dict[int, tuple[float, float]] = {}
    sensors_by_area: dict[str, list[int]] = {}
    entities_by_area: dict[str, list[int]] = {}
    routes_by_area: dict[str, list[int]] = {}
    sensor_property: dict[int, int] = {}
    sensor_area: dict[int, str] = {}
    sensor_coords: dict[int, tuple[float, float]] = {}
    entity_coords: dict[int, tuple[float, float]] = {}
    cell_assignment: dict[int, int] = {}

    # Persistent entities and sparse topology.
    cell_offsets = ((-0.035, -0.045), (-0.035, 0.045), (0.035, -0.045), (0.035, 0.045))
    for area_name, lat0, lon0, split in AREA_ANCHORS:
        area_text = f"Synthetic administrative anchor for {area_name}, Flevoland demonstration area. Spatial split {split}."
        area = add_node("admin-area", area_name, "administrative_area", lat0, lon0, 0.0, area_text, [split / 2.0, 1.0])
        areas[area_name] = area
        cells: list[int] = []
        for c, (dlat, dlon) in enumerate(cell_offsets[: config.cells_per_area]):
            lat, lon = lat0 + dlat, lon0 + dlon
            text = f"Broad-phase spatial support cell {c} around {area_name}."
            cell = add_node("demo-cell", f"{area_name}:{c}", "spatial_cell", lat, lon, 0.0, text, [c / max(1, config.cells_per_area - 1), split / 2.0])
            cells.append(cell); cell_coords[cell] = (lat, lon)
            builder.add_edge(cell, area, rel["located_in"].id, 0.0, 1.0)
            builder.add_edge(area, cell, rel["contains"].id, 0.0, 1.0)
        for a in range(len(cells)):
            for b in range(a + 1, len(cells)):
                builder.add_edge(cells[a], cells[b], rel["adjacent_to"].id, 0.0, 0.5)
                builder.add_edge(cells[b], cells[a], rel["adjacent_to"].id, 0.0, 0.5)
        cells_by_area[area_name] = cells

        sensors: list[int] = []
        for s in range(config.sensors_per_area):
            lat, lon = _jitter_lat_lon(rng, lat0, lon0, 11_000.0)
            prop_id = (s + 2 * list(x[0] for x in AREA_ANCHORS).index(area_name)) % len(properties)
            reliability = float(rng.uniform(0.90, 0.999))
            rate = float(rng.uniform(0.25, 2.0))
            name = PROPERTY_SPECS[prop_id][0]
            text = f"Synthetic {name} sensor {s} in {area_name}; persistent sensor identity with irregular observations."
            sensor = add_node("demo-sensor", f"{area_name}:{s}", "sensor", lat, lon, float(rng.uniform(-2.0, 25.0)), text, [*(1.0 if j == prop_id else 0.0 for j in range(len(properties))), reliability, rate / 2.0, split / 2.0])
            sensors.append(sensor); sensor_property[sensor] = prop_id; sensor_area[sensor] = area_name; sensor_coords[sensor] = (lat, lon)
            # Area relation remains in the message graph; cell relation is held out
            # as a supervised candidate to avoid a direct-edge label shortcut.
            builder.add_edge(sensor, area, rel["located_in"].id, 0.0, 0.8)
            builder.add_edge(area, sensor, rel["contains"].id, 0.0, 0.8)
            builder.add_edge(sensor, concepts.get("M088", concepts.get("M116")), rel["compatible_with"].id, 0.0, 1.0)
            if "M118" in concepts:
                builder.add_edge(sensor, concepts["M118"], rel["compatible_with"].id, 0.0, 0.8)
            builder.add_edge(sensor, properties[prop_id], rel["has_property"].id, 0.0, 1.0)
            builder.add_edge(sensor, properties[prop_id], rel["compatible_with"].id, 0.0, 0.9)
            builder.add_edge(properties[prop_id], sensor, rel["compatible_with"].id, 0.0, 0.9)
            # Assign nearest synthetic cell for supervised located_in examples.
            assigned = min(cells, key=lambda cidx: haversine_m(lat, lon, *cell_coords[cidx]))
            cell_assignment[sensor] = assigned

            event_count = int(rng.integers(config.min_events_per_sensor, config.max_events_per_sensor + 1))
            times = np.sort(rng.uniform(0.0, config.max_time_hours, size=event_count))
            mean, scale = PROPERTY_SPECS[prop_id][2], PROPERTY_SPECS[prop_id][3]
            prev = mean
            for sequence, time_h in enumerate(times):
                periodic = math.sin(time_h * math.tau / 24.0 + s * 0.2)
                value = float(mean + 0.6 * scale * periodic + rng.normal(0.0, 0.2 * scale))
                delta = value - prev; prev = value
                uncertainty = float(abs(rng.normal(0.03, 0.01)))
                event_type = 0
                if abs(delta) > 0.75 * scale and rng.random() < 0.35:
                    event_type = 3
                elif rng.random() < 0.015:
                    event_type = 4
                builder.add_event(sensor, float(time_h), event_type, [value, delta, uncertainty, float(sequence)])
            # Calibration and occasional status events are interleaved but no
            # fixed count is imposed per sensor.
            if rng.random() < 0.8:
                builder.add_event(sensor, float(rng.uniform(0.0, config.max_time_hours)), 7, [reliability, rate, 0.0, 0.0])
            if rng.random() < 0.12:
                builder.add_event(sensor, float(rng.uniform(0.0, config.max_time_hours)), 2, [0.0, 0.0, 0.0, 0.0])
                builder.add_event(sensor, float(rng.uniform(0.0, config.max_time_hours)), 1, [1.0, 0.0, 0.0, 0.0])
        sensors_by_area[area_name] = sensors

        entities: list[int] = []
        for e in range(config.entities_per_area):
            lat, lon = _jitter_lat_lon(rng, lat0, lon0, 13_000.0)
            category = ENTITY_CATEGORIES[e % len(ENTITY_CATEGORIES)]
            importance = float(rng.uniform(0.1, 1.0))
            text = f"Synthetic geospatial asset: {category} {e} in {area_name}."
            entity = add_node("demo-asset", f"{area_name}:{e}", "spatial_entity", lat, lon, float(rng.uniform(-3.0, 40.0)), text, [e % len(ENTITY_CATEGORIES) / len(ENTITY_CATEGORIES), importance, split / 2.0])
            entities.append(entity); entity_coords[entity] = (lat, lon)
            builder.add_edge(entity, area, rel["located_in"].id, 0.0, 0.8)
            builder.add_edge(area, entity, rel["contains"].id, 0.0, 0.8)
            builder.add_edge(entity, properties[e % len(properties)], rel["has_property"].id, 0.0, 0.7)
        entities_by_area[area_name] = entities

        routes: list[int] = []
        for r in range(config.routes_per_area):
            lat, lon = _jitter_lat_lon(rng, lat0, lon0, 7_000.0)
            text = f"Synthetic route segment {r} in {area_name}."
            route = add_node("demo-route", f"{area_name}:{r}", "route", lat, lon, 0.0, text, [r / max(1, config.routes_per_area - 1), split / 2.0])
            routes.append(route)
            builder.add_edge(route, area, rel["located_in"].id, 0.0, 0.8)
            builder.add_edge(area, route, rel["contains"].id, 0.0, 0.8)
        for a, b in zip(routes, routes[1:]):
            builder.add_edge(a, b, rel["connected_to"].id, 0.0, 1.0)
            builder.add_edge(b, a, rel["connected_to"].id, 0.0, 1.0)
        routes_by_area[area_name] = routes

        # Observation nodes are sparse latest-record exemplars. The full temporal
        # stream remains in the event arrays and therefore has no frame dimension.
        for o in range(config.observation_nodes_per_area):
            sensor = sensors[o % len(sensors)]
            lat, lon = sensor_coords[sensor]
            prop_id = sensor_property[sensor]
            time_h = float(rng.uniform(0.0, config.max_time_hours))
            text = f"Synthetic observation {o} of {PROPERTY_SPECS[prop_id][0]} in {area_name} at hour {time_h:.2f}."
            obs = add_node("demo-observation", f"{area_name}:{o}", "observation", lat, lon, 0.0, text, [prop_id / len(properties), time_h / config.max_time_hours, split / 2.0])
            target_entity = min(entities, key=lambda x: haversine_m(lat, lon, *entity_coords[x]))
            builder.add_edge(obs, sensor, rel["made_by_sensor"].id, time_h, 1.0)
            builder.add_edge(sensor, obs, rel["made_observation"].id, time_h, 1.0)
            builder.add_edge(obs, target_entity, rel["feature_of_interest"].id, time_h, 0.9)
            builder.add_edge(target_entity, obs, rel["observed_in"].id, time_h, 0.9)

        lineage = add_node("demo-lineage", area_name, "lineage_state", lat0, lon0, 0.0, f"Lineage root for {area_name} synthetic spatial state.", [split / 2.0])
        builder.add_edge(lineage, concepts.get("M075", concepts.get("M119")), rel["governed_by"].id, 0.0, 1.0)

    # Add self loops after all nodes exist; they stabilize isolated ontology nodes.
    for idx in range(len(builder.nodes)):
        builder.add_edge(idx, idx, rel["self"].id, 0.0, 1.0)

    # Training examples use whole-area holdouts to demonstrate spatial rather
    # than random leakage control.
    mechanism_targets = [m for m in ("M088", "M089", "M100", "M118", "M075", "M092") if m in concepts]
    for area_name, _, _, split in AREA_ANCHORS:
        sensors = sensors_by_area[area_name]
        entities = entities_by_area[area_name]
        cells = cells_by_area[area_name]
        for sensor in sensors:
            slat, slon = sensor_coords[sensor]
            # Near relation: closest assets positive, distant assets negative.
            distances = sorted((haversine_m(slat, slon, *entity_coords[e]), e) for e in entities)
            positives = [x for x in distances if x[0] <= 7_000.0][:3]
            negatives = [x for x in reversed(distances) if x[0] >= 9_000.0][:3]
            # Ensure both classes even in compact/random areas.
            if len(positives) < 3:
                positives = distances[:3]
            if len(negatives) < 3:
                negatives = list(reversed(distances[-3:]))
            for distance, entity in positives:
                teacher = 0.55 + 0.44 * _sigmoid((7_500.0 - distance) / 1_400.0)
                builder.add_example(sensor, entity, rel["near"].id, 1.0, teacher, config.max_time_hours, distance, split)
            for distance, entity in negatives:
                teacher = 0.01 + 0.44 * _sigmoid((7_500.0 - distance) / 1_400.0)
                builder.add_example(sensor, entity, rel["near"].id, 0.0, teacher, config.max_time_hours, distance, split)

            # Correct spatial cell plus one deliberately wrong cell keeps this
            # relation balanced while preserving a complete-area spatial holdout.
            correct = cell_assignment[sensor]
            wrong_cell = max((c for c in cells if c != correct), key=lambda c: haversine_m(slat, slon, *cell_coords[c]))
            for cell, label in ((correct, 1.0), (wrong_cell, 0.0)):
                distance = haversine_m(slat, slon, *cell_coords[cell])
                teacher = 0.94 if label else max(0.03, 0.25 * math.exp(-distance / 2_500.0))
                builder.add_example(sensor, cell, rel["located_in"].id, label, teacher, config.max_time_hours, distance, split)

            # Semantic teacher task: the message graph exposes a more general
            # has_property relation, while the student must transfer it to the
            # specific observes predicate.
            correct_prop = sensor_property[sensor]
            wrong_prop = (correct_prop + 3) % len(properties)
            builder.add_example(sensor, properties[correct_prop], rel["observes"].id, 1.0, 0.96, config.max_time_hours, 0.0, split)
            builder.add_example(sensor, properties[wrong_prop], rel["observes"].id, 0.0, 0.04, config.max_time_hours, 0.0, split)

            # UGTS ontology transfer task: map runtime entities to suitable
            # substrate mechanisms and reject unrelated mechanism concepts.
            positive_mid = "M088" if sensor % 2 == 0 else "M118"
            negative_mid = "M184" if "M184" in concepts else mechanism_targets[-1]
            builder.add_example(sensor, concepts[positive_mid], rel["governed_by"].id, 1.0, 0.93, config.max_time_hours, 0.0, split)
            builder.add_example(sensor, concepts[negative_mid], rel["governed_by"].id, 0.0, 0.08, config.max_time_hours, 0.0, split)

    # Attach deterministic fallback teacher vectors last so every node receives
    # an embedding. These are explicitly tagged as synthetic in metadata.
    for idx, text in node_text.items():
        builder.set_teacher_vector(idx, deterministic_teacher_embedding(text, config.teacher_dim))

    indexer = SpatialIndexer(prefer_h3=True)
    builder.metadata.update({
        "generator": "ugts_spatial.demo_data.build_demo_graph",
        "generator_version": "0.1.0",
        "synthetic": True,
        "seed": config.seed,
        "geographic_scope": "Flevoland-like synthetic pilot around six named municipal anchors",
        "spatial_split": {"0": ["Almere", "Lelystad", "Dronten"], "1": ["Emmeloord"], "2": ["Urk", "Zeewolde"]},
        "event_types": list(EVENT_TYPES),
        "max_time_hours": config.max_time_hours,
        "ontology_schema": ontology.schema,
        "catalog_schema": catalog.get("schema"),
        "catalog_count": int(catalog.get("count", len(catalog["mechanisms"]))),
        "teacher_kind": "deterministic_hash_fallback",
        "teacher_dim": config.teacher_dim,
        "spatial_index_preferred": "H3",
        "spatial_index_runtime_backend": indexer.backend,
        "no_frame_padding": True,
        "identity_contract": "stable source address + lineage seed; coordinates are attributes, not identity",
    })
    return builder.build()


def save_demo_graph(output_dir: str | Path, ontology_path: str | Path, catalog_path: str | Path, config: DemoConfig = DemoConfig()) -> Path:
    graph = build_demo_graph(ontology_path, catalog_path, config)
    return graph.save(output_dir)
