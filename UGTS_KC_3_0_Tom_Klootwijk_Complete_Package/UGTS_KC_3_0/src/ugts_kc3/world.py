"""Minimal query-first state/event world preserving the UGTS canonical sequence."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

from .events import EventInterval
from .kinematics import JetState
from .math3 import dot, norm, normalize, sub
from .uncertainty import canonical_json_hash


@dataclass(frozen=True)
class StateRecord:
    id: str
    jet: JetState
    phase: float = 0.0
    sheet: int = 0
    orientation: int = 1
    branch: str = "A"
    lineage: Tuple[str, ...] = tuple()
    uncertainty: float = 0.0
    tags: Tuple[str, ...] = tuple()

    def at(self, time: float) -> "StateRecord":
        return replace(self, jet=self.jet.taylor(time - self.jet.time))


@dataclass(frozen=True)
class RadialAngularSupport:
    origin: Tuple[float, ...]
    radius: float
    axis: Tuple[float, ...] | None = None
    cone_cos: float = -1.0

    def admits(self, position: Sequence[float]) -> bool:
        if len(position) != len(self.origin) or self.radius < 0.0:
            return False
        delta = sub(position, self.origin)
        r = norm(delta)
        if r > self.radius:
            return False
        if self.axis is None or r <= 1e-15:
            return True
        if len(self.axis) != len(position):
            return False
        return dot(tuple(x / r for x in delta), normalize(self.axis)) >= self.cone_cos


@dataclass(frozen=True)
class CompatibilityRule:
    allowed_sheets: Tuple[int, ...] | None = None
    orientation: int | None = None
    phase_center: float | None = None
    phase_tolerance: float = 0.0
    required_tags: Tuple[str, ...] = tuple()

    def check(self, state: StateRecord) -> Tuple[bool, Tuple[str, ...]]:
        reasons = []
        if self.allowed_sheets is not None and state.sheet not in self.allowed_sheets:
            reasons.append("sheet_mismatch")
        if self.orientation is not None and state.orientation != self.orientation:
            reasons.append("orientation_mismatch")
        if self.phase_center is not None and abs(state.phase - self.phase_center) > self.phase_tolerance:
            reasons.append("phase_mismatch")
        missing = sorted(set(self.required_tags) - set(state.tags))
        if missing:
            reasons.append("missing_tags:" + ",".join(missing))
        return not reasons, tuple(reasons)


@dataclass(frozen=True)
class Relation:
    id: str
    guard: Callable[[StateRecord], float]
    support: RadialAngularSupport
    compatibility: CompatibilityRule
    patch: Mapping[str, object]
    priority: int = 0


@dataclass(frozen=True)
class EventRecord:
    entity_id: str
    relation_id: str
    time: EventInterval
    pre_hash: str
    post_hash: str
    reasons: Tuple[str, ...]
    lineage: Tuple[str, ...]


class World:
    def __init__(self, states: Iterable[StateRecord], relations: Iterable[Relation]):
        self.states: Dict[str, StateRecord] = {s.id: s for s in states}
        self.relations = sorted(list(relations), key=lambda r: (r.priority, r.id))
        self.event_log: List[EventRecord] = []

    def state_at(self, entity_id: str, time: float) -> StateRecord:
        return self.states[entity_id].at(time)

    def can_couple(self, a: str, b: str, time: float, max_distance: float = 1e-9,
                   require_same_sheet: bool = True, require_same_orientation: bool = True,
                   phase_tolerance: float = 1e-6) -> Tuple[bool, Tuple[str, ...]]:
        sa, sb = self.state_at(a, time), self.state_at(b, time)
        reasons = []
        if norm(sub(sa.jet.position, sb.jet.position)) > max_distance:
            reasons.append("position_mismatch")
        if require_same_sheet and sa.sheet != sb.sheet:
            reasons.append("sheet_mismatch")
        if require_same_orientation and sa.orientation != sb.orientation:
            reasons.append("orientation_mismatch")
        if abs(sa.phase - sb.phase) > phase_tolerance:
            reasons.append("phase_mismatch")
        return not reasons, tuple(reasons)

    def next_event(self, entity_id: str, t0: float, t1: float, samples: int = 128,
                   tolerance: float = 1e-10) -> Tuple[Relation, EventInterval, Tuple[str, ...]] | None:
        if t1 <= t0 or samples < 2:
            raise ValueError("require t1>t0 and samples>=2")
        candidates = []
        for relation in self.relations:
            prev_t = t0
            prev_state = self.state_at(entity_id, prev_t)
            prev_g = relation.guard(prev_state)
            for i in range(1, samples + 1):
                cur_t = t0 + (t1 - t0) * i / samples
                cur_state = self.state_at(entity_id, cur_t)
                cur_g = relation.guard(cur_state)
                if prev_g == 0.0 or cur_g == 0.0 or prev_g * cur_g < 0.0:
                    lo, hi = prev_t, cur_t
                    glo = prev_g
                    for _ in range(80):
                        mid = 0.5 * (lo + hi)
                        gmid = relation.guard(self.state_at(entity_id, mid))
                        if hi - lo <= tolerance:
                            break
                        if glo == 0.0 or glo * gmid <= 0.0:
                            hi = mid
                        else:
                            lo = mid; glo = gmid
                    event_time = 0.5 * (lo + hi)
                    state = self.state_at(entity_id, event_time)
                    if not relation.support.admits(state.jet.position):
                        break
                    compatible, reasons = relation.compatibility.check(state)
                    if compatible:
                        candidates.append((event_time, relation, EventInterval(lo, hi, abs(relation.guard(state)), "indeterminate", "enclosed"), reasons))
                    break
                prev_t, prev_g = cur_t, cur_g
        if not candidates:
            return None
        _, relation, interval, reasons = min(candidates, key=lambda x: (x[0], x[1].priority, x[1].id))
        return relation, interval, reasons

    def process_next_event(self, entity_id: str, t0: float, t1: float) -> EventRecord | None:
        candidate = self.next_event(entity_id, t0, t1)
        if candidate is None:
            return None
        relation, interval, reasons = candidate
        pre = self.state_at(entity_id, interval.midpoint)
        values = {
            "phase": pre.phase,
            "sheet": pre.sheet,
            "orientation": pre.orientation,
            "branch": pre.branch,
            "uncertainty": pre.uncertainty,
        }
        values.update(relation.patch)
        lineage = pre.lineage + (relation.id,)
        post = replace(
            pre,
            phase=float(values["phase"]),
            sheet=int(values["sheet"]),
            orientation=int(values["orientation"]),
            branch=str(values["branch"]),
            uncertainty=float(values["uncertainty"]),
            lineage=lineage,
        )
        self.states[entity_id] = post
        pre_payload = {"id": pre.id, "time": pre.jet.time, "position": pre.jet.position, "phase": pre.phase, "sheet": pre.sheet, "orientation": pre.orientation, "branch": pre.branch, "lineage": pre.lineage}
        post_payload = {"id": post.id, "time": post.jet.time, "position": post.jet.position, "phase": post.phase, "sheet": post.sheet, "orientation": post.orientation, "branch": post.branch, "lineage": post.lineage}
        record = EventRecord(entity_id, relation.id, interval, canonical_json_hash(pre_payload), canonical_json_hash(post_payload), reasons, lineage)
        self.event_log.append(record)
        return record
