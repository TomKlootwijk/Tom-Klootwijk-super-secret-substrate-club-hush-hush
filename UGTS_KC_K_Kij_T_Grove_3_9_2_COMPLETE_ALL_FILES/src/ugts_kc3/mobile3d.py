"""UGTS-KC 3.9.1 mobile-3D records, device profiles and deterministic game oracle.

The JSON model is authoritative for authoring and validation.  Native Android rendering is a
separate downstream adapter implemented by :mod:`ugts_kc3.androidexport`.
"""
from __future__ import annotations

from bisect import bisect_left
from collections.abc import MutableMapping
from dataclasses import dataclass, field
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .animation3d import (
    ANIMATION_LIBRARY_METADATA_KEY,
    ANIMATION_METADATA_KEY,
    TransformAnimationError,
    attach_transform_animations_3d,
    collect_transform_animation_spec,
    transform_animation_from_metadata,
    transform_animation_library_from_metadata,
)
from .geometry import Mesh
from .hierarchy3d import (
    TransformHierarchySystem3D,
    attach_transform_hierarchy_3d,
    build_hierarchy3d,
    hierarchy_issues3d,
    is_uniform_positive_scale_3d,
)
from .materials import PBRMaterial
from .packed_kinematics import (
    PackedKinematicComponent,
    PackedKinematicCodec,
    PolarLookupTable,
    PolarMovementComponent3D,
    pack_ecs_document,
    polar_movement_from_component,
    replace_polar_movement,
    unpack_ecs_document,
)
from .polarpack import (
    PolarPackError,
    PolarProjectSpec,
    collect_polar_project_spec,
    quantized_profile_lut,
)
from .polar_population import (
    PolarPopulationError,
    collect_polar_population_project_spec,
)
from .math3d import (
    EPS, add, compose_trs, cross, dot, norm, normalize, quat_from_axis_angle,
    quat_mul, quat_normalize, scale as vscale, sub,
)
from .scene import Asset, Scene, SceneMetadata, SceneNode
from .scatter import (
    ScatterError,
    collect_scatter_project_spec,
    f32,
    scatter_instance_id,
    scatter_instances,
)
from .visual_graph import VisualGraph, attach_graph, run_ready_batch

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]
Color3 = tuple[float, float, float]
Color4 = tuple[float, float, float, float]
MOBILE3D_SCHEMA = "ugts-kc-mobile-3d-project-3.9.1"
MAX_TRIGGER_SENSORS = 4096

TAG_PLAYER = 1 << 0
TAG_COLLECTIBLE = 1 << 1
TAG_GOAL = 1 << 2
TAG_DECORATIVE = 1 << 3
TAG_HAZARD = 1 << 4
TAG_MAP = {
    "player": TAG_PLAYER,
    "collectible": TAG_COLLECTIBLE,
    "goal": TAG_GOAL,
    "decorative": TAG_DECORATIVE,
    "hazard": TAG_HAZARD,
}

_SAVED_SCENE_METADATA_KEYS = frozenset({"saved_scenes", "saved_scene_instances"})


def _materialize_runtime_project(project: Any) -> Any:
    """Return the flat runtime view when linked Saved Scenes are authored."""

    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, Mapping) or not any(
        key in metadata for key in _SAVED_SCENE_METADATA_KEYS
    ):
        return project
    # Local by design: saved_scene builds Mobile3DProject records and therefore
    # must not become an import-time dependency of the core project model.
    from .saved_scene import materialize_saved_scenes

    return materialize_saved_scenes(project)


def visual_graphs_from_metadata(metadata: Mapping[str, Any]) -> tuple[VisualGraph, ...]:
    """Read the canonical visual-graph collection used by desktop and Android 3D."""
    raw = metadata.get("visual_graphs", ())
    if isinstance(raw, Mapping):
        if "nodes" in raw or "schema" in raw:
            items = [raw]
        else:
            items = []
            for graph_id, value in sorted(raw.items(), key=lambda pair: str(pair[0])):
                if not isinstance(value, Mapping):
                    raise TypeError(f"visual graph {graph_id!r} must be an object")
                item = dict(value)
                item.setdefault("id", str(graph_id))
                items.append(item)
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise TypeError("metadata.visual_graphs must be a list or object")
    graphs = tuple(
        item if isinstance(item, VisualGraph) else VisualGraph.from_dict(item)
        for item in items
    )
    ids = [graph.id for graph in graphs]
    if len(ids) != len(set(ids)):
        raise ValueError("project contains duplicate visual graph ids")
    return tuple(sorted(graphs, key=lambda graph: graph.id))


def visual_graph_binding_ids(raw: Any, label: str = "visual graph binding") -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = (raw,)
    elif isinstance(raw, (list, tuple)) and all(isinstance(item, str) for item in raw):
        values = tuple(raw)
    else:
        raise TypeError(f"{label} must be text or a list of text graph ids")
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{label} cannot contain an empty graph id")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} cannot contain the same graph id more than once")
    return normalized


_SCATTER_ENTITY_MUTATIONS = {
    "action.set_component": "Change Object Setting",
    "action.apply_force": "Push an Object",
    "action.set_active": "Show or Hide Object",
    "action.despawn": "Remove Object",
}
_OWNER_ENTITY_EVENTS = frozenset(
    {
        "event.ready",
        "event.tick",
        "event.input_pressed",
        "event.trigger_enter",
        "event.trigger_exit",
    }
)


def _graph_mutation_targets(
    graph: VisualGraph,
    action_node: Any,
    owners: set[str | None],
) -> set[str] | None:
    """Resolve fixed mutation targets; ``None`` means runtime-selected.

    Populate Area instances live in an immutable native instance buffer.  A
    target is therefore considered safe only when graph metadata proves that
    it is a non-populated scene node (or the non-entity world binding).  This
    deliberately treats state/component-derived entity ids as dynamic.
    """

    incoming = next(
        (
            link
            for link in graph.links
            if link.target_node == action_node.id and link.target_port == "entity"
        ),
        None,
    )
    if incoming is None:
        literal = action_node.properties.get("entity")
        if literal in (None, ""):
            return {owner for owner in owners if owner is not None}
        return {str(literal)}

    source = next((node for node in graph.nodes if node.id == incoming.source_node), None)
    if source is None:
        return None
    if source.type == "value.constant" and incoming.source_port == "value":
        value = source.properties.get("value", 0)
        return {value} if isinstance(value, str) else None
    if source.type in _OWNER_ENTITY_EVENTS and incoming.source_port == "entity":
        return {owner for owner in owners if owner is not None}
    return None


def _scatter_graph_mutation_messages(
    graphs: Sequence[VisualGraph],
    graph_owners: Mapping[str, set[str | None]],
    prototype_ids: set[str],
) -> tuple[tuple[str, str], ...]:
    """Return child-friendly errors for graph writes into frozen populations."""

    messages: list[tuple[str, str]] = []
    for graph in graphs:
        owners = graph_owners.get(graph.id, set())
        if not owners:
            # Stored but unbound graphs cannot execute.
            continue
        for node in graph.nodes:
            friendly_action = _SCATTER_ENTITY_MUTATIONS.get(node.type)
            if friendly_action is None:
                continue
            targets = _graph_mutation_targets(graph, node, owners)
            path = f"metadata.visual_graphs.{graph.id}.nodes.{node.id}"
            if targets is None:
                names = ", ".join(repr(value) for value in sorted(prototype_ids))
                object_word = "object" if len(prototype_ids) == 1 else "objects"
                messages.append(
                    (
                        path,
                        f"Logic Blocks graph {graph.id!r} uses {friendly_action} with an "
                        f"object chosen while the game runs. It could change Populate Area "
                        f"{object_word} {names}, whose phone-rendered copies are frozen. Choose "
                        "a specific normal object for this block, or remove Populate Area first.",
                    )
                )
                continue
            unsafe = sorted(targets & prototype_ids)
            if unsafe:
                names = ", ".join(repr(value) for value in unsafe)
                object_word = "object" if len(unsafe) == 1 else "objects"
                copy_owner = "Its" if len(unsafe) == 1 else "Their"
                messages.append(
                    (
                        path,
                        f"Logic Blocks graph {graph.id!r} uses {friendly_action} on Populate "
                        f"Area {object_word} {names}. {copy_owner} phone-rendered copies are frozen, so "
                        "choose a normal object or remove Populate Area first.",
                    )
                )
    return tuple(messages)


def _graph_known_input(
    graph: VisualGraph,
    action_node: Any,
    port_name: str,
    default: Any,
) -> tuple[bool, Any]:
    """Resolve one saved/constant graph input without pretending runtime data is fixed."""

    incoming = next(
        (
            link
            for link in graph.links
            if link.target_node == action_node.id and link.target_port == port_name
        ),
        None,
    )
    if incoming is None:
        return True, action_node.properties.get(port_name, default)
    source = next(
        (node for node in graph.nodes if node.id == incoming.source_node),
        None,
    )
    if (
        source is not None
        and source.type == "value.constant"
        and incoming.source_port == "value"
    ):
        return True, source.properties.get("value", 0)
    return False, None


def _packed_polar_write_is_safe(component: str, field: str) -> bool:
    """Whether one generic write leaves packed-polar-owned axes untouched."""

    component = str(component)
    field = str(field)
    if component == "transform":
        return field in {
            "position.y",
            "position.1",
            "translation.y",
            "translation.1",
            "scale",
            "scale.x",
            "scale.y",
            "scale.z",
            "scale.0",
            "scale.1",
            "scale.2",
        }
    if component == "velocity":
        return field in {"y", "1"}
    if component in {"angular_velocity", "body"}:
        return False
    return True


def _packed_polar_graph_write_messages(
    graphs: Sequence[VisualGraph],
    graph_owners: Mapping[str, set[str | None]],
    prototype_ids: set[str],
) -> tuple[tuple[str, str], ...]:
    """Reject generic graph writes that compete with packed polar authority."""

    messages: list[tuple[str, str]] = []
    controlled_components = {"transform", "velocity", "angular_velocity", "body"}
    for graph in graphs:
        owners = graph_owners.get(graph.id, set())
        if not owners:
            continue
        for graph_node in graph.nodes:
            if graph_node.type != "action.set_component":
                continue
            targets = _graph_mutation_targets(graph, graph_node, owners)
            affected = prototype_ids if targets is None else prototype_ids & targets
            if not affected:
                continue
            component_known, component = _graph_known_input(
                graph, graph_node, "component", "transform"
            )
            field_known, field = _graph_known_input(
                graph, graph_node, "field", "position"
            )
            if component_known:
                component_name = str(component)
                if component_name not in controlled_components:
                    continue
                if field_known and _packed_polar_write_is_safe(
                    component_name, str(field)
                ):
                    continue
            path = f"metadata.visual_graphs.{graph.id}.nodes.{graph_node.id}"
            names = ", ".join(repr(value) for value in sorted(affected))
            target_text = (
                f"Movement Pattern object {names}"
                if len(affected) == 1
                else f"Movement Pattern objects {names}"
            )
            field_text = (
                "a setting chosen while the game runs"
                if not component_known or not field_known
                else f"{component}.{field or '<whole>'}"
            )
            messages.append(
                (
                    path,
                    f"Logic Blocks graph {graph.id!r} tries to change {field_text} on "
                    f"{target_text}. Movement Pattern owns X/Z position, facing rotation, "
                    "X/Z velocity, and spin. Change Polar Movement fields instead; only "
                    "Y position, Y velocity, and Scale remain ordinary settings.",
                )
            )
    return tuple(messages)


def _hierarchy_graph_scale_messages(
    graphs: Sequence[VisualGraph],
    graph_owners: Mapping[str, set[str | None]],
    parent_ids: set[str],
) -> tuple[tuple[str, str], ...]:
    """Reject graph scale writes that can make a retained parent uncomposable."""

    messages: list[tuple[str, str]] = []
    for graph in graphs:
        owners = graph_owners.get(graph.id, set())
        if not owners:
            continue
        for graph_node in graph.nodes:
            if graph_node.type != "action.set_component":
                continue
            targets = _graph_mutation_targets(graph, graph_node, owners)
            affected = parent_ids if targets is None else parent_ids & targets
            if not affected:
                continue

            component_known, component = _graph_known_input(
                graph, graph_node, "component", "transform"
            )
            field_known, field = _graph_known_input(
                graph, graph_node, "field", "position"
            )
            could_be_transform = not component_known or str(component) == "transform"
            field_name = "" if not field_known else str(field)
            could_write_scale = (
                not field_known
                or field_name in {"", "scale"}
                or field_name.startswith("scale.")
            )
            if not could_be_transform or not could_write_scale:
                continue

            # A complete, saved uniform-positive vector is the one scale write
            # whose result is safe regardless of when the graph runs. A
            # single-axis or runtime-selected write cannot prove that all
            # three parent axes remain equal.
            if component_known and field_known and field_name in {"", "scale"}:
                value_known, value = _graph_known_input(
                    graph, graph_node, "value", None
                )
                if value_known:
                    if field_name == "scale" and is_uniform_positive_scale_3d(value):
                        continue
                    if (
                        field_name == ""
                        and isinstance(value, Mapping)
                        and (
                            "scale" not in value
                            or is_uniform_positive_scale_3d(value["scale"])
                        )
                    ):
                        continue

            path = f"metadata.visual_graphs.{graph.id}.nodes.{graph_node.id}"
            if targets is None:
                target_text = "a parent chosen while the game runs"
            else:
                names = ", ".join(repr(value) for value in sorted(affected))
                target_text = (
                    f"hierarchy parent {names}"
                    if len(affected) == 1
                    else f"hierarchy parents {names}"
                )
            messages.append(
                (
                    path,
                    f"Logic Blocks graph {graph.id!r} can change the Scale of {target_text} "
                    "without proving equal positive X, Y, and Z values. Retained children "
                    "need a uniform positive parent scale; save one complete uniform Scale "
                    "vector or move this block to an object without children.",
                )
            )
    return tuple(messages)


def _animation_graph_messages(
    graphs: Sequence[VisualGraph],
    graph_owners: Mapping[str, set[str | None]],
    scene_ids: set[str],
    clip_ids_by_node: Mapping[str, set[str]],
) -> tuple[tuple[str, str], ...]:
    """Prove fixed Play/Stop targets while leaving dynamic choices runtime-checked."""

    messages: list[tuple[str, str]] = []
    for graph in graphs:
        owners = graph_owners.get(graph.id, set())
        if not owners:
            continue
        for graph_node in graph.nodes:
            if graph_node.type not in {
                "action.play_animation",
                "action.stop_animation",
            }:
                continue
            path = f"metadata.visual_graphs.{graph.id}.nodes.{graph_node.id}"
            targets = _graph_mutation_targets(graph, graph_node, owners)
            if targets is None:
                # Sensing/state can deliberately choose an object while the game runs.
                # The bounded runtime reports a precise issue if that object has no clip.
                continue
            if not targets:
                messages.append(
                    (
                        path,
                        f"Logic Blocks graph {graph.id!r} uses This object for Animation, "
                        "but this is World Logic. Choose a specific animated object.",
                    )
                )
                continue
            missing_scene = sorted(target for target in targets if target not in scene_ids)
            if missing_scene:
                messages.append(
                    (
                        path,
                        "Animation Logic Blocks name missing scene "
                        + ("object " if len(missing_scene) == 1 else "objects ")
                        + ", ".join(repr(value) for value in missing_scene)
                        + ". Choose an object from this project.",
                    )
                )
                continue
            missing_animation = sorted(
                target for target in targets if target not in clip_ids_by_node
            )
            if missing_animation:
                messages.append(
                    (
                        path,
                        "Animation Logic Blocks target "
                        + ("object " if len(missing_animation) == 1 else "objects ")
                        + ", ".join(repr(value) for value in missing_animation)
                        + " without an Animation. Create a clip on each target first.",
                    )
                )
                continue
            if graph_node.type != "action.play_animation":
                continue
            clip_known, clip_value = _graph_known_input(
                graph, graph_node, "clip", "main"
            )
            if not clip_known or not isinstance(clip_value, str):
                continue
            missing_clip = sorted(
                target
                for target in targets
                if clip_value not in clip_ids_by_node[target]
            )
            if missing_clip:
                messages.append(
                    (
                        path,
                        f"Play Animation asks for clip {clip_value!r}, but "
                        + ("object " if len(missing_clip) == 1 else "objects ")
                        + ", ".join(repr(value) for value in missing_clip)
                        + " do not have it. Choose one of their saved clips.",
                    )
                )
    return tuple(messages)


def _polar_population_graph_messages(
    graphs: Sequence[VisualGraph],
    graph_owners: Mapping[str, set[str | None]],
    prototype_ids: set[str],
) -> tuple[tuple[str, str], ...]:
    """Validate fixed Make Many targets without inventing a runtime entity query."""

    messages: list[tuple[str, str]] = []
    for graph in graphs:
        owners = graph_owners.get(graph.id, set())
        if not owners:
            continue
        for graph_node in graph.nodes:
            if graph_node.type != "action.set_polar_population_visible":
                continue
            path = f"metadata.visual_graphs.{graph.id}.nodes.{graph_node.id}"
            literal = graph_node.properties.get("entity")
            if literal in (None, ""):
                invalid = sorted(
                    "World Logic" if owner is None else repr(owner)
                    for owner in owners
                    if owner is None or owner not in prototype_ids
                )
                if invalid:
                    messages.append(
                        (
                            path,
                            "Show or Hide Extra Copies uses This object, but "
                            + ", ".join(invalid)
                            + " does not own a Make Many recipe. Choose an object listed by Make Many.",
                        )
                    )
                continue
            target = str(literal)
            if target not in prototype_ids:
                messages.append(
                    (
                        path,
                        f"Show or Hide Extra Copies target {target!r} does not own a Make Many recipe. "
                        "Choose an object listed by Make Many.",
                    )
                )
    return tuple(messages)


def _normalized_json(value: Any) -> Any:
    """Normalize numerically equivalent JSON values before hashing."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite value in canonical JSON")
        return int(value) if value.is_integer() else value
    if isinstance(value, int):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalized_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalized_json(item) for item in value]
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        _normalized_json(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


def initial_state_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach the JSON state seeded into a new 3D world."""
    raw = metadata.get("initial_state", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TypeError("metadata.initial_state must be an object")
    if any(not isinstance(key, str) or not key.strip() for key in raw):
        raise ValueError("metadata.initial_state keys must be nonempty text")
    # Reuse the content-hash normalizer to reject NaN/infinity and values that
    # cannot cross the JSON authoring/runtime boundary.
    _canonical(raw)
    return copy.deepcopy(dict(raw))


def _values(value: Sequence[float], count: int, label: str) -> tuple[float, ...]:
    if len(value) != count:
        raise ValueError(f"{label} requires {count} values")
    result = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{label} must be finite")
    return result


def _positive(value: float, label: str, allow_zero: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{label} must be {'nonnegative' if allow_zero else 'positive'}")
    return result


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def tag_mask(tags: Sequence[str]) -> int:
    result = 0
    for tag in tags:
        result |= TAG_MAP.get(tag, 0)
    return result


@dataclass(frozen=True)
class Transform3DRecord:
    translation: Vec3 = (0.0, 0.0, 0.0)
    rotation: Quat = (1.0, 0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)

    def validate(self) -> None:
        _values(self.translation, 3, "translation")
        quat_normalize(_values(self.rotation, 4, "rotation"))
        scale = _values(self.scale, 3, "scale")
        if any(abs(v) <= EPS for v in scale):
            raise ValueError("scale components must be nonzero")

    def matrix(self):
        self.validate()
        return compose_trs(self.translation, self.rotation, self.scale)

    def to_dict(self) -> dict[str, Any]:
        return {
            "translation": list(self.translation),
            "rotation": list(self.rotation),
            "scale": list(self.scale),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Transform3DRecord":
        data = data or {}
        return cls(
            _values(data.get("translation", (0, 0, 0)), 3, "translation"),
            _values(data.get("rotation", (1, 0, 0, 0)), 4, "rotation"),
            _values(data.get("scale", (1, 1, 1)), 3, "scale"),
        )


@dataclass(frozen=True)
class Material3DRecord:
    id: str
    base_color: Color4 = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.5
    emissive: Color3 = (0.0, 0.0, 0.0)
    double_sided: bool = False

    def validate(self) -> None:
        if not self.id:
            raise ValueError("material id required")
        base = _values(self.base_color, 4, "base_color")
        emissive = _values(self.emissive, 3, "emissive")
        if any(v < 0 or v > 1 for v in base) or any(v < 0 for v in emissive):
            raise ValueError("material colors outside supported range")
        if not 0 <= self.metallic <= 1 or not 0 <= self.roughness <= 1:
            raise ValueError("metallic and roughness must be in [0,1]")

    def to_pbr(self) -> PBRMaterial:
        self.validate()
        return PBRMaterial(
            self.id, self.base_color, self.metallic, self.roughness,
            self.emissive, double_sided=self.double_sided,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_color": list(self.base_color),
            "metallic": self.metallic,
            "roughness": self.roughness,
            "emissive": list(self.emissive),
            "double_sided": self.double_sided,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Material3DRecord":
        return cls(
            str(data["id"]),
            _values(data.get("base_color", (0.8, 0.8, 0.8, 1)), 4, "base_color"),
            float(data.get("metallic", 0)),
            float(data.get("roughness", 0.5)),
            _values(data.get("emissive", (0, 0, 0)), 3, "emissive"),
            bool(data.get("double_sided", False)),
        )


def _computed_normals(
    vertices: Sequence[Vec3], triangles: Sequence[tuple[int, int, int]]
) -> tuple[Vec3, ...]:
    sums = [[0.0, 0.0, 0.0] for _ in vertices]
    for ia, ib, ic in triangles:
        face = cross(sub(vertices[ib], vertices[ia]), sub(vertices[ic], vertices[ia]))
        if norm(face) <= EPS:
            continue
        for index in (ia, ib, ic):
            for axis in range(3):
                sums[index][axis] += face[axis]
    return tuple((0.0, 1.0, 0.0) if norm(v) <= EPS else normalize(v) for v in sums)


@dataclass(frozen=True)
class Mesh3DRecord:
    id: str
    vertices: tuple[Vec3, ...]
    triangles: tuple[tuple[int, int, int], ...]
    normals: tuple[Vec3, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("mesh id required")
        self.to_mesh().validate()

    def resolved_normals(self) -> tuple[Vec3, ...]:
        return self.normals or _computed_normals(self.vertices, self.triangles)

    def to_mesh(self) -> Mesh:
        return Mesh(self.vertices, self.triangles, self.normals, metadata=dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vertices": [list(v) for v in self.vertices],
            "triangles": [list(t) for t in self.triangles],
            "normals": [list(n) for n in self.normals],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Mesh3DRecord":
        return cls(
            str(data["id"]),
            tuple(_values(v, 3, "vertex") for v in data["vertices"]),
            tuple(tuple(int(i) for i in tri) for tri in data["triangles"]),
            tuple(_values(n, 3, "normal") for n in data.get("normals", [])),
            dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class Collider3DRecord:
    shape: str = "none"
    radius: float = 0.5
    half_extents: Vec3 = (0.5, 0.5, 0.5)
    sensor: bool = False

    def validate(self) -> None:
        if self.shape not in {"none", "sphere", "box"}:
            raise ValueError("collider shape must be none, sphere or box")
        if self.shape == "sphere":
            _positive(self.radius, "collider radius")
        if self.shape == "box" and any(
            v <= 0 for v in _values(self.half_extents, 3, "half_extents")
        ):
            raise ValueError("box half_extents must be positive")

    def bounding_radius(self, scale: Vec3 = (1, 1, 1)) -> float:
        if self.shape == "none":
            return 0.0
        if self.shape == "sphere":
            return self.radius * max(abs(v) for v in scale)
        return math.sqrt(
            sum((self.half_extents[i] * abs(scale[i])) ** 2 for i in range(3))
        )

    def vertical_extent(self, scale: Vec3 = (1, 1, 1)) -> float:
        if self.shape == "none":
            return 0.0
        if self.shape == "sphere":
            return self.radius * abs(scale[1])
        return self.half_extents[1] * abs(scale[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": self.shape,
            "radius": self.radius,
            "half_extents": list(self.half_extents),
            "sensor": self.sensor,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Collider3DRecord":
        data = data or {"shape": "none"}
        return cls(
            str(data.get("shape", "none")),
            float(data.get("radius", 0.5)),
            _values(data.get("half_extents", (0.5, 0.5, 0.5)), 3, "half_extents"),
            bool(data.get("sensor", False)),
        )


@dataclass(frozen=True)
class Node3DRecord:
    id: str
    mesh_id: str
    material_id: str
    transform: Transform3DRecord = Transform3DRecord()
    velocity: Vec3 = (0.0, 0.0, 0.0)
    angular_velocity: Vec3 = (0.0, 0.0, 0.0)
    collider: Collider3DRecord = Collider3DRecord()
    dynamic: bool = False
    mass: float = 1.0
    restitution: float = 0.35
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)
    parent_id: str | None = None

    def validate(self) -> None:
        if not self.id or not self.mesh_id or not self.material_id:
            raise ValueError("node id, mesh_id and material_id required")
        if self.parent_id is not None and not isinstance(self.parent_id, str):
            raise ValueError("parent_id must be nonempty text or null")
        if self.parent_id == "":
            raise ValueError("parent_id must be nonempty text or null")
        self.transform.validate()
        _values(self.velocity, 3, "velocity")
        _values(self.angular_velocity, 3, "angular_velocity")
        self.collider.validate()
        _positive(self.mass, "mass")
        if not 0 <= self.restitution <= 1:
            raise ValueError("restitution must be in [0,1]")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "mesh_id": self.mesh_id,
            "material_id": self.material_id,
            "transform": self.transform.to_dict(),
            "velocity": list(self.velocity),
            "angular_velocity": list(self.angular_velocity),
            "collider": self.collider.to_dict(),
            "dynamic": self.dynamic,
            "mass": self.mass,
            "restitution": self.restitution,
            "tags": list(self.tags),
            "metadata": self.metadata,
        }
        if self.parent_id is not None:
            result["parent_id"] = self.parent_id
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Node3DRecord":
        return cls(
            str(data["id"]), str(data["mesh_id"]), str(data["material_id"]),
            Transform3DRecord.from_dict(data.get("transform")),
            _values(data.get("velocity", (0, 0, 0)), 3, "velocity"),
            _values(data.get("angular_velocity", (0, 0, 0)), 3, "angular_velocity"),
            Collider3DRecord.from_dict(data.get("collider")),
            bool(data.get("dynamic", False)), float(data.get("mass", 1)),
            float(data.get("restitution", 0.35)),
            tuple(str(tag) for tag in data.get("tags", [])),
            dict(data.get("metadata", {})),
            None if data.get("parent_id") is None else str(data["parent_id"]),
        )


@dataclass(frozen=True)
class Camera3DRecord:
    position: Vec3 = (8.0, 5.0, 10.0)
    target: Vec3 = (0.0, 1.0, 0.0)
    up: Vec3 = (0.0, 1.0, 0.0)
    vertical_fov_degrees: float = 55.0
    near: float = 0.05
    far: float = 250.0

    def validate(self) -> None:
        position = _values(self.position, 3, "camera position")
        target = _values(self.target, 3, "camera target")
        up = _values(self.up, 3, "camera up")
        if norm(sub(target, position)) <= EPS or norm(up) <= EPS:
            raise ValueError("camera vectors are degenerate")
        if not 10 <= self.vertical_fov_degrees <= 140:
            raise ValueError("camera FOV outside supported range")
        if self.near <= 0 or self.far <= self.near:
            raise ValueError("camera clip range invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": list(self.position), "target": list(self.target),
            "up": list(self.up), "vertical_fov_degrees": self.vertical_fov_degrees,
            "near": self.near, "far": self.far,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Camera3DRecord":
        data = data or {}
        return cls(
            _values(data.get("position", (8, 5, 10)), 3, "camera position"),
            _values(data.get("target", (0, 1, 0)), 3, "camera target"),
            _values(data.get("up", (0, 1, 0)), 3, "camera up"),
            float(data.get("vertical_fov_degrees", 55)),
            float(data.get("near", 0.05)), float(data.get("far", 250)),
        )


@dataclass(frozen=True)
class DirectionalLight3DRecord:
    direction: Vec3 = (-0.4, -1.0, -0.25)
    color: Color3 = (1.0, 0.96, 0.9)
    intensity: float = 1.25
    ambient: float = 0.18

    def validate(self) -> None:
        if norm(_values(self.direction, 3, "light direction")) <= EPS:
            raise ValueError("light direction is degenerate")
        if any(v < 0 for v in _values(self.color, 3, "light color")):
            raise ValueError("light color invalid")
        _positive(self.intensity, "light intensity", True)
        if not 0 <= self.ambient <= 1:
            raise ValueError("ambient must be in [0,1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": list(self.direction), "color": list(self.color),
            "intensity": self.intensity, "ambient": self.ambient,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "DirectionalLight3DRecord":
        data = data or {}
        return cls(
            _values(data.get("direction", (-0.4, -1, -0.25)), 3, "light direction"),
            _values(data.get("color", (1, 0.96, 0.9)), 3, "light color"),
            float(data.get("intensity", 1.25)), float(data.get("ambient", 0.18)),
        )


@dataclass(frozen=True)
class QualityTier3D:
    id: str
    target_fps: int
    render_scale: float
    max_visible_nodes: int
    msaa_samples: int = 0
    post_processing: bool = True
    shadow_quality: int = 0

    def validate(self) -> None:
        if not self.id:
            raise ValueError("quality id required")
        if self.target_fps not in {30, 40, 45, 60, 72, 90, 120, 144}:
            raise ValueError("unsupported target_fps")
        if not 0.45 <= self.render_scale <= 1:
            raise ValueError("render_scale must be in [0.45,1]")
        if self.max_visible_nodes < 1:
            raise ValueError("max_visible_nodes must be positive")
        if self.msaa_samples not in {0, 2, 4, 8} or not 0 <= self.shadow_quality <= 3:
            raise ValueError("quality fields invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "target_fps": self.target_fps,
            "render_scale": self.render_scale,
            "max_visible_nodes": self.max_visible_nodes,
            "msaa_samples": self.msaa_samples,
            "post_processing": self.post_processing,
            "shadow_quality": self.shadow_quality,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QualityTier3D":
        return cls(
            str(data["id"]), int(data["target_fps"]), float(data["render_scale"]),
            int(data["max_visible_nodes"]), int(data.get("msaa_samples", 0)),
            bool(data.get("post_processing", True)),
            int(data.get("shadow_quality", 0)),
        )


@dataclass(frozen=True)
class AndroidTargetProfile:
    id: str
    label: str
    min_sdk: int = 26
    target_sdk: int = 36
    compile_sdk: int = 36
    preferred_abis: tuple[str, ...] = ("arm64-v8a",)
    required_gles: tuple[int, int] = (3, 0)
    vulkan_optional: bool = True
    target_refresh_hz: int = 60
    memory_floor_mb: int = 3072
    device_hints: tuple[str, ...] = ()
    gpu_hints: tuple[str, ...] = ()
    default_quality: str = "balanced"

    def validate(self) -> None:
        if not self.id or not self.label:
            raise ValueError("target id and label required")
        if not 21 <= self.min_sdk <= self.target_sdk <= self.compile_sdk:
            raise ValueError("Android SDK levels invalid")
        if not self.preferred_abis or not set(self.preferred_abis) <= {
            "arm64-v8a", "armeabi-v7a", "x86_64"
        }:
            raise ValueError("unsupported Android ABI")
        if self.required_gles < (3, 0):
            raise ValueError("OpenGL ES 3.0 is required")
        if self.target_refresh_hz not in {30, 45, 60, 72, 90, 120, 144}:
            raise ValueError("unsupported refresh target")
        if self.memory_floor_mb < 1024:
            raise ValueError("memory floor too low")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "min_sdk": self.min_sdk,
            "target_sdk": self.target_sdk, "compile_sdk": self.compile_sdk,
            "preferred_abis": list(self.preferred_abis),
            "required_gles": list(self.required_gles),
            "vulkan_optional": self.vulkan_optional,
            "target_refresh_hz": self.target_refresh_hz,
            "memory_floor_mb": self.memory_floor_mb,
            "device_hints": list(self.device_hints),
            "gpu_hints": list(self.gpu_hints),
            "default_quality": self.default_quality,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AndroidTargetProfile":
        gles = tuple(int(v) for v in data.get("required_gles", (3, 0)))
        if len(gles) != 2:
            raise ValueError("required_gles requires major/minor")
        return cls(
            str(data["id"]), str(data.get("label", data["id"])),
            int(data.get("min_sdk", 26)), int(data.get("target_sdk", 36)),
            int(data.get("compile_sdk", 36)),
            tuple(str(v) for v in data.get("preferred_abis", ["arm64-v8a"])),
            (gles[0], gles[1]), bool(data.get("vulkan_optional", True)),
            int(data.get("target_refresh_hz", 60)),
            int(data.get("memory_floor_mb", 3072)),
            tuple(str(v) for v in data.get("device_hints", [])),
            tuple(str(v) for v in data.get("gpu_hints", [])),
            str(data.get("default_quality", "balanced")),
        )


@dataclass(frozen=True)
class DeviceCapabilities3D:
    model: str = "unknown"
    manufacturer: str = "unknown"
    gpu_renderer: str = "unknown"
    ram_mb: int = 4096
    cpu_cores: int = 4
    gles_major: int = 3
    gles_minor: int = 0
    display_refresh_hz: float = 60.0

    def validate(self) -> None:
        if self.ram_mb < 512 or self.cpu_cores < 1:
            raise ValueError("RAM/core count invalid")
        if self.gles_major < 2 or self.display_refresh_hz <= 0:
            raise ValueError("graphics/display capabilities invalid")


@dataclass(frozen=True)
class SelectedDeviceProfile3D:
    profile_id: str
    quality_id: str
    target_fps: int
    render_scale: float
    reason: str


def select_device_profile(
    capabilities: DeviceCapabilities3D,
    profiles: Sequence[AndroidTargetProfile],
    quality_tiers: Sequence[QualityTier3D],
    requested: str = "auto",
) -> SelectedDeviceProfile3D:
    capabilities.validate()
    profile_by_id = {profile.id: profile for profile in profiles}
    quality_by_id = {quality.id: quality for quality in quality_tiers}
    if not profile_by_id or not quality_by_id:
        raise ValueError("profiles and quality tiers required")
    if requested != "auto":
        if requested not in profile_by_id:
            raise KeyError(requested)
        selected = profile_by_id[requested]
        reason = "explicit profile request"
    else:
        model = f"{capabilities.manufacturer} {capabilities.model}".lower()
        gpu = capabilities.gpu_renderer.lower()
        scored: list[tuple[int, int, str, AndroidTargetProfile, str]] = []
        for profile in profiles:
            score = 0
            reasons: list[str] = []
            poco_match = (
                "poco x7 pro" in model
                or any(hint.lower() in model for hint in profile.device_hints)
                or any(hint.lower() in gpu for hint in profile.gpu_hints)
            )
            if profile.id == "poco_x7_pro_12gb":
                score += 100 if poco_match else -25
                if poco_match:
                    reasons.append("POCO/Mali-G720 signature match")
            if capabilities.ram_mb >= profile.memory_floor_mb:
                score += 15
                reasons.append("RAM floor met")
            else:
                score -= 80
            if (capabilities.gles_major, capabilities.gles_minor) >= profile.required_gles:
                score += 15
            else:
                score -= 120
            if capabilities.display_refresh_hz + 1 >= profile.target_refresh_hz:
                score += 5
            scored.append(
                (score, profile.memory_floor_mb, profile.id, profile,
                 ", ".join(reasons) or "generic capability match")
            )
        _, _, _, selected, reason = max(scored)
    quality = quality_by_id.get(selected.default_quality)
    if quality is None:
        raise KeyError(selected.default_quality)
    target_fps = min(
        quality.target_fps,
        selected.target_refresh_hz,
        max(30, int(round(capabilities.display_refresh_hz))),
    )
    return SelectedDeviceProfile3D(
        selected.id, quality.id, target_fps, quality.render_scale, reason
    )


@dataclass
class AdaptiveQualityController3D:
    quality_ids: tuple[str, ...]
    current_index: int = 0
    low_fps_seconds: float = 0.0
    recovery_seconds: float = 0.0

    @property
    def current(self) -> str:
        if not self.quality_ids:
            raise ValueError("quality_ids required")
        return self.quality_ids[self.current_index]

    def update(
        self, frame_fps: float, target_fps: float, thermal_status: int, dt: float
    ) -> str:
        if not self.quality_ids or dt < 0:
            raise ValueError("quality ids and nonnegative dt required")
        stressed = thermal_status >= 3 or frame_fps < target_fps * 0.82
        comfortable = thermal_status <= 1 and frame_fps >= target_fps * 0.96
        self.low_fps_seconds = (
            self.low_fps_seconds + dt
            if stressed else max(0.0, self.low_fps_seconds - dt * 0.5)
        )
        self.recovery_seconds = self.recovery_seconds + dt if comfortable else 0.0
        if self.low_fps_seconds >= 1.5 and self.current_index < len(self.quality_ids) - 1:
            self.current_index += 1
            self.low_fps_seconds = self.recovery_seconds = 0.0
        elif self.recovery_seconds >= 8.0 and self.current_index > 0:
            self.current_index -= 1
            self.recovery_seconds = 0.0
        return self.current


@dataclass(frozen=True)
class World3DSettings:
    fixed_dt: float = 1 / 120
    gravity: Vec3 = (0.0, -9.81, 0.0)
    floor_y: float = 0.0
    bounds_min: Vec3 = (-24.0, -8.0, -24.0)
    bounds_max: Vec3 = (24.0, 28.0, 24.0)
    player_speed: float = 6.0
    jump_speed: float = 7.5

    def validate(self) -> None:
        if not 1 / 1000 <= self.fixed_dt <= 1 / 15:
            raise ValueError("fixed_dt outside supported range")
        _values(self.gravity, 3, "gravity")
        lo = _values(self.bounds_min, 3, "bounds_min")
        hi = _values(self.bounds_max, 3, "bounds_max")
        if any(lo[i] >= hi[i] for i in range(3)):
            raise ValueError("world bounds invalid")
        _positive(self.player_speed, "player_speed", True)
        _positive(self.jump_speed, "jump_speed", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed_dt": self.fixed_dt, "gravity": list(self.gravity),
            "floor_y": self.floor_y, "bounds_min": list(self.bounds_min),
            "bounds_max": list(self.bounds_max),
            "player_speed": self.player_speed, "jump_speed": self.jump_speed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "World3DSettings":
        data = data or {}
        return cls(
            float(data.get("fixed_dt", 1 / 120)),
            _values(data.get("gravity", (0, -9.81, 0)), 3, "gravity"),
            float(data.get("floor_y", 0)),
            _values(data.get("bounds_min", (-24, -8, -24)), 3, "bounds_min"),
            _values(data.get("bounds_max", (24, 28, 24)), 3, "bounds_max"),
            float(data.get("player_speed", 6)),
            float(data.get("jump_speed", 7.5)),
        )


@dataclass(frozen=True)
class ProjectIssue3D:
    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity, "code": self.code,
            "path": self.path, "message": self.message,
        }


@dataclass(frozen=True)
class ProjectValidation3D:
    passed: bool
    issues: tuple[ProjectIssue3D, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ugts-kc-mobile-3d-validation-3.9.1",
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "metrics": self.metrics,
        }


@dataclass
class Mobile3DProject:
    id: str
    title: str
    author: str
    meshes: dict[str, Mesh3DRecord]
    materials: dict[str, Material3DRecord]
    nodes: tuple[Node3DRecord, ...]
    camera: Camera3DRecord = Camera3DRecord()
    light: DirectionalLight3DRecord = DirectionalLight3DRecord()
    quality_tiers: tuple[QualityTier3D, ...] = ()
    target_profiles: tuple[AndroidTargetProfile, ...] = ()
    world: World3DSettings = World3DSettings()
    start_quality: str = "balanced"
    background: Color4 = (0.018, 0.03, 0.055, 1.0)
    schema: str = MOBILE3D_SCHEMA
    edition: str = "3.9.2 - K-Kij-T / Grove — Tom Klootwijk Signature Edition"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, raise_on_error: bool = True) -> ProjectValidation3D:
        issues: list[ProjectIssue3D] = []

        def error(code: str, path: str, message: str) -> None:
            issues.append(ProjectIssue3D("error", code, path, message))

        if self.schema != MOBILE3D_SCHEMA:
            error("schema.unsupported", "schema", f"expected {MOBILE3D_SCHEMA}")
        if not self.id or not self.title:
            error("project.identity", "id/title", "project id and title required")
        initial_state_count = 0
        try:
            initial_state_count = len(initial_state_from_metadata(self.metadata))
        except (TypeError, ValueError) as exc:
            error("state.initial_invalid", "metadata.initial_state", str(exc))
        for label, value in (
            ("camera", self.camera), ("light", self.light), ("world", self.world)
        ):
            try:
                value.validate()
            except ValueError as exc:
                error(f"{label}.invalid", label, str(exc))
        try:
            bg = _values(self.background, 4, "background")
            if any(v < 0 or v > 1 for v in bg):
                raise ValueError("background must be in [0,1]")
        except ValueError as exc:
            error("background.invalid", "background", str(exc))
        for key, mesh in self.meshes.items():
            if key != mesh.id:
                error("mesh.key", f"meshes.{key}", "key differs from id")
            try:
                mesh.validate()
            except ValueError as exc:
                error("mesh.invalid", f"meshes.{key}", str(exc))
        for key, material in self.materials.items():
            if key != material.id:
                error("material.key", f"materials.{key}", "key differs from id")
            try:
                material.validate()
            except ValueError as exc:
                error("material.invalid", f"materials.{key}", str(exc))
        node_ids: set[str] = set()
        sensor_count = 0
        for index, node in enumerate(self.nodes):
            path = f"nodes[{index}]"
            if node.id in node_ids:
                error("node.duplicate", path, node.id)
            node_ids.add(node.id)
            try:
                node.validate()
            except ValueError as exc:
                error("node.invalid", path, str(exc))
            if node.mesh_id not in self.meshes:
                error("mesh.unknown", f"{path}.mesh_id", node.mesh_id)
            if node.material_id not in self.materials:
                error("material.unknown", f"{path}.material_id", node.material_id)
            if node.collider.sensor and node.collider.shape != "none":
                sensor_count += 1
        node_index_by_id = {
            node.id: index for index, node in enumerate(self.nodes)
        }
        hierarchy_issue_paths = {
            "parent_missing": "parent_id",
            "cycle": "parent_id",
            "depth": "parent_id",
            "parent_scale": "transform.scale",
            "child_dynamic": "dynamic",
            "child_collider": "collider",
            "child_tags": "tags",
            "child_angular_velocity": "angular_velocity",
            "child_visual_graph": "metadata.visual_graph",
            "child_packed_movement": "metadata.packed_kinematic",
            "child_population": "metadata.scatter_population",
            "child_transform_animation": "metadata.transform_animation",
        }
        for hierarchy_issue in hierarchy_issues3d(self.nodes):
            # The ordinary node pass already reports duplicate ids with its
            # established public code.  Avoid changing that flat error shape.
            if hierarchy_issue.code == "duplicate":
                continue
            index = node_index_by_id.get(hierarchy_issue.node_id)
            suffix = hierarchy_issue_paths.get(hierarchy_issue.code, "parent_id")
            path = "nodes" if index is None else f"nodes[{index}].{suffix}"
            error(
                f"hierarchy.{hierarchy_issue.code}",
                path,
                hierarchy_issue.message,
            )
        if sensor_count > MAX_TRIGGER_SENSORS:
            error(
                "trigger.sensor_limit",
                "nodes",
                f"projects support at most {MAX_TRIGGER_SENSORS} active trigger areas",
            )
        hierarchy_parent_ids = {
            str(node.parent_id) for node in self.nodes if node.parent_id is not None
        }
        graphs: tuple[VisualGraph, ...] = ()
        graphs_valid = True
        try:
            graphs = visual_graphs_from_metadata(self.metadata)
            for graph in graphs:
                graph.validate()
        except (TypeError, ValueError) as exc:
            graphs_valid = False
            error("graph.invalid", "metadata.visual_graphs", str(exc))
        graph_ids = {graph.id for graph in graphs}
        graph_owners: dict[str, set[str | None]] = {}
        binding_count = 0
        for index, node in enumerate(self.nodes):
            raw_binding = node.metadata.get("visual_graph")
            if raw_binding is None:
                continue
            try:
                bindings = visual_graph_binding_ids(
                    raw_binding, f"node {node.id} visual_graph binding"
                )
            except (TypeError, ValueError) as exc:
                error(
                    "graph.binding_type",
                    f"nodes[{index}].metadata.visual_graph",
                    str(exc),
                )
                continue
            binding_count += len(bindings)
            for graph_id in bindings:
                if graph_id not in graph_ids:
                    error(
                        "graph.binding_unknown",
                        f"nodes[{index}].metadata.visual_graph",
                        graph_id,
                    )
                else:
                    graph_owners.setdefault(graph_id, set()).add(node.id)
        raw_world_bindings = self.metadata.get("world_graphs", ())
        try:
            world_bindings = visual_graph_binding_ids(
                raw_world_bindings, "metadata.world_graphs"
            )
        except (TypeError, ValueError) as exc:
            world_bindings = ()
            error(
                "graph.world_binding_type",
                "metadata.world_graphs",
                str(exc),
            )
        binding_count += len(world_bindings)
        for graph_id in world_bindings:
            if graph_id not in graph_ids:
                error("graph.binding_unknown", "metadata.world_graphs", graph_id)
            else:
                graph_owners.setdefault(graph_id, set()).add(None)
        if graphs_valid and hierarchy_parent_ids:
            for path, message in _hierarchy_graph_scale_messages(
                graphs, graph_owners, hierarchy_parent_ids
            ):
                error("hierarchy.parent_graph_scale", path, message)
        polar_profile_count = 0
        polar_component_count = 0
        try:
            polar_spec = collect_polar_project_spec(self)
            polar_profile_count = len(polar_spec.profiles)
            polar_component_count = len(polar_spec.components)
            # Validate the exact binary16-roundtripped table used by both the
            # desktop preview and native exporter, not merely its source range.
            for profile in polar_spec.profiles:
                quantized_profile_lut(profile)
        except PolarPackError as exc:
            error("packed_kinematic.invalid", "metadata.packed_kinematic_profiles", str(exc))
        else:
            for item in polar_spec.components:
                polar_node = self.nodes[item.node_index]
                if polar_node.dynamic:
                    error(
                        "packed_kinematic.dynamic_conflict",
                        f"nodes[{item.node_index}].dynamic",
                        "packed kinematics are transform-authoritative; use a static node so physics does not overwrite them",
                    )
                if "player" in polar_node.tags:
                    error(
                        "packed_kinematic.player_conflict",
                        f"nodes[{item.node_index}].tags",
                        "Movement Pattern owns horizontal position and velocity, while the Player controller also writes them; remove the Player tag or the Movement Pattern",
                    )
                try:
                    has_packed_spin = any(
                        f32(value) != 0.0 for value in polar_node.angular_velocity
                    )
                except ScatterError:
                    has_packed_spin = True
                if has_packed_spin:
                    error(
                        "packed_kinematic.angular_velocity_conflict",
                        f"nodes[{item.node_index}].angular_velocity",
                        "Movement Pattern owns facing rotation; set Spin velocity to zero and change Facing in Polar Movement instead",
                    )
            if graphs_valid and polar_spec.components:
                polar_ids = {item.node_id for item in polar_spec.components}
                for path, message in _packed_polar_graph_write_messages(
                    graphs, graph_owners, polar_ids
                ):
                    error("packed_kinematic.graph_write_conflict", path, message)
        scatter_group_count = 0
        scatter_total_instances = 0
        scatter_generated_copies = 0
        try:
            scatter_spec = collect_scatter_project_spec(self)
            scatter_group_count = len(scatter_spec.groups)
            scatter_total_instances = scatter_spec.total_instances
            scatter_generated_copies = scatter_spec.generated_copies
        except ScatterError as exc:
            error("scatter.invalid", "nodes[].metadata.scatter_population", str(exc))
        else:
            if graphs_valid and scatter_spec.groups:
                prototype_ids = {group.prototype_id for group in scatter_spec.groups}
                for path, message in _scatter_graph_mutation_messages(
                    graphs, graph_owners, prototype_ids
                ):
                    error("scatter.graph_mutation", path, message)
        polar_population_count = 0
        polar_population_total_instances = 0
        polar_population_generated_copies = 0
        try:
            polar_population_spec = collect_polar_population_project_spec(self)
            polar_population_count = len(polar_population_spec.groups)
            polar_population_total_instances = polar_population_spec.total_instances
            polar_population_generated_copies = polar_population_spec.generated_copies
        except PolarPopulationError as exc:
            error(
                "polar_population.invalid",
                "nodes[].metadata.polar_population",
                str(exc),
            )
        else:
            if graphs_valid:
                prototype_ids = {
                    group.prototype_id for group in polar_population_spec.groups
                }
                for path, message in _polar_population_graph_messages(
                    graphs, graph_owners, prototype_ids
                ):
                    error("polar_population.graph_target", path, message)
        animation_binding_count = 0
        animation_clip_count = 0
        animation_key_count = 0
        animation_spec_valid = True
        clip_ids_by_node: dict[str, set[str]] = {}
        try:
            animation_spec = collect_transform_animation_spec(self)
            animation_binding_count = animation_spec.animated_node_count
            animation_clip_count = animation_spec.clip_count
            animation_key_count = animation_spec.key_count
            for binding in animation_spec.bindings:
                clip_ids_by_node.setdefault(binding.node_id, set()).add(
                    binding.clip_id
                )
                if binding.node_id in hierarchy_parent_ids and any(
                    not is_uniform_positive_scale_3d(key.scale)
                    for key in binding.animation.keys
                ):
                    binding_index = node_index_by_id[binding.node_id]
                    animation_key = (
                        ANIMATION_LIBRARY_METADATA_KEY
                        if ANIMATION_LIBRARY_METADATA_KEY
                        in self.nodes[binding_index].metadata
                        else ANIMATION_METADATA_KEY
                    )
                    error(
                        "hierarchy.parent_animation_scale",
                        f"nodes[{binding_index}].metadata.{animation_key}",
                        f"hierarchy parent {binding.node_id!r} animation clip "
                        f"{binding.clip_id!r} must keep scale uniform and positive",
                    )
        except TransformAnimationError as exc:
            animation_spec_valid = False
            error(
                "transform_animation.invalid",
                (
                    f"nodes[].metadata.{ANIMATION_METADATA_KEY}/"
                    f"{ANIMATION_LIBRARY_METADATA_KEY}"
                ),
                str(exc),
            )
        if graphs_valid and animation_spec_valid:
            for path, message in _animation_graph_messages(
                graphs,
                graph_owners,
                node_ids,
                clip_ids_by_node,
            ):
                error("transform_animation.graph_control", path, message)
        reusable_object_count = 0
        try:
            # Kept local to avoid coupling the flat runtime model to the
            # authoring-only reusable-object helper during module import.
            from .reusable import reusable_objects_from_metadata, reusable_source_id

            reusable_objects = reusable_objects_from_metadata(self.metadata)
            reusable_object_count = len(reusable_objects)
            reusable_ids = {reusable.id for reusable in reusable_objects}
            for node in self.nodes:
                reusable_id = reusable_source_id(node)
                if reusable_id is not None and reusable_id not in reusable_ids:
                    raise ValueError(
                        f"node {node.id!r} came from missing saved object "
                        f"{reusable_id!r}"
                    )
            for reusable in reusable_objects:
                reusable.validate(self.meshes, self.materials)
                reusable_library = transform_animation_library_from_metadata(
                    reusable.node.metadata
                )
                reusable_animation = transform_animation_from_metadata(
                    reusable.node.metadata
                )
                if "player" in reusable.node.tags:
                    raise ValueError(
                        f"saved object {reusable.id!r} cannot contain the unique Player"
                    )
                if reusable.node.metadata.get("packed_kinematic") is not None:
                    raise ValueError(
                        f"saved object {reusable.id!r} cannot contain a world-centred "
                        "Movement Pattern"
                    )
                if reusable.node.metadata.get("scatter_population") is not None:
                    raise ValueError(
                        f"saved object {reusable.id!r} cannot contain Populate Area"
                    )
                if reusable.node.metadata.get("polar_population") is not None:
                    raise ValueError(
                        f"saved object {reusable.id!r} cannot contain a world-centred "
                        "polar display population"
                    )
                if reusable_animation is not None:
                    if reusable.node.dynamic:
                        raise ValueError(
                            f"saved object {reusable.id!r} cannot combine Animation "
                            "with dynamic physics"
                        )
                    if any(
                        abs(float(value)) > 1.0e-12
                        for value in reusable.node.angular_velocity
                    ):
                        raise ValueError(
                            f"saved object {reusable.id!r} cannot combine Animation "
                            "with spin velocity"
                        )
                raw_binding = reusable.node.metadata.get("visual_graph")
                if raw_binding is None:
                    continue
                bindings = visual_graph_binding_ids(
                    raw_binding,
                    f"reusable object {reusable.id} visual_graph binding",
                )
                if graphs_valid:
                    unknown = sorted(set(bindings) - graph_ids)
                    if unknown:
                        raise ValueError(
                            f"reusable object {reusable.id!r} uses unknown Logic Blocks: "
                            + ", ".join(unknown)
                        )
                    graph_map = {graph.id: graph for graph in graphs}
                    owner_ids = {reusable.node.id} | {
                        node.id
                        for node in self.nodes
                        if reusable_source_id(node) == reusable.id
                    }
                    reference_fields = {"entity", "origin", "source", "target"}
                    for graph_id in bindings:
                        graph = graph_map[graph_id]
                        reusable_clips = (
                            {}
                            if reusable_library is None
                            else {
                                reusable.node.id: {
                                    clip.id for clip in reusable_library.clips
                                }
                            }
                        )
                        animation_messages = _animation_graph_messages(
                            (graph,),
                            {graph_id: {reusable.node.id}},
                            {reusable.node.id},
                            reusable_clips,
                        )
                        if animation_messages:
                            raise ValueError(animation_messages[0][1])
                        graph_nodes = {node.id: node for node in graph.nodes}
                        for graph_node in graph.nodes:
                            for key, value in graph_node.properties.items():
                                if (
                                    key in reference_fields
                                    and isinstance(value, str)
                                    and value in owner_ids
                                ):
                                    raise ValueError(
                                        f"saved object {reusable.id!r} Logic Blocks name "
                                        f"placed owner {value!r}; use owner-relative This object"
                                    )
                        for link in graph.links:
                            if link.target_port not in reference_fields:
                                continue
                            value_node = graph_nodes.get(link.source_node)
                            if (
                                value_node is not None
                                and value_node.type == "value.constant"
                                and isinstance(value_node.properties.get("value"), str)
                                and value_node.properties.get("value") in owner_ids
                            ):
                                raise ValueError(
                                    f"saved object {reusable.id!r} Logic Blocks feed a "
                                    "placed owner id into an object input; use owner-relative "
                                    "This object"
                                )
        except (TypeError, ValueError) as exc:
            error(
                "reusable.invalid",
                "metadata.reusable_objects",
                str(exc),
            )
        quality_ids: set[str] = set()
        for index, tier in enumerate(self.quality_tiers):
            try:
                tier.validate()
            except ValueError as exc:
                error("quality.invalid", f"quality_tiers[{index}]", str(exc))
            if tier.id in quality_ids:
                error("quality.duplicate", f"quality_tiers[{index}]", tier.id)
            quality_ids.add(tier.id)
        if self.start_quality not in quality_ids:
            error("quality.start", "start_quality", self.start_quality)
        target_ids: set[str] = set()
        for index, target in enumerate(self.target_profiles):
            try:
                target.validate()
            except ValueError as exc:
                error("target.invalid", f"target_profiles[{index}]", str(exc))
            if target.id in target_ids:
                error("target.duplicate", f"target_profiles[{index}]", target.id)
            target_ids.add(target.id)
            if target.default_quality not in quality_ids:
                error(
                    "target.quality",
                    f"target_profiles[{index}].default_quality",
                    target.default_quality,
                )
        if not self.target_profiles:
            error("target.missing", "target_profiles", "at least one target required")
        raw_saved_scenes = self.metadata.get("saved_scenes", ())
        raw_saved_scene_instances = self.metadata.get("saved_scene_instances", ())
        saved_scene_definition_count = (
            len(raw_saved_scenes)
            if isinstance(raw_saved_scenes, Sequence)
            and not isinstance(raw_saved_scenes, (str, bytes, bytearray))
            else 0
        )
        saved_scene_instance_count = (
            len(raw_saved_scene_instances)
            if isinstance(raw_saved_scene_instances, Sequence)
            and not isinstance(raw_saved_scene_instances, (str, bytes, bytearray))
            else 0
        )
        metrics = {
            "mesh_count": len(self.meshes),
            "material_count": len(self.materials),
            "node_count": len(self.nodes),
            "dynamic_node_count": sum(node.dynamic for node in self.nodes),
            "trigger_sensor_count": sensor_count,
            "vertex_count": sum(len(mesh.vertices) for mesh in self.meshes.values()),
            "triangle_count": sum(len(mesh.triangles) for mesh in self.meshes.values()),
            "quality_tier_count": len(self.quality_tiers),
            "target_profile_count": len(self.target_profiles),
            "visual_graph_count": len(graphs),
            "visual_graph_binding_count": binding_count,
            "packed_kinematic_profile_count": polar_profile_count,
            "packed_kinematic_component_count": polar_component_count,
            "scatter_population_count": scatter_group_count,
            "scatter_total_instance_count": scatter_total_instances,
            "scatter_generated_copy_count": scatter_generated_copies,
            "polar_population_count": polar_population_count,
            "polar_population_total_instance_count": polar_population_total_instances,
            "polar_population_generated_copy_count": polar_population_generated_copies,
            "reusable_object_count": reusable_object_count,
            "transform_animation_binding_count": animation_binding_count,
            "transform_animation_clip_count": animation_clip_count,
            "transform_animation_key_count": animation_key_count,
            "initial_state_key_count": initial_state_count,
            "saved_scene_definition_count": saved_scene_definition_count,
            "saved_scene_instance_count": saved_scene_instance_count,
        }
        if any(key in self.metadata for key in _SAVED_SCENE_METADATA_KEYS):
            try:
                materialized = _materialize_runtime_project(self)
                materialized_report = materialized.validate(raise_on_error=False)
            except (KeyError, TypeError, ValueError) as exc:
                error("saved_scene.invalid", "metadata.saved_scenes", str(exc))
            else:
                existing_issues = {
                    (issue.severity, issue.code, issue.path, issue.message)
                    for issue in issues
                }
                for issue in materialized_report.issues:
                    identity = (
                        issue.severity,
                        issue.code,
                        issue.path,
                        issue.message,
                    )
                    if identity not in existing_issues:
                        issues.append(issue)
                        existing_issues.add(identity)
                metrics = dict(materialized_report.metrics)
                metrics["authored_node_count"] = len(self.nodes)
                metrics["materialized_node_count"] = len(materialized.nodes)
                metrics["saved_scene_definition_count"] = len(
                    self.metadata.get("saved_scenes", ())
                )
                metrics["saved_scene_instance_count"] = len(
                    self.metadata.get("saved_scene_instances", ())
                )
        report = ProjectValidation3D(not issues, tuple(issues), metrics)
        if raise_on_error and not report.passed:
            raise ValueError(
                "; ".join(f"{i.code}@{i.path}: {i.message}" for i in issues)
            )
        return report

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "id": self.id, "title": self.title,
            "author": self.author, "edition": self.edition,
            "background": list(self.background), "camera": self.camera.to_dict(),
            "light": self.light.to_dict(), "world": self.world.to_dict(),
            "start_quality": self.start_quality,
            "quality_tiers": [tier.to_dict() for tier in self.quality_tiers],
            "target_profiles": [profile.to_dict() for profile in self.target_profiles],
            "materials": [
                self.materials[key].to_dict() for key in sorted(self.materials)
            ],
            "meshes": [self.meshes[key].to_dict() for key in sorted(self.meshes)],
            "nodes": [node.to_dict() for node in self.nodes],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], validate: bool = True
    ) -> "Mobile3DProject":
        project = cls(
            str(data["id"]), str(data["title"]), str(data.get("author", "")),
            {
                str(item["id"]): Mesh3DRecord.from_dict(item)
                for item in data.get("meshes", [])
            },
            {
                str(item["id"]): Material3DRecord.from_dict(item)
                for item in data.get("materials", [])
            },
            tuple(Node3DRecord.from_dict(item) for item in data.get("nodes", [])),
            Camera3DRecord.from_dict(data.get("camera")),
            DirectionalLight3DRecord.from_dict(data.get("light")),
            tuple(
                QualityTier3D.from_dict(item)
                for item in data.get("quality_tiers", [])
            ),
            tuple(
                AndroidTargetProfile.from_dict(item)
                for item in data.get("target_profiles", [])
            ),
            World3DSettings.from_dict(data.get("world")),
            str(data.get("start_quality", "balanced")),
            _values(data.get("background", (0.018, 0.03, 0.055, 1)), 4, "background"),
            str(data.get("schema", MOBILE3D_SCHEMA)),
            str(
                data.get(
                    "edition", "3.9.2 - K-Kij-T / Grove — Tom Klootwijk Signature Edition"
                )
            ),
            dict(data.get("metadata", {})),
        )
        if validate:
            project.validate()
        return project

    @classmethod
    def load(
        cls, path: str | Path, validate: bool = True
    ) -> "Mobile3DProject":
        return cls.from_dict(json.loads(Path(path).read_text("utf-8")), validate)

    @classmethod
    def load_packed(
        cls, path: str | Path, validate: bool = True
    ) -> "Mobile3DProject":
        """Load a compact, checksummed deployment copy of a 3D project."""
        return cls.from_dict(unpack_ecs_document(Path(path).read_bytes()), validate)

    def write(self, path: str | Path) -> Path:
        self.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        return path

    def write_packed(self, path: str | Path) -> Path:
        """Write compact runtime data while keeping JSON as the authoring format."""
        project = _materialize_runtime_project(self)
        project.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pack_ecs_document(project.to_dict()))
        return path

    def content_hash(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def material_map(self) -> dict[str, PBRMaterial]:
        return {key: value.to_pbr() for key, value in self.materials.items()}

    def to_scene(self) -> Scene:
        """Convert to the retained scene model without losing per-node materials."""
        project = _materialize_runtime_project(self)
        project.validate()
        scene = Scene(
            SceneMetadata(
                schema_version="3.9.1",
                determinism_profile="mobile-3d-reference",
            )
        )
        asset_ids: dict[tuple[str, str], str] = {}
        for node in project.nodes:
            key = (node.mesh_id, node.material_id)
            if key in asset_ids:
                continue
            record = project.meshes[node.mesh_id]
            asset_id = f"{node.mesh_id}__{node.material_id}"
            asset_ids[key] = asset_id
            scene.add_asset(
                Asset(
                    asset_id,
                    Mesh(
                        record.vertices, record.triangles, record.resolved_normals()
                    ),
                    node.material_id,
                    metadata={"source_mesh_id": node.mesh_id},
                )
            )
        hierarchy = build_hierarchy3d(project.nodes)
        node_by_id = {node.id: node for node in project.nodes}
        ordered_nodes = (
            project.nodes
            if not any(node.parent_id is not None for node in project.nodes)
            else tuple(node_by_id[node_id] for node_id in hierarchy.topological_order)
        )
        for node in ordered_nodes:
            scene.add_node(
                SceneNode(
                    node.id,
                    asset_ids[(node.mesh_id, node.material_id)],
                    parent_id=node.parent_id,
                    local_transform=node.transform.matrix(),
                    tags=frozenset(node.tags),
                    metadata={
                        **node.metadata,
                        "material_id": node.material_id,
                        "source_mesh_id": node.mesh_id,
                        "dynamic": node.dynamic,
                        "velocity": list(node.velocity),
                        "angular_velocity": list(node.angular_velocity),
                    },
                )
            )
        scatter_spec = collect_scatter_project_spec(project)
        for group in scatter_spec.groups:
            prototype = project.nodes[group.prototype_node_index]
            asset_id = asset_ids[(prototype.mesh_id, prototype.material_id)]
            for instance in scatter_instances(prototype, group):
                scene.add_node(
                    SceneNode(
                        scatter_instance_id(prototype.id, instance.lineage),
                        asset_id,
                        local_transform=compose_trs(
                            instance.translation, instance.rotation, instance.scale
                        ),
                        tags=frozenset({"decorative"}),
                        lineage=(
                            "scatter_population",
                            prototype.id,
                            str(instance.index),
                            f"{instance.lineage:016x}",
                        ),
                        metadata={
                            "render_only": True,
                            "population_prototype": prototype.id,
                            "population_index": instance.index,
                            "population_lineage": f"{instance.lineage:016x}",
                        },
                    )
                )
        return scene

    def instantiate_world(self) -> "GameWorld3D":
        project = _materialize_runtime_project(self)
        return GameWorld3D.from_project(project)


@dataclass(frozen=True)
class InputFrame3D:
    move_x: float = 0.0
    move_z: float = 0.0
    look_x: float = 0.0
    look_y: float = 0.0
    jump: bool = False
    action: bool = False
    previous_jump: bool = False
    previous_action: bool = False
    previous_move_x: float = 0.0
    previous_move_z: float = 0.0

    def value(self, action: str, default: float = 0.0) -> float:
        """Expose named actions to the shared visual-graph event nodes."""
        values = {
            "move_left": max(0.0, -float(self.move_x)),
            "move_right": max(0.0, float(self.move_x)),
            "move_up": max(0.0, -float(self.move_z)),
            "move_down": max(0.0, float(self.move_z)),
            "jump": float(bool(self.jump)),
            "action": float(bool(self.action)),
            "accept": float(bool(self.action)),
            "dash": float(bool(self.action)),
        }
        return float(values.get(str(action), default))

    def pressed(self, action: str) -> bool:
        current = abs(self.value(action)) >= 0.5
        previous_values = {
            "move_left": max(0.0, -float(self.previous_move_x)),
            "move_right": max(0.0, float(self.previous_move_x)),
            "move_up": max(0.0, -float(self.previous_move_z)),
            "move_down": max(0.0, float(self.previous_move_z)),
            "jump": float(bool(self.previous_jump)),
            "action": float(bool(self.previous_action)),
            "accept": float(bool(self.previous_action)),
            "dash": float(bool(self.previous_action)),
        }
        return current and abs(previous_values.get(str(action), 0.0)) < 0.5

    def with_previous(self, previous: "InputFrame3D") -> "InputFrame3D":
        """Return this frame with edge history supplied by its owning world."""
        return InputFrame3D(
            self.move_x,
            self.move_z,
            self.look_x,
            self.look_y,
            self.jump,
            self.action,
            previous.jump,
            previous.action,
            previous.move_x,
            previous.move_z,
        )

    def normalized(self) -> "InputFrame3D":
        x, z = float(self.move_x), float(self.move_z)
        length = math.hypot(x, z)
        if length > 1:
            x, z = x / length, z / length
        return InputFrame3D(
            _clamp(x, -1, 1), _clamp(z, -1, 1),
            _clamp(float(self.look_x), -1, 1),
            _clamp(float(self.look_y), -1, 1),
            bool(self.jump), bool(self.action),
            bool(self.previous_jump), bool(self.previous_action),
            _clamp(float(self.previous_move_x), -1, 1),
            _clamp(float(self.previous_move_z), -1, 1),
        )


@dataclass
class TransformComponent3D:
    position: Vec3
    rotation: Quat
    scale: Vec3

    @property
    def translation(self) -> Vec3:
        return self.position

    @translation.setter
    def translation(self, value: Sequence[float]) -> None:
        self.position = _values(value, 3, "transform translation")

    def validate(self) -> None:
        self.position = _values(self.position, 3, "transform position")
        self.rotation = quat_normalize(_values(self.rotation, 4, "transform rotation"))
        self.scale = _values(self.scale, 3, "transform scale")


class Vector3Value3D(list[float]):
    """Mutable JSON-like Vec3 view used by portable graph component aliases."""

    def __init__(self, values: Sequence[float]):
        super().__init__(_values(values, 3, "vector component"))

    @property
    def x(self) -> float:
        return self[0]

    @x.setter
    def x(self, value: float) -> None:
        self[0] = _finite_component_value(value)

    @property
    def y(self) -> float:
        return self[1]

    @y.setter
    def y(self, value: float) -> None:
        self[1] = _finite_component_value(value)

    @property
    def z(self) -> float:
        return self[2]

    @z.setter
    def z(self, value: float) -> None:
        self[2] = _finite_component_value(value)

    def validate(self) -> None:
        self[:] = _values(self, 3, "vector component")


def _finite_component_value(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("vector component must be finite")
    return result


@dataclass
class BodyComponent3D:
    velocity: Vec3
    angular_velocity: Vec3
    dynamic: bool
    mass: float
    restitution: float

    def validate(self) -> None:
        self.velocity = _values(self.velocity, 3, "body velocity")
        self.angular_velocity = _values(self.angular_velocity, 3, "body angular velocity")
        self.mass = _positive(self.mass, "body mass")
        if not 0 <= float(self.restitution) <= 1:
            raise ValueError("body restitution must be in [0,1]")


@dataclass
class ColliderComponent3D:
    shape: str = "none"
    radius: float = 0.5
    half_extents: Vec3 = (0.5, 0.5, 0.5)
    sensor: bool = False

    def validate(self) -> None:
        Collider3DRecord(
            str(self.shape), float(self.radius), _values(self.half_extents, 3, "collider half extents"), bool(self.sensor)
        ).validate()

    def to_record(self) -> Collider3DRecord:
        self.validate()
        return Collider3DRecord(str(self.shape), float(self.radius), tuple(self.half_extents), bool(self.sensor))


@dataclass
class RenderComponent3D:
    mesh_id: str
    material_id: str

    def validate(self) -> None:
        if not str(self.mesh_id) or not str(self.material_id):
            raise ValueError("render mesh and material ids are required")


_BUILTIN_POOL_FIELD_NAMES_3D = (
    "mesh_id",
    "material_id",
    "position",
    "rotation",
    "scale",
    "velocity",
    "angular_velocity",
    "collider",
    "dynamic",
    "mass",
    "restitution",
)


class _BuiltinComponentField3D:
    """Dataclass descriptor backed by detached values or one world pool."""

    __slots__ = ("_component_attribute", "_field_name", "_pool_name")

    def __init__(self, pool_name: str, component_attribute: str | None):
        self._pool_name = pool_name
        self._component_attribute = component_attribute
        self._field_name = ""

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self._field_name = name

    def _component(self, instance: Any) -> Any:
        owner = instance.__dict__.get("_component_owner")
        if owner is None:
            return None
        pool_id = instance.__dict__.get("_component_pool_id")
        if pool_id is None:
            raise RuntimeError("attached entity has no component-pool id")
        return owner._component_pool(self._pool_name)[pool_id]

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> Any:
        if instance is None:
            # Raising here tells dataclasses that this descriptor field has no
            # default, preserving the historical required constructor slots.
            raise AttributeError(self._field_name)
        component = self._component(instance)
        if component is None:
            return instance.__dict__[self._field_name]
        if self._component_attribute is None:
            return component
        return getattr(component, self._component_attribute)

    def __set__(self, instance: Any, value: Any) -> None:
        component = self._component(instance)
        if component is None:
            instance.__dict__[self._field_name] = value
        elif self._component_attribute is None:
            owner = instance.__dict__["_component_owner"]
            pool_id = instance.__dict__["_component_pool_id"]
            owner._component_pool(self._pool_name)[pool_id] = value
        else:
            setattr(component, self._component_attribute, value)


@dataclass
class EntityState3D:
    """Compatibility record whose spawned built-ins live in world-owned pools."""

    id: str
    mesh_id: str = _BuiltinComponentField3D("render", "mesh_id")
    material_id: str = _BuiltinComponentField3D("render", "material_id")
    position: Vec3 = _BuiltinComponentField3D("transform", "position")
    rotation: Quat = _BuiltinComponentField3D("transform", "rotation")
    scale: Vec3 = _BuiltinComponentField3D("transform", "scale")
    velocity: Vec3 = _BuiltinComponentField3D("body", "velocity")
    angular_velocity: Vec3 = _BuiltinComponentField3D("body", "angular_velocity")
    collider: Collider3DRecord = _BuiltinComponentField3D("collider", None)
    dynamic: bool = _BuiltinComponentField3D("body", "dynamic")
    mass: float = _BuiltinComponentField3D("body", "mass")
    restitution: float = _BuiltinComponentField3D("body", "restitution")
    tags: tuple[str, ...]
    grounded: bool = False
    alive: bool = True
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    extra_components: MutableMapping[str, Any] = field(default_factory=dict)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "extra_components":
            current = self.__dict__.get(name)
            if (
                isinstance(current, _SparseComponentsView3D)
                and self.__dict__.get("_component_owner") is not None
            ):
                current.replace_all(value)
                return
        object.__setattr__(self, name, value)

    def _detached_builtin_components(
        self,
    ) -> tuple[
        TransformComponent3D,
        BodyComponent3D,
        Collider3DRecord,
        RenderComponent3D,
    ]:
        if self.__dict__.get("_component_owner") is not None:
            raise ValueError(
                f"entity {self.id!r} already belongs to a GameWorld3D"
            )
        return (
            TransformComponent3D(self.position, self.rotation, self.scale),
            BodyComponent3D(
                self.velocity,
                self.angular_velocity,
                self.dynamic,
                self.mass,
                self.restitution,
            ),
            self.collider,
            RenderComponent3D(self.mesh_id, self.material_id),
        )

    def _attach_builtin_components(self, world: GameWorld3D, pool_id: str) -> None:
        if self.__dict__.get("_component_owner") is not None:
            raise ValueError(
                f"entity {self.id!r} already belongs to a GameWorld3D"
            )
        self.__dict__["_component_owner"] = world
        self.__dict__["_component_pool_id"] = pool_id
        for name in _BUILTIN_POOL_FIELD_NAMES_3D:
            self.__dict__.pop(name, None)

    def _detach_builtin_components(
        self,
        world: GameWorld3D,
        transform: TransformComponent3D,
        body: BodyComponent3D,
        collider: Collider3DRecord,
        render: RenderComponent3D,
    ) -> None:
        if self.__dict__.get("_component_owner") is not world:
            raise RuntimeError("entity is not attached to this GameWorld3D")
        del self.__dict__["_component_owner"]
        del self.__dict__["_component_pool_id"]
        self.__dict__.update(
            {
                "mesh_id": render.mesh_id,
                "material_id": render.material_id,
                "position": transform.position,
                "rotation": transform.rotation,
                "scale": transform.scale,
                "velocity": body.velocity,
                "angular_velocity": body.angular_velocity,
                "collider": collider,
                "dynamic": body.dynamic,
                "mass": body.mass,
                "restitution": body.restitution,
            }
        )

    def __copy__(self) -> EntityState3D:
        result = type(self).__new__(type(self))
        state = {
            name: value
            for name, value in self.__dict__.items()
            if name not in {"_component_owner", "_component_pool_id"}
        }
        if self.__dict__.get("_component_owner") is not None:
            state.update(
                {
                    name: getattr(self, name)
                    for name in _BUILTIN_POOL_FIELD_NAMES_3D
                }
            )
        result.__dict__.update(state)
        return result

    def __getstate__(self) -> dict[str, Any]:
        state = {
            name: value
            for name, value in self.__dict__.items()
            if name not in {"_component_owner", "_component_pool_id"}
        }
        if self.__dict__.get("_component_owner") is not None:
            state.update(
                {
                    name: getattr(self, name)
                    for name in _BUILTIN_POOL_FIELD_NAMES_3D
                }
            )
        if isinstance(state.get("extra_components"), _SparseComponentsView3D):
            state["extra_components"] = dict(self.extra_components)
        return state

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        self.__dict__.update(state)

    def __deepcopy__(self, memo: dict[int, Any]) -> EntityState3D:
        result = type(self).__new__(type(self))
        memo[id(self)] = result
        state = {
            name: copy.deepcopy(value, memo)
            for name, value in self.__dict__.items()
            if name not in {"_component_owner", "_component_pool_id"}
        }
        if self.__dict__.get("_component_owner") is not None:
            state.update(
                {
                    name: copy.deepcopy(getattr(self, name), memo)
                    for name in _BUILTIN_POOL_FIELD_NAMES_3D
                }
            )
        result.__dict__.update(state)
        return result

    @classmethod
    def from_node(cls, node: Node3DRecord) -> "EntityState3D":
        return cls(
            node.id, node.mesh_id, node.material_id,
            node.transform.translation, quat_normalize(node.transform.rotation),
            node.transform.scale, node.velocity, node.angular_velocity,
            node.collider, node.dynamic, node.mass, node.restitution, node.tags,
            metadata=dict(node.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "mesh_id": self.mesh_id,
            "material_id": self.material_id,
            "position": list(self.position), "rotation": list(self.rotation),
            "scale": list(self.scale), "velocity": list(self.velocity),
            "angular_velocity": list(self.angular_velocity),
            "collider": self.collider.to_dict(), "dynamic": self.dynamic,
            "mass": self.mass, "restitution": self.restitution,
            "tags": list(self.tags), "grounded": self.grounded,
            "alive": self.alive, "active": self.active,
            "metadata": self.metadata,
            "extra_components": {
                name: value.to_dict() if hasattr(value, "to_dict") else value
                for name, value in sorted(self.extra_components.items())
            },
        }


def _trigger_overlap_3d(sensor: EntityState3D, player: EntityState3D) -> bool:
    """Translation/scale-aligned sphere/box overlap shared with native Android."""
    sensor_shape, player_shape = sensor.collider.shape, player.collider.shape
    if sensor_shape == "none" or player_shape == "none":
        return False

    def sphere_radius(entity: EntityState3D) -> float:
        return entity.collider.radius * max(abs(value) for value in entity.scale)

    def box_extents(entity: EntityState3D) -> Vec3:
        return tuple(
            entity.collider.half_extents[index] * abs(entity.scale[index])
            for index in range(3)
        )  # type: ignore[return-value]

    if sensor_shape == player_shape == "sphere":
        radius = sphere_radius(sensor) + sphere_radius(player)
        delta = sub(sensor.position, player.position)
        return radius > 0.0 and dot(delta, delta) <= radius * radius
    if sensor_shape == player_shape == "box":
        first, second = box_extents(sensor), box_extents(player)
        return all(
            abs(sensor.position[index] - player.position[index])
            <= first[index] + second[index]
            for index in range(3)
        )

    sphere, box = (
        (sensor, player) if sensor_shape == "sphere" else (player, sensor)
    )
    radius, extents = sphere_radius(sphere), box_extents(box)
    nearest = tuple(
        max(-extents[index], min(extents[index], sphere.position[index] - box.position[index]))
        for index in range(3)
    )
    remainder = tuple(
        sphere.position[index] - box.position[index] - nearest[index]
        for index in range(3)
    )
    return radius > 0.0 and dot(remainder, remainder) <= radius * radius


def _compose_packed_kinematic_3d(
    entity: EntityState3D,
    component: PackedKinematicComponent,
    codec,
    lut,
) -> None:
    state = codec.cartesian_state(component, lut)
    x, z = state["position"]
    velocity_x, velocity_z = state["velocity"]
    entity.position = (x, entity.position[1], z)
    # Packed polar motion owns horizontal position and therefore also owns the
    # matching horizontal velocity used by collision response.  Y remains an
    # ordinary authored/gameplay axis.
    entity.velocity = (velocity_x, entity.velocity[1], velocity_z)
    entity.rotation = quat_from_axis_angle((0.0, 1.0, 0.0), state["pose"].heading)


def attach_packed_kinematics_3d(
    world: "GameWorld3D", spec: PolarProjectSpec
) -> bool:
    """Attach the sparse transform-authoritative polar system to a 3D world.

    Initial composition happens before Ready graphs.  Fixed-step advancement is
    priority -100 in pre-physics, matching Android's polar -> graph -> gameplay
    ordering while leaving authored Y, scale and all non-transform components.
    """
    profiles = {profile.id: profile.codec for profile in spec.profiles}
    luts = {profile.id: quantized_profile_lut(profile) for profile in spec.profiles}
    world._polar_codecs = profiles
    world._polar_luts = luts
    if not spec.components:
        return False
    for item in spec.components:
        entity = world.require(item.node_id)
        packed = PackedKinematicComponent(
            item.component.pose_word,
            item.component.motion_word,
            item.component.profile_id,
        )
        entity.extra_components["packed_kinematic"] = packed
        _compose_packed_kinematic_3d(
            entity, packed, profiles[packed.profile_id], luts[packed.profile_id]
        )

    def packed_polar_kinematics_3d(
        target_world: "GameWorld3D", dt: float, input_frame: InputFrame3D
    ) -> None:
        del input_frame
        for entity in target_world.query("packed_kinematic"):
            packed = entity.extra_components["packed_kinematic"]
            codec = profiles[packed.profile_id]
            advanced = codec.advance(packed, dt)
            entity.extra_components["packed_kinematic"] = advanced
            _compose_packed_kinematic_3d(
                entity, advanced, codec, luts[advanced.profile_id]
            )

    world.add_system(
        packed_polar_kinematics_3d,
        phase="pre_physics",
        priority=-100,
        name="packed_polar_kinematics_3d",
    )
    return True


@dataclass(frozen=True)
class WorldEvent3D:
    tick: int
    kind: str
    entity_a: str
    entity_b: str | None = None
    data: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick, "kind": self.kind,
            "entity_a": self.entity_a, "entity_b": self.entity_b,
            "data": self.data,
        }


@dataclass(order=True)
class _SystemEntry3D:
    priority: int
    name: str
    callback: Callable[["GameWorld3D", float, InputFrame3D], None] = field(compare=False)


_BUILTIN_COMPONENT_NAMES_3D = frozenset(
    {
        "transform",
        "body",
        "velocity",
        "angular_velocity",
        "alive",
        "active",
        "collider",
        "render",
        "entity",
    }
)

_BUILTIN_QUERY_POOL_NAMES_3D = {
    "transform": "transform",
    "body": "body",
    "velocity": "body",
    "angular_velocity": "body",
    "collider": "collider",
    "render": "render",
}


def _component_pool_name_3d(component_name: str) -> str | None:
    """Return the owning pool name for one query-visible component."""

    builtin_pool = _BUILTIN_QUERY_POOL_NAMES_3D.get(component_name)
    if builtin_pool is not None:
        return builtin_pool
    if component_name in _BUILTIN_COMPONENT_NAMES_3D:
        return None
    if component_name == "polar_movement":
        return "packed_kinematic"
    return component_name


@dataclass(frozen=True, slots=True)
class QueryPlanDiagnostics3D:
    """Read-only structural evidence for one live component-query plan."""

    candidate_component: str | None
    candidate_count: int
    total_entity_count: int


@dataclass(frozen=True, slots=True)
class QueryPlan3D:
    """Reusable normalized query shape backed by live component pools."""

    _world: "GameWorld3D" = field(repr=False)
    components: tuple[str, ...]
    tags: frozenset[str]
    active_only: bool
    _pool_components: tuple[str, ...] = field(repr=False)

    def execute(self) -> tuple[EntityState3D, ...]:
        return self._world._execute_query_plan(self)

    @property
    def diagnostics(self) -> QueryPlanDiagnostics3D:
        return self._world._query_plan_diagnostics(self)


class _SparseComponentsView3D(dict[str, Any]):
    """Real dict storage synchronized with world sparse query indexes.

    ``dataclasses.asdict`` reconstructs dict subclasses from an iterable of
    converted pairs.  The one-argument construction path deliberately returns
    a plain dict, preserving the historical ``EntityState3D`` output exactly.
    Live two-argument construction fills the dict base so C-level dict APIs,
    JSON encoding, reverse iteration, and held views retain normal semantics.
    """

    def __new__(
        cls, world_or_items: Any, entity_id: str | None = None
    ) -> _SparseComponentsView3D | dict[str, Any]:
        if entity_id is None:
            return dict(world_or_items)
        return super().__new__(cls)

    def __init__(self, world_or_items: Any, entity_id: str | None = None):
        if entity_id is None:
            return
        self._world = world_or_items
        self._entity_id = entity_id
        dict.__init__(
            self,
            (
                (
                    key,
                    self._world._get_sparse_component(self._entity_id, key),
                )
                for key in self._world._sparse_component_keys(self._entity_id)
            ),
        )

    def __setitem__(self, key: str, value: Any) -> None:
        self._world._set_sparse_component(self._entity_id, key, value)

    def __delitem__(self, key: str) -> None:
        self._world._remove_sparse_component(self._entity_id, key)

    def copy(self) -> dict[str, Any]:
        return dict.copy(self)

    def clear(self) -> None:
        for key in tuple(self):
            del self[key]

    def pop(self, key: str, *default: Any) -> Any:
        if len(default) > 1:
            raise TypeError(f"pop expected at most 2 arguments, got {len(default) + 1}")
        try:
            return self._world._remove_sparse_component(self._entity_id, key)
        except KeyError:
            if default:
                return default[0]
            raise

    def popitem(self) -> tuple[str, Any]:
        keys = self._world._sparse_component_keys(self._entity_id)
        if not keys:
            raise KeyError("popitem(): mapping is empty")
        key = keys[-1]
        return key, self._world._remove_sparse_component(self._entity_id, key)

    def setdefault(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            self[key] = default
            return default

    def update(self, *args: Any, **kwargs: Any) -> None:
        values = dict(*args, **kwargs)
        for key, value in values.items():
            self[key] = value

    def replace_all(self, values: Any) -> None:
        replacement = dict(values)
        next_pools = {
            name: dict(pool) for name, pool in self._world._sparse_components.items()
        }
        for name in self._world._sparse_component_order[self._entity_id]:
            pool = next_pools[name]
            del pool[self._entity_id]
            if not pool:
                del next_pools[name]
        for name, component in replacement.items():
            next_pools.setdefault(name, {})[self._entity_id] = component
        next_order = dict(self._world._sparse_component_order)
        next_order[self._entity_id] = list(replacement)

        previous = dict.copy(self)
        try:
            dict.clear(self)
            dict.update(self, replacement)
        except Exception:
            dict.clear(self)
            dict.update(self, previous)
            raise
        self._world._sparse_components = next_pools
        self._world._sparse_component_order = next_order

    def __ior__(self, other: Mapping[str, Any]):
        self.update(other)
        return self

    def __or__(self, other: Mapping[str, Any]) -> dict[str, Any]:
        result = self.copy()
        result.update(other)
        return result

    def __ror__(self, other: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(other)
        result.update(self)
        return result

    def __copy__(self) -> dict[str, Any]:
        return self.copy()

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return copy.deepcopy(self.copy(), memo)

    def __reduce_ex__(self, protocol: int):
        del protocol
        return dict, (self.copy(),)


@dataclass(slots=True)
class PolarPopulationRuntimeState:
    """Ephemeral visibility for render-only Make Many copies.

    Prototype entities remain ordinary ECS entities.  This sidecar deliberately
    never enters ``GameWorld3D.state``, component pools, snapshots, or hashes.
    """

    _copies_visible: dict[str, bool] = field(default_factory=dict)

    @property
    def prototype_ids(self) -> tuple[str, ...]:
        return tuple(self._copies_visible)

    def configure(self, prototype_ids: Sequence[str]) -> None:
        normalized = tuple(sorted(str(value) for value in prototype_ids))
        if any(not value for value in normalized):
            raise ValueError("Make Many prototype ids must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Make Many prototype ids must be unique")
        self._copies_visible = {value: True for value in normalized}

    def has_prototype(self, entity_id: str) -> bool:
        return str(entity_id) in self._copies_visible

    def copies_visible(self, entity_id: str) -> bool:
        target = str(entity_id)
        if target not in self._copies_visible:
            raise KeyError(f"object {target!r} has no Make Many recipe")
        return self._copies_visible[target]

    def set_copies_visible(self, entity_id: str, visible: bool) -> None:
        if not isinstance(visible, bool):
            raise TypeError("Make Many copy visibility must be true or false")
        target = str(entity_id)
        if target not in self._copies_visible:
            raise ValueError(
                f"Show or Hide Extra Copies target {target!r} has no Make Many recipe."
            )
        self._copies_visible[target] = visible


class GameWorld3D:
    """Deterministic 3D ECS facade with bounded arcade physics and graph systems.

    The historical ``EntityState3D`` record remains available for compatibility,
    while ``get/add_component/query`` expose editable component composition to the
    shared visual-graph runtime and authoring tools.
    """

    PHASES = ("input", "pre_physics", "post_physics", "update", "late")

    def __init__(self, settings: World3DSettings = World3DSettings()):
        settings.validate()
        self.settings = settings
        self.entities: dict[str, EntityState3D] = {}
        self._ordered_entity_ids: list[str] = []
        self._transform_components: dict[str, TransformComponent3D] = {}
        self._body_components: dict[str, BodyComponent3D] = {}
        self._collider_components: dict[str, Collider3DRecord] = {}
        self._render_components: dict[str, RenderComponent3D] = {}
        self._sparse_components: dict[str, dict[str, Any]] = {}
        self._sparse_component_order: dict[str, list[str]] = {}
        self._query_plans: dict[
            tuple[tuple[str, ...], frozenset[str], bool], QueryPlan3D
        ] = {}
        self.tick = 0
        self.time = 0.0
        self.events: list[WorldEvent3D] = []
        self.state: dict[str, Any] = {
            "score": 0, "finished": False, "health": 3
        }
        self._systems: dict[str, list[_SystemEntry3D]] = {
            phase: [] for phase in self.PHASES
        }
        self._listeners: dict[str, list[Callable[[WorldEvent3D], None]]] = {}
        self.visual_graph_bindings: list[Any] = []
        self.polar_population_runtime = PolarPopulationRuntimeState()
        self.transform_hierarchy_system: TransformHierarchySystem3D | None = None
        self._polar_codecs: dict[str, PackedKinematicCodec] = {}
        self._polar_luts: dict[str, PolarLookupTable] = {}
        self._previous_input_frame = InputFrame3D()
        self._trigger_contacts: tuple[tuple[str, str], ...] = ()

    def __deepcopy__(self, memo: dict[int, Any]) -> GameWorld3D:
        result = type(self).__new__(type(self))
        memo[id(self)] = result
        result.__dict__.update(copy.deepcopy(self.__dict__, memo))
        result._relink_entity_component_views()
        return result

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        self.__dict__.update(state)
        self._relink_entity_component_views()

    def _relink_entity_component_views(self) -> None:
        for entity_id, entity in self.entities.items():
            entity._attach_builtin_components(self, entity_id)
            object.__setattr__(
                entity,
                "extra_components",
                _SparseComponentsView3D(self, entity_id),
            )

    @classmethod
    def from_project(cls, project: Mobile3DProject) -> "GameWorld3D":
        project = _materialize_runtime_project(project)
        project.validate()
        world = cls(project.world)
        world.state.update(initial_state_from_metadata(project.metadata))
        polar_population_spec = collect_polar_population_project_spec(project)
        world.polar_population_runtime.configure(
            tuple(group.prototype_id for group in polar_population_spec.groups)
        )
        for node in project.nodes:
            world.spawn(EntityState3D.from_node(node))
        attach_packed_kinematics_3d(world, collect_polar_project_spec(project))
        attach_transform_animations_3d(
            world, collect_transform_animation_spec(project)
        )
        # Capture authored child-local TRS only after root-authoritative startup
        # adapters have composed, then produce the initial world hierarchy
        # before Ready graphs observe it.
        world.transform_hierarchy_system = attach_transform_hierarchy_3d(
            world, project.nodes
        )
        graphs = {graph.id: graph for graph in visual_graphs_from_metadata(project.metadata)}

        for node in project.nodes:
            for graph_id in sorted(
                visual_graph_binding_ids(node.metadata.get("visual_graph"))
            ):
                world.visual_graph_bindings.append(
                    attach_graph(
                        world,
                        graphs[graph_id],
                        entity_id=node.id,
                        phase="pre_physics",
                        run_ready=False,
                    )
                )
        for graph_id in sorted(
            visual_graph_binding_ids(project.metadata.get("world_graphs"))
        ):
            world.visual_graph_bindings.append(
                attach_graph(
                    world,
                    graphs[graph_id],
                    phase="pre_physics",
                    run_ready=False,
                )
            )
        run_ready_batch(world.visual_graph_bindings)
        # Ready may move an ancestor.  Return a settled world without allowing
        # those writes to leak authored-local children for one frame.
        if world.transform_hierarchy_system is not None:
            world.transform_hierarchy_system.recompose(world)
        return world

    def spawn(self, entity: EntityState3D) -> None:
        if entity.id in self.entities:
            raise ValueError(f"duplicate entity {entity.id}")
        transform, body, collider, render = entity._detached_builtin_components()
        initial_components = tuple(entity.extra_components.items())
        original_components = entity.extra_components
        self.entities[entity.id] = entity
        self._transform_components[entity.id] = transform
        self._body_components[entity.id] = body
        self._collider_components[entity.id] = collider
        self._render_components[entity.id] = render
        entity._attach_builtin_components(self, entity.id)
        self._sparse_component_order[entity.id] = []
        insert_at = bisect_left(self._ordered_entity_ids, entity.id)
        self._ordered_entity_ids.insert(insert_at, entity.id)
        try:
            for name, component in initial_components:
                self._set_sparse_component(entity.id, name, component)
            object.__setattr__(
                entity,
                "extra_components",
                _SparseComponentsView3D(self, entity.id),
            )
        except Exception:
            for name in tuple(self._sparse_component_order[entity.id]):
                self._remove_sparse_component(entity.id, name)
            del self._sparse_component_order[entity.id]
            self._ordered_entity_ids.pop(insert_at)
            del self.entities[entity.id]
            transform = self._transform_components.pop(entity.id)
            body = self._body_components.pop(entity.id)
            collider = self._collider_components.pop(entity.id)
            render = self._render_components.pop(entity.id)
            entity._detach_builtin_components(
                self, transform, body, collider, render
            )
            entity.extra_components = original_components
            raise

    def set_polar_population_copies_visible(
        self, entity_id: str, visible: bool
    ) -> None:
        """Set one Make Many sidecar flag without changing its real ECS prototype."""

        self.require(entity_id)
        self.polar_population_runtime.set_copies_visible(entity_id, visible)

    def _sparse_component_keys(self, entity_id: str) -> tuple[str, ...]:
        return tuple(self._sparse_component_order[entity_id])

    def _has_sparse_component(self, entity_id: str, name: object) -> bool:
        pool = self._sparse_components.get(name)  # type: ignore[arg-type]
        return pool is not None and entity_id in pool

    def _component_pool(self, name: str) -> Mapping[str, Any]:
        if name == "transform":
            return self._transform_components
        if name == "body":
            return self._body_components
        if name == "collider":
            return self._collider_components
        if name == "render":
            return self._render_components
        return self._sparse_components.get(name, {})

    def _get_sparse_component(self, entity_id: str, name: str) -> Any:
        pool = self._sparse_components.get(name)
        if pool is None or entity_id not in pool:
            raise KeyError(name)
        return pool[entity_id]

    def _set_sparse_component(
        self, entity_id: str, name: str, component: Any
    ) -> None:
        order = self._sparse_component_order[entity_id]
        pool = self._sparse_components.setdefault(name, {})
        entity = self.entities.get(entity_id)
        view = None if entity is None else entity.extra_components
        if entity_id in pool:
            previous = pool[entity_id]
            pool[entity_id] = component
            try:
                if isinstance(view, _SparseComponentsView3D):
                    dict.__setitem__(view, name, component)
            except Exception:
                pool[entity_id] = previous
                raise
            return
        order.append(name)
        try:
            pool[entity_id] = component
            if isinstance(view, _SparseComponentsView3D):
                dict.__setitem__(view, name, component)
        except Exception:
            pool.pop(entity_id, None)
            order.pop()
            if not pool:
                self._sparse_components.pop(name, None)
            raise

    def _remove_sparse_component(self, entity_id: str, name: str) -> Any:
        pool = self._sparse_components.get(name)
        if pool is None or entity_id not in pool:
            raise KeyError(name)
        order = self._sparse_component_order[entity_id]
        order_index = order.index(name)
        view = self.entities[entity_id].extra_components
        if isinstance(view, _SparseComponentsView3D):
            dict.__delitem__(view, name)
        component = pool.pop(entity_id)
        del order[order_index]
        if not pool:
            del self._sparse_components[name]
        return component

    def require(
        self, entity_id: str, component_or_name: type | str | None = None
    ) -> EntityState3D | Any:
        if entity_id not in self.entities:
            raise KeyError(entity_id)
        if component_or_name is None:
            return self.entities[entity_id]
        return self.require_component(entity_id, component_or_name)

    @staticmethod
    def _component_key(component_or_name: type | str) -> str:
        if isinstance(component_or_name, str):
            return component_or_name
        names = {
            TransformComponent3D: "transform",
            BodyComponent3D: "body",
            ColliderComponent3D: "collider",
            RenderComponent3D: "render",
            PackedKinematicComponent: "packed_kinematic",
            PolarMovementComponent3D: "polar_movement",
        }
        return names.get(component_or_name, component_or_name.__name__.lower())

    def get(
        self,
        entity_id: str,
        component_or_name: type | str,
        default: Any = None,
    ) -> Any:
        entity = self.entities.get(entity_id)
        if entity is None:
            return default
        name = self._component_key(component_or_name)
        if name == "transform":
            return TransformComponent3D(entity.position, entity.rotation, entity.scale)
        if name == "body":
            return BodyComponent3D(
                entity.velocity,
                entity.angular_velocity,
                entity.dynamic,
                entity.mass,
                entity.restitution,
            )
        if name == "velocity":
            return Vector3Value3D(entity.velocity)
        if name == "angular_velocity":
            return Vector3Value3D(entity.angular_velocity)
        if name == "alive":
            return entity.alive
        if name == "active":
            return entity.active
        if name == "collider":
            return ColliderComponent3D(
                entity.collider.shape,
                entity.collider.radius,
                entity.collider.half_extents,
                entity.collider.sensor,
            )
        if name == "render":
            return RenderComponent3D(entity.mesh_id, entity.material_id)
        if name == "polar_movement":
            packed = entity.extra_components.get("packed_kinematic")
            if packed is None:
                return default
            codec = self._polar_codecs.get(packed.profile_id)
            lut = self._polar_luts.get(packed.profile_id)
            if codec is None or lut is None:
                raise ValueError(
                    f"entity {entity_id} uses unknown polar movement profile "
                    f"{packed.profile_id!r}"
                )
            return polar_movement_from_component(packed, codec, lut)
        if name == "entity":
            return entity
        return entity.extra_components.get(name, default)

    def require_component(
        self, entity_id: str, component_or_name: type | str
    ) -> Any:
        component = self.get(entity_id, component_or_name)
        if component is None:
            raise KeyError(
                f"entity {entity_id} lacks component {self._component_key(component_or_name)}"
            )
        return component

    def validate_component_write(
        self, entity_id: str, component_name: str, field_path: str = ""
    ) -> None:
        """Guard generic writes against the packed polar authority boundary."""

        entity = self.require(entity_id)
        if "packed_kinematic" not in entity.extra_components:
            return
        component_name = str(component_name)
        field_path = str(field_path)
        if _packed_polar_write_is_safe(component_name, field_path):
            return
        target = f"{component_name}.{field_path}" if field_path else component_name
        raise ValueError(
            f"Cannot change {target} on {entity_id!r}: Movement Pattern owns X/Z "
            "position, facing rotation, X/Z velocity, and spin. Change Polar "
            "Movement fields instead; only Y position, Y velocity, and Scale "
            "remain ordinary settings."
        )

    def add_component(
        self,
        entity_id: str,
        component: Any,
        name: str | None = None,
        replace_existing: bool = False,
        *,
        _ownership_field_path: str | None = None,
    ) -> None:
        entity = self.require(entity_id)
        component_name = name or self._component_key(type(component))
        self.validate_component_write(
            entity_id,
            component_name,
            "" if _ownership_field_path is None else _ownership_field_path,
        )
        if component_name == "transform":
            value = component if isinstance(component, TransformComponent3D) else TransformComponent3D(
                tuple(component.get("position", component.get("translation", entity.position))),
                tuple(component.get("rotation", entity.rotation)),
                tuple(component.get("scale", entity.scale)),
            )
            value.validate()
            self._transform_components[entity_id] = value
            return
        if component_name == "body":
            value = component if isinstance(component, BodyComponent3D) else BodyComponent3D(
                tuple(component.get("velocity", entity.velocity)),
                tuple(component.get("angular_velocity", entity.angular_velocity)),
                bool(component.get("dynamic", entity.dynamic)),
                float(component.get("mass", entity.mass)),
                float(component.get("restitution", entity.restitution)),
            )
            value.validate()
            self._body_components[entity_id] = value
            return
        if component_name in {"velocity", "angular_velocity"}:
            value = tuple(Vector3Value3D(component))
            if component_name == "velocity":
                entity.velocity = value
            else:
                entity.angular_velocity = value
            return
        if component_name in {"alive", "active"}:
            if not isinstance(component, bool):
                raise TypeError(f"{component_name} component must be a boolean")
            setattr(entity, component_name, component)
            return
        if component_name == "collider":
            value = component if isinstance(component, ColliderComponent3D) else ColliderComponent3D(
                str(component.get("shape", entity.collider.shape)),
                float(component.get("radius", entity.collider.radius)),
                tuple(component.get("half_extents", entity.collider.half_extents)),
                bool(component.get("sensor", entity.collider.sensor)),
            )
            self._collider_components[entity_id] = value.to_record()
            return
        if component_name == "render":
            value = component if isinstance(component, RenderComponent3D) else RenderComponent3D(
                str(component.get("mesh_id", entity.mesh_id)),
                str(component.get("material_id", entity.material_id)),
            )
            value.validate()
            self._render_components[entity_id] = value
            return
        if component_name == "polar_movement":
            packed = entity.extra_components.get("packed_kinematic")
            if packed is None:
                raise ValueError(
                    f"entity {entity_id} has no packed movement to edit; choose a "
                    "Movement Pattern in the Inspector first"
                )
            codec = self._polar_codecs.get(packed.profile_id)
            lut = self._polar_luts.get(packed.profile_id)
            if codec is None or lut is None:
                raise ValueError(
                    f"entity {entity_id} uses unknown polar movement profile "
                    f"{packed.profile_id!r}"
                )
            updated = replace_polar_movement(packed, codec, component, lut)
            entity.extra_components["packed_kinematic"] = updated
            _compose_packed_kinematic_3d(entity, updated, codec, lut)
            return
        if component_name in entity.extra_components and not replace_existing:
            raise ValueError(f"entity {entity_id} already has component {component_name}")
        validate = getattr(component, "validate", None)
        if callable(validate):
            validate()
        entity.extra_components[component_name] = component

    def remove_component(self, entity_id: str, component_or_name: type | str) -> Any:
        name = self._component_key(component_or_name)
        if name in _BUILTIN_COMPONENT_NAMES_3D:
            raise ValueError(f"built-in 3D component {name} cannot be removed from the compatibility record")
        return self.require(entity_id).extra_components.pop(name)

    def compile_query(
        self,
        *component_types: type | str,
        tags: Sequence[str] = (),
        active_only: bool = True,
    ) -> QueryPlan3D:
        """Return a reusable plan whose membership and filters remain live."""

        # Component order has no query meaning.  Canonicalize it so callers
        # asking for the same set in a different order share one compact plan.
        names = tuple(
            sorted({self._component_key(item) for item in component_types})
        )
        required_tags = frozenset(tags)
        active = bool(active_only)
        cache_key = (names, required_tags, active)
        cached = self._query_plans.get(cache_key)
        if cached is not None:
            return cached
        pool_names = tuple(
            dict.fromkeys(
                pool_name
                for name in names
                if (pool_name := _component_pool_name_3d(name)) is not None
            )
        )
        plan = QueryPlan3D(self, names, required_tags, active, pool_names)
        self._query_plans[cache_key] = plan
        return plan

    def _query_plan_candidate(
        self, plan: QueryPlan3D
    ) -> tuple[str | None, tuple[str, ...]]:
        if not plan._pool_components:
            return None, tuple(self._ordered_entity_ids)
        candidate_name = min(
            plan._pool_components,
            key=lambda name: (len(self._component_pool(name)), name),
        )
        return candidate_name, tuple(
            sorted(self._component_pool(candidate_name))
        )

    def _query_plan_diagnostics(
        self, plan: QueryPlan3D
    ) -> QueryPlanDiagnostics3D:
        candidate_name, candidate_ids = self._query_plan_candidate(plan)
        return QueryPlanDiagnostics3D(
            candidate_name,
            len(candidate_ids),
            len(self._ordered_entity_ids),
        )

    def _execute_query_plan(
        self, plan: QueryPlan3D
    ) -> tuple[EntityState3D, ...]:
        _, candidate_ids = self._query_plan_candidate(plan)
        return tuple(
            entity
            for entity_id in candidate_ids
            if (entity := self.entities[entity_id]).alive
            and (entity.active or not plan.active_only)
            and plan.tags.issubset(entity.tags)
            and all(
                entity_id in self._component_pool(name)
                for name in plan._pool_components
            )
        )

    def query(
        self,
        *component_types: type | str,
        tags: Sequence[str] = (),
        active_only: bool = True,
    ) -> tuple[EntityState3D, ...]:
        return self.compile_query(
            *component_types, tags=tags, active_only=active_only
        ).execute()

    def add_system(
        self,
        callback: Callable[["GameWorld3D", float, InputFrame3D], None],
        *,
        phase: str = "update",
        priority: int = 0,
        name: str | None = None,
    ) -> None:
        if phase not in self._systems:
            raise ValueError(f"unknown system phase: {phase}")
        entry = _SystemEntry3D(
            int(priority), name or getattr(callback, "__name__", "system"), callback
        )
        self._systems[phase].append(entry)
        self._systems[phase].sort()

    def _run_systems(self, phase: str, frame: InputFrame3D) -> None:
        for system in tuple(self._systems[phase]):
            system.callback(self, self.settings.fixed_dt, frame)

    def on(self, kind: str, listener: Callable[[WorldEvent3D], None]) -> None:
        self._listeners.setdefault(str(kind), []).append(listener)

    def emit(
        self,
        kind: str,
        source: str | None = None,
        target: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> WorldEvent3D:
        event = WorldEvent3D(
            self.tick,
            str(kind),
            source or "world",
            target,
            dict(payload or {}),
        )
        self.events.append(event)
        for listener in (*self._listeners.get(event.kind, ()), *self._listeners.get("*", ())):
            listener(event)
        return event

    def despawn(self, entity_id: str) -> None:
        self.require(entity_id).alive = False

    def apply_force(self, entity_id: str, force: Sequence[float]) -> None:
        entity = self.require(entity_id)
        values = tuple(float(value) for value in force)
        if len(values) == 2:
            values = (values[0], 0.0, values[1])
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise ValueError("3D force must contain two XZ values or three XYZ values")
        if entity.dynamic:
            entity.velocity = add(entity.velocity, vscale(values, 1.0 / entity.mass))

    def _emit(
        self, kind: str, a: str, b: str | None = None, **data: Any
    ) -> None:
        self.emit(kind, source=a, target=b, payload=data)

    def _player(self, frame: InputFrame3D) -> None:
        frame = frame.normalized()
        for key in sorted(self.entities):
            entity = self.entities[key]
            if entity.alive and entity.active and "player" in entity.tags:
                entity.velocity = (
                    frame.move_x * self.settings.player_speed,
                    entity.velocity[1],
                    frame.move_z * self.settings.player_speed,
                )
                if frame.jump and entity.grounded:
                    entity.velocity = (
                        entity.velocity[0], self.settings.jump_speed,
                        entity.velocity[2],
                    )
                    entity.grounded = False
                    self._emit("jump", entity.id)

    def _integrate(self) -> None:
        dt = self.settings.fixed_dt
        for key in sorted(self.entities):
            entity = self.entities[key]
            if not entity.alive or not entity.active:
                continue
            if entity.dynamic:
                entity.velocity = add(
                    entity.velocity, vscale(self.settings.gravity, dt)
                )
                entity.position = add(
                    entity.position, vscale(entity.velocity, dt)
                )
            angular_speed = norm(entity.angular_velocity)
            if angular_speed > EPS:
                axis = vscale(entity.angular_velocity, 1 / angular_speed)
                entity.rotation = quat_normalize(
                    quat_mul(
                        quat_from_axis_angle(axis, angular_speed * dt),
                        entity.rotation,
                    )
                )

    def _floor_bounds(self) -> None:
        lo, hi = self.settings.bounds_min, self.settings.bounds_max
        for key in sorted(self.entities):
            entity = self.entities[key]
            if not entity.alive or not entity.active or not entity.dynamic:
                continue
            extent_y = entity.collider.vertical_extent(entity.scale)
            if entity.position[1] - extent_y < self.settings.floor_y:
                entity.position = (
                    entity.position[0], self.settings.floor_y + extent_y,
                    entity.position[2],
                )
                if entity.velocity[1] < 0:
                    bounce = -entity.velocity[1] * entity.restitution
                    entity.velocity = (
                        entity.velocity[0], 0.0 if bounce < 0.08 else bounce,
                        entity.velocity[2],
                    )
                    self._emit("floor_contact", entity.id)
                entity.grounded = abs(entity.velocity[1]) < 0.1
            else:
                entity.grounded = False
            p, v = list(entity.position), list(entity.velocity)
            radius = entity.collider.bounding_radius(entity.scale)
            for axis in (0, 2):
                minimum, maximum = lo[axis] + radius, hi[axis] - radius
                if p[axis] < minimum:
                    p[axis], v[axis] = minimum, abs(v[axis]) * entity.restitution
                    self._emit("bounds_contact", entity.id, axis=axis, side="min")
                elif p[axis] > maximum:
                    p[axis], v[axis] = maximum, -abs(v[axis]) * entity.restitution
                    self._emit("bounds_contact", entity.id, axis=axis, side="max")
            entity.position, entity.velocity = tuple(p), tuple(v)

    def _pairs(self) -> None:
        ids = [
            key for key in sorted(self.entities)
            if self.entities[key].alive and self.entities[key].active
        ]
        for index, a_id in enumerate(ids):
            a = self.entities[a_id]
            ra = a.collider.bounding_radius(a.scale)
            if ra <= 0 or a.collider.sensor:
                continue
            for b_id in ids[index + 1:]:
                b = self.entities[b_id]
                rb = b.collider.bounding_radius(b.scale)
                if rb <= 0 or b.collider.sensor or (not a.dynamic and not b.dynamic):
                    continue
                delta = sub(b.position, a.position)
                distance, target = norm(delta), ra + rb
                if distance >= target:
                    continue
                normal = (
                    (1.0, 0.0, 0.0)
                    if distance <= EPS else vscale(delta, 1 / distance)
                )
                penetration = target - distance
                inv_a = 1 / a.mass if a.dynamic else 0
                inv_b = 1 / b.mass if b.dynamic else 0
                total = inv_a + inv_b
                if total <= EPS:
                    continue
                if a.dynamic:
                    a.position = sub(
                        a.position, vscale(normal, penetration * inv_a / total)
                    )
                if b.dynamic:
                    b.position = add(
                        b.position, vscale(normal, penetration * inv_b / total)
                    )
                relative = dot(sub(b.velocity, a.velocity), normal)
                if relative < 0:
                    impulse = (
                        -(1 + min(a.restitution, b.restitution))
                        * relative / total
                    )
                    if a.dynamic:
                        a.velocity = sub(
                            a.velocity, vscale(normal, impulse * inv_a)
                        )
                    if b.dynamic:
                        b.velocity = add(
                            b.velocity, vscale(normal, impulse * inv_b)
                        )
                self._emit("collision", a_id, b_id, penetration=penetration)

    def _trigger_areas(self) -> None:
        """Emit one enter/exit transition for the first active player and each sensor."""
        player = next(
            (
                entity for entity in self.entities.values()
                if entity.alive and entity.active and "player" in entity.tags
            ),
            None,
        )
        current: list[tuple[str, str]] = []
        if player is not None:
            sensors = 0
            for entity in self.entities.values():
                if (
                    entity is player
                    or not entity.alive
                    or not entity.active
                    or not entity.collider.sensor
                    or entity.collider.shape == "none"
                ):
                    continue
                if sensors >= MAX_TRIGGER_SENSORS:
                    break
                sensors += 1
                if _trigger_overlap_3d(entity, player):
                    current.append((entity.id, player.id))

        current_contacts = tuple(current)
        current_set = set(current_contacts)
        previous_set = set(self._trigger_contacts)
        for sensor_id, player_id in self._trigger_contacts:
            if (sensor_id, player_id) not in current_set:
                self._emit(
                    "trigger_exit", sensor_id, player_id,
                    sensor=sensor_id, player=player_id,
                )
        for sensor_id, player_id in current_contacts:
            if (sensor_id, player_id) not in previous_set:
                self._emit(
                    "trigger_enter", sensor_id, player_id,
                    sensor=sensor_id, player=player_id,
                )
        self._trigger_contacts = current_contacts

    def _gameplay(self) -> None:
        players = [
            entity for entity in self.entities.values()
            if entity.alive and entity.active and "player" in entity.tags
        ]
        for key in sorted(self.entities):
            entity = self.entities[key]
            if not entity.alive or not entity.active:
                continue
            radius = entity.collider.bounding_radius(entity.scale)
            for player in players:
                touching = norm(sub(player.position, entity.position)) <= (
                    player.collider.bounding_radius(player.scale) + radius
                )
                if not touching:
                    continue
                if "collectible" in entity.tags:
                    entity.alive = False
                    self.state["score"] = int(self.state["score"]) + 1
                    self._emit(
                        "collected", player.id, entity.id,
                        score=self.state["score"],
                    )
                elif "goal" in entity.tags:
                    self.state["finished"] = True
                    self._emit("goal", player.id, entity.id)
                elif "hazard" in entity.tags:
                    self.state["health"] = max(
                        0, int(self.state["health"]) - 1
                    )
                    self._emit(
                        "damage", player.id, entity.id,
                        health=self.state["health"],
                    )

    def step(
        self, frame: InputFrame3D | None = None, steps: int = 1
    ) -> tuple[WorldEvent3D, ...]:
        if steps < 1:
            raise ValueError("steps must be positive")
        start = len(self.events)
        current_frame = (frame or InputFrame3D()).normalized()
        for _ in range(steps):
            frame = current_frame.with_previous(self._previous_input_frame)
            self._run_systems("input", frame)
            self._player(frame)
            self._run_systems("pre_physics", frame)
            self._integrate()
            self._floor_bounds()
            self._run_systems("post_physics", frame)
            self._pairs()
            self._trigger_areas()
            self._gameplay()
            self._run_systems("update", frame)
            self._run_systems("late", frame)
            # This endpoint is intentionally after every graph, physics,
            # gameplay and user-system transform writer in the fixed step.
            if self.transform_hierarchy_system is not None:
                self.transform_hierarchy_system.recompose(self)
            self.tick += 1
            self.time = self.tick * self.settings.fixed_dt
            self._previous_input_frame = current_frame
        return tuple(self.events[start:])

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "ugts-kc-game-world-3d-snapshot-3.9.1",
            "tick": self.tick, "time": self.time,
            "settings": self.settings.to_dict(), "state": self.state,
            "entities": [
                self.entities[key].to_dict() for key in sorted(self.entities)
            ],
            "events": [event.to_dict() for event in self.events],
        }

    def state_hash(self) -> str:
        return hashlib.sha256(_canonical(self.snapshot())).hexdigest()

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n")
        return path


def cube_mesh3d(mesh_id: str = "cube", size: float = 1.0) -> Mesh3DRecord:
    h = _positive(size, "cube size") * 0.5
    faces = (
        ((0, 0, 1), ((-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h))),
        ((0, 0, -1), ((h, -h, -h), (-h, -h, -h), (-h, h, -h), (h, h, -h))),
        ((1, 0, 0), ((h, -h, h), (h, -h, -h), (h, h, -h), (h, h, h))),
        ((-1, 0, 0), ((-h, -h, -h), (-h, -h, h), (-h, h, h), (-h, h, -h))),
        ((0, 1, 0), ((-h, h, h), (h, h, h), (h, h, -h), (-h, h, -h))),
        ((0, -1, 0), ((-h, -h, -h), (h, -h, -h), (h, -h, h), (-h, -h, h))),
    )
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    triangles: list[tuple[int, int, int]] = []
    for normal, points in faces:
        base = len(vertices)
        vertices.extend(points)
        normals.extend((normal,) * 4)
        triangles.extend(
            ((base, base + 1, base + 2), (base, base + 2, base + 3))
        )
    return Mesh3DRecord(
        mesh_id, tuple(vertices), tuple(triangles), tuple(normals),
        {"primitive": "cube", "size": h * 2},
    )


def plane_mesh3d(
    mesh_id: str = "plane", width: float = 1, depth: float = 1
) -> Mesh3DRecord:
    x = _positive(width, "plane width") * 0.5
    z = _positive(depth, "plane depth") * 0.5
    return Mesh3DRecord(
        mesh_id,
        ((-x, 0, -z), (x, 0, -z), (x, 0, z), (-x, 0, z)),
        ((0, 1, 2), (0, 2, 3)),
        ((0, 1, 0),) * 4,
        {"primitive": "plane"},
    )


def pyramid_mesh3d(
    mesh_id: str = "pyramid", size: float = 1, height: float = 1.4
) -> Mesh3DRecord:
    h = _positive(size, "pyramid size") * 0.5
    y = _positive(height, "pyramid height")
    vertices = (
        (-h, 0, -h), (h, 0, -h), (h, 0, h), (-h, 0, h), (0, y, 0)
    )
    triangles = (
        (0, 2, 1), (0, 3, 2), (0, 1, 4),
        (1, 2, 4), (2, 3, 4), (3, 0, 4),
    )
    return Mesh3DRecord(
        mesh_id, vertices, triangles, _computed_normals(vertices, triangles),
        {"primitive": "pyramid"},
    )


def uv_sphere_mesh3d(
    mesh_id: str = "sphere", radius: float = 0.5,
    segments: int = 20, rings: int = 12,
) -> Mesh3DRecord:
    radius = _positive(radius, "sphere radius")
    if segments < 3 or rings < 2:
        raise ValueError("sphere segments/rings too small")
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    for ring in range(rings + 1):
        phi = math.pi * ring / rings
        y, ring_radius = math.cos(phi), math.sin(phi)
        for segment in range(segments + 1):
            theta = math.tau * segment / segments
            normal = (
                ring_radius * math.cos(theta), y,
                ring_radius * math.sin(theta),
            )
            normals.append(normal)
            vertices.append(vscale(normal, radius))
    triangles: list[tuple[int, int, int]] = []
    stride = segments + 1
    for ring in range(rings):
        for segment in range(segments):
            a, b = ring * stride + segment, (ring + 1) * stride + segment
            if ring > 0:
                triangles.append((a, b, a + 1))
            if ring < rings - 1:
                triangles.append((a + 1, b, b + 1))
    return Mesh3DRecord(
        mesh_id, tuple(vertices), tuple(triangles), tuple(normals),
        {"primitive": "uv_sphere", "radius": radius},
    )
