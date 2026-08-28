"""Kinematic calculus, Lie-group helpers and trajectory contracts."""
from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, cos, pi, sin, sqrt
from typing import Callable, Iterable, List, Sequence, Tuple

from .math3 import (
    Mat3, Mat4, Quat, Vec2, Vec3, add, clamp, cross, dot, lerp, mat3_add,
    mat3_identity, mat3_mul, mat3_scale, mat3_to_quat, mat3_transpose,
    mat3_vec, mat4_from_rt, norm, normalize, quat_conjugate, quat_dot,
    quat_from_axis_angle, quat_multiply, quat_normalize, quat_rotate,
    quat_slerp, quat_to_axis_angle, quat_to_mat3, rodrigues, scale, skew, sub,
)


@dataclass(frozen=True)
class JetState:
    """Finite kinematic jet with explicit derivative levels.

    All vectors must have the same dimension.  Frame and unit metadata are kept
    as strings because the reference package does not impose a unit library.
    """

    position: Tuple[float, ...]
    velocity: Tuple[float, ...]
    acceleration: Tuple[float, ...]
    jerk: Tuple[float, ...]
    snap: Tuple[float, ...]
    time: float = 0.0
    frame: str = "world"
    length_unit: str = "unit"
    time_unit: str = "unit"

    def __post_init__(self) -> None:
        n = len(self.position)
        if n == 0 or any(len(v) != n for v in (self.velocity, self.acceleration, self.jerk, self.snap)):
            raise ValueError("jet vectors must be nonempty and have matching dimensions")

    def taylor(self, dt: float) -> "JetState":
        p = tuple(
            self.position[i]
            + self.velocity[i] * dt
            + 0.5 * self.acceleration[i] * dt**2
            + self.jerk[i] * dt**3 / 6.0
            + self.snap[i] * dt**4 / 24.0
            for i in range(len(self.position))
        )
        v = tuple(
            self.velocity[i]
            + self.acceleration[i] * dt
            + 0.5 * self.jerk[i] * dt**2
            + self.snap[i] * dt**3 / 6.0
            for i in range(len(self.position))
        )
        a = tuple(self.acceleration[i] + self.jerk[i] * dt + 0.5 * self.snap[i] * dt**2 for i in range(len(self.position)))
        j = tuple(self.jerk[i] + self.snap[i] * dt for i in range(len(self.position)))
        return JetState(p, v, a, j, self.snap, self.time + dt, self.frame, self.length_unit, self.time_unit)


def material_derivative(field: Callable[[Sequence[float], float], float], p: Sequence[float], t: float,
                        velocity: Sequence[float], h: float = 1e-6) -> float:
    if len(p) != len(velocity) or h <= 0.0:
        raise ValueError("dimension mismatch or invalid h")
    partial_t = (field(p, t + h) - field(p, t - h)) / (2.0 * h)
    grad = []
    for i in range(len(p)):
        pp = list(p); pm = list(p)
        pp[i] += h; pm[i] -= h
        grad.append((field(pp, t) - field(pm, t)) / (2.0 * h))
    return partial_t + dot(grad, velocity)


def _jacobian_2d(field: Callable[[Vec2], Vec2], p: Vec2, h: float) -> Tuple[Vec2, Vec2]:
    if h <= 0.0:
        raise ValueError("h must be positive")
    cols = []
    for i in range(2):
        pp = [p[0], p[1]]; pm = [p[0], p[1]]
        pp[i] += h; pm[i] -= h
        fp = field((pp[0], pp[1])); fm = field((pm[0], pm[1]))
        cols.append(((fp[0] - fm[0]) / (2 * h), (fp[1] - fm[1]) / (2 * h)))
    # Return rows.
    return ((cols[0][0], cols[1][0]), (cols[0][1], cols[1][1]))


def lie_bracket_2d(x_field: Callable[[Vec2], Vec2], y_field: Callable[[Vec2], Vec2], p: Vec2,
                   h: float = 1e-6) -> Vec2:
    x = x_field(p); y = y_field(p)
    jx = _jacobian_2d(x_field, p, h)
    jy = _jacobian_2d(y_field, p, h)
    dy_x = (jy[0][0] * x[0] + jy[0][1] * x[1], jy[1][0] * x[0] + jy[1][1] * x[1])
    dx_y = (jx[0][0] * y[0] + jx[0][1] * y[1], jx[1][0] * y[0] + jx[1][1] * y[1])
    return (dy_x[0] - dx_y[0], dy_x[1] - dx_y[1])


def se2_exp(twist: Sequence[float], dt: float = 1.0) -> Tuple[Tuple[float, float, float], ...]:
    if len(twist) != 3:
        raise ValueError("SE(2) twist is (vx,vy,omega)")
    vx, vy, omega = twist
    th = omega * dt
    if abs(th) < 1e-10:
        tx, ty = vx * dt, vy * dt
    else:
        a = sin(th) / omega
        b = (1.0 - cos(th)) / omega
        tx = a * vx - b * vy
        ty = b * vx + a * vy
    c, s = cos(th), sin(th)
    return ((c, -s, tx), (s, c, ty), (0.0, 0.0, 1.0))


def so3_left_jacobian(phi: Sequence[float]) -> Mat3:
    if len(phi) != 3:
        raise ValueError("phi must be 3D")
    theta = norm(phi)
    k = skew(phi)
    kk = mat3_mul(k, k)
    if theta < 1e-8:
        return mat3_add(mat3_add(mat3_identity(), mat3_scale(k, 0.5)), mat3_scale(kk, 1.0 / 6.0))
    a = (1.0 - cos(theta)) / (theta * theta)
    b = (theta - sin(theta)) / (theta**3)
    return mat3_add(mat3_add(mat3_identity(), mat3_scale(k, a)), mat3_scale(kk, b))


def _so3_left_jacobian_inverse(phi: Sequence[float]) -> Mat3:
    theta = norm(phi)
    k = skew(phi)
    kk = mat3_mul(k, k)
    if theta < 1e-8:
        return mat3_add(mat3_add(mat3_identity(), mat3_scale(k, -0.5)), mat3_scale(kk, 1.0 / 12.0))
    s = sin(theta)
    c = cos(theta)
    if abs(s) < 1e-12:
        # Near pi the principal branch is poorly conditioned.  The caller gets
        # a bounded reference approximation rather than an exact claim.
        a = 1.0 / (theta * theta)
    else:
        a = 1.0 / (theta * theta) - (1.0 + c) / (2.0 * theta * s)
    return mat3_add(mat3_add(mat3_identity(), mat3_scale(k, -0.5)), mat3_scale(kk, a))


def se3_exp(twist: Sequence[float], dt: float = 1.0) -> Mat4:
    if len(twist) != 6:
        raise ValueError("SE(3) twist is (wx,wy,wz,vx,vy,vz)")
    omega = twist[:3]
    v = twist[3:]
    phi = scale(omega, dt)
    rho = scale(v, dt)
    r = rodrigues(phi)
    j = so3_left_jacobian(phi)
    t = mat3_vec(j, rho)
    return mat4_from_rt(r, t)


def se3_log(transform: Mat4) -> Tuple[float, float, float, float, float, float]:
    r: Mat3 = (
        (transform[0][0], transform[0][1], transform[0][2]),
        (transform[1][0], transform[1][1], transform[1][2]),
        (transform[2][0], transform[2][1], transform[2][2]),
    )
    t = (transform[0][3], transform[1][3], transform[2][3])
    axis, angle = quat_to_axis_angle(mat3_to_quat(r))
    phi = scale(axis, angle)
    rho = mat3_vec(_so3_left_jacobian_inverse(phi), t)
    return (phi[0], phi[1], phi[2], rho[0], rho[1], rho[2])


def se3_adjoint(transform: Mat4) -> Tuple[Tuple[float, ...], ...]:
    r: Mat3 = (
        (transform[0][0], transform[0][1], transform[0][2]),
        (transform[1][0], transform[1][1], transform[1][2]),
        (transform[2][0], transform[2][1], transform[2][2]),
    )
    t = (transform[0][3], transform[1][3], transform[2][3])
    tr = mat3_mul(skew(t), r)
    z = ((0.0, 0.0, 0.0),) * 3
    rows = []
    for i in range(3):
        rows.append(tuple(r[i]) + tuple(z[i]))
    for i in range(3):
        rows.append(tuple(tr[i]) + tuple(r[i]))
    return tuple(rows)


def integrate_quaternion(q: Quat, angular_velocity: Sequence[float], dt: float) -> Quat:
    if len(angular_velocity) != 3:
        raise ValueError("angular velocity must be 3D")
    speed = norm(angular_velocity)
    if speed < 1e-15 or dt == 0.0:
        return quat_normalize(q)
    dq = quat_from_axis_angle(scale(angular_velocity, 1.0 / speed), speed * dt)
    return quat_normalize(quat_multiply(q, dq))


@dataclass(frozen=True)
class DualQuaternion:
    real: Quat
    dual: Quat

    def normalized(self) -> "DualQuaternion":
        nr = quat_normalize(self.real)
        scale_factor = 1.0 / sqrt(quat_dot(self.real, self.real))
        nd = tuple(x * scale_factor for x in self.dual)  # type: ignore[assignment]
        # Remove a component parallel to the real part to enforce qr dot qd = 0.
        parallel = quat_dot(nr, nd)
        nd = tuple(nd[i] - parallel * nr[i] for i in range(4))  # type: ignore[assignment]
        return DualQuaternion(nr, nd)  # type: ignore[arg-type]

    @staticmethod
    def from_rotation_translation(rotation: Quat, translation: Sequence[float]) -> "DualQuaternion":
        if len(translation) != 3:
            raise ValueError("translation must be 3D")
        qr = quat_normalize(rotation)
        tq: Quat = (0.0, float(translation[0]), float(translation[1]), float(translation[2]))
        qd = tuple(0.5 * x for x in quat_multiply(tq, qr))  # type: ignore[assignment]
        return DualQuaternion(qr, qd).normalized()  # type: ignore[arg-type]

    def translation(self) -> Vec3:
        n = self.normalized()
        t = quat_multiply(tuple(2.0 * x for x in n.dual), quat_conjugate(n.real))  # type: ignore[arg-type]
        return (t[1], t[2], t[3])

    def transform_point(self, p: Sequence[float]) -> Vec3:
        r = quat_rotate(self.normalized().real, p)
        t = self.translation()
        return (r[0] + t[0], r[1] + t[1], r[2] + t[2])


def blend_dual_quaternions(items: Sequence[DualQuaternion], weights: Sequence[float]) -> DualQuaternion:
    if not items or len(items) != len(weights) or sum(weights) == 0.0:
        raise ValueError("items and nonzero matching weights required")
    reference = items[0].normalized().real
    real = [0.0] * 4
    dual = [0.0] * 4
    for item, w in zip(items, weights):
        n = item.normalized()
        sign = -1.0 if quat_dot(reference, n.real) < 0.0 else 1.0
        for i in range(4):
            real[i] += w * sign * n.real[i]
            dual[i] += w * sign * n.dual[i]
    return DualQuaternion(tuple(real), tuple(dual)).normalized()  # type: ignore[arg-type]


def rigid_geodesic_interpolate(rotation_a: Quat, translation_a: Sequence[float], rotation_b: Quat,
                               translation_b: Sequence[float], t: float) -> DualQuaternion:
    if len(translation_a) != 3 or len(translation_b) != 3:
        raise ValueError("translations must be 3D")
    return DualQuaternion.from_rotation_translation(
        quat_slerp(rotation_a, rotation_b, t),
        lerp(translation_a, translation_b, t),
    )


def screw_interpolate(a: Mat4, b: Mat4, t: float) -> Mat4:
    if not 0.0 <= t <= 1.0:
        raise ValueError("t must be in [0,1]")
    # Bounded reference: relative transform is formed through R_a^T and a
    # principal se(3) logarithm.  This is adequate away from branch ambiguity.
    ra: Mat3 = ((a[0][0], a[0][1], a[0][2]), (a[1][0], a[1][1], a[1][2]), (a[2][0], a[2][1], a[2][2]))
    rb: Mat3 = ((b[0][0], b[0][1], b[0][2]), (b[1][0], b[1][1], b[1][2]), (b[2][0], b[2][1], b[2][2]))
    ta = (a[0][3], a[1][3], a[2][3]); tb = (b[0][3], b[1][3], b[2][3])
    rat = mat3_transpose(ra)
    rrel = mat3_mul(rat, rb)
    trel = mat3_vec(rat, sub(tb, ta))
    rel = mat4_from_rt(rrel, trel)
    xi = se3_log(rel)
    inc = se3_exp(scale(xi, t))
    ri: Mat3 = ((inc[0][0], inc[0][1], inc[0][2]), (inc[1][0], inc[1][1], inc[1][2]), (inc[2][0], inc[2][1], inc[2][2]))
    ti = (inc[0][3], inc[1][3], inc[2][3])
    rout = mat3_mul(ra, ri)
    tout = add(ta, mat3_vec(ra, ti))
    return mat4_from_rt(rout, tout)


def curvature_and_torsion(r1: Sequence[float], r2: Sequence[float], r3: Sequence[float], eps: float = 1e-12) -> Tuple[float, float, str]:
    if not (len(r1) == len(r2) == len(r3) == 3):
        raise ValueError("derivatives must be 3D")
    speed = norm(r1)
    c = cross(r1, r2)
    c_norm = norm(c)
    if speed <= eps:
        return 0.0, 0.0, "zero_speed"
    curvature = c_norm / speed**3
    if c_norm <= eps:
        return curvature, 0.0, "zero_curvature"
    torsion = dot(c, r3) / (c_norm * c_norm)
    return curvature, torsion, "ok"


def frenet_frame(r1: Sequence[float], r2: Sequence[float], r3: Sequence[float], eps: float = 1e-12) -> Tuple[Vec3, Vec3, Vec3, float, float, str]:
    curvature, torsion, status = curvature_and_torsion(r1, r2, r3, eps)
    if status == "zero_speed":
        raise ValueError("Frenet frame undefined at zero speed")
    tangent = normalize(r1)
    c = cross(r1, r2)
    if norm(c) <= eps:
        raise ValueError("Frenet normal undefined at zero curvature")
    binormal = normalize(c)
    normal = normalize(cross(binormal, tangent))
    return tangent, normal, binormal, curvature, torsion, status


def bishop_transport(previous_tangent: Sequence[float], previous_normal: Sequence[float], new_tangent: Sequence[float]) -> Tuple[Vec3, Vec3]:
    t0 = normalize(previous_tangent)
    n0 = normalize(previous_normal)
    t1 = normalize(new_tangent)
    axis = cross(t0, t1)
    axis_norm = norm(axis)
    d = clamp(dot(t0, t1), -1.0, 1.0)
    if axis_norm < 1e-12:
        if d > 0.0:
            n1 = normalize(sub(n0, scale(t1, dot(n0, t1))))
        else:
            # 180-degree turn: choose an axis orthogonal to t0 and n0.
            axis = normalize(cross(t0, n0))
            q = quat_from_axis_angle(axis, pi)
            n1 = normalize(quat_rotate(q, n0))
    else:
        q = quat_from_axis_angle(scale(axis, 1.0 / axis_norm), acos(d))
        n1 = normalize(quat_rotate(q, n0))
        n1 = normalize(sub(n1, scale(t1, dot(n1, t1))))
    b1 = normalize(cross(t1, n1))
    return n1, b1


def bishop_holonomy(points: Sequence[Sequence[float]]) -> float:
    if len(points) < 4 or any(len(p) != 3 for p in points):
        raise ValueError("closed 3D polyline with at least four points required")
    tangents = [normalize(sub(points[(i + 1) % len(points)], points[i])) for i in range(len(points))]
    t0 = tangents[0]
    seed = (1.0, 0.0, 0.0) if abs(t0[0]) < 0.8 else (0.0, 1.0, 0.0)
    n0 = normalize(sub(seed, scale(t0, dot(seed, t0))))
    n = n0
    for i in range(1, len(tangents) + 1):
        n, _ = bishop_transport(tangents[i - 1], n, tangents[i % len(tangents)])
    # Signed angle around initial tangent.
    b0 = cross(t0, n0)
    return atan2(dot(n, b0), dot(n, n0))


def arc_length_table(curve: Callable[[float], Sequence[float]], t0: float, t1: float, samples: int = 128) -> List[Tuple[float, float]]:
    if samples < 2:
        raise ValueError("samples must be at least 2")
    table = [(t0, 0.0)]
    prev = tuple(curve(t0))
    length = 0.0
    for i in range(1, samples):
        t = t0 + (t1 - t0) * i / (samples - 1)
        cur = tuple(curve(t))
        length += norm(sub(cur, prev))
        table.append((t, length))
        prev = cur
    return table


def curvature_speed_limit(curvature: float, max_lateral_acceleration: float, fallback_max_speed: float = float("inf")) -> float:
    if curvature < 0.0 or max_lateral_acceleration < 0.0 or fallback_max_speed <= 0.0:
        raise ValueError("invalid curvature/speed-limit parameters")
    if curvature <= 1e-15:
        return fallback_max_speed
    return min(fallback_max_speed, sqrt(max_lateral_acceleration / curvature))


def quintic_time_scaling(u: float) -> Tuple[float, float, float, float]:
    """Return position scale and first three derivatives versus normalized time."""
    if not 0.0 <= u <= 1.0:
        raise ValueError("u must be in [0,1]")
    s = 10 * u**3 - 15 * u**4 + 6 * u**5
    ds = 30 * u**2 - 60 * u**3 + 30 * u**4
    d2 = 60 * u - 180 * u**2 + 120 * u**3
    d3 = 60 - 360 * u + 360 * u**2
    return s, ds, d2, d3


def limit_aware_time_scale(path_length: float, max_speed: float, max_acceleration: float, max_jerk: float) -> float:
    if path_length < 0.0 or min(max_speed, max_acceleration, max_jerk) <= 0.0:
        raise ValueError("positive limits and nonnegative length required")
    if path_length == 0.0:
        return 0.0
    # Quintic normalized profile maxima are bounded conservatively by constants
    # 2, 6 and 60 for first, second and third derivatives.
    tv = 2.0 * path_length / max_speed
    ta = sqrt(6.0 * path_length / max_acceleration)
    tj = (60.0 * path_length / max_jerk) ** (1.0 / 3.0)
    return max(tv, ta, tj)


def forward_kinematics_2d(lengths: Sequence[float], angles: Sequence[float], base: Vec2 = (0.0, 0.0), base_angle: float = 0.0) -> List[Vec2]:
    if len(lengths) != len(angles) or any(l < 0.0 for l in lengths):
        raise ValueError("matching nonnegative link lengths and angles required")
    points = [base]
    x, y = base
    a = base_angle
    for length, joint in zip(lengths, angles):
        a += joint
        x += length * cos(a)
        y += length * sin(a)
        points.append((x, y))
    return points


def unicycle_from_flat_output(position: Vec2, first_derivative: Vec2, second_derivative: Vec2,
                               eps: float = 1e-12) -> Tuple[float, float, float, str]:
    speed = norm(first_derivative)
    if speed <= eps:
        return 0.0, 0.0, 0.0, "zero_speed"
    heading = atan2(first_derivative[1], first_derivative[0])
    angular_rate = (first_derivative[0] * second_derivative[1] - first_derivative[1] * second_derivative[0]) / (speed * speed)
    return heading, speed, angular_rate, "ok"
