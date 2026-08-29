from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from ugts_kc3.templates import first_steps_project  # noqa: E402
from ugts_kc3.visual_graph import (  # noqa: E402
    BUILTIN_NODE_REGISTRY,
    GraphLink,
    GraphNode,
    VisualGraph,
)
from ugts_kc3 import webexport  # noqa: E402
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
globalThis.fireWindow = (kind, event = {}) => {
  event.preventDefault ||= (() => {});
  for (const callback of listeners[kind] || []) callback(event);
};
require(runtimePath);
eval(commands);
'''


def _run_browser_js(output: Path, commands: str) -> dict:
    import base64

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
        raise AssertionError(f"Node runtime failed:\n{completed.stdout}\n{completed.stderr}")
    return json.loads(completed.stdout)


class WebVisualGraphTests(unittest.TestCase):
    def test_browser_support_is_explicit_for_every_builtin(self):
        self.assertEqual(set(BUILTIN_NODE_REGISTRY.types), set(webexport._WEB_VISUAL_GRAPH_NODE_TYPES))
        project = first_steps_project()
        with mock.patch.object(
            webexport,
            "_WEB_VISUAL_GRAPH_NODE_TYPES",
            webexport._WEB_VISUAL_GRAPH_NODE_TYPES - {"math.add"},
        ):
            with self.assertRaisesRegex(ValueError, r"HTML5 visual graph.*math\.add"):
                webexport._compile_web_visual_graphs(project)

    def test_repeatable_random_number_matches_binary32_golden_with_linked_inputs(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")
        project = first_steps_project("Browser Repeatable Number")
        scene = project.scenes[project.start_scene]
        graph = VisualGraph(
            "repeatable",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("world", "value.constant", {"value": 392.000001}),
                GraphNode("pick", "value.constant", {"value": 7}),
                GraphNode("low", "value.constant", {"value": -10.0}),
                GraphNode("high", "value.constant", {"value": 10.0}),
                GraphNode("number", "value.seeded_number"),
                GraphNode("remember", "action.set_state", {"key": "draw"}),
            ),
            (
                GraphLink("ready", "out", "remember", "in"),
                GraphLink("world", "value", "number", "world_number"),
                GraphLink("pick", "value", "number", "pick_number"),
                GraphLink("low", "value", "number", "smallest"),
                GraphLink("high", "value", "number", "largest"),
                GraphLink("number", "value", "remember", "value"),
            ),
        )
        project.scenes[scene.id] = replace(
            scene,
            entities=tuple(
                replace(entity, metadata={key: value for key, value in entity.metadata.items() if key != "visual_graph"})
                for entity in scene.entities
            ),
            rules={
                **scene.rules,
                "visual_graphs": [graph.to_dict()],
                "world_graphs": [graph.id],
            },
        )
        project.validate()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
const bytes = new ArrayBuffer(4);
const view = new DataView(bytes);
view.setFloat32(0, KCGame.state().draw, true);
process.stdout.write(JSON.stringify({value: KCGame.state().draw, bits: view.getUint32(0, true)}));
''',
            )
            self.assertEqual(observed["bits"], 0xC0F72CB8)
            self.assertEqual(observed["value"], -7.724208831787109)

        bad_nodes = tuple(
            replace(node, properties={"value": 392.1})
            if node.id == "world"
            else node
            for node in graph.nodes
        )
        bad_graph = VisualGraph(graph.id, bad_nodes, graph.links)
        current = project.scenes[scene.id]
        project.scenes[scene.id] = replace(
            current,
            rules={**current.rules, "visual_graphs": [bad_graph.to_dict()]},
        )
        project.validate()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            with self.assertRaisesRegex(
                AssertionError,
                "World number must be a whole number from 0 to 65535",
            ):
                _run_browser_js(result.output_dir, "")

    def test_nearest_tag_matches_f32_ties_boundaries_nulls_and_dynamic_errors(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")
        project = first_steps_project("Browser Nearest Tag")
        scene = project.scenes[project.start_scene]
        source_player = next(entity for entity in scene.entities if entity.id == "player")
        source_collectible = next(
            entity for entity in scene.entities if entity.id == "first_collectible"
        )

        def moved(entity, entity_id, position, tags, *, active=True):
            components = {
                name: dict(value) for name, value in entity.components.items()
            }
            components["transform"] = {
                **components["transform"],
                "position": list(position),
            }
            return replace(
                entity,
                id=entity_id,
                components=components,
                tags=frozenset(tags),
                active=active,
                metadata={},
            )

        entities = (
            moved(source_player, "player", (0.0, 0.0), ("player",)),
            moved(
                source_collectible,
                "first_collectible",
                (4.2, 0.0),
                ("collectible",),
            ),
            # Reverse lexical authoring order is intentional.
            moved(source_collectible, "zeta", (1.1, 2.2), ("goal",)),
            moved(source_collectible, "alpha", (-1.1, -2.2), ("goal",)),
            moved(
                source_collectible,
                "closer_inactive",
                (0.1, 0.0),
                ("goal",),
                active=False,
            ),
        )
        graph = VisualGraph(
            "nearest_web",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "nearest",
                    "query.nearest_tag",
                    {"origin": "player", "tag": "goal", "radius": 10.0},
                ),
                GraphNode(
                    "missing",
                    "query.nearest_tag",
                    {"origin": "player", "tag": "hazard", "radius": 10.0},
                ),
                GraphNode(
                    "boundary",
                    "query.nearest_tag",
                    {"origin": "player", "tag": "collectible", "radius": 4.2},
                ),
                GraphNode("nearest_found", "action.set_state", {"key": "nearest_found"}),
                GraphNode("nearest_entity", "action.set_state", {"key": "nearest_entity"}),
                GraphNode("nearest_distance", "action.set_state", {"key": "nearest_distance"}),
                GraphNode("missing_found", "action.set_state", {"key": "missing_found"}),
                GraphNode("missing_entity", "action.set_state", {"key": "missing_entity"}),
                GraphNode("missing_distance", "action.set_state", {"key": "missing_distance"}),
                GraphNode("boundary_found", "action.set_state", {"key": "boundary_found"}),
            ),
            (
                *(
                    GraphLink("ready", "out", target, "in")
                    for target in (
                        "nearest_found",
                        "nearest_entity",
                        "nearest_distance",
                        "missing_found",
                        "missing_entity",
                        "missing_distance",
                        "boundary_found",
                    )
                ),
                GraphLink("nearest", "found", "nearest_found", "value"),
                GraphLink("nearest", "entity", "nearest_entity", "value"),
                GraphLink("nearest", "distance", "nearest_distance", "value"),
                GraphLink("missing", "found", "missing_found", "value"),
                GraphLink("missing", "entity", "missing_entity", "value"),
                GraphLink("missing", "distance", "missing_distance", "value"),
                GraphLink("boundary", "found", "boundary_found", "value"),
            ),
        )
        project.scenes[scene.id] = replace(
            scene,
            entities=entities,
            rules={
                **scene.rules,
                "visual_graphs": [graph.to_dict()],
                "world_graphs": [graph.id],
            },
        )
        project.validate()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
const bytes = new ArrayBuffer(4);
const view = new DataView(bytes);
view.setFloat32(0, KCGame.state().nearest_distance, true);
process.stdout.write(JSON.stringify({
  nearestFound: KCGame.state().nearest_found,
  nearestEntity: KCGame.state().nearest_entity,
  nearestDistanceBits: view.getUint32(0, true),
  missingFound: KCGame.state().missing_found,
  missingEntity: KCGame.state().missing_entity,
  missingDistance: KCGame.state().missing_distance,
  boundaryFound: KCGame.state().boundary_found,
}));
''',
            )
        self.assertEqual(
            observed,
            {
                "nearestFound": True,
                "nearestEntity": "alpha",
                "nearestDistanceBits": 0x401D6B50,
                "missingFound": False,
                "missingEntity": None,
                "missingDistance": None,
                "boundaryFound": True,
            },
        )

        for port, value, message in (
            ("tag", "custom", "tag must be player"),
            ("radius", -1.0, "radius must be a finite non-negative"),
        ):
            with self.subTest(port=port):
                bad_graph = VisualGraph(
                    f"bad_{port}",
                    (
                        GraphNode("ready", "event.ready"),
                        GraphNode("bad", "value.constant", {"value": value}),
                        GraphNode(
                            "nearest",
                            "query.nearest_tag",
                            {"origin": "player"},
                        ),
                        GraphNode("remember", "action.set_state", {"key": "result"}),
                    ),
                    (
                        GraphLink("ready", "out", "remember", "in"),
                        GraphLink("bad", "value", "nearest", port),
                        GraphLink("nearest", "found", "remember", "value"),
                    ),
                )
                current = project.scenes[scene.id]
                project.scenes[scene.id] = replace(
                    current,
                    rules={
                        **current.rules,
                        "visual_graphs": [bad_graph.to_dict()],
                        "world_graphs": [bad_graph.id],
                    },
                )
                project.validate()
                with tempfile.TemporaryDirectory() as temp_dir:
                    result = build_html5(project, Path(temp_dir), single_file=False)
                    with self.assertRaisesRegex(AssertionError, message):
                        _run_browser_js(result.output_dir, "")

    def test_first_steps_graph_is_precompiled_and_counts_input_edges_in_node(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")
        project = first_steps_project()
        scene = project.scenes[project.start_scene]
        project.scenes[scene.id] = replace(scene, rules={**scene.rules, "score_to_win": 99})
        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            document = json.loads((result.output_dir / "project.json").read_text(encoding="utf-8"))
            runtime = document["web_visual_graph_runtime"]
            self.assertEqual(runtime["graph_count"], 1)
            self.assertEqual(runtime["binding_count"], 1)
            plan = runtime["scenes"]["main"]["graphs"]["dash_counter"]
            self.assertEqual(plan["roots"]["tick"], ["when_dash"])
            self.assertEqual(plan["incoming_data"]["save_score"]["value"], ["add_one", "result"])

            observed = _run_browser_js(
                result.output_dir,
                r'''
fireWindow("keydown", {code: "Space", repeat: false});
const first = KCGame.step().score;
const held = KCGame.step().score;
fireWindow("keyup", {code: "Space"});
KCGame.step();
fireWindow("keydown", {code: "Space", repeat: false});
const second = KCGame.step().score;
process.stdout.write(JSON.stringify({first, held, second}));
''',
            )
            self.assertEqual(observed, {"first": 1, "held": 1, "second": 2})

    def test_sensor_trigger_roots_run_once_with_browser_entity_context(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")
        project = first_steps_project("Browser Trigger Area")
        scene = project.scenes[project.start_scene]
        player = next(entity for entity in scene.entities if "player" in entity.tags)
        sensor = next(
            entity for entity in scene.entities
            if bool(entity.components.get("collider", {}).get("filter", {}).get("sensor"))
        )
        graph = VisualGraph(
            "trigger_lesson",
            (
                GraphNode("enter", "event.trigger_enter"),
                GraphNode("inside", "value.constant", {"value": True}),
                GraphNode("remember_inside", "action.set_state", {"key": "inside_trigger"}),
                GraphNode("announce_enter", "action.emit_event", {"kind": "graph_trigger_enter", "payload": {}}),
                GraphNode("exit", "event.trigger_exit"),
                GraphNode("outside", "value.constant", {"value": False}),
                GraphNode("remember_outside", "action.set_state", {"key": "inside_trigger"}),
                GraphNode("announce_exit", "action.emit_event", {"kind": "graph_trigger_exit", "payload": {}}),
            ),
            (
                GraphLink("enter", "out", "remember_inside", "in"),
                GraphLink("inside", "value", "remember_inside", "value"),
                GraphLink("enter", "out", "announce_enter", "in"),
                GraphLink("enter", "sensor", "announce_enter", "source"),
                GraphLink("enter", "player", "announce_enter", "target"),
                GraphLink("exit", "out", "remember_outside", "in"),
                GraphLink("outside", "value", "remember_outside", "value"),
                GraphLink("exit", "out", "announce_exit", "in"),
                GraphLink("exit", "sensor", "announce_exit", "source"),
                GraphLink("exit", "player", "announce_exit", "target"),
            ),
        )
        player_position = list(player.components["transform"]["position"])
        entities = []
        for entity in scene.entities:
            metadata = {
                key: value for key, value in entity.metadata.items()
                if key != "visual_graph"
            }
            components = dict(entity.components)
            tags = entity.tags
            if entity.id == sensor.id:
                transform = dict(components["transform"])
                transform["position"] = player_position
                components["transform"] = transform
                components.pop("collectible", None)
                tags = frozenset(tag for tag in tags if tag != "collectible")
                metadata["visual_graph"] = graph.id
            entities.append(replace(
                entity,
                components=components,
                tags=tags,
                metadata=metadata,
            ))
        rules = dict(scene.rules)
        rules["visual_graphs"] = [graph.to_dict()]
        rules.pop("world_graphs", None)
        rules["score_to_win"] = 999
        project.scenes[scene.id] = replace(scene, entities=tuple(entities), rules=rules)
        project.validate()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                '''
const first = KCGame.step().inside_trigger;
fireWindow("keydown", {code: "ArrowRight", repeat: false});
KCGame.step(120);
fireWindow("keyup", {code: "ArrowRight"});
const afterExit = KCGame.state().inside_trigger;
const custom = KCGame.events().filter(event => event.kind.startsWith("graph_trigger_"));
process.stdout.write(JSON.stringify({
  first,
  afterExit,
  kinds: custom.map(event => event.kind),
  contexts: custom.map(event => [event.source, event.target]),
}));
''',
            )
            self.assertIs(observed["first"], True)
            self.assertIs(observed["afterExit"], False)
            self.assertEqual(
                observed["kinds"],
                ["graph_trigger_enter", "graph_trigger_exit"],
            )
            self.assertEqual(
                observed["contexts"],
                [[sensor.id, player.id], [sensor.id, player.id]],
            )

    def test_all_action_and_value_families_execute_in_browser(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")
        project = first_steps_project("Browser Graph Coverage")
        scene = project.scenes[project.start_scene]
        action_graph = VisualGraph(
            "ready_actions",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("ten", "value.constant", {"value": 10}),
                GraphNode("two", "value.constant", {"value": 2}),
                GraphNode("one", "value.constant", {"value": 1}),
                GraphNode("subtract", "math.subtract"),
                GraphNode("multiply", "math.multiply"),
                GraphNode("divide", "math.divide"),
                GraphNode("greater", "compare", {"operator": "greater"}),
                GraphNode("branch", "flow.branch"),
                GraphNode("position", "value.constant", {"value": [222, 111]}),
                GraphNode("set_position", "action.set_component", {"component": "transform", "field": "position"}),
                GraphNode("read_position", "value.component", {"component": "transform", "field": "position"}),
                GraphNode("remember", "action.set_state", {"key": "remembered"}),
                GraphNode("force", "value.constant", {"value": [60, 0]}),
                GraphNode("push", "action.apply_force"),
                GraphNode("announce", "action.emit_event", {"kind": "graph_ready", "payload": {"lesson": 1}}),
                GraphNode("disable", "action.set_active", {"active": False}),
            ),
            (
                GraphLink("ten", "value", "subtract", "a"),
                GraphLink("two", "value", "subtract", "b"),
                GraphLink("subtract", "result", "multiply", "a"),
                GraphLink("two", "value", "multiply", "b"),
                GraphLink("multiply", "result", "divide", "a"),
                GraphLink("two", "value", "divide", "b"),
                GraphLink("divide", "result", "greater", "a"),
                GraphLink("one", "value", "greater", "b"),
                GraphLink("greater", "result", "branch", "condition"),
                GraphLink("ready", "out", "branch", "in"),
                GraphLink("branch", "true", "set_position", "in"),
                GraphLink("position", "value", "set_position", "value"),
                GraphLink("set_position", "out", "remember", "in"),
                GraphLink("read_position", "value", "remember", "value"),
                GraphLink("remember", "out", "push", "in"),
                GraphLink("force", "value", "push", "force"),
                GraphLink("push", "out", "announce", "in"),
                GraphLink("announce", "out", "disable", "in"),
            ),
        )
        despawn_graph = VisualGraph(
            "remove_collectible",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("remove", "action.despawn", {"entity": "first_collectible"}),
            ),
            (GraphLink("ready", "out", "remove", "in"),),
        )
        entities = tuple(
            replace(entity, metadata={**entity.metadata, "visual_graph": "ready_actions"})
            if entity.id == "player"
            else entity
            for entity in scene.entities
        )
        project.scenes[scene.id] = replace(
            scene,
            entities=entities,
            rules={
                **scene.rules,
                "visual_graphs": [action_graph.to_dict(), despawn_graph.to_dict()],
                "world_graphs": ["remove_collectible"],
            },
        )
        project.validate()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
const player = KCGame.entities().find(entity => entity.id === "player");
process.stdout.write(JSON.stringify({
  active: player.active,
  position: player.components.transform.position,
  force: player.components.body.force,
  remembered: KCGame.state().remembered,
  collectibleExists: KCGame.entities().some(entity => entity.id === "first_collectible"),
  eventKinds: KCGame.events().map(event => event.kind),
}));
''',
            )
            self.assertFalse(observed["active"])
            self.assertEqual(observed["position"], [222, 111])
            self.assertEqual(observed["force"], [60, 0])
            self.assertEqual(observed["remembered"], [222, 111])
            self.assertFalse(observed["collectibleExists"])
            self.assertIn("graph_ready", observed["eventKinds"])
            self.assertIn("entity_despawned", observed["eventKinds"])

    def test_timer_matches_60_step_schedule_and_resets_without_save_state(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")
        project = first_steps_project("Browser Timer")
        scene = project.scenes[project.start_scene]
        graph = VisualGraph(
            "timer_web",
            (
                GraphNode("a_repeat", "event.timer"),
                GraphNode(
                    "b_once",
                    "event.timer",
                    {"seconds": 1.0, "repeat": False},
                ),
                GraphNode("z_tick", "event.tick"),
                GraphNode(
                    "repeat_event",
                    "action.emit_event",
                    {"kind": "repeat_ring"},
                ),
                GraphNode(
                    "once_event",
                    "action.emit_event",
                    {"kind": "once_ring"},
                ),
                GraphNode(
                    "remember_remaining",
                    "action.set_state",
                    {"key": "timer_remaining"},
                ),
            ),
            (
                GraphLink("a_repeat", "out", "repeat_event", "in"),
                GraphLink("b_once", "out", "once_event", "in"),
                GraphLink("z_tick", "out", "remember_remaining", "in"),
                GraphLink(
                    "a_repeat",
                    "remaining",
                    "remember_remaining",
                    "value",
                ),
            ),
        )
        entities = tuple(
            replace(
                entity,
                metadata={
                    key: value
                    for key, value in entity.metadata.items()
                    if key != "visual_graph"
                },
            )
            for entity in scene.entities
        )
        project.scenes[scene.id] = replace(
            scene,
            entities=entities,
            rules={
                **scene.rules,
                "visual_graphs": [graph.to_dict()],
                "world_graphs": [graph.id],
            },
        )
        project.validate()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
KCGame.step(59);
const before = KCGame.state().timer_remaining;
KCGame.step(1);
const atFirstRing = KCGame.state().timer_remaining;
KCGame.step(60);
const ringKinds = KCGame.events().filter(event => event.kind.endsWith("_ring")).map(event => event.kind);
KCGame.restart();
KCGame.step(59);
const afterRestart = {
  remaining: KCGame.state().timer_remaining,
  rings: KCGame.events().filter(event => event.kind.endsWith("_ring")).length,
};
process.stdout.write(JSON.stringify({before, atFirstRing, ringKinds, afterRestart}));
''',
            )
            self.assertAlmostEqual(observed["before"], 1.0 / 60.0, places=8)
            self.assertEqual(observed["atFirstRing"], 0)
            self.assertEqual(
                observed["ringKinds"],
                ["repeat_ring", "once_ring", "repeat_ring"],
            )
            self.assertAlmostEqual(
                observed["afterRestart"]["remaining"],
                1.0 / 60.0,
                places=8,
            )
            self.assertEqual(observed["afterRestart"]["rings"], 0)


if __name__ == "__main__":
    unittest.main()
