"""Conventional spatial acceleration integrated with UGTS support/compatibility pruning."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable, Sequence

from .math3d import EPS, add, dot, scale, sub, transform_point

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class AABB:
    minimum: Vec3
    maximum: Vec3

    def __post_init__(self):
        if any(self.minimum[i] > self.maximum[i] for i in range(3)):
            raise ValueError("AABB minimum must not exceed maximum")
        if not all(math.isfinite(v) for v in self.minimum + self.maximum):
            raise ValueError("AABB coordinates must be finite")

    @classmethod
    def from_points(cls, points: Sequence[Vec3]) -> "AABB":
        if not points:
            raise ValueError("points required")
        return cls(
            tuple(min(p[i] for p in points) for i in range(3)),
            tuple(max(p[i] for p in points) for i in range(3)),
        )

    def union(self, other: "AABB") -> "AABB":
        return AABB(
            tuple(min(self.minimum[i], other.minimum[i]) for i in range(3)),
            tuple(max(self.maximum[i], other.maximum[i]) for i in range(3)),
        )

    def intersects(self, other: "AABB") -> bool:
        return all(self.minimum[i] <= other.maximum[i] and self.maximum[i] >= other.minimum[i] for i in range(3))

    def contains(self, point: Vec3) -> bool:
        return all(self.minimum[i] <= point[i] <= self.maximum[i] for i in range(3))

    def center(self) -> Vec3:
        return tuple((self.minimum[i] + self.maximum[i]) * 0.5 for i in range(3))

    def extent(self) -> Vec3:
        return tuple(self.maximum[i] - self.minimum[i] for i in range(3))

    def surface_area(self) -> float:
        x, y, z = self.extent()
        return 2.0 * (x * y + y * z + z * x)

    def transformed(self, matrix) -> "AABB":
        mn, mx = self.minimum, self.maximum
        corners = [
            (x, y, z)
            for x in (mn[0], mx[0])
            for y in (mn[1], mx[1])
            for z in (mn[2], mx[2])
        ]
        return AABB.from_points([transform_point(matrix, p) for p in corners])

    def ray_interval(self, origin: Vec3, direction: Vec3, t_min: float = 0.0, t_max: float = float("inf")):
        lo, hi = t_min, t_max
        for axis in range(3):
            o, d = origin[axis], direction[axis]
            if abs(d) <= EPS:
                if o < self.minimum[axis] or o > self.maximum[axis]:
                    return None
                continue
            inv = 1.0 / d
            a = (self.minimum[axis] - o) * inv
            b = (self.maximum[axis] - o) * inv
            if a > b:
                a, b = b, a
            lo = max(lo, a)
            hi = min(hi, b)
            if hi < lo:
                return None
        return lo, hi

    def inside_frustum(self, planes: Sequence[tuple[Vec3, float]]) -> bool:
        """Conservative AABB/frustum test; planes use dot(n,p)+d >= 0 as inside."""
        for n, d in planes:
            positive = tuple(self.maximum[i] if n[i] >= 0 else self.minimum[i] for i in range(3))
            if dot(n, positive) + d < 0:
                return False
        return True


@dataclass
class BVHNode:
    bounds: AABB
    item_ids: tuple[str, ...] = ()
    left: "BVHNode | None" = None
    right: "BVHNode | None" = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None


class BVH:
    def __init__(self, entries: Iterable[tuple[str, AABB]], leaf_size: int = 4):
        entries = list(entries)
        if not entries:
            raise ValueError("BVH entries required")
        if leaf_size < 1:
            raise ValueError("leaf_size must be positive")
        self._bounds_by_id = {key: box for key, box in entries}
        if len(self._bounds_by_id) != len(entries):
            raise ValueError("BVH item IDs must be unique")
        self.leaf_size = leaf_size
        self.root = self._build(entries)

    @staticmethod
    def _union(entries) -> AABB:
        box = entries[0][1]
        for _, other in entries[1:]:
            box = box.union(other)
        return box

    def _build(self, entries) -> BVHNode:
        bounds = self._union(entries)
        if len(entries) <= self.leaf_size:
            return BVHNode(bounds, tuple(sorted(key for key, _ in entries)))
        ext = bounds.extent()
        axis = max(range(3), key=lambda i: ext[i])
        entries.sort(key=lambda kv: (kv[1].center()[axis], kv[0]))
        mid = len(entries) // 2
        left = self._build(entries[:mid])
        right = self._build(entries[mid:])
        return BVHNode(bounds, (), left, right)

    def query_aabb(self, query: AABB) -> tuple[str, ...]:
        out: list[str] = []

        def visit(node: BVHNode):
            if not node.bounds.intersects(query):
                return
            if node.is_leaf:
                for item_id in node.item_ids:
                    if self._bounds_by_id[item_id].intersects(query):
                        out.append(item_id)
            else:
                visit(node.left)  # type: ignore[arg-type]
                visit(node.right)  # type: ignore[arg-type]

        visit(self.root)
        return tuple(sorted(out))

    def query_ray(self, origin: Vec3, direction: Vec3, t_max: float = float("inf")) -> tuple[tuple[str, float], ...]:
        hits: list[tuple[str, float]] = []

        def visit(node: BVHNode):
            interval = node.bounds.ray_interval(origin, direction, 0.0, t_max)
            if interval is None:
                return
            if node.is_leaf:
                for item_id in node.item_ids:
                    hit = self._bounds_by_id[item_id].ray_interval(origin, direction, 0.0, t_max)
                    if hit is not None:
                        hits.append((item_id, hit[0]))
            else:
                visit(node.left)  # type: ignore[arg-type]
                visit(node.right)  # type: ignore[arg-type]

        visit(self.root)
        return tuple(sorted(hits, key=lambda item: (item[1], item[0])))

    def query_frustum(self, planes: Sequence[tuple[Vec3, float]]) -> tuple[str, ...]:
        out: list[str] = []

        def visit(node: BVHNode):
            if not node.bounds.inside_frustum(planes):
                return
            if node.is_leaf:
                out.extend(i for i in node.item_ids if self._bounds_by_id[i].inside_frustum(planes))
            else:
                visit(node.left)  # type: ignore[arg-type]
                visit(node.right)  # type: ignore[arg-type]

        visit(self.root)
        return tuple(sorted(out))

    def support_aware_query(self, query: AABB, support_predicate: Callable[[str], bool]) -> tuple[str, ...]:
        return tuple(item_id for item_id in self.query_aabb(query) if support_predicate(item_id))


def sphere_query_box(center: Vec3, radius: float) -> AABB:
    if radius < 0:
        raise ValueError("radius must be nonnegative")
    r = (radius, radius, radius)
    return AABB(sub(center, r), add(center, r))


def grid_cell(point: Vec3, cell_size: float) -> tuple[int, int, int]:
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")
    return tuple(math.floor(v / cell_size) for v in point)


def cells_for_aabb(box: AABB, cell_size: float) -> tuple[tuple[int, int, int], ...]:
    c0 = grid_cell(box.minimum, cell_size)
    c1 = grid_cell(box.maximum, cell_size)
    return tuple(
        (i, j, k)
        for i in range(c0[0], c1[0] + 1)
        for j in range(c0[1], c1[1] + 1)
        for k in range(c0[2], c1[2] + 1)
    )


def interest_set(
    entries: Iterable[tuple[str, AABB, set[str]]],
    center: Vec3,
    radius: float,
    required_tags: set[str] | None = None,
) -> tuple[str, ...]:
    required_tags = required_tags or set()
    query = sphere_query_box(center, radius)
    out = []
    for item_id, box, tags in entries:
        if box.intersects(query) and required_tags.issubset(tags):
            out.append(item_id)
    return tuple(sorted(out))


@dataclass(frozen=True)
class CullResult:
    item_id: str
    visible: bool
    reason: str


def classify_culling(item_id: str, box: AABB, frustum_planes, support_ok: bool, compatibility_ok: bool) -> CullResult:
    if not box.inside_frustum(frustum_planes):
        return CullResult(item_id, False, "outside_frustum")
    if not support_ok:
        return CullResult(item_id, False, "outside_support")
    if not compatibility_ok:
        return CullResult(item_id, False, "incompatible")
    return CullResult(item_id, True, "visible")
