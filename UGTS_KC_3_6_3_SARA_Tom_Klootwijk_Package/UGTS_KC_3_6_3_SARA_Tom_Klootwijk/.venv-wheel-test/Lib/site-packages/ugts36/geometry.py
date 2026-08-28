"""Small dependency-free geometric calculus for UGTS-KC 3.6."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point2 = tuple[float, float]
Matrix3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


def digit_count(value: int, base: int = 10) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("value must be an integer")
    if value < 0:
        raise ValueError("value must be non-negative")
    if base < 2:
        raise ValueError("base must be at least 2")
    if value == 0:
        return 1
    count = 0
    n = value
    while n:
        n //= base
        count += 1
    return count


def radix_digits(value: int, base: int = 10) -> tuple[int, ...]:
    if value < 0:
        raise ValueError("value must be non-negative")
    if base < 2:
        raise ValueError("base must be at least 2")
    if value == 0:
        return (0,)
    digits: list[int] = []
    n = value
    while n:
        n, rem = divmod(n, base)
        digits.append(rem)
    return tuple(reversed(digits))


def radix_thresholds(base: int, levels: int) -> tuple[int, ...]:
    if base < 2 or levels < 0:
        raise ValueError("base >= 2 and levels >= 0 required")
    return tuple(base**k for k in range(levels + 1))


def active_bit_positions(value: int) -> tuple[int, ...]:
    if value < 0:
        raise ValueError("value must be non-negative")
    return tuple(i for i in range(value.bit_length()) if value & (1 << i))


def regular_polygon(count: int, radius: float = 1.0, phase: float = math.pi / 2.0) -> tuple[Point2, ...]:
    if count < 1:
        raise ValueError("count must be positive")
    if radius <= 0:
        raise ValueError("radius must be positive")
    if count == 1:
        return ((0.0, 0.0),)
    return tuple(
        (
            radius * math.cos(phase + 2.0 * math.pi * i / count),
            radius * math.sin(phase + 2.0 * math.pi * i / count),
        )
        for i in range(count)
    )


def polygon_area(points: Sequence[Point2]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def identity2() -> Matrix3:
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def rotation_about(angle: float, pivot: Point2 = (0.0, 0.0)) -> Matrix3:
    c, s = math.cos(angle), math.sin(angle)
    px, py = pivot
    return (
        (c, -s, px - c * px + s * py),
        (s, c, py - s * px - c * py),
        (0.0, 0.0, 1.0),
    )


def translation(dx: float, dy: float) -> Matrix3:
    return ((1.0, 0.0, dx), (0.0, 1.0, dy), (0.0, 0.0, 1.0))


def matmul3(a: Matrix3, b: Matrix3) -> Matrix3:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )  # type: ignore[return-value]


def apply_affine(matrix: Matrix3, point: Point2) -> Point2:
    x, y = point
    xp = matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]
    yp = matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]
    wp = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if abs(wp) < 1e-15:
        raise ZeroDivisionError("homogeneous point mapped to infinity")
    return (xp / wp, yp / wp)


def log_polar(point: Point2, r0: float = 1.0, epsilon: float = 1e-12) -> tuple[float, float, bool]:
    if r0 <= 0 or epsilon <= 0:
        raise ValueError("r0 and epsilon must be positive")
    x, y = point
    r = math.hypot(x, y)
    core = r < epsilon
    safe_r = max(r, epsilon)
    return (math.log(safe_r / r0), math.atan2(y, x), core)


def from_log_polar(rho: float, theta: float, r0: float = 1.0) -> Point2:
    if r0 <= 0:
        raise ValueError("r0 must be positive")
    r = r0 * math.exp(rho)
    return (r * math.cos(theta), r * math.sin(theta))


def sdf_circle(point: Point2, center: Point2 = (0.0, 0.0), radius: float = 1.0) -> float:
    if radius < 0:
        raise ValueError("radius must be non-negative")
    return math.hypot(point[0] - center[0], point[1] - center[1]) - radius


def implicit_union(a: float, b: float) -> float:
    return min(a, b)


def implicit_intersection(a: float, b: float) -> float:
    return max(a, b)


def implicit_subtraction(a: float, b: float) -> float:
    return max(a, -b)


def quadratic_position(p0: Point2, v0: Point2, acceleration: Point2, dt: float) -> Point2:
    return (
        p0[0] + v0[0] * dt + 0.5 * acceleration[0] * dt * dt,
        p0[1] + v0[1] * dt + 0.5 * acceleration[1] * dt * dt,
    )


def finite_difference(values: Iterable[float], dt: float) -> tuple[float, ...]:
    values = tuple(values)
    if dt <= 0:
        raise ValueError("dt must be positive")
    return tuple((b - a) / dt for a, b in zip(values, values[1:]))
