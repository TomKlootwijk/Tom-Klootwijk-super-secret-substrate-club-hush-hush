"""Small dependency-free vector, matrix and quaternion helpers for UGTS-KC 3.0.

The routines are intentionally explicit and bounded.  They are reference-oracle
implementations, not replacements for optimized numerical libraries.
"""
from __future__ import annotations

from math import acos, cos, isfinite, sin, sqrt
from typing import Iterable, List, Sequence, Tuple

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]  # w, x, y, z
Mat3 = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]
Mat4 = Tuple[
    Tuple[float, float, float, float],
    Tuple[float, float, float, float],
    Tuple[float, float, float, float],
    Tuple[float, float, float, float],
]


def clamp(x: float, lo: float, hi: float) -> float:
    if lo > hi:
        raise ValueError("lo must not exceed hi")
    return lo if x < lo else hi if x > hi else x


def add(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    if len(a) != len(b):
        raise ValueError("dimension mismatch")
    return tuple(float(x + y) for x, y in zip(a, b))


def sub(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    if len(a) != len(b):
        raise ValueError("dimension mismatch")
    return tuple(float(x - y) for x, y in zip(a, b))


def scale(a: Sequence[float], s: float) -> Tuple[float, ...]:
    return tuple(float(s * x) for x in a)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dimension mismatch")
    return float(sum(x * y for x, y in zip(a, b)))


def cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    if len(a) != 3 or len(b) != 3:
        raise ValueError("cross product requires 3D vectors")
    return (
        float(a[1] * b[2] - a[2] * b[1]),
        float(a[2] * b[0] - a[0] * b[2]),
        float(a[0] * b[1] - a[1] * b[0]),
    )


def norm_sq(a: Sequence[float]) -> float:
    return dot(a, a)


def norm(a: Sequence[float]) -> float:
    return sqrt(norm_sq(a))


def normalize(a: Sequence[float], eps: float = 1e-15) -> Tuple[float, ...]:
    n = norm(a)
    if n <= eps:
        raise ValueError("cannot normalize a near-zero vector")
    return scale(a, 1.0 / n)


def distance(a: Sequence[float], b: Sequence[float]) -> float:
    return norm(sub(a, b))


def lerp(a: Sequence[float], b: Sequence[float], t: float) -> Tuple[float, ...]:
    if len(a) != len(b):
        raise ValueError("dimension mismatch")
    return tuple(float((1.0 - t) * x + t * y) for x, y in zip(a, b))


def almost_equal(a: float, b: float, abs_tol: float = 1e-12, rel_tol: float = 1e-12) -> bool:
    if not (isfinite(a) and isfinite(b)):
        return a == b
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def mat3_identity() -> Mat3:
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def mat3_add(a: Mat3, b: Mat3) -> Mat3:
    return tuple(tuple(a[i][j] + b[i][j] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def mat3_scale(a: Mat3, s: float) -> Mat3:
    return tuple(tuple(s * a[i][j] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def mat3_mul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )  # type: ignore[return-value]


def mat3_vec(a: Mat3, v: Sequence[float]) -> Vec3:
    if len(v) != 3:
        raise ValueError("mat3_vec requires a 3-vector")
    return tuple(sum(a[i][j] * v[j] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def mat3_transpose(a: Mat3) -> Mat3:
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def skew(v: Sequence[float]) -> Mat3:
    if len(v) != 3:
        raise ValueError("skew requires a 3-vector")
    x, y, z = v
    return ((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0))


def rodrigues(axis_angle: Sequence[float]) -> Mat3:
    if len(axis_angle) != 3:
        raise ValueError("axis-angle must be 3D")
    theta = norm(axis_angle)
    if theta < 1e-12:
        # I + K + 1/2 K^2 is adequate for the reference small-angle branch.
        k = skew(axis_angle)
        return mat3_add(mat3_add(mat3_identity(), k), mat3_scale(mat3_mul(k, k), 0.5))
    axis = scale(axis_angle, 1.0 / theta)
    k = skew(axis)
    kk = mat3_mul(k, k)
    return mat3_add(mat3_add(mat3_identity(), mat3_scale(k, sin(theta))), mat3_scale(kk, 1.0 - cos(theta)))


def mat4_from_rt(r: Mat3, t: Sequence[float]) -> Mat4:
    if len(t) != 3:
        raise ValueError("translation must be 3D")
    return (
        (r[0][0], r[0][1], r[0][2], float(t[0])),
        (r[1][0], r[1][1], r[1][2], float(t[1])),
        (r[2][0], r[2][1], r[2][2], float(t[2])),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat4_apply(m: Mat4, p: Sequence[float]) -> Vec3:
    if len(p) != 3:
        raise ValueError("point must be 3D")
    return (
        m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3],
        m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3],
        m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3],
    )


def quat_identity() -> Quat:
    return (1.0, 0.0, 0.0, 0.0)


def quat_dot(a: Quat, b: Quat) -> float:
    return dot(a, b)


def quat_norm(q: Quat) -> float:
    return norm(q)


def quat_normalize(q: Quat, eps: float = 1e-15) -> Quat:
    n = quat_norm(q)
    if n <= eps:
        raise ValueError("cannot normalize zero quaternion")
    return tuple(x / n for x in q)  # type: ignore[return-value]


def quat_conjugate(q: Quat) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def quat_multiply(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def quat_from_axis_angle(axis: Sequence[float], angle: float) -> Quat:
    axis_n = normalize(axis)
    h = 0.5 * angle
    s = sin(h)
    return quat_normalize((cos(h), axis_n[0] * s, axis_n[1] * s, axis_n[2] * s))


def quat_to_axis_angle(q: Quat) -> Tuple[Vec3, float]:
    qn = quat_normalize(q)
    if qn[0] < 0.0:
        qn = tuple(-x for x in qn)  # type: ignore[assignment]
    w = clamp(qn[0], -1.0, 1.0)
    angle = 2.0 * acos(w)
    s = sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-12:
        return (1.0, 0.0, 0.0), 0.0
    return (qn[1] / s, qn[2] / s, qn[3] / s), angle


def quat_rotate(q: Quat, v: Sequence[float]) -> Vec3:
    if len(v) != 3:
        raise ValueError("quat_rotate requires 3D vector")
    qn = quat_normalize(q)
    p: Quat = (0.0, float(v[0]), float(v[1]), float(v[2]))
    r = quat_multiply(quat_multiply(qn, p), quat_conjugate(qn))
    return (r[1], r[2], r[3])


def quat_to_mat3(q: Quat) -> Mat3:
    w, x, y, z = quat_normalize(q)
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def mat3_to_quat(m: Mat3) -> Quat:
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0.0:
        s = sqrt(trace + 1.0) * 2.0
        q = (0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        q = ((m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    elif m[1][1] > m[2][2]:
        s = sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        q = ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s)
    else:
        s = sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        q = ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s)
    return quat_normalize(q)


def quat_slerp(a: Quat, b: Quat, t: float) -> Quat:
    if not 0.0 <= t <= 1.0:
        raise ValueError("t must be in [0,1]")
    qa = quat_normalize(a)
    qb = quat_normalize(b)
    d = quat_dot(qa, qb)
    if d < 0.0:
        qb = tuple(-x for x in qb)  # type: ignore[assignment]
        d = -d
    d = clamp(d, -1.0, 1.0)
    if d > 0.9995:
        return quat_normalize(tuple((1 - t) * x + t * y for x, y in zip(qa, qb)))  # type: ignore[arg-type]
    theta = acos(d)
    s = sin(theta)
    w0 = sin((1.0 - t) * theta) / s
    w1 = sin(t * theta) / s
    return quat_normalize(tuple(w0 * x + w1 * y for x, y in zip(qa, qb)))  # type: ignore[arg-type]


def finite_vector(values: Iterable[float]) -> bool:
    return all(isfinite(float(v)) for v in values)


def matrix_vector_mul(a: Sequence[Sequence[float]], x: Sequence[float]) -> List[float]:
    if any(len(row) != len(x) for row in a):
        raise ValueError("matrix/vector dimension mismatch")
    return [sum(row[j] * x[j] for j in range(len(x))) for row in a]


def matrix_mul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> List[List[float]]:
    if not a or not b:
        return []
    n = len(a[0])
    if any(len(row) != n for row in a) or len(b) != n:
        raise ValueError("matrix dimension mismatch")
    m = len(b[0])
    if any(len(row) != m for row in b):
        raise ValueError("ragged matrix")
    return [[sum(a[i][k] * b[k][j] for k in range(n)) for j in range(m)] for i in range(len(a))]


def transpose(a: Sequence[Sequence[float]]) -> List[List[float]]:
    if not a:
        return []
    if any(len(row) != len(a[0]) for row in a):
        raise ValueError("ragged matrix")
    return [list(col) for col in zip(*a)]
