"""Versioned project container for the spatial-evidence substrate."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import content_hash, write_json
from .index import RayKeyProfile, VoxelKeyProfile
from .ledger import SpatialLedger
from .model import CaptureProfile, MapState
from .support import CompatibilityPolicy, SupportRegistry
from .topology import RoutePolicy, validate_route_topology
from .verify import ProposalVerifier, VerificationPolicy
from .version import __schema__, __version__


@dataclass(frozen=True, slots=True)
class ProjectMetadata:
    id: str
    title: str
    author: str
    description: str = ""
    release: str = __version__
    requester_attribution: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.title or not self.author:
            raise ValueError("project metadata requires id, title and author")
        object.__setattr__(self, "requester_attribution", dict(self.requester_attribution))
        object.__setattr__(self, "tags", tuple(sorted(set(map(str, self.tags)))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "description": self.description,
            "release": self.release,
            "requester_attribution": dict(self.requester_attribution),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectMetadata":
        return cls(
            id=str(value["id"]),
            title=str(value["title"]),
            author=str(value["author"]),
            description=str(value.get("description", "")),
            release=str(value.get("release", __version__)),
            requester_attribution=dict(value.get("requester_attribution", {})),
            tags=tuple(value.get("tags", ())),
        )


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]
    metrics: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "metrics": dict(self.metrics),
        }


@dataclass
class SpatialEvidenceProject:
    metadata: ProjectMetadata
    capture_profiles: tuple[CaptureProfile, ...]
    supports: SupportRegistry
    compatibility_policies: tuple[CompatibilityPolicy, ...]
    verification_policy: VerificationPolicy = field(default_factory=VerificationPolicy)
    route_policies: tuple[RoutePolicy, ...] = (RoutePolicy(),)
    voxel_profile: VoxelKeyProfile = field(default_factory=VoxelKeyProfile)
    ray_profile: RayKeyProfile = field(default_factory=RayKeyProfile)
    initial_map: MapState = field(default_factory=MapState)
    schema: str = __schema__
    android_implementation_status: str = "deferred"

    def __post_init__(self) -> None:
        self.capture_profiles = tuple(self.capture_profiles)
        self.compatibility_policies = tuple(self.compatibility_policies)
        self.route_policies = tuple(self.route_policies)
        if self.schema != __schema__:
            raise ValueError(f"unsupported project schema: {self.schema}")
        if self.android_implementation_status not in {"deferred", "reference_only"}:
            raise ValueError("4.0 Android status must remain deferred/reference_only")

    def _unique_map(self, values: tuple[Any, ...], label: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for value in values:
            if value.id in result:
                raise ValueError(f"duplicate {label} id: {value.id}")
            result[value.id] = value
        return result

    @property
    def capture_profile_map(self) -> dict[str, CaptureProfile]:
        return self._unique_map(self.capture_profiles, "capture profile")

    @property
    def compatibility_policy_map(self) -> dict[str, CompatibilityPolicy]:
        return self._unique_map(self.compatibility_policies, "compatibility policy")

    @property
    def route_policy_map(self) -> dict[str, RoutePolicy]:
        return self._unique_map(self.route_policies, "route policy")

    def validate(self, *, raise_on_error: bool = False) -> ValidationReport:
        issues: list[ValidationIssue] = []
        try:
            profiles = self.capture_profile_map
        except ValueError as exc:
            profiles = {}
            issues.append(ValidationIssue("error", "capture_profile.duplicate", "capture_profiles", str(exc)))
        try:
            compatibility = self.compatibility_policy_map
        except ValueError as exc:
            compatibility = {}
            issues.append(ValidationIssue("error", "compatibility.duplicate", "compatibility_policies", str(exc)))
        try:
            route_policies = self.route_policy_map
        except ValueError as exc:
            route_policies = {}
            issues.append(ValidationIssue("error", "route_policy.duplicate", "route_policies", str(exc)))

        if not profiles:
            issues.append(ValidationIssue("error", "capture_profile.missing", "capture_profiles", "at least one capture profile is required"))
        if not self.supports.supports:
            issues.append(ValidationIssue("error", "support.missing", "supports", "at least one support volume is required"))
        if "default" not in compatibility:
            issues.append(ValidationIssue("error", "compatibility.default_missing", "compatibility_policies", "default policy is required"))
        if not route_policies:
            issues.append(ValidationIssue("error", "route_policy.missing", "route_policies", "at least one route policy is required"))
        if self.verification_policy.require_source_hash and not self.verification_policy.accepted_guard_statuses:
            issues.append(ValidationIssue("error", "verification.guard_empty", "verification_policy", "accepted guard statuses cannot be empty"))
        if not any(profile.metric_ready for profile in profiles.values()):
            issues.append(ValidationIssue("warning", "scale.no_metric_profile", "capture_profiles", "no profile provides metric-ready scale"))
        for issue in validate_route_topology(self.initial_map):
            issues.append(ValidationIssue("error", "topology.invalid", "initial_map", issue))

        metrics = {
            "capture_profile_count": len(profiles),
            "metric_ready_profiles": sum(profile.metric_ready for profile in profiles.values()),
            "support_count": len(self.supports.supports),
            "compatibility_policy_count": len(compatibility),
            "route_policy_count": len(route_policies),
            "initial_node_count": len(self.initial_map.nodes),
            "initial_edge_count": len(self.initial_map.edges),
            "android_implementation_status": self.android_implementation_status,
            "mechanism_range": "M450-M509",
        }
        report = ValidationReport(tuple(issues), metrics)
        if raise_on_error and not report.passed:
            raise ValueError("project validation failed: " + "; ".join(issue.message for issue in issues if issue.severity == "error"))
        return report

    def instantiate_ledger(self) -> SpatialLedger:
        self.validate(raise_on_error=True)
        return SpatialLedger(self.initial_map, self.capture_profile_map)

    def make_verifier(self) -> ProposalVerifier:
        return ProposalVerifier(self.supports, self.compatibility_policy_map, self.verification_policy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": "spatial_evidence_schema_4_0.json",
            "schema": self.schema,
            "metadata": self.metadata.to_dict(),
            "capture_profiles": [profile.to_dict() for profile in sorted(self.capture_profiles, key=lambda item: item.id)],
            "supports": self.supports.to_dict(),
            "compatibility_policies": [policy.to_dict() for policy in sorted(self.compatibility_policies, key=lambda item: item.id)],
            "verification_policy": self.verification_policy.to_dict(),
            "route_policies": [policy.to_dict() for policy in sorted(self.route_policies, key=lambda item: item.id)],
            "voxel_profile": self.voxel_profile.to_dict(),
            "ray_profile": self.ray_profile.to_dict(),
            "initial_map": self.initial_map.to_dict(),
            "android_implementation_status": self.android_implementation_status,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpatialEvidenceProject":
        return cls(
            metadata=ProjectMetadata.from_dict(value["metadata"]),
            capture_profiles=tuple(CaptureProfile.from_dict(item) for item in value.get("capture_profiles", ())),
            supports=SupportRegistry.from_dict(list(value.get("supports", ()))),
            compatibility_policies=tuple(CompatibilityPolicy.from_dict(item) for item in value.get("compatibility_policies", ())),
            verification_policy=VerificationPolicy.from_dict(value.get("verification_policy", {})),
            route_policies=tuple(RoutePolicy.from_dict(item) for item in value.get("route_policies", ({},))),
            voxel_profile=VoxelKeyProfile.from_dict(value.get("voxel_profile", {})),
            ray_profile=RayKeyProfile.from_dict(value.get("ray_profile", {})),
            initial_map=MapState.from_dict(value.get("initial_map", {})),
            schema=str(value.get("schema", __schema__)),
            android_implementation_status=str(value.get("android_implementation_status", "deferred")),
        )

    def content_hash(self) -> str:
        return content_hash(self.to_dict())

    def write(self, path: str | Path) -> Path:
        self.validate(raise_on_error=True)
        return write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: str | Path, *, validate: bool = True) -> "SpatialEvidenceProject":
        project = cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        if validate:
            project.validate(raise_on_error=True)
        return project
