"""Fixed-step game runtime bridge with deterministic event proposal and commit semantics."""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import json
from typing import Any, Callable, Iterable

from .scene import Scene


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class EventProposal:
    proposal_id: str
    event_time: float
    event_type: str
    entity_id: str
    payload: dict[str, Any]
    source: str = "cpu"
    priority: int = 0
    confidence: float = 1.0
    support_ok: bool = True
    compatibility_ok: bool = True
    guard_status: str = "crossing"
    numeric_error: float = 0.0
    event_margin: float = 1.0e-6
    lineage_label: str = ""

    def verified(self, confidence_floor: float = 0.5, accepted_statuses=("crossing", "touch", "tangency")) -> tuple[bool, str]:
        if not self.support_ok:
            return False, "outside_support"
        if not self.compatibility_ok:
            return False, "incompatible"
        if self.guard_status not in accepted_statuses:
            return False, f"guard_{self.guard_status}"
        if self.confidence < confidence_floor:
            return False, "confidence_below_floor"
        if self.numeric_error > self.event_margin:
            return False, "numeric_error_exceeds_margin"
        return True, "verified"


@dataclass(frozen=True)
class RuntimeEvent:
    sequence: int
    event_time: float
    event_type: str
    entity_id: str
    payload: dict[str, Any]
    source: str
    priority: int
    confidence: float
    lineage: tuple[str, ...]
    pre_state_hash: str
    post_state_hash: str
    runtime_tick: int
    runtime_time: float
    status: str = "committed"
    reason: str = "verified"


@dataclass(frozen=True)
class RejectedProposal:
    proposal_id: str
    event_time: float
    entity_id: str
    reason: str


@dataclass
class RuntimeMetrics:
    proposed: int = 0
    verified: int = 0
    committed: int = 0
    rejected: int = 0
    conflicts: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)

    def count_reason(self, reason: str):
        self.reason_counts[reason] = self.reason_counts.get(reason, 0) + 1


class KCRuntime:
    def __init__(self, scene: Scene, fixed_dt: float = 1.0 / 60.0, confidence_floor: float = 0.5):
        if fixed_dt <= 0:
            raise ValueError("fixed_dt must be positive")
        self.scene = scene
        self.fixed_dt = fixed_dt
        self.confidence_floor = confidence_floor
        self.tick = 0
        self.time = 0.0
        self.sequence = 0
        self.events: list[RuntimeEvent] = []
        self.rejected: list[RejectedProposal] = []
        self.metrics = RuntimeMetrics()
        self.systems: list[Callable[["KCRuntime", float, float], Iterable[EventProposal]]] = []

    def add_system(self, system: Callable[["KCRuntime", float, float], Iterable[EventProposal]]) -> None:
        self.systems.append(system)

    def state_hash(self) -> str:
        payload = {
            "scene": self.scene.to_dict(include_geometry=True),
            "tick": self.tick,
            "time": round(self.time, 12),
            "sequence": self.sequence,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()

    @staticmethod
    def _conflict_key(proposal: EventProposal):
        field = proposal.payload.get("field") or proposal.event_type
        return round(proposal.event_time, 12), proposal.entity_id, field

    def commit_proposals(self, proposals: Iterable[EventProposal]) -> tuple[RuntimeEvent, ...]:
        proposals = list(proposals)
        self.metrics.proposed += len(proposals)
        verified: list[EventProposal] = []
        for p in proposals:
            ok, reason = p.verified(self.confidence_floor)
            if not ok:
                self.metrics.rejected += 1
                self.metrics.count_reason(reason)
                self.rejected.append(RejectedProposal(p.proposal_id, p.event_time, p.entity_id, reason))
            else:
                self.metrics.verified += 1
                verified.append(p)

        ordered = sorted(verified, key=lambda p: (round(p.event_time, 12), -p.priority, p.source, p.proposal_id))
        winners: list[EventProposal] = []
        occupied: dict[tuple, EventProposal] = {}
        for proposal in ordered:
            key = self._conflict_key(proposal)
            if key in occupied and occupied[key].payload != proposal.payload:
                self.metrics.conflicts += 1
                reason = f"conflict_with:{occupied[key].proposal_id}"
                self.metrics.rejected += 1
                self.metrics.count_reason("conflict")
                self.rejected.append(RejectedProposal(proposal.proposal_id, proposal.event_time, proposal.entity_id, reason))
                continue
            occupied[key] = proposal
            winners.append(proposal)

        committed: list[RuntimeEvent] = []
        for proposal in winners:
            pre_hash = self.state_hash()
            self._apply(proposal)
            self.sequence += 1
            lineage = tuple(self.scene.nodes[proposal.entity_id].lineage) if proposal.entity_id in self.scene.nodes else ()
            if proposal.lineage_label:
                lineage = lineage + (proposal.lineage_label,)
                if proposal.entity_id in self.scene.nodes:
                    self.scene.update_node(proposal.entity_id, lineage=lineage)
            post_hash = self.state_hash()
            event = RuntimeEvent(
                self.sequence,
                proposal.event_time,
                proposal.event_type,
                proposal.entity_id,
                copy.deepcopy(proposal.payload),
                proposal.source,
                proposal.priority,
                proposal.confidence,
                lineage,
                pre_hash,
                post_hash,
                self.tick,
                self.time,
            )
            self.events.append(event)
            committed.append(event)
            self.metrics.committed += 1
        return tuple(committed)

    def _apply(self, proposal: EventProposal) -> None:
        if proposal.entity_id not in self.scene.nodes and proposal.event_type not in {"set_variant", "custom"}:
            raise KeyError(f"unknown runtime entity {proposal.entity_id}")
        p = proposal.payload
        if proposal.event_type == "set_transform":
            transform = tuple(tuple(float(v) for v in row) for row in p["transform"])
            self.scene.update_node(proposal.entity_id, local_transform=transform)
        elif proposal.event_type == "set_visibility":
            self.scene.update_node(proposal.entity_id, visible=bool(p["visible"]))
        elif proposal.event_type == "set_parent":
            self.scene.set_parent(proposal.entity_id, p.get("parent_id"))
        elif proposal.event_type == "set_asset":
            self.scene.update_node(proposal.entity_id, asset_id=p["asset_id"])
        elif proposal.event_type == "set_variant":
            self.scene.variant_selection[p["set"]] = p["selection"]
        elif proposal.event_type == "metadata_patch":
            node = self.scene.nodes[proposal.entity_id]
            metadata = dict(node.metadata)
            metadata.update(p["updates"])
            self.scene.update_node(proposal.entity_id, metadata=metadata)
        elif proposal.event_type == "custom":
            # Custom events are authoritative log entries only; application-specific reducers may replay them.
            pass
        else:
            raise ValueError(f"unsupported event type: {proposal.event_type}")

    def step(self, steps: int = 1) -> tuple[RuntimeEvent, ...]:
        if steps < 1:
            raise ValueError("steps must be positive")
        committed: list[RuntimeEvent] = []
        for _ in range(steps):
            t0 = self.time
            t1 = t0 + self.fixed_dt
            proposals: list[EventProposal] = []
            for system in self.systems:
                proposals.extend(system(self, t0, t1))
            committed.extend(self.commit_proposals(proposals))
            self.tick += 1
            self.time = t1
        return tuple(committed)

    def snapshot(self) -> dict[str, Any]:
        return {
            "scene": self.scene.to_dict(include_geometry=True),
            "fixed_dt": self.fixed_dt,
            "confidence_floor": self.confidence_floor,
            "tick": self.tick,
            "time": self.time,
            "sequence": self.sequence,
            "events": [event.__dict__ for event in self.events],
            "rejected": [item.__dict__ for item in self.rejected],
            "metrics": self.metrics.__dict__,
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "KCRuntime":
        runtime = cls(Scene.from_dict(snapshot["scene"]), snapshot["fixed_dt"], snapshot["confidence_floor"])
        runtime.tick = int(snapshot["tick"])
        runtime.time = float(snapshot["time"])
        runtime.sequence = int(snapshot["sequence"])
        runtime.events = [RuntimeEvent(**event) for event in snapshot.get("events", [])]
        runtime.rejected = [RejectedProposal(**item) for item in snapshot.get("rejected", [])]
        metrics = snapshot.get("metrics", {})
        runtime.metrics = RuntimeMetrics(**metrics)
        return runtime
