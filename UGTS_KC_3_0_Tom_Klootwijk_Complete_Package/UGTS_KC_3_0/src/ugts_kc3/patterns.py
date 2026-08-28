"""Parametric pattern and surface families used by UGTS-KC 2.0/3.0."""
from __future__ import annotations

from math import atan, atan2, cos, cosh, exp, floor, pi, sin, sinh, sqrt
from typing import Iterable, List, Sequence, Tuple

from .math3 import Vec2, Vec3, add, distance, lerp, scale


def _signed_power(x: float, p: float) -> float:
    if p <= 0.0:
        raise ValueError("power must be positive")
    if x == 0.0:
        return 0.0
    return (1.0 if x > 0.0 else -1.0) * abs(x) ** p


def superellipse(theta: float, a: float = 1.0, b: float = 1.0, n: float = 2.0) -> Vec2:
    if a <= 0.0 or b <= 0.0 or n <= 0.0:
        raise ValueError("a, b and n must be positive")
    c, s = cos(theta), sin(theta)
    p = 2.0 / n
    return (a * _signed_power(c, p), b * _signed_power(s, p))


def superformula(theta: float, m: float = 6.0, a: float = 1.0, b: float = 1.0,
                 n1: float = 1.0, n2: float = 1.0, n3: float = 1.0) -> Vec2:
    if a == 0.0 or b == 0.0 or n1 == 0.0:
        raise ValueError("a, b and n1 must be nonzero")
    t1 = abs(cos(m * theta / 4.0) / a) ** n2
    t2 = abs(sin(m * theta / 4.0) / b) ** n3
    r = (t1 + t2) ** (-1.0 / n1) if t1 + t2 > 0.0 else 0.0
    return (r * cos(theta), r * sin(theta))


def lissajous(t: float, ax: float = 1.0, ay: float = 1.0,
              wx: float = 3.0, wy: float = 2.0, delta: float = pi / 2.0) -> Vec2:
    return (ax * sin(wx * t + delta), ay * sin(wy * t))


def hypotrochoid(t: float, R: float, r: float, d: float) -> Vec2:
    if R <= 0.0 or r <= 0.0 or r >= R:
        raise ValueError("require R>r>0")
    q = (R - r) / r
    return ((R - r) * cos(t) + d * cos(q * t), (R - r) * sin(t) - d * sin(q * t))


def epitrochoid(t: float, R: float, r: float, d: float) -> Vec2:
    if R <= 0.0 or r <= 0.0:
        raise ValueError("R and r must be positive")
    q = (R + r) / r
    return ((R + r) * cos(t) - d * cos(q * t), (R + r) * sin(t) - d * sin(q * t))


def cycloid(t: float, r: float = 1.0) -> Vec2:
    if r <= 0.0:
        raise ValueError("r must be positive")
    return (r * (t - sin(t)), r * (1.0 - cos(t)))


def involute(t: float, r: float = 1.0) -> Vec2:
    if r <= 0.0:
        raise ValueError("r must be positive")
    return (r * (cos(t) + t * sin(t)), r * (sin(t) - t * cos(t)))


def archimedean_spiral(theta: float, a: float = 0.0, b: float = 1.0) -> Vec2:
    radius = a + b * theta
    return (radius * cos(theta), radius * sin(theta))


def logarithmic_spiral(theta: float, a: float = 1.0, b: float = 0.2) -> Vec2:
    if a <= 0.0:
        raise ValueError("a must be positive")
    radius = a * exp(b * theta)
    return (radius * cos(theta), radius * sin(theta))


def fermat_spiral(theta: float, a: float = 1.0, branch: int = 1) -> Vec2:
    if theta < 0.0 or a < 0.0 or branch not in (-1, 1):
        raise ValueError("theta>=0, a>=0 and branch in {-1,1} required")
    radius = branch * a * sqrt(theta)
    return (radius * cos(theta), radius * sin(theta))


def clothoid(s: float, a: float = 1.0, steps: int = 256) -> Vec2:
    """Evaluate an Euler spiral by trapezoidal quadrature.

    Heading is theta(u)=u^2/(2*a^2), so curvature is u/a^2.
    Negative s is handled by integrating over the signed interval.
    """
    if a <= 0.0 or steps < 2:
        raise ValueError("a>0 and steps>=2 required")
    if s == 0.0:
        return (0.0, 0.0)
    n = max(2, int(steps * max(1.0, abs(s))))
    h = s / n
    x = y = 0.0
    prev_c = cos(0.0)
    prev_s = sin(0.0)
    for i in range(1, n + 1):
        u = i * h
        theta = (u * u) / (2.0 * a * a)
        c, sn = cos(theta), sin(theta)
        x += 0.5 * h * (prev_c + c)
        y += 0.5 * h * (prev_s + sn)
        prev_c, prev_s = c, sn
    return (x, y)


def quadratic_bezier(p0: Sequence[float], p1: Sequence[float], p2: Sequence[float], t: float) -> Tuple[float, ...]:
    if not 0.0 <= t <= 1.0 or not (len(p0) == len(p1) == len(p2)):
        raise ValueError("control point dimensions must match and t in [0,1]")
    u = 1.0 - t
    return tuple(u * u * p0[i] + 2.0 * u * t * p1[i] + t * t * p2[i] for i in range(len(p0)))


def cubic_bezier(p0: Sequence[float], p1: Sequence[float], p2: Sequence[float], p3: Sequence[float], t: float) -> Tuple[float, ...]:
    if not 0.0 <= t <= 1.0 or not (len(p0) == len(p1) == len(p2) == len(p3)):
        raise ValueError("control point dimensions must match and t in [0,1]")
    u = 1.0 - t
    return tuple(
        u**3 * p0[i] + 3.0 * u * u * t * p1[i] + 3.0 * u * t * t * p2[i] + t**3 * p3[i]
        for i in range(len(p0))
    )


def catmull_rom(p0: Sequence[float], p1: Sequence[float], p2: Sequence[float], p3: Sequence[float], t: float, tension: float = 0.0) -> Tuple[float, ...]:
    if not 0.0 <= t <= 1.0 or not (len(p0) == len(p1) == len(p2) == len(p3)):
        raise ValueError("control point dimensions must match and t in [0,1]")
    if not 0.0 <= tension <= 1.0:
        raise ValueError("tension must be in [0,1]")
    s = (1.0 - tension) * 0.5
    t2, t3 = t * t, t * t * t
    out = []
    for i in range(len(p0)):
        m1 = s * (p2[i] - p0[i])
        m2 = s * (p3[i] - p1[i])
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        out.append(h00 * p1[i] + h10 * m1 + h01 * p2[i] + h11 * m2)
    return tuple(out)


def uniform_cubic_bspline(p0: Sequence[float], p1: Sequence[float], p2: Sequence[float], p3: Sequence[float], t: float) -> Tuple[float, ...]:
    if not 0.0 <= t <= 1.0 or not (len(p0) == len(p1) == len(p2) == len(p3)):
        raise ValueError("control point dimensions must match and t in [0,1]")
    t2, t3 = t * t, t * t * t
    b0 = (1 - 3 * t + 3 * t2 - t3) / 6.0
    b1 = (4 - 6 * t2 + 3 * t3) / 6.0
    b2 = (1 + 3 * t + 3 * t2 - 3 * t3) / 6.0
    b3 = t3 / 6.0
    return tuple(b0 * p0[i] + b1 * p1[i] + b2 * p2[i] + b3 * p3[i] for i in range(len(p0)))


def _basis(i: int, degree: int, u: float, knots: Sequence[float]) -> float:
    if degree == 0:
        # Include the right endpoint in the final span.
        if knots[i] <= u < knots[i + 1] or (u == knots[-1] and knots[i + 1] == knots[-1] and knots[i] < knots[i + 1]):
            return 1.0
        return 0.0
    left_denom = knots[i + degree] - knots[i]
    right_denom = knots[i + degree + 1] - knots[i + 1]
    left = 0.0 if left_denom == 0.0 else (u - knots[i]) / left_denom * _basis(i, degree - 1, u, knots)
    right = 0.0 if right_denom == 0.0 else (knots[i + degree + 1] - u) / right_denom * _basis(i + 1, degree - 1, u, knots)
    return left + right


def nurbs_curve(control_points: Sequence[Sequence[float]], weights: Sequence[float], knots: Sequence[float], degree: int, u: float) -> Tuple[float, ...]:
    n = len(control_points)
    if n == 0 or len(weights) != n or degree < 1:
        raise ValueError("nonempty control points, matching weights and degree>=1 required")
    if any(w <= 0.0 for w in weights):
        raise ValueError("weights must be positive")
    if len(knots) != n + degree + 1 or any(knots[i] > knots[i + 1] for i in range(len(knots) - 1)):
        raise ValueError("invalid knot vector")
    dim = len(control_points[0])
    if any(len(p) != dim for p in control_points):
        raise ValueError("control point dimension mismatch")
    lo, hi = knots[degree], knots[-degree - 1]
    if not lo <= u <= hi:
        raise ValueError("u outside active knot domain")
    coeff = [_basis(i, degree, u, knots) * weights[i] for i in range(n)]
    denom = sum(coeff)
    if denom == 0.0:
        raise ValueError("zero rational denominator")
    return tuple(sum(coeff[i] * control_points[i][d] for i in range(n)) / denom for d in range(dim))


def reuleaux_triangle_point(t: float, width: float = 1.0) -> Vec2:
    if width <= 0.0:
        raise ValueError("width must be positive")
    t = t % 1.0
    h = width / sqrt(3.0)
    A = (0.0, h)
    B = (-width / 2.0, -h / 2.0)
    C = (width / 2.0, -h / 2.0)
    seg = min(2, int(floor(3.0 * t)))
    local = 3.0 * t - seg
    if seg == 0:
        center, a0, a1 = A, -5.0 * pi / 6.0, -pi / 6.0
    elif seg == 1:
        center, a0, a1 = B, 0.0, pi / 3.0
    else:
        center, a0, a1 = C, 2.0 * pi / 3.0, pi
    ang = (1.0 - local) * a0 + local * a1
    return (center[0] + width * cos(ang), center[1] + width * sin(ang))


def rose(theta: float, a: float = 1.0, k: float = 4.0, phase: float = 0.0) -> Vec2:
    r = a * cos(k * theta + phase)
    return (r * cos(theta), r * sin(theta))


def viviani(t: float, radius: float = 1.0) -> Vec3:
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    # Sphere x^2+y^2+z^2=R^2 and cylinder (x-R/2)^2+y^2=(R/2)^2.
    return (radius * (1.0 + cos(t)) / 2.0, radius * sin(t) / 2.0, radius * sin(t / 2.0))


def loxodrome(longitude: float, bearing_parameter: float = 0.25, radius: float = 1.0) -> Vec3:
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    lat = 2.0 * atan(exp(bearing_parameter * longitude)) - pi / 2.0
    cl = cos(lat)
    return (radius * cl * cos(longitude), radius * cl * sin(longitude), radius * sin(lat))


def helicoid(u: float, v: float, pitch: float = 1.0) -> Vec3:
    return (u * cos(v), u * sin(v), pitch * v)


def catenoid(u: float, v: float, scale_parameter: float = 1.0) -> Vec3:
    if scale_parameter <= 0.0:
        raise ValueError("scale_parameter must be positive")
    r = scale_parameter * cosh(v / scale_parameter)
    return (r * cos(u), r * sin(u), v)


def sample_curve(func, start: float, end: float, count: int) -> List[Tuple[float, ...]]:
    if count < 2:
        raise ValueError("count must be at least 2")
    return [tuple(func(start + (end - start) * i / (count - 1))) for i in range(count)]
