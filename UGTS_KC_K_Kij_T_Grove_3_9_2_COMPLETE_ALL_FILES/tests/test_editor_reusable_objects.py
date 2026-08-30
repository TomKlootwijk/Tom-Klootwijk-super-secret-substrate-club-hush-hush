from __future__ import annotations

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from ugts_kc3.androidexport import compile_scene_pack_bytes, inspect_scene_pack
from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.polarpack import compile_polar_pack_bytes
from ugts_kc3.reusable import (
    REUSABLE_INSTANCE_KEY,
    REUSABLE_OBJECTS_KEY,
    reusable_source_id,
)
from ugts_kc3.templates3d import first_steps_mobile3d_project
from ugts_kc3.scatterpack import compile_scatter_pack_bytes


def _tree_texts(tree) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    iterator = QTreeWidgetItemIterator(tree)
    while iterator.value():
        item = iterator.value()
        rows.append((item.text(0), item.text(1)))
        iterator += 1
    return tuple(rows)


class ReusableObjectCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = first_steps_mobile3d_project()
        self.document = EditorDocument()
        self.document.create(self.project)
        self.document.set_selection(SelectionRef("node", "floor"))

    def test_definition_preserves_compact_components_without_mutating_source(self) -> None:
        source_before = copy.deepcopy(self.document.entity())
        metadata, reusable = self.document.reusable_object_metadata_snapshot(
            "Smart Floor"
        )

        self.assertEqual(reusable.id, "smart_floor")
        self.assertEqual(reusable.node, source_before)
        self.assertEqual(self.document.entity(), source_before)
        self.assertNotIn("packed_kinematic", reusable.node.metadata)
        self.assertEqual(
            reusable.node.metadata["visual_graph"], "repeatable_number_lesson"
        )
        self.assertNotIn(REUSABLE_INSTANCE_KEY, reusable.node.metadata)
        self.assertNotIn(REUSABLE_OBJECTS_KEY, self.project.metadata)
        self.assertEqual(metadata[REUSABLE_OBJECTS_KEY][0], reusable.to_dict())

    def test_roundtrip_and_collision_suffixes_are_deterministic(self) -> None:
        first_metadata, first = self.document.reusable_object_metadata_snapshot(
            "Smart Floor"
        )
        self.document.replace_reusable_objects(
            self.project.nodes, first_metadata, self.document.selection
        )
        second_metadata, second = self.document.reusable_object_metadata_snapshot(
            "Smart Floor"
        )
        self.assertEqual(second.id, "smart_floor_2")
        self.document.replace_reusable_objects(
            self.project.nodes, second_metadata, self.document.selection
        )

        clone = Mobile3DProject.from_dict(
            json.loads(json.dumps(self.project.to_dict()))
        )
        clone_document = EditorDocument()
        clone_document.create(clone)
        self.assertEqual(clone_document.reusable_objects(), self.document.reusable_objects())
        self.assertEqual(
            [definition.id for definition in clone_document.reusable_objects()],
            ["smart_floor", "smart_floor_2"],
        )

    def test_instance_is_flat_collision_free_and_shares_logic_resource(self) -> None:
        metadata, reusable = self.document.reusable_object_metadata_snapshot(
            "Smart Floor"
        )
        self.document.replace_reusable_objects(
            self.project.nodes, metadata, self.document.selection
        )
        first = self.document.instantiate_reusable_object_record(reusable.id)
        self.document.replace_reusable_objects(
            (*self.project.nodes, first), metadata, SelectionRef("node", first.id)
        )
        second = self.document.instantiate_reusable_object_record(reusable.id)

        self.assertEqual(first.id, "smart_floor")
        self.assertEqual(second.id, "smart_floor_2")
        self.assertEqual(reusable_source_id(first), reusable.id)
        self.assertEqual(reusable_source_id(second), reusable.id)
        self.assertEqual(first.mesh_id, reusable.node.mesh_id)
        self.assertEqual(first.material_id, reusable.node.material_id)
        self.assertEqual(first.collider, reusable.node.collider)
        self.assertEqual(first.metadata["visual_graph"], "repeatable_number_lesson")
        self.assertNotIn("packed_kinematic", first.metadata)
        self.assertNotEqual(first.transform.translation, reusable.node.transform.translation)
        self.assertNotEqual(second.transform.translation, first.transform.translation)
        self.assertGreaterEqual(
            first.transform.translation[0] - reusable.node.transform.translation[0],
            25.0,
        )

        changed_metadata = copy.deepcopy(first.metadata)
        changed_metadata["description"] = "Only this instance changed"
        changed_first = copy.deepcopy(first)
        object.__setattr__(changed_first, "metadata", changed_metadata)
        self.assertNotEqual(changed_first.metadata, reusable.node.metadata)

    def test_deleted_gap_is_reused_without_overlapping_a_surviving_instance(self) -> None:
        metadata, reusable = self.document.reusable_object_metadata_snapshot(
            "Smart Floor"
        )
        self.document.replace_reusable_objects(
            self.project.nodes, metadata, self.document.selection
        )
        first = self.document.instantiate_reusable_object_record(reusable.id)
        self.document.replace_reusable_objects(
            (*self.project.nodes, first), metadata, SelectionRef("node", first.id)
        )
        second = self.document.instantiate_reusable_object_record(reusable.id)
        self.document.replace_reusable_objects(
            (*self.project.nodes, second), metadata, SelectionRef("node", second.id)
        )
        without_first = tuple(node for node in self.project.nodes if node.id != first.id)
        self.document.replace_reusable_objects(
            without_first, metadata, SelectionRef("node", second.id)
        )

        replacement = self.document.instantiate_reusable_object_record(reusable.id)
        self.assertEqual(replacement.transform.translation, first.transform.translation)
        self.assertNotEqual(replacement.transform.translation, second.transform.translation)

    def test_placement_honors_runtime_collider_radius_from_the_largest_scale_axis(
        self,
    ) -> None:
        colliders = (
            replace(self.document.entity().collider, shape="sphere", radius=10.0),
            replace(
                self.document.entity().collider,
                shape="box",
                half_extents=(1.0, 10.0, 1.0),
            ),
        )
        for collider in colliders:
            with self.subTest(shape=collider.shape):
                project = first_steps_mobile3d_project()
                document = EditorDocument()
                document.create(project)
                document.set_selection(SelectionRef("node", "floor"))
                source = document.entity()
                scaled_source = replace(
                    source,
                    transform=replace(source.transform, scale=(1.0, 10.0, 1.0)),
                    collider=collider,
                )
                document.replace_scene_objects(
                    tuple(
                        scaled_source if node.id == source.id else node
                        for node in project.nodes
                    ),
                    document.selection,
                )
                metadata, reusable = document.reusable_object_metadata_snapshot(
                    f"Tall {collider.shape}"
                )
                document.replace_reusable_objects(
                    project.nodes,
                    metadata,
                    document.selection,
                )

                instance = document.instantiate_reusable_object_record(reusable.id)
                offset = (
                    instance.transform.translation[0]
                    - scaled_source.transform.translation[0]
                )
                runtime_radius = scaled_source.collider.bounding_radius(
                    scaled_source.transform.scale
                )
                self.assertGreaterEqual(offset, runtime_radius * 2.0 + 0.25)

    def test_player_packed_movement_and_literal_self_logic_are_rejected_safely(self) -> None:
        self.document.set_selection(SelectionRef("node", "player"))
        with self.assertRaisesRegex(ValueError, "Keep one Player"):
            self.document.reusable_object_metadata_snapshot("Another Player")

        self.document.set_selection(SelectionRef("node", "goal"))
        with self.assertRaisesRegex(ValueError, "Movement Pattern"):
            self.document.reusable_object_metadata_snapshot("Orbiting Goal")

        self.document.set_selection(SelectionRef("node", "crystal_garden"))
        with self.assertRaisesRegex(ValueError, "Populate Area"):
            self.document.reusable_object_metadata_snapshot("Whole Garden")

        self.document.set_selection(SelectionRef("node", "floor"))
        repeatable = next(
            graph
            for graph in self.project.metadata["visual_graphs"]
            if graph["id"] == "repeatable_number_lesson"
        )
        constant = next(
            node for node in repeatable["nodes"] if node["id"] == "pick_garden_number"
        )
        constant["type"] = "value.constant"
        constant["properties"] = {"value": "floor"}
        action = next(
            node
            for node in repeatable["nodes"]
            if node["id"] == "remember_garden_number"
        )
        action["type"] = "action.set_active"
        action["properties"] = {"active": True}
        data_link = next(
            link
            for link in repeatable["links"]
            if link["source_node"] == "pick_garden_number"
        )
        data_link["target_port"] = "entity"
        with self.assertRaisesRegex(ValueError, "Choose This Object"):
            self.document.reusable_object_metadata_snapshot("Literal Floor")

    def test_saved_snapshot_does_not_follow_source_transform_or_material_look(self) -> None:
        original_material = copy.deepcopy(self.project.materials["floor"])
        metadata, reusable = self.document.reusable_object_metadata_snapshot(
            "Smart Floor"
        )
        self.document.replace_reusable_objects(
            self.project.nodes, metadata, self.document.selection
        )

        source = self.document.entity(SelectionRef("node", "floor"))
        moved = replace(
            source,
            transform=replace(source.transform, translation=(100.0, 2.0, 100.0)),
        )
        nodes = tuple(
            moved if node.id == source.id else node for node in self.project.nodes
        )
        self.document.replace_scene_objects(
            nodes,
            SelectionRef("node", "floor"),
        )
        look_nodes, look_materials = self.document.material_look_snapshot(
            SelectionRef("node", "floor"),
            "metal",
        )
        self.document.replace_material_look(
            look_nodes,
            look_materials,
            SelectionRef("node", "floor"),
        )

        stored = self.document.reusable_objects()[0]
        edited_source = self.document.entity(SelectionRef("node", "floor"))
        self.assertEqual(stored.node.transform, reusable.node.transform)
        self.assertEqual(stored.node.material_id, "floor")
        self.assertNotEqual(edited_source.material_id, "floor")
        self.assertEqual(self.project.materials["floor"], original_material)
        instance = self.document.instantiate_reusable_object_record(stored.id)
        self.assertEqual(instance.material_id, "floor")

    def test_malformed_or_missing_resource_definition_fails_project_validation(self) -> None:
        source = self.project.nodes[0].to_dict()
        source["mesh_id"] = "missing_mesh"
        self.project.metadata[REUSABLE_OBJECTS_KEY] = [
            {"id": "broken", "label": "Broken", "node": source}
        ]
        report = self.project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        issue = next(issue for issue in report.issues if issue.code == "reusable.invalid")
        self.assertIn("missing mesh", issue.message)

        self.project.metadata[REUSABLE_OBJECTS_KEY] = [
            {"label": "Missing ID", "node": self.project.nodes[0].to_dict()}
        ]
        report = self.project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        issue = next(issue for issue in report.issues if issue.code == "reusable.invalid")
        self.assertIn("missing required id", issue.message)

    def test_raw_unsafe_definitions_cannot_bypass_project_or_placement_validation(
        self,
    ) -> None:
        cases = (
            ("player", "unique Player"),
            ("goal", "Movement Pattern"),
            ("crystal_garden", "Populate Area"),
        )
        for source_id, expected_message in cases:
            with self.subTest(source_id=source_id):
                project = first_steps_mobile3d_project()
                source = next(node for node in project.nodes if node.id == source_id)
                project.metadata[REUSABLE_OBJECTS_KEY] = [
                    {
                        "id": f"unsafe_{source_id}",
                        "label": f"Unsafe {source_id}",
                        "node": source.to_dict(),
                    }
                ]
                report = project.validate(raise_on_error=False)
                self.assertFalse(report.passed)
                issue = next(
                    issue for issue in report.issues if issue.code == "reusable.invalid"
                )
                self.assertIn(expected_message, issue.message)

        player = next(node for node in self.project.nodes if node.id == "player")
        self.project.metadata[REUSABLE_OBJECTS_KEY] = [
            {"id": "unsafe_player", "label": "Unsafe Player", "node": player.to_dict()}
        ]
        with self.assertRaisesRegex(ValueError, "unique Player"):
            self.document.instantiate_reusable_object_record("unsafe_player")

    def test_shared_graph_edits_after_save_are_revalidated(self) -> None:
        for indirect in (False, True):
            with self.subTest(indirect=indirect):
                project = first_steps_mobile3d_project()
                document = EditorDocument()
                document.create(project)
                document.set_selection(SelectionRef("node", "floor"))
                metadata, _ = document.reusable_object_metadata_snapshot("Smart Floor")
                document.replace_reusable_objects(
                    project.nodes,
                    metadata,
                    document.selection,
                )
                graph = next(
                    value
                    for value in project.metadata["visual_graphs"]
                    if value["id"] == "repeatable_number_lesson"
                )
                if not indirect:
                    graph["nodes"][1]["properties"]["entity"] = "floor"
                else:
                    graph["nodes"][0]["type"] = "value.constant"
                    graph["nodes"][0]["properties"] = {"value": "floor"}
                    graph["nodes"][1]["type"] = "action.set_active"
                    graph["nodes"][1]["properties"] = {"active": True}
                    graph["links"][0]["target_port"] = "entity"

                report = project.validate(raise_on_error=False)
                self.assertFalse(report.passed)
                issue = next(
                    issue for issue in report.issues if issue.code == "reusable.invalid"
                )
                self.assertIn("This object", issue.message)

    def test_malformed_instance_provenance_is_rejected(self) -> None:
        for malformed in ("", 7, {}, {"id": 7}):
            with self.subTest(malformed=malformed):
                project = first_steps_mobile3d_project()
                node = project.nodes[0]
                metadata = copy.deepcopy(node.metadata)
                metadata[REUSABLE_INSTANCE_KEY] = malformed
                project.nodes = (replace(node, metadata=metadata), *project.nodes[1:])

                report = project.validate(raise_on_error=False)
                self.assertFalse(report.passed)
                issue = next(
                    issue for issue in report.issues if issue.code == "reusable.invalid"
                )
                self.assertIn("non-empty saved object id string", issue.message)

    def test_library_adds_no_native_records_or_bytes_beyond_project_fingerprint(self) -> None:
        before_hash = self.project.content_hash().encode("ascii")
        before = compile_scene_pack_bytes(self.project)
        graph_before = compile_graph_pack_bytes(self.project)
        polar_before = compile_polar_pack_bytes(self.project)
        scatter_before = compile_scatter_pack_bytes(self.project)
        metadata, _ = self.document.reusable_object_metadata_snapshot("Smart Floor")
        self.document.replace_reusable_objects(
            self.project.nodes, metadata, self.document.selection
        )
        after_hash = self.project.content_hash().encode("ascii")
        after = compile_scene_pack_bytes(self.project)

        self.assertEqual(len(after), len(before))
        self.assertNotEqual(before_hash, after_hash)
        hash_offset = before.index(before_hash)
        self.assertEqual(after[hash_offset : hash_offset + 64], after_hash)
        self.assertEqual(
            before[:hash_offset] + before[hash_offset + 64 :],
            after[:hash_offset] + after[hash_offset + 64 :],
        )
        self.assertEqual(inspect_scene_pack(before)["node_count"], 4)
        self.assertEqual(inspect_scene_pack(after)["node_count"], 4)
        self.assertEqual(compile_graph_pack_bytes(self.project), graph_before)
        self.assertEqual(compile_polar_pack_bytes(self.project), polar_before)
        self.assertEqual(compile_scatter_pack_bytes(self.project), scatter_before)

        instance = self.document.instantiate_reusable_object_record("smart_floor")
        self.document.replace_reusable_objects(
            (*self.project.nodes, instance),
            metadata,
            SelectionRef("node", instance.id),
        )
        graph_after_instance = inspect_graph_pack(
            compile_graph_pack_bytes(self.project)
        )
        self.assertEqual(graph_after_instance["binding_count"], 8)
        self.assertIn(
            {
                "graph": "repeatable_number_lesson",
                "scope": "node",
                "scene_node_index": 4,
            },
            graph_after_instance["bindings"],
        )
        self.assertEqual(compile_polar_pack_bytes(self.project), polar_before)
        self.assertEqual(compile_scatter_pack_bytes(self.project), scatter_before)
        placed_scene = compile_scene_pack_bytes(self.project)
        self.assertEqual(inspect_scene_pack(placed_scene)["node_count"], 5)
        self.assertGreater(len(placed_scene), len(after))


class ReusableObjectEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.new_3d_project()
        self.window.document.set_selection(SelectionRef("node", "floor"))
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def _save_floor(self) -> None:
        with patch(
            "ugts_kc3.editor.main_window.QInputDialog.getText",
            return_value=("Smart Floor", True),
        ):
            self.window.hierarchy.save_reusable_button.click()
        self.app.processEvents()

    def test_save_reusable_is_one_undo_step_and_resources_explain_it(self) -> None:
        before_nodes = copy.deepcopy(self.window.document.project.nodes)
        self._save_floor()

        self.assertEqual(self.window.undo_stack.count(), 1)
        self.assertEqual(len(self.window.document.reusable_objects()), 1)
        self.assertEqual(self.window.document.project.nodes, before_nodes)
        self.assertTrue(self.window.hierarchy.add_reusable_button.isEnabled())
        self.assertIn(
            ("Saved Objects", "1"),
            _tree_texts(self.window.assets_project.assets),
        )
        self.assertIn("changing its Logic Blocks", self.window.status_message.text())

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(self.window.document.reusable_objects(), ())
        self.assertFalse(self.window.hierarchy.add_reusable_button.isEnabled())
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(len(self.window.document.reusable_objects()), 1)

    def test_add_reusable_is_one_undo_step_and_selects_flat_instance(self) -> None:
        self._save_floor()
        before_count = len(self.window.document.project.nodes)
        with patch(
            "ugts_kc3.editor.main_window.QInputDialog.getItem",
            return_value=("Smart Floor", True),
        ):
            self.window.hierarchy.add_reusable_button.click()
        self.app.processEvents()

        self.assertEqual(self.window.undo_stack.count(), 2)
        self.assertEqual(len(self.window.document.project.nodes), before_count + 1)
        instance = self.window.document.entity()
        self.assertEqual(instance.id, "smart_floor")
        self.assertEqual(reusable_source_id(instance), "smart_floor")
        self.assertIn(
            ("Smart Floor", "1 placed · Floor"),
            _tree_texts(self.window.assets_project.assets),
        )
        hierarchy_rows = _tree_texts(self.window.hierarchy.tree)
        self.assertIn(("Smart Floor", "Saved Object"), hierarchy_rows)

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(len(self.window.document.project.nodes), before_count)
        self.assertEqual(self.window.document.selection.object_id, "floor")
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(len(self.window.document.project.nodes), before_count + 1)
        self.assertEqual(self.window.document.selection.object_id, "smart_floor")
        self.assertTrue(self.window.document.validate().passed)

    def test_save_load_keeps_library_and_clean_index_dirty_semantics(self) -> None:
        self._save_floor()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "project.json"
            self.window.document.save(path)
            self.window.undo_stack.setClean()
            self.assertFalse(self.window.document.is_dirty)

            self.window.undo_stack.undo()
            self.app.processEvents()
            self.assertTrue(self.window.document.is_dirty)
            self.window.undo_stack.redo()
            self.app.processEvents()
            self.assertFalse(self.window.document.is_dirty)

            loaded = Mobile3DProject.load(path)
            loaded_document = EditorDocument()
            loaded_document.create(loaded)
            self.assertEqual(
                loaded_document.reusable_objects()[0].label,
                "Smart Floor",
            )

    def test_remove_saved_keeps_placed_object_and_is_atomic(self) -> None:
        self._save_floor()
        with patch(
            "ugts_kc3.editor.main_window.QInputDialog.getItem",
            return_value=("Smart Floor", True),
        ):
            self.window.hierarchy.add_reusable_button.click()
        self.app.processEvents()
        placed_id = self.window.document.selection.object_id

        with patch(
            "ugts_kc3.editor.main_window.QInputDialog.getItem",
            return_value=("Smart Floor", True),
        ):
            self.window.hierarchy.remove_reusable_button.click()
        self.app.processEvents()

        self.assertEqual(self.window.undo_stack.count(), 3)
        self.assertEqual(self.window.document.reusable_objects(), ())
        placed = next(
            node for node in self.window.document.project.nodes if node.id == placed_id
        )
        self.assertIsNone(reusable_source_id(placed))
        self.assertIn(("Smart Floor", "3D Object"), _tree_texts(self.window.hierarchy.tree))
        self.assertIn("Placed objects stayed", self.window.status_message.text())

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(len(self.window.document.reusable_objects()), 1)
        placed = next(
            node for node in self.window.document.project.nodes if node.id == placed_id
        )
        self.assertEqual(reusable_source_id(placed), "smart_floor")
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(self.window.document.reusable_objects(), ())

    def test_saved_object_controls_are_contextual_and_3d_only(self) -> None:
        hierarchy = self.window.hierarchy
        self.assertFalse(hierarchy.add_button.isHidden())
        self.assertFalse(hierarchy.duplicate_button.isHidden())
        self.assertFalse(hierarchy.delete_button.isHidden())
        self.assertFalse(self.window.hierarchy.save_reusable_button.isHidden())
        self.assertTrue(self.window.hierarchy.add_reusable_button.isHidden())
        self.assertTrue(self.window.hierarchy.remove_reusable_button.isHidden())

        self.window.document.set_selection(None)
        self.app.processEvents()
        self.assertFalse(hierarchy.add_button.isHidden())
        self.assertTrue(hierarchy.duplicate_button.isHidden())
        self.assertTrue(hierarchy.delete_button.isHidden())
        self.assertTrue(hierarchy.save_reusable_button.isHidden())

        self.window.document.set_selection(SelectionRef("node", "floor"))
        self._save_floor()
        self.assertFalse(hierarchy.add_reusable_button.isHidden())
        self.assertFalse(hierarchy.remove_reusable_button.isHidden())

        hierarchy.set_authoring_enabled(False)
        self.assertFalse(hierarchy.add_button.isHidden())
        self.assertFalse(hierarchy.add_button.isEnabled())
        self.assertTrue(hierarchy.duplicate_button.isHidden())
        self.assertTrue(hierarchy.delete_button.isHidden())
        self.assertTrue(hierarchy.save_reusable_button.isHidden())
        self.assertTrue(hierarchy.add_reusable_button.isHidden())
        self.assertTrue(hierarchy.remove_reusable_button.isHidden())
        hierarchy.set_authoring_enabled(True)

        self.window.document.set_dirty(False)
        self.window.new_2d_project()
        self.app.processEvents()
        self.assertTrue(self.window.hierarchy.save_reusable_button.isHidden())
        self.assertTrue(self.window.hierarchy.add_reusable_button.isHidden())
        self.assertTrue(self.window.hierarchy.remove_reusable_button.isHidden())


if __name__ == "__main__":
    unittest.main()
