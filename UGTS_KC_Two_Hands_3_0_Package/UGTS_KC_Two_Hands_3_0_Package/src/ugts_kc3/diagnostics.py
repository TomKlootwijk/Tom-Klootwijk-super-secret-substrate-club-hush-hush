"""Editor-facing inspection records and validation diagnostics."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable

from .runtime import KCRuntime, RuntimeEvent
from .scene import Scene


@dataclass(frozen=True)
class DiagnosticIssue:
    severity: str
    code: str
    subject: str
    message: str


@dataclass
class DiagnosticReport:
    issues: list[DiagnosticIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def add(self, severity: str, code: str, subject: str, message: str):
        self.issues.append(DiagnosticIssue(severity, code, subject, message))

    def to_dict(self):
        return {
            "passed": self.passed,
            "issues": [issue.__dict__ for issue in self.issues],
            "metrics": self.metrics,
        }

    def write(self, path: str | Path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def audit_scene(scene: Scene) -> DiagnosticReport:
    report = DiagnosticReport()
    try:
        scene.metadata.validate()
    except Exception as exc:
        report.add("error", "metadata_invalid", "scene", str(exc))
    try:
        scene._assert_acyclic()  # intentional internal audit hook
    except Exception as exc:
        report.add("error", "hierarchy_cycle", "scene", str(exc))
    referenced_assets = set()
    for node in scene.nodes.values():
        if node.asset_id is not None:
            referenced_assets.add(node.asset_id)
            if node.asset_id not in scene.assets:
                report.add("error", "missing_asset", node.id, node.asset_id)
        if node.parent_id is not None and node.parent_id not in scene.nodes:
            report.add("error", "missing_parent", node.id, node.parent_id)
    for asset in scene.assets.values():
        try:
            asset.validate()
        except Exception as exc:
            report.add("error", "asset_invalid", asset.id, str(exc))
        if asset.id not in referenced_assets:
            report.add("warning", "unreferenced_asset", asset.id, "asset is not instanced by a scene node")
    bounds = scene.scene_bounds()
    report.metrics.update(
        {
            "asset_count": len(scene.assets),
            "node_count": len(scene.nodes),
            "layer_count": len(scene.layers),
            "scene_hash": scene.content_hash(),
            "scene_bounds": None if bounds is None else {"minimum": bounds.minimum, "maximum": bounds.maximum},
        }
    )
    return report


def event_timeline(events: Iterable[RuntimeEvent]) -> list[dict[str, Any]]:
    return [
        {
            "sequence": e.sequence,
            "time": e.event_time,
            "type": e.event_type,
            "entity": e.entity_id,
            "source": e.source,
            "priority": e.priority,
            "lineage": e.lineage,
            "pre": e.pre_state_hash[:16],
            "post": e.post_state_hash[:16],
        }
        for e in sorted(events, key=lambda event: event.sequence)
    ]


def lineage_edges(events: Iterable[RuntimeEvent]) -> tuple[tuple[str, str], ...]:
    edges = []
    for event in events:
        lineage = list(event.lineage)
        for a, b in zip(lineage[:-1], lineage[1:]):
            edges.append((a, b))
    return tuple(sorted(set(edges)))


def runtime_report(runtime: KCRuntime) -> DiagnosticReport:
    report = audit_scene(runtime.scene)
    report.metrics.update(
        {
            "tick": runtime.tick,
            "time": runtime.time,
            "event_sequence": runtime.sequence,
            "event_count": len(runtime.events),
            "rejected_count": len(runtime.rejected),
            "runtime_metrics": runtime.metrics.__dict__,
            "timeline": event_timeline(runtime.events),
            "lineage_edges": lineage_edges(runtime.events),
        }
    )
    if runtime.metrics.conflicts:
        report.add("warning", "event_conflicts", "runtime", f"{runtime.metrics.conflicts} proposal conflicts were resolved")
    return report
