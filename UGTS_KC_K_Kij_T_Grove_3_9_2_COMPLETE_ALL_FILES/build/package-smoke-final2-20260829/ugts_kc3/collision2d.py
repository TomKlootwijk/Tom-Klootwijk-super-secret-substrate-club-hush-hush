"""Deterministic 2D collision primitives, broad phase and sweep queries."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Iterator, Sequence

Vec2 = tuple[float, float]
EPS = 1.0e-9


def v2(value: Sequence[float]) -> Vec2:
    if len(value) != 2:
        raise ValueError("expected a 2D vector")
    x, y = float(value[0]), float(value[1])
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("vector values must be finite")
    return x, y


def add2(a: Sequence[float], b: Sequence[float]) -> Vec2:
    return float(a[0]) + float(b[0]), float(a[1]) + float(b[1])


def sub2(a: Sequence[float], b: Sequence[float]) -> Vec2:
    return float(a[0]) - float(b[0]), float(a[1]) - float(b[1])


def scale2(a: Sequence[float], scalar: float) -> Vec2:
    return float(a[0]) * scalar, float(a[1]) * scalar


def dot2(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1])


def length2(a: Sequence[float]) -> float:
    return math.hypot(float(a[0]), float(a[1]))


def normalize2(a: Sequence[float], fallback: Vec2 = (1.0, 0.0)) -> Vec2:
    n = length2(a)
    if n <= EPS:
        return fallback
    return float(a[0]) / n, float(a[1]) / n


def perpendicular(a: Sequence[float]) -> Vec2:
    return -float(a[1]), float(a[0])


def clamp2(point: Sequence[float], minimum: Sequence[float], maximum: Sequence[float]) -> Vec2:
    return (
        max(float(minimum[0]), min(float(maximum[0]), float(point[0]))),
        max(float(minimum[1]), min(float(maximum[1]), float(point[1]))),
    )


@dataclass(frozen=True)
class AABB2:
    minimum: Vec2
    maximum: Vec2

    def __post_init__(self) -> None:
        minimum, maximum = v2(self.minimum), v2(self.maximum)
        if minimum[0] > maximum[0] or minimum[1] > maximum[1]:
            raise ValueError("AABB minimum must not exceed maximum")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    @classmethod
    def from_center(cls, center: Sequence[float], half_extents: Sequence[float]) -> "AABB2":
        c, h = v2(center), v2(half_extents)
        if h[0] < 0 or h[1] < 0:
            raise ValueError("half extents must be non-negative")
        return cls((c[0] - h[0], c[1] - h[1]), (c[0] + h[0], c[1] + h[1]))

    @property
    def center(self) -> Vec2:
        return ((self.minimum[0] + self.maximum[0]) * 0.5, (self.minimum[1] + self.maximum[1]) * 0.5)

    @property
    def half_extents(self) -> Vec2:
        return ((self.maximum[0] - self.minimum[0]) * 0.5, (self.maximum[1] - self.minimum[1]) * 0.5)

    @property
    def width(self) -> float:
        return self.maximum[0] - self.minimum[0]

    @property
    def height(self) -> float:
        return self.maximum[1] - self.minimum[1]

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, point: Sequence[float], inclusive: bool = True) -> bool:
        x, y = v2(point)
        if inclusive:
            return self.minimum[0] <= x <= self.maximum[0] and self.minimum[1] <= y <= self.maximum[1]
        return self.minimum[0] < x < self.maximum[0] and self.minimum[1] < y < self.maximum[1]

    def intersects(self, other: "AABB2", inclusive: bool = True) -> bool:
        if inclusive:
            return not (
                self.maximum[0] < other.minimum[0]
                or self.minimum[0] > other.maximum[0]
                or self.maximum[1] < other.minimum[1]
                or self.minimum[1] > other.maximum[1]
            )
        return not (
            self.maximum[0] <= other.minimum[0]
            or self.minimum[0] >= other.maximum[0]
            or self.maximum[1] <= other.minimum[1]
            or self.minimum[1] >= other.maximum[1]
        )

    def moved(self, offset: Sequence[float]) -> "AABB2":
        o = v2(offset)
        return AABB2(add2(self.minimum, o), add2(self.maximum, o))

    def expanded(self, amount: float | Sequence[float]) -> "AABB2":
        if isinstance(amount, (int, float)):
            ax = ay = float(amount)
        else:
            ax, ay = v2(amount)
        if self.width + 2 * ax < 0 or self.height + 2 * ay < 0:
            raise ValueError("expansion would invert AABB")
        return AABB2((self.minimum[0] - ax, self.minimum[1] - ay), (self.maximum[0] + ax, self.maximum[1] + ay))

    def union(self, other: "AABB2") -> "AABB2":
        return AABB2(
            (min(self.minimum[0], other.minimum[0]), min(self.minimum[1], other.minimum[1])),
            (max(self.maximum[0], other.maximum[0]), max(self.maximum[1], other.maximum[1])),
        )

    def to_dict(self) -> dict:
        return {"type": "aabb", "minimum": list(self.minimum), "maximum": list(self.maximum)}


@dataclass(frozen=True)
class Circle2:
    center: Vec2
    radius: float

    def __post_init__(self) -> None:
        center = v2(self.center)
        radius = float(self.radius)
        if not math.isfinite(radius) or radius < 0:
            raise ValueError("circle radius must be finite and non-negative")
        object.__setattr__(self, "center", center)
        object.__setattr__(self, "radius", radius)

    @property
    def bounds(self) -> AABB2:
        return AABB2.from_center(self.center, (self.radius, self.radius))

    def contains(self, point: Sequence[float]) -> bool:
        return length2(sub2(point, self.center)) <= self.radius + EPS

    def moved(self, offset: Sequence[float]) -> "Circle2":
        return Circle2(add2(self.center, offset), self.radius)

    def to_dict(self) -> dict:
        return {"type": "circle", "center": list(self.center), "radius": self.radius}


@dataclass(frozen=True)
class ConvexPolygon2:
    points: tuple[Vec2, ...]

    def __post_init__(self) -> None:
        points = tuple(v2(p) for p in self.points)
        if len(points) < 3:
            raise ValueError("polygon requires at least three points")
        area2 = sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points)))
        if abs(area2) <= EPS:
            raise ValueError("polygon area must be non-zero")
        signs: set[int] = set()
        for i in range(len(points)):
            a, b, c = points[i - 1], points[i], points[(i + 1) % len(points)]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cross) > EPS:
                signs.add(1 if cross > 0 else -1)
        if len(signs) > 1:
            raise ValueError("polygon must be convex")
        object.__setattr__(self, "points", points)

    @property
    def center(self) -> Vec2:
        return (sum(p[0] for p in self.points) / len(self.points), sum(p[1] for p in self.points) / len(self.points))

    @property
    def bounds(self) -> AABB2:
        return AABB2(
            (min(p[0] for p in self.points), min(p[1] for p in self.points)),
            (max(p[0] for p in self.points), max(p[1] for p in self.points)),
        )

    def axes(self) -> tuple[Vec2, ...]:
        axes: list[Vec2] = []
        for index, point in enumerate(self.points):
            edge = sub2(self.points[(index + 1) % len(self.points)], point)
            axis = normalize2(perpendicular(edge))
            if not any(abs(dot2(axis, existing)) > 1.0 - 1.0e-8 for existing in axes):
                axes.append(axis)
        return tuple(axes)

    def moved(self, offset: Sequence[float]) -> "ConvexPolygon2":
        o = v2(offset)
        return ConvexPolygon2(tuple(add2(p, o) for p in self.points))

    def to_dict(self) -> dict:
        return {"type": "polygon", "points": [list(p) for p in self.points]}


Shape2D = AABB2 | Circle2 | ConvexPolygon2


def shape_from_dict(data: dict) -> Shape2D:
    kind = data.get("type")
    if kind == "aabb":
        if "half_extents" in data:
            return AABB2.from_center(data.get("center", (0, 0)), data["half_extents"])
        return AABB2(v2(data["minimum"]), v2(data["maximum"]))
    if kind == "circle":
        return Circle2(v2(data.get("center", (0, 0))), float(data["radius"]))
    if kind == "polygon":
        return ConvexPolygon2(tuple(v2(p) for p in data["points"]))
    raise ValueError(f"unsupported shape type: {kind}")


def shape_bounds(shape: Shape2D) -> AABB2:
    return shape if isinstance(shape, AABB2) else shape.bounds


def translate_shape(shape: Shape2D, offset: Sequence[float]) -> Shape2D:
    return shape.moved(offset)


@dataclass(frozen=True)
class CollisionFilter:
    layer: int = 1
    mask: int = 0xFFFFFFFF
    sensor: bool = False

    def __post_init__(self) -> None:
        if self.layer <= 0 or self.layer > 0xFFFFFFFF:
            raise ValueError("layer must be a non-zero 32-bit bit mask")
        if self.mask < 0 or self.mask > 0xFFFFFFFF:
            raise ValueError("mask must be a 32-bit bit mask")

    def allows(self, other: "CollisionFilter") -> bool:
        return bool((self.mask & other.layer) and (other.mask & self.layer))


@dataclass(frozen=True)
class CollisionManifold:
    normal: Vec2
    penetration: float
    contacts: tuple[Vec2, ...] = ()

    def __post_init__(self) -> None:
        if self.penetration < -EPS or not math.isfinite(self.penetration):
            raise ValueError("penetration must be finite and non-negative")
        object.__setattr__(self, "normal", normalize2(self.normal))
        object.__setattr__(self, "penetration", max(0.0, float(self.penetration)))
        object.__setattr__(self, "contacts", tuple(v2(p) for p in self.contacts))


def _aabb_aabb(a: AABB2, b: AABB2) -> CollisionManifold | None:
    overlap_x = min(a.maximum[0], b.maximum[0]) - max(a.minimum[0], b.minimum[0])
    overlap_y = min(a.maximum[1], b.maximum[1]) - max(a.minimum[1], b.minimum[1])
    if overlap_x < -EPS or overlap_y < -EPS:
        return None
    delta = sub2(b.center, a.center)
    if overlap_x <= overlap_y:
        normal = (1.0 if delta[0] >= 0 else -1.0, 0.0)
        contact = ((a.maximum[0] if normal[0] > 0 else a.minimum[0]), max(a.minimum[1], min(b.center[1], a.maximum[1])))
        return CollisionManifold(normal, max(0.0, overlap_x), (contact,))
    normal = (0.0, 1.0 if delta[1] >= 0 else -1.0)
    contact = (max(a.minimum[0], min(b.center[0], a.maximum[0])), (a.maximum[1] if normal[1] > 0 else a.minimum[1]))
    return CollisionManifold(normal, max(0.0, overlap_y), (contact,))


def _circle_circle(a: Circle2, b: Circle2) -> CollisionManifold | None:
    delta = sub2(b.center, a.center)
    distance = length2(delta)
    radius_sum = a.radius + b.radius
    if distance > radius_sum + EPS:
        return None
    normal = normalize2(delta)
    contact = add2(a.center, scale2(normal, a.radius))
    return CollisionManifold(normal, max(0.0, radius_sum - distance), (contact,))


def _aabb_circle(box: AABB2, circle: Circle2) -> CollisionManifold | None:
    closest = clamp2(circle.center, box.minimum, box.maximum)
    delta = sub2(circle.center, closest)
    distance = length2(delta)
    if distance > circle.radius + EPS:
        return None
    if distance > EPS:
        normal = scale2(delta, 1.0 / distance)
        return CollisionManifold(normal, max(0.0, circle.radius - distance), (closest,))

    # Center is inside the box. Select the nearest face and push toward the circle.
    distances = [
        (circle.center[0] - box.minimum[0], (-1.0, 0.0), (box.minimum[0], circle.center[1])),
        (box.maximum[0] - circle.center[0], (1.0, 0.0), (box.maximum[0], circle.center[1])),
        (circle.center[1] - box.minimum[1], (0.0, -1.0), (circle.center[0], box.minimum[1])),
        (box.maximum[1] - circle.center[1], (0.0, 1.0), (circle.center[0], box.maximum[1])),
    ]
    face_distance, normal, contact = min(distances, key=lambda item: item[0])
    return CollisionManifold(normal, circle.radius + face_distance, (contact,))


def _project_polygon(poly: ConvexPolygon2, axis: Vec2) -> tuple[float, float]:
    values = [dot2(point, axis) for point in poly.points]
    return min(values), max(values)


def _interval_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return min(a[1], b[1]) - max(a[0], b[0])


def _polygon_polygon(a: ConvexPolygon2, b: ConvexPolygon2) -> CollisionManifold | None:
    min_overlap = math.inf
    best_axis: Vec2 = (1.0, 0.0)
    for axis in (*a.axes(), *b.axes()):
        overlap = _interval_overlap(_project_polygon(a, axis), _project_polygon(b, axis))
        if overlap < -EPS:
            return None
        if overlap < min_overlap:
            min_overlap = overlap
            best_axis = axis
    if dot2(sub2(b.center, a.center), best_axis) < 0:
        best_axis = scale2(best_axis, -1.0)
    contact = scale2(add2(a.center, b.center), 0.5)
    return CollisionManifold(best_axis, max(0.0, min_overlap), (contact,))


def _polygon_circle(poly: ConvexPolygon2, circle: Circle2) -> CollisionManifold | None:
    closest_vertex = min(poly.points, key=lambda p: length2(sub2(circle.center, p)))
    vertex_axis = normalize2(sub2(circle.center, closest_vertex), fallback=(1.0, 0.0))
    axes = (*poly.axes(), vertex_axis)
    min_overlap = math.inf
    best_axis: Vec2 = (1.0, 0.0)
    for axis in axes:
        poly_proj = _project_polygon(poly, axis)
        center_proj = dot2(circle.center, axis)
        circle_proj = (center_proj - circle.radius, center_proj + circle.radius)
        overlap = _interval_overlap(poly_proj, circle_proj)
        if overlap < -EPS:
            return None
        if overlap < min_overlap:
            min_overlap = overlap
            best_axis = axis
    if dot2(sub2(circle.center, poly.center), best_axis) < 0:
        best_axis = scale2(best_axis, -1.0)
    contact = sub2(circle.center, scale2(best_axis, circle.radius))
    return CollisionManifold(best_axis, max(0.0, min_overlap), (contact,))


def collide(a: Shape2D, b: Shape2D) -> CollisionManifold | None:
    """Return a manifold whose normal points from ``a`` toward ``b``."""
    if not shape_bounds(a).intersects(shape_bounds(b)):
        return None
    if isinstance(a, AABB2) and isinstance(b, AABB2):
        return _aabb_aabb(a, b)
    if isinstance(a, Circle2) and isinstance(b, Circle2):
        return _circle_circle(a, b)
    if isinstance(a, AABB2) and isinstance(b, Circle2):
        return _aabb_circle(a, b)
    if isinstance(a, Circle2) and isinstance(b, AABB2):
        manifold = _aabb_circle(b, a)
        return None if manifold is None else CollisionManifold(scale2(manifold.normal, -1.0), manifold.penetration, manifold.contacts)
    if isinstance(a, ConvexPolygon2) and isinstance(b, ConvexPolygon2):
        return _polygon_polygon(a, b)
    if isinstance(a, ConvexPolygon2) and isinstance(b, Circle2):
        return _polygon_circle(a, b)
    if isinstance(a, Circle2) and isinstance(b, ConvexPolygon2):
        manifold = _polygon_circle(b, a)
        return None if manifold is None else CollisionManifold(scale2(manifold.normal, -1.0), manifold.penetration, manifold.contacts)
    # Convert an AABB to a polygon for the remaining mixed case.
    if isinstance(a, AABB2):
        a = ConvexPolygon2((a.minimum, (a.maximum[0], a.minimum[1]), a.maximum, (a.minimum[0], a.maximum[1])))
    if isinstance(b, AABB2):
        b = ConvexPolygon2((b.minimum, (b.maximum[0], b.minimum[1]), b.maximum, (b.minimum[0], b.maximum[1])))
    return _polygon_polygon(a, b)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SweepHit:
    time: float
    normal: Vec2
    position: Vec2

    def __post_init__(self) -> None:
        if not 0.0 <= self.time <= 1.0:
            raise ValueError("sweep time must be in [0, 1]")
        object.__setattr__(self, "normal", normalize2(self.normal))
        object.__setattr__(self, "position", v2(self.position))


def sweep_aabb(moving: AABB2, delta: Sequence[float], target: AABB2) -> SweepHit | None:
    """Sweep an axis-aligned box against another box over normalized time [0, 1]."""
    d = v2(delta)
    if moving.intersects(target, inclusive=False):
        manifold = _aabb_aabb(moving, target)
        return SweepHit(0.0, manifold.normal if manifold else (1.0, 0.0), moving.center)

    expanded = AABB2(
        (target.minimum[0] - moving.half_extents[0], target.minimum[1] - moving.half_extents[1]),
        (target.maximum[0] + moving.half_extents[0], target.maximum[1] + moving.half_extents[1]),
    )
    origin = moving.center
    entry = [-math.inf, -math.inf]
    exit_ = [math.inf, math.inf]
    for axis in range(2):
        if abs(d[axis]) <= EPS:
            if origin[axis] < expanded.minimum[axis] or origin[axis] > expanded.maximum[axis]:
                return None
            continue
        t1 = (expanded.minimum[axis] - origin[axis]) / d[axis]
        t2 = (expanded.maximum[axis] - origin[axis]) / d[axis]
        entry[axis], exit_[axis] = min(t1, t2), max(t1, t2)
    entry_time = max(entry)
    exit_time = min(exit_)
    if entry_time > exit_time or exit_time < 0.0 or entry_time > 1.0:
        return None
    time = max(0.0, entry_time)
    if entry[0] > entry[1]:
        normal = (-1.0 if d[0] > 0 else 1.0, 0.0)
    else:
        normal = (0.0, -1.0 if d[1] > 0 else 1.0)
    position = add2(origin, scale2(d, time))
    return SweepHit(time, normal, position)


def resolve_velocity(velocity: Sequence[float], normal: Sequence[float], restitution: float = 0.0, friction: float = 0.0) -> Vec2:
    """Resolve velocity against a contact normal with simple restitution/friction."""
    v, n = v2(velocity), normalize2(normal)
    restitution = max(0.0, min(1.0, float(restitution)))
    friction = max(0.0, min(1.0, float(friction)))
    normal_speed = dot2(v, n)
    if normal_speed >= 0:
        return v
    normal_component = scale2(n, normal_speed)
    tangent_component = sub2(v, normal_component)
    bounced = scale2(normal_component, -restitution)
    tangent = scale2(tangent_component, 1.0 - friction)
    return add2(bounced, tangent)


class SpatialHash2D:
    """Small deterministic broad phase with stable pair ordering."""

    def __init__(self, cell_size: float = 64.0):
        cell_size = float(cell_size)
        if not math.isfinite(cell_size) or cell_size <= 0:
            raise ValueError("cell_size must be positive and finite")
        self.cell_size = cell_size
        self._items: dict[str, AABB2] = {}
        self._cells: dict[tuple[int, int], set[str]] = {}

    def _cell(self, point: Sequence[float]) -> tuple[int, int]:
        return math.floor(float(point[0]) / self.cell_size), math.floor(float(point[1]) / self.cell_size)

    def cells_for(self, box: AABB2) -> tuple[tuple[int, int], ...]:
        x0, y0 = self._cell(box.minimum)
        x1, y1 = self._cell(box.maximum)
        return tuple((x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))

    def insert(self, item_id: str, box: AABB2) -> None:
        if not item_id:
            raise ValueError("item id is required")
        if item_id in self._items:
            raise ValueError(f"item already inserted: {item_id}")
        self._items[item_id] = box
        for cell in self.cells_for(box):
            self._cells.setdefault(cell, set()).add(item_id)

    def update(self, item_id: str, box: AABB2) -> None:
        if item_id in self._items:
            self.remove(item_id)
        self.insert(item_id, box)

    def remove(self, item_id: str) -> None:
        box = self._items.pop(item_id)
        for cell in self.cells_for(box):
            members = self._cells.get(cell)
            if members is None:
                continue
            members.discard(item_id)
            if not members:
                del self._cells[cell]

    def clear(self) -> None:
        self._items.clear()
        self._cells.clear()

    def query(self, box: AABB2) -> tuple[str, ...]:
        candidates: set[str] = set()
        for cell in self.cells_for(box):
            candidates.update(self._cells.get(cell, ()))
        return tuple(sorted(item_id for item_id in candidates if self._items[item_id].intersects(box)))

    def potential_pairs(self) -> tuple[tuple[str, str], ...]:
        pairs: set[tuple[str, str]] = set()
        for members in self._cells.values():
            ordered = sorted(members)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1 :]:
                    pair = (a, b)
                    if self._items[a].intersects(self._items[b]):
                        pairs.add(pair)
        return tuple(sorted(pairs))

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[tuple[str, AABB2]]:
        for item_id in sorted(self._items):
            yield item_id, self._items[item_id]
