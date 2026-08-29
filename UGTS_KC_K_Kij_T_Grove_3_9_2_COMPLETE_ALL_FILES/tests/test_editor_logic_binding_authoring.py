from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.project import GameProject
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


class EditorLogicBindingAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.resize(1200, 800)
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        if self.window._playing:
            self.window.stop()
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    @staticmethod
    def _project_bytes(document: EditorDocument) -> bytes:
        return json.dumps(
            document.serialize(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _graphs(project: GameProject | Mobile3DProject) -> dict[str, dict]:
        if isinstance(project, GameProject):
            values = project.scenes[project.start_scene].rules["visual_graphs"]
        else:
            values = project.metadata["visual_graphs"]
        return {str(value["id"]): value for value in values}

    def test_unbound_2d_first_block_creates_only_its_graph_and_undo_is_exact(
        self,
    ) -> None:
        self.window.new_2d_project()
        self.window.hierarchy.add_button.click()
        self.app.processEvents()
        self.window.undo_stack.clear()
        self.window.document.set_dirty(False)

        project = self.window.document.project
        self.assertIsInstance(project, GameProject)
        selected = self.window.document.entity()
        self.assertEqual(selected.id, "new_object")
        self.assertIsNone(selected.metadata.get("visual_graph"))
        original_dash = json.dumps(
            self._graphs(project)["dash_counter"], sort_keys=True
        )

        context = self.window.document.graph_authoring_context()
        self.assertEqual(context.active_graph_id, "new_object_logic")
        self.assertFalse(context.persisted)
        self.assertEqual(context.graph["nodes"], [])
        self.assertIn("Logic for New Object", self.window.graph_page.context_label.text())
        self.assertIn("Pick a block", self.window.graph_page.context_label.text())
        before = self._project_bytes(self.window.document)

        self.window.graph_page.add_template("event.ready")
        self.app.processEvents()

        selected = self.window.document.entity()
        self.assertEqual(selected.metadata.get("visual_graph"), "new_object_logic")
        graphs = self._graphs(project)
        self.assertIn("new_object_logic", graphs)
        self.assertEqual(
            json.dumps(graphs["dash_counter"], sort_keys=True), original_dash
        )
        self.assertEqual(self.window.undo_stack.count(), 1)
        after = self._project_bytes(self.window.document)
        self.assertNotEqual(after, before)

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(self._project_bytes(self.window.document), before)
        self.assertIsNone(self.window.document.entity().metadata.get("visual_graph"))
        self.assertFalse(self.window.document.graph_authoring_context().persisted)
        self.assertFalse(self.window.document.is_dirty)

        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(self._project_bytes(self.window.document), after)
        self.assertEqual(
            self.window.document.entity().metadata.get("visual_graph"),
            "new_object_logic",
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "project.json")
            loaded = EditorDocument()
            loaded.load(path)
            loaded.set_selection(SelectionRef("entity", "new_object", "main"))
            loaded_context = loaded.graph_authoring_context()
        self.assertTrue(loaded_context.persisted)
        self.assertEqual(loaded_context.active_graph_id, "new_object_logic")
        self.assertTrue(loaded.validate().passed)

    def test_3d_unique_graph_previews_and_compiles_to_exact_android_binding(
        self,
    ) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        # Prove collision handling against an existing, unbound resource.
        project.metadata["visual_graphs"] = [
            *project.metadata["visual_graphs"],
            VisualGraph("new_object_logic").to_dict(),
        ]
        self.window.hierarchy.add_button.click()
        self.app.processEvents()
        self.window.undo_stack.clear()
        self.window.document.set_dirty(False)

        context = self.window.document.graph_authoring_context()
        self.assertEqual(context.active_graph_id, "new_object_logic_2")
        self.assertFalse(context.persisted)
        before = self._project_bytes(self.window.document)
        graph = VisualGraph(
            context.active_graph_id,
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "remember",
                    "action.set_state",
                    {"key": "new_object_ready", "value": True},
                ),
            ),
            (GraphLink("ready", "out", "remember", "in"),),
            context.graph["metadata"],
        ).to_dict()
        self.window._graph_edited(graph)
        self.app.processEvents()

        selected = self.window.document.entity()
        graph_id = str(selected.metadata["visual_graph"])
        self.assertEqual(graph_id, "new_object_logic_2")
        self.assertTrue(self.window.document.validate().passed)
        info = inspect_graph_pack(compile_graph_pack_bytes(project))
        node_index = next(
            index for index, node in enumerate(project.nodes) if node.id == "new_object"
        )
        self.assertIn(
            {
                "graph": graph_id,
                "scope": "node",
                "scene_node_index": node_index,
            },
            info["bindings"],
        )

        self.window.play()
        self.app.processEvents()
        snapshot = self.window.document.logic_trace(graph_id, "new_object")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.owner_id, "new_object")
        self.assertEqual(snapshot.graph_id, graph_id)
        self.assertTrue(self.window.graph_page.read_only)
        play_bytes = self._project_bytes(self.window.document)
        self.window.graph_page.add_template("value.constant")
        self.app.processEvents()
        self.assertEqual(self._project_bytes(self.window.document), play_bytes)
        self.window.stop()

        after = self._project_bytes(self.window.document)
        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(self._project_bytes(self.window.document), before)
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(self._project_bytes(self.window.document), after)

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "project.json")
            loaded = EditorDocument()
            loaded.load(path)
            loaded.set_selection(SelectionRef("node", "new_object"))
        self.assertEqual(loaded.graph_data()["id"], graph_id)
        self.assertTrue(loaded.validate().passed)

    def test_multiple_object_bindings_have_visible_exact_choice(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        original_binding = ["goal_area_lesson", "dash_lesson"]
        project.nodes = tuple(
            replace(
                node,
                metadata={**node.metadata, "visual_graph": list(original_binding)},
            )
            if node.id == "player"
            else node
            for node in project.nodes
        )
        self.window.document.set_selection(SelectionRef("node", "player"))
        self.app.processEvents()
        self.window.undo_stack.clear()
        self.window.document.set_dirty(False)

        context = self.window.document.graph_authoring_context()
        self.assertEqual(
            tuple(graph_id for graph_id, _label in context.choices),
            tuple(original_binding),
        )
        self.assertEqual(context.active_graph_id, "goal_area_lesson")
        self.assertFalse(self.window.graph_page.graph_choice.isHidden())
        dash_index = self.window.graph_page.graph_choice.findData("dash_lesson")
        self.assertGreaterEqual(dash_index, 0)
        self.window.graph_page.graph_choice.setCurrentIndex(dash_index)
        self.app.processEvents()
        self.assertEqual(self.window._active_graph_id, "dash_lesson")
        self.assertEqual(
            self.window.graph_page.graph_scene.property("graph_id"), "dash_lesson"
        )

        graphs_before = self._graphs(project)
        untouched = json.dumps(graphs_before["goal_area_lesson"], sort_keys=True)
        dash_count = len(graphs_before["dash_lesson"]["nodes"])
        self.window.graph_page.add_template("value.constant")
        self.app.processEvents()

        player = self.window.document.entity(SelectionRef("node", "player"))
        self.assertEqual(player.metadata["visual_graph"], original_binding)
        graphs_after = self._graphs(project)
        self.assertEqual(
            json.dumps(graphs_after["goal_area_lesson"], sort_keys=True), untouched
        )
        self.assertEqual(len(graphs_after["dash_lesson"]["nodes"]), dash_count + 1)
        self.assertEqual(self.window._active_graph_id, "dash_lesson")

        self.window.undo_stack.undo()
        self.app.processEvents()
        player = self.window.document.entity(SelectionRef("node", "player"))
        self.assertEqual(player.metadata["visual_graph"], original_binding)
        self.assertEqual(
            json.dumps(self._graphs(project)["goal_area_lesson"], sort_keys=True),
            untouched,
        )

    def test_populate_area_refuses_a_new_logic_binding_without_mutation(self) -> None:
        self.window.new_3d_project()
        selection = SelectionRef("node", "crystal_garden")
        self.window.document.set_selection(selection)
        self.app.processEvents()
        self.window.undo_stack.clear()
        self.window.document.set_dirty(False)

        context = self.window.document.graph_authoring_context()
        self.assertFalse(context.persisted)
        self.assertIsNotNone(context.creation_problem)
        self.assertIn("Populate Area", context.creation_problem)
        self.assertFalse(self.window.graph_page.palette.isEnabled())
        self.assertTrue(self.window.graph_page.graph_scene.read_only)
        self.assertFalse(self.window.graph_page.read_only)
        before = self._project_bytes(self.window.document)
        messages: list[str] = []
        self.window.graph_page.helpRequested.connect(messages.append)

        self.window.graph_page.add_template("event.ready")
        self.app.processEvents()
        self.assertEqual(self._project_bytes(self.window.document), before)
        self.assertEqual(self.window.undo_stack.count(), 0)
        self.assertTrue(any("Populate Area" in message for message in messages))

        blocked = VisualGraph(
            context.active_graph_id,
            (GraphNode("ready", "event.ready"),),
            metadata=context.graph["metadata"],
        ).to_dict()
        with self.assertRaisesRegex(ValueError, "Populate Area"):
            self.window.document.set_graph_data(blocked, selection)
        self.assertEqual(self._project_bytes(self.window.document), before)


if __name__ == "__main__":
    unittest.main()
