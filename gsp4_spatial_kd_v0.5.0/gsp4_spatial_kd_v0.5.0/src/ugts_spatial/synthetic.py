from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np

from .builder import GraphBuilder
from .geocell import encode_morton_cell, haversine_m
from .graph import GraphPackage
from .novelty import NoveltyLog, NoveltyRecord
from .schema import NodeType, NoveltyOp, RelationType


@dataclass(frozen=True)
class SyntheticResult:
    graph: GraphPackage
    observation_counts: tuple[int, ...]
    novelty_records: int


_SENSOR_KIND = (
    ("air", "air-quality sensor", "concept:no2", 0.68),
    ("water", "water-level sensor", "concept:water_level", 0.72),
    ("traffic", "traffic-flow sensor", "concept:traffic_flow", 0.76),
)


def generate_flevoland_pilot(
    *,
    seed: int = 20260710,
    time_steps: int = 12,
    entities_per_cell: int = 6,
    morton_resolution: int = 14,
) -> SyntheticResult:
    """Create a small variable-length Flevoland-like semantic event graph.

    The coordinates and readings are synthetic. The graph is intentionally
    shaped like a realistic pilot: persistent places/sensors, irregular timed
    observations, verified threshold events, ontology nodes, spatial cells and
    lineage state.
    """
    if time_steps < 3:
        raise ValueError("time_steps must be at least 3")
    if entities_per_cell < 3:
        raise ValueError("entities_per_cell must be at least 3")
    rng = np.random.default_rng(seed)
    center_lat, center_lon = 52.52, 5.47
    builder = GraphBuilder(
        name="synthetic-flevoland-variable-event-pilot",
        source="procedurally generated; no external data",
        morton_resolution=morton_resolution,
        input_dim=32,
        teacher_dim=64,
        metadata={
            "generator": "ugts_spatial.synthetic.generate_flevoland_pilot",
            "seed": seed,
            "time_steps": time_steps,
            "coordinates_are_synthetic": True,
            "split_policy": "spatial-cell holdout",
        },
    )

    concepts = {
        "spatial_entity": "persistent geospatial entity",
        "road": "road and transport link",
        "water": "water body or hydraulic asset",
        "facility": "public facility or point of interest",
        "air_sensor": "air-quality monitoring sensor",
        "water_sensor": "water-level monitoring sensor",
        "traffic_sensor": "traffic-flow monitoring sensor",
        "no2": "nitrogen dioxide concentration observation property",
        "water_level": "water level observation property",
        "traffic_flow": "traffic flow observation property",
        "threshold_event": "verified spatial threshold event",
    }
    for name, text in concepts.items():
        builder.add_node(
            f"concept:{name}",
            NodeType.CONCEPT,
            f"ontology concept: {text}",
            latitude=center_lat,
            longitude=center_lon,
            split=0,
            active=1.0,
        )

    # A 3x3 cell lattice. Holdouts are entire cells, preventing ordinary
    # random-row leakage between nearby observations.
    cell_indices: dict[tuple[int, int], int] = {}
    cell_splits: dict[tuple[int, int], int] = {}
    test_cells = {(2, 0), (2, 2)}
    validation_cells = {(1, 2), (0, 2)}
    for iy in range(3):
        for ix in range(3):
            lat = center_lat + (iy - 1) * 0.105
            lon = center_lon + (ix - 1) * 0.155
            split = 2 if (ix, iy) in test_cells else 1 if (ix, iy) in validation_cells else 0
            cell_splits[(ix, iy)] = split
            cell_id = encode_morton_cell(lat, lon, morton_resolution)
            cell_indices[(ix, iy)] = builder.add_node(
                f"cell:{ix}:{iy}",
                NodeType.SPATIAL_CELL,
                f"hierarchical spatial support cell x={ix} y={iy} in synthetic Flevoland pilot",
                latitude=lat,
                longitude=lon,
                cell_id=cell_id,
                split=split,
                metadata={"grid_x": ix, "grid_y": iy},
            )
    for iy in range(3):
        for ix in range(3):
            for dx, dy in ((1, 0), (0, 1)):
                other = (ix + dx, iy + dy)
                if other in cell_indices:
                    builder.add_edge(
                        cell_indices[(ix, iy)],
                        cell_indices[other],
                        RelationType.ADJACENT_TO,
                        symmetric=True,
                    )

    entity_rows: dict[tuple[int, int], list[int]] = {}
    road_rows: dict[tuple[int, int], list[int]] = {}
    sensor_rows: list[dict[str, Any]] = []
    for iy in range(3):
        for ix in range(3):
            cell = cell_indices[(ix, iy)]
            split = cell_splits[(ix, iy)]
            base_lat = builder.nodes[cell].latitude
            base_lon = builder.nodes[cell].longitude
            entities: list[int] = []
            roads: list[int] = []
            for j in range(entities_per_cell):
                lat = base_lat + float(rng.normal(0.0, 0.018))
                lon = base_lon + float(rng.normal(0.0, 0.027))
                kind = ("road", "water", "facility")[j % 3]
                label = {
                    "road": "regional road segment",
                    "water": "canal or water-management asset",
                    "facility": "public facility",
                }[kind]
                row = builder.add_node(
                    f"entity:{ix}:{iy}:{j}",
                    NodeType.SPATIAL_ENTITY,
                    f"{label} {j} in cell {ix},{iy}; persistent geospatial entity",
                    latitude=lat,
                    longitude=lon,
                    elevation=float(rng.uniform(-4.0, 8.0)),
                    split=split,
                    value=(j + 1) / entities_per_cell,
                    metadata={"kind": kind},
                )
                entities.append(row)
                if kind == "road":
                    roads.append(row)
                builder.add_edge(row, cell, RelationType.LOCATED_IN)
                builder.add_edge(row, f"concept:{kind}", RelationType.INSTANCE_OF)
                builder.add_edge(row, "concept:spatial_entity", RelationType.HAS_PROPERTY)
            entity_rows[(ix, iy)] = entities
            road_rows[(ix, iy)] = roads
            for a, b in zip(roads, roads[1:]):
                builder.add_edge(a, b, RelationType.CONNECTED_TO, symmetric=True)

            for sensor_slot, (short, sensor_label, property_key, threshold) in enumerate(_SENSOR_KIND):
                anchor = entities[sensor_slot % len(entities)]
                lat = builder.nodes[anchor].latitude + float(rng.normal(0.0, 0.004))
                lon = builder.nodes[anchor].longitude + float(rng.normal(0.0, 0.006))
                sensor = builder.add_node(
                    f"sensor:{ix}:{iy}:{short}",
                    NodeType.SENSOR,
                    f"{sensor_label} in spatial cell {ix},{iy}; observes {property_key.split(':')[1]}",
                    latitude=lat,
                    longitude=lon,
                    elevation=builder.nodes[anchor].elevation + 1.5,
                    split=split,
                    value=threshold,
                    metadata={"sensor_kind": short, "threshold": threshold},
                )
                lineage = builder.add_node(
                    f"lineage:{ix}:{iy}:{short}",
                    NodeType.LINEAGE_STATE,
                    f"persistent lineage state for {sensor_label} in cell {ix},{iy}",
                    latitude=lat,
                    longitude=lon,
                    split=split,
                    lineage_depth=1.0,
                )
                concept_sensor = f"concept:{short}_sensor"
                builder.add_edge(sensor, cell, RelationType.LOCATED_IN)
                builder.add_edge(sensor, concept_sensor, RelationType.INSTANCE_OF)
                builder.add_edge(sensor, property_key, RelationType.OBSERVES)
                builder.add_edge(sensor, anchor, RelationType.NEAR, symmetric=True)
                builder.add_edge(sensor, anchor, RelationType.SAME_CELL, symmetric=True)
                builder.add_edge(sensor, lineage, RelationType.COMPATIBLE_WITH)
                sensor_rows.append(
                    {
                        "sensor": sensor,
                        "lineage": lineage,
                        "cell": cell,
                        "anchor": anchor,
                        "kind": short,
                        "property": property_key,
                        "threshold": threshold,
                        "split": split,
                        "previous_observation": None,
                        "previous_event": None,
                        "bias": float(rng.normal(0.0, 0.08)),
                    }
                )

            # Local broad-phase connections. They deliberately stay sparse.
            local_nodes = entities + [row["sensor"] for row in sensor_rows if row["cell"] == cell]
            for a_pos, a in enumerate(local_nodes):
                distances = []
                for b in local_nodes[a_pos + 1 :]:
                    distance = haversine_m(
                        builder.nodes[a].latitude,
                        builder.nodes[a].longitude,
                        builder.nodes[b].latitude,
                        builder.nodes[b].longitude,
                    )
                    distances.append((distance, b))
                for distance, b in sorted(distances)[:2]:
                    weight = float(math.exp(-distance / 2500.0))
                    builder.add_edge(a, b, RelationType.NEAR, weight=weight, symmetric=True)

    base_time = 1_704_067_200.0  # deterministic timestamp used only as an address
    observation_counts: list[int] = []
    novelty_specs: list[dict[str, Any]] = []
    for step in range(time_steps):
        active_count = 0
        seasonal = 0.14 * math.sin(2.0 * math.pi * step / time_steps)
        for ordinal, sensor_info in enumerate(sensor_rows):
            # Deliberately irregular: activity changes each time window and by
            # sensor kind. There is no fixed tensor row count per frame.
            activity_probability = 0.38 + 0.18 * ((step + ordinal) % 4) / 3.0
            if rng.random() > activity_probability:
                continue
            active_count += 1
            sensor = int(sensor_info["sensor"])
            kind = str(sensor_info["kind"])
            threshold = float(sensor_info["threshold"])
            kind_phase = {"air": 0.0, "water": 0.9, "traffic": 1.8}[kind]
            value = (
                0.55
                + seasonal
                + 0.11 * math.sin(0.75 * step + kind_phase)
                + float(sensor_info["bias"])
                + float(rng.normal(0.0, 0.055))
            )
            value = float(np.clip(value, 0.0, 1.2))
            timestamp = base_time + step * 900.0 + ordinal * 0.01
            observation = builder.add_node(
                f"observation:{step}:{ordinal}",
                NodeType.OBSERVATION,
                f"{kind} observation value {value:.4f} at irregular time window {step}",
                latitude=builder.nodes[sensor].latitude,
                longitude=builder.nodes[sensor].longitude,
                elevation=builder.nodes[sensor].elevation,
                timestamp=timestamp,
                cell_id=builder.nodes[sensor].cell_id,
                split=int(sensor_info["split"]),
                value=value,
                confidence=float(np.clip(0.86 + rng.normal(0.0, 0.05), 0.55, 0.99)),
                lineage_depth=float(step + 1),
                metadata={"sensor_kind": kind, "time_step": step},
            )
            builder.add_edge(observation, sensor, RelationType.MADE_BY_SENSOR, timestamp=timestamp)
            builder.add_edge(observation, sensor_info["property"], RelationType.HAS_PROPERTY, timestamp=timestamp)
            builder.add_edge(observation, sensor_info["cell"], RelationType.LOCATED_IN, timestamp=timestamp)
            builder.add_edge(observation, sensor_info["anchor"], RelationType.AFFECTS, timestamp=timestamp, weight=value)
            builder.add_edge(observation, sensor, RelationType.DERIVED_FROM, timestamp=timestamp, weight=value)
            previous_observation = sensor_info["previous_observation"]
            if previous_observation is not None:
                builder.add_edge(
                    observation,
                    int(previous_observation),
                    RelationType.DESCENDS_FROM,
                    timestamp=timestamp,
                    weight=1.0,
                )
                builder.add_edge(
                    observation,
                    int(previous_observation),
                    RelationType.SUPERSEDES,
                    timestamp=timestamp,
                    weight=1.0,
                )
            sensor_info["previous_observation"] = observation
            novelty_specs.append(
                {
                    "timestamp": timestamp,
                    "op": NoveltyOp.OBSERVATION,
                    "relation": RelationType.MADE_BY_SENSOR,
                    "source": observation,
                    "target": sensor,
                    "value": value,
                    "confidence": builder.nodes[observation].confidence,
                }
            )

            # Create an explicit verified event only when a deterministic scalar
            # threshold is crossed. The GNN learns semantics; this gate remains
            # authoritative and inspectable.
            guard_value = value - threshold
            if guard_value >= 0.0:
                event = builder.add_node(
                    f"event:{step}:{ordinal}",
                    NodeType.EVENT,
                    f"verified {kind} threshold event; guard value {guard_value:.4f}",
                    latitude=builder.nodes[sensor].latitude,
                    longitude=builder.nodes[sensor].longitude,
                    elevation=builder.nodes[sensor].elevation,
                    timestamp=timestamp,
                    cell_id=builder.nodes[sensor].cell_id,
                    split=int(sensor_info["split"]),
                    value=guard_value,
                    confidence=float(np.clip(0.75 + 0.3 * guard_value, 0.0, 1.0)),
                    lineage_depth=float(step + 1),
                    metadata={"guard_threshold": threshold, "sensor_kind": kind},
                )
                builder.add_edge(event, sensor_info["anchor"], RelationType.CROSSED_GUARD, timestamp=timestamp, weight=guard_value)
                builder.add_edge(event, sensor_info["cell"], RelationType.AFFECTS, timestamp=timestamp, weight=guard_value)
                builder.add_edge(event, "concept:threshold_event", RelationType.INSTANCE_OF, timestamp=timestamp)
                builder.add_edge(event, observation, RelationType.DERIVED_FROM, timestamp=timestamp)
                builder.add_edge(event, sensor_info["lineage"], RelationType.TRANSITIONED_TO, timestamp=timestamp)
                previous_event = sensor_info["previous_event"]
                if previous_event is not None:
                    builder.add_edge(event, int(previous_event), RelationType.DESCENDS_FROM, timestamp=timestamp)
                sensor_info["previous_event"] = event
                novelty_specs.append(
                    {
                        "timestamp": timestamp,
                        "op": NoveltyOp.VERIFIED_EVENT,
                        "relation": RelationType.CROSSED_GUARD,
                        "source": event,
                        "target": int(sensor_info["anchor"]),
                        "value": guard_value,
                        "confidence": builder.nodes[event].confidence,
                    }
                )
        observation_counts.append(active_count)

    graph = builder.build()
    graph.metadata["observation_counts_per_window"] = observation_counts
    graph.metadata["observation_min_per_window"] = min(observation_counts)
    graph.metadata["observation_max_per_window"] = max(observation_counts)
    graph.metadata["novelty_specs"] = len(novelty_specs)
    # Rebuild once after metadata mutation to keep the schema descriptor stable;
    # metadata content is data provenance and not part of the ABI hash.
    graph.validate()
    graph.metadata["_novelty_specs_internal"] = novelty_specs
    return SyntheticResult(graph, tuple(observation_counts), len(novelty_specs))


def write_flevoland_pilot(
    graph_path: str | Path,
    novelty_path: str | Path,
    *,
    seed: int = 20260710,
    time_steps: int = 12,
    entities_per_cell: int = 6,
    overwrite: bool = True,
) -> SyntheticResult:
    result = generate_flevoland_pilot(
        seed=seed,
        time_steps=time_steps,
        entities_per_cell=entities_per_cell,
    )
    specs = result.graph.metadata.pop("_novelty_specs_internal")
    result.graph.save(graph_path)
    log = NoveltyLog(novelty_path)
    log.create(overwrite=overwrite)
    for sequence, spec in enumerate(specs):
        log.append(
            NoveltyRecord(
                sequence=sequence,
                timestamp=float(spec["timestamp"]),
                op=int(spec["op"]),
                relation=int(spec["relation"]),
                flags=0,
                source=int(result.graph.node_id[int(spec["source"])]),
                target=int(result.graph.node_id[int(spec["target"])]),
                value=float(spec["value"]),
                confidence=float(spec["confidence"]),
            )
        )
    log.validate()
    return result
