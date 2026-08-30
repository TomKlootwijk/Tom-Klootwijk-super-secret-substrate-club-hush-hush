# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path
import struct
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

from ugts_kc3 import webexport
from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.graph import (
    GraphNode as EditorGraphNode,
    NodePalette,
    NodePropertiesPanel,
    TEMPLATE_BY_KEY,
)
from ugts_kc3.editor.scene_view import SceneViewport
from ugts_kc3.graphpack import (
    GraphPackError,
    NODE_DATA_OUTPUTS,
    NODE_FLOW_OUTPUTS,
    NODE_INPUTS,
    NODE_OPCODES,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import polar_population_preset
from ugts_kc3.templates import first_steps_project
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


OLD_OPCODES = {
    "event.ready": 1,
    "event.tick": 2,
    "event.input_pressed": 3,
    "flow.branch": 4,
    "value.constant": 5,
    "value.state": 6,
    "value.component": 7,
    "math.add": 8,
    "math.subtract": 9,
    "math.multiply": 10,
    "math.divide": 11,
    "compare": 12,
    "action.set_state": 13,
    "action.set_component": 14,
    "action.emit_event": 15,
    "action.set_active": 16,
    "action.despawn": 17,
    "action.apply_force": 18,
    "event.trigger_enter": 19,
    "event.trigger_exit": 20,
    "value.seeded_number": 21,
    "query.nearest_tag": 22,
    "event.timer": 23,
    "query.nearest_in_cone": 24,
    "event.message": 25,
    "action.play_animation": 26,
    "action.stop_animation": 27,
    "value.polar_movement": 28,
    "action.set_polar_movement": 29,
}


def _visibility_graph(*, entity=None, visible=False) -> VisualGraph:
    return VisualGraph(
        "copies",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "copies",
                "action.set_polar_population_visible",
                {"entity": entity, "visible": visible},
            ),
        ),
        (GraphLink("ready", "out", "copies", "in"),),
    )


def _project(graph: VisualGraph | None = None):
    project = blank_mobile3d_project("Extra Copies", "Test")
    profile = LogPolarProfile(r0=2.0, rho_min=-5.0, rho_max=5.0)
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(math.log(2.0), -math.pi * 0.5, 0, 0.0),
        PolarMotion(0.0, 0.0),
        profile_id="display",
    )
    project.metadata["packed_kinematic_profiles"] = {
        "display": {
            "profile": profile.to_dict(),
            "motion_range": motion_range.to_dict(),
            "lut_resolution": 64,
        }
    }
    if graph is not None:
        project.metadata["visual_graphs"] = [graph.to_dict()]
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            metadata={
                **node.metadata,
                "packed_kinematic": component.to_dict(),
                "polar_population": polar_population_preset(
                    "ring", instance_count=4, seed=2
                ).to_dict(),
                **({"visual_graph": graph.id} if graph is not None else {}),
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _copy_items(viewport: SceneViewport):
    return tuple(
        item
        for item in viewport.scene().items()
        if item.data(3) == "polar_population_copy"
    )


class PolarPopulationVisibilityGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_opcode_30_is_append_only_compact_and_byte_frozen(self) -> None:
        self.assertEqual(
            {name: NODE_OPCODES[name] for name in OLD_OPCODES}, OLD_OPCODES
        )
        self.assertEqual(NODE_OPCODES["action.set_polar_population_visible"], 30)
        self.assertEqual(
            NODE_INPUTS["action.set_polar_population_visible"],
            ("entity", "visible"),
        )
        self.assertEqual(
            NODE_DATA_OUTPUTS["action.set_polar_population_visible"], ()
        )
        self.assertEqual(
            NODE_FLOW_OUTPUTS["action.set_polar_population_visible"], ("out",)
        )

        packed = compile_graph_pack_bytes(_project(_visibility_graph()))
        self.assertEqual(
            packed.hex(),
            "4b43564730303100040302010100000001000000020000000100000001000000"
            "020000000200000001000000000000000600636f706965730001000000000000"
            "00000002000004000000000200000000000000000000000200000000001e0002"
            "00000000000000000001000000010000000000010000000000",
        )
        self.assertEqual(inspect_graph_pack(packed)["input_count"], 2)
        linked_target = bytearray(packed)
        struct.pack_into("<I", linked_target, len(linked_target) - 10, (1 << 30) | 1)
        with self.assertRaisesRegex(GraphPackError, "packed literal"):
            inspect_graph_pack(bytes(linked_target))

    def test_ready_executor_uses_ephemeral_state_and_new_world_resets(self) -> None:
        project = _project(_visibility_graph())
        world = project.instantiate_world()
        self.assertEqual(world.polar_population_runtime.prototype_ids, ("goal",))
        self.assertFalse(world.polar_population_runtime.copies_visible("goal"))
        self.assertTrue(world.require("goal").alive)
        self.assertTrue(world.require("goal").active)

        snapshot = world.snapshot()
        state_hash = world.state_hash()
        world.set_polar_population_copies_visible("goal", True)
        self.assertEqual(world.snapshot(), snapshot)
        self.assertEqual(world.state_hash(), state_hash)
        serialized = json.dumps(snapshot)
        self.assertNotIn("make_many_copies_visible", serialized)
        self.assertNotIn("polar_population_runtime", serialized)
        self.assertNotIn("polar_population", world._sparse_components)

        reset_project = _project()
        first = reset_project.instantiate_world()
        first.set_polar_population_copies_visible("goal", False)
        second = reset_project.instantiate_world()
        self.assertFalse(first.polar_population_runtime.copies_visible("goal"))
        self.assertTrue(second.polar_population_runtime.copies_visible("goal"))
        with self.assertRaisesRegex(ValueError, "no Make Many recipe"):
            second.set_polar_population_copies_visible("floor", False)

    def test_literal_and_actual_target_validation_fail_child_friendly(self) -> None:
        linked = VisualGraph(
            "linked",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "copies",
                    "action.set_polar_population_visible",
                    {"visible": False},
                ),
            ),
            (
                GraphLink("ready", "out", "copies", "in"),
                GraphLink("ready", "entity", "copies", "entity"),
            ),
        )
        issues = linked.validation_issues()
        self.assertIn(
            "polar_population_target_literal_only",
            {issue.code for issue in issues},
        )
        with self.assertRaisesRegex(ValueError, "chosen on the block"):
            _project(linked)

        invalid = _project()
        graph = _visibility_graph(entity="floor")
        invalid.metadata["visual_graphs"] = [graph.to_dict()]
        invalid.nodes = tuple(
            replace(node, metadata={**node.metadata, "visual_graph": graph.id})
            if node.id == "goal"
            else node
            for node in invalid.nodes
        )
        report = invalid.validate(raise_on_error=False)
        self.assertIn(
            "polar_population.graph_target", {issue.code for issue in report.issues}
        )
        with self.assertRaisesRegex(ValueError, "does not own a Make Many recipe"):
            compile_graph_pack_bytes(invalid)

        for scope in ("world", "mixed"):
            with self.subTest(scope=scope):
                scoped = _project()
                self_graph = _visibility_graph()
                scoped.metadata["visual_graphs"] = [self_graph.to_dict()]
                if scope == "world":
                    scoped.metadata["world_graphs"] = self_graph.id
                else:
                    scoped.nodes = tuple(
                        replace(
                            node,
                            metadata={
                                **node.metadata,
                                "visual_graph": self_graph.id,
                            },
                        )
                        if node.id in {"goal", "floor"}
                        else node
                        for node in scoped.nodes
                    )
                report = scoped.validate(raise_on_error=False)
                target_issue = next(
                    issue
                    for issue in report.issues
                    if issue.code == "polar_population.graph_target"
                )
                self.assertIn(
                    "World Logic" if scope == "world" else "floor",
                    target_issue.message,
                )

    def test_editor_sideband_hides_only_retained_copies_and_stop_restores(self) -> None:
        project = _project(_visibility_graph())
        document = EditorDocument()
        document.create(project)
        viewport = SceneViewport()
        viewport.set_document(document)
        try:
            authored_copies = _copy_items(viewport)
            self.assertGreater(len(authored_copies), 0)
            document.begin_play()
            state, _events = document.step_play(set())
            self.assertFalse(state["goal"]["make_many_copies_visible"])
            viewport.set_playing(True)
            viewport.set_runtime_state(state)
            self.app.processEvents()
            self.assertTrue(all(not item.isVisible() for item in authored_copies))
            self.assertIn("goal", viewport._mesh_items)
            self.assertTrue(viewport._mesh_items["goal"].isVisible())

            world = document._runtime_world
            assert world is not None
            world.set_polar_population_copies_visible("goal", True)
            state, _events = document.step_play(set())
            viewport.set_runtime_state(state)
            self.assertTrue(all(item.isVisible() for item in authored_copies))
            self.assertTrue(viewport._mesh_items["goal"].isVisible())

            document.stop_play()
            viewport.set_playing(False)
            viewport.set_runtime_state(None)
            self.app.processEvents()
            self.assertTrue(all(item.isVisible() for item in _copy_items(viewport)))
        finally:
            document.stop_play()
            viewport.close()
            self.app.processEvents()

    def test_3d_looks_picker_lists_only_real_make_many_targets(self) -> None:
        document = EditorDocument()
        document.create(_project())
        document.set_selection(SelectionRef("node", "goal"))
        goal_context = document.graph_authoring_context()
        self.assertEqual(goal_context.polar_population_choices, (("goal", "Goal"),))

        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        panel.set_entity_context(goal_context.owner_id, goal_context.entity_choices)
        panel.set_polar_population_context(goal_context.polar_population_choices)
        node = EditorGraphNode(
            "copies",
            TEMPLATE_BY_KEY["action.set_polar_population_visible"],
            {"entity": None, "visible": False},
        )
        panel.set_node(node)
        entity = panel.editor_for("entity")
        visible = panel.editor_for("visible")
        self.assertIsInstance(entity, QComboBox)
        self.assertIsInstance(visible, QComboBox)
        self.assertEqual(
            tuple(entity.itemData(index) for index in range(entity.count())),
            (None, "goal"),
        )
        self.assertEqual(entity.findData("floor"), -1)
        self.assertEqual(visible.itemText(visible.findData(False)), "Hide extra copies")
        self.assertEqual(panel.values.topLevelItem(0).text(0), "Make Many object")
        self.assertEqual(panel.values.topLevelItem(1).text(0), "Show extra copies")

        document.set_selection(SelectionRef("node", "floor"))
        floor_context = document.graph_authoring_context()
        panel.set_entity_context(floor_context.owner_id, floor_context.entity_choices)
        panel.set_polar_population_context(floor_context.polar_population_choices)
        panel.set_node(node)
        entity = panel.editor_for("entity")
        assert isinstance(entity, QComboBox)
        self.assertEqual(entity.findData(None), -1)
        self.assertEqual(entity.findData("goal"), 0)

        palette = NodePalette()
        palette.set_project_kind("2d")
        item = next(
            palette.tree.topLevelItem(category).child(child)
            for category in range(palette.tree.topLevelItemCount())
            for child in range(palette.tree.topLevelItem(category).childCount())
            if palette.tree.topLevelItem(category).child(child).data(
                0, Qt.ItemDataRole.UserRole
            )
            == "action.set_polar_population_visible"
        )
        self.assertTrue(item.isHidden())
        palette.set_project_kind("3d")
        self.assertFalse(item.isHidden())

    def test_browser_explicitly_rejects_the_mobile_3d_only_block(self) -> None:
        project = first_steps_project("No Browser Copies")
        scene = project.scenes[project.start_scene]
        graph = VisualGraph(
            "copies",
            (
                GraphNode(
                    "copies",
                    "action.set_polar_population_visible",
                    {"entity": "player", "visible": False},
                ),
            ),
        )
        project.scenes[scene.id] = replace(
            scene,
            rules={**scene.rules, "visual_graphs": [graph.to_dict()]},
        )
        with self.assertRaisesRegex(ValueError, "Mobile 3D-only.*polar_population"):
            webexport._compile_web_visual_graphs(project)


if __name__ == "__main__":
    unittest.main()
