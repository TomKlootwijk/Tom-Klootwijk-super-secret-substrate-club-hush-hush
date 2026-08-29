from __future__ import annotations

from dataclasses import replace
import base64
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from ugts_kc3.templates import first_steps_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402
from ugts_kc3.webexport import build_html5  # noqa: E402


_NODE_HARNESS = r'''
const fs = require("fs");
const projectText = fs.readFileSync(process.argv[1], "utf8");
const runtimePath = process.argv[2];
const commands = Buffer.from(process.argv[3], "base64").toString("utf8");
const listeners = Object.create(null);
const listen = (kind, callback) => { (listeners[kind] ||= []).push(callback); };
globalThis.window = globalThis;
window.innerWidth = 960; window.innerHeight = 540; window.devicePixelRatio = 1;
window.addEventListener = listen;
globalThis.requestAnimationFrame = () => 0;
Object.defineProperty(globalThis, "navigator", {value: {maxTouchPoints: 0, getGamepads: () => []}, configurable: true});
const storage = new Map();
globalThis.localStorage = {
  getItem: key => storage.has(key) ? storage.get(key) : null,
  setItem: (key, value) => storage.set(key, String(value)),
};
const context = new Proxy({}, {get(target, key) { return key in target ? target[key] : (() => {}); }});
const canvasListeners = Object.create(null);
const canvas = {
  style: {}, width: 0, height: 0,
  getContext: () => context,
  getBoundingClientRect: () => ({left: 0, top: 0, width: 960, height: 540}),
  addEventListener: (kind, callback) => { (canvasListeners[kind] ||= []).push(callback); },
  setPointerCapture: () => {},
};
const status = {textContent: ""};
const touch = {hidden: true};
globalThis.document = {getElementById: id => id === "kc-project" ? {textContent: projectText} : id === "kc-canvas" ? canvas : id === "kc-status" ? status : touch};
require(runtimePath);
eval(commands);
'''


def _run_browser_js(output: Path, commands: str) -> dict:
    completed = subprocess.run(
        [
            shutil.which("node") or "node",
            "-e",
            _NODE_HARNESS,
            str(output / "project.json"),
            str(output / "kc-runtime.js"),
            base64.b64encode(commands.encode("utf-8")).decode("ascii"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(
            f"Node runtime failed:\n{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def _moved(entity, entity_id, position, tags, *, active=True, origin=False):
    components = {name: dict(value) for name, value in entity.components.items()}
    components["transform"] = {
        **components["transform"],
        "position": list(position),
    }
    if origin:
        # Cone axes are saved in world space. Neither field may affect a query.
        components["transform"]["rotation"] = math.pi
        components["transform"]["scale"] = [19.0, -7.0]
    return replace(
        entity,
        id=entity_id,
        components=components,
        tags=frozenset(tags),
        active=active,
        metadata={},
    )


def _install_world_graph(project, graph: VisualGraph, entities) -> None:
    scene = project.scenes[project.start_scene]
    project.scenes[scene.id] = replace(
        scene,
        entities=tuple(entities),
        rules={
            **scene.rules,
            "visual_graphs": [graph.to_dict()],
            "world_graphs": [graph.id],
        },
    )
    project.validate()


def _state_capture(query_ids: dict[str, tuple[str, ...]]):
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []
    for query_id, ports in query_ids.items():
        for port in ports:
            capture_id = f"save_{query_id}_{port}"
            key = f"{query_id}_{port}"
            nodes.append(GraphNode(capture_id, "action.set_state", {"key": key}))
            links.append(GraphLink("ready", "out", capture_id, "in"))
            links.append(GraphLink(query_id, port, capture_id, "value"))
    return nodes, links


class WebNearestInConeTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")

    def test_node_runtime_matches_f32_cone_boundaries_and_nearest_parity(self):
        project = first_steps_project("Browser Cone Query")
        scene = project.scenes[project.start_scene]
        source_player = next(entity for entity in scene.entities if entity.id == "player")
        source_collectible = next(
            entity for entity in scene.entities if entity.id == "first_collectible"
        )

        normal = 0.7071067690849304
        normalization_cone = [
            -148964.84375,
            -38.332176208496094,
            63.12776184082031,
            0.9999998807907104,
        ]
        entities = (
            _moved(source_player, "player", (0.0, 0.0), ("player",), origin=True),
            # Both candidates lie exactly on the inclusive 45-degree boundary.
            # Reverse authoring order makes the UTF-8 id tie-break observable.
            _moved(source_collectible, "zeta_boundary", (1.0, -1.0), ("goal",)),
            _moved(source_collectible, "alpha_boundary", (1.0, 1.0), ("goal",)),
            _moved(source_collectible, "closer_outside", (0.1, 0.2), ("goal",)),
            _moved(
                source_collectible,
                "closer_inactive",
                (0.01, 0.0),
                ("goal",),
                active=False,
            ),
            # This exact float32 case is accepted by the normalized dot/divide
            # schedule but rejected by the former squared-dot approximation.
            _moved(
                source_collectible,
                "normalization_boundary",
                (-83.24039459228516, 0.003091727616265416),
                ("decorative",),
            ),
            _moved(source_collectible, "apex", (0.0, 0.0), ("hazard",)),
            _moved(
                source_collectible,
                "inside_clamp_distance",
                (5.0e-7, 0.0),
                ("hazard",),
            ),
            _moved(
                source_collectible,
                "collectible_boundary",
                (1.0, 1.0),
                ("collectible",),
            ),
            # One float32 step outside 45 degrees, but closer than the included
            # boundary candidate, so a rounded comparison bug changes the id.
            _moved(
                source_collectible,
                "collectible_just_outside",
                (0.5, 0.5000000596046448),
                ("collectible",),
            ),
        )

        queries = (
            GraphNode(
                "boundary",
                "query.nearest_in_cone",
                {
                    "origin": "player",
                    "tag": "goal",
                    "radius": 2.0,
                    "cone": [1.0, 0.0, 0.0, normal],
                },
            ),
            GraphNode("normalization_cone", "value.constant", {"value": normalization_cone}),
            GraphNode(
                "normalization",
                "query.nearest_in_cone",
                {"origin": "player", "tag": "decorative", "radius": 100.0},
            ),
            GraphNode(
                "ulp_boundary",
                "query.nearest_in_cone",
                {
                    "origin": "player",
                    "tag": "collectible",
                    "radius": 2.0,
                    "cone": [1.0, 0.0, 0.0, normal],
                },
            ),
            GraphNode(
                "apex_positive",
                "query.nearest_in_cone",
                {
                    "origin": "player",
                    "tag": "hazard",
                    "radius": 0.0,
                    "cone": [1.0, 0.0, 0.0, normal],
                },
            ),
            GraphNode(
                "apex_zero",
                "query.nearest_in_cone",
                {
                    "origin": "player",
                    "tag": "hazard",
                    "radius": 0.0,
                    "cone": [1.0, 0.0, 0.0, 0.0],
                },
            ),
            GraphNode(
                "clamped_direction",
                "query.nearest_in_cone",
                {
                    "origin": "player",
                    "tag": "hazard",
                    "radius": 1.0e-6,
                    "cone": [1.0, 0.0, 0.0, 0.75],
                },
            ),
            GraphNode(
                "plain",
                "query.nearest_tag",
                {"origin": "player", "tag": "goal", "radius": 2.0},
            ),
            GraphNode(
                "full_sphere",
                "query.nearest_in_cone",
                {
                    "origin": "player",
                    "tag": "goal",
                    "radius": 2.0,
                    "cone": [1.0, 0.0, 0.0, -1.0],
                },
            ),
            GraphNode(
                "missing",
                "query.nearest_in_cone",
                {
                    "origin": "player",
                    "tag": "collectible",
                    "radius": 0.1,
                    "cone": [1.0, 0.0, 0.0, -1.0],
                },
            ),
        )
        captures = {
            "boundary": ("found", "entity", "distance"),
            "normalization": ("found", "entity", "distance"),
            "ulp_boundary": ("entity",),
            "apex_positive": ("found", "entity", "distance"),
            "apex_zero": ("found", "entity", "distance"),
            "clamped_direction": ("found", "entity", "distance"),
            "plain": ("found", "entity", "distance"),
            "full_sphere": ("found", "entity", "distance"),
            "missing": ("found", "entity", "distance"),
        }
        capture_nodes, capture_links = _state_capture(captures)
        graph = VisualGraph(
            "cone_web",
            (GraphNode("ready", "event.ready"), *queries, *capture_nodes),
            (
                GraphLink(
                    "normalization_cone", "value", "normalization", "cone"
                ),
                *capture_links,
            ),
        )
        _install_world_graph(project, graph, entities)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
const bits = value => {
  if (value === null) return null;
  const bytes = new ArrayBuffer(4);
  const view = new DataView(bytes);
  view.setFloat32(0, value, true);
  return view.getUint32(0, true);
};
const state = KCGame.state();
process.stdout.write(JSON.stringify({
  boundaryFound: state.boundary_found,
  boundaryEntity: state.boundary_entity,
  boundaryDistanceBits: bits(state.boundary_distance),
  normalizationFound: state.normalization_found,
  normalizationEntity: state.normalization_entity,
  normalizationDistanceBits: bits(state.normalization_distance),
  ulpBoundaryEntity: state.ulp_boundary_entity,
  apexPositiveFound: state.apex_positive_found,
  apexPositiveEntity: state.apex_positive_entity,
  apexPositiveDistance: state.apex_positive_distance,
  apexZeroFound: state.apex_zero_found,
  apexZeroEntity: state.apex_zero_entity,
  apexZeroDistanceBits: bits(state.apex_zero_distance),
  clampedFound: state.clamped_direction_found,
  clampedEntity: state.clamped_direction_entity,
  clampedDistance: state.clamped_direction_distance,
  plainFound: state.plain_found,
  plainEntity: state.plain_entity,
  plainDistanceBits: bits(state.plain_distance),
  fullFound: state.full_sphere_found,
  fullEntity: state.full_sphere_entity,
  fullDistanceBits: bits(state.full_sphere_distance),
  missingFound: state.missing_found,
  missingEntity: state.missing_entity,
  missingDistance: state.missing_distance,
}));
''',
            )

        self.assertEqual(
            observed,
            {
                "boundaryFound": True,
                "boundaryEntity": "alpha_boundary",
                "boundaryDistanceBits": 0x3FB504F3,
                "normalizationFound": True,
                "normalizationEntity": "normalization_boundary",
                "normalizationDistanceBits": 0x42A67B15,
                "ulpBoundaryEntity": "collectible_boundary",
                "apexPositiveFound": False,
                "apexPositiveEntity": None,
                "apexPositiveDistance": None,
                "apexZeroFound": True,
                "apexZeroEntity": "apex",
                "apexZeroDistanceBits": 0,
                "clampedFound": False,
                "clampedEntity": None,
                "clampedDistance": None,
                "plainFound": True,
                "plainEntity": "closer_outside",
                "plainDistanceBits": 0x3E64F92F,
                "fullFound": True,
                "fullEntity": "closer_outside",
                "fullDistanceBits": 0x3E64F92F,
                "missingFound": False,
                "missingEntity": None,
                "missingDistance": None,
            },
        )

    def test_node_runtime_rejects_invalid_linked_cones(self):
        cases = (
            ([0.0, 0.0, 0.0, 0.0], "cone Facing direction must be finite and non-zero"),
            ([3.4e38, 3.4e38, 0.0, 0.0], "cone Facing direction must be finite and non-zero"),
            ([1.0, 0.0, 0.0, 1.0001], "cone View width must use a minimum cosine"),
            ([1.0, 0.0, 0.0], "cone must contain a three-number Facing direction"),
            (["right", 0.0, 0.0, 0.0], "cone must contain finite numbers"),
        )
        for index, (cone, message) in enumerate(cases):
            with self.subTest(cone=cone):
                project = first_steps_project(f"Browser Bad Cone {index}")
                scene = project.scenes[project.start_scene]
                player = next(entity for entity in scene.entities if entity.id == "player")
                goal = next(
                    entity for entity in scene.entities if entity.id == "first_collectible"
                )
                graph = VisualGraph(
                    f"bad_cone_{index}",
                    (
                        GraphNode("ready", "event.ready"),
                        GraphNode("bad", "value.constant", {"value": cone}),
                        GraphNode(
                            "query",
                            "query.nearest_in_cone",
                            {"origin": "player", "tag": "goal", "radius": 10.0},
                        ),
                        GraphNode("save", "action.set_state", {"key": "result"}),
                    ),
                    (
                        GraphLink("bad", "value", "query", "cone"),
                        GraphLink("query", "found", "save", "value"),
                        GraphLink("ready", "out", "save", "in"),
                    ),
                )
                entities = (
                    _moved(player, "player", (0.0, 0.0), ("player",)),
                    _moved(goal, "goal", (1.0, 0.0), ("goal",)),
                )
                _install_world_graph(project, graph, entities)
                with tempfile.TemporaryDirectory() as temp_dir:
                    result = build_html5(
                        project, Path(temp_dir), single_file=False
                    )
                    with self.assertRaisesRegex(AssertionError, message):
                        _run_browser_js(result.output_dir, "")


if __name__ == "__main__":
    unittest.main()
