"""Checked-in SafeRoute + DamageDelta reference project and demonstration."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from .canonical import write_json
from .change import ChangePolicy, detect_changes
from .export import build_offline_html, write_geojson
from .ledger import SpatialLedger
from .model import (
    CaptureProfile, MapEdge, MapNode, MapPatch, MapState, Observation, Pose3D,
    Uncertainty3D,
)
from .project import ProjectMetadata, SpatialEvidenceProject
from .support import AABBSupport, CompatibilityPolicy, SupportRegistry
from .topology import RouteGraph, RoutePolicy
from .verify import EventProposal, VerificationPolicy


def _sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def safe_route_demo_project(author: str = "Tom Klootwijk") -> SpatialEvidenceProject:
    profile = CaptureProfile(
        id="capture:phone-video-anchored-v1",
        device_family="Android phone reference capture",
        camera_model="monocular-video-plus-optional-imu",
        calibration_hash=_sha("UGTS-KC-4.0-demo-camera-calibration"),
        scale_mode="anchored",
        scale_anchor_id="anchor:doorway-width-1m",
        units_per_meter=1.0,
        coordinate_frame="right-handed-y-up-xz-floor",
        timestamp_unit="seconds",
        model_versions=(
            ("depth", "distilled-depth-v1"),
            ("topology", "spatial-topology-head-v1"),
            ("uncertainty", "calibrated-interval-head-v1"),
        ),
        privacy_policy="local_only",
    )
    verification = VerificationPolicy(
        id="safe-route-verification-v1",
        confidence_floor=0.80,
        max_numeric_error=0.04,
        event_margin=0.05,
        max_position_uncertainty=0.20,
        kind_uncertainty_limits=(("doorway", 0.08), ("route_edge", 0.12), ("object", 0.20)),
        metric_required_kinds=("doorway", "route_edge", "clearance", "measurement"),
        require_source_hash=True,
    )
    route_policy = RoutePolicy(
        id="wheelchair-reference",
        min_clearance_m=0.90,
        max_slope_deg=6.0,
        min_confidence=0.80,
        max_uncertainty_m=0.15,
        allow_unknown=False,
    )
    return SpatialEvidenceProject(
        metadata=ProjectMetadata(
            id="ugts:kc:4.0:demo:safe-route-delta",
            title="SafeRoute and DamageDelta Spatial Evidence Demo",
            author=author,
            description="Synthetic indoor route graph with a repeat-scan blockage and moved object.",
            requester_attribution={
                "name": "Tom Klootwijk",
                "identifier": "NL200678942",
                "date_of_birth": "10-07-1990",
                "status": "requester-supplied-unverified",
                "substrate_attribution": "Kees Klootwijk (KC edition), requester supplied",
            },
            tags=("spatial-evidence", "accessibility", "repeat-scan", "offline"),
        ),
        capture_profiles=(profile,),
        supports=SupportRegistry({
            "scan-volume": AABBSupport("scan-volume", (-2.0, -1.0, -2.0), (15.0, 4.0, 7.0)),
        }),
        compatibility_policies=(
            CompatibilityPolicy("default", allowed_dynamic_states=("static", "movable", "unknown")),
        ),
        verification_policy=verification,
        route_policies=(route_policy,),
        initial_map=MapState(metadata={
            "site_id": "demo-building-a",
            "floor_id": "F0",
            "authority": "verified-event-ledger",
            "geometry_role": "descriptive-reference",
        }),
        android_implementation_status="deferred",
    )


def _observation(
    observation_id: str,
    kind: str,
    position: tuple[float, float, float],
    timestamp: float,
    *,
    dynamic_state: str = "static",
    semantic: dict[str, Any] | None = None,
    confidence: float = 0.96,
    max_error: float = 0.03,
    scale_required: bool = False,
) -> Observation:
    return Observation(
        id=observation_id,
        capture_profile_id="capture:phone-video-anchored-v1",
        frame_id=f"keyframe:{int(timestamp * 10):04d}",
        timestamp=timestamp,
        kind=kind,
        pose=Pose3D(position),
        uncertainty=Uncertainty3D((0.005, 0.005, 0.005), 0.95, max_error=max_error),
        confidence=confidence,
        guard_status="confirmed",
        relation_value=0.0,
        numeric_error=0.01,
        support_id="scan-volume",
        compatibility_policy_id="default",
        compatibility_tags=("floor:F0", "evidence:synthetic-demo"),
        semantic=semantic or {},
        source_model="distilled-spatial-transformer-reference-v1",
        source_hash=_sha("distilled-spatial-transformer-reference-v1"),
        definition_hashes=(_sha("ugts-kc-4.0-observation-definition"),),
        scale_required=scale_required,
        dynamic_state=dynamic_state,
        floor_id="F0",
        evidence_uri=f"evidence://demo/{observation_id}",
    )


def _node_proposal(node: MapNode, timestamp: float, *, source: str = "phone-A", event_type: str = "node_observed", priority: int = 10) -> EventProposal:
    observation_kind = "doorway" if node.kind == "portal" else ("object" if node.kind in {"object", "obstacle"} else node.kind)
    observation = _observation(
        f"obs:{node.id}:{timestamp:.1f}", observation_kind, node.pose.position, timestamp,
        dynamic_state="movable" if node.kind == "object" else "static",
        semantic={"target_id": node.id, "node_kind": node.kind},
        scale_required=node.kind == "portal",
    )
    return EventProposal(
        id=f"proposal:{event_type}:{node.id}:{timestamp:.1f}",
        event_time=timestamp,
        event_type=event_type,
        target_id=node.id,
        observation=observation,
        patch=MapPatch("upsert_node", node.id, {"node": node.to_dict()}),
        source=source,
        priority=priority,
        lineage_label="baseline-observation",
    )


def _edge_midpoint(edge: MapEdge, nodes: dict[str, MapNode]) -> tuple[float, float, float]:
    a = nodes[edge.source].pose.position
    b = nodes[edge.target].pose.position
    return tuple((a[index] + b[index]) / 2.0 for index in range(3))  # type: ignore[return-value]


def _edge_proposal(edge: MapEdge, nodes: dict[str, MapNode], timestamp: float, *, source: str = "phone-A", event_type: str = "route_observed", priority: int = 8) -> EventProposal:
    position = _edge_midpoint(edge, nodes)
    observation = _observation(
        f"obs:{edge.id}:{timestamp:.1f}", "route_edge", position, timestamp,
        semantic={"target_id": edge.id, "edge_kind": edge.kind},
        scale_required=True,
        max_error=0.04,
    )
    return EventProposal(
        id=f"proposal:{event_type}:{edge.id}:{timestamp:.1f}",
        event_time=timestamp,
        event_type=event_type,
        target_id=edge.id,
        observation=observation,
        patch=MapPatch("upsert_edge", edge.id, {"edge": edge.to_dict()}),
        source=source,
        priority=priority,
        lineage_label="baseline-route-observation",
    )


def safe_route_baseline_proposals() -> tuple[EventProposal, ...]:
    nodes = {
        "N-ENTRANCE": MapNode("N-ENTRANCE", "waypoint", Pose3D((0.0, 0.0, 0.0)), semantic={"label": "Entrance"}, state={"status": "open", "present": True, "confidence": 0.99}),
        "N-JUNCTION": MapNode("N-JUNCTION", "waypoint", Pose3D((4.0, 0.0, 0.0)), semantic={"label": "Junction"}, state={"status": "open", "present": True, "confidence": 0.98}),
        "N-DOOR-MAIN": MapNode("N-DOOR-MAIN", "portal", Pose3D((8.0, 0.0, 0.0)), semantic={"label": "Main door", "width_m": 1.00}, state={"status": "open", "blocked": False, "present": True, "confidence": 0.98}),
        "N-EXIT": MapNode("N-EXIT", "waypoint", Pose3D((12.0, 0.0, 0.0)), semantic={"label": "Exit"}, state={"status": "open", "present": True, "confidence": 0.99}),
        "N-RAMP": MapNode("N-RAMP", "waypoint", Pose3D((6.0, 0.0, 4.0)), semantic={"label": "Ramp"}, state={"status": "open", "present": True, "confidence": 0.95}),
        "N-DOOR-ALT": MapNode("N-DOOR-ALT", "portal", Pose3D((10.0, 0.0, 4.0)), semantic={"label": "Alternate door", "width_m": 0.96}, state={"status": "open", "blocked": False, "present": True, "confidence": 0.96}),
        "N-CART": MapNode("N-CART", "object", Pose3D((5.0, 0.0, 1.5)), uncertainty=Uncertainty3D((0.01, 0.01, 0.01), max_error=0.03), semantic={"label": "Supply cart"}, state={"status": "parked", "present": True, "confidence": 0.93}),
    }
    def route(edge_id: str, source: str, target: str, length: float, clearance: float, slope: float = 0.0, confidence: float = 0.96) -> MapEdge:
        return MapEdge(
            edge_id, source, target, "route", False,
            state={"status": "passable", "confidence": confidence},
            metrics={
                "length_m": length,
                "clearance_m": clearance,
                "clearance_error_m": 0.02,
                "slope_deg": slope,
                "slope_error_deg": 0.5,
                "confidence": confidence,
                "uncertainty_m": 0.04,
            },
        )
    edges = (
        route("E-ENTRANCE-JUNCTION", "N-ENTRANCE", "N-JUNCTION", 4.0, 1.20),
        route("E-JUNCTION-MAIN", "N-JUNCTION", "N-DOOR-MAIN", 4.0, 1.00),
        route("E-MAIN-EXIT", "N-DOOR-MAIN", "N-EXIT", 4.0, 0.95),
        route("E-JUNCTION-RAMP", "N-JUNCTION", "N-RAMP", math.sqrt(20), 0.98, 4.0, 0.94),
        route("E-RAMP-ALT", "N-RAMP", "N-DOOR-ALT", 4.0, 0.96, 4.5, 0.94),
        route("E-ALT-EXIT", "N-DOOR-ALT", "N-EXIT", math.sqrt(20), 0.94, 1.0, 0.95),
    )
    proposals: list[EventProposal] = []
    timestamp = 1.0
    for node_id in sorted(nodes):
        proposals.append(_node_proposal(nodes[node_id], timestamp))
        timestamp += 0.1
    for edge in edges:
        proposals.append(_edge_proposal(edge, nodes, timestamp))
        timestamp += 0.1
    return tuple(proposals)


def safe_route_change_proposals() -> tuple[EventProposal, ...]:
    proposals: list[EventProposal] = []
    timestamp = 10.0
    door_observation = _observation(
        "obs:N-DOOR-MAIN:blockage", "doorway", (8.0, 0.0, 0.0), timestamp,
        semantic={"target_id": "N-DOOR-MAIN", "change": "blocked"}, scale_required=True,
    )
    proposals.append(EventProposal(
        "proposal:door-blocked:N-DOOR-MAIN", timestamp, "passability_changed", "N-DOOR-MAIN",
        door_observation, MapPatch("update_node_state", "N-DOOR-MAIN", {"status": "blocked", "blocked": True, "confidence": 0.98}),
        source="phone-B", priority=20, lineage_label="repeat-scan:blockage",
    ))
    timestamp += 0.1
    edge_observation = _observation(
        "obs:E-MAIN-EXIT:blockage", "route_edge", (10.0, 0.0, 0.0), timestamp,
        semantic={"target_id": "E-MAIN-EXIT", "change": "blocked"}, scale_required=True,
    )
    proposals.append(EventProposal(
        "proposal:route-blocked:E-MAIN-EXIT", timestamp, "route_state_changed", "E-MAIN-EXIT",
        edge_observation, MapPatch("update_edge_state", "E-MAIN-EXIT", {"status": "blocked", "confidence": 0.98}),
        source="phone-B", priority=20, lineage_label="repeat-scan:blockage",
    ))
    timestamp += 0.1
    cart_observation = _observation(
        "obs:N-CART:moved", "object", (5.8, 0.0, 1.5), timestamp,
        dynamic_state="movable", semantic={"target_id": "N-CART", "change": "moved"},
        confidence=0.94,
    )
    proposals.append(EventProposal(
        "proposal:object-moved:N-CART", timestamp, "object_moved", "N-CART",
        cart_observation,
        MapPatch("update_node_pose", "N-CART", {
            "pose": Pose3D((5.8, 0.0, 1.5)).to_dict(),
            "uncertainty": Uncertainty3D((0.01, 0.01, 0.01), max_error=0.03).to_dict(),
        }),
        source="phone-B", priority=12, lineage_label="repeat-scan:moved",
    ))
    timestamp += 0.1
    obstacle = MapNode(
        "N-OBSTACLE", "obstacle", Pose3D((10.0, 0.0, 0.3)),
        uncertainty=Uncertainty3D((0.01, 0.01, 0.01), max_error=0.04),
        semantic={"label": "Temporary obstruction"},
        state={"status": "present", "present": True, "confidence": 0.95},
    )
    obstacle_observation = _observation(
        "obs:N-OBSTACLE:added", "object", obstacle.pose.position, timestamp,
        semantic={"target_id": obstacle.id, "change": "added"}, confidence=0.95,
    )
    proposals.append(EventProposal(
        "proposal:object-added:N-OBSTACLE", timestamp, "object_added", obstacle.id,
        obstacle_observation, MapPatch("upsert_node", obstacle.id, {"node": obstacle.to_dict()}),
        source="phone-B", priority=12, lineage_label="repeat-scan:added",
    ))
    return tuple(proposals)


def run_safe_route_demo(output_dir: str | Path, author: str = "Tom Klootwijk") -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    project = safe_route_demo_project(author)
    project_path = project.write(output / "project.json")
    ledger = project.instantiate_ledger()
    verifier = project.make_verifier()

    baseline_result = ledger.commit(safe_route_baseline_proposals(), verifier)
    if baseline_result.rejected:
        raise RuntimeError(f"baseline demo proposals rejected: {baseline_result.rejected}")
    baseline_state = ledger.map_state.clone()
    route_policy = project.route_policy_map["wheelchair-reference"]
    route_before = RouteGraph(baseline_state).shortest_path("N-ENTRANCE", "N-EXIT", route_policy)
    checkpoint = ledger.checkpoint()
    baseline_ledger_path = ledger.write(output / "baseline_ledger.json")

    change_result = ledger.commit(safe_route_change_proposals(), verifier)
    if change_result.rejected:
        raise RuntimeError(f"change demo proposals rejected: {change_result.rejected}")
    route_after = RouteGraph(ledger.map_state).shortest_path("N-ENTRANCE", "N-EXIT", route_policy)
    changes = detect_changes(baseline_state, ledger.map_state, ChangePolicy())
    changed_ledger_path = ledger.write(output / "changed_ledger.json")
    geojson_path = write_geojson(output / "changed_map.geojson", ledger.map_state)
    route_path = write_json(output / "route_results.json", {"before": route_before.to_dict(), "after": route_after.to_dict()})
    change_path = write_json(output / "change_candidates.json", [item.to_dict() for item in changes])
    html_path = build_offline_html(
        project, ledger, output / "offline_report.html",
        routes={"before blockage": route_before, "after blockage": route_after},
        changes=changes,
        title="SafeRoute + DamageDelta - UGTS-KC 4.0 Demo",
    )
    replay = SpatialLedger.replay(project.initial_map, ledger.events, project.capture_profile_map)
    summary = {
        "schema": "ugts-kc-spatial-demo-summary-4.0",
        "project": str(project_path.name),
        "baseline_ledger": str(baseline_ledger_path.name),
        "changed_ledger": str(changed_ledger_path.name),
        "geojson": str(geojson_path.name),
        "offline_report": str(html_path.name),
        "route_results": str(route_path.name),
        "change_candidates": str(change_path.name),
        "baseline_events": baseline_result.accepted_count,
        "change_events": change_result.accepted_count,
        "total_events": ledger.sequence,
        "baseline_route": route_before.to_dict(),
        "changed_route": route_after.to_dict(),
        "verified_changes": sum(item.verified for item in changes),
        "change_count": len(changes),
        "checkpoint_sequence": checkpoint.sequence,
        "project_hash": project.content_hash(),
        "state_hash": ledger.state_hash(),
        "event_stream_hash": ledger.event_stream_hash(),
        "replay_success": replay.success,
        "replay_state_hash": replay.state.state_hash(),
        "android_implementation_status": project.android_implementation_status,
    }
    write_json(output / "demo_summary.json", summary)
    return summary
