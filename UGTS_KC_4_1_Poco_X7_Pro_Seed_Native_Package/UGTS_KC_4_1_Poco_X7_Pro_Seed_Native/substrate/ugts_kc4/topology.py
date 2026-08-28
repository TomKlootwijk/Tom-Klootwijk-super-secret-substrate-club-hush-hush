"""Route topology, accessibility guards and deterministic path queries."""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Any, Mapping

from .model import MapEdge, MapState

_ROUTE_STATUSES = {"passable", "open", "blocked", "closed", "unknown", "restricted"}


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    id: str = "accessible-default"
    min_clearance_m: float = 0.90
    max_slope_deg: float = 6.0
    min_confidence: float = 0.75
    max_uncertainty_m: float = 0.20
    allow_unknown: bool = False
    allowed_statuses: tuple[str, ...] = ("passable", "open")
    unknown_penalty: float = 10.0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("route policy id is required")
        values = (
            float(self.min_clearance_m), float(self.max_slope_deg), float(self.min_confidence),
            float(self.max_uncertainty_m), float(self.unknown_penalty),
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("route policy values must be finite")
        if self.min_clearance_m < 0 or self.max_slope_deg < 0 or self.max_uncertainty_m < 0 or self.unknown_penalty < 0:
            raise ValueError("route policy limits must be non-negative")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("route min_confidence must be in [0,1]")
        object.__setattr__(self, "min_clearance_m", values[0])
        object.__setattr__(self, "max_slope_deg", values[1])
        object.__setattr__(self, "min_confidence", values[2])
        object.__setattr__(self, "max_uncertainty_m", values[3])
        object.__setattr__(self, "unknown_penalty", values[4])
        object.__setattr__(self, "allowed_statuses", tuple(sorted(set(map(str, self.allowed_statuses)))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "min_clearance_m": self.min_clearance_m,
            "max_slope_deg": self.max_slope_deg,
            "min_confidence": self.min_confidence,
            "max_uncertainty_m": self.max_uncertainty_m,
            "allow_unknown": self.allow_unknown,
            "allowed_statuses": list(self.allowed_statuses),
            "unknown_penalty": self.unknown_penalty,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RoutePolicy":
        return cls(
            id=str(value.get("id", "accessible-default")),
            min_clearance_m=float(value.get("min_clearance_m", 0.90)),
            max_slope_deg=float(value.get("max_slope_deg", 6.0)),
            min_confidence=float(value.get("min_confidence", 0.75)),
            max_uncertainty_m=float(value.get("max_uncertainty_m", 0.20)),
            allow_unknown=bool(value.get("allow_unknown", False)),
            allowed_statuses=tuple(value.get("allowed_statuses", ("passable", "open"))),
            unknown_penalty=float(value.get("unknown_penalty", 10.0)),
        )


@dataclass(frozen=True, slots=True)
class EdgeAdmission:
    admitted: bool
    reasons: tuple[str, ...]
    cost: float
    status: str
    clearance_interval: tuple[float, float]
    slope_interval: tuple[float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "reasons": list(self.reasons),
            "cost": self.cost,
            "status": self.status,
            "clearance_interval": list(self.clearance_interval),
            "slope_interval": list(self.slope_interval),
        }


def evaluate_route_edge(edge: MapEdge, policy: RoutePolicy) -> EdgeAdmission:
    reasons: list[str] = []
    status = str(edge.state.get("status", "unknown"))
    if status not in _ROUTE_STATUSES:
        reasons.append(f"status_invalid:{status}")
    elif status == "unknown":
        if not policy.allow_unknown:
            reasons.append("status_unknown")
    elif status not in policy.allowed_statuses:
        reasons.append(f"status_not_allowed:{status}")

    clearance = float(edge.metrics.get("clearance_m", math.inf))
    clearance_error = abs(float(edge.metrics.get("clearance_error_m", 0.0)))
    clearance_interval = (clearance - clearance_error, clearance + clearance_error)
    if clearance_interval[0] < policy.min_clearance_m:
        reasons.append("clearance_below_minimum")

    slope = abs(float(edge.metrics.get("slope_deg", 0.0)))
    slope_error = abs(float(edge.metrics.get("slope_error_deg", 0.0)))
    slope_interval = (max(0.0, slope - slope_error), slope + slope_error)
    if slope_interval[1] > policy.max_slope_deg:
        reasons.append("slope_above_maximum")

    confidence = float(edge.metrics.get("confidence", edge.state.get("confidence", 1.0)))
    if confidence < policy.min_confidence:
        reasons.append("confidence_below_minimum")

    uncertainty = abs(float(edge.metrics.get("uncertainty_m", 0.0)))
    if uncertainty > policy.max_uncertainty_m:
        reasons.append("uncertainty_above_maximum")

    length = float(edge.metrics.get("length_m", 1.0))
    if not math.isfinite(length) or length <= 0:
        reasons.append("length_invalid")
        length = math.inf
    risk = uncertainty + max(0.0, policy.min_confidence - confidence) * length
    cost = length + risk
    if status == "unknown" and policy.allow_unknown:
        cost += policy.unknown_penalty
    return EdgeAdmission(not reasons, tuple(reasons), cost, status, clearance_interval, slope_interval)


@dataclass(frozen=True, slots=True)
class RouteResult:
    found: bool
    start: str
    goal: str
    node_path: tuple[str, ...] = ()
    edge_path: tuple[str, ...] = ()
    cost: float = math.inf
    rejected_edges: tuple[tuple[str, tuple[str, ...]], ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "start": self.start,
            "goal": self.goal,
            "node_path": list(self.node_path),
            "edge_path": list(self.edge_path),
            "cost": self.cost if math.isfinite(self.cost) else None,
            "rejected_edges": {edge_id: list(reasons) for edge_id, reasons in self.rejected_edges},
            "reason": self.reason,
        }


class RouteGraph:
    def __init__(self, state: MapState):
        self.state = state
        self._adjacency: dict[str, list[tuple[str, MapEdge]]] = {node_id: [] for node_id in state.nodes}
        for edge in state.route_edges():
            self._adjacency[edge.source].append((edge.target, edge))
            if not edge.directed:
                self._adjacency[edge.target].append((edge.source, edge))
        for node_id in self._adjacency:
            self._adjacency[node_id].sort(key=lambda item: (item[1].id, item[0]))

    def shortest_path(self, start: str, goal: str, policy: RoutePolicy | None = None) -> RouteResult:
        policy = policy or RoutePolicy()
        if start not in self.state.nodes:
            return RouteResult(False, start, goal, reason="start_unknown")
        if goal not in self.state.nodes:
            return RouteResult(False, start, goal, reason="goal_unknown")
        if start == goal:
            return RouteResult(True, start, goal, (start,), (), 0.0, reason="same_node")

        rejected: dict[str, tuple[str, ...]] = {}
        queue: list[tuple[float, tuple[str, ...], str]] = [(0.0, (start,), start)]
        best: dict[str, tuple[float, tuple[str, ...]]] = {start: (0.0, (start,))}
        previous: dict[str, tuple[str, str]] = {}

        while queue:
            cost, signature, node_id = heapq.heappop(queue)
            if best.get(node_id) != (cost, signature):
                continue
            if node_id == goal:
                break
            for neighbor, edge in self._adjacency.get(node_id, ()):  # deterministic order prepared above
                admission = evaluate_route_edge(edge, policy)
                if not admission.admitted:
                    rejected.setdefault(edge.id, admission.reasons)
                    continue
                candidate_cost = cost + admission.cost
                candidate_signature = signature + (edge.id, neighbor)
                prior = best.get(neighbor)
                if prior is None or (candidate_cost, candidate_signature) < prior:
                    best[neighbor] = (candidate_cost, candidate_signature)
                    previous[neighbor] = (node_id, edge.id)
                    heapq.heappush(queue, (candidate_cost, candidate_signature, neighbor))

        if goal not in best:
            return RouteResult(
                False, start, goal, rejected_edges=tuple(sorted(rejected.items())),
                reason="no_admissible_route",
            )

        nodes = [goal]
        edges = []
        cursor = goal
        while cursor != start:
            parent, edge_id = previous[cursor]
            edges.append(edge_id)
            nodes.append(parent)
            cursor = parent
        nodes.reverse()
        edges.reverse()
        return RouteResult(
            True, start, goal, tuple(nodes), tuple(edges), best[goal][0],
            tuple(sorted(rejected.items())), reason="ok",
        )

    def connected_components(self, policy: RoutePolicy | None = None) -> tuple[tuple[str, ...], ...]:
        policy = policy or RoutePolicy()
        remaining = set(self.state.nodes)
        components: list[tuple[str, ...]] = []
        while remaining:
            start = min(remaining)
            stack = [start]
            seen = {start}
            while stack:
                node = stack.pop()
                for neighbor, edge in self._adjacency.get(node, ()):  # pragma: no branch - tiny loop
                    if neighbor in seen or not evaluate_route_edge(edge, policy).admitted:
                        continue
                    seen.add(neighbor)
                    stack.append(neighbor)
            remaining -= seen
            components.append(tuple(sorted(seen)))
        return tuple(sorted(components))


def validate_route_topology(state: MapState) -> tuple[str, ...]:
    issues: list[str] = []
    for edge in state.route_edges():
        status = str(edge.state.get("status", "unknown"))
        if status not in _ROUTE_STATUSES:
            issues.append(f"edge:{edge.id}:invalid_status:{status}")
        length = edge.metrics.get("length_m")
        if length is None or not math.isfinite(float(length)) or float(length) <= 0:
            issues.append(f"edge:{edge.id}:invalid_length")
        clearance = edge.metrics.get("clearance_m")
        if clearance is not None and float(clearance) < 0:
            issues.append(f"edge:{edge.id}:negative_clearance")
    portal_nodes = [node for node in state.nodes.values() if node.kind == "portal"]
    route_degree = {node.id: 0 for node in portal_nodes}
    for edge in state.route_edges():
        if edge.source in route_degree:
            route_degree[edge.source] += 1
        if edge.target in route_degree:
            route_degree[edge.target] += 1
    for node_id, degree in route_degree.items():
        if degree == 0:
            issues.append(f"portal:{node_id}:isolated")
    return tuple(sorted(issues))
