"""Deterministic map mutation, lineage, checkpoints and replay."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import content_hash, write_json
from .model import CaptureProfile, MapEdge, MapNode, MapPatch, MapState, Pose3D, Uncertainty3D
from .verify import EventProposal, ProposalVerifier, VerificationDecision


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    sequence: int
    proposal_id: str
    event_time: float
    event_type: str
    target_id: str
    patch: MapPatch
    evidence_ids: tuple[str, ...]
    source: str
    priority: int
    confidence: float
    pre_hash: str
    post_hash: str
    lineage_label: str
    verification: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("ledger event sequence must be positive")
        if not self.proposal_id or not self.event_type or not self.target_id:
            raise ValueError("ledger event identity fields are required")
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(map(str, self.evidence_ids))))
        object.__setattr__(self, "verification", dict(self.verification))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "proposal_id": self.proposal_id,
            "event_time": self.event_time,
            "event_type": self.event_type,
            "target_id": self.target_id,
            "patch": self.patch.to_dict(),
            "evidence_ids": list(self.evidence_ids),
            "source": self.source,
            "priority": self.priority,
            "confidence": self.confidence,
            "pre_hash": self.pre_hash,
            "post_hash": self.post_hash,
            "lineage_label": self.lineage_label,
            "verification": dict(self.verification),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerEvent":
        return cls(
            sequence=int(value["sequence"]),
            proposal_id=str(value["proposal_id"]),
            event_time=float(value["event_time"]),
            event_type=str(value["event_type"]),
            target_id=str(value["target_id"]),
            patch=MapPatch.from_dict(value["patch"]),
            evidence_ids=tuple(value.get("evidence_ids", ())),
            source=str(value.get("source", "unknown")),
            priority=int(value.get("priority", 0)),
            confidence=float(value.get("confidence", 0.0)),
            pre_hash=str(value["pre_hash"]),
            post_hash=str(value["post_hash"]),
            lineage_label=str(value.get("lineage_label", "observed")),
            verification=dict(value.get("verification", {})),
        )


@dataclass(frozen=True, slots=True)
class RejectedProposal:
    proposal_id: str
    event_time: float
    target_id: str
    reasons: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "event_time": self.event_time,
            "target_id": self.target_id,
            "reasons": list(self.reasons),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RejectedProposal":
        return cls(
            str(value["proposal_id"]), float(value["event_time"]), str(value["target_id"]),
            tuple(value.get("reasons", ())), str(value.get("source", "unknown")),
        )


@dataclass(frozen=True, slots=True)
class CommitResult:
    events: tuple[LedgerEvent, ...]
    rejected: tuple[RejectedProposal, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.events)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [event.to_dict() for event in self.events],
            "rejected": [item.to_dict() for item in self.rejected],
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
        }


@dataclass(frozen=True, slots=True)
class Checkpoint:
    sequence: int
    map_state: Mapping[str, Any]
    state_hash: str
    event_stream_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "map_state": dict(self.map_state),
            "state_hash": self.state_hash,
            "event_stream_hash": self.event_stream_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Checkpoint":
        return cls(int(value["sequence"]), dict(value["map_state"]), str(value["state_hash"]), str(value["event_stream_hash"]))


@dataclass(frozen=True, slots=True)
class ReplayResult:
    success: bool
    state: MapState
    applied_events: int
    divergence_sequence: int | None = None
    reason: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "applied_events": self.applied_events,
            "divergence_sequence": self.divergence_sequence,
            "reason": self.reason,
            "state_hash": self.state.state_hash(),
        }


@dataclass
class SpatialLedger:
    map_state: MapState = field(default_factory=MapState)
    capture_profiles: dict[str, CaptureProfile] = field(default_factory=dict)
    events: list[LedgerEvent] = field(default_factory=list)
    rejected: list[RejectedProposal] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.map_state = self.map_state.clone()
        self.capture_profiles = dict(self.capture_profiles)
        self.events = list(self.events)
        self.rejected = list(self.rejected)
        self.checkpoints = list(self.checkpoints)
        if self.events:
            sequences = [event.sequence for event in self.events]
            if sequences != list(range(1, len(self.events) + 1)):
                raise ValueError("ledger events must have contiguous sequences beginning at one")

    @property
    def sequence(self) -> int:
        return len(self.events)

    def state_hash(self) -> str:
        return self.map_state.state_hash()

    def event_stream_hash(self) -> str:
        return content_hash([event.to_dict() for event in self.events])

    def _apply_patch(self, patch: MapPatch, *, evidence_id: str | None, lineage_label: str | None) -> None:
        operation = patch.operation
        target = patch.target_id
        payload = dict(patch.payload)

        if operation == "upsert_node":
            record = payload.get("node", payload)
            node = MapNode.from_dict(record)
            if node.id != target:
                raise ValueError("upsert_node payload id does not match target")
            existing = self.map_state.nodes.get(target)
            if existing is None:
                evidence = node.evidence_ids + ((evidence_id,) if evidence_id and evidence_id not in node.evidence_ids else ())
                lineage = node.lineage + ((lineage_label,) if lineage_label else ())
                self.map_state.nodes[target] = replace(node, evidence_ids=evidence, lineage=lineage)
            else:
                evidence = tuple(dict.fromkeys(existing.evidence_ids + node.evidence_ids + ((evidence_id,) if evidence_id else ())))
                lineage = existing.lineage + node.lineage + ((lineage_label,) if lineage_label else ())
                self.map_state.nodes[target] = replace(node, revision=existing.revision + 1, evidence_ids=evidence, lineage=lineage)

        elif operation == "remove_node":
            if target not in self.map_state.nodes:
                raise KeyError(f"unknown node: {target}")
            del self.map_state.nodes[target]
            for edge_id in sorted([edge_id for edge_id, edge in self.map_state.edges.items() if target in {edge.source, edge.target}]):
                del self.map_state.edges[edge_id]

        elif operation == "update_node_state":
            node = self.map_state.nodes.get(target)
            if node is None:
                raise KeyError(f"unknown node: {target}")
            state = dict(node.state)
            state.update(payload)
            self.map_state.nodes[target] = node.with_revision(evidence_id=evidence_id, lineage_label=lineage_label, state=state)

        elif operation == "update_node_pose":
            node = self.map_state.nodes.get(target)
            if node is None:
                raise KeyError(f"unknown node: {target}")
            pose_value = payload.get("pose", payload)
            pose = Pose3D.from_dict(pose_value)
            uncertainty = node.uncertainty
            if "uncertainty" in payload:
                uncertainty = Uncertainty3D.from_dict(payload["uncertainty"])
            self.map_state.nodes[target] = node.with_revision(
                evidence_id=evidence_id, lineage_label=lineage_label, pose=pose, uncertainty=uncertainty,
            )

        elif operation == "append_node_evidence":
            node = self.map_state.nodes.get(target)
            if node is None:
                raise KeyError(f"unknown node: {target}")
            values = tuple(payload.get("evidence_ids", ())) + ((evidence_id,) if evidence_id else ())
            evidence = tuple(dict.fromkeys(node.evidence_ids + tuple(map(str, values))))
            lineage = node.lineage + ((lineage_label,) if lineage_label else ())
            self.map_state.nodes[target] = replace(node, revision=node.revision + 1, evidence_ids=evidence, lineage=lineage)

        elif operation == "upsert_edge":
            record = payload.get("edge", payload)
            edge = MapEdge.from_dict(record)
            if edge.id != target:
                raise ValueError("upsert_edge payload id does not match target")
            if edge.source not in self.map_state.nodes or edge.target not in self.map_state.nodes:
                raise ValueError("upsert_edge references unknown node")
            existing = self.map_state.edges.get(target)
            if existing is None:
                evidence = edge.evidence_ids + ((evidence_id,) if evidence_id and evidence_id not in edge.evidence_ids else ())
                lineage = edge.lineage + ((lineage_label,) if lineage_label else ())
                self.map_state.edges[target] = replace(edge, evidence_ids=evidence, lineage=lineage)
            else:
                evidence = tuple(dict.fromkeys(existing.evidence_ids + edge.evidence_ids + ((evidence_id,) if evidence_id else ())))
                lineage = existing.lineage + edge.lineage + ((lineage_label,) if lineage_label else ())
                self.map_state.edges[target] = replace(edge, revision=existing.revision + 1, evidence_ids=evidence, lineage=lineage)

        elif operation == "remove_edge":
            if target not in self.map_state.edges:
                raise KeyError(f"unknown edge: {target}")
            del self.map_state.edges[target]

        elif operation == "update_edge_state":
            edge = self.map_state.edges.get(target)
            if edge is None:
                raise KeyError(f"unknown edge: {target}")
            state = dict(edge.state)
            state.update(payload)
            self.map_state.edges[target] = edge.with_revision(evidence_id=evidence_id, lineage_label=lineage_label, state=state)

        elif operation == "update_edge_metrics":
            edge = self.map_state.edges.get(target)
            if edge is None:
                raise KeyError(f"unknown edge: {target}")
            metrics = dict(edge.metrics)
            metrics.update({str(key): float(value) for key, value in payload.items()})
            self.map_state.edges[target] = edge.with_revision(evidence_id=evidence_id, lineage_label=lineage_label, metrics=metrics)

        elif operation == "append_edge_evidence":
            edge = self.map_state.edges.get(target)
            if edge is None:
                raise KeyError(f"unknown edge: {target}")
            values = tuple(payload.get("evidence_ids", ())) + ((evidence_id,) if evidence_id else ())
            evidence = tuple(dict.fromkeys(edge.evidence_ids + tuple(map(str, values))))
            lineage = edge.lineage + ((lineage_label,) if lineage_label else ())
            self.map_state.edges[target] = replace(edge, revision=edge.revision + 1, evidence_ids=evidence, lineage=lineage)

        else:  # pragma: no cover - MapPatch already validates the operation
            raise ValueError(f"unsupported patch operation: {operation}")
        self.map_state.validate()

    def commit(self, proposals: Iterable[EventProposal], verifier: ProposalVerifier) -> CommitResult:
        accepted_events: list[LedgerEvent] = []
        rejected: list[RejectedProposal] = []
        conflict_keys: dict[tuple[float, str], str] = {}
        seen_ids = {event.proposal_id for event in self.events}

        for proposal in sorted(proposals, key=EventProposal.sort_key):
            reasons: list[str] = []
            if proposal.id in seen_ids:
                reasons.append("proposal_id_duplicate")
            decision: VerificationDecision | None = None
            if not reasons:
                decision = verifier.verify(proposal, self.capture_profiles)
                if not decision.accepted:
                    reasons.extend(decision.reasons)
            if not reasons:
                for key in proposal.patch.conflict_keys():
                    conflict_key = (proposal.event_time, key)
                    if conflict_key in conflict_keys:
                        reasons.append(f"conflict_with:{conflict_keys[conflict_key]}")
                        break
            if reasons:
                item = RejectedProposal(proposal.id, proposal.event_time, proposal.target_id, tuple(reasons), proposal.source)
                self.rejected.append(item)
                rejected.append(item)
                continue

            pre_hash = self.state_hash()
            prior_state = self.map_state.clone()
            try:
                self._apply_patch(
                    proposal.patch,
                    evidence_id=proposal.observation.id,
                    lineage_label=proposal.lineage_label,
                )
            except (KeyError, TypeError, ValueError) as exc:
                self.map_state = prior_state
                item = RejectedProposal(
                    proposal.id, proposal.event_time, proposal.target_id,
                    (f"patch_error:{type(exc).__name__}:{exc}",), proposal.source,
                )
                self.rejected.append(item)
                rejected.append(item)
                continue
            post_hash = self.state_hash()
            event = LedgerEvent(
                sequence=self.sequence + 1,
                proposal_id=proposal.id,
                event_time=proposal.event_time,
                event_type=proposal.event_type,
                target_id=proposal.target_id,
                patch=proposal.patch,
                evidence_ids=(proposal.observation.id,),
                source=proposal.source,
                priority=proposal.priority,
                confidence=proposal.observation.confidence,
                pre_hash=pre_hash,
                post_hash=post_hash,
                lineage_label=proposal.lineage_label,
                verification=decision.to_dict() if decision is not None else {},
            )
            self.events.append(event)
            accepted_events.append(event)
            seen_ids.add(proposal.id)
            for key in proposal.patch.conflict_keys():
                conflict_keys[(proposal.event_time, key)] = proposal.id

        return CommitResult(tuple(accepted_events), tuple(rejected))

    def checkpoint(self) -> Checkpoint:
        checkpoint = Checkpoint(
            sequence=self.sequence,
            map_state=self.map_state.to_dict(),
            state_hash=self.state_hash(),
            event_stream_hash=self.event_stream_hash(),
        )
        self.checkpoints.append(checkpoint)
        return checkpoint

    def restore(self, checkpoint: Checkpoint) -> None:
        state = MapState.from_dict(checkpoint.map_state)
        if state.state_hash() != checkpoint.state_hash:
            raise ValueError("checkpoint state hash mismatch")
        if checkpoint.sequence > self.sequence:
            raise ValueError("checkpoint sequence is ahead of this ledger")
        self.map_state = state
        self.events = self.events[:checkpoint.sequence]
        self.rejected = []
        self.checkpoints = [item for item in self.checkpoints if item.sequence <= checkpoint.sequence]
        if self.event_stream_hash() != checkpoint.event_stream_hash:
            raise ValueError("checkpoint event-stream hash mismatch")

    def snapshot(self, *, include_events: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema": "ugts-kc-spatial-ledger-4.0",
            "sequence": self.sequence,
            "state_hash": self.state_hash(),
            "event_stream_hash": self.event_stream_hash(),
            "map_state": self.map_state.to_dict(),
            "capture_profiles": [self.capture_profiles[key].to_dict() for key in sorted(self.capture_profiles)],
            "checkpoints": [checkpoint.to_dict() for checkpoint in self.checkpoints],
            "rejected": [item.to_dict() for item in self.rejected],
        }
        if include_events:
            value["events"] = [event.to_dict() for event in self.events]
        return value

    def to_dict(self) -> dict[str, Any]:
        return self.snapshot(include_events=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpatialLedger":
        profiles = {item["id"]: CaptureProfile.from_dict(item) for item in value.get("capture_profiles", [])}
        ledger = cls(
            map_state=MapState.from_dict(value.get("map_state", {})),
            capture_profiles=profiles,
            events=[LedgerEvent.from_dict(item) for item in value.get("events", [])],
            rejected=[RejectedProposal.from_dict(item) for item in value.get("rejected", [])],
            checkpoints=[Checkpoint.from_dict(item) for item in value.get("checkpoints", [])],
        )
        expected = value.get("state_hash")
        if expected is not None and ledger.state_hash() != expected:
            raise ValueError("ledger state hash mismatch")
        expected_stream = value.get("event_stream_hash")
        if expected_stream is not None and ledger.event_stream_hash() != expected_stream:
            raise ValueError("ledger event-stream hash mismatch")
        return ledger

    def write(self, path: str | Path) -> Path:
        return write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: str | Path) -> "SpatialLedger":
        import json
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @staticmethod
    def replay(initial_state: MapState, events: Iterable[LedgerEvent], capture_profiles: Mapping[str, CaptureProfile] | None = None) -> ReplayResult:
        ledger = SpatialLedger(initial_state, dict(capture_profiles or {}))
        applied = 0
        for event in sorted(events, key=lambda item: item.sequence):
            if event.sequence != applied + 1:
                return ReplayResult(False, ledger.map_state, applied, event.sequence, "sequence_gap")
            if ledger.state_hash() != event.pre_hash:
                return ReplayResult(False, ledger.map_state, applied, event.sequence, "pre_hash_mismatch")
            try:
                ledger._apply_patch(
                    event.patch,
                    evidence_id=event.evidence_ids[0] if event.evidence_ids else None,
                    lineage_label=event.lineage_label,
                )
            except (KeyError, TypeError, ValueError):
                return ReplayResult(False, ledger.map_state, applied, event.sequence, "patch_apply_failed")
            if ledger.state_hash() != event.post_hash:
                return ReplayResult(False, ledger.map_state, applied, event.sequence, "post_hash_mismatch")
            ledger.events.append(event)
            applied += 1
        return ReplayResult(True, ledger.map_state, applied)
