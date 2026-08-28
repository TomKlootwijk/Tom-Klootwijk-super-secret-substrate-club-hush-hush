"""UGTS-KC 3.6.2 SCLP reference operators.

SCLP means *Swept-Cone Log-Polar Packing*.  The module distills the attached
13-page source into a bounded, query-first geometric-topological substrate.
It deliberately does not implement rasterization, ray marching or a renderer.

The source motifs are preserved, but overloaded or absolute statements are
separated into typed operators:

* ``T`` is a cone slant length; time is ``t`` or a declared modular tick ``X``;
* lower-case ``phi`` is a periodic hinge/hoop angle, not the golden ratio;
* a bit shift appends a radix-trie branch bit; it does not directly halve a
  physical coordinate;
* the source half-turn bundle twist and a genuine orientation-reversing Klein
  quotient are distinct profiles;
* one-bit jitter is a deterministic bounded perturbation/route selector, not
  complete state;
* a 64-bit key is finite and quantized; it does not contain infinite detail;
* width ratios are not called compression ratios unless the compared records
  preserve the same semantics and error contract.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Matrix = tuple[tuple[float, ...], ...]

TAU = 2.0 * math.pi


# ---------------------------------------------------------------------------
# Small vector helpers
# ---------------------------------------------------------------------------


def _v3(value: Sequence[float]) -> Vec3:
    if len(value) != 3:
        raise ValueError("expected a 3-vector")
    out = (float(value[0]), float(value[1]), float(value[2]))
    if not all(math.isfinite(x) for x in out):
        raise ValueError("vector entries must be finite")
    return out


def v_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def v_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_norm(a: Vec3) -> float:
    return math.sqrt(v_dot(a, a))


def v_normalize(a: Vec3) -> Vec3:
    length = v_norm(a)
    if length <= 0.0:
        raise ValueError("zero vector cannot be normalized")
    return v_scale(a, 1.0 / length)


def wrap_angle(theta: float) -> float:
    """Return an angle in ``[-pi, pi)``."""

    return (float(theta) + math.pi) % TAU - math.pi


# ---------------------------------------------------------------------------
# Finite right circular cone and sphere relations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FiniteCone:
    """Finite right circular cone parameterized by slant length and half-angle.

    The source uses ``T`` as the side of a pyramidal/conical cross-section.  A
    single side length does not determine a cone, so the bounded profile also
    declares a half-angle ``alpha``.  Height and base radius are then exact:

    ``h = T cos(alpha)`` and ``R = T sin(alpha)``.
    """

    slant_length: float
    half_angle: float
    apex: Vec3 = (0.0, 0.0, 0.0)
    axis: Vec3 = (0.0, 0.0, 1.0)

    def __post_init__(self) -> None:
        if not math.isfinite(self.slant_length) or self.slant_length <= 0.0:
            raise ValueError("slant_length must be positive and finite")
        if not math.isfinite(self.half_angle) or not (0.0 < self.half_angle < math.pi / 2.0):
            raise ValueError("half_angle must lie in (0, pi/2)")
        object.__setattr__(self, "apex", _v3(self.apex))
        object.__setattr__(self, "axis", v_normalize(_v3(self.axis)))

    @property
    def height(self) -> float:
        return self.slant_length * math.cos(self.half_angle)

    @property
    def base_radius(self) -> float:
        return self.slant_length * math.sin(self.half_angle)

    @property
    def bounding_radius(self) -> float:
        # Every point of the cone lies within slant_length of the apex.
        return self.slant_length

    def translated(self, offset: Vec3) -> "FiniteCone":
        return FiniteCone(
            slant_length=self.slant_length,
            half_angle=self.half_angle,
            apex=v_add(self.apex, offset),
            axis=self.axis,
        )

    def signed_distance(self, point: Vec3) -> float:
        """Exact Euclidean signed distance to the finite solid cone.

        Rotational symmetry reduces the problem to signed distance from the
        meridian point ``(q,z)`` to the filled triangle with vertices
        ``(-R,h)``, ``(R,h)``, ``(0,0)``.  The closest 3D point can always be
        chosen in the meridian plane containing the query point and the axis.
        """

        p = v_sub(_v3(point), self.apex)
        z = v_dot(p, self.axis)
        radial = v_sub(p, v_scale(self.axis, z))
        q = v_norm(radial)
        R = self.base_radius
        h = self.height
        pt = (q, z)
        a = (-R, h)
        b = (R, h)
        c = (0.0, 0.0)
        distance = min(
            _point_segment_distance_2d(pt, a, b),
            _point_segment_distance_2d(pt, b, c),
            _point_segment_distance_2d(pt, c, a),
        )
        inside = (0.0 <= z <= h) and (q <= z * math.tan(self.half_angle) + 1e-15)
        return -distance if inside and distance > 0.0 else distance

    def relation_class(self, point: Vec3, epsilon: float = 0.0) -> int:
        value = self.signed_distance(point)
        if abs(value) <= epsilon:
            return 0
        return -1 if value < 0.0 else 1


@dataclass(frozen=True)
class SphereRelation:
    center: Vec3
    radius: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _v3(self.center))
        if not math.isfinite(self.radius) or self.radius <= 0.0:
            raise ValueError("radius must be positive and finite")

    def signed_distance(self, point: Vec3) -> float:
        return v_norm(v_sub(_v3(point), self.center)) - self.radius


@dataclass(frozen=True)
class PairedSphereSupport:
    """Two local spherical supports (the source's two-sphered eye motif)."""

    left: SphereRelation
    right: SphereRelation
    mode: str = "union"

    def __post_init__(self) -> None:
        if self.mode not in {"union", "intersection", "either-with-tag"}:
            raise ValueError("unsupported paired-sphere mode")

    def classify(self, point: Vec3) -> dict[str, Any]:
        dl = self.left.signed_distance(point)
        dr = self.right.signed_distance(point)
        left_in = dl <= 0.0
        right_in = dr <= 0.0
        admitted = (left_in or right_in) if self.mode != "intersection" else (left_in and right_in)
        return {
            "left_sdf": dl,
            "right_sdf": dr,
            "left_in": left_in,
            "right_in": right_in,
            "overlap": left_in and right_in,
            "admitted": admitted,
            "mode": self.mode,
        }


def _point_segment_distance_2d(p: Vec2, a: Vec2, b: Vec2) -> float:
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    denom = ab[0] * ab[0] + ab[1] * ab[1]
    if denom == 0.0:
        return math.hypot(ap[0], ap[1])
    t = max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1]) / denom))
    q = (a[0] + t * ab[0], a[1] + t * ab[1])
    return math.hypot(p[0] - q[0], p[1] - q[1])


# ---------------------------------------------------------------------------
# Certified translational sweep relation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinearSweepSegment:
    start_offset: Vec3
    end_offset: Vec3

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_offset", _v3(self.start_offset))
        object.__setattr__(self, "end_offset", _v3(self.end_offset))

    @property
    def length(self) -> float:
        return v_norm(v_sub(self.end_offset, self.start_offset))

    def offset_at(self, u: float) -> Vec3:
        if not 0.0 <= u <= 1.0:
            raise ValueError("u must lie in [0,1]")
        return v_add(self.start_offset, v_scale(v_sub(self.end_offset, self.start_offset), u))


@dataclass(frozen=True)
class SweepBoundCertificate:
    sample_count: int
    sample_min: float
    lower_bound: float
    upper_bound: float
    lipschitz_error: float
    status: str

    @property
    def contains_zero(self) -> bool:
        return self.lower_bound <= 0.0 <= self.upper_bound


def certify_linear_cone_sweep(
    point: Vec3,
    cone: FiniteCone,
    segment: LinearSweepSegment,
    *,
    sample_count: int = 33,
    guard_band: float = 0.0,
) -> SweepBoundCertificate:
    """Bound the infimum relation over a translated cone sweep.

    For fixed orientation, translation changes a signed-distance field by at
    most the translation magnitude.  With uniformly spaced samples, the true
    infimum lies in ``[sample_min - L*h/2, sample_min]``, where ``L`` is the
    segment length and ``h`` is the parameter spacing.  This is a certified
    interval, not a claim that an arbitrary sweep has a closed-form SDF.
    """

    if sample_count < 2:
        raise ValueError("sample_count must be at least 2")
    if guard_band < 0.0 or not math.isfinite(guard_band):
        raise ValueError("guard_band must be finite and non-negative")
    values = []
    for i in range(sample_count):
        u = i / (sample_count - 1)
        values.append(cone.translated(segment.offset_at(u)).signed_distance(point))
    sample_min = min(values)
    error = segment.length / (2.0 * (sample_count - 1))
    lower = sample_min - error
    upper = sample_min
    if lower > guard_band:
        status = "certified-outside"
    elif upper < -guard_band:
        status = "certified-inside-witness"
    else:
        status = "guard-or-boundary-uncertain"
    return SweepBoundCertificate(
        sample_count=sample_count,
        sample_min=sample_min,
        lower_bound=lower,
        upper_bound=upper,
        lipschitz_error=error,
        status=status,
    )


# ---------------------------------------------------------------------------
# Log-polar chart, metric and kinematic calculus
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LogPolarChart:
    r0: float = 1.0
    rho_min: float = -20.0
    rho_max: float = 0.0
    core_radius: float = 1e-12

    def __post_init__(self) -> None:
        if not (math.isfinite(self.r0) and self.r0 > 0.0):
            raise ValueError("r0 must be positive")
        if not (math.isfinite(self.rho_min) and math.isfinite(self.rho_max) and self.rho_min < self.rho_max):
            raise ValueError("invalid rho range")
        if not (math.isfinite(self.core_radius) and self.core_radius > 0.0):
            raise ValueError("core_radius must be positive")

    def encode(self, x: float, y: float) -> tuple[float, float, bool]:
        r = math.hypot(x, y)
        if r < self.core_radius:
            return (self.rho_min, 0.0, True)
        return (math.log(r / self.r0), math.atan2(y, x), False)

    def decode(self, rho: float, theta: float) -> Vec2:
        r = self.r0 * math.exp(float(rho))
        return (r * math.cos(theta), r * math.sin(theta))

    def metric_scale(self, rho: float) -> float:
        """Return the conformal factor ``r^2`` for ``ds^2=r^2(dρ²+dθ²)``."""

        r = self.r0 * math.exp(float(rho))
        return r * r

    def jacobian(self, rho: float, theta: float) -> tuple[tuple[float, float], tuple[float, float]]:
        r = self.r0 * math.exp(float(rho))
        c = math.cos(theta)
        s = math.sin(theta)
        return ((r * c, -r * s), (r * s, r * c))

    def exact_radial_increment(self, rho: float, delta_rho: float) -> float:
        """Exact real-radius increment produced by a log-radius step."""

        r = self.r0 * math.exp(float(rho))
        return r * math.expm1(float(delta_rho))

    def cartesian_velocity(self, rho: float, theta: float, rho_dot: float, theta_dot: float) -> Vec2:
        r = self.r0 * math.exp(float(rho))
        er = (math.cos(theta), math.sin(theta))
        et = (-math.sin(theta), math.cos(theta))
        return (
            r * (rho_dot * er[0] + theta_dot * et[0]),
            r * (rho_dot * er[1] + theta_dot * et[1]),
        )

    def cartesian_acceleration(
        self,
        rho: float,
        theta: float,
        rho_dot: float,
        theta_dot: float,
        rho_ddot: float,
        theta_ddot: float,
    ) -> Vec2:
        r = self.r0 * math.exp(float(rho))
        er = (math.cos(theta), math.sin(theta))
        et = (-math.sin(theta), math.cos(theta))
        ar = rho_ddot + rho_dot * rho_dot - theta_dot * theta_dot
        at = theta_ddot + 2.0 * rho_dot * theta_dot
        return (r * (ar * er[0] + at * et[0]), r * (ar * er[1] + at * et[1]))

    def gradient_to_cartesian(self, rho: float, theta: float, df_drho: float, df_dtheta: float) -> Vec2:
        r = self.r0 * math.exp(float(rho))
        er = (math.cos(theta), math.sin(theta))
        et = (-math.sin(theta), math.cos(theta))
        return (
            (df_drho * er[0] + df_dtheta * et[0]) / r,
            (df_drho * er[1] + df_dtheta * et[1]) / r,
        )


# ---------------------------------------------------------------------------
# One-bit deterministic jitter with an interval contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OneBitJitter:
    amplitude: float
    guard_margin: float
    seed: str = "sclp362"

    def __post_init__(self) -> None:
        if not math.isfinite(self.amplitude) or self.amplitude < 0.0:
            raise ValueError("amplitude must be finite and non-negative")
        if not math.isfinite(self.guard_margin) or self.guard_margin < 0.0:
            raise ValueError("guard_margin must be finite and non-negative")
        if not self.seed:
            raise ValueError("seed must not be empty")

    @property
    def safe_under_margin(self) -> bool:
        return self.amplitude < self.guard_margin if self.guard_margin > 0.0 else self.amplitude == 0.0

    def bit(self, address: int, time_tick: int) -> int:
        payload = f"{self.seed}|{int(address)}|{int(time_tick)}".encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        return digest[0] & 1

    def signed_offset(self, address: int, time_tick: int) -> float:
        return self.amplitude if self.bit(address, time_tick) else -self.amplitude

    def interval(self, authoritative_residual: float) -> tuple[float, float]:
        value = float(authoritative_residual)
        return (value - self.amplitude, value + self.amplitude)

    def certificate(self, authoritative_residual: float, address: int, time_tick: int) -> dict[str, Any]:
        bit = self.bit(address, time_tick)
        lo, hi = self.interval(authoritative_residual)
        return {
            "bit": bit,
            "offset": self.signed_offset(address, time_tick),
            "authoritative_residual": authoritative_residual,
            "interval": [lo, hi],
            "amplitude": self.amplitude,
            "guard_margin": self.guard_margin,
            "safe_under_margin": self.safe_under_margin,
            "role": "bounded perturbation or route metadata; not complete state",
        }


# ---------------------------------------------------------------------------
# Time as a linear coordinate plus periodic phase and winding count
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseClock:
    reference_tick: int = 1135  # 18:55 when the declared unit is minutes from midnight
    period_ticks: int = 256
    unit: str = "minute"

    def __post_init__(self) -> None:
        if self.period_ticks <= 0:
            raise ValueError("period_ticks must be positive")
        if not self.unit:
            raise ValueError("time unit must be declared")

    def state(self, tick: int | float) -> dict[str, Any]:
        unwrapped = (float(tick) - self.reference_tick) / self.period_ticks
        winding = math.floor(unwrapped)
        phase = unwrapped - winding
        return {
            "tick": float(tick),
            "reference_tick": self.reference_tick,
            "period_ticks": self.period_ticks,
            "unit": self.unit,
            "phase_S1": phase,
            "winding": winding,
            "winding_parity": winding & 1,
            "note": "linear time is retained; only the phase is periodic",
        }


# ---------------------------------------------------------------------------
# Source half-turn bundle twist and corrected Klein quotient
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopologicalWrapState:
    rho: float
    theta: float
    phi: float
    orientation: int
    wrap_count: int = 0

    def __post_init__(self) -> None:
        if self.orientation not in {-1, 1}:
            raise ValueError("orientation must be -1 or +1")


@dataclass(frozen=True)
class RadialTwistBundle:
    rho_min: float = -20.0
    rho_max: float = 0.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.rho_min) and math.isfinite(self.rho_max) and self.rho_min < self.rho_max):
            raise ValueError("invalid radial interval")

    @property
    def width(self) -> float:
        return self.rho_max - self.rho_min

    def _reduce(self, rho: float) -> tuple[float, int]:
        k = math.floor((rho - self.rho_min) / self.width)
        wrapped = rho - k * self.width
        # Defend against round-off at the upper boundary.
        if wrapped >= self.rho_max:
            wrapped -= self.width
            k += 1
        if wrapped < self.rho_min:
            wrapped += self.width
            k -= 1
        return wrapped, k

    def source_half_turn(self, state: TopologicalWrapState) -> dict[str, Any]:
        """Implement the source formula ``theta+pi, -phi`` on odd radial wraps.

        This is retained as an internal state-bundle twist.  Because ``theta``
        is shifted rather than reflected, the base-coordinate gluing alone is
        orientation preserving and is not called a Klein-bottle quotient.
        """

        rho, k = self._reduce(state.rho)
        odd = abs(k) & 1
        theta = wrap_angle(state.theta + (math.pi if odd else 0.0))
        phi = wrap_angle(-state.phi if odd else state.phi)
        orientation = -state.orientation if odd else state.orientation
        return {
            "profile": "source-half-turn-bundle-v0",
            "rho": rho,
            "theta": theta,
            "phi": phi,
            "orientation": orientation,
            "wrap_count": state.wrap_count + k,
            "base_non_orientable": False,
            "source_formula_preserved": True,
        }

    def klein_reflection(self, state: TopologicalWrapState) -> dict[str, Any]:
        """Orientation-reversing radial gluing for a genuine Klein profile.

        Odd radial wraps apply ``theta -> pi-theta``, ``phi -> -phi`` and flip
        the orientation flag.  The first map is a reflection of the angular
        circle (with a half-turn offset), so the base quotient is non-orientable.
        """

        rho, k = self._reduce(state.rho)
        odd = abs(k) & 1
        theta = wrap_angle(math.pi - state.theta) if odd else wrap_angle(state.theta)
        phi = wrap_angle(-state.phi if odd else state.phi)
        orientation = -state.orientation if odd else state.orientation
        return {
            "profile": "klein-reflective-radial-gluing-v1",
            "rho": rho,
            "theta": theta,
            "phi": phi,
            "orientation": orientation,
            "wrap_count": state.wrap_count + k,
            "base_non_orientable": True,
            "source_formula_preserved": False,
            "tangent_signs": {"dtheta": -1 if odd else 1, "dphi": -1 if odd else 1},
        }


# ---------------------------------------------------------------------------
# Hinge calculus and missing-shackle constraint release
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HingeState:
    phi: float
    omega: float
    alpha: float

    def reflected(self) -> "HingeState":
        return HingeState(phi=wrap_angle(-self.phi), omega=-self.omega, alpha=-self.alpha)


@dataclass(frozen=True)
class LinearHingeModel:
    inertia: float
    damping: float = 0.0
    stiffness: float = 0.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.inertia) and self.inertia > 0.0):
            raise ValueError("inertia must be positive")
        if not (math.isfinite(self.damping) and self.damping >= 0.0):
            raise ValueError("damping must be non-negative")
        if not (math.isfinite(self.stiffness) and self.stiffness >= 0.0):
            raise ValueError("stiffness must be non-negative")

    def torque(self, state: HingeState) -> float:
        return self.inertia * state.alpha + self.damping * state.omega + self.stiffness * state.phi


def matrix_rank(matrix: Sequence[Sequence[float]], tolerance: float = 1e-12) -> int:
    rows = [list(map(float, row)) for row in matrix]
    if not rows:
        return 0
    cols = len(rows[0])
    if cols == 0:
        return 0
    if any(len(row) != cols for row in rows):
        raise ValueError("matrix rows must have equal length")
    rank = 0
    for col in range(cols):
        pivot = max(range(rank, len(rows)), key=lambda r: abs(rows[r][col]), default=rank)
        if rank >= len(rows) or abs(rows[pivot][col]) <= tolerance:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        scale = rows[rank][col]
        rows[rank] = [value / scale for value in rows[rank]]
        for r in range(len(rows)):
            if r == rank:
                continue
            factor = rows[r][col]
            if abs(factor) > tolerance:
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[rank])]
        rank += 1
        if rank == len(rows):
            break
    return rank


def nullity(matrix: Sequence[Sequence[float]], columns: int | None = None) -> int:
    rows = [tuple(row) for row in matrix]
    if columns is None:
        columns = len(rows[0]) if rows else 0
    return int(columns) - matrix_rank(rows)


def nullspace_basis(matrix: Sequence[Sequence[float]], tolerance: float = 1e-12) -> tuple[tuple[float, ...], ...]:
    rows = [list(map(float, row)) for row in matrix]
    if not rows:
        return ()
    cols = len(rows[0])
    if any(len(row) != cols for row in rows):
        raise ValueError("matrix rows must have equal length")
    r = 0
    pivots: list[int] = []
    for c in range(cols):
        pivot = next((i for i in range(r, len(rows)) if abs(rows[i][c]) > tolerance), None)
        if pivot is None:
            continue
        rows[r], rows[pivot] = rows[pivot], rows[r]
        scale = rows[r][c]
        rows[r] = [value / scale for value in rows[r]]
        for i in range(len(rows)):
            if i != r and abs(rows[i][c]) > tolerance:
                factor = rows[i][c]
                rows[i] = [a - factor * b for a, b in zip(rows[i], rows[r])]
        pivots.append(c)
        r += 1
        if r == len(rows):
            break
    free = [c for c in range(cols) if c not in pivots]
    basis: list[tuple[float, ...]] = []
    for f in free:
        vec = [0.0] * cols
        vec[f] = 1.0
        for row_index, pivot_col in enumerate(pivots):
            vec[pivot_col] = -rows[row_index][f]
        basis.append(tuple(0.0 if abs(x) <= tolerance else x for x in vec))
    return tuple(basis)


@dataclass(frozen=True)
class MissingShackleCertificate:
    original_rank: int
    released_rank: int
    original_nullity: int
    released_nullity: int
    freedom_gain: int
    released_basis: tuple[tuple[float, ...], ...]


def release_constraint_row(matrix: Sequence[Sequence[float]], row_index: int) -> MissingShackleCertificate:
    rows = [tuple(map(float, row)) for row in matrix]
    if not rows:
        raise ValueError("matrix must contain at least one row")
    columns = len(rows[0])
    if any(len(row) != columns for row in rows):
        raise ValueError("matrix rows must have equal length")
    if not 0 <= row_index < len(rows):
        raise IndexError(row_index)
    released = rows[:row_index] + rows[row_index + 1 :]
    rank0 = matrix_rank(rows)
    rank1 = matrix_rank(released)
    null0 = columns - rank0
    null1 = columns - rank1
    return MissingShackleCertificate(
        original_rank=rank0,
        released_rank=rank1,
        original_nullity=null0,
        released_nullity=null1,
        freedom_gain=null1 - null0,
        released_basis=nullspace_basis(released),
    )


def tangent_project_velocity(gradient: Vec3, proposed_velocity: Vec3) -> Vec3:
    """Project velocity into the tangent space of a regular zero surface."""

    n = v_normalize(_v3(gradient))
    v = _v3(proposed_velocity)
    return v_sub(v, v_scale(n, v_dot(v, n)))


# ---------------------------------------------------------------------------
# Bounded binary L-system / motion grammar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MotionSymbol:
    kind: str
    value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True)
class GrammarExpansion:
    depth: int
    symbols: tuple[MotionSymbol, ...]
    grammar_state_word_12: int
    forward_count: int
    max_stack_depth: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "symbol_count": len(self.symbols),
            "forward_count": self.forward_count,
            "max_stack_depth": self.max_stack_depth,
            "grammar_state_word_12": self.grammar_state_word_12,
            "symbols": [symbol.to_dict() for symbol in self.symbols],
        }


@dataclass(frozen=True)
class BoundedBinaryGrammar:
    initial_scale: float
    turn_angle: float
    delta_rho: float
    max_depth: int = 8
    max_symbols: int = 100_000
    max_stack: int = 64

    def __post_init__(self) -> None:
        if not (math.isfinite(self.initial_scale) and self.initial_scale > 0.0):
            raise ValueError("initial_scale must be positive")
        if not math.isfinite(self.turn_angle):
            raise ValueError("turn_angle must be finite")
        if not math.isfinite(self.delta_rho):
            raise ValueError("delta_rho must be finite")
        if self.max_depth < 0 or self.max_symbols <= 0 or self.max_stack <= 0:
            raise ValueError("grammar budgets must be positive")

    def expand(
        self,
        branch_bits: Sequence[int],
        *,
        depth: int,
        rho: float,
        chirality: int = 1,
        chart: LogPolarChart | None = None,
    ) -> GrammarExpansion:
        if depth > self.max_depth:
            raise ValueError("grammar depth budget exceeded")
        if chirality not in {-1, 1}:
            raise ValueError("chirality must be -1 or +1")
        if len(branch_bits) < depth:
            raise ValueError("one branch bit is required per depth")
        if any(bit not in {0, 1} for bit in branch_bits[:depth]):
            raise ValueError("branch bits must be 0 or 1")
        chart = chart or LogPolarChart()
        word: list[MotionSymbol] = [MotionSymbol("F", self.initial_scale)]
        local_jitter = chart.exact_radial_increment(rho, self.delta_rho)
        for level in range(depth):
            bit = branch_bits[level]
            turn = chirality * (1.0 if bit == 0 else -1.0) * self.turn_angle
            out: list[MotionSymbol] = []
            for symbol in word:
                if symbol.kind != "F":
                    out.append(symbol)
                    continue
                scale = float(symbol.value) * 0.5
                # Two bounded branches preserve the source L-system/bifurcation
                # motif while making the exponential growth explicit.
                out.extend(
                    [
                        MotionSymbol("F", scale),
                        MotionSymbol("PUSH"),
                        MotionSymbol("TURN", turn),
                        MotionSymbol("F", scale),
                        MotionSymbol("POP"),
                        MotionSymbol("JITTER", local_jitter),
                    ]
                )
                if len(out) > self.max_symbols:
                    raise ValueError("grammar symbol budget exceeded")
            word = out
        max_stack = _validate_stack(word, self.max_stack)
        payload = repr([(s.kind, None if s.value is None else round(s.value, 15)) for s in word]).encode("utf-8")
        state_word = int.from_bytes(hashlib.sha256(payload).digest()[:2], "big") & 0x0FFF
        return GrammarExpansion(
            depth=depth,
            symbols=tuple(word),
            grammar_state_word_12=state_word,
            forward_count=sum(symbol.kind == "F" for symbol in word),
            max_stack_depth=max_stack,
        )


def _validate_stack(symbols: Sequence[MotionSymbol], max_stack: int) -> int:
    depth = 0
    maximum = 0
    for symbol in symbols:
        if symbol.kind == "PUSH":
            depth += 1
            maximum = max(maximum, depth)
            if depth > max_stack:
                raise ValueError("grammar stack budget exceeded")
        elif symbol.kind == "POP":
            depth -= 1
            if depth < 0:
                raise ValueError("grammar stack underflow")
    if depth != 0:
        raise ValueError("grammar stack not balanced")
    return maximum


def compile_motion_polyline(expansion: GrammarExpansion, origin: Vec2 = (0.0, 0.0), heading: float = 0.0) -> tuple[Vec2, ...]:
    """Compile a bounded grammar word to a 2D apex path (no rendering)."""

    x, y = map(float, origin)
    angle = float(heading)
    stack: list[tuple[float, float, float]] = []
    points: list[Vec2] = [(x, y)]
    for symbol in expansion.symbols:
        if symbol.kind == "F":
            length = float(symbol.value)
            x += length * math.cos(angle)
            y += length * math.sin(angle)
            points.append((x, y))
        elif symbol.kind == "TURN":
            angle = wrap_angle(angle + float(symbol.value))
        elif symbol.kind == "PUSH":
            stack.append((x, y, angle))
        elif symbol.kind == "POP":
            x, y, angle = stack.pop()
            points.append((x, y))
        elif symbol.kind == "JITTER":
            # The jitter token is metadata for the next query/guard.  It does
            # not displace the authoritative path in this reference compiler.
            continue
        else:
            raise ValueError(f"unknown motion symbol: {symbol.kind}")
    return tuple(points)


# ---------------------------------------------------------------------------
# 64-bit quantization and two non-confusable key layouts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantizedCoordinates:
    rho: int
    theta: int
    time: int
    phi: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class KeyLayout64:
    bits_rho: int = 20
    bits_theta: int = 18
    bits_time: int = 14
    bits_phi: int = 12
    rho_min: float = -20.0
    rho_max: float = 0.0

    def __post_init__(self) -> None:
        if self.total_bits != 64:
            raise ValueError("SCLP 3.6.2 key layout must total 64 bits")
        if min(self.bits_rho, self.bits_theta, self.bits_time, self.bits_phi) <= 0:
            raise ValueError("field widths must be positive")
        if not (math.isfinite(self.rho_min) and math.isfinite(self.rho_max) and self.rho_min < self.rho_max):
            raise ValueError("invalid rho range")

    @property
    def total_bits(self) -> int:
        return self.bits_rho + self.bits_theta + self.bits_time + self.bits_phi

    @property
    def capacities(self) -> dict[str, int]:
        return {
            "rho": 1 << self.bits_rho,
            "theta": 1 << self.bits_theta,
            "time": 1 << self.bits_time,
            "phi": 1 << self.bits_phi,
        }

    @property
    def state_capacity(self) -> int:
        return 1 << 64

    def quantize(self, rho: float, theta: float, time_tick: int | float, phi: float) -> QuantizedCoordinates:
        return QuantizedCoordinates(
            rho=_quantize_closed(rho, self.rho_min, self.rho_max, self.bits_rho),
            theta=_quantize_periodic(theta, TAU, self.bits_theta),
            time=int(math.floor(float(time_tick))) % (1 << self.bits_time),
            phi=_quantize_periodic(phi, TAU, self.bits_phi),
        )

    def pack_contiguous(self, q: QuantizedCoordinates) -> int:
        """Pack the source table's contiguous bit ranges [63:44]...[11:0]."""

        self._validate_q(q)
        return (
            (q.rho << (self.bits_theta + self.bits_time + self.bits_phi))
            | (q.theta << (self.bits_time + self.bits_phi))
            | (q.time << self.bits_phi)
            | q.phi
        )

    def unpack_contiguous(self, key: int) -> QuantizedCoordinates:
        _validate_u64(key)
        phi_mask = (1 << self.bits_phi) - 1
        time_mask = (1 << self.bits_time) - 1
        theta_mask = (1 << self.bits_theta) - 1
        phi = key & phi_mask
        time = (key >> self.bits_phi) & time_mask
        theta = (key >> (self.bits_phi + self.bits_time)) & theta_mask
        rho = key >> (self.bits_phi + self.bits_time + self.bits_theta)
        return QuantizedCoordinates(rho=rho, theta=theta, time=time, phi=phi)

    def morton_schedule(self) -> tuple[tuple[str, int], ...]:
        """Return the exact MSB-first round-robin schedule.

        The first round is ``rho19, theta17, time13, phi11``, matching the
        source expression.  After a field exhausts its bits, the remaining
        fields continue.  This schedule is distinct from the contiguous table.
        """

        widths = {
            "rho": self.bits_rho,
            "theta": self.bits_theta,
            "time": self.bits_time,
            "phi": self.bits_phi,
        }
        order = ("rho", "theta", "time", "phi")
        schedule: list[tuple[str, int]] = []
        max_width = max(widths.values())
        for round_index in range(max_width):
            for name in order:
                bit_index = widths[name] - 1 - round_index
                if bit_index >= 0:
                    schedule.append((name, bit_index))
        if len(schedule) != 64:
            raise AssertionError("invalid Morton schedule")
        return tuple(schedule)

    def pack_morton(self, q: QuantizedCoordinates) -> int:
        self._validate_q(q)
        values = q.as_dict()
        key = 0
        for name, bit_index in self.morton_schedule():
            key = (key << 1) | ((values[name] >> bit_index) & 1)
        return key

    def unpack_morton(self, key: int) -> QuantizedCoordinates:
        _validate_u64(key)
        values = {"rho": 0, "theta": 0, "time": 0, "phi": 0}
        schedule = self.morton_schedule()
        for position, (name, bit_index) in enumerate(schedule):
            bit = (key >> (63 - position)) & 1
            values[name] |= bit << bit_index
        return QuantizedCoordinates(**values)

    def append_prefix_bit(self, prefix: int, depth: int, bit: int) -> tuple[int, int]:
        if bit not in {0, 1}:
            raise ValueError("branch bit must be 0 or 1")
        if not 0 <= depth < 64:
            raise ValueError("depth must lie in [0,63]")
        if prefix < 0 or prefix >= (1 << depth):
            raise ValueError("prefix does not fit declared depth")
        return ((prefix << 1) | bit, depth + 1)

    def prefix_integer_bounds(self, prefix: int, depth: int) -> dict[str, tuple[int, int]]:
        if not 0 <= depth <= 64:
            raise ValueError("depth must lie in [0,64]")
        if prefix < 0 or prefix >= (1 << depth if depth else 1):
            raise ValueError("prefix does not fit declared depth")
        widths = {
            "rho": self.bits_rho,
            "theta": self.bits_theta,
            "time": self.bits_time,
            "phi": self.bits_phi,
        }
        known_mask = {name: 0 for name in widths}
        known_value = {name: 0 for name in widths}
        for position, (name, bit_index) in enumerate(self.morton_schedule()[:depth]):
            bit = (prefix >> (depth - 1 - position)) & 1
            known_mask[name] |= 1 << bit_index
            known_value[name] |= bit << bit_index
        out: dict[str, tuple[int, int]] = {}
        for name, width in widths.items():
            full = (1 << width) - 1
            lower = known_value[name]
            upper = known_value[name] | (full ^ known_mask[name])
            out[name] = (lower, upper)
        return out

    def quantization_metrics(self) -> dict[str, Any]:
        return {
            "bits": {
                "rho": self.bits_rho,
                "theta": self.bits_theta,
                "time": self.bits_time,
                "phi": self.bits_phi,
            },
            "capacities": self.capacities,
            "total_states": self.state_capacity,
            "rho_step": (self.rho_max - self.rho_min) / ((1 << self.bits_rho) - 1),
            "theta_step_rad": TAU / (1 << self.bits_theta),
            "phi_step_rad": TAU / (1 << self.bits_phi),
            "time_states": 1 << self.bits_time,
            "keys_per_64_byte_cache_line": 8,
        }

    def _validate_q(self, q: QuantizedCoordinates) -> None:
        limits = {
            "rho": 1 << self.bits_rho,
            "theta": 1 << self.bits_theta,
            "time": 1 << self.bits_time,
            "phi": 1 << self.bits_phi,
        }
        for name, value in q.as_dict().items():
            if not 0 <= value < limits[name]:
                raise ValueError(f"{name} does not fit field width")


def _validate_u64(key: int) -> None:
    if not isinstance(key, int) or not 0 <= key < (1 << 64):
        raise ValueError("key must be an unsigned 64-bit integer")


def _quantize_closed(value: float, lower: float, upper: float, bits: int) -> int:
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    clamped = min(upper, max(lower, value))
    scale = ((1 << bits) - 1) / (upper - lower)
    return int(round((clamped - lower) * scale))


def _quantize_periodic(value: float, period: float, bits: int) -> int:
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    phase = value % period
    return int(math.floor(phase / period * (1 << bits))) % (1 << bits)


# ---------------------------------------------------------------------------
# Logical radix trie and storage/metric audit
# ---------------------------------------------------------------------------


class SparseRadixTrie:
    """Logical 64-level radix-2 trie for one-bit payloads.

    The Python reference uses dictionaries for clarity.  A production succinct
    representation needs topology/presence bits plus rank/select metadata; it
    is not literally zero-overhead.
    """

    def __init__(self, width: int = 64):
        if width <= 0:
            raise ValueError("width must be positive")
        self.width = width
        self._leaves: dict[int, int] = {}

    def insert(self, key: int, payload_bit: int) -> None:
        if payload_bit not in {0, 1}:
            raise ValueError("payload must be one bit")
        if not 0 <= key < (1 << self.width):
            raise ValueError("key out of range")
        self._leaves[key] = payload_bit

    def lookup(self, key: int) -> int | None:
        return self._leaves.get(key)

    def path(self, key: int) -> tuple[int, ...]:
        if not 0 <= key < (1 << self.width):
            raise ValueError("key out of range")
        return tuple((key >> (self.width - 1 - i)) & 1 for i in range(self.width))

    @property
    def leaf_count(self) -> int:
        return len(self._leaves)

    @property
    def logical_node_count(self) -> int:
        prefixes = {()}
        for key in self._leaves:
            path = self.path(key)
            for depth in range(1, self.width + 1):
                prefixes.add(path[:depth])
        return len(prefixes)

    def storage_lower_bound_bits(self) -> dict[str, int]:
        nodes = self.logical_node_count
        leaves = self.leaf_count
        return {
            "topology_presence_min_bits": nodes,
            "leaf_payload_bits": leaves,
            "combined_before_rank_select": nodes + leaves,
            "rank_select_overhead_included": 0,
        }


@dataclass(frozen=True)
class CompressionMetric:
    name: str
    baseline_bits: int
    packed_bits: int
    ratio: float
    semantic_equivalence: bool
    qualification: str


def source_width_metrics() -> tuple[CompressionMetric, ...]:
    """Return the source's bit-width comparisons with explicit qualifications."""

    return (
        CompressionMetric(
            "coordinate-boundary-key",
            192,
            64,
            3.0,
            False,
            "Nominal width ratio: six float32 values versus one quantized key; decode metadata and error differ.",
        ),
        CompressionMetric(
            "sdf-sign-only",
            32,
            1,
            32.0,
            False,
            "A sign bit does not preserve distance magnitude, uncertainty or a zero-state encoding by itself.",
        ),
        CompressionMetric(
            "kinematic-state-word",
            512,
            12,
            512.0 / 12.0,
            False,
            "A 12-bit state selector is not semantically equivalent to an arbitrary 4x4 float matrix.",
        ),
    )


def comparable_compression_ratio(baseline_bytes: int, packed_bytes: int) -> float:
    if baseline_bytes <= 0 or packed_bytes <= 0:
        raise ValueError("byte counts must be positive")
    return baseline_bytes / packed_bytes


# ---------------------------------------------------------------------------
# Integrated deterministic example certificate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SCLP362Certificate:
    profile_id: str
    cone: Mapping[str, Any]
    logpolar: Mapping[str, Any]
    quantized: Mapping[str, Any]
    keys: Mapping[str, Any]
    jitter: Mapping[str, Any]
    time: Mapping[str, Any]
    topology: Mapping[str, Any]
    shackle: Mapping[str, Any]
    grammar: Mapping[str, Any]
    sweep: Mapping[str, Any]
    metrics: Mapping[str, Any]
    handoff: Mapping[str, Any]
    valid: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_reference_sclp362_certificate() -> SCLP362Certificate:
    chart = LogPolarChart()
    layout = KeyLayout64(rho_min=chart.rho_min, rho_max=chart.rho_max)
    cone = FiniteCone(slant_length=2.0, half_angle=math.radians(30.0))
    point = (0.15, 0.0, 0.6)
    residual = cone.signed_distance(point)
    rho, theta, core = chart.encode(point[0], point[1])
    clock = PhaseClock()
    clock_state = clock.state(1135 + 3 * 256 + 17)
    phi = math.radians(20.0)
    q = layout.quantize(rho, theta, clock_state["tick"], phi)
    contiguous = layout.pack_contiguous(q)
    morton = layout.pack_morton(q)
    jitter = OneBitJitter(amplitude=1e-4, guard_margin=1e-3, seed="sclp362-reference")
    jitter_certificate = jitter.certificate(residual, morton, int(clock_state["tick"]))
    twist = RadialTwistBundle(chart.rho_min, chart.rho_max)
    topological = twist.klein_reflection(
        TopologicalWrapState(
            rho=chart.rho_max + 0.25,
            theta=theta,
            phi=phi,
            orientation=1,
        )
    )
    shackle = release_constraint_row(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), 1)
    branch_bits = [jitter.bit(morton, int(clock_state["tick"]) + i) for i in range(4)]
    grammar = BoundedBinaryGrammar(
        initial_scale=1.0,
        turn_angle=math.radians(25.0),
        delta_rho=1e-3,
        max_depth=6,
        max_symbols=20_000,
    ).expand(branch_bits, depth=4, rho=rho, chirality=topological["orientation"], chart=chart)
    sweep = certify_linear_cone_sweep(
        point=(0.5, 0.0, 0.6),
        cone=cone,
        segment=LinearSweepSegment((0.0, 0.0, 0.0), (0.75, 0.0, 0.0)),
        sample_count=65,
        guard_band=1e-3,
    )
    metrics = {
        "quantization": layout.quantization_metrics(),
        "source_width_metrics": [asdict(metric) for metric in source_width_metrics()],
        "morton_schedule_prefix": [f"{name}{bit}" for name, bit in layout.morton_schedule()[:16]],
        "morton_schedule_length": len(layout.morton_schedule()),
    }
    handoff = {
        "sequence": ["support", "compatibility", "guard", "verified_event", "transition", "lineage"],
        "relation_residual": residual,
        "guard_interval": jitter_certificate["interval"],
        "verified": jitter_certificate["safe_under_margin"] and not (jitter_certificate["interval"][0] <= 0.0 <= jitter_certificate["interval"][1]),
        "reason": "jitter interval must not change the declared guard class",
    }
    valid = (
        layout.unpack_contiguous(contiguous) == q
        and layout.unpack_morton(morton) == q
        and jitter_certificate["safe_under_margin"]
        and shackle.freedom_gain == 1
        and grammar.depth == 4
        and len(layout.morton_schedule()) == 64
    )
    return SCLP362Certificate(
        profile_id="sclp362:profile:packed-swept-cone-v1",
        cone={
            "T_slant": cone.slant_length,
            "alpha_half_angle_rad": cone.half_angle,
            "height": cone.height,
            "base_radius": cone.base_radius,
            "query_point": list(point),
            "signed_distance": residual,
            "relation_class": cone.relation_class(point, epsilon=1e-12),
        },
        logpolar={
            "rho": rho,
            "theta": theta,
            "core": core,
            "metric_scale": chart.metric_scale(rho),
            "exact_delta_r_for_delta_rho_1e-3": chart.exact_radial_increment(rho, 1e-3),
        },
        quantized=q.as_dict(),
        keys={
            "contiguous_u64": contiguous,
            "contiguous_hex": f"0x{contiguous:016x}",
            "morton_u64": morton,
            "morton_hex": f"0x{morton:016x}",
            "layouts_are_distinct": contiguous != morton,
        },
        jitter=jitter_certificate,
        time=clock_state,
        topology=topological,
        shackle=asdict(shackle),
        grammar=grammar.to_dict(),
        sweep=asdict(sweep),
        metrics=metrics,
        handoff=handoff,
        valid=valid,
    )
