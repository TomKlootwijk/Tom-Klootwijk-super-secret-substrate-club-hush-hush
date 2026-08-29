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

from ugts_kc3.templates import first_steps_project
from ugts_kc3.visual_graph import BUILTIN_NODE_REGISTRY, GraphLink, GraphNode, VisualGraph
from ugts_kc3 import webexport
from ugts_kc3.webexport import build_html5


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


if __name__ == "__main__":
    unittest.main()
