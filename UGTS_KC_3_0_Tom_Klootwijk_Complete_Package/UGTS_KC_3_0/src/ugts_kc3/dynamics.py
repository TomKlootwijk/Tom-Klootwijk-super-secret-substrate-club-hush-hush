"""Bounded reference integrators and field-dynamics updates."""
from __future__ import annotations

from math import cos, exp, isfinite, sin, sqrt
from typing import Callable, Iterable, List, Sequence, Tuple

from .constraints import rattle_project_velocity_circle, shake_project_circle
from .kinematics import integrate_quaternion
from .math3 import Quat, add, scale


def symplectic_euler(position: Sequence[float], velocity: Sequence[float], acceleration: Sequence[float], dt: float) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    if not (len(position) == len(velocity) == len(acceleration)):
        raise ValueError("dimension mismatch")
    v = tuple(velocity[i] + dt * acceleration[i] for i in range(len(position)))
    x = tuple(position[i] + dt * v[i] for i in range(len(position)))
    return x, v


def velocity_verlet(position: Sequence[float], velocity: Sequence[float], acceleration_function: Callable[[Sequence[float]], Sequence[float]], dt: float) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    if len(position) != len(velocity):
        raise ValueError("dimension mismatch")
    a0 = tuple(acceleration_function(position))
    if len(a0) != len(position):
        raise ValueError("acceleration dimension mismatch")
    x = tuple(position[i] + velocity[i] * dt + 0.5 * a0[i] * dt * dt for i in range(len(position)))
    a1 = tuple(acceleration_function(x))
    v = tuple(velocity[i] + 0.5 * (a0[i] + a1[i]) * dt for i in range(len(position)))
    return x, v


def damped_oscillator_exact(x0: float, v0: float, mass: float, damping: float, stiffness: float, t: float) -> Tuple[float, float]:
    if mass <= 0.0 or damping < 0.0 or stiffness < 0.0 or t < 0.0:
        raise ValueError("invalid oscillator parameters")
    if stiffness == 0.0:
        if damping == 0.0:
            return x0 + v0 * t, v0
        alpha = damping / mass
        v = v0 * exp(-alpha * t)
        return x0 + v0 * (1.0 - exp(-alpha * t)) / alpha, v
    omega0_sq = stiffness / mass
    alpha = damping / (2.0 * mass)
    disc = omega0_sq - alpha * alpha
    if disc > 1e-14:
        wd = sqrt(disc)
        a = x0
        b = (v0 + alpha * x0) / wd
        e = exp(-alpha * t)
        c, s = cos(wd * t), sin(wd * t)
        x = e * (a * c + b * s)
        v = e * ((-alpha * a + b * wd) * c + (-alpha * b - a * wd) * s)
        return x, v
    if abs(disc) <= 1e-14:
        e = exp(-alpha * t)
        b = v0 + alpha * x0
        x = e * (x0 + b * t)
        v = e * (b - alpha * (x0 + b * t))
        return x, v
    sdisc = sqrt(-disc)
    r1, r2 = -alpha + sdisc, -alpha - sdisc
    c1 = (v0 - r2 * x0) / (r1 - r2)
    c2 = x0 - c1
    x = c1 * exp(r1 * t) + c2 * exp(r2 * t)
    v = r1 * c1 * exp(r1 * t) + r2 * c2 * exp(r2 * t)
    return x, v


def graph_diffusion_step(values: Sequence[float], edges: Sequence[Tuple[int, int, float]], dt: float, rate: float = 1.0) -> List[float]:
    if dt < 0.0 or rate < 0.0:
        raise ValueError("dt and rate must be nonnegative")
    delta = [0.0] * len(values)
    for u, v, weight in edges:
        if not (0 <= u < len(values) and 0 <= v < len(values)) or weight < 0.0:
            raise ValueError("invalid graph edge")
        flux = rate * weight * (values[v] - values[u])
        delta[u] += flux
        delta[v] -= flux
    return [values[i] + dt * delta[i] for i in range(len(values))]


def _laplacian_periodic(values: Sequence[float], dx: float = 1.0) -> List[float]:
    if len(values) < 3 or dx <= 0.0:
        raise ValueError("periodic Laplacian requires at least 3 values and dx>0")
    inv = 1.0 / (dx * dx)
    n = len(values)
    return [(values[(i - 1) % n] - 2.0 * values[i] + values[(i + 1) % n]) * inv for i in range(n)]


def gray_scott_step_1d(u: Sequence[float], v: Sequence[float], dt: float, du: float = 0.16, dv: float = 0.08,
                       feed: float = 0.060, kill: float = 0.062, dx: float = 1.0) -> Tuple[List[float], List[float]]:
    if len(u) != len(v) or dt < 0.0 or min(du, dv, feed, kill) < 0.0:
        raise ValueError("invalid Gray-Scott parameters")
    lu, lv = _laplacian_periodic(u, dx), _laplacian_periodic(v, dx)
    out_u, out_v = [], []
    for i in range(len(u)):
        reaction = u[i] * v[i] * v[i]
        out_u.append(u[i] + dt * (du * lu[i] - reaction + feed * (1.0 - u[i])))
        out_v.append(v[i] + dt * (dv * lv[i] + reaction - (feed + kill) * v[i]))
    return out_u, out_v


def hamiltonian_symplectic_euler(q: float, p: float, dt: float,
                                 dH_dq: Callable[[float, float], float], dH_dp: Callable[[float, float], float]) -> Tuple[float, float]:
    p_new = p - dt * dH_dq(q, p)
    q_new = q + dt * dH_dp(q, p_new)
    return q_new, p_new


def discrete_variational_oscillator(q_prev: float, q_current: float, dt: float, omega: float) -> float:
    if dt <= 0.0 or omega < 0.0:
        raise ValueError("invalid variational oscillator parameters")
    return 2.0 * q_current - q_prev - dt * dt * omega * omega * q_current


def implicit_midpoint_scalar(y: float, dt: float, derivative: Callable[[float], float],
                             tolerance: float = 1e-12, max_iterations: int = 32) -> Tuple[float, int, float]:
    if tolerance <= 0.0 or max_iterations < 1:
        raise ValueError("invalid implicit-midpoint parameters")
    guess = y + dt * derivative(y)
    for iteration in range(1, max_iterations + 1):
        midpoint = 0.5 * (y + guess)
        new = y + dt * derivative(midpoint)
        residual = abs(new - guess)
        guess = new
        if residual <= tolerance:
            return guess, iteration, residual
    return guess, max_iterations, abs(y + dt * derivative(0.5 * (y + guess)) - guess)


def stormer_verlet(q: float, p: float, dt: float,
                   force: Callable[[float], float], inverse_mass: float = 1.0) -> Tuple[float, float]:
    if inverse_mass < 0.0:
        raise ValueError("inverse_mass must be nonnegative")
    p_half = p + 0.5 * dt * force(q)
    q_new = q + dt * inverse_mass * p_half
    p_new = p_half + 0.5 * dt * force(q_new)
    return q_new, p_new


def lie_group_quaternion_step(q: Quat, angular_velocity: Sequence[float], dt: float) -> Quat:
    return integrate_quaternion(q, angular_velocity, dt)


def projected_symplectic_circle(position: Sequence[float], velocity: Sequence[float], acceleration: Sequence[float],
                                dt: float, radius: float = 1.0) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
    trial_x, trial_v = symplectic_euler(position, velocity, acceleration, dt)
    projected_x, _, residual = shake_project_circle(trial_x, radius)
    projected_v = rattle_project_velocity_circle(projected_x, trial_v)
    return projected_x, projected_v, residual


def _periodic_linear_sample(values: Sequence[float], x: float) -> float:
    n = len(values)
    x %= n
    i0 = int(x) % n
    i1 = (i0 + 1) % n
    t = x - int(x)
    return (1.0 - t) * values[i0] + t * values[i1]


def semi_lagrangian_1d(values: Sequence[float], velocity: Sequence[float] | float, dt: float, dx: float = 1.0) -> List[float]:
    if len(values) < 2 or dx <= 0.0:
        raise ValueError("invalid semi-Lagrangian parameters")
    if isinstance(velocity, (int, float)):
        velocities = [float(velocity)] * len(values)
    else:
        velocities = list(velocity)
        if len(velocities) != len(values):
            raise ValueError("velocity length mismatch")
    return [_periodic_linear_sample(values, i - velocities[i] * dt / dx) for i in range(len(values))]


def _solve_tridiagonal(a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]) -> List[float]:
    n = len(d)
    if not (len(a) == len(b) == len(c) == n):
        raise ValueError("tridiagonal arrays must match")
    cp = [0.0] * n; dp = [0.0] * n
    if abs(b[0]) <= 1e-30:
        raise ValueError("singular tridiagonal system")
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n):
        denom = b[i] - a[i] * cp[i - 1]
        if abs(denom) <= 1e-30:
            raise ValueError("singular tridiagonal system")
        cp[i] = c[i] / denom if i < n - 1 else 0.0
        dp[i] = (d[i] - a[i] * dp[i - 1]) / denom
    x = [0.0] * n
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def implicit_diffusion_1d(values: Sequence[float], diffusivity: float, dt: float, dx: float = 1.0) -> List[float]:
    if len(values) < 3 or diffusivity < 0.0 or dt < 0.0 or dx <= 0.0:
        raise ValueError("invalid diffusion parameters")
    if dt == 0.0 or diffusivity == 0.0:
        return [float(v) for v in values]
    n = len(values)
    r = diffusivity * dt / (dx * dx)
    # Dirichlet boundaries are held fixed.
    interior = n - 2
    a = [0.0] + [-r] * (interior - 1)
    b = [1.0 + 2.0 * r] * interior
    c = [-r] * (interior - 1) + [0.0]
    d = [float(values[i + 1]) for i in range(interior)]
    d[0] += r * values[0]
    d[-1] += r * values[-1]
    solved = _solve_tridiagonal(a, b, c, d)
    return [float(values[0])] + solved + [float(values[-1])]


def wave_leapfrog_1d(previous: Sequence[float], current: Sequence[float], wave_speed: float, dt: float, dx: float = 1.0) -> List[float]:
    if len(previous) != len(current) or len(current) < 3 or wave_speed < 0.0 or dt < 0.0 or dx <= 0.0:
        raise ValueError("invalid wave parameters")
    cfl = wave_speed * dt / dx
    if cfl > 1.0 + 1e-12:
        raise ValueError("CFL condition violated")
    out = [float(current[0])]
    c2 = cfl * cfl
    for i in range(1, len(current) - 1):
        out.append(2.0 * current[i] - previous[i] + c2 * (current[i - 1] - 2.0 * current[i] + current[i + 1]))
    out.append(float(current[-1]))
    return out


def gray_scott_split_1d(u: Sequence[float], v: Sequence[float], dt: float, du: float = 0.16, dv: float = 0.08,
                        feed: float = 0.060, kill: float = 0.062, dx: float = 1.0, substeps: int = 1) -> Tuple[List[float], List[float]]:
    if substeps < 1:
        raise ValueError("substeps must be positive")
    uu, vv = [float(x) for x in u], [float(x) for x in v]
    h = dt / substeps
    for _ in range(substeps):
        lu, lv = _laplacian_periodic(uu, dx), _laplacian_periodic(vv, dx)
        uu = [uu[i] + h * du * lu[i] for i in range(len(uu))]
        vv = [vv[i] + h * dv * lv[i] for i in range(len(vv))]
        for i in range(len(uu)):
            reaction = uu[i] * vv[i] * vv[i]
            uu[i] += h * (-reaction + feed * (1.0 - uu[i]))
            vv[i] += h * (reaction - (feed + kill) * vv[i])
    return uu, vv


def allen_cahn_step_1d(phi: Sequence[float], dt: float, mobility: float = 1.0, epsilon: float = 1.0, dx: float = 1.0) -> List[float]:
    if dt < 0.0 or mobility < 0.0 or epsilon <= 0.0:
        raise ValueError("invalid Allen-Cahn parameters")
    lap = _laplacian_periodic(phi, dx)
    return [phi[i] + dt * mobility * (epsilon * epsilon * lap[i] - (phi[i] ** 3 - phi[i])) for i in range(len(phi))]


def cahn_hilliard_step_1d(phi: Sequence[float], dt: float, mobility: float = 1.0, epsilon: float = 1.0, dx: float = 1.0) -> List[float]:
    if dt < 0.0 or mobility < 0.0 or epsilon <= 0.0:
        raise ValueError("invalid Cahn-Hilliard parameters")
    lap_phi = _laplacian_periodic(phi, dx)
    chemical = [phi[i] ** 3 - phi[i] - epsilon * epsilon * lap_phi[i] for i in range(len(phi))]
    lap_mu = _laplacian_periodic(chemical, dx)
    return [phi[i] + dt * mobility * lap_mu[i] for i in range(len(phi))]


def _eikonal_update(a: float, b: float, h_over_f: float) -> float:
    lo, hi = min(a, b), max(a, b)
    if not isfinite(lo):
        return float("inf")
    if hi - lo >= h_over_f or not isfinite(hi):
        return lo + h_over_f
    disc = 2.0 * h_over_f * h_over_f - (hi - lo) ** 2
    return 0.5 * (lo + hi + sqrt(max(0.0, disc)))


def fast_sweeping_eikonal(speed: Sequence[Sequence[float]], sources: Iterable[Tuple[int, int]], grid_spacing: float = 1.0,
                           sweeps: int = 8) -> List[List[float]]:
    if not speed or not speed[0] or any(len(row) != len(speed[0]) for row in speed) or grid_spacing <= 0.0 or sweeps < 1:
        raise ValueError("invalid Eikonal grid")
    rows, cols = len(speed), len(speed[0])
    if any(v <= 0.0 for row in speed for v in row):
        raise ValueError("speed must be positive")
    t = [[float("inf") for _ in range(cols)] for _ in range(rows)]
    source_set = set(sources)
    for i, j in source_set:
        if not (0 <= i < rows and 0 <= j < cols):
            raise ValueError("source outside grid")
        t[i][j] = 0.0
    orders = [
        (range(rows), range(cols)),
        (range(rows - 1, -1, -1), range(cols)),
        (range(rows), range(cols - 1, -1, -1)),
        (range(rows - 1, -1, -1), range(cols - 1, -1, -1)),
    ]
    for _ in range(sweeps):
        for irange, jrange in orders:
            for i in irange:
                for j in jrange:
                    if (i, j) in source_set:
                        continue
                    a = min(t[i - 1][j] if i > 0 else float("inf"), t[i + 1][j] if i + 1 < rows else float("inf"))
                    b = min(t[i][j - 1] if j > 0 else float("inf"), t[i][j + 1] if j + 1 < cols else float("inf"))
                    candidate = _eikonal_update(a, b, grid_spacing / speed[i][j])
                    if candidate < t[i][j]:
                        t[i][j] = candidate
    return t
