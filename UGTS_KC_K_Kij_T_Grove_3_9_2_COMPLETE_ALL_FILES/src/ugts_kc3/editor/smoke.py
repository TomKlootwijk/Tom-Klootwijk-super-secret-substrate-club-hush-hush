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

from PySide6.QtWidgets import QApplication  # noqa: E402

from .main_window import EditorMainWindow  # noqa: E402


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
    window.play()
    window._play_frame()
    window.stop()
    app.processEvents()

    window.document.set_dirty(False)
    window.new_3d_project()
    app.processEvents()
    three_d_items = len(window.viewport.scene().items())
    window.play()
    window._play_frame()
    window.stop()
    app.processEvents()

    result = {
        "welcome": welcome_ok,
        "2d_scene_items": two_d_items,
        "3d_scene_items": three_d_items,
        "learner_graph": graph.get("id"),
        "learner_nodes": graph_ids,
        "passed": bool(
            welcome_ok
            and two_d_items > 0
            and three_d_items > 0
            and graph.get("id") == "dash_counter"
            and "when_dash" in graph_ids
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
