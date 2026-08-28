"""Implicit fields and signed-distance primitives for UGTS-KC 3.0."""
from __future__ import annotations

from math import cos, sin, sqrt
from typing import Callable, Iterable, Sequence, Tuple

from .math3 import Vec3, clamp, distance, dot, norm, scale, sub

ScalarField3 = Callable[[Sequence[float]], float]


def sphere_sdf(p: Sequence[float], center: Sequence[float] = (0.0, 0.0, 0.0), radius: float = 1.0) -> float:
    if len(p) != 3 or len(center) != 3 or radius < 0.0:
        raise ValueError("sphere_sdf requires 3D points and nonnegative radius")
    return distance(p, center) - radius


def box_sdf(p: Sequence[float], half_extents: Sequence[float], center: Sequence[float] = (0.0, 0.0, 0.0)) -> float:
    if len(p) != 3 or len(half_extents) != 3 or len(center) != 3 or any(h < 0.0 for h in half_extents):
        raise ValueError("invalid box parameters")
    q = [abs(p[i] - center[i]) - half_extents[i] for i in range(3)]
    outside = sqrt(sum(max(v, 0.0) ** 2 for v in q))
    inside = min(max(q), 0.0)
    return outside + inside


def capsule_sdf(p: Sequence[float], a: Sequence[float], b: Sequence[float], radius: float) -> float:
    if len(p) != 3 or len(a) != 3 or len(b) != 3 or radius < 0.0:
        raise ValueError("invalid capsule parameters")
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom <= 1e-30:
        return distance(p, a) - radius
    h = clamp(dot(sub(p, a), ab) / denom, 0.0, 1.0)
    closest = tuple(a[i] + h * ab[i] for i in range(3))
    return distance(p, closest) - radius


def torus_sdf(p: Sequence[float], major_radius: float, minor_radius: float, center: Sequence[float] = (0.0, 0.0, 0.0)) -> float:
    if len(p) != 3 or len(center) != 3 or major_radius < 0.0 or minor_radius < 0.0:
        raise ValueError("invalid torus parameters")
    x, y, z = (p[i] - center[i] for i in range(3))
    qx = sqrt(x * x + y * y) - major_radius
    return sqrt(qx * qx + z * z) - minor_radius


def superquadric_field(p: Sequence[float], axes: Sequence[float] = (1.0, 1.0, 1.0), e1: float = 1.0, e2: float = 1.0) -> float:
    """Signed implicit field for a superellipsoid.

    This sign field is not claimed to be an exact signed-distance function.
    """
    if len(p) != 3 or len(axes) != 3 or any(a <= 0.0 for a in axes) or e1 <= 0.0 or e2 <= 0.0:
        raise ValueError("axes and exponents must be positive")
    x, y, z = (abs(p[i] / axes[i]) for i in range(3))
    xy = (x ** (2.0 / e2) + y ** (2.0 / e2)) ** (e2 / e1)
    return (xy + z ** (2.0 / e1)) ** (e1 / 2.0) - 1.0


def gyroid_field(p: Sequence[float], scale_parameter: float = 1.0, level: float = 0.0) -> float:
    if len(p) != 3 or scale_parameter == 0.0:
        raise ValueError("invalid gyroid parameters")
    x, y, z = (v / scale_parameter for v in p)
    return sin(x) * cos(y) + sin(y) * cos(z) + sin(z) * cos(x) - level


def schwarz_p_field(p: Sequence[float], scale_parameter: float = 1.0, level: float = 0.0) -> float:
    if len(p) != 3 or scale_parameter == 0.0:
        raise ValueError("invalid Schwarz-P parameters")
    x, y, z = (v / scale_parameter for v in p)
    return cos(x) + cos(y) + cos(z) - level


def metaball_field(p: Sequence[float], centers: Sequence[Sequence[float]], weights: Sequence[float],
                   epsilon: float = 1e-6, isovalue: float = 1.0) -> float:
    if len(p) != 3 or len(centers) != len(weights) or epsilon <= 0.0:
        raise ValueError("invalid metaball parameters")
    value = 0.0
    for c, w in zip(centers, weights):
        if len(c) != 3 or w < 0.0:
            raise ValueError("centers must be 3D and weights nonnegative")
        r2 = sum((p[i] - c[i]) ** 2 for i in range(3))
        value += w / (r2 + epsilon)
    # Negative is inside, matching the package field sign convention.
    return isovalue - value


def offset_field(field: ScalarField3, offset: float) -> ScalarField3:
    return lambda p: float(field(p) - offset)


def union_field(a: ScalarField3, b: ScalarField3) -> ScalarField3:
    return lambda p: min(a(p), b(p))


def intersection_field(a: ScalarField3, b: ScalarField3) -> ScalarField3:
    return lambda p: max(a(p), b(p))


def subtraction_field(a: ScalarField3, b: ScalarField3) -> ScalarField3:
    return lambda p: max(a(p), -b(p))


def smooth_union_value(a: float, b: float, k: float) -> float:
    if k <= 0.0:
        return min(a, b)
    h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return (1.0 - h) * b + h * a - k * h * (1.0 - h)


def smooth_union(a: ScalarField3, b: ScalarField3, k: float) -> ScalarField3:
    return lambda p: smooth_union_value(a(p), b(p), k)


def gradient_central(field: ScalarField3, p: Sequence[float], h: float = 1e-5) -> Vec3:
    if len(p) != 3 or h <= 0.0:
        raise ValueError("gradient_central requires 3D point and h>0")
    out = []
    for i in range(3):
        pp = list(p); pm = list(p)
        pp[i] += h; pm[i] -= h
        out.append((field(pp) - field(pm)) / (2.0 * h))
    return tuple(out)  # type: ignore[return-value]


def point_segment_distance(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    if len(p) != len(a) or len(a) != len(b):
        raise ValueError("dimension mismatch")
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom <= 1e-30:
        return distance(p, a)
    t = clamp(dot(sub(p, a), ab) / denom, 0.0, 1.0)
    q = tuple(a[i] + t * ab[i] for i in range(len(a)))
    return distance(p, q)


def polyline_tube_sdf(p: Sequence[float], points: Sequence[Sequence[float]], radius: float) -> float:
    if len(points) < 2 or radius < 0.0:
        raise ValueError("polyline requires at least two points and nonnegative radius")
    dim = len(p)
    if dim not in (2, 3) or any(len(q) != dim for q in points):
        raise ValueError("point dimensions must be 2 or 3 and consistent")
    return min(point_segment_distance(p, points[i], points[i + 1]) for i in range(len(points) - 1)) - radius


def sample_field(field: ScalarField3, points: Iterable[Sequence[float]]) -> Tuple[float, ...]:
    return tuple(float(field(p)) for p in points)
