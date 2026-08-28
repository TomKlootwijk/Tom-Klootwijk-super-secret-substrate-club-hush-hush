"""Repeat-scan change candidates and low-bandwidth proposal-delta merging."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping

from .canonical import content_hash
from .model import Interval, MapEdge, MapNode, MapState, vec_distance
from .verify import EventProposal


@dataclass(frozen=True, slots=True)
class ChangePolicy:
    movement_threshold_m: float = 0.10
    state_keys: tuple[str, ...] = ("status", "passability", "present", "blocked")
    metric_thresholds: tuple[tuple[str, float], ...] = (("clearance_m", 0.05),)
    confidence_floor: float = 0.70
    report_ambiguous_movement: bool = True

    def __post_init__(self) -> None:
        movement = float(self.movement_threshold_m)
        confidence = float(self.confidence_floor)
        if not math.isfinite(movement) or movement < 0:
            raise ValueError("movement threshold must be finite and non-negative")
        if not 0 <= confidence <= 1:
            raise ValueError("change confidence floor must be in [0,1]")
        thresholds = tuple(sorted((str(key), float(value)) for key, value in self.metric_thresholds))
        if any(not math.isfinite(value) or value < 0 for _, value in thresholds):
            raise ValueError("metric thresholds must be finite and non-negative")
        object.__setattr__(self, "movement_threshold_m", movement)
        object.__setattr__(self, "confidence_floor", confidence)
        object.__setattr__(self, "state_keys", tuple(sorted(set(map(str, self.state_keys)))))
        object.__setattr__(self, "metric_thresholds", thresholds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "movement_threshold_m": self.movement_threshold_m,
            "state_keys": list(self.state_keys),
            "metric_thresholds": {key: value for key, value in self.metric_thresholds},
            "confidence_floor": self.confidence_floor,
            "report_ambiguous_movement": self.report_ambiguous_movement,
        }


@dataclass(frozen=True, slots=True)
class ChangeCandidate:
    id: str
    kind: str
    entity_type: str
    target_id: str
    baseline_id: str | None
    current_id: str | None
    verified: bool
    confidence: float
    reason: str
    value_interval: Interval | None = None
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.kind or not self.entity_type or not self.target_id:
            raise ValueError("change candidate identity fields are required")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("change candidate confidence must be in [0,1]")
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "before", dict(self.before))
        object.__setattr__(self, "after", dict(self.after))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "entity_type": self.entity_type,
            "target_id": self.target_id,
            "baseline_id": self.baseline_id,
            "current_id": self.current_id,
            "verified": self.verified,
            "confidence": self.confidence,
            "reason": self.reason,
            "value_interval": self.value_interval.to_dict() if self.value_interval else None,
            "before": dict(self.before),
            "after": dict(self.after),
        }


def _state_confidence(value: Mapping[str, Any]) -> float:
    try:
        confidence = float(value.get("confidence", 1.0))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _node_changes(baseline: MapNode, current: MapNode, policy: ChangePolicy) -> list[ChangeCandidate]:
    candidates: list[ChangeCandidate] = []
    distance = vec_distance(baseline.pose.position, current.pose.position)
    bound = baseline.uncertainty.position_bound() + current.uncertainty.position_bound()
    interval = Interval(max(0.0, distance - bound), distance + bound)
    confidence = min(_state_confidence(baseline.state), _state_confidence(current.state))
    if interval.lower > policy.movement_threshold_m:
        candidates.append(ChangeCandidate(
            f"change:node:{baseline.id}:moved", "moved", "node", baseline.id,
            baseline.id, current.id, confidence >= policy.confidence_floor, confidence,
            "displacement_interval_exceeds_threshold", interval,
            {"position": list(baseline.pose.position)}, {"position": list(current.pose.position)},
        ))
    elif policy.report_ambiguous_movement and interval.upper > policy.movement_threshold_m:
        candidates.append(ChangeCandidate(
            f"change:node:{baseline.id}:movement_ambiguous", "movement_ambiguous", "node", baseline.id,
            baseline.id, current.id, False, confidence,
            "uncertainty_interval_overlaps_threshold", interval,
            {"position": list(baseline.pose.position)}, {"position": list(current.pose.position)},
        ))
    before = {key: baseline.state.get(key) for key in policy.state_keys if key in baseline.state or key in current.state}
    after = {key: current.state.get(key) for key in policy.state_keys if key in baseline.state or key in current.state}
    if before != after:
        candidates.append(ChangeCandidate(
            f"change:node:{baseline.id}:state", "state_changed", "node", baseline.id,
            baseline.id, current.id, confidence >= policy.confidence_floor, confidence,
            "selected_state_fields_changed", None, before, after,
        ))
    return candidates


def _edge_changes(baseline: MapEdge, current: MapEdge, policy: ChangePolicy) -> list[ChangeCandidate]:
    candidates: list[ChangeCandidate] = []
    confidence = min(_state_confidence(baseline.state), _state_confidence(current.state))
    before = {key: baseline.state.get(key) for key in policy.state_keys if key in baseline.state or key in current.state}
    after = {key: current.state.get(key) for key in policy.state_keys if key in baseline.state or key in current.state}
    if before != after:
        candidates.append(ChangeCandidate(
            f"change:edge:{baseline.id}:state", "state_changed", "edge", baseline.id,
            baseline.id, current.id, confidence >= policy.confidence_floor, confidence,
            "selected_state_fields_changed", None, before, after,
        ))
    for key, threshold in policy.metric_thresholds:
        if key not in baseline.metrics or key not in current.metrics:
            continue
        delta = abs(float(current.metrics[key]) - float(baseline.metrics[key]))
        error = abs(float(baseline.metrics.get(f"{key}_error", 0.0))) + abs(float(current.metrics.get(f"{key}_error", 0.0)))
        interval = Interval(max(0.0, delta - error), delta + error)
        if interval.lower > threshold:
            candidates.append(ChangeCandidate(
                f"change:edge:{baseline.id}:metric:{key}", "metric_changed", "edge", baseline.id,
                baseline.id, current.id, confidence >= policy.confidence_floor, confidence,
                f"metric_interval_exceeds_threshold:{key}", interval,
                {key: baseline.metrics[key]}, {key: current.metrics[key]},
            ))
    return candidates


def detect_changes(baseline: MapState, current: MapState, policy: ChangePolicy | None = None) -> tuple[ChangeCandidate, ...]:
    policy = policy or ChangePolicy()
    candidates: list[ChangeCandidate] = []
    baseline_nodes = set(baseline.nodes)
    current_nodes = set(current.nodes)
    for node_id in sorted(baseline_nodes & current_nodes):
        candidates.extend(_node_changes(baseline.nodes[node_id], current.nodes[node_id], policy))
    for node_id in sorted(current_nodes - baseline_nodes):
        confidence = _state_confidence(current.nodes[node_id].state)
        candidates.append(ChangeCandidate(
            f"change:node:{node_id}:added", "added", "node", node_id,
            None, node_id, confidence >= policy.confidence_floor, confidence,
            "stable_id_present_only_in_current", None, {}, current.nodes[node_id].to_dict(),
        ))
    for node_id in sorted(baseline_nodes - current_nodes):
        confidence = _state_confidence(baseline.nodes[node_id].state)
        candidates.append(ChangeCandidate(
            f"change:node:{node_id}:removed", "removed", "node", node_id,
            node_id, None, confidence >= policy.confidence_floor, confidence,
            "stable_id_present_only_in_baseline", None, baseline.nodes[node_id].to_dict(), {},
        ))

    baseline_edges = set(baseline.edges)
    current_edges = set(current.edges)
    for edge_id in sorted(baseline_edges & current_edges):
        candidates.extend(_edge_changes(baseline.edges[edge_id], current.edges[edge_id], policy))
    for edge_id in sorted(current_edges - baseline_edges):
        confidence = _state_confidence(current.edges[edge_id].state)
        candidates.append(ChangeCandidate(
            f"change:edge:{edge_id}:added", "added", "edge", edge_id,
            None, edge_id, confidence >= policy.confidence_floor, confidence,
            "stable_id_present_only_in_current", None, {}, current.edges[edge_id].to_dict(),
        ))
    for edge_id in sorted(baseline_edges - current_edges):
        confidence = _state_confidence(baseline.edges[edge_id].state)
        candidates.append(ChangeCandidate(
            f"change:edge:{edge_id}:removed", "removed", "edge", edge_id,
            edge_id, None, confidence >= policy.confidence_floor, confidence,
            "stable_id_present_only_in_baseline", None, baseline.edges[edge_id].to_dict(), {},
        ))
    return tuple(sorted(candidates, key=lambda item: (item.entity_type, item.target_id, item.kind, item.id)))


@dataclass(frozen=True, slots=True)
class ProposalDelta:
    base_state_hash: str
    source_id: str
    proposals: tuple[EventProposal, ...]
    schema: str = "ugts-kc-spatial-proposal-delta-4.0"

    def __post_init__(self) -> None:
        if not self.base_state_hash or not self.source_id:
            raise ValueError("proposal delta requires base hash and source id")
        object.__setattr__(self, "proposals", tuple(self.proposals))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "base_state_hash": self.base_state_hash,
            "source_id": self.source_id,
            "proposals": [proposal.to_dict() for proposal in sorted(self.proposals, key=EventProposal.sort_key)],
            "content_hash": self.content_hash(),
        }

    def content_hash(self) -> str:
        payload = {
            "schema": self.schema,
            "base_state_hash": self.base_state_hash,
            "source_id": self.source_id,
            "proposals": [proposal.to_dict() for proposal in sorted(self.proposals, key=EventProposal.sort_key)],
        }
        return content_hash(payload)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProposalDelta":
        delta = cls(
            base_state_hash=str(value["base_state_hash"]),
            source_id=str(value["source_id"]),
            proposals=tuple(EventProposal.from_dict(item) for item in value.get("proposals", ())),
            schema=str(value.get("schema", "ugts-kc-spatial-proposal-delta-4.0")),
        )
        expected = value.get("content_hash")
        if expected is not None and expected != delta.content_hash():
            raise ValueError("proposal delta content hash mismatch")
        return delta


@dataclass(frozen=True, slots=True)
class MergeConflict:
    proposal_id: str
    winner_id: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"proposal_id": self.proposal_id, "winner_id": self.winner_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class DeltaMergeResult:
    base_state_hash: str
    proposals: tuple[EventProposal, ...]
    conflicts: tuple[MergeConflict, ...]
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_state_hash": self.base_state_hash,
            "source_ids": list(self.source_ids),
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
        }


def merge_proposal_deltas(deltas: Iterable[ProposalDelta]) -> DeltaMergeResult:
    values = list(deltas)
    if not values:
        raise ValueError("at least one delta is required")
    base_hashes = {value.base_state_hash for value in values}
    if len(base_hashes) != 1:
        raise ValueError("proposal deltas do not share a base state hash")
    source_ids = tuple(sorted({value.source_id for value in values}))
    conflicts: list[MergeConflict] = []
    by_id: dict[str, EventProposal] = {}
    for delta in sorted(values, key=lambda item: item.source_id):
        for proposal in delta.proposals:
            existing = by_id.get(proposal.id)
            if existing is None:
                by_id[proposal.id] = proposal
            elif existing.to_dict() != proposal.to_dict():
                winner = min(existing, proposal, key=EventProposal.sort_key)
                by_id[proposal.id] = winner
                conflicts.append(MergeConflict(proposal.id, winner.id, "duplicate_id_with_different_payload"))

    accepted: list[EventProposal] = []
    occupied: dict[tuple[float, str], str] = {}
    for proposal in sorted(by_id.values(), key=EventProposal.sort_key):
        conflict_with: str | None = None
        for key in proposal.patch.conflict_keys():
            lookup = (proposal.event_time, key)
            if lookup in occupied:
                conflict_with = occupied[lookup]
                break
        if conflict_with is not None:
            conflicts.append(MergeConflict(proposal.id, conflict_with, "same_time_patch_conflict"))
            continue
        accepted.append(proposal)
        for key in proposal.patch.conflict_keys():
            occupied[(proposal.event_time, key)] = proposal.id
    return DeltaMergeResult(next(iter(base_hashes)), tuple(accepted), tuple(conflicts), source_ids)
