"""Holonomic constraints, projection and bounded contact/impact helpers."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

from .math3 import Vec2, Vec3, add, clamp, dot, norm, normalize, scale, sub


@dataclass(frozen=True)
class HolonomicConstraint:
    name: str
    value: Callable[[Sequence[float], float], float]
    tolerance: float = 1e-9

    def evaluate(self, q: Sequence[float], t: float = 0.0) -> float:
        return float(self.value(q, t))

    def satisfied(self, q: Sequence[float], t: float = 0.0) -> bool:
        return abs(self.evaluate(q, t)) <= self.tolerance


def numeric_jacobian(phi: Callable[[Sequence[float]], float], q: Sequence[float], h: float = 1e-6) -> Tuple[float, ...]:
    if h <= 0.0:
        raise ValueError("h must be positive")
    out = []
    for i in range(len(q)):
        qp = list(q); qm = list(q)
        qp[i] += h; qm[i] -= h
        out.append((phi(qp) - phi(qm)) / (2.0 * h))
    return tuple(out)


def baumgarte_term(phi: float, phi_dot: float, omega: float, zeta: float = 1.0) -> float:
    if omega < 0.0 or zeta < 0.0:
        raise ValueError("omega and zeta must be nonnegative")
    return -2.0 * zeta * omega * phi_dot - omega * omega * phi


def shake_project_circle(q: Sequence[float], radius: float = 1.0, tolerance: float = 1e-12,
                         max_iterations: int = 16) -> Tuple[Vec2, int, float]:
    if len(q) != 2 or radius <= 0.0 or tolerance <= 0.0 or max_iterations < 1:
        raise ValueError("invalid SHAKE parameters")
    x = [float(q[0]), float(q[1])]
    for iteration in range(1, max_iterations + 1):
        phi = x[0] * x[0] + x[1] * x[1] - radius * radius
        if abs(phi) <= tolerance:
            return (x[0], x[1]), iteration - 1, abs(phi)
        grad = (2.0 * x[0], 2.0 * x[1])
        denom = dot(grad, grad)
        if denom <= 1e-30:
            raise ValueError("circle projection singular at origin")
        lam = phi / denom
        x[0] -= lam * grad[0]
        x[1] -= lam * grad[1]
    residual = abs(x[0] * x[0] + x[1] * x[1] - radius * radius)
    return (x[0], x[1]), max_iterations, residual


def rattle_project_velocity_circle(q: Sequence[float], v: Sequence[float]) -> Vec2:
    if len(q) != 2 or len(v) != 2:
        raise ValueError("q and v must be 2D")
    denom = dot(q, q)
    if denom <= 1e-30:
        raise ValueError("circle tangent undefined at origin")
    normal_component = dot(q, v) / denom
    return (v[0] - normal_component * q[0], v[1] - normal_component * q[1])


def solve_single_multiplier(jacobian: Sequence[float], inverse_mass_diagonal: Sequence[float], rhs: float,
                            tolerance: float = 1e-15) -> Tuple[float, str]:
    if len(jacobian) != len(inverse_mass_diagonal) or any(m < 0.0 for m in inverse_mass_diagonal):
        raise ValueError("matching Jacobian and nonnegative inverse masses required")
    effective = sum(j * j * m for j, m in zip(jacobian, inverse_mass_diagonal))
    if effective <= tolerance:
        return 0.0, "singular"
    return rhs / effective, "ok"


def project_to_nullspace_single(vector: Sequence[float], jacobian: Sequence[float], tolerance: float = 1e-15) -> Tuple[float, ...]:
    if len(vector) != len(jacobian):
        raise ValueError("dimension mismatch")
    denom = dot(jacobian, jacobian)
    if denom <= tolerance:
        return tuple(float(x) for x in vector)
    coeff = dot(jacobian, vector) / denom
    return tuple(vector[i] - coeff * jacobian[i] for i in range(len(vector)))


def gap_plane(point: Sequence[float], plane_point: Sequence[float], plane_normal: Sequence[float]) -> float:
    if not (len(point) == len(plane_point) == len(plane_normal)):
        raise ValueError("dimension mismatch")
    n = normalize(plane_normal)
    return dot(sub(point, plane_point), n)


def complementarity_residual(normal_impulse: float, gap_or_velocity: float) -> Tuple[float, float, float]:
    """Return nonnegativity and product residuals for a scalar complementarity pair."""
    return (max(0.0, -normal_impulse), max(0.0, -gap_or_velocity), abs(normal_impulse * gap_or_velocity))


def restitution_target_velocity(pre_impact_normal_velocity: float, restitution: float,
                                activation_speed: float = 1e-6) -> float:
    if not 0.0 <= restitution <= 1.0 or activation_speed < 0.0:
        raise ValueError("invalid restitution parameters")
    if pre_impact_normal_velocity >= -activation_speed:
        return 0.0
    return -restitution * pre_impact_normal_velocity


def normal_impact_impulse(relative_normal_velocity: float, inverse_mass_sum: float,
                          restitution: float = 0.0, activation_speed: float = 1e-6) -> float:
    if inverse_mass_sum <= 0.0:
        raise ValueError("inverse_mass_sum must be positive")
    target = restitution_target_velocity(relative_normal_velocity, restitution, activation_speed)
    impulse = (target - relative_normal_velocity) / inverse_mass_sum
    return max(0.0, impulse)


def clamp_friction_cone_2d(tangential_impulse: Sequence[float], mu: float, normal_impulse: float) -> Vec2:
    if len(tangential_impulse) != 2 or mu < 0.0 or normal_impulse < 0.0:
        raise ValueError("invalid friction parameters")
    limit = mu * normal_impulse
    n = norm(tangential_impulse)
    if n <= limit or n <= 1e-30:
        return (float(tangential_impulse[0]), float(tangential_impulse[1]))
    s = limit / n
    return (tangential_impulse[0] * s, tangential_impulse[1] * s)


def clamp_friction_pyramid_2d(tangential_impulse: Sequence[float], mu: float, normal_impulse: float) -> Vec2:
    if len(tangential_impulse) != 2 or mu < 0.0 or normal_impulse < 0.0:
        raise ValueError("invalid friction parameters")
    limit = mu * normal_impulse
    # L-infinity square/pyramid section; conservative only after a declared
    # scaling convention.  Here each component is independently bounded.
    return (clamp(tangential_impulse[0], -limit, limit), clamp(tangential_impulse[1], -limit, limit))


def reduce_contacts(contacts: Sequence[Mapping[str, object]], max_contacts: int = 4) -> List[Mapping[str, object]]:
    """Deterministically retain deepest and spatially diverse contacts.

    Contact dictionaries may contain ``depth`` and ``point``.  The reference
    routine first keeps the deepest contact and then greedily maximizes distance
    from the selected set.
    """
    if max_contacts < 1:
        raise ValueError("max_contacts must be positive")
    if len(contacts) <= max_contacts:
        return list(contacts)
    indexed = list(enumerate(contacts))
    deepest = min(indexed, key=lambda item: (float(item[1].get("depth", 0.0)), item[0]))
    selected = [deepest]
    remaining = [item for item in indexed if item[0] != deepest[0]]
    while remaining and len(selected) < max_contacts:
        def score(item):
            p = item[1].get("point", (0.0, 0.0, 0.0))
            p = tuple(float(x) for x in p)  # type: ignore[arg-type]
            min_dist = min(norm(sub(p, tuple(float(x) for x in s[1].get("point", (0.0, 0.0, 0.0))))) for s in selected)
            return (min_dist, -item[0])
        chosen = max(remaining, key=score)
        selected.append(chosen)
        remaining = [item for item in remaining if item[0] != chosen[0]]
    return [item[1] for item in sorted(selected, key=lambda item: item[0])]


def apply_warm_start(velocity: Sequence[float], inverse_mass: float, impulses: Iterable[Sequence[float]]) -> Tuple[float, ...]:
    if inverse_mass < 0.0:
        raise ValueError("inverse_mass must be nonnegative")
    out = [float(x) for x in velocity]
    for impulse in impulses:
        if len(impulse) != len(out):
            raise ValueError("impulse dimension mismatch")
        for i in range(len(out)):
            out[i] += inverse_mass * impulse[i]
    return tuple(out)
