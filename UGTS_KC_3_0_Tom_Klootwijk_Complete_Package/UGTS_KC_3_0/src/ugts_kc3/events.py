"""Hybrid event clustering, certification and deterministic transition batching."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

from .uncertainty import Interval, canonical_json_hash


@dataclass(frozen=True)
class EventInterval:
    t_lo: float
    t_hi: float
    residual: float = 0.0
    direction: str = "indeterminate"
    status: str = "enclosed"

    def __post_init__(self) -> None:
        if self.t_lo > self.t_hi or not all(isfinite(v) for v in (self.t_lo, self.t_hi, self.residual)):
            raise ValueError("invalid event interval")

    @property
    def midpoint(self) -> float:
        return 0.5 * (self.t_lo + self.t_hi)

    @property
    def width(self) -> float:
        return self.t_hi - self.t_lo


def crossing_direction(g_before: float, g_after: float, tolerance: float = 1e-12) -> str:
    if tolerance < 0.0:
        raise ValueError("tolerance must be nonnegative")
    b = 0.0 if abs(g_before) <= tolerance else g_before
    a = 0.0 if abs(g_after) <= tolerance else g_after
    if b < 0.0 and a >= 0.0:
        return "rising"
    if b > 0.0 and a <= 0.0:
        return "falling"
    if b == 0.0 and a == 0.0:
        return "neutral"
    if b == 0.0:
        return "departing_positive" if a > 0.0 else "departing_negative"
    if a == 0.0:
        return "arriving_from_negative" if b < 0.0 else "arriving_from_positive"
    return "none"


def classify_tangency(value: float, first_derivative: float, second_derivative: float,
                       value_tolerance: float = 1e-9, derivative_tolerance: float = 1e-8) -> str:
    if abs(value) > value_tolerance:
        return "off_guard"
    if abs(first_derivative) > derivative_tolerance:
        return "crossing"
    if abs(second_derivative) > derivative_tolerance:
        return "touch"
    if abs(value) <= value_tolerance and abs(first_derivative) <= derivative_tolerance and abs(second_derivative) <= derivative_tolerance:
        return "coincident_or_high_order"
    return "unresolved"


def grazing_marker(value: float, normal_velocity: float, normal_acceleration: float,
                   value_tolerance: float = 1e-9, velocity_tolerance: float = 1e-8) -> bool:
    return abs(value) <= value_tolerance and abs(normal_velocity) <= velocity_tolerance and normal_acceleration != 0.0


def group_simultaneous_events(events: Sequence[Mapping[str, Any]], tolerance: float = 1e-9,
                              time_key: str = "time") -> List[List[Mapping[str, Any]]]:
    if tolerance < 0.0:
        raise ValueError("tolerance must be nonnegative")
    ordered = sorted(events, key=lambda e: (float(e[time_key]), str(e.get("id", ""))))
    groups: List[List[Mapping[str, Any]]] = []
    for event in ordered:
        if not groups or abs(float(event[time_key]) - float(groups[-1][0][time_key])) > tolerance:
            groups.append([event])
        else:
            groups[-1].append(event)
    return groups


def topological_event_order(event_ids: Sequence[str], precedence: Sequence[Tuple[str, str]]) -> List[str]:
    nodes = list(dict.fromkeys(event_ids))
    incoming: Dict[str, set[str]] = {n: set() for n in nodes}
    outgoing: Dict[str, set[str]] = {n: set() for n in nodes}
    for before, after in precedence:
        if before not in incoming or after not in incoming:
            raise ValueError("precedence references unknown event")
        outgoing[before].add(after)
        incoming[after].add(before)
    ready = sorted(n for n in nodes if not incoming[n])
    result: List[str] = []
    while ready:
        node = ready.pop(0)
        result.append(node)
        for other in sorted(outgoing[node]):
            incoming[other].remove(node)
            if not incoming[other]:
                ready.append(other)
                ready.sort()
    if len(result) != len(nodes):
        raise ValueError("event priority graph contains a cycle")
    return result


def event_tie_break_key(event: Mapping[str, Any], time_quantum: float = 1e-9) -> Tuple[int, int, str, str]:
    if time_quantum <= 0.0:
        raise ValueError("time_quantum must be positive")
    bucket = int(round(float(event.get("time", 0.0)) / time_quantum))
    priority = int(event.get("priority", 0))
    relation_id = str(event.get("relation_id", event.get("id", "")))
    lineage_hash = str(event.get("lineage_hash", ""))
    return (bucket, priority, relation_id, lineage_hash)


def detect_zeno(times: Sequence[float], ratio_threshold: float = 0.8, min_intervals: int = 4) -> Tuple[bool, float | None]:
    if ratio_threshold <= 0.0 or ratio_threshold >= 1.0 or min_intervals < 3:
        raise ValueError("invalid Zeno parameters")
    if len(times) < min_intervals + 1:
        return False, None
    intervals = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    if any(dt <= 0.0 for dt in intervals):
        raise ValueError("times must be strictly increasing")
    recent = intervals[-min_intervals:]
    ratios = [recent[i + 1] / recent[i] for i in range(len(recent) - 1)]
    if all(r <= ratio_threshold for r in ratios):
        r = sum(ratios) / len(ratios)
        horizon = times[-1] + recent[-1] * r / max(1e-15, 1.0 - r)
        return True, horizon
    return False, None


@dataclass
class DwellHysteresis:
    enter_threshold: float
    exit_threshold: float
    dwell_time: float
    active: bool = False
    _candidate_since: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.exit_threshold > self.enter_threshold or self.dwell_time < 0.0:
            raise ValueError("require exit_threshold <= enter_threshold and dwell_time>=0")

    def update(self, value: float, time: float) -> bool:
        if self.active:
            if value <= self.exit_threshold:
                self.active = False
                self._candidate_since = None
            return self.active
        if value >= self.enter_threshold:
            if self._candidate_since is None:
                self._candidate_since = time
            if time - self._candidate_since >= self.dwell_time:
                self.active = True
                self._candidate_since = None
        else:
            self._candidate_since = None
        return self.active


def lipschitz_excludes_root(value_at_center: float, half_width: float, lipschitz_constant: float) -> bool:
    if half_width < 0.0 or lipschitz_constant < 0.0:
        raise ValueError("half_width and Lipschitz constant must be nonnegative")
    return abs(value_at_center) > lipschitz_constant * half_width


def interval_newton(function: Callable[[float], float], derivative_interval: Callable[[Interval], Interval],
                    x: Interval, max_iterations: int = 12, tolerance: float = 1e-12) -> Tuple[Interval | None, str, int]:
    if max_iterations < 1 or tolerance <= 0.0:
        raise ValueError("invalid interval-Newton parameters")
    current = x
    for iteration in range(1, max_iterations + 1):
        d = derivative_interval(current)
        if d.contains_zero():
            return current, "unresolved_derivative_contains_zero", iteration
        m = current.midpoint
        fm = function(m)
        newton = Interval(m, m) - Interval(fm, fm) / d
        contracted = current.intersect(newton)
        if contracted is None:
            return None, "no_root", iteration
        if contracted.width <= tolerance:
            return contracted, "unique_root", iteration
        if contracted.subset_of(current, strict=True):
            current = contracted
        else:
            return current, "unresolved_no_contraction", iteration
    return current, "max_iterations", max_iterations


def _poly_trim(coeffs: Sequence[float], eps: float = 1e-15) -> List[float]:
    out = [float(c) for c in coeffs]
    while len(out) > 1 and abs(out[0]) <= eps:
        out.pop(0)
    return out


def _poly_derivative(coeffs: Sequence[float]) -> List[float]:
    n = len(coeffs) - 1
    return [coeffs[i] * (n - i) for i in range(n)] or [0.0]


def _poly_eval(coeffs: Sequence[float], x: float) -> float:
    y = 0.0
    for c in coeffs:
        y = y * x + c
    return y


def _poly_div_remainder(a: Sequence[float], b: Sequence[float], eps: float = 1e-14) -> List[float]:
    dividend = _poly_trim(a, eps)
    divisor = _poly_trim(b, eps)
    if len(divisor) == 1 and abs(divisor[0]) <= eps:
        raise ZeroDivisionError("zero polynomial divisor")
    if len(dividend) < len(divisor):
        return dividend
    work = dividend[:]
    while len(work) >= len(divisor) and not (len(work) == 1 and abs(work[0]) <= eps):
        factor = work[0] / divisor[0]
        for i in range(len(divisor)):
            work[i] -= factor * divisor[i]
        work = _poly_trim(work, eps)
        if len(work) < len(divisor):
            break
    return _poly_trim(work, eps)


def sturm_sequence(coefficients: Sequence[float]) -> List[List[float]]:
    p0 = _poly_trim(coefficients)
    if len(p0) < 2:
        return [p0]
    p1 = _poly_trim(_poly_derivative(p0))
    sequence = [p0, p1]
    while not (len(sequence[-1]) == 1 and abs(sequence[-1][0]) <= 1e-14):
        rem = _poly_div_remainder(sequence[-2], sequence[-1])
        if len(rem) == 1 and abs(rem[0]) <= 1e-14:
            break
        sequence.append([-c for c in rem])
    return sequence


def _sign_variations(sequence: Sequence[Sequence[float]], x: float, eps: float = 1e-12) -> int:
    signs = []
    for p in sequence:
        v = _poly_eval(p, x)
        if abs(v) <= eps:
            continue
        signs.append(1 if v > 0.0 else -1)
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


def sturm_root_count(coefficients: Sequence[float], a: float, b: float) -> int:
    if a >= b:
        raise ValueError("require a<b")
    seq = sturm_sequence(coefficients)
    return _sign_variations(seq, a) - _sign_variations(seq, b)


def apply_atomic_transition_batch(state: Mapping[str, Any], transitions: Sequence[Mapping[str, Any]],
                                  invariant: Callable[[Mapping[str, Any]], bool] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    snapshot = dict(state)
    ordered = sorted(transitions, key=event_tie_break_key)
    result = dict(snapshot)
    applied = []
    for transition in ordered:
        patch = transition.get("patch", {})
        if not isinstance(patch, Mapping):
            raise ValueError("transition patch must be a mapping")
        for key, value in patch.items():
            result[str(key)] = value
        applied.append(str(transition.get("id", transition.get("relation_id", ""))))
    ok = invariant(result) if invariant is not None else True
    if not ok:
        return snapshot, {
            "committed": False,
            "applied": applied,
            "pre_hash": canonical_json_hash(snapshot),
            "post_hash": canonical_json_hash(snapshot),
            "reason": "invariant_failed",
        }
    return result, {
        "committed": True,
        "applied": applied,
        "pre_hash": canonical_json_hash(snapshot),
        "post_hash": canonical_json_hash(result),
        "reason": "ok",
    }


@dataclass(frozen=True)
class HybridTransition:
    id: str
    source_mode: str
    target_mode: str
    guard: Callable[[Mapping[str, Any]], bool]
    reset: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    priority: int = 0


@dataclass
class HybridAutomaton:
    modes: Sequence[str]
    transitions: Sequence[HybridTransition]

    def step(self, mode: str, state: Mapping[str, Any]) -> Tuple[str, Dict[str, Any], str | None]:
        if mode not in self.modes:
            raise ValueError("unknown mode")
        candidates = [t for t in self.transitions if t.source_mode == mode and t.guard(state)]
        if not candidates:
            return mode, dict(state), None
        chosen = sorted(candidates, key=lambda t: (t.priority, t.id))[0]
        return chosen.target_mode, dict(chosen.reset(state)), chosen.id
