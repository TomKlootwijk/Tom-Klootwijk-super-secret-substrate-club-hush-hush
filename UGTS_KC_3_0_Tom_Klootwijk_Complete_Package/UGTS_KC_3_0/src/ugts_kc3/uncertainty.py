"""Bounded uncertainty, deterministic reduction and replay helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from math import isfinite, nextafter, sqrt, inf
import random
from typing import Callable, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

from .math3 import matrix_mul, transpose


def _down(x: float) -> float:
    return nextafter(float(x), -inf)


def _up(x: float) -> float:
    return nextafter(float(x), inf)


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float

    def __post_init__(self) -> None:
        if self.lo > self.hi:
            raise ValueError("interval lo must not exceed hi")
        if not (isfinite(self.lo) and isfinite(self.hi)):
            # Infinite bounds are deliberately not part of the compact exchange
            # schema.  Keep the reference implementation finite and auditable.
            raise ValueError("interval bounds must be finite")

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def midpoint(self) -> float:
        return 0.5 * (self.lo + self.hi)

    def contains(self, x: float) -> bool:
        return self.lo <= x <= self.hi

    def contains_zero(self) -> bool:
        return self.lo <= 0.0 <= self.hi

    def intersect(self, other: "Interval") -> "Interval | None":
        lo, hi = max(self.lo, other.lo), min(self.hi, other.hi)
        return None if lo > hi else Interval(lo, hi)

    def subset_of(self, other: "Interval", strict: bool = False) -> bool:
        if strict:
            return other.lo < self.lo and self.hi < other.hi
        return other.lo <= self.lo and self.hi <= other.hi

    def __add__(self, other: float | "Interval") -> "Interval":
        o = other if isinstance(other, Interval) else Interval(float(other), float(other))
        return Interval(_down(self.lo + o.lo), _up(self.hi + o.hi))

    __radd__ = __add__

    def __neg__(self) -> "Interval":
        return Interval(-self.hi, -self.lo)

    def __sub__(self, other: float | "Interval") -> "Interval":
        o = other if isinstance(other, Interval) else Interval(float(other), float(other))
        return self + (-o)

    def __rsub__(self, other: float | "Interval") -> "Interval":
        o = other if isinstance(other, Interval) else Interval(float(other), float(other))
        return o - self

    def __mul__(self, other: float | "Interval") -> "Interval":
        o = other if isinstance(other, Interval) else Interval(float(other), float(other))
        products = [self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi]
        return Interval(_down(min(products)), _up(max(products)))

    __rmul__ = __mul__

    def reciprocal(self) -> "Interval":
        if self.contains_zero():
            raise ZeroDivisionError("interval contains zero")
        values = [1.0 / self.lo, 1.0 / self.hi]
        return Interval(_down(min(values)), _up(max(values)))

    def __truediv__(self, other: float | "Interval") -> "Interval":
        o = other if isinstance(other, Interval) else Interval(float(other), float(other))
        return self * o.reciprocal()

    def square(self) -> "Interval":
        if self.contains_zero():
            return Interval(0.0, _up(max(self.lo * self.lo, self.hi * self.hi)))
        values = [self.lo * self.lo, self.hi * self.hi]
        return Interval(_down(min(values)), _up(max(values)))

    def sqrt(self) -> "Interval":
        if self.lo < 0.0:
            raise ValueError("sqrt interval must be nonnegative")
        return Interval(_down(sqrt(self.lo)), _up(sqrt(self.hi)))


def interval_norm_bounds(components: Sequence[Interval]) -> Interval:
    if not components:
        return Interval(0.0, 0.0)
    lower_sq = 0.0
    upper_sq = 0.0
    for c in components:
        if c.contains_zero():
            min_abs = 0.0
        else:
            min_abs = min(abs(c.lo), abs(c.hi))
        max_abs = max(abs(c.lo), abs(c.hi))
        lower_sq += min_abs * min_abs
        upper_sq += max_abs * max_abs
    return Interval(_down(sqrt(lower_sq)), _up(sqrt(upper_sq)))


@dataclass(frozen=True)
class AffineForm:
    center: float
    coefficients: Mapping[str, float] = field(default_factory=dict)
    remainder: float = 0.0

    def __post_init__(self) -> None:
        if self.remainder < 0.0:
            raise ValueError("remainder must be nonnegative")

    @staticmethod
    def from_interval(interval: Interval, symbol: str = "e0") -> "AffineForm":
        return AffineForm(interval.midpoint, {symbol: interval.width / 2.0}, 0.0)

    def interval(self) -> Interval:
        radius = sum(abs(v) for v in self.coefficients.values()) + self.remainder
        return Interval(_down(self.center - radius), _up(self.center + radius))

    def __add__(self, other: float | "AffineForm") -> "AffineForm":
        if not isinstance(other, AffineForm):
            return AffineForm(self.center + float(other), dict(self.coefficients), self.remainder)
        keys = set(self.coefficients) | set(other.coefficients)
        return AffineForm(
            self.center + other.center,
            {k: self.coefficients.get(k, 0.0) + other.coefficients.get(k, 0.0) for k in keys},
            self.remainder + other.remainder,
        )

    __radd__ = __add__

    def scale(self, scalar: float) -> "AffineForm":
        return AffineForm(
            self.center * scalar,
            {k: v * scalar for k, v in self.coefficients.items()},
            abs(scalar) * self.remainder,
        )

    def multiply(self, other: "AffineForm", new_symbol: str = "e_mul") -> "AffineForm":
        # First-order affine product plus a conservative nonlinear remainder.
        coeffs: Dict[str, float] = {}
        for k in set(self.coefficients) | set(other.coefficients):
            coeffs[k] = self.center * other.coefficients.get(k, 0.0) + other.center * self.coefficients.get(k, 0.0)
        ra = self.interval().width / 2.0
        rb = other.interval().width / 2.0
        nonlinear = ra * rb + abs(self.center) * other.remainder + abs(other.center) * self.remainder
        coeffs[new_symbol] = coeffs.get(new_symbol, 0.0) + nonlinear
        return AffineForm(self.center * other.center, coeffs, self.remainder * other.remainder)


def propagate_covariance(F: Sequence[Sequence[float]], P: Sequence[Sequence[float]], Q: Sequence[Sequence[float]]) -> List[List[float]]:
    if not F or len(F) != len(F[0]) or len(P) != len(F) or len(Q) != len(F):
        raise ValueError("F, P and Q must be same-size square matrices")
    n = len(F)
    if any(len(row) != n for row in F) or any(len(row) != n for row in P) or any(len(row) != n for row in Q):
        raise ValueError("matrices must be square")
    fpft = matrix_mul(matrix_mul(F, P), transpose(F))
    return [[fpft[i][j] + Q[i][j] for j in range(n)] for i in range(n)]


def unscented_transform_scalar(mean: float, variance: float, function: Callable[[float], float],
                               alpha: float = 0.5, beta: float = 2.0, kappa: float = 2.0) -> Tuple[float, float]:
    if variance < 0.0 or alpha <= 0.0:
        raise ValueError("variance must be nonnegative and alpha positive")
    n = 1.0
    lam = alpha * alpha * (n + kappa) - n
    c = n + lam
    if c <= 0.0:
        raise ValueError("unscented parameters produce nonpositive spread")
    spread = sqrt(c * variance)
    points = [mean, mean + spread, mean - spread]
    wm = [lam / c, 1.0 / (2.0 * c), 1.0 / (2.0 * c)]
    wc = [wm[0] + (1.0 - alpha * alpha + beta), wm[1], wm[2]]
    values = [function(x) for x in points]
    out_mean = sum(w * y for w, y in zip(wm, values))
    out_var = sum(w * (y - out_mean) ** 2 for w, y in zip(wc, values))
    return out_mean, max(0.0, out_var)


def _stable_seed(parts: Sequence[object]) -> int:
    payload = json.dumps(list(parts), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return int.from_bytes(sha256(payload).digest()[:8], "big")


def deterministic_samples(parts: Sequence[object], count: int, distribution: str = "uniform") -> List[float]:
    if count < 0:
        raise ValueError("count must be nonnegative")
    rng = random.Random(_stable_seed(parts))
    if distribution == "uniform":
        return [rng.random() for _ in range(count)]
    if distribution == "normal":
        return [rng.gauss(0.0, 1.0) for _ in range(count)]
    raise ValueError("distribution must be 'uniform' or 'normal'")


@dataclass(frozen=True)
class TolerancePolicy:
    absolute: float = 1e-9
    relative: float = 1e-9
    time: float = 1e-9
    guard: float = 1e-8
    topology: float = 1e-8

    def __post_init__(self) -> None:
        if min(self.absolute, self.relative, self.time, self.guard, self.topology) < 0.0:
            raise ValueError("tolerances must be nonnegative")

    def close(self, a: float, b: float) -> bool:
        return abs(a - b) <= max(self.absolute, self.relative * max(abs(a), abs(b)))


def deterministic_pairwise_sum(values: Iterable[float]) -> float:
    layer = [float(v) for v in values]
    if not layer:
        return 0.0
    while len(layer) > 1:
        next_layer = []
        for i in range(0, len(layer) - 1, 2):
            next_layer.append(layer[i] + layer[i + 1])
        if len(layer) % 2:
            next_layer.append(layer[-1])
        layer = next_layer
    return layer[0]


def _assert_finite_json(value: object) -> None:
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("nonfinite float in canonical JSON")
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError("canonical JSON object keys must be strings")
            _assert_finite_json(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _assert_finite_json(v)


def canonical_json_bytes(value: object) -> bytes:
    _assert_finite_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_json_hash(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def merkle_event_chain(events: Iterable[object], initial_hash: str = "0" * 64) -> List[str]:
    if len(initial_hash) != 64:
        raise ValueError("initial_hash must be a 64-character hex digest")
    head = initial_hash
    chain = []
    for event in events:
        head = sha256(bytes.fromhex(head) + canonical_json_bytes(event)).hexdigest()
        chain.append(head)
    return chain


def make_checkpoint(state: object, schema_hash: str, event_chain_head: str, sequence: int) -> Dict[str, object]:
    if sequence < 0 or len(schema_hash) != 64 or len(event_chain_head) != 64:
        raise ValueError("invalid checkpoint metadata")
    checkpoint = {
        "sequence": sequence,
        "schema_hash": schema_hash,
        "event_chain_head": event_chain_head,
        "state": state,
    }
    checkpoint["checkpoint_hash"] = canonical_json_hash(checkpoint)
    return checkpoint


@dataclass
class ErrorBudget:
    components: MutableMapping[str, float] = field(default_factory=dict)

    def add(self, name: str, bound: float) -> None:
        if not name or bound < 0.0 or not isfinite(bound):
            raise ValueError("name and finite nonnegative bound required")
        self.components[name] = float(bound)

    def worst_case(self) -> float:
        return sum(self.components.values())

    def root_sum_square(self) -> float:
        return sqrt(sum(v * v for v in self.components.values()))

    def within(self, limit: float, mode: str = "worst_case") -> bool:
        if limit < 0.0:
            raise ValueError("limit must be nonnegative")
        if mode == "worst_case":
            return self.worst_case() <= limit
        if mode == "rss":
            return self.root_sum_square() <= limit
        raise ValueError("mode must be 'worst_case' or 'rss'")
