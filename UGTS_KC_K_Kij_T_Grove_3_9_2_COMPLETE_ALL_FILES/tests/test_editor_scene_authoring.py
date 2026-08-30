from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.androidbuild import AndroidProfileResult
from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import (
    BuildWorker,
    EditorMainWindow,
    PhoneProfileWorker,
)
from ugts_kc3.mobile3d import Mobile3DProject, Node3DRecord
from ugts_kc3.project import EntitySpec, GameProject


def _smooth_phone_result() -> AndroidProfileResult:
    return AndroidProfileResult(
        application_id="org.ugts.games.my_mobile_3d_game.pocox7pro",
        serial="poco-1",
        model="POCO X7 Pro",
        requested_seconds=30.0,
        samples=6,
        frame_intervals=720,
        display_period_ms=8.3333,
        effective_fps=119.82,
        frame_ms_p50=8.36,
        frame_ms_p95=9.91,
        frame_ms_p99=11.2,
        intervals_over_1_5_vsync=2,
        pss_kib_min=133_000,
        pss_kib_max=134_000,
        rss_kib_min=250_000,
        rss_kib_max=252_000,
        cpu_total_capacity_pct_mean=4.0,
        cpu_total_capacity_pct_max=5.0,
        cpu_one_core_pct_mean=32.0,
        cpu_one_core_pct_max=40.0,
        cpu_logical_cores=8,
        gpu_c_min=47.0,
        gpu_c_max=49.5,
        battery_c_min=35.0,
        battery_c_max=36.0,
        battery_level_start=81,
        battery_level_end=81,
        thermal_status_max=0,
        pid=123,
        crash_buffer_lines=0,
        summary="Smooth 120 Hz baseline",
        warnings=(),
        gpu_timer_supported=True,
        gpu_timer_counter_bits=64,
        gpu_timer_samples_since_renderer_start=599,
        gpu_render_ms_total_since_renderer_start=1272.875,
        gpu_render_ms_mean_since_renderer_start=2.125,
        gpu_render_ms_max_since_renderer_start=4.5,
        gpu_render_ms_last=2.0,
        gpu_timer_disjoint_intervals_since_renderer_start=1,
        gpu_timer_pending_queries=2,
    )


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
            summary, phase, error, folder = partial[0]
            self.assertIn("APK built", summary)
            self.assertEqual(phase, "install")
            self.assertIn("No Android device", error)
            self.assertEqual(folder, apk.parent)

    def test_phone_deploy_builds_installs_and_opens_on_pinned_serial(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            apk = output / "app-pocoX7Pro-debug.apk"
            apk.write_bytes(b"compiled apk")
            worker = BuildWorker(project, "android-install", output)
            finished: list[object] = []
            worker.finished.connect(finished.append)
            with (
                patch(
                    "ugts_kc3.editor.main_window.build_android_project",
                    return_value=SimpleNamespace(output_dir=output),
                ),
                patch(
                    "ugts_kc3.editor.main_window.select_android_device",
                    return_value=SimpleNamespace(serial="poco-1"),
                ),
                patch(
                    "ugts_kc3.editor.main_window.build_apk",
                    return_value=SimpleNamespace(
                        apk=apk,
                        application_id="org.ugts.games.child.pocox7pro",
                    ),
                ),
                patch(
                    "ugts_kc3.editor.main_window.install_apk",
                    return_value=SimpleNamespace(serial="poco-1"),
                ) as install,
                patch("ugts_kc3.editor.main_window.launch_android_app") as launch,
            ):
                worker.run()
            install.assert_called_once_with(apk, serial="poco-1")
            launch.assert_called_once_with(
                "org.ugts.games.child.pocox7pro", serial="poco-1"
            )
            self.assertEqual(len(finished), 1)
            summary, folder = finished[0]
            self.assertIn("installed on poco-1 and opened", summary)
            self.assertEqual(folder, apk.parent)

    def test_phone_launch_failure_is_partial_after_successful_install(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            apk = output / "app-pocoX7Pro-debug.apk"
            apk.write_bytes(b"compiled apk")
            worker = BuildWorker(project, "android-install", output)
            partial: list[object] = []
            worker.partial.connect(partial.append)
            with (
                patch(
                    "ugts_kc3.editor.main_window.build_android_project",
                    return_value=SimpleNamespace(output_dir=output),
                ),
                patch(
                    "ugts_kc3.editor.main_window.select_android_device",
                    return_value=SimpleNamespace(serial="poco-1"),
                ),
                patch(
                    "ugts_kc3.editor.main_window.build_apk",
                    return_value=SimpleNamespace(
                        apk=apk,
                        application_id="org.ugts.games.child.pocox7pro",
                    ),
                ),
                patch(
                    "ugts_kc3.editor.main_window.install_apk",
                    return_value=SimpleNamespace(serial="poco-1"),
                ),
                patch(
                    "ugts_kc3.editor.main_window.launch_android_app",
                    side_effect=RuntimeError("Activity did not start"),
                ),
            ):
                worker.run()
            self.assertEqual(len(partial), 1)
            summary, phase, error, folder = partial[0]
            self.assertIn("installed on poco-1", summary)
            self.assertEqual(phase, "launch")
            self.assertIn("Activity did not start", error)
            self.assertEqual(folder, apk.parent)

    def test_phone_preflight_failure_never_starts_android_build(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        worker = BuildWorker(project, "android-install", Path("unused"))
        failures: list[str] = []
        worker.failed.connect(failures.append)
        with (
            patch(
                "ugts_kc3.editor.main_window.select_android_device",
                side_effect=RuntimeError("No Android device was found"),
            ),
            patch("ugts_kc3.editor.main_window.build_android_project") as build,
        ):
            worker.run()
        build.assert_not_called()
        self.assertEqual(failures, ["No Android device was found"])

    def test_deploy_action_uses_adb_target_and_editor_owned_folder(self) -> None:
        self.window.new_2d_project()
        self.assertFalse(self.window.deploy_action.isEnabled())
        self.window.document.set_dirty(False)
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        self.assertTrue(self.window.deploy_action.isEnabled())
        install_index = self.window.build_output.target.findData("android-install")
        self.assertGreaterEqual(install_index, 0)
        self.assertIn("Open", self.window.build_output.target.itemText(install_index))
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

    def test_phone_profile_worker_uses_read_only_profiler_arguments(self) -> None:
        result = _smooth_phone_result()
        worker = PhoneProfileWorker(
            result.application_id, seconds=5, sample_seconds=2
        )
        finished: list[object] = []
        failed: list[str] = []
        worker.finished.connect(finished.append)
        worker.failed.connect(failed.append)
        with patch(
            "ugts_kc3.editor.main_window.profile_android_app",
            return_value=result,
        ) as profile:
            worker.run()
        profile.assert_called_once_with(
            result.application_id, seconds=5.0, sample_seconds=2.0
        )
        self.assertEqual(finished, [result])
        self.assertEqual(failed, [])

    def test_check_phone_action_targets_poco_flavor_and_reports_friendly_metrics(self) -> None:
        self.window.new_2d_project()
        self.assertFalse(self.window.profile_phone_action.isEnabled())
        self.window.document.set_dirty(False)
        self.window.new_3d_project()
        self.assertTrue(self.window.profile_phone_action.isEnabled())
        with patch.object(self.window, "_start_phone_profile") as start:
            self.window.profile_running_phone()
        start.assert_called_once_with(
            "org.ugts.games.my_mobile_3d_game.pocox7pro"
        )

        self.window.build_output.output.clear()
        self.window._profile_finished(_smooth_phone_result())
        messages = self.window.build_output.output.toPlainText()
        self.assertIn("Smooth 120 Hz baseline on POCO X7 Pro", messages)
        self.assertIn("119.82 FPS", messages)
        self.assertIn("Game memory (PSS): 129.9–130.9 MiB", messages)
        self.assertIn("CPU work: average 32.0% of one core; 4.0% of the whole phone", messages)
        self.assertIn(
            "GPU drawing since the renderer started: average 2.125 ms, "
            "slowest measured 4.500 ms",
            messages,
        )
        self.assertIn("599 non-blocking samples", messages)
        self.assertIn("GPU temperature: 47.0–49.5 °C", messages)
        self.assertEqual(self.window.status_message.text(), "Phone check passed.")

    def test_successful_phone_deploy_reports_that_game_is_running(self) -> None:
        self.window.new_3d_project()
        with tempfile.TemporaryDirectory() as temporary:
            self.window._build_finished((
                "Poco APK built and installed on poco-1 and opened",
                Path(temporary),
            ))
        self.assertEqual(
            self.window.status_message.text(),
            "The game is running on the connected phone.",
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
