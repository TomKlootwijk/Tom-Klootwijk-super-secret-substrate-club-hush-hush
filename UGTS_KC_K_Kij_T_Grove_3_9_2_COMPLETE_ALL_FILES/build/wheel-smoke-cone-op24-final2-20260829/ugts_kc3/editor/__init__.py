"""UGTS Studio desktop editor.

The package is optional at runtime: projects and exporters remain usable without
starting Qt.  Call :func:`run_editor` to launch the dockable desktop app, or
instantiate :class:`EditorMainWindow` when embedding it in an existing Qt app.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .document import EditorDocument, SelectionRef
from .graph import GraphPage, VisualGraphScene
from .main_window import EditorMainWindow
from .scene_view import SceneViewport
from .theme import apply_theme


def create_editor_window(project_path: str | Path | None = None) -> EditorMainWindow:
    """Create a themed editor window inside the current Qt application."""

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Create a QApplication first, or call run_editor().")
    apply_theme(app)
    return EditorMainWindow(project_path)


def run_editor(project_path: str | Path | None = None) -> int:
    """Start UGTS Studio and return the Qt process exit code."""

    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("UGTS Studio")
    app.setOrganizationName("UGTS-KC")
    app.setApplicationDisplayName("UGTS Studio")
    apply_theme(app)
    window = EditorMainWindow(project_path)
    window.show()
    # Keep a Python reference when an existing host owns the event loop.
    setattr(app, "_ugts_editor_window", window)
    return app.exec() if owns_application else 0


__all__ = [
    "EditorDocument",
    "EditorMainWindow",
    "GraphPage",
    "SceneViewport",
    "SelectionRef",
    "VisualGraphScene",
    "create_editor_window",
    "run_editor",
]
