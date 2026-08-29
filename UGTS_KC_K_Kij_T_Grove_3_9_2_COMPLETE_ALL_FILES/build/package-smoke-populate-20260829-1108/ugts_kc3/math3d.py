"""Small dependency-free 3D math helpers used by the KC Two Hands 3.0 reference runtime.

Conventions
-----------
* Vectors are tuples of floats.
* Quaternions use ``(w, x, y, z)``.
* Matrices are row-major 4x4 tuples and multiply column vectors.
* World transforms are composed as ``parent @ local``.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

EPS = 1.0e-12


def vec3(v: Iterable[float]) -> tuple[float, float, float]:
    x, y, z = v
    return float(x), float(y), float(z)


def add(a: Sequence[float], b: Sequence[float]):
    return tuple(x + y for x, y in zip(a, b))


def sub(a: Sequence[float], b: Sequence[float]):
    return tuple(x - y for x, y in zip(a, b))


def scale(a: Sequence[float], s: float):
    return tuple(x * s for x in a)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(a: Sequence[float]) -> float:
    return math.sqrt(dot(a, a))


def normalize(a: Sequence[float], eps: float = EPS):
    n = norm(a)
    if n <= eps:
        raise ValueError("cannot normalize a near-zero vector")
    return scale(a, 1.0 / n)


def distance(a: Sequence[float], b: Sequence[float]) -> float:
    return norm(sub(a, b))


def lerp(a: Sequence[float], b: Sequence[float], t: float):
    return tuple((1.0 - t) * x + t * y for x, y in zip(a, b))


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def mat4_identity():
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat4_mul(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4))
        for i in range(4)
    )


def mat4_translation(t: Sequence[float]):
    x, y, z = t
    return (
        (1.0, 0.0, 0.0, x),
        (0.0, 1.0, 0.0, y),
        (0.0, 0.0, 1.0, z),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat4_scale(s: float | Sequence[float]):
    if isinstance(s, (int, float)):
        sx = sy = sz = float(s)
    else:
        sx, sy, sz = s
    return (
        (sx, 0.0, 0.0, 0.0),
        (0.0, sy, 0.0, 0.0),
        (0.0, 0.0, sz, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def transform_point(m, p: Sequence[float]):
    x, y, z = p
    w = m[3][0] * x + m[3][1] * y + m[3][2] * z + m[3][3]
    if abs(w) <= EPS:
        raise ValueError("projective point has zero homogeneous coordinate")
    return (
        (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3]) / w,
        (m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3]) / w,
        (m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]) / w,
    )


def transform_vector(m, v: Sequence[float]):
    x, y, z = v
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z,
        m[1][0] * x + m[1][1] * y + m[1][2] * z,
        m[2][0] * x + m[2][1] * y + m[2][2] * z,
    )


def quat_normalize(q):
    n = math.sqrt(sum(v * v for v in q))
    if n <= EPS:
        raise ValueError("zero quaternion")
    return tuple(v / n for v in q)


def quat_conjugate(q):
    w, x, y, z = q
    return w, -x, -y, -z


def quat_inverse(q):
    d = sum(v * v for v in q)
    if d <= EPS:
        raise ValueError("zero quaternion")
    return tuple(v / d for v in quat_conjugate(q))


def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def quat_from_axis_angle(axis: Sequence[float], angle: float):
    ax = normalize(axis)
    h = 0.5 * angle
    s = math.sin(h)
    return quat_normalize((math.cos(h), ax[0] * s, ax[1] * s, ax[2] * s))


def quat_from_two_vectors(a: Sequence[float], b: Sequence[float]):
    """Shortest rotation mapping vector *a* to vector *b*."""
    u = normalize(a)
    v = normalize(b)
    d = clamp(dot(u, v), -1.0, 1.0)
    if d > 1.0 - 1.0e-10:
        return (1.0, 0.0, 0.0, 0.0)
    if d < -1.0 + 1.0e-10:
        trial = (1.0, 0.0, 0.0) if abs(u[0]) < 0.8 else (0.0, 1.0, 0.0)
        axis = normalize(cross(u, trial))
        return quat_from_axis_angle(axis, math.pi)
    c = cross(u, v)
    return quat_normalize((1.0 + d, c[0], c[1], c[2]))


def quat_rotate(q, v: Sequence[float]):
    qn = quat_normalize(q)
    p = (0.0, v[0], v[1], v[2])
    r = quat_mul(quat_mul(qn, p), quat_conjugate(qn))
    return r[1], r[2], r[3]


def quat_nlerp(a, b, t: float):
    a = quat_normalize(a)
    b = quat_normalize(b)
    if dot(a, b) < 0.0:
        b = tuple(-v for v in b)
    return quat_normalize(tuple((1.0 - t) * x + t * y for x, y in zip(a, b)))


def quat_to_mat4(q):
    w, x, y, z = quat_normalize(q)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy), 0.0),
        (2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx), 0.0),
        (2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy), 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def compose_trs(translation=(0.0, 0.0, 0.0), rotation=(1.0, 0.0, 0.0, 0.0), scale_value=1.0):
    return mat4_mul(mat4_translation(translation), mat4_mul(quat_to_mat4(rotation), mat4_scale(scale_value)))


def matrix_translation(m):
    return m[0][3], m[1][3], m[2][3]


def rigid_inverse(m):
    """Inverse for a rigid transform (rotation + translation, no scale/shear)."""
    r = tuple(tuple(m[i][j] for j in range(3)) for i in range(3))
    rt = tuple(tuple(r[j][i] for j in range(3)) for i in range(3))
    p = matrix_translation(m)
    q = tuple(-dot(rt[i], p) for i in range(3))
    return (
        (rt[0][0], rt[0][1], rt[0][2], q[0]),
        (rt[1][0], rt[1][1], rt[1][2], q[1]),
        (rt[2][0], rt[2][1], rt[2][2], q[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def swing_twist(q, axis: Sequence[float]):
    """Decompose q into swing and twist around *axis*."""
    q = quat_normalize(q)
    a = normalize(axis)
    _, x, y, z = q
    projection = scale(a, dot((x, y, z), a))
    twist_raw = (q[0], projection[0], projection[1], projection[2])
    if sum(v * v for v in twist_raw) <= EPS:
        twist = (1.0, 0.0, 0.0, 0.0)
    else:
        twist = quat_normalize(twist_raw)
    swing = quat_mul(q, quat_inverse(twist))
    return quat_normalize(swing), twist


def signed_twist_angle(q, axis: Sequence[float]) -> float:
    _, twist = swing_twist(q, axis)
    w, x, y, z = twist
    v = (x, y, z)
    mag = norm(v)
    if mag <= EPS:
        return 0.0
    angle = 2.0 * math.atan2(mag, clamp(w, -1.0, 1.0))
    return math.copysign(angle, dot(v, normalize(axis)))


def matrix_almost_equal(a, b, tol: float = 1.0e-9) -> bool:
    return all(abs(a[i][j] - b[i][j]) <= tol for i in range(4) for j in range(4))


def finite_matrix(m) -> bool:
    return all(math.isfinite(v) for row in m for v in row)


def flatten_column_major(m) -> list[float]:
    """Convert row-major matrix to the column-major list expected by glTF."""
    return [m[row][col] for col in range(4) for row in range(4)]
