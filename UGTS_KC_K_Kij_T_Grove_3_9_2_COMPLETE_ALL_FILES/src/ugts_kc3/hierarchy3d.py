"""Bounded retained transform hierarchies for the Mobile 3D runtime.

The first retained-hierarchy slice deliberately stays small: authored child
transforms are parent-local, roots remain ordinary world-space entities, and a
parent must have positive uniform scale.  The latter rule keeps TRS composition
closed (no shear matrix needs to be introduced) and is checked both while
authoring and whenever a moving hierarchy is recomposed at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

from .math3d import EPS, add, quat_inverse, quat_mul, quat_normalize, quat_rotate

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]

MAX_HIERARCHY_DEPTH_3D = 8
_SCALE_REL_TOL = 1.0e-9
_SCALE_ABS_TOL = 1.0e-10


@dataclass(frozen=True)
class HierarchyIssue3D:
    """One deterministic hierarchy validation issue."""

    code: str
    node_id: str
    message: str


class Hierarchy3DError(ValueError):
    """Raised when a retained hierarchy cannot be represented safely."""

    def __init__(self, issue: HierarchyIssue3D):
        self.issue = issue
        self.code = issue.code
        self.node_id = issue.node_id
        super().__init__(issue.message)


@dataclass(frozen=True)
class TransformTRS3D:
    """Dependency-free translation/rotation/scale value used by hierarchy math."""

    translation: Vec3 = (0.0, 0.0, 0.0)
    rotation: Quat = (1.0, 0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)

    @property
    def position(self) -> Vec3:
        """Runtime-friendly alias for :attr:`translation`."""

        return self.translation

    @classmethod
    def from_value(cls, value: Any) -> "TransformTRS3D":
        if isinstance(value, cls):
            return value.normalized()
        if isinstance(value, Mapping):
            translation = value.get("translation", value.get("position", (0, 0, 0)))
            rotation = value.get("rotation", (1, 0, 0, 0))
            scale = value.get("scale", (1, 1, 1))
        else:
            translation = getattr(value, "translation", getattr(value, "position", None))
            rotation = getattr(value, "rotation", None)
            scale = getattr(value, "scale", None)
            if translation is None or rotation is None or scale is None:
                raise TypeError("transform must provide translation/position, rotation and scale")
        return cls(
            _values(translation, 3, "translation"),
            quat_normalize(_values(rotation, 4, "rotation")),
            _values(scale, 3, "scale"),
        )

    def normalized(self) -> "TransformTRS3D":
        return TransformTRS3D(
            _values(self.translation, 3, "translation"),
            quat_normalize(_values(self.rotation, 4, "rotation")),
            _values(self.scale, 3, "scale"),
        )


@dataclass(frozen=True)
class Hierarchy3D:
    """Canonical, parent-before-child view of a validated node collection."""

    parent_by_id: dict[str, str | None]
    children_by_id: dict[str, tuple[str, ...]]
    depth_by_id: dict[str, int]
    roots: tuple[str, ...]
    topological_order: tuple[str, ...]

    def _require(self, node_id: str) -> str:
        value = str(node_id)
        if value not in self.parent_by_id:
            raise KeyError(value)
        return value

    def parent(self, node_id: str) -> str | None:
        return self.parent_by_id[self._require(node_id)]

    def children(self, node_id: str) -> tuple[str, ...]:
        return self.children_by_id[self._require(node_id)]

    def depth(self, node_id: str) -> int:
        return self.depth_by_id[self._require(node_id)]

    def descendants(self, node_id: str) -> tuple[str, ...]:
        root = self._require(node_id)
        result: list[str] = []

        def visit(parent_id: str) -> None:
            for child_id in self.children_by_id[parent_id]:
                result.append(child_id)
                visit(child_id)

        visit(root)
        return tuple(result)

    def is_descendant(self, node_id: str, possible_ancestor: str) -> bool:
        current = self.parent(self._require(node_id))
        ancestor = self._require(possible_ancestor)
        while current is not None:
            if current == ancestor:
                return True
            current = self.parent_by_id[current]
        return False


def _values(raw: Iterable[float], count: int, label: str) -> tuple[float, ...]:
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain {count} finite numbers") from exc
    if len(values) != count or not all(math.isfinite(value) for value in values):
        raise ValueError(f"{label} must contain {count} finite numbers")
    return values


def is_uniform_positive_scale_3d(scale: Sequence[float]) -> bool:
    """Return whether *scale* is a positive scalar represented as XYZ."""

    try:
        values = _values(scale, 3, "parent scale")
    except ValueError:
        return False
    return (
        all(value > EPS for value in values)
        and math.isclose(
            values[0], values[1], rel_tol=_SCALE_REL_TOL, abs_tol=_SCALE_ABS_TOL
        )
        and math.isclose(
            values[1], values[2], rel_tol=_SCALE_REL_TOL, abs_tol=_SCALE_ABS_TOL
        )
    )


def _require_uniform_positive_parent(transform: TransformTRS3D) -> float:
    if not is_uniform_positive_scale_3d(transform.scale):
        raise ValueError("hierarchy parent scale must be uniform and positive")
    return float(transform.scale[0])


def compose_world_trs_3d(parent: Any, local: Any) -> TransformTRS3D:
    """Compose a parent world TRS with one parent-local TRS.

    A uniform positive parent scale is required so the result remains an exact
    TRS even when the child has its own rotation or non-uniform scale.
    """

    parent_trs = TransformTRS3D.from_value(parent)
    local_trs = TransformTRS3D.from_value(local)
    parent_scale = _require_uniform_positive_parent(parent_trs)
    offset = quat_rotate(
        parent_trs.rotation,
        tuple(parent_scale * value for value in local_trs.translation),
    )
    return TransformTRS3D(
        tuple(add(parent_trs.translation, offset)),  # type: ignore[arg-type]
        quat_normalize(quat_mul(parent_trs.rotation, local_trs.rotation)),
        tuple(parent_scale * value for value in local_trs.scale),  # type: ignore[arg-type]
    )


def local_trs_from_world_3d(parent_world: Any, world: Any) -> TransformTRS3D:
    """Return the local TRS that preserves *world* under *parent_world*."""

    parent_trs = TransformTRS3D.from_value(parent_world)
    world_trs = TransformTRS3D.from_value(world)
    parent_scale = _require_uniform_positive_parent(parent_trs)
    inverse_rotation = quat_inverse(parent_trs.rotation)
    delta = tuple(
        world_trs.translation[index] - parent_trs.translation[index]
        for index in range(3)
    )
    local_translation = tuple(
        value / parent_scale for value in quat_rotate(inverse_rotation, delta)
    )
    return TransformTRS3D(
        local_translation,  # type: ignore[arg-type]
        quat_normalize(quat_mul(inverse_rotation, world_trs.rotation)),
        tuple(value / parent_scale for value in world_trs.scale),  # type: ignore[arg-type]
    )


# Readable editor-facing alias: the first argument is the desired world pose.
def local_transform_for_parent_3d(world: Any, parent_world: Any) -> TransformTRS3D:
    return local_trs_from_world_3d(parent_world, world)


def _node_id(node: Any) -> str:
    return str(getattr(node, "id"))


def _parent_id(node: Any) -> str | None:
    raw = getattr(node, "parent_id", None)
    return None if raw is None else str(raw)


def _structural_issues(
    nodes: Sequence[Any], max_depth: int
) -> tuple[HierarchyIssue3D, ...]:
    if (
        isinstance(max_depth, bool)
        or not isinstance(max_depth, int)
        or max_depth < 0
    ):
        raise ValueError("hierarchy max depth must be a nonnegative integer")
    ids = [_node_id(node) for node in nodes]
    issues: list[HierarchyIssue3D] = []
    counts: dict[str, int] = {}
    for node_id in ids:
        counts[node_id] = counts.get(node_id, 0) + 1
    for node_id in sorted(key for key, count in counts.items() if count > 1):
        issues.append(
            HierarchyIssue3D(
                "duplicate", node_id, f"hierarchy contains duplicate node id {node_id!r}"
            )
        )
    if issues:
        return tuple(issues)

    parent_by_id = {_node_id(node): _parent_id(node) for node in nodes}
    for node_id in sorted(parent_by_id):
        parent_id = parent_by_id[node_id]
        if parent_id is not None and parent_id not in parent_by_id:
            issues.append(
                HierarchyIssue3D(
                    "parent_missing",
                    node_id,
                    f"node {node_id!r} uses missing parent {parent_id!r}",
                )
            )
    if issues:
        return tuple(issues)

    depths: dict[str, int] = {}
    cycle_nodes: set[str] = set()
    for node_id in sorted(parent_by_id):
        if node_id in depths:
            continue
        trail: list[str] = []
        trail_index: dict[str, int] = {}
        current: str | None = node_id
        while current is not None and current not in depths:
            if current in trail_index:
                cycle_nodes.update(trail[trail_index[current] :])
                break
            trail_index[current] = len(trail)
            trail.append(current)
            current = parent_by_id[current]
        if cycle_nodes:
            continue
        depth = -1 if current is None else depths[current]
        for current in reversed(trail):
            depth += 1
            depths[current] = depth
    if cycle_nodes:
        first = min(cycle_nodes)
        return (
            HierarchyIssue3D(
                "cycle", first, f"hierarchy contains a parent cycle involving {first!r}"
            ),
        )
    for node_id in sorted(depths):
        if depths[node_id] > max_depth:
            issues.append(
                HierarchyIssue3D(
                    "depth",
                    node_id,
                    f"node {node_id!r} is at depth {depths[node_id]}; maximum is {max_depth}",
                )
            )
    return tuple(issues)


def _canonical_graph(nodes: Sequence[Any]) -> Hierarchy3D:
    parent_by_id = {
        node_id: parent_id
        for node_id, parent_id in sorted(
            ((_node_id(node), _parent_id(node)) for node in nodes),
            key=lambda pair: pair[0],
        )
    }
    mutable_children: dict[str, list[str]] = {
        node_id: [] for node_id in parent_by_id
    }
    for node_id, parent_id in parent_by_id.items():
        if parent_id is not None:
            mutable_children[parent_id].append(node_id)
    children_by_id = {
        node_id: tuple(sorted(mutable_children[node_id]))
        for node_id in parent_by_id
    }
    roots = tuple(
        node_id for node_id, parent_id in parent_by_id.items() if parent_id is None
    )
    depth_by_id: dict[str, int] = {}
    ordered: list[str] = []

    def visit(node_id: str, depth: int) -> None:
        depth_by_id[node_id] = depth
        ordered.append(node_id)
        for child_id in children_by_id[node_id]:
            visit(child_id, depth + 1)

    for root_id in roots:
        visit(root_id, 0)
    return Hierarchy3D(
        parent_by_id,
        children_by_id,
        {node_id: depth_by_id[node_id] for node_id in parent_by_id},
        roots,
        tuple(ordered),
    )


def hierarchy_issues3d(
    nodes: Sequence[Any], *, max_depth: int = MAX_HIERARCHY_DEPTH_3D
) -> tuple[HierarchyIssue3D, ...]:
    """Return structural and first-slice capability issues in stable order."""

    values = tuple(nodes)
    structural = _structural_issues(values, max_depth)
    issues = list(structural)
    if structural:
        return tuple(issues)
    hierarchy = _canonical_graph(values)
    by_id = {_node_id(node): node for node in values}

    for node_id in hierarchy.topological_order:
        node = by_id[node_id]
        if hierarchy.children_by_id[node_id] and not is_uniform_positive_scale_3d(
            getattr(getattr(node, "transform"), "scale")
        ):
            issues.append(
                HierarchyIssue3D(
                    "parent_scale",
                    node_id,
                    f"hierarchy parent {node_id!r} must have uniform positive authored scale",
                )
            )
        if hierarchy.parent_by_id[node_id] is None:
            continue
        if bool(getattr(node, "dynamic", False)):
            issues.append(
                HierarchyIssue3D(
                    "child_dynamic", node_id, f"hierarchy child {node_id!r} cannot be dynamic"
                )
            )
        collider = getattr(node, "collider", None)
        if (
            collider is None
            or str(getattr(collider, "shape", "none")) != "none"
            or bool(getattr(collider, "sensor", False))
        ):
            issues.append(
                HierarchyIssue3D(
                    "child_collider",
                    node_id,
                    f"hierarchy child {node_id!r} must use a non-sensor none collider",
                )
            )
        try:
            child_tags = tuple(getattr(node, "tags", ()))
        except TypeError:
            child_tags = ()
        if child_tags:
            issues.append(
                HierarchyIssue3D(
                    "child_tags", node_id, f"hierarchy child {node_id!r} must be tagless"
                )
            )
        try:
            angular_velocity = _values(
                getattr(node, "angular_velocity", (0, 0, 0)),
                3,
                "angular velocity",
            )
        except ValueError:
            # The record validator owns malformed component diagnostics.  Do
            # not turn its collected project issue into a hierarchy crash.
            angular_velocity = (0.0, 0.0, 0.0)
        if any(abs(value) > EPS for value in angular_velocity):
            issues.append(
                HierarchyIssue3D(
                    "child_angular_velocity",
                    node_id,
                    f"hierarchy child {node_id!r} must have zero angular velocity",
                )
            )
        metadata = getattr(node, "metadata", {})
        metadata = metadata if isinstance(metadata, Mapping) else {}
        raw_binding = metadata.get("visual_graph")
        if raw_binding not in (None, "", (), []):
            issues.append(
                HierarchyIssue3D(
                    "child_visual_graph",
                    node_id,
                    f"hierarchy child {node_id!r} cannot bind a visual graph",
                )
            )
        for key, code, label in (
            ("packed_kinematic", "child_packed_movement", "packed movement"),
            ("scatter_population", "child_population", "a scatter population"),
            ("transform_animation", "child_transform_animation", "transform animation"),
            (
                "transform_animation_library",
                "child_transform_animation",
                "transform animation",
            ),
        ):
            if metadata.get(key) is not None:
                issues.append(
                    HierarchyIssue3D(
                        code,
                        node_id,
                        f"hierarchy child {node_id!r} cannot use {label}",
                    )
                )
    return tuple(issues)


def build_hierarchy3d(
    nodes: Sequence[Any], *, max_depth: int = MAX_HIERARCHY_DEPTH_3D
) -> Hierarchy3D:
    """Validate and return the canonical retained hierarchy for *nodes*."""

    values = tuple(nodes)
    issues = hierarchy_issues3d(values, max_depth=max_depth)
    if issues:
        raise Hierarchy3DError(issues[0])
    return _canonical_graph(values)


def world_trs_by_id(
    nodes: Sequence[Any], hierarchy: Hierarchy3D | None = None
) -> dict[str, TransformTRS3D]:
    """Compose authored local transforms into canonical world TRS values."""

    values = tuple(nodes)
    graph = hierarchy or build_hierarchy3d(values)
    by_id = {_node_id(node): node for node in values}
    if set(by_id) != set(graph.parent_by_id):
        raise ValueError("hierarchy does not describe the supplied nodes")
    result: dict[str, TransformTRS3D] = {}
    for node_id in graph.topological_order:
        local = TransformTRS3D.from_value(getattr(by_id[node_id], "transform"))
        parent_id = graph.parent_by_id[node_id]
        result[node_id] = (
            local
            if parent_id is None
            else compose_world_trs_3d(result[parent_id], local)
        )
    return result


def world_transforms_3d(
    nodes: Sequence[Any], hierarchy: Hierarchy3D | None = None
) -> dict[str, TransformTRS3D]:
    """Alias for :func:`world_trs_by_id` used by editor viewports."""

    return world_trs_by_id(nodes, hierarchy)


def _replace_node_transform(node: Any, transform: TransformTRS3D) -> Any:
    authored = getattr(node, "transform")
    authored = replace(
        authored,
        translation=transform.translation,
        rotation=transform.rotation,
        scale=transform.scale,
    )
    return replace(node, transform=authored)


ReparentAuthorization3D = Callable[[str, str | None], bool]


def reparent_node3d(
    nodes: Sequence[Any],
    node_id: str,
    parent_id: str | None,
    *,
    preserve_world: bool = True,
    max_depth: int = MAX_HIERARCHY_DEPTH_3D,
    allow: ReparentAuthorization3D | None = None,
) -> tuple[Any, ...]:
    """Return records with one node reparented, optionally preserving world TRS."""

    values = tuple(nodes)
    graph = build_hierarchy3d(values, max_depth=max_depth)
    node_id = str(node_id)
    parent_id = None if parent_id is None else str(parent_id)
    if node_id not in graph.parent_by_id:
        raise KeyError(node_id)
    if parent_id is not None and parent_id not in graph.parent_by_id:
        raise KeyError(parent_id)
    if allow is not None and not bool(allow(node_id, parent_id)):
        raise PermissionError(f"reparenting {node_id!r} under {parent_id!r} is not allowed")
    if parent_id == node_id or (
        parent_id is not None and graph.is_descendant(parent_id, node_id)
    ):
        raise Hierarchy3DError(
            HierarchyIssue3D(
                "cycle", node_id, f"reparenting {node_id!r} would create a parent cycle"
            )
        )
    worlds = world_trs_by_id(values, graph) if preserve_world else {}
    replacement_by_id: dict[str, Any] = {}
    for node in values:
        if _node_id(node) != node_id:
            continue
        replacement = replace(node, parent_id=parent_id)
        if preserve_world:
            local = (
                worlds[node_id]
                if parent_id is None
                else local_trs_from_world_3d(worlds[parent_id], worlds[node_id])
            )
            replacement = _replace_node_transform(replacement, local)
        replacement_by_id[node_id] = replacement
    result = tuple(replacement_by_id.get(_node_id(node), node) for node in values)
    build_hierarchy3d(result, max_depth=max_depth)
    return result


def remove_node3d_promote_children(
    nodes: Sequence[Any],
    node_id: str,
    *,
    preserve_world: bool = True,
    max_depth: int = MAX_HIERARCHY_DEPTH_3D,
    allow: ReparentAuthorization3D | None = None,
) -> tuple[Any, ...]:
    """Delete one node and promote its direct children to the deleted parent."""

    values = tuple(nodes)
    graph = build_hierarchy3d(values, max_depth=max_depth)
    node_id = str(node_id)
    if node_id not in graph.parent_by_id:
        raise KeyError(node_id)
    promoted_parent = graph.parent_by_id[node_id]
    direct_children = graph.children_by_id[node_id]
    if allow is not None:
        for child_id in direct_children:
            if not bool(allow(child_id, promoted_parent)):
                raise PermissionError(
                    f"promoting {child_id!r} under {promoted_parent!r} is not allowed"
                )
    worlds = world_trs_by_id(values, graph) if preserve_world else {}
    result: list[Any] = []
    for node in values:
        current_id = _node_id(node)
        if current_id == node_id:
            continue
        if current_id not in direct_children:
            result.append(node)
            continue
        replacement = replace(node, parent_id=promoted_parent)
        if preserve_world:
            local = (
                worlds[current_id]
                if promoted_parent is None
                else local_trs_from_world_3d(
                    worlds[promoted_parent], worlds[current_id]
                )
            )
            replacement = _replace_node_transform(replacement, local)
        result.append(replacement)
    candidate = tuple(result)
    build_hierarchy3d(candidate, max_depth=max_depth)
    return candidate


@dataclass(frozen=True)
class TransformHierarchySystem3D:
    """Desktop adapter that retains authored child locals across world updates."""

    hierarchy: Hierarchy3D
    authored_local_by_id: dict[str, TransformTRS3D]

    @classmethod
    def from_nodes(cls, nodes: Sequence[Any]) -> "TransformHierarchySystem3D":
        values = tuple(nodes)
        hierarchy = build_hierarchy3d(values)
        return cls(
            hierarchy,
            {
                _node_id(node): TransformTRS3D.from_value(getattr(node, "transform"))
                for node in values
                if _parent_id(node) is not None
            },
        )

    def recompose(self, world: Any) -> None:
        for node_id in self.hierarchy.topological_order:
            parent_id = self.hierarchy.parent_by_id[node_id]
            if parent_id is None:
                continue
            parent = world.require(parent_id)
            child = world.require(node_id)
            composed = compose_world_trs_3d(
                TransformTRS3D(parent.position, parent.rotation, parent.scale),
                self.authored_local_by_id[node_id],
            )
            child.position = composed.translation
            child.rotation = composed.rotation
            child.scale = composed.scale

    def __call__(self, world: Any, dt: float = 0.0, input_frame: Any = None) -> None:
        del dt, input_frame
        self.recompose(world)


def attach_transform_hierarchy_3d(
    world: Any, nodes: Sequence[Any]
) -> TransformHierarchySystem3D | None:
    """Capture child locals, register the late adapter, and compose initial world TRS."""

    values = tuple(nodes)
    if not any(_parent_id(node) is not None for node in values):
        return None
    system = TransformHierarchySystem3D.from_nodes(values)
    system.recompose(world)
    world.add_system(
        system,
        phase="late",
        priority=2_147_483_647,
        name="transform_hierarchy_3d",
    )
    return system


__all__ = [
    "Hierarchy3D",
    "Hierarchy3DError",
    "HierarchyIssue3D",
    "MAX_HIERARCHY_DEPTH_3D",
    "ReparentAuthorization3D",
    "TransformHierarchySystem3D",
    "TransformTRS3D",
    "attach_transform_hierarchy_3d",
    "build_hierarchy3d",
    "compose_world_trs_3d",
    "hierarchy_issues3d",
    "is_uniform_positive_scale_3d",
    "local_transform_for_parent_3d",
    "local_trs_from_world_3d",
    "remove_node3d_promote_children",
    "reparent_node3d",
    "world_transforms_3d",
    "world_trs_by_id",
]
