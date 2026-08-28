"""Canonical JSON, GeoJSON and self-contained offline spatial reports."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import write_json
from .change import ChangeCandidate
from .ledger import SpatialLedger
from .model import MapState
from .project import SpatialEvidenceProject
from .topology import RouteResult


def map_to_geojson(state: MapState) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for node_id in sorted(state.nodes):
        node = state.nodes[node_id]
        x, y, z = node.pose.position
        features.append({
            "type": "Feature",
            "id": node.id,
            "geometry": {"type": "Point", "coordinates": [x, z, y]},
            "properties": {
                "entity_type": "node",
                "kind": node.kind,
                "state": dict(node.state),
                "semantic": dict(node.semantic),
                "uncertainty_m": node.uncertainty.position_bound(),
                "revision": node.revision,
                "evidence_ids": list(node.evidence_ids),
                "lineage": list(node.lineage),
            },
        })
    for edge_id in sorted(state.edges):
        edge = state.edges[edge_id]
        source = state.nodes[edge.source].pose.position
        target = state.nodes[edge.target].pose.position
        features.append({
            "type": "Feature",
            "id": edge.id,
            "geometry": {
                "type": "LineString",
                "coordinates": [[source[0], source[2], source[1]], [target[0], target[2], target[1]]],
            },
            "properties": {
                "entity_type": "edge",
                "kind": edge.kind,
                "source": edge.source,
                "target": edge.target,
                "directed": edge.directed,
                "state": dict(edge.state),
                "metrics": dict(edge.metrics),
                "revision": edge.revision,
                "evidence_ids": list(edge.evidence_ids),
                "lineage": list(edge.lineage),
            },
        })
    return {
        "type": "FeatureCollection",
        "name": "UGTS-KC 4.0 Spatial Evidence Map",
        "features": features,
        "ugts_state_hash": state.state_hash(),
    }


def write_geojson(path: str | Path, state: MapState) -> Path:
    return write_json(path, map_to_geojson(state))


def _plan_svg(state: MapState, routes: Mapping[str, RouteResult]) -> str:
    width, height, pad = 900.0, 520.0, 60.0
    if state.nodes:
        xs = [node.pose.position[0] for node in state.nodes.values()]
        zs = [node.pose.position[2] for node in state.nodes.values()]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
    else:
        min_x = min_z = 0.0
        max_x = max_z = 1.0
    if max_x - min_x < 1e-9:
        max_x = min_x + 1.0
    if max_z - min_z < 1e-9:
        max_z = min_z + 1.0
    scale = min((width - 2 * pad) / (max_x - min_x), (height - 2 * pad) / (max_z - min_z))

    def point(node_id: str) -> tuple[float, float]:
        x, _, z = state.nodes[node_id].pose.position
        return pad + (x - min_x) * scale, height - pad - (z - min_z) * scale

    route_edges: dict[str, str] = {}
    for name, result in routes.items():
        if result.found:
            for edge_id in result.edge_path:
                route_edges[edge_id] = name

    parts = [f'<svg class="plan" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="Topological route map">']
    parts.append('<rect x="0" y="0" width="900" height="520" rx="18" class="plan-bg"/>')
    for edge_id in sorted(state.edges):
        edge = state.edges[edge_id]
        if edge.kind != "route":
            continue
        x1, y1 = point(edge.source)
        x2, y2 = point(edge.target)
        status = str(edge.state.get("status", "unknown"))
        classes = ["route-edge", f"status-{escape(status)}"]
        if edge_id in route_edges:
            classes.append("selected-route")
        title = f"{edge.id}: {status}; length {edge.metrics.get('length_m', '?')} m; clearance {edge.metrics.get('clearance_m', '?')} m"
        parts.append(
            f'<g><title>{escape(title)}</title><line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{" ".join(classes)}"/></g>'
        )
    for node_id in sorted(state.nodes):
        node = state.nodes[node_id]
        x, y = point(node_id)
        kind = escape(node.kind)
        label = escape(str(node.semantic.get("label", node.id)))
        parts.append(f'<g class="map-node kind-{kind}"><title>{escape(node.id)} ({kind})</title><circle cx="{x:.1f}" cy="{y:.1f}" r="11"/><text x="{x:.1f}" y="{y - 17:.1f}">{label}</text></g>')
    parts.append('</svg>')
    return "".join(parts)


def build_offline_html(
    project: SpatialEvidenceProject,
    ledger: SpatialLedger,
    output: str | Path,
    *,
    routes: Mapping[str, RouteResult] | None = None,
    changes: Iterable[ChangeCandidate] = (),
    title: str | None = None,
) -> Path:
    routes = dict(routes or {})
    changes = tuple(changes)
    title = title or f"{project.metadata.title} - Spatial Evidence Report"
    embedded = {
        "project": project.to_dict(),
        "project_hash": project.content_hash(),
        "ledger": ledger.to_dict(),
        "routes": {name: result.to_dict() for name, result in sorted(routes.items())},
        "changes": [item.to_dict() for item in changes],
        "geojson": map_to_geojson(ledger.map_state),
    }
    data_json = json.dumps(embedded, sort_keys=True, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    plan = _plan_svg(ledger.map_state, routes)

    route_rows = []
    for name, result in sorted(routes.items()):
        route_rows.append(
            "<tr>"
            f"<td>{escape(name)}</td><td>{'FOUND' if result.found else 'NOT FOUND'}</td>"
            f"<td>{escape(' -> '.join(result.node_path) if result.node_path else result.reason)}</td>"
            f"<td>{'' if not result.found else f'{result.cost:.3f}'}</td>"
            "</tr>"
        )
    change_rows = []
    for item in changes:
        interval = ""
        if item.value_interval is not None:
            interval = f"[{item.value_interval.lower:.3f}, {item.value_interval.upper:.3f}]"
        change_rows.append(
            "<tr>"
            f"<td>{escape(item.kind)}</td><td>{escape(item.entity_type)}</td><td>{escape(item.target_id)}</td>"
            f"<td>{'verified' if item.verified else 'review'}</td><td>{escape(interval)}</td><td>{escape(item.reason)}</td>"
            "</tr>"
        )
    event_rows = []
    for event in ledger.events:
        event_rows.append(
            "<tr>"
            f"<td>{event.sequence}</td><td>{event.event_time:.3f}</td><td>{escape(event.event_type)}</td>"
            f"<td>{escape(event.target_id)}</td><td>{escape(event.source)}</td><td>{event.confidence:.3f}</td>"
            f"<td><code>{escape(event.post_hash[:12])}</code></td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{ color-scheme: dark; --bg:#07101f; --panel:#101b31; --line:#2d426a; --text:#e7eefc; --muted:#9fb0cf; --cyan:#4de1da; --gold:#f5c95d; --red:#ff7b7b; --green:#6be39d; }}
* {{ box-sizing:border-box; }} body {{ margin:0; font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif; background:radial-gradient(circle at top,#142441 0,#07101f 55%); color:var(--text); }}
header,main {{ max-width:1180px; margin:auto; padding:28px; }} header h1 {{ margin:0 0 6px; font-size:clamp(26px,4vw,48px); }} header p {{ color:var(--muted); max-width:900px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin:20px 0; }} .card,section {{ background:rgba(16,27,49,.94); border:1px solid var(--line); border-radius:16px; padding:18px; box-shadow:0 12px 32px #0006; }}
.card strong {{ display:block; color:var(--cyan); font-size:26px; }} h2 {{ margin-top:0; }} table {{ width:100%; border-collapse:collapse; font-size:13px; }} th,td {{ text-align:left; padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; }} th {{ color:var(--cyan); }} code {{ color:var(--gold); }}
.plan {{ width:100%; height:auto; }} .plan-bg {{ fill:#081426; stroke:#2d426a; }} .route-edge {{ stroke:#7f91b5; stroke-width:6; opacity:.75; }} .status-blocked,.status-closed {{ stroke:var(--red); stroke-dasharray:12 8; }} .status-unknown {{ stroke:var(--gold); stroke-dasharray:4 8; }} .status-passable,.status-open {{ stroke:var(--green); }} .selected-route {{ stroke:var(--cyan); stroke-width:10; opacity:1; }} .map-node circle {{ fill:#182b4c; stroke:var(--cyan); stroke-width:3; }} .map-node text {{ fill:var(--text); font-size:13px; text-anchor:middle; paint-order:stroke; stroke:#07101f; stroke-width:4px; }}
.notice {{ border-left:5px solid var(--gold); }} footer {{ color:var(--muted); text-align:center; padding:30px; }} button {{ background:#1a335a; border:1px solid var(--cyan); color:var(--text); border-radius:10px; padding:9px 12px; cursor:pointer; }}
@media (max-width:700px) {{ header,main {{ padding:18px; }} table {{ display:block; overflow:auto; white-space:nowrap; }} }}
</style>
</head>
<body>
<header>
<h1>{escape(title)}</h1>
<p>Offline, self-contained UGTS-KC 4.0 report. Geometry, topology, uncertainty and event lineage are embedded below. The report is descriptive evidence, not a structural-safety or medical certification.</p>
</header>
<main>
<div class="grid">
<div class="card"><span>Map nodes</span><strong>{len(ledger.map_state.nodes)}</strong></div>
<div class="card"><span>Map edges</span><strong>{len(ledger.map_state.edges)}</strong></div>
<div class="card"><span>Committed events</span><strong>{len(ledger.events)}</strong></div>
<div class="card"><span>Change candidates</span><strong>{len(changes)}</strong></div>
</div>
<section><h2>Topological plan</h2>{plan}</section>
<section><h2>Route queries</h2><table><thead><tr><th>Name</th><th>Status</th><th>Path or reason</th><th>Cost</th></tr></thead><tbody>{''.join(route_rows) or '<tr><td colspan="4">No route query embedded.</td></tr>'}</tbody></table></section>
<section><h2>Change ledger</h2><table><thead><tr><th>Kind</th><th>Entity</th><th>Target</th><th>Decision</th><th>Interval</th><th>Reason</th></tr></thead><tbody>{''.join(change_rows) or '<tr><td colspan="6">No change candidates embedded.</td></tr>'}</tbody></table></section>
<section><h2>Committed events</h2><table><thead><tr><th>Seq</th><th>Time</th><th>Type</th><th>Target</th><th>Source</th><th>Confidence</th><th>Post hash</th></tr></thead><tbody>{''.join(event_rows) or '<tr><td colspan="7">No events committed.</td></tr>'}</tbody></table></section>
<section class="notice"><h2>Integrity and scope</h2><p>Project hash: <code>{project.content_hash()}</code><br>Map state hash: <code>{ledger.state_hash()}</code><br>Event stream hash: <code>{ledger.event_stream_hash()}</code></p><p>Android implementation is deferred in 4.0. The attached 3.9.1 NativeActivity/GLES3 implementation remains a frozen reference for later device-specific work.</p><button id="save-json">Save embedded JSON</button></section>
</main>
<footer>UGTS-KC 4.0 Spatial Evidence Ledger - generated without external runtime assets.</footer>
<script id="ugts-data" type="application/json">{data_json}</script>
<script>
(() => {{
 const button=document.getElementById('save-json');
 button.addEventListener('click',()=>{{
   const text=document.getElementById('ugts-data').textContent;
   const blob=new Blob([JSON.stringify(JSON.parse(text),null,2)],{{type:'application/json'}});
   const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download='ugts-spatial-evidence.json'; link.click();
   setTimeout(()=>URL.revokeObjectURL(link.href),1000);
 }});
}})();
</script>
</body>
</html>
"""
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target
