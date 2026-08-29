from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import BuildWorker, EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject, Node3DRecord
from ugts_kc3.project import EntitySpec, GameProject


class EditorSceneAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def test_2d_add_copy_delete_and_undo_preserve_project_records(self) -> None:
        self.window.new_2d_project()
        project = self.window.document.project
        self.assertIsInstance(project, GameProject)
        initial = tuple(self.window.document.scene_objects())

        self.window.hierarchy.add_button.click()
        self.app.processEvents()
        added_selection = self.window.document.selection
        self.assertEqual(added_selection, SelectionRef("entity", "new_object", "main"))
        added = self.window.document.entity()
        self.assertIsInstance(added, EntitySpec)
        self.assertEqual(len(self.window.document.scene_objects()), len(initial) + 1)
        self.assertIn("transform", added.components)
        self.assertIn("vector_renderer", added.components)

        self.window.hierarchy.duplicate_button.click()
        self.app.processEvents()
        copied = self.window.document.entity()
        self.assertIsInstance(copied, EntitySpec)
        self.assertEqual(copied.id, "new_object_copy")
        self.assertEqual(copied.tags, added.tags)
        self.assertEqual(copied.metadata, added.metadata)
        self.assertEqual(set(copied.components), set(added.components))
        self.assertNotEqual(
            copied.components["transform"]["position"],
            added.components["transform"]["position"],
        )

        # Copying the same source again produces a readable collision-free id.
        self.window.document.set_selection(added_selection)
        self.window.hierarchy.duplicate_button.click()
        self.assertEqual(self.window.document.selection.object_id, "new_object_copy_2")
        ids = [record.id for record in self.window.document.scene_objects()]
        self.assertEqual(len(ids), len(set(ids)))

        self.window.hierarchy.delete_button.click()
        count_after_delete = len(self.window.document.scene_objects())
        self.window.undo_stack.undo()
        self.assertEqual(len(self.window.document.scene_objects()), count_after_delete + 1)
        self.assertEqual(self.window.document.selection.object_id, "new_object_copy_2")
        self.window.undo_stack.redo()
        self.assertEqual(len(self.window.document.scene_objects()), count_after_delete)
        self.assertTrue(self.window.document.validate().passed)

    def test_2d_structural_references_have_friendly_delete_guards(self) -> None:
        self.window.new_2d_project()
        player = SelectionRef("entity", "player", "main")
        message = self.window.document.deletion_problem(player)
        self.assertIsNotNone(message)
        self.assertIn("scene's player id", message)
        self.assertIn("rules", message)

    def test_add_logic_block_reacquires_reloaded_node_and_undoes(self) -> None:
        self.window.new_2d_project()
        original_ids = set(self.window.graph_page.graph_scene.nodes)
        guidance: list[str] = []
        self.window.graph_page.helpRequested.connect(guidance.append)

        # This exercises the synchronous GraphCommand redo -> graph reload path.
        self.window.graph_page.add_template("action.despawn")
        self.app.processEvents()

        added = [
            node
            for node_id, node in self.window.graph_page.graph_scene.nodes.items()
            if node_id not in original_ids
        ]
        self.assertEqual(len(added), 1)
        node = added[0]
        self.assertEqual(node.template.key, "action.despawn")
        self.assertTrue(node.isSelected())
        self.assertIs(self.window.graph_page.properties.node, node)
        self.assertTrue(any("Added “Remove Object”" in message for message in guidance))
        self.assertIn("Drag its dots", self.window.status_message.text())
        self.assertTrue(self.window.undo_stack.canUndo())

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(set(self.window.graph_page.graph_scene.nodes), original_ids)

    def test_3d_add_copy_delete_and_undo_keep_mesh_material_and_metadata(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        initial_count = len(project.nodes)

        self.window.hierarchy.add_button.click()
        added = self.window.document.entity()
        self.assertIsInstance(added, Node3DRecord)
        self.assertEqual(added.id, "new_object")
        self.assertIn(added.mesh_id, project.meshes)
        self.assertIn(added.material_id, project.materials)

        self.window.hierarchy.duplicate_button.click()
        copied = self.window.document.entity()
        self.assertIsInstance(copied, Node3DRecord)
        self.assertEqual(copied.id, "new_object_copy")
        self.assertEqual(copied.mesh_id, added.mesh_id)
        self.assertEqual(copied.material_id, added.material_id)
        self.assertEqual(copied.metadata, added.metadata)
        self.assertEqual(copied.tags, added.tags)
        self.assertNotEqual(copied.transform.translation, added.transform.translation)

        self.window.hierarchy.delete_button.click()
        self.assertEqual(len(project.nodes), initial_count + 1)
        self.window.undo_stack.undo()
        self.assertEqual(len(project.nodes), initial_count + 2)
        self.assertEqual(self.window.document.selection.object_id, "new_object_copy")
        self.window.undo_stack.redo()
        self.assertEqual(len(project.nodes), initial_count + 1)
        self.assertTrue(self.window.document.validate().passed)

    def test_last_3d_node_cannot_be_deleted(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        project.nodes = (project.nodes[0],)
        selection = SelectionRef("node", project.nodes[0].id)
        self.assertIn("at least one object", self.window.document.deletion_problem(selection))

    def test_apk_install_failure_reports_partial_success_with_build_folder(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            apk = output / "app-pocoX7Pro-debug.apk"
            apk.write_bytes(b"compiled apk")
            worker = BuildWorker(project, "android-install", output)
            partial: list[object] = []
            failures: list[str] = []
            worker.partial.connect(partial.append)
            worker.failed.connect(failures.append)
            with (
                patch(
                    "ugts_kc3.editor.main_window.build_android_project",
                    return_value=SimpleNamespace(output_dir=output),
                ),
                patch(
                    "ugts_kc3.editor.main_window.select_android_device",
                    return_value=SimpleNamespace(serial="device-1"),
                ),
                patch(
                    "ugts_kc3.editor.main_window.build_apk",
                    return_value=SimpleNamespace(apk=apk),
                ),
                patch(
                    "ugts_kc3.editor.main_window.install_apk",
                    side_effect=RuntimeError("No Android device is connected"),
                ),
            ):
                worker.run()
            self.assertFalse(failures)
            self.assertEqual(len(partial), 1)
            summary, error, folder = partial[0]
            self.assertIn("APK built", summary)
            self.assertIn("No Android device", error)
            self.assertEqual(folder, apk.parent)

    def test_deploy_action_uses_adb_target_and_editor_owned_folder(self) -> None:
        self.window.new_2d_project()
        self.assertFalse(self.window.deploy_action.isEnabled())
        self.window.document.set_dirty(False)
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        self.assertTrue(self.window.deploy_action.isEnabled())
        with tempfile.TemporaryDirectory() as temporary:
            project_path = self.window.document.save(Path(temporary) / "project.json")
            with patch.object(self.window, "_build_requested") as requested:
                self.window.deploy_to_phone()
            requested.assert_called_once()
            target, destination = requested.call_args.args
            self.assertEqual(target, "android-install")
            self.assertEqual(self.window.build_output.target.currentData(), "android-install")
            self.assertEqual(
                destination,
                project_path.parent / ".ugts-studio" / "deploy" / f"{project.id}-android",
            )

    def test_check_project_accepts_portable_android_world_graph(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        project.metadata["world_graphs"] = ["dash_lesson"]
        self.assertTrue(self.window.document.validate().passed)

        self.window.build_output.output.clear()
        self.window.validate_project()
        messages = self.window.build_output.output.toPlainText()
        self.assertIn("Project check passed", messages)
        self.assertNotIn("Android build cannot use these Logic Blocks yet", messages)
        self.assertEqual(self.window.assets_project.project_status.text(), "Ready")


if __name__ == "__main__":
    unittest.main()
