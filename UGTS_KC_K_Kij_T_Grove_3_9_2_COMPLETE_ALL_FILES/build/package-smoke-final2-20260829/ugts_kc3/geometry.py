"""Geometry compilation for the KC Two Hands 3.0 reference vertical slice.

The compiler keeps source patterns authoritative and emits derived render/collision meshes with
explicit approximation settings.  It deliberately favors clarity and deterministic behavior over
production-grade throughput.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Callable, Iterable, Sequence

from .math3d import (
    EPS,
    add,
    cross,
    distance,
    dot,
    lerp,
    norm,
    normalize,
    scale,
    sub,
    transform_point,
    transform_vector,
)

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Tri = tuple[int, int, int]


@dataclass(frozen=True)
class Mesh:
    vertices: tuple[Vec3, ...]
    triangles: tuple[Tri, ...]
    normals: tuple[Vec3, ...] = ()
    uvs: tuple[Vec2, ...] = ()
    metadata: dict = field(default_factory=dict, compare=False)

    def validate(self) -> None:
        if not self.vertices:
            raise ValueError("mesh requires vertices")
        if self.normals and len(self.normals) != len(self.vertices):
            raise ValueError("normal count must match vertex count")
        if self.uvs and len(self.uvs) != len(self.vertices):
            raise ValueError("UV count must match vertex count")
        n = len(self.vertices)
        for p in self.vertices:
            if len(p) != 3 or not all(math.isfinite(v) for v in p):
                raise ValueError("mesh contains invalid vertex")
        for tri in self.triangles:
            if len(tri) != 3 or len(set(tri)) < 3 or min(tri) < 0 or max(tri) >= n:
                raise ValueError(f"invalid triangle {tri}")

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    def bounds(self) -> tuple[Vec3, Vec3]:
        xs = [p[0] for p in self.vertices]
        ys = [p[1] for p in self.vertices]
        zs = [p[2] for p in self.vertices]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


@dataclass(frozen=True)
class GeometryErrorContract:
    world_error: float
    collision_error: float
    screen_space_error_pixels: float
    normal_error_degrees: float
    topology_preserved: bool | None = None

    def validate(self) -> None:
        if min(self.world_error, self.collision_error, self.screen_space_error_pixels, self.normal_error_degrees) < 0:
            raise ValueError("error budgets must be nonnegative")


def _point_line_distance(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom <= EPS:
        return distance(p, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / denom))
    return distance(p, add(a, scale(ab, t)))


def cubic_bezier_point(p0, p1, p2, p3, t: float) -> Vec3:
    u = 1.0 - t
    return tuple(
        u**3 * p0[i] + 3 * u * u * t * p1[i] + 3 * u * t * t * p2[i] + t**3 * p3[i]
        for i in range(3)
    )


def adaptive_cubic_bezier(
    p0: Vec3,
    p1: Vec3,
    p2: Vec3,
    p3: Vec3,
    tolerance: float = 1.0e-3,
    max_depth: int = 16,
) -> list[Vec3]:
    """Flatten a cubic Bezier with a control-polygon flatness bound."""
    if tolerance <= 0 or max_depth < 1:
        raise ValueError("positive tolerance and max_depth required")
    out: list[Vec3] = [tuple(map(float, p0))]

    def recur(a, b, c, d, depth):
        flat = max(_point_line_distance(b, a, d), _point_line_distance(c, a, d))
        if flat <= tolerance or depth >= max_depth:
            out.append(tuple(map(float, d)))
            return
        ab = lerp(a, b, 0.5)
        bc = lerp(b, c, 0.5)
        cd = lerp(c, d, 0.5)
        abc = lerp(ab, bc, 0.5)
        bcd = lerp(bc, cd, 0.5)
        mid = lerp(abc, bcd, 0.5)
        recur(a, ab, abc, mid, depth + 1)
        recur(mid, bcd, cd, d, depth + 1)

    recur(p0, p1, p2, p3, 0)
    return out


def polyline_length(points: Sequence[Vec3]) -> float:
    return sum(distance(a, b) for a, b in zip(points[:-1], points[1:]))


def resample_polyline(points: Sequence[Vec3], sample_count: int) -> list[Vec3]:
    if len(points) < 2 or sample_count < 2:
        raise ValueError("at least two points and two samples required")
    lengths = [0.0]
    for a, b in zip(points[:-1], points[1:]):
        lengths.append(lengths[-1] + distance(a, b))
    total = lengths[-1]
    if total <= EPS:
        return [points[0]] * sample_count
    out: list[Vec3] = []
    seg = 0
    for k in range(sample_count):
        target = total * k / (sample_count - 1)
        while seg + 1 < len(lengths) - 1 and lengths[seg + 1] < target:
            seg += 1
        span = lengths[seg + 1] - lengths[seg]
        t = 0.0 if span <= EPS else (target - lengths[seg]) / span
        out.append(lerp(points[seg], points[seg + 1], t))
    return out


def _tangents(points: Sequence[Vec3]) -> list[Vec3]:
    tangents: list[Vec3] = []
    for i in range(len(points)):
        if i == 0:
            d = sub(points[1], points[0])
        elif i == len(points) - 1:
            d = sub(points[-1], points[-2])
        else:
            d = sub(points[i + 1], points[i - 1])
        tangents.append(normalize(d))
    return tangents


def parallel_transport_frames(points: Sequence[Vec3], initial_normal: Vec3 = (0.0, 0.0, 1.0)):
    if len(points) < 2:
        raise ValueError("at least two points required")
    tangents = _tangents(points)
    n = sub(initial_normal, scale(tangents[0], dot(initial_normal, tangents[0])))
    if norm(n) <= 1.0e-8:
        trial = (1.0, 0.0, 0.0) if abs(tangents[0][0]) < 0.8 else (0.0, 1.0, 0.0)
        n = sub(trial, scale(tangents[0], dot(trial, tangents[0])))
    n = normalize(n)
    frames = []
    for t in tangents:
        projected = sub(n, scale(t, dot(n, t)))
        if norm(projected) <= 1.0e-8:
            trial = (1.0, 0.0, 0.0) if abs(t[0]) < 0.8 else (0.0, 1.0, 0.0)
            projected = sub(trial, scale(t, dot(trial, t)))
        n = normalize(projected)
        b = normalize(cross(t, n))
        n = normalize(cross(b, t))
        frames.append((t, n, b))
    return frames


def tube_mesh(points: Sequence[Vec3], radius: float = 0.1, sides: int = 12, cap: bool = True) -> Mesh:
    if len(points) < 2 or radius <= 0 or sides < 3:
        raise ValueError("tube needs >=2 points, positive radius and >=3 sides")
    frames = parallel_transport_frames(points)
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    uvs: list[Vec2] = []
    lengths = [0.0]
    for a, b in zip(points[:-1], points[1:]):
        lengths.append(lengths[-1] + distance(a, b))
    total = max(lengths[-1], EPS)
    for i, (p, (_, n, b)) in enumerate(zip(points, frames)):
        for j in range(sides):
            angle = 2.0 * math.pi * j / sides
            radial = add(scale(n, math.cos(angle)), scale(b, math.sin(angle)))
            vertices.append(add(p, scale(radial, radius)))
            normals.append(normalize(radial))
            uvs.append((j / sides, lengths[i] / total))
    triangles: list[Tri] = []
    for i in range(len(points) - 1):
        for j in range(sides):
            a = i * sides + j
            b0 = i * sides + (j + 1) % sides
            c = (i + 1) * sides + (j + 1) % sides
            d = (i + 1) * sides + j
            triangles.extend(((a, b0, c), (a, c, d)))
    if cap:
        start_center = len(vertices)
        vertices.append(points[0])
        normals.append(scale(frames[0][0], -1.0))
        uvs.append((0.5, 0.5))
        end_center = len(vertices)
        vertices.append(points[-1])
        normals.append(frames[-1][0])
        uvs.append((0.5, 0.5))
        for j in range(sides):
            j1 = (j + 1) % sides
            triangles.append((start_center, j1, j))
            a = (len(points) - 1) * sides + j
            b0 = (len(points) - 1) * sides + j1
            triangles.append((end_center, a, b0))
    mesh = Mesh(tuple(vertices), tuple(triangles), tuple(normals), tuple(uvs), {"compiler": "tube_mesh"})
    mesh.validate()
    return mesh


def stroke_polyline_2d(points: Sequence[Vec2], width: float = 0.05, z: float = 0.0) -> Mesh:
    """Compile an open 2D polyline to a simple ribbon mesh with bevel-style joins."""
    if len(points) < 2 or width <= 0:
        raise ValueError("stroke needs at least two points and positive width")
    half = width * 0.5
    verts: list[Vec3] = []
    for i, p in enumerate(points):
        if i == 0:
            d = sub(points[1], points[0])
        elif i == len(points) - 1:
            d = sub(points[-1], points[-2])
        else:
            d = sub(points[i + 1], points[i - 1])
        dn = normalize((d[0], d[1], 0.0))
        n = (-dn[1], dn[0], 0.0)
        verts.append((p[0] + n[0] * half, p[1] + n[1] * half, z))
        verts.append((p[0] - n[0] * half, p[1] - n[1] * half, z))
    tris: list[Tri] = []
    for i in range(len(points) - 1):
        a = 2 * i
        tris.extend(((a, a + 1, a + 3), (a, a + 3, a + 2)))
    normals = tuple((0.0, 0.0, 1.0) for _ in verts)
    mesh = Mesh(tuple(verts), tuple(tris), normals, metadata={"compiler": "stroke_polyline_2d"})
    mesh.validate()
    return mesh


def point_in_polygon(point: Vec2, polygon: Sequence[Vec2], rule: str = "even-odd") -> bool:
    if len(polygon) < 3:
        return False
    x, y = point
    pts = list(polygon)
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    if rule == "even-odd":
        inside = False
        for a, b in zip(pts[:-1], pts[1:]):
            if (a[1] > y) != (b[1] > y):
                x_hit = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if x_hit > x:
                    inside = not inside
        return inside
    if rule == "nonzero":
        winding = 0
        for a, b in zip(pts[:-1], pts[1:]):
            if a[1] <= y < b[1] and (b[0] - a[0]) * (y - a[1]) - (x - a[0]) * (b[1] - a[1]) > 0:
                winding += 1
            elif b[1] <= y < a[1] and (b[0] - a[0]) * (y - a[1]) - (x - a[0]) * (b[1] - a[1]) < 0:
                winding -= 1
        return winding != 0
    raise ValueError("rule must be 'even-odd' or 'nonzero'")


def _edge_intersection(pa: Vec3, pb: Vec3, va: float, vb: float, iso: float) -> Vec3:
    denom = vb - va
    t = 0.5 if abs(denom) <= EPS else (iso - va) / denom
    t = max(0.0, min(1.0, t))
    return lerp(pa, pb, t)


def finite_difference_normal(field_fn: Callable[[Vec3], float], p: Vec3, h: float = 1.0e-4) -> Vec3:
    if h <= 0:
        raise ValueError("h must be positive")
    x, y, z = p
    g = (
        field_fn((x + h, y, z)) - field_fn((x - h, y, z)),
        field_fn((x, y + h, z)) - field_fn((x, y - h, z)),
        field_fn((x, y, z + h)) - field_fn((x, y, z - h)),
    )
    if norm(g) <= EPS:
        return (0.0, 0.0, 1.0)
    return normalize(g)


def marching_tetrahedra(
    field_fn: Callable[[Vec3], float],
    bounds_min: Vec3 = (-1.0, -1.0, -1.0),
    bounds_max: Vec3 = (1.0, 1.0, 1.0),
    resolution: tuple[int, int, int] = (12, 12, 12),
    iso: float = 0.0,
) -> Mesh:
    """Deterministic, compact marching-tetrahedra reference implementation.

    Vertices are duplicated between tetrahedra.  This is intentional: it keeps the implementation
    small and makes the emitted mesh a correctness/reference artifact rather than a production
    topology optimizer.
    """
    nx, ny, nz = resolution
    if min(nx, ny, nz) < 2:
        raise ValueError("resolution dimensions must be >= 2")
    b0, b1 = bounds_min, bounds_max
    steps = tuple((b1[i] - b0[i]) / (resolution[i] - 1) for i in range(3))
    if min(steps) <= 0:
        raise ValueError("bounds must be increasing")

    def pos(i, j, k):
        return (b0[0] + i * steps[0], b0[1] + j * steps[1], b0[2] + k * steps[2])

    values = {}
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                p = pos(i, j, k)
                values[(i, j, k)] = float(field_fn(p))

    corner_offsets = (
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    )
    tets = ((0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6))
    tet_edges = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    triangles: list[Tri] = []

    for i in range(nx - 1):
        for j in range(ny - 1):
            for k in range(nz - 1):
                keys = [(i + di, j + dj, k + dk) for di, dj, dk in corner_offsets]
                ps = [pos(*key) for key in keys]
                vs = [values[key] for key in keys]
                for tet in tets:
                    tps = [ps[q] for q in tet]
                    tvs = [vs[q] for q in tet]
                    intersections: list[Vec3] = []
                    for ea, eb in tet_edges:
                        va, vb = tvs[ea], tvs[eb]
                        crosses = (va < iso and vb >= iso) or (vb < iso and va >= iso)
                        if crosses and abs(va - vb) > EPS:
                            p = _edge_intersection(tps[ea], tps[eb], va, vb, iso)
                            if not any(distance(p, q) <= 1.0e-10 for q in intersections):
                                intersections.append(p)
                    if len(intersections) < 3:
                        continue
                    local_indices = []
                    for p in intersections:
                        local_indices.append(len(vertices))
                        vertices.append(p)
                        normals.append(finite_difference_normal(field_fn, p, min(steps) * 0.15))
                    if len(local_indices) == 3:
                        triangles.append(tuple(local_indices))
                    elif len(local_indices) == 4:
                        triangles.append((local_indices[0], local_indices[1], local_indices[2]))
                        triangles.append((local_indices[0], local_indices[2], local_indices[3]))
                    else:
                        # Rare exact-isovalue degeneracy: fan triangulation with bounded output.
                        for q in range(1, len(local_indices) - 1):
                            triangles.append((local_indices[0], local_indices[q], local_indices[q + 1]))
    if not vertices or not triangles:
        raise ValueError("isosurface not found inside declared bounds")
    mesh = Mesh(
        tuple(vertices),
        tuple(triangles),
        tuple(normals),
        metadata={"compiler": "marching_tetrahedra", "resolution": list(resolution), "iso": iso},
    )
    mesh.validate()
    return mesh


def transform_mesh(mesh: Mesh, transform) -> Mesh:
    vertices = tuple(transform_point(transform, p) for p in mesh.vertices)
    normals = ()
    if mesh.normals:
        transformed = []
        for n in mesh.normals:
            q = transform_vector(transform, n)
            transformed.append((0.0, 0.0, 1.0) if norm(q) <= EPS else normalize(q))
        normals = tuple(transformed)
    out = Mesh(vertices, mesh.triangles, normals, mesh.uvs, dict(mesh.metadata))
    out.validate()
    return out


def merge_meshes(meshes: Iterable[Mesh]) -> Mesh:
    vertices: list[Vec3] = []
    triangles: list[Tri] = []
    normals: list[Vec3] = []
    uvs: list[Vec2] = []
    all_have_normals = True
    all_have_uvs = True
    for mesh in meshes:
        offset = len(vertices)
        vertices.extend(mesh.vertices)
        triangles.extend((a + offset, b + offset, c + offset) for a, b, c in mesh.triangles)
        if mesh.normals:
            normals.extend(mesh.normals)
        else:
            all_have_normals = False
        if mesh.uvs:
            uvs.extend(mesh.uvs)
        else:
            all_have_uvs = False
    out = Mesh(
        tuple(vertices),
        tuple(triangles),
        tuple(normals) if all_have_normals else (),
        tuple(uvs) if all_have_uvs else (),
        {"compiler": "merge_meshes"},
    )
    out.validate()
    return out


def mesh_lod(mesh: Mesh, ratio: float) -> Mesh:
    """Deterministic triangle subsampling reference LOD.

    This is not a topology-preserving simplifier.  The metadata states that limitation explicitly.
    """
    if not 0.0 < ratio <= 1.0:
        raise ValueError("ratio must be in (0, 1]")
    if ratio == 1.0:
        return mesh
    target = max(1, int(round(len(mesh.triangles) * ratio)))
    step = len(mesh.triangles) / target
    chosen = []
    used = set()
    for i in range(target):
        idx = min(len(mesh.triangles) - 1, int(i * step))
        if idx not in used:
            chosen.append(mesh.triangles[idx])
            used.add(idx)
    out = Mesh(mesh.vertices, tuple(chosen), mesh.normals, mesh.uvs, {**mesh.metadata, "lod_ratio": ratio, "topology_preserved": False})
    out.validate()
    return out


def aabb_proxy(mesh: Mesh) -> Mesh:
    mn, mx = mesh.bounds()
    x0, y0, z0 = mn
    x1, y1, z1 = mx
    v = (
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    )
    t = (
        (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
    )
    out = Mesh(v, t, metadata={"compiler": "aabb_proxy", "collision_proxy": True})
    out.validate()
    return out


def screen_space_error(world_error: float, distance_to_camera: float, focal_length_pixels: float) -> float:
    if world_error < 0 or distance_to_camera <= 0 or focal_length_pixels <= 0:
        raise ValueError("invalid screen-space error parameters")
    return world_error * focal_length_pixels / distance_to_camera
