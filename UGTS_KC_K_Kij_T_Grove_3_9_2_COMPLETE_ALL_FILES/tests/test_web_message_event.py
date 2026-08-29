from __future__ import annotations

from dataclasses import replace
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from ugts_kc3 import webexport  # noqa: E402
from ugts_kc3.templates import first_steps_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402
from ugts_kc3.webexport import build_html5  # noqa: E402


_NODE_HARNESS = r'''
const fs = require("fs");
const projectText = fs.readFileSync(process.argv[1], "utf8");
const runtimePath = process.argv[2];
const commands = Buffer.from(process.argv[3], "base64").toString("utf8");
const catchRuntime = process.argv[4] === "catch";
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
let runtimeError = null;
try { require(runtimePath); }
catch (error) {
  if (!catchRuntime) throw error;
  runtimeError = error instanceof Error ? error.message : String(error);
}
eval(commands);
'''


def _run_browser_js(
    output: Path,
    commands: str,
    *,
    catch_runtime: bool = False,
) -> dict:
    completed = subprocess.run(
        [
            shutil.which("node") or "node",
            "-e",
            _NODE_HARNESS,
            str(output / "project.json"),
            str(output / "kc-runtime.js"),
            base64.b64encode(commands.encode("utf-8")).decode("ascii"),
            "catch" if catch_runtime else "throw",
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


def _project_with(
    graphs: tuple[VisualGraph, ...],
    *,
    entity_bindings: dict[str, tuple[str, ...]] | None = None,
    world_bindings: tuple[str, ...] = (),
    extra_entities: tuple = (),
):
    project = first_steps_project("Browser Message Events")
    scene = project.scenes[project.start_scene]
    bindings = entity_bindings or {}
    entities = []
    for entity in (*scene.entities, *extra_entities):
        metadata = {
            key: value
            for key, value in entity.metadata.items()
            if key != "visual_graph"
        }
        graph_ids = bindings.get(entity.id, ())
        if graph_ids:
            metadata["visual_graph"] = list(graph_ids)
        entities.append(replace(entity, metadata=metadata))
    rules = {
        **scene.rules,
        "visual_graphs": [graph.to_dict() for graph in graphs],
        "world_graphs": list(world_bindings),
        "score_to_win": 999,
    }
    project.scenes[scene.id] = replace(
        scene,
        entities=tuple(entities),
        rules=rules,
    )
    project.validate()
    return project


def _message_emitter(
    graph_id: str,
    trigger: str,
    messages: tuple[tuple[str, str | None, str | None, dict], ...],
) -> VisualGraph:
    event_type = "event.ready" if trigger == "ready" else "event.tick"
    nodes = [GraphNode("root", event_type)]
    links = []
    for index, (kind, source, target, payload) in enumerate(messages):
        node_id = f"send_{index:02d}"
        nodes.append(
            GraphNode(
                node_id,
                "action.emit_event",
                {
                    "kind": kind,
                    "source": source,
                    "target": target,
                    "payload": payload,
                },
            )
        )
        links.append(GraphLink("root", "out", node_id, "in"))
    return VisualGraph(graph_id, tuple(nodes), tuple(links))


def _message_listener(graph_id: str, message: str, emitted: str) -> VisualGraph:
    return VisualGraph(
        graph_id,
        (
            GraphNode("heard", "event.message", {"message": message}),
            GraphNode("announce", "action.emit_event", {"kind": emitted}),
        ),
        (GraphLink("heard", "out", "announce", "in"),),
    )


class WebMessageEventTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is not installed")

    def test_compile_and_runtime_route_exact_messages_in_binding_order(self) -> None:
        a_listener = _message_listener("a_listener", "ordered", "seen_a")
        z_listener = _message_listener("z_listener", "ordered", "seen_z")
        capture = VisualGraph(
            "capture",
            (
                GraphNode("heard", "event.message", {"message": "capture"}),
                GraphNode("save_source", "action.set_state", {"key": "heard_source"}),
                GraphNode("save_target", "action.set_state", {"key": "heard_target"}),
                GraphNode("save_entity", "action.set_state", {"key": "heard_entity"}),
            ),
            (
                GraphLink("heard", "out", "save_source", "in"),
                GraphLink("heard", "source", "save_source", "value"),
                GraphLink("heard", "out", "save_target", "in"),
                GraphLink("heard", "target", "save_target", "value"),
                GraphLink("heard", "out", "save_entity", "in"),
                GraphLink("heard", "entity", "save_entity", "value"),
            ),
        )
        emitter = _message_emitter(
            "00_emitter",
            "ready",
            (
                ("ordered", "first_collectible", "player", {}),
                ("ordered", None, None, {}),
                ("capture", "first_collectible", "player", {"ignored": 99}),
                ("ordered.extra", None, "player", {}),
            ),
        )
        starter = first_steps_project()
        collectible = next(
            entity
            for entity in starter.scenes[starter.start_scene].entities
            if entity.id == "first_collectible"
        )
        sleeping = replace(collectible, id="sleeping", active=False)
        project = _project_with(
            (z_listener, emitter, capture, a_listener),
            entity_bindings={
                "player": ("z_listener", "capture", "a_listener"),
                "first_collectible": ("z_listener", "a_listener"),
                "sleeping": ("z_listener", "a_listener"),
            },
            world_bindings=("z_listener", "00_emitter", "a_listener"),
            extra_entities=(sleeping,),
        )

        plan = webexport._compile_web_visual_graphs(project)["scenes"]["main"]
        self.assertEqual(
            plan["bindings"],
            [
                {"graph": "a_listener", "entity": "player"},
                {"graph": "capture", "entity": "player"},
                {"graph": "z_listener", "entity": "player"},
                {"graph": "a_listener", "entity": "first_collectible"},
                {"graph": "z_listener", "entity": "first_collectible"},
                {"graph": "a_listener", "entity": "sleeping"},
                {"graph": "z_listener", "entity": "sleeping"},
                {"graph": "00_emitter", "entity": None},
                {"graph": "a_listener", "entity": None},
                {"graph": "z_listener", "entity": None},
            ],
        )
        self.assertEqual(plan["graphs"]["a_listener"]["roots"]["message"], ["heard"])

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
const seen = KCGame.events()
  .filter(event => event.kind === "seen_a" || event.kind === "seen_z")
  .map(event => [event.kind, event.source]);
const captureEvent = KCGame.events().find(event => event.kind === "capture");
process.stdout.write(JSON.stringify({seen, state: KCGame.state(), capturePayload: captureEvent.payload}));
''',
            )

        self.assertEqual(
            observed["seen"],
            [
                ["seen_a", "player"],
                ["seen_z", "player"],
                ["seen_a", None],
                ["seen_z", None],
                ["seen_a", "player"],
                ["seen_z", "player"],
                ["seen_a", "first_collectible"],
                ["seen_z", "first_collectible"],
                ["seen_a", None],
                ["seen_z", None],
            ],
        )
        self.assertEqual(observed["state"]["heard_source"], "first_collectible")
        self.assertEqual(observed["state"]["heard_target"], "player")
        self.assertEqual(observed["state"]["heard_entity"], "player")
        self.assertEqual(observed["capturePayload"], {"ignored": 99})

    def test_ready_and_fixed_step_messages_drain_after_the_outer_batch(self) -> None:
        ready_first = _message_emitter(
            "00_ready_first", "ready", (("first", None, None, {}),)
        )
        ready_after = _message_emitter(
            "01_ready_after", "ready", (("ready_after", None, None, {}),)
        )
        first_a = _message_listener("10_first_a", "first", "second")
        first_b = _message_listener("11_first_b", "first", "sibling")
        second = _message_listener("20_second", "second", "child")
        tick_first = _message_emitter(
            "30_tick_first", "tick", (("tick_first", None, None, {}),)
        )
        tick_after = _message_emitter(
            "31_tick_after", "tick", (("tick_after", None, None, {}),)
        )
        tick_listener = _message_listener(
            "40_tick_listener", "tick_first", "tick_handled"
        )
        graphs = (
            ready_first,
            ready_after,
            first_a,
            first_b,
            second,
            tick_first,
            tick_after,
            tick_listener,
        )
        project = _project_with(
            graphs,
            world_bindings=tuple(graph.id for graph in reversed(graphs)),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
const readyKinds = KCGame.events().map(event => event.kind);
KCGame.step();
const allKinds = KCGame.events().map(event => event.kind);
process.stdout.write(JSON.stringify({readyKinds, fixedKinds: allKinds.slice(readyKinds.length)}));
''',
            )

        self.assertEqual(
            observed["readyKinds"],
            ["first", "ready_after", "second", "sibling", "child"],
        )
        self.assertEqual(
            observed["fixedKinds"],
            ["tick_first", "tick_after", "tick_handled"],
        )

    def test_message_cascade_reports_event_limit_in_status_and_log(self) -> None:
        start = _message_emitter(
            "00_start", "ready", (("loop", None, None, {}),)
        )
        # Unrelated literal roots must be filtered before execution. If they
        # consumed steps, this cascade would hit TotalStepLimit before the
        # intended 64-message EventLimit.
        loop_nodes = [
            GraphNode("heard_loop", "event.message", {"message": "loop"}),
            GraphNode("send_again", "action.emit_event", {"kind": "loop"}),
            *(
                GraphNode(
                    f"unrelated_{index:03d}",
                    "event.message",
                    {"message": f"other_{index:03d}"},
                )
                for index in range(300)
            ),
        ]
        loop = VisualGraph(
            "01_loop",
            tuple(loop_nodes),
            (GraphLink("heard_loop", "out", "send_again", "in"),),
        )
        project = _project_with((start, loop), world_bindings=(start.id, loop.id))

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
process.stdout.write(JSON.stringify({error: runtimeError, status: status.textContent, events: KCGame.events().length}));
''',
                catch_runtime=True,
            )

        expected = "Visual graph message dispatch stopped with EventLimit after 64 queued events"
        self.assertIn(expected, observed["error"])
        self.assertIn(expected, observed["status"])
        self.assertEqual(observed["events"], 65)

    def test_outer_batch_rejects_the_65th_enqueue_before_drain(self) -> None:
        messages = tuple(
            (f"message_{index:02d}", None, None, {}) for index in range(65)
        )
        emitter = _message_emitter("emit_65", "ready", messages)
        project = _project_with((emitter,), world_bindings=(emitter.id,))

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
process.stdout.write(JSON.stringify({error: runtimeError, status: status.textContent, events: KCGame.events().length}));
''',
                catch_runtime=True,
            )

        expected = "EventLimit after 64 queued events"
        self.assertIn(expected, observed["error"])
        self.assertIn(expected, observed["status"])
        self.assertEqual(observed["events"], 65)

    def test_outer_message_batch_reports_total_step_limit_at_16384(self) -> None:
        start = _message_emitter(
            "00_start", "ready", (("large_loop", None, None, {}),)
        )
        nodes = [GraphNode("heard", "event.message", {"message": "large_loop"})]
        links = []
        previous = "heard"
        for index in range(600):
            node_id = f"save_{index:03d}"
            nodes.append(GraphNode(node_id, "action.set_state", {"key": "work"}))
            links.append(GraphLink(previous, "out", node_id, "in"))
            previous = node_id
        nodes.append(GraphNode("send_again", "action.emit_event", {"kind": "large_loop"}))
        links.append(GraphLink(previous, "out", "send_again", "in"))
        loop = VisualGraph("01_large_loop", tuple(nodes), tuple(links))
        project = _project_with((start, loop), world_bindings=(start.id, loop.id))

        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_html5(project, Path(temp_dir), single_file=False)
            observed = _run_browser_js(
                result.output_dir,
                r'''
process.stdout.write(JSON.stringify({error: runtimeError, status: status.textContent}));
''',
                catch_runtime=True,
            )

        expected = "TotalStepLimit after 16384 node steps"
        self.assertIn(expected, observed["error"])
        self.assertIn(expected, observed["status"])


if __name__ == "__main__":
    unittest.main()
