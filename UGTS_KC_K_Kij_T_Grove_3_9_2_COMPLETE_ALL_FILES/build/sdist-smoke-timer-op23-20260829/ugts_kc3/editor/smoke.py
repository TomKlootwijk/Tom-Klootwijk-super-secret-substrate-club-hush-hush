"""Small headless startup check for packaging and CI environments.

Run with ``python -m ugts_kc3.editor.smoke``.  It creates no project or build
files and exercises the welcome page, both renderers, the learner graph, and
the real preview runtimes.
"""
from __future__ import annotations

import json
import os
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem  # noqa: E402

from .main_window import EditorMainWindow  # noqa: E402
from .scene_view import EntityGraphicsItem  # noqa: E402


def run_offscreen_smoke() -> dict[str, Any]:
    app = QApplication.instance() or QApplication([])
    window = EditorMainWindow()
    window.show()
    app.processEvents()
    welcome_ok = window.central_stack.currentWidget() is window.welcome

    window.new_2d_project()
    app.processEvents()
    graph = window.document.graph_data()
    graph_ids = [node.get("id") for node in graph.get("nodes", [])]
    two_d_items = len(window.viewport.scene().items())
    entity_item = next(
        item
        for item in window.viewport.scene().items()
        if isinstance(item, EntityGraphicsItem)
    )
    click_position = window.viewport.mapFromScene(entity_item.sceneBoundingRect().center())
    QTest.mouseClick(
        window.viewport.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        click_position,
    )
    app.processEvents()
    click_selection_ok = bool(
        window.document.selection is not None
        and window.document.selection.object_id == entity_item.object_id
    )
    original_2d_count = len(window.document.scene_objects())
    window.hierarchy.add_button.click()
    added_2d_id = window.document.selection.object_id if window.document.selection else ""
    window.undo_stack.undo()
    add_2d_undo_ok = len(window.document.scene_objects()) == original_2d_count
    window.undo_stack.redo()
    window.hierarchy.duplicate_button.click()
    copied_2d_id = window.document.selection.object_id if window.document.selection else ""
    window.hierarchy.delete_button.click()
    delete_2d_ok = len(window.document.scene_objects()) == original_2d_count + 1
    window.undo_stack.undo()
    delete_2d_undo_ok = len(window.document.scene_objects()) == original_2d_count + 2
    # Return to the template before previewing it; the commands themselves remain tested.
    window.undo_stack.undo()
    window.undo_stack.undo()
    authoring_2d_ok = bool(
        added_2d_id == "new_object"
        and copied_2d_id == "new_object_copy"
        and add_2d_undo_ok
        and delete_2d_ok
        and delete_2d_undo_ok
        and len(window.document.scene_objects()) == original_2d_count
    )
    graph_scene = window.graph_page.graph_scene
    original_position = graph_scene.nodes["one"].pos()
    graph_scene.nodes["one"].setPos(original_position.x() + 32, original_position.y() + 8)
    graph_scene.notify_edited()
    app.processEvents()
    undo_available = window.undo_stack.canUndo()
    edited_graph = window.document.graph_data()
    metadata_preserved = all(
        key in edited_graph.get("metadata", {}) for key in ("title", "lesson", "beginner")
    )
    scene_record = window.document.scene()
    binding_count = 0 if scene_record is None else sum(
        bool(entity.metadata.get("visual_graph")) for entity in scene_record.entities
    )
    window.undo_stack.undo()
    undone = next(
        node for node in window.document.graph_data()["nodes"] if node["id"] == "one"
    )["position"] == [original_position.x(), original_position.y()]
    window.undo_stack.redo()
    window.play()
    window.viewport.pressed_keys.add("space")
    window._play_frame()
    window.viewport.pressed_keys.discard("space")
    score_visible = any(
        isinstance(item, QGraphicsSimpleTextItem)
        and ("Score  1" in item.text() or "Crystals  1" in item.text())
        for item in window.viewport.scene().items()
    )
    window.stop()
    app.processEvents()

    window.document.set_dirty(False)
    window.new_3d_project()
    app.processEvents()
    three_d_items = len(window.viewport.scene().items())
    mobile_graph = window.document.graph_data()
    mobile_apk_target = window.build_output.target.currentData() == "android-apk"
    original_3d_count = len(window.document.scene_objects())
    window.hierarchy.add_button.click()
    added_3d_id = window.document.selection.object_id if window.document.selection else ""
    window.hierarchy.duplicate_button.click()
    copied_3d_id = window.document.selection.object_id if window.document.selection else ""
    window.hierarchy.delete_button.click()
    delete_3d_ok = len(window.document.scene_objects()) == original_3d_count + 1
    window.undo_stack.undo()
    delete_3d_undo_ok = len(window.document.scene_objects()) == original_3d_count + 2
    window.undo_stack.undo()
    window.undo_stack.undo()
    authoring_3d_ok = bool(
        added_3d_id == "new_object"
        and copied_3d_id == "new_object_copy"
        and delete_3d_ok
        and delete_3d_undo_ok
        and len(window.document.scene_objects()) == original_3d_count
    )
    window.play()
    window.viewport.pressed_keys.add("space")
    window._play_frame()
    window.viewport.pressed_keys.discard("space")
    mobile_score_visible = "Score 1" in window.status_message.text()
    window.stop()
    app.processEvents()

    result = {
        "welcome": welcome_ok,
        "2d_scene_items": two_d_items,
        "3d_scene_items": three_d_items,
        "learner_graph": graph.get("id"),
        "learner_nodes": graph_ids,
        "mobile_graph": mobile_graph.get("id"),
        "mobile_apk_target": mobile_apk_target,
        "mobile_score_visible": mobile_score_visible,
        "scene_authoring_2d": authoring_2d_ok,
        "scene_authoring_3d": authoring_3d_ok,
        "selection_click": click_selection_ok,
        "graph_metadata": metadata_preserved,
        "graph_undo": undo_available and undone,
        "single_binding": binding_count == 1,
        "score_visible": score_visible,
        "passed": bool(
            welcome_ok
            and two_d_items > 0
            and three_d_items > 0
            and graph.get("id") == "dash_counter"
            and mobile_graph.get("id") == "dash_lesson"
            and mobile_apk_target
            and mobile_score_visible
            and authoring_2d_ok
            and authoring_3d_ok
            and "when_dash" in graph_ids
            and click_selection_ok
            and metadata_preserved
            and undo_available
            and undone
            and binding_count == 1
            and score_visible
        ),
    }
    window.document.set_dirty(False)
    window.close()
    app.processEvents()
    return result


def main() -> int:
    result = run_offscreen_smoke()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_offscreen_smoke"]
