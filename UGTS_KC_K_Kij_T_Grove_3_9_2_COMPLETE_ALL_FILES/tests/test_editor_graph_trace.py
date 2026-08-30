from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QGraphicsItem, QTabWidget

from ugts_kc3.editor.document import LogicTraceSnapshot
from ugts_kc3.editor.graph import GraphPage, TEMPLATE_BY_KEY
from ugts_kc3.visual_graph import GraphNode as DataGraphNode
from ugts_kc3.visual_graph import TraceEntry, VisualGraph


class GraphTracePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _graph(graph_id: str = "lesson") -> dict[str, object]:
        return VisualGraph(
            graph_id,
            (
                DataGraphNode("start", "event.ready", position=(0.0, 0.0)),
                DataGraphNode(
                    "constant",
                    "value.constant",
                    {"value": True},
                    (260.0, 0.0),
                ),
            ),
            metadata={"lesson": "trace"},
        ).to_dict()

    @staticmethod
    def _snapshot(graph_id: str = "lesson") -> LogicTraceSnapshot:
        trace = (
            TraceEntry(1, "start", "event.ready", None, {}, {}, ("out",)),
            TraceEntry(
                2,
                "constant",
                "value.constant",
                None,
                {},
                {"value": True},
                (),
            ),
            TraceEntry(
                3,
                "constant",
                "value.constant",
                None,
                {"value": True},
                {},
                (),
                "error",
                "A friendly test error",
            ),
        )
        return LogicTraceSnapshot(graph_id, "player", "ready", len(trace), trace, False, 7)

    def setUp(self) -> None:
        self.page = GraphPage()
        self.page.resize(1000, 700)
        self.page.load_data(self._graph())
        self.app.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def test_matching_snapshot_adds_ordered_nonserialized_trace_presentation(self) -> None:
        before = VisualGraph.from_dict(self.page.graph_scene.data()).canonical_bytes()

        self.assertTrue(self.page.show_trace(self._snapshot()))

        self.assertEqual(self.page.trace_step_count, 3)
        self.assertEqual(self.page.trace_count, 3)
        self.assertEqual(self.page.trace_list.topLevelItemCount(), 3)
        self.assertEqual(
            [self.page.trace_list.topLevelItem(index).text(0) for index in range(3)],
            ["1", "2", "3"],
        )
        self.assertIn("Value: Yes", self.page.trace_list.topLevelItem(1).text(2))
        self.assertIn("Error:", self.page.trace_list.topLevelItem(2).text(2))
        self.assertIn("Stopped with an error", self.page.trace_status.text())

        start = self.page.graph_scene.nodes["start"]
        constant = self.page.graph_scene.nodes["constant"]
        self.assertEqual(start.trace_steps, (1,))
        self.assertEqual(constant.trace_steps, (2, 3))
        self.assertEqual(constant.trace_status, "error")
        self.assertEqual(constant.trace_error, "A friendly test error")
        self.assertEqual(
            VisualGraph.from_dict(self.page.graph_scene.data()).canonical_bytes(),
            before,
        )

    def test_mapping_trace_is_supported_and_mismatched_graph_is_ignored(self) -> None:
        mapping_snapshot = {
            "graph_id": "lesson",
            "owner_id": "player",
            "trigger": "button_pressed",
            "steps": 1,
            "completed": True,
            "sequence": 8,
            "trace": [
                {
                    "step": 4,
                    "node_id": "constant",
                    "node_type": "value.constant",
                    "flow_input": None,
                    "inputs": {},
                    "outputs": {"value": False},
                    "flow_outputs": [],
                    "status": "ok",
                    "error": None,
                }
            ],
        }
        self.assertTrue(self.page.show_trace(mapping_snapshot))
        self.assertEqual(self.page.trace_list.topLevelItem(0).text(0), "4")
        self.assertIn("Value: No", self.page.trace_list.topLevelItem(0).text(2))
        status_before = self.page.trace_status.text()

        self.assertFalse(
            self.page.show_trace(
                {
                    **mapping_snapshot,
                    "graph_id": "another_graph",
                    "trace": [],
                }
            )
        )
        self.assertEqual(self.page.trace_step_count, 1)
        self.assertEqual(self.page.trace_list.topLevelItemCount(), 1)
        self.assertEqual(self.page.trace_status.text(), status_before)
        self.assertEqual(self.page.graph_scene.nodes["constant"].trace_steps, (4,))

        self.assertTrue(self.page.show_trace(None))
        self.assertEqual(self.page.trace_step_count, 0)
        self.assertEqual(self.page.trace_list.topLevelItemCount(), 0)
        self.assertEqual(self.page.graph_scene.nodes["constant"].trace_steps, ())

    def test_last_run_click_focuses_block_even_when_read_only(self) -> None:
        self.page.show_trace(self._snapshot())
        self.page.set_read_only(True)
        self.page.graph_scene.clearSelection()
        item = self.page.trace_list.topLevelItem(1)

        self.page.trace_list.itemClicked.emit(item, 0)
        self.app.processEvents()

        constant = self.page.graph_scene.nodes["constant"]
        self.assertTrue(constant.isSelected())
        self.assertIs(self.page.properties.node, constant)
        self.assertTrue(self.page.view.isEnabled())

    def test_sidebar_uses_focused_tabs_at_compact_editor_size(self) -> None:
        self.page.resize(980, 640)
        self.page.show()
        self.app.processEvents()

        tabs = self.page.sidebar_tabs
        self.assertIsInstance(tabs, QTabWidget)
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            ["Blocks", "Settings", "Trail"],
        )
        self.assertIs(tabs.widget(0), self.page.palette)
        self.assertIs(tabs.widget(1), self.page.properties)
        self.assertIs(tabs.widget(2), self.page.last_run)
        self.assertGreaterEqual(tabs.width(), 260)
        self.assertGreater(self.page.view.width(), tabs.width())

        for panel in (self.page.palette, self.page.properties, self.page.last_run):
            tabs.setCurrentWidget(panel)
            self.app.processEvents()
            self.assertTrue(panel.isVisibleTo(self.page))
            self.assertTrue(
                all(
                    other is panel or not other.isVisibleTo(self.page)
                    for other in (
                        self.page.palette,
                        self.page.properties,
                        self.page.last_run,
                    )
                )
            )
        self.assertGreater(self.page.last_run.steps.height(), 190)

    def test_selecting_a_graph_block_opens_its_settings_tab(self) -> None:
        self.page.show()
        self.page.sidebar_tabs.setCurrentWidget(self.page.last_run)
        self.page.graph_scene.clearSelection()
        self.page.graph_scene.nodes["constant"].setSelected(True)
        self.app.processEvents()

        self.assertIs(self.page.sidebar_tabs.currentWidget(), self.page.properties)
        self.assertIs(self.page.properties.node, self.page.graph_scene.nodes["constant"])

    def test_read_only_blocks_scene_palette_and_property_mutations(self) -> None:
        scene = self.page.graph_scene
        constant = scene.nodes["constant"]
        scene.clearSelection()
        constant.setSelected(True)
        self.app.processEvents()
        before = VisualGraph.from_dict(scene.data()).canonical_bytes()
        original_position = QPointF(constant.pos())
        original_count = len(scene.nodes)

        self.page.set_read_only(True)
        self.assertTrue(self.page.read_only)
        self.assertTrue(scene.read_only)
        self.assertFalse(
            constant.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.assertTrue(
            constant.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        editor = self.page.properties.editor_for("value")
        self.assertIsNotNone(editor)
        self.assertFalse(editor.isEnabled())

        constant.setPos(QPointF(900.0, 900.0))
        self.page.properties._commit_property("value", False)
        self.page.add_template("compare")
        scene.delete_selected()
        scene.clear_graph()
        scene.begin_connection(next(iter(scene.nodes["start"].output_ports.values())))

        self.assertEqual(constant.pos(), original_position)
        self.assertIs(constant.properties["value"], True)
        self.assertEqual(len(scene.nodes), original_count)
        self.assertIsNone(scene._connecting_port)
        self.assertEqual(VisualGraph.from_dict(scene.data()).canonical_bytes(), before)
        with self.assertRaises(RuntimeError):
            scene.add_node(TEMPLATE_BY_KEY["compare"], QPointF())

        scene.clearSelection()
        constant.setSelected(True)
        self.assertTrue(constant.isSelected())
        self.page.set_read_only(False)
        self.assertFalse(self.page.read_only)
        self.assertTrue(constant.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)


if __name__ == "__main__":
    unittest.main()
