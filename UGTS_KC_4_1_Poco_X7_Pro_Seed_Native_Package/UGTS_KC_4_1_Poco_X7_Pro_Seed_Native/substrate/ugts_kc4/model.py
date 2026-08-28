"""Typed records for capture, observations, maps and patches."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Any, Iterable, Mapping, Sequence

from .canonical import content_hash

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def as_vec3(value: Sequence[float], name: str = "vector") -> Vec3:
    if len(value) != 3:
        raise ValueError(f"{name} must have exactly three components")
    return (
        _finite(value[0], f"{name}[0]"),
        _finite(value[1], f"{name}[1]"),
        _finite(value[2], f"{name}[2]"),
    )


def as_quat(value: Sequence[float], name: str = "quaternion") -> Quat:
    if len(value) != 4:
        raise ValueError(f"{name} must have exactly four components")
    q = tuple(_finite(component, f"{name}[{index}]") for index, component in enumerate(value))
    norm = math.sqrt(sum(component * component for component in q))
    if norm <= 1e-12:
        raise ValueError(f"{name} must have non-zero norm")
    return tuple(component / norm for component in q)  # type: ignore[return-value]


def vec_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_scale(a: Vec3, scalar: float) -> Vec3:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def vec_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_norm(a: Vec3) -> float:
    return math.sqrt(vec_dot(a, a))


def vec_distance(a: Vec3, b: Vec3) -> float:
    return vec_norm(vec_sub(a, b))


def vec_normalize(a: Vec3) -> Vec3:
    norm = vec_norm(a)
    if norm <= 1e-12:
        raise ValueError("cannot normalize a zero vector")
    return vec_scale(a, 1.0 / norm)


@dataclass(frozen=True, slots=True)
class Interval:
    lower: float
    upper: float

    def __post_init__(self) -> None:
        lower = _finite(self.lower, "interval.lower")
        upper = _finite(self.upper, "interval.upper")
        if lower > upper:
            raise ValueError("interval lower bound exceeds upper bound")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)

    @property
    def width(self) -> float:
        return self.upper - self.lower

    @property
    def midpoint(self) -> float:
        return (self.lower + self.upper) / 2.0

    def contains(self, value: float) -> bool:
        return self.lower <= value <= self.upper

    def overlaps(self, other: "Interval") -> bool:
        return self.lower <= other.upper and other.lower <= self.upper

    def expand(self, amount: float) -> "Interval":
        amount = _finite(amount, "amount")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        return Interval(self.lower - amount, self.upper + amount)

    def to_dict(self) -> dict[str, float]:
        return {"lower": self.lower, "upper": self.upper}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Interval":
        return cls(float(value["lower"]), float(value["upper"]))


@dataclass(frozen=True, slots=True)
class Pose3D:
    position: Vec3 = (0.0, 0.0, 0.0)
    orientation: Quat = (0.0, 0.0, 0.0, 1.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", as_vec3(self.position, "pose.position"))
        object.__setattr__(self, "orientation", as_quat(self.orientation, "pose.orientation"))

    def to_dict(self) -> dict[str, Any]:
        return {"position": list(self.position), "orientation": list(self.orientation)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Pose3D":
        return cls(tuple(value.get("position", (0, 0, 0))), tuple(value.get("orientation", (0, 0, 0, 1))))


_ALLOWED_SCALE_MODES = {"metric_calibrated", "anchored", "relative", "unknown"}
_ALLOWED_PRIVACY = {"local_only", "redacted_export", "consented_sync", "unrestricted"}


@dataclass(frozen=True, slots=True)
class CaptureProfile:
    id: str
    device_family: str
    camera_model: str
    calibration_hash: str
    scale_mode: str = "unknown"
    units_per_meter: float = 1.0
    coordinate_frame: str = "right-handed-y-up"
    timestamp_unit: str = "seconds"
    model_versions: tuple[tuple[str, str], ...] = ()
    privacy_policy: str = "local_only"
    scale_anchor_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("capture profile id is required")
        if not self.device_family or not self.camera_model:
            raise ValueError("device_family and camera_model are required")
        if self.scale_mode not in _ALLOWED_SCALE_MODES:
            raise ValueError(f"unsupported scale mode: {self.scale_mode}")
        units = _finite(self.units_per_meter, "units_per_meter")
        if units <= 0:
            raise ValueError("units_per_meter must be positive")
        if self.privacy_policy not in _ALLOWED_PRIVACY:
            raise ValueError(f"unsupported privacy policy: {self.privacy_policy}")
        if self.scale_mode == "anchored" and not self.scale_anchor_id:
            raise ValueError("anchored scale mode requires scale_anchor_id")
        versions = tuple(sorted((str(key), str(value)) for key, value in self.model_versions))
        object.__setattr__(self, "units_per_meter", units)
        object.__setattr__(self, "model_versions", versions)

    @property
    def metric_ready(self) -> bool:
        return self.scale_mode in {"metric_calibrated", "anchored"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "device_family": self.device_family,
            "camera_model": self.camera_model,
            "calibration_hash": self.calibration_hash,
            "scale_mode": self.scale_mode,
            "units_per_meter": self.units_per_meter,
            "coordinate_frame": self.coordinate_frame,
            "timestamp_unit": self.timestamp_unit,
            "model_versions": {key: value for key, value in self.model_versions},
            "privacy_policy": self.privacy_policy,
            "scale_anchor_id": self.scale_anchor_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CaptureProfile":
        versions = value.get("model_versions", {})
        if isinstance(versions, Mapping):
            versions_tuple = tuple((str(key), str(val)) for key, val in versions.items())
        else:
            versions_tuple = tuple((str(item[0]), str(item[1])) for item in versions)
        return cls(
            id=str(value["id"]),
            device_family=str(value["device_family"]),
            camera_model=str(value["camera_model"]),
            calibration_hash=str(value.get("calibration_hash", "unverified")),
            scale_mode=str(value.get("scale_mode", "unknown")),
            units_per_meter=float(value.get("units_per_meter", 1.0)),
            coordinate_frame=str(value.get("coordinate_frame", "right-handed-y-up")),
            timestamp_unit=str(value.get("timestamp_unit", "seconds")),
            model_versions=versions_tuple,
            privacy_policy=str(value.get("privacy_policy", "local_only")),
            scale_anchor_id=value.get("scale_anchor_id"),
        )

    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class Uncertainty3D:
    sigma: Vec3 = (0.0, 0.0, 0.0)
    confidence_level: float = 0.95
    max_error: float | None = None

    def __post_init__(self) -> None:
        sigma = as_vec3(self.sigma, "uncertainty.sigma")
        if any(component < 0 for component in sigma):
            raise ValueError("uncertainty sigma components must be non-negative")
        level = _finite(self.confidence_level, "confidence_level")
        if not 0 < level <= 1:
            raise ValueError("confidence_level must be in (0,1]")
        maximum = self.max_error
        if maximum is not None:
            maximum = _finite(maximum, "max_error")
            if maximum < 0:
                raise ValueError("max_error must be non-negative")
        object.__setattr__(self, "sigma", sigma)
        object.__setattr__(self, "confidence_level", level)
        object.__setattr__(self, "max_error", maximum)

    def position_bound(self) -> float:
        if self.max_error is not None:
            return self.max_error
        return 3.0 * math.sqrt(sum(component * component for component in self.sigma))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sigma": list(self.sigma),
            "confidence_level": self.confidence_level,
            "max_error": self.max_error,
            "position_bound": self.position_bound(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Uncertainty3D":
        return cls(
            sigma=tuple(value.get("sigma", (0, 0, 0))),
            confidence_level=float(value.get("confidence_level", 0.95)),
            max_error=value.get("max_error"),
        )


_ALLOWED_DYNAMIC = {"static", "movable", "dynamic", "unknown"}


@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    capture_profile_id: str
    frame_id: str
    timestamp: float
    kind: str
    pose: Pose3D
    uncertainty: Uncertainty3D = Uncertainty3D()
    confidence: float = 1.0
    guard_status: str = "confirmed"
    relation_value: float = 0.0
    numeric_error: float = 0.0
    support_id: str = "world"
    compatibility_policy_id: str = "default"
    compatibility_tags: tuple[str, ...] = ()
    semantic: Mapping[str, Any] = field(default_factory=dict)
    source_model: str = "unknown"
    source_hash: str = "unverified"
    definition_hashes: tuple[str, ...] = ()
    scale_required: bool = False
    dynamic_state: str = "unknown"
    floor_id: str | None = None
    evidence_uri: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.capture_profile_id or not self.frame_id or not self.kind:
            raise ValueError("observation id, profile, frame and kind are required")
        timestamp = _finite(self.timestamp, "observation.timestamp")
        confidence = _finite(self.confidence, "observation.confidence")
        if not 0 <= confidence <= 1:
            raise ValueError("observation confidence must be in [0,1]")
        relation = _finite(self.relation_value, "observation.relation_value")
        error = _finite(self.numeric_error, "observation.numeric_error")
        if error < 0:
            raise ValueError("observation numeric_error must be non-negative")
        if self.dynamic_state not in _ALLOWED_DYNAMIC:
            raise ValueError(f"unsupported dynamic_state: {self.dynamic_state}")
        tags = tuple(sorted({str(tag) for tag in self.compatibility_tags}))
        definitions = tuple(sorted({str(item) for item in self.definition_hashes}))
        semantic = dict(self.semantic)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "relation_value", relation)
        object.__setattr__(self, "numeric_error", error)
        object.__setattr__(self, "compatibility_tags", tags)
        object.__setattr__(self, "definition_hashes", definitions)
        object.__setattr__(self, "semantic", semantic)

    @property
    def relation_interval(self) -> Interval:
        return Interval(self.relation_value - self.numeric_error, self.relation_value + self.numeric_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capture_profile_id": self.capture_profile_id,
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "pose": self.pose.to_dict(),
            "uncertainty": self.uncertainty.to_dict(),
            "confidence": self.confidence,
            "guard_status": self.guard_status,
            "relation_value": self.relation_value,
            "numeric_error": self.numeric_error,
            "relation_interval": self.relation_interval.to_dict(),
            "support_id": self.support_id,
            "compatibility_policy_id": self.compatibility_policy_id,
            "compatibility_tags": list(self.compatibility_tags),
            "semantic": dict(self.semantic),
            "source_model": self.source_model,
            "source_hash": self.source_hash,
            "definition_hashes": list(self.definition_hashes),
            "scale_required": self.scale_required,
            "dynamic_state": self.dynamic_state,
            "floor_id": self.floor_id,
            "evidence_uri": self.evidence_uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Observation":
        return cls(
            id=str(value["id"]),
            capture_profile_id=str(value["capture_profile_id"]),
            frame_id=str(value["frame_id"]),
            timestamp=float(value["timestamp"]),
            kind=str(value["kind"]),
            pose=Pose3D.from_dict(value.get("pose", {})),
            uncertainty=Uncertainty3D.from_dict(value.get("uncertainty", {})),
            confidence=float(value.get("confidence", 1.0)),
            guard_status=str(value.get("guard_status", "confirmed")),
            relation_value=float(value.get("relation_value", 0.0)),
            numeric_error=float(value.get("numeric_error", 0.0)),
            support_id=str(value.get("support_id", "world")),
            compatibility_policy_id=str(value.get("compatibility_policy_id", "default")),
            compatibility_tags=tuple(value.get("compatibility_tags", ())),
            semantic=dict(value.get("semantic", {})),
            source_model=str(value.get("source_model", "unknown")),
            source_hash=str(value.get("source_hash", "unverified")),
            definition_hashes=tuple(value.get("definition_hashes", ())),
            scale_required=bool(value.get("scale_required", False)),
            dynamic_state=str(value.get("dynamic_state", "unknown")),
            floor_id=value.get("floor_id"),
            evidence_uri=value.get("evidence_uri"),
        )


@dataclass(frozen=True, slots=True)
class MapNode:
    id: str
    kind: str
    pose: Pose3D
    uncertainty: Uncertainty3D = Uncertainty3D()
    semantic: Mapping[str, Any] = field(default_factory=dict)
    state: Mapping[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    lineage: tuple[str, ...] = ()
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.id or not self.kind:
            raise ValueError("map node id and kind are required")
        if int(self.revision) < 0:
            raise ValueError("node revision must be non-negative")
        object.__setattr__(self, "semantic", dict(self.semantic))
        object.__setattr__(self, "state", dict(self.state))
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(str(x) for x in self.evidence_ids)))
        object.__setattr__(self, "lineage", tuple(str(x) for x in self.lineage))
        object.__setattr__(self, "revision", int(self.revision))

    def with_revision(self, *, evidence_id: str | None = None, lineage_label: str | None = None, **changes: Any) -> "MapNode":
        evidence = self.evidence_ids + ((evidence_id,) if evidence_id and evidence_id not in self.evidence_ids else ())
        lineage = self.lineage + ((lineage_label,) if lineage_label else ())
        return replace(self, revision=self.revision + 1, evidence_ids=evidence, lineage=lineage, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "pose": self.pose.to_dict(),
            "uncertainty": self.uncertainty.to_dict(),
            "semantic": dict(self.semantic),
            "state": dict(self.state),
            "evidence_ids": list(self.evidence_ids),
            "lineage": list(self.lineage),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MapNode":
        return cls(
            id=str(value["id"]),
            kind=str(value["kind"]),
            pose=Pose3D.from_dict(value.get("pose", {})),
            uncertainty=Uncertainty3D.from_dict(value.get("uncertainty", {})),
            semantic=dict(value.get("semantic", {})),
            state=dict(value.get("state", {})),
            evidence_ids=tuple(value.get("evidence_ids", ())),
            lineage=tuple(value.get("lineage", ())),
            revision=int(value.get("revision", 0)),
        )


@dataclass(frozen=True, slots=True)
class MapEdge:
    id: str
    source: str
    target: str
    kind: str
    directed: bool = False
    state: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, float] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    lineage: tuple[str, ...] = ()
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.id or not self.source or not self.target or not self.kind:
            raise ValueError("map edge id, source, target and kind are required")
        if self.source == self.target:
            raise ValueError("map edge cannot connect a node to itself")
        if int(self.revision) < 0:
            raise ValueError("edge revision must be non-negative")
        metrics = {str(key): _finite(value, f"edge metric {key}") for key, value in self.metrics.items()}
        object.__setattr__(self, "state", dict(self.state))
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(str(x) for x in self.evidence_ids)))
        object.__setattr__(self, "lineage", tuple(str(x) for x in self.lineage))
        object.__setattr__(self, "revision", int(self.revision))

    def with_revision(self, *, evidence_id: str | None = None, lineage_label: str | None = None, **changes: Any) -> "MapEdge":
        evidence = self.evidence_ids + ((evidence_id,) if evidence_id and evidence_id not in self.evidence_ids else ())
        lineage = self.lineage + ((lineage_label,) if lineage_label else ())
        return replace(self, revision=self.revision + 1, evidence_ids=evidence, lineage=lineage, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "directed": self.directed,
            "state": dict(self.state),
            "metrics": dict(self.metrics),
            "evidence_ids": list(self.evidence_ids),
            "lineage": list(self.lineage),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MapEdge":
        return cls(
            id=str(value["id"]),
            source=str(value["source"]),
            target=str(value["target"]),
            kind=str(value["kind"]),
            directed=bool(value.get("directed", False)),
            state=dict(value.get("state", {})),
            metrics={str(key): float(val) for key, val in value.get("metrics", {}).items()},
            evidence_ids=tuple(value.get("evidence_ids", ())),
            lineage=tuple(value.get("lineage", ())),
            revision=int(value.get("revision", 0)),
        )


_ALLOWED_PATCHES = {
    "upsert_node", "remove_node", "update_node_state", "update_node_pose",
    "append_node_evidence", "upsert_edge", "remove_edge", "update_edge_state",
    "update_edge_metrics", "append_edge_evidence",
}


@dataclass(frozen=True, slots=True)
class MapPatch:
    operation: str
    target_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.operation not in _ALLOWED_PATCHES:
            raise ValueError(f"unsupported map patch operation: {self.operation}")
        if not self.target_id:
            raise ValueError("map patch target_id is required")
        object.__setattr__(self, "payload", dict(self.payload))

    def conflict_keys(self) -> tuple[str, ...]:
        if self.operation in {"update_node_state", "update_edge_state", "update_edge_metrics"}:
            return tuple(f"{self.target_id}:{self.operation}:{key}" for key in sorted(self.payload))
        if self.operation in {"append_node_evidence", "append_edge_evidence"}:
            return ()
        return (f"{self.target_id}:{self.operation}",)

    def to_dict(self) -> dict[str, Any]:
        return {"operation": self.operation, "target_id": self.target_id, "payload": dict(self.payload)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MapPatch":
        return cls(str(value["operation"]), str(value["target_id"]), dict(value.get("payload", {})))


@dataclass
class MapState:
    nodes: dict[str, MapNode] = field(default_factory=dict)
    edges: dict[str, MapEdge] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.nodes = dict(self.nodes)
        self.edges = dict(self.edges)
        self.metadata = dict(self.metadata)
        self.validate()

    def validate(self) -> None:
        for key, node in self.nodes.items():
            if key != node.id:
                raise ValueError(f"node dictionary key mismatch: {key} != {node.id}")
        for key, edge in self.edges.items():
            if key != edge.id:
                raise ValueError(f"edge dictionary key mismatch: {key} != {edge.id}")
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ValueError(f"edge {edge.id} references an unknown node")

    def clone(self) -> "MapState":
        return MapState(dict(self.nodes), dict(self.edges), dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ugts-kc-spatial-map-state-4.0",
            "metadata": dict(self.metadata),
            "nodes": [self.nodes[key].to_dict() for key in sorted(self.nodes)],
            "edges": [self.edges[key].to_dict() for key in sorted(self.edges)],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MapState":
        nodes = {item["id"]: MapNode.from_dict(item) for item in value.get("nodes", [])}
        edges = {item["id"]: MapEdge.from_dict(item) for item in value.get("edges", [])}
        return cls(nodes, edges, dict(value.get("metadata", {})))

    def state_hash(self) -> str:
        return content_hash(self.to_dict())

    def node_bounds(self) -> tuple[Vec3, Vec3] | None:
        if not self.nodes:
            return None
        points = [node.pose.position for node in self.nodes.values()]
        minimum = tuple(min(point[index] for point in points) for index in range(3))
        maximum = tuple(max(point[index] for point in points) for index in range(3))
        return as_vec3(minimum), as_vec3(maximum)

    def route_edges(self) -> list[MapEdge]:
        return [self.edges[key] for key in sorted(self.edges) if self.edges[key].kind == "route"]

    def evidence_ids(self) -> tuple[str, ...]:
        values: list[str] = []
        for node in self.nodes.values():
            values.extend(node.evidence_ids)
        for edge in self.edges.values():
            values.extend(edge.evidence_ids)
        return tuple(dict.fromkeys(values))


def map_state_from(nodes: Iterable[MapNode], edges: Iterable[MapEdge] = (), **metadata: Any) -> MapState:
    node_list = list(nodes)
    edge_list = list(edges)
    node_map = {node.id: node for node in node_list}
    edge_map = {edge.id: edge for edge in edge_list}
    if len(node_map) != len(node_list):
        raise ValueError("duplicate node IDs")
    if len(edge_map) != len(edge_list):
        raise ValueError("duplicate edge IDs")
    return MapState(node_map, edge_map, metadata)
