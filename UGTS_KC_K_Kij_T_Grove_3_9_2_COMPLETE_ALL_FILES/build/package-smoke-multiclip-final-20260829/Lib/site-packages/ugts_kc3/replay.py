"""Event-log replay, checkpoints, rollback and divergence detection."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable

from .runtime import EventProposal, KCRuntime, RuntimeEvent, canonical_json
from .scene import Scene


@dataclass(frozen=True)
class Checkpoint:
    sequence: int
    snapshot: dict[str, Any]
    snapshot_hash: str


@dataclass(frozen=True)
class Divergence:
    sequence: int
    expected_hash: str
    actual_hash: str
    reason: str


def scene_hash(scene: Scene) -> str:
    return hashlib.sha256(canonical_json(scene.to_dict(include_geometry=True))).hexdigest()


def checkpoint_runtime(runtime: KCRuntime) -> Checkpoint:
    snapshot = runtime.snapshot()
    digest = hashlib.sha256(canonical_json(snapshot)).hexdigest()
    return Checkpoint(runtime.sequence, snapshot, digest)


def verify_checkpoint(checkpoint: Checkpoint) -> bool:
    return hashlib.sha256(canonical_json(checkpoint.snapshot)).hexdigest() == checkpoint.snapshot_hash


def _proposal_from_event(event: RuntimeEvent) -> EventProposal:
    lineage_label = event.lineage[-1] if event.lineage else ""
    return EventProposal(
        proposal_id=f"replay-{event.sequence:08d}",
        event_time=event.event_time,
        event_type=event.event_type,
        entity_id=event.entity_id,
        payload=event.payload,
        source=event.source,
        priority=event.priority,
        confidence=event.confidence,
        lineage_label=lineage_label,
    )


def replay_events(initial_scene: Scene, events: Iterable[RuntimeEvent], fixed_dt: float = 1.0 / 60.0) -> tuple[KCRuntime, Divergence | None]:
    runtime = KCRuntime(initial_scene.clone(), fixed_dt=fixed_dt)
    for expected in sorted(events, key=lambda e: e.sequence):
        runtime.tick = expected.runtime_tick
        runtime.time = expected.runtime_time
        if expected.sequence != runtime.sequence + 1:
            return runtime, Divergence(expected.sequence, expected.post_state_hash, runtime.state_hash(), "sequence_gap")
        committed = runtime.commit_proposals([_proposal_from_event(expected)])
        if len(committed) != 1:
            return runtime, Divergence(expected.sequence, expected.post_state_hash, runtime.state_hash(), "event_not_committed")
        actual = committed[0]
        if actual.post_state_hash != expected.post_state_hash:
            return runtime, Divergence(expected.sequence, expected.post_state_hash, actual.post_state_hash, "post_state_hash_mismatch")
    return runtime, None


def rollback_to_checkpoint(checkpoint: Checkpoint, later_events: Iterable[RuntimeEvent], target_sequence: int) -> tuple[KCRuntime, Divergence | None]:
    if not verify_checkpoint(checkpoint):
        raise ValueError("checkpoint hash invalid")
    if target_sequence < checkpoint.sequence:
        raise ValueError("target precedes checkpoint")
    runtime = KCRuntime.from_snapshot(checkpoint.snapshot)
    selected = [e for e in later_events if checkpoint.sequence < e.sequence <= target_sequence]
    for expected in sorted(selected, key=lambda e: e.sequence):
        runtime.tick = expected.runtime_tick
        runtime.time = expected.runtime_time
        committed = runtime.commit_proposals([_proposal_from_event(expected)])
        if len(committed) != 1 or committed[0].post_state_hash != expected.post_state_hash:
            actual_hash = committed[0].post_state_hash if committed else runtime.state_hash()
            return runtime, Divergence(expected.sequence, expected.post_state_hash, actual_hash, "rollback_replay_mismatch")
    return runtime, None


class ReplayLog:
    def __init__(self, initial_scene: Scene):
        self.initial_scene = initial_scene.clone()
        self.events: list[RuntimeEvent] = []
        self.checkpoints: list[Checkpoint] = []
        self.schema_hash: str = hashlib.sha256(canonical_json({"schema": "ugts-kc3-replay-1"})).hexdigest()

    def append(self, event: RuntimeEvent):
        expected = len(self.events) + 1
        if event.sequence != expected:
            raise ValueError(f"expected event sequence {expected}")
        self.events.append(event)

    def add_checkpoint(self, checkpoint: Checkpoint):
        if not verify_checkpoint(checkpoint):
            raise ValueError("invalid checkpoint")
        self.checkpoints.append(checkpoint)
        self.checkpoints.sort(key=lambda c: c.sequence)

    def nearest_checkpoint(self, sequence: int) -> Checkpoint | None:
        candidates = [c for c in self.checkpoints if c.sequence <= sequence]
        return candidates[-1] if candidates else None

    def reconstruct(self, sequence: int | None = None) -> tuple[KCRuntime, Divergence | None]:
        sequence = len(self.events) if sequence is None else sequence
        if not 0 <= sequence <= len(self.events):
            raise ValueError("sequence outside log")
        checkpoint = self.nearest_checkpoint(sequence)
        if checkpoint is None:
            return replay_events(self.initial_scene, self.events[:sequence])
        return rollback_to_checkpoint(checkpoint, self.events, sequence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ugts-kc3-replay-1",
            "schema_hash": self.schema_hash,
            "initial_scene": self.initial_scene.to_dict(include_geometry=True),
            "events": [event.__dict__ for event in self.events],
            "checkpoints": [checkpoint.__dict__ for checkpoint in self.checkpoints],
        }

    def write(self, path: str):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReplayLog":
        log = cls(Scene.from_dict(data["initial_scene"]))
        if data.get("schema_hash") != log.schema_hash:
            raise ValueError("replay schema hash mismatch")
        log.events = [RuntimeEvent(**event) for event in data.get("events", [])]
        log.checkpoints = [Checkpoint(**checkpoint) for checkpoint in data.get("checkpoints", [])]
        return log
