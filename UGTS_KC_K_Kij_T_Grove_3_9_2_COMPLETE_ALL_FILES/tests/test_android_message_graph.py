from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


HOST_TESTS = ROOT / "native" / "host_tests"
ENGINE_CPP = (
    SRC
    / "ugts_kc3"
    / "android_template"
    / "project"
    / "app"
    / "src"
    / "main"
    / "cpp"
    / "engine.cpp"
)


def _host_cpp_toolchain_available() -> bool:
    if os.name != "nt":
        return any(shutil.which(name) for name in ("c++", "g++", "clang++"))
    if shutil.which("cl") or shutil.which("clang++") or shutil.which("g++"):
        return True
    vswhere = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    ) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return False
    found = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return found.returncode == 0 and bool(found.stdout.strip())


def _listener_graph(
    graph_id: str,
    handlers: tuple[tuple[str, str, str | None, str | None], ...],
) -> VisualGraph:
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []
    for index, (message, emitted, source_output, target_output) in enumerate(handlers):
        heard_id = f"heard_{index}"
        emit_id = f"emit_{index}"
        nodes.extend(
            (
                GraphNode(heard_id, "event.message", {"message": message}),
                GraphNode(emit_id, "action.emit_event", {"kind": emitted}),
            )
        )
        links.append(GraphLink(heard_id, "out", emit_id, "in"))
        if source_output is not None:
            links.append(GraphLink(heard_id, source_output, emit_id, "source"))
        if target_output is not None:
            links.append(GraphLink(heard_id, target_output, emit_id, "target"))
    return VisualGraph(graph_id, tuple(nodes), tuple(links))


def _routing_project():
    project = blank_mobile3d_project()
    emitter = VisualGraph(
        "world_emitter",
        (
            GraphNode("ready", "event.ready"),
            GraphNode("emit_alpha", "action.emit_event", {"kind": "alpha", "source": "player"}),
            GraphNode(
                "emit_beta",
                "action.emit_event",
                {"kind": "beta", "source": "player", "target": "goal"},
            ),
            GraphNode("tick", "event.tick"),
            GraphNode("emit_tick", "action.emit_event", {"kind": "tick.ping", "source": "player"}),
        ),
        (
            GraphLink("ready", "out", "emit_alpha", "in"),
            GraphLink("emit_alpha", "out", "emit_beta", "in"),
            GraphLink("tick", "out", "emit_tick", "in"),
        ),
    )
    floor_listener = _listener_graph(
        "floor_listener",
        (
            ("alpha", "forbidden.floor.alpha", None, None),
            ("beta", "forbidden.floor.beta", None, None),
        ),
    )
    player_listener = _listener_graph(
        "player_listener",
        (
            ("alpha", "seen.player.alpha", "source", "entity"),
            ("beta", "forbidden.player.beta", None, None),
            ("tick.ping", "seen.player.tick", None, None),
        ),
    )
    goal_listener = _listener_graph(
        "goal_listener",
        (
            ("alpha", "seen.goal.alpha", "source", "entity"),
            ("beta", "seen.goal.beta", "source", "target"),
            ("tick.ping", "seen.goal.tick", None, None),
        ),
    )
    dead_listener = _listener_graph(
        "dead_listener",
        (
            ("alpha", "forbidden.dead.alpha", None, None),
            ("beta", "forbidden.dead.beta", None, None),
        ),
    )
    world_listener = _listener_graph(
        "world_listener",
        (
            ("alpha", "seen.world.alpha", "source", "entity"),
            ("beta", "seen.world.beta", "target", "entity"),
            ("tick.ping", "seen.world.tick", None, None),
        ),
    )
    graphs = (
        emitter,
        floor_listener,
        player_listener,
        goal_listener,
        dead_listener,
        world_listener,
    )
    bindings = {
        "floor": floor_listener.id,
        "player": player_listener.id,
        "goal": goal_listener.id,
    }
    project.nodes = tuple(
        replace(node, metadata={"visual_graph": bindings[node.id]})
        for node in project.nodes
    ) + (
        replace(
            project.nodes[0],
            id="dead",
            metadata={"visual_graph": dead_listener.id},
        ),
    )
    project.metadata["visual_graphs"] = [graph.to_dict() for graph in graphs]
    project.metadata["world_graphs"] = [emitter.id, world_listener.id]
    return project


def _event_limit_project():
    project = blank_mobile3d_project()
    unrelated = tuple(
        GraphNode(
            f"unused_{index:03d}",
            "event.message",
            {"message": f"unused.{index:03d}"},
        )
        for index in range(300)
    )
    graph = VisualGraph(
        "limit_loop",
        (
            GraphNode("ready", "event.ready"),
            GraphNode("emit_first", "action.emit_event", {"kind": "loop"}),
            GraphNode("heard_loop", "event.message", {"message": "loop"}),
            GraphNode("emit_again", "action.emit_event", {"kind": "loop"}),
        ) + unrelated,
        (
            GraphLink("ready", "out", "emit_first", "in"),
            GraphLink("heard_loop", "out", "emit_again", "in"),
        ),
    )
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.metadata["world_graphs"] = [graph.id]
    return project


class AndroidMessageGraphTests(unittest.TestCase):
    def test_engine_finishes_messages_after_triggers_on_both_fixed_step_exits(self) -> None:
        source = ENGINE_CPP.read_text(encoding="utf-8")
        self.assertEqual(source.count("graphVm_.finishStep("), 2)

        tick = source.index("graphVm_.tick(")
        no_player = source.index("if (!p) {")
        no_player_trigger = source.index("dispatchTriggerAreas(dt,currentInput);", no_player)
        no_player_finish = source.index("graphVm_.finishStep(", no_player)
        no_player_increment = source.index("++fixedTick_;", no_player)
        normal_trigger = source.index(
            "dispatchTriggerAreas(dt,currentInput);", no_player_trigger + 1
        )
        normal_finish = source.index("graphVm_.finishStep(", no_player_finish + 1)
        normal_increment = source.index("++fixedTick_;", no_player_increment + 1)

        self.assertLess(tick, no_player_finish)
        self.assertLess(no_player_trigger, no_player_finish)
        self.assertLess(no_player_finish, no_player_increment)
        self.assertLess(normal_trigger, normal_finish)
        self.assertLess(normal_finish, normal_increment)

    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the host graph-VM test")
    def test_opcode_25_routes_fifo_messages_and_enforces_event_limit(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")

        routing = compile_graph_pack_bytes(_routing_project())
        routing_info = inspect_graph_pack(routing)
        self.assertEqual(routing_info["binding_count"], 6)
        self.assertEqual(routing_info["world_binding_count"], 2)

        event_limit = compile_graph_pack_bytes(_event_limit_project())
        limit_info = inspect_graph_pack(event_limit)
        self.assertEqual(limit_info["binding_count"], 1)
        self.assertEqual(limit_info["world_binding_count"], 1)

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            routing_fixture = temporary_path / "message-routing.kcvg"
            routing_fixture.write_bytes(routing)
            limit_fixture = temporary_path / "message-limit.kcvg"
            limit_fixture.write_bytes(event_limit)
            build = temporary_path / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                configured.returncode,
                0,
                configured.stdout + configured.stderr,
            )
            compiled = subprocess.run(
                [
                    "cmake",
                    "--build",
                    str(build),
                    "--config",
                    "Release",
                    "--target",
                    "message_graph_vm_tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                compiled.returncode,
                0,
                compiled.stdout + compiled.stderr,
            )
            candidates = tuple(build.rglob("message_graph_vm_tests.exe")) or tuple(
                path
                for path in build.rglob("message_graph_vm_tests")
                if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the message host test")
            executed = subprocess.run(
                [str(candidates[0]), str(routing_fixture), str(limit_fixture)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                executed.returncode,
                0,
                executed.stdout + executed.stderr,
            )
            self.assertIn(
                "PASS message graph VM routing and limits",
                executed.stdout,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
