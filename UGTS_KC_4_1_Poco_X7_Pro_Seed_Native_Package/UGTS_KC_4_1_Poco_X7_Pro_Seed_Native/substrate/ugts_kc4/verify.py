"""Canonical support -> compatibility -> guard -> verified-proposal pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from .model import CaptureProfile, Interval, MapPatch, Observation
from .support import CompatibilityPolicy, SupportRegistry


@dataclass(frozen=True, slots=True)
class GuardResult:
    status: str
    interval: Interval
    margin: float

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "interval": self.interval.to_dict(), "margin": self.margin}


def classify_guard(value: float, numeric_error: float, margin: float) -> GuardResult:
    value = float(value)
    numeric_error = float(numeric_error)
    margin = float(margin)
    if not all(math.isfinite(item) for item in (value, numeric_error, margin)):
        raise ValueError("guard inputs must be finite")
    if numeric_error < 0 or margin < 0:
        raise ValueError("guard error and margin must be non-negative")
    interval = Interval(value - numeric_error, value + numeric_error)
    if interval.upper < -margin:
        status = "inside"
    elif interval.lower > margin:
        status = "outside"
    elif interval.lower <= -margin and interval.upper >= margin:
        status = "crossing"
    elif interval.lower >= -margin and interval.upper <= margin:
        status = "guard"
    else:
        status = "ambiguous"
    return GuardResult(status, interval, margin)


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    id: str = "default"
    confidence_floor: float = 0.75
    max_numeric_error: float = 0.05
    event_margin: float = 0.05
    max_position_uncertainty: float = 0.25
    kind_uncertainty_limits: tuple[tuple[str, float], ...] = ()
    accepted_guard_statuses: tuple[str, ...] = ("confirmed", "crossing", "inside", "guard")
    accepted_relation_classes: tuple[str, ...] = ("inside", "guard", "crossing")
    metric_required_kinds: tuple[str, ...] = ("doorway", "route_edge", "clearance", "measurement")
    require_source_hash: bool = True
    require_definition_hashes: bool = False
    allowed_source_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("verification policy id is required")
        confidence = float(self.confidence_floor)
        numeric = float(self.max_numeric_error)
        margin = float(self.event_margin)
        uncertainty = float(self.max_position_uncertainty)
        if not 0 <= confidence <= 1:
            raise ValueError("confidence_floor must be in [0,1]")
        if any(not math.isfinite(value) or value < 0 for value in (numeric, margin, uncertainty)):
            raise ValueError("verification error limits must be finite and non-negative")
        limits = tuple(sorted((str(kind), float(limit)) for kind, limit in self.kind_uncertainty_limits))
        if any(not math.isfinite(limit) or limit < 0 for _, limit in limits):
            raise ValueError("kind uncertainty limits must be finite and non-negative")
        object.__setattr__(self, "confidence_floor", confidence)
        object.__setattr__(self, "max_numeric_error", numeric)
        object.__setattr__(self, "event_margin", margin)
        object.__setattr__(self, "max_position_uncertainty", uncertainty)
        object.__setattr__(self, "kind_uncertainty_limits", limits)
        object.__setattr__(self, "accepted_guard_statuses", tuple(sorted(set(map(str, self.accepted_guard_statuses)))))
        object.__setattr__(self, "accepted_relation_classes", tuple(sorted(set(map(str, self.accepted_relation_classes)))))
        object.__setattr__(self, "metric_required_kinds", tuple(sorted(set(map(str, self.metric_required_kinds)))))
        object.__setattr__(self, "allowed_source_models", tuple(sorted(set(map(str, self.allowed_source_models)))))

    def uncertainty_limit(self, kind: str) -> float:
        limits = dict(self.kind_uncertainty_limits)
        return limits.get(kind, self.max_position_uncertainty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "confidence_floor": self.confidence_floor,
            "max_numeric_error": self.max_numeric_error,
            "event_margin": self.event_margin,
            "max_position_uncertainty": self.max_position_uncertainty,
            "kind_uncertainty_limits": {kind: limit for kind, limit in self.kind_uncertainty_limits},
            "accepted_guard_statuses": list(self.accepted_guard_statuses),
            "accepted_relation_classes": list(self.accepted_relation_classes),
            "metric_required_kinds": list(self.metric_required_kinds),
            "require_source_hash": self.require_source_hash,
            "require_definition_hashes": self.require_definition_hashes,
            "allowed_source_models": list(self.allowed_source_models),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationPolicy":
        limits = value.get("kind_uncertainty_limits", {})
        limit_items = tuple(limits.items()) if isinstance(limits, Mapping) else tuple(tuple(item) for item in limits)
        return cls(
            id=str(value.get("id", "default")),
            confidence_floor=float(value.get("confidence_floor", 0.75)),
            max_numeric_error=float(value.get("max_numeric_error", 0.05)),
            event_margin=float(value.get("event_margin", 0.05)),
            max_position_uncertainty=float(value.get("max_position_uncertainty", 0.25)),
            kind_uncertainty_limits=limit_items,
            accepted_guard_statuses=tuple(value.get("accepted_guard_statuses", ("confirmed", "crossing", "inside", "guard"))),
            accepted_relation_classes=tuple(value.get("accepted_relation_classes", ("inside", "guard", "crossing"))),
            metric_required_kinds=tuple(value.get("metric_required_kinds", ("doorway", "route_edge", "clearance", "measurement"))),
            require_source_hash=bool(value.get("require_source_hash", True)),
            require_definition_hashes=bool(value.get("require_definition_hashes", False)),
            allowed_source_models=tuple(value.get("allowed_source_models", ())),
        )


@dataclass(frozen=True, slots=True)
class EventProposal:
    id: str
    event_time: float
    event_type: str
    target_id: str
    observation: Observation
    patch: MapPatch
    source: str = "local"
    priority: int = 0
    event_margin: float | None = None
    lineage_label: str = "observed"

    def __post_init__(self) -> None:
        if not self.id or not self.event_type or not self.target_id or not self.source:
            raise ValueError("proposal id, type, target and source are required")
        event_time = float(self.event_time)
        if not math.isfinite(event_time):
            raise ValueError("proposal event_time must be finite")
        if self.target_id != self.patch.target_id:
            raise ValueError("proposal target_id must match patch target_id")
        margin = self.event_margin
        if margin is not None:
            margin = float(margin)
            if not math.isfinite(margin) or margin < 0:
                raise ValueError("proposal event_margin must be finite and non-negative")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(self, "event_margin", margin)

    def sort_key(self) -> tuple[float, int, str, str]:
        return (self.event_time, -self.priority, self.source, self.id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_time": self.event_time,
            "event_type": self.event_type,
            "target_id": self.target_id,
            "observation": self.observation.to_dict(),
            "patch": self.patch.to_dict(),
            "source": self.source,
            "priority": self.priority,
            "event_margin": self.event_margin,
            "lineage_label": self.lineage_label,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EventProposal":
        return cls(
            id=str(value["id"]),
            event_time=float(value["event_time"]),
            event_type=str(value["event_type"]),
            target_id=str(value["target_id"]),
            observation=Observation.from_dict(value["observation"]),
            patch=MapPatch.from_dict(value["patch"]),
            source=str(value.get("source", "local")),
            priority=int(value.get("priority", 0)),
            event_margin=value.get("event_margin"),
            lineage_label=str(value.get("lineage_label", "observed")),
        )


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    accepted: bool
    proposal_id: str
    reasons: tuple[str, ...]
    support_ok: bool
    compatibility_ok: bool
    guard: GuardResult
    profile_metric_ready: bool
    position_uncertainty: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "proposal_id": self.proposal_id,
            "reasons": list(self.reasons),
            "support_ok": self.support_ok,
            "compatibility_ok": self.compatibility_ok,
            "guard": self.guard.to_dict(),
            "profile_metric_ready": self.profile_metric_ready,
            "position_uncertainty": self.position_uncertainty,
        }


@dataclass
class ProposalVerifier:
    supports: SupportRegistry
    compatibility_policies: dict[str, CompatibilityPolicy]
    policy: VerificationPolicy = field(default_factory=VerificationPolicy)

    def __post_init__(self) -> None:
        self.compatibility_policies = dict(self.compatibility_policies)
        if "default" not in self.compatibility_policies:
            self.compatibility_policies["default"] = CompatibilityPolicy("default")

    def verify(self, proposal: EventProposal, capture_profiles: Mapping[str, CaptureProfile]) -> VerificationDecision:
        observation = proposal.observation
        reasons: list[str] = []
        profile = capture_profiles.get(observation.capture_profile_id)
        if profile is None:
            profile_metric_ready = False
            reasons.append("capture_profile_unknown")
        else:
            profile_metric_ready = profile.metric_ready

        support_ok = False
        try:
            support_ok = self.supports.contains(
                observation.support_id,
                observation.pose.position,
                observation.uncertainty.position_bound(),
            )
        except KeyError:
            reasons.append("support_unknown")
        if not support_ok and "support_unknown" not in reasons:
            reasons.append("outside_support")

        compatibility = self.compatibility_policies.get(observation.compatibility_policy_id)
        if compatibility is None:
            compatibility_ok = False
            reasons.append("compatibility_policy_unknown")
        else:
            compatibility_result = compatibility.evaluate(observation)
            compatibility_ok = compatibility_result.compatible
            reasons.extend(compatibility_result.reasons)

        margin = proposal.event_margin if proposal.event_margin is not None else self.policy.event_margin
        guard = classify_guard(observation.relation_value, observation.numeric_error, margin)
        if observation.guard_status not in self.policy.accepted_guard_statuses:
            reasons.append(f"guard_status_rejected:{observation.guard_status}")
        if guard.status not in self.policy.accepted_relation_classes:
            reasons.append(f"relation_class_rejected:{guard.status}")
        if observation.confidence < self.policy.confidence_floor:
            reasons.append("confidence_below_floor")
        if observation.numeric_error > self.policy.max_numeric_error:
            reasons.append("numeric_error_exceeds_policy")
        if observation.numeric_error > margin:
            reasons.append("numeric_error_exceeds_event_margin")

        position_uncertainty = observation.uncertainty.position_bound()
        if position_uncertainty > self.policy.uncertainty_limit(observation.kind):
            reasons.append("position_uncertainty_exceeds_limit")

        metric_required = observation.scale_required or observation.kind in self.policy.metric_required_kinds
        if metric_required and not profile_metric_ready:
            reasons.append("metric_scale_required")
        if self.policy.require_source_hash and observation.source_hash in {"", "unverified", "unknown"}:
            reasons.append("source_hash_required")
        if self.policy.require_definition_hashes and not observation.definition_hashes:
            reasons.append("definition_hashes_required")
        if self.policy.allowed_source_models and observation.source_model not in self.policy.allowed_source_models:
            reasons.append("source_model_not_allowed")
        if profile is not None and profile.id != observation.capture_profile_id:
            reasons.append("capture_profile_mismatch")

        return VerificationDecision(
            accepted=not reasons,
            proposal_id=proposal.id,
            reasons=tuple(reasons),
            support_ok=support_ok,
            compatibility_ok=compatibility_ok,
            guard=guard,
            profile_metric_ready=profile_metric_ready,
            position_uncertainty=position_uncertainty,
        )
