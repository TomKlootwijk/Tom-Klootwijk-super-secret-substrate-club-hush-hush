"""Main desktop window for the UGTS Studio project editor."""
from __future__ import annotations

import copy
from pathlib import Path
import time
from typing import Any, Mapping

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import (
    QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence,
    QUndoCommand, QUndoStack,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..androidbuild import (
    AndroidProfileResult,
    build_apk,
    install_apk,
    launch_android_app,
    profile_android_app,
    select_android_device,
)
from ..androidexport import (
    android_application_id,
    build_android_project,
    write_mobile3d_gltf,
)
from ..graphpack import GraphPackError, compile_graph_pack_bytes
from ..mobile3d import Material3DRecord, Mesh3DRecord, Mobile3DProject
from ..project import GameProject
from ..templates import first_steps_project
from ..templates3d import first_steps_mobile3d_project
from ..webexport import build_html5
from .document import EditorDocument, LogicTraceSnapshot, SelectionRef
from .graph import GraphPage
from .scene_view import SceneViewport
from .widgets import (
    AssetsProjectPanel,
    BuildOutputPanel,
    HierarchyPanel,
    InspectorPanel,
    WelcomePage,
    friendly,
)

def _same_transform(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> bool:
    if a is None or b is None or set(a) != set(b):
        return False

    def flatten(value: Any):
        if isinstance(value, (tuple, list)):
            for item in value:
                yield from flatten(item)
        else:
            yield float(value)

    left = [value for key in sorted(a) for value in flatten(a[key])]
    right = [value for key in sorted(b) for value in flatten(b[key])]
    return len(left) == len(right) and all(abs(x - y) <= 1.0e-9 for x, y in zip(left, right))


def _safe_build_slug(value: Any) -> str:
    text = "".join(
        character if character.isascii() and (character.isalnum() or character in "-_") else "_"
        for character in str(value)
    )
    return text.strip("_-")[:64] or "game"


def _phone_profile_lines(result: AndroidProfileResult) -> tuple[str, ...]:
    """Turn one technical capture into short, child-readable Output messages."""

    device = result.model or result.serial
    headline = (
        f"{result.summary} on {device}: {result.effective_fps:.2f} FPS, "
        f"middle frame {result.frame_ms_p50:.3f} ms, slow-frame edge "
        f"{result.frame_ms_p95:.3f} ms."
    )
    details = [
        headline,
        (
            f"Watched {result.frame_intervals} frame gaps in {result.samples} samples; "
            f"{result.intervals_over_1_5_vsync} missed the active display rhythm."
        ),
    ]
    if result.pss_kib_min is not None and result.pss_kib_max is not None:
        details.append(
            "Game memory (PSS): "
            f"{result.pss_kib_min / 1024:.1f}–{result.pss_kib_max / 1024:.1f} MiB."
        )
    if result.gpu_c_min is not None and result.gpu_c_max is not None:
        details.append(
            f"GPU temperature: {result.gpu_c_min:.1f}–{result.gpu_c_max:.1f} °C."
        )
    if result.crash_buffer_lines:
        details.append(
            f"Android reported {result.crash_buffer_lines} crash-buffer line(s) for this run."
        )
    details.extend(result.warnings)
    return tuple(details)


class TransformCommand(QUndoCommand):
    def __init__(
        self,
        document: EditorDocument,
        selection: SelectionRef,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
    ) -> None:
        super().__init__(f"Move {friendly(selection.object_id)}")
        self.document = document
        self.selection = selection
        self.before = copy.deepcopy(dict(before))
        self.after = copy.deepcopy(dict(after))
        self.before_dirty = document.is_dirty

    def undo(self) -> None:
        self.document.set_transform(self.selection, self.before)
        self.document.set_dirty(self.before_dirty)

    def redo(self) -> None:
        self.document.set_transform(self.selection, self.after)


class GraphCommand(QUndoCommand):
    def __init__(
        self,
        document: EditorDocument,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
    ) -> None:
        super().__init__("Edit logic blocks")
        self.document = document
        self.before = copy.deepcopy(dict(before))
        self.after = copy.deepcopy(dict(after))
        self.selection = document.selection
        self.before_dirty = document.is_dirty
        self.before_storage = document.graph_storage_snapshot(self.selection)
        self.after_storage = None
        self.bindings_changed = False

    def undo(self) -> None:
        self.document.restore_graph_storage(
            self.before_storage,
            bindings_changed=self.bindings_changed,
        )
        self.document.set_dirty(self.before_dirty)

    def redo(self) -> None:
        if self.after_storage is None:
            self.document.set_graph_data(self.after, self.selection)
            self.after_storage = self.document.graph_storage_snapshot(self.selection)
            self.bindings_changed = (
                self.before_storage.object_metadata
                != self.after_storage.object_metadata
            )
            return
        self.document.restore_graph_storage(
            self.after_storage,
            bindings_changed=self.bindings_changed,
        )


class SceneObjectsCommand(QUndoCommand):
    """Undoable replacement of only one scene's entity/node records."""

    def __init__(
        self,
        document: EditorDocument,
        text: str,
        before: tuple[Any, ...],
        after: tuple[Any, ...],
        before_selection: SelectionRef | None,
        after_selection: SelectionRef | None,
        scene_id: str | None,
    ) -> None:
        super().__init__(text)
        self.document = document
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.before_selection = before_selection
        self.after_selection = after_selection
        self.scene_id = scene_id
        self.before_dirty = document.is_dirty

    def undo(self) -> None:
        self.document.replace_scene_objects(
            self.before, self.before_selection, self.scene_id
        )
        self.document.set_dirty(self.before_dirty)

    def redo(self) -> None:
        self.document.replace_scene_objects(
            self.after, self.after_selection, self.scene_id
        )


class MeshResourcesCommand(QUndoCommand):
    """Undoable replacement of a mobile-3D project's mesh resources."""

    def __init__(
        self,
        document: EditorDocument,
        text: str,
        before: Mapping[str, Mesh3DRecord],
        after: Mapping[str, Mesh3DRecord],
    ) -> None:
        super().__init__(text)
        self.document = document
        self.before = copy.deepcopy(dict(before))
        self.after = copy.deepcopy(dict(after))
        self.before_dirty = document.is_dirty

    def undo(self) -> None:
        self.document.replace_mesh_resources(self.before)
        self.document.set_dirty(self.before_dirty)

    def redo(self) -> None:
        self.document.replace_mesh_resources(self.after)


class MaterialLookCommand(QUndoCommand):
    """One undoable material edit, including any safe clone and node rebind."""

    def __init__(
        self,
        document: EditorDocument,
        text: str,
        before_nodes: tuple[Any, ...],
        after_nodes: tuple[Any, ...],
        before_materials: Mapping[str, Material3DRecord],
        after_materials: Mapping[str, Material3DRecord],
        selection: SelectionRef,
    ) -> None:
        super().__init__(text)
        self.document = document
        self.before_nodes = copy.deepcopy(before_nodes)
        self.after_nodes = copy.deepcopy(after_nodes)
        self.before_materials = copy.deepcopy(dict(before_materials))
        self.after_materials = copy.deepcopy(dict(after_materials))
        self.selection = selection
        self.before_dirty = document.is_dirty

    def undo(self) -> None:
        self.document.replace_material_look(
            self.before_nodes, self.before_materials, self.selection
        )
        self.document.set_dirty(self.before_dirty)

    def redo(self) -> None:
        self.document.replace_material_look(
            self.after_nodes, self.after_materials, self.selection
        )


class MovementPatternCommand(QUndoCommand):
    """Undoable packed-movement edit spanning node records and shared profiles."""

    def __init__(
        self,
        document: EditorDocument,
        text: str,
        before_nodes: tuple[Any, ...],
        after_nodes: tuple[Any, ...],
        before_profiles: Mapping[str, Any],
        after_profiles: Mapping[str, Any],
        selection: SelectionRef,
    ) -> None:
        super().__init__(text)
        self.document = document
        self.before_nodes = copy.deepcopy(before_nodes)
        self.after_nodes = copy.deepcopy(after_nodes)
        self.before_profiles = copy.deepcopy(dict(before_profiles))
        self.after_profiles = copy.deepcopy(dict(after_profiles))
        self.selection = selection
        self.before_dirty = document.is_dirty

    def undo(self) -> None:
        self.document.replace_movement_patterns(
            self.before_nodes, self.before_profiles, self.selection
        )
        self.document.set_dirty(self.before_dirty)

    def redo(self) -> None:
        self.document.replace_movement_patterns(
            self.after_nodes, self.after_profiles, self.selection
        )


class BuildWorker(QObject):
    finished = Signal(object)
    partial = Signal(object)
    failed = Signal(str)

    def __init__(self, project: GameProject | Mobile3DProject, target: str, destination: Path) -> None:
        super().__init__()
        self.project = project
        self.target = target
        self.destination = destination

    @Slot()
    def run(self) -> None:
        try:
            if self.target == "html5" and isinstance(self.project, GameProject):
                result = build_html5(self.project, self.destination, clean=True)
                summary = f"Web game built: {len(result.files)} files, {result.total_bytes / 1024:.1f} KiB"
                folder = result.output_dir
            elif self.target in {"android", "android-apk", "android-install"} and isinstance(self.project, Mobile3DProject):
                install_serial: str | None = None
                if self.target == "android-install":
                    install_serial = select_android_device().serial
                result = build_android_project(self.project, self.destination, clean=True)
                if self.target == "android":
                    summary = f"Android project built: {result.file_count} files, {result.total_bytes / 1024:.1f} KiB"
                    folder = result.output_dir
                else:
                    compiled = build_apk(result.output_dir, "poco-debug")
                    size_mib = compiled.apk.stat().st_size / (1024 * 1024)
                    summary = f"Poco X7 Pro APK built: {compiled.apk.name} ({size_mib:.2f} MiB)"
                    folder = compiled.apk.parent
                    if self.target == "android-install":
                        try:
                            installed = install_apk(compiled.apk, serial=install_serial)
                            summary += f" and installed on {installed.serial}"
                        except Exception as exc:
                            self.partial.emit((summary, "install", str(exc), folder))
                            return
                        try:
                            launch_android_app(
                                compiled.application_id,
                                serial=install_serial,
                            )
                            summary += " and opened"
                        except Exception as exc:
                            self.partial.emit((summary, "launch", str(exc), folder))
                            return
            elif self.target == "gltf" and isinstance(self.project, Mobile3DProject):
                write_mobile3d_gltf(self.project, self.destination)
                summary = f"3D preview exported: {self.destination.name}"
                folder = self.destination.parent
            else:
                raise ValueError("That build target does not match this project.")
            self.finished.emit((summary, folder))
        except Exception as exc:
            self.failed.emit(str(exc))


class PhoneProfileWorker(QObject):
    """Run the read-only ADB sampler away from Qt's GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        application_id: str,
        *,
        seconds: float = 30.0,
        sample_seconds: float = 5.0,
    ) -> None:
        super().__init__()
        self.application_id = application_id
        self.seconds = float(seconds)
        self.sample_seconds = float(sample_seconds)

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(
                profile_android_app(
                    self.application_id,
                    seconds=self.seconds,
                    sample_seconds=self.sample_seconds,
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class EditorMainWindow(QMainWindow):
    """Godot-inspired, dockable authoring window for both UGTS project models."""

    def __init__(self, project_path: str | Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("UGTSEditorMainWindow")
        self.setWindowTitle("UGTS Studio")
        self.resize(1480, 900)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.document = EditorDocument(self)
        self.undo_stack = QUndoStack(self)
        self._playing = False
        self._active_graph_id: str | None = None
        self._logic_trace_snapshot: LogicTraceSnapshot | None = None
        self._preserve_logic_trace_on_stop = False
        self._frame_count = 0
        self._fps_started = time.perf_counter()
        self._build_thread: QThread | None = None
        self._build_worker: BuildWorker | None = None
        self._profile_thread: QThread | None = None
        self._profile_worker: PhoneProfileWorker | None = None
        self._create_central_area()
        self._create_docks()
        self._create_actions()
        self._create_menus_and_toolbar()
        self._create_status_bar()
        self._connect_signals()
        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.play_timer.setInterval(16)
        self.play_timer.timeout.connect(self._play_frame)
        self._show_welcome_state()
        if project_path is not None:
            QTimer.singleShot(0, lambda: self.open_project(project_path))

    def _create_central_area(self) -> None:
        self.central_stack = QStackedWidget()
        self.welcome = WelcomePage()
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setDocumentMode(True)
        scene_page = QWidget()
        scene_layout = QVBoxLayout(scene_page)
        scene_layout.setContentsMargins(0, 0, 0, 0)
        scene_layout.setSpacing(0)
        scene_bar = QWidget()
        scene_bar.setObjectName("GraphToolbar")
        scene_bar_layout = QHBoxLayout(scene_bar)
        scene_bar_layout.setContentsMargins(12, 7, 12, 7)
        self.scene_label = QLabel("Scene")
        self.scene_label.setObjectName("MutedLabel")
        self.fit_button = QPushButton("Fit Scene")
        self.fit_button.setToolTip("Shows the whole game world")
        self.focus_button = QPushButton("Focus Selected")
        self.focus_button.setToolTip("Zooms to the selected object")
        scene_bar_layout.addWidget(self.scene_label, 1)
        scene_bar_layout.addWidget(self.fit_button)
        scene_bar_layout.addWidget(self.focus_button)
        self.viewport = SceneViewport()
        scene_layout.addWidget(scene_bar)
        scene_layout.addWidget(self.viewport, 1)
        self.graph_page = GraphPage()
        self._scene_tab_index = self.editor_tabs.addTab(scene_page, "Scene")
        self._logic_tab_index = self.editor_tabs.addTab(self.graph_page, "Logic Blocks")
        self.central_stack.addWidget(self.welcome)
        self.central_stack.addWidget(self.editor_tabs)
        self.setCentralWidget(self.central_stack)

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "") + "Dock")
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(area, dock)
        return dock

    def _create_docks(self) -> None:
        self.hierarchy = HierarchyPanel()
        self.inspector = InspectorPanel()
        self.assets_project = AssetsProjectPanel()
        self.build_output = BuildOutputPanel()
        self.hierarchy_dock = self._dock("Scene Tree", self.hierarchy, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.assets_dock = self._dock("Resources & Project", self.assets_project, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.inspector_dock = self._dock("Inspector", self.inspector, Qt.DockWidgetArea.RightDockWidgetArea)
        self.output_dock = self._dock("Output & Builds", self.build_output, Qt.DockWidgetArea.BottomDockWidgetArea)
        for dock in (self.hierarchy_dock, self.assets_dock):
            dock.setMinimumWidth(230)
            dock.setMaximumWidth(350)
        self.inspector_dock.setMinimumWidth(275)
        self.inspector_dock.setMaximumWidth(390)
        self.splitDockWidget(self.hierarchy_dock, self.assets_dock, Qt.Orientation.Vertical)
        self.resizeDocks([self.hierarchy_dock, self.assets_dock], [510, 290], Qt.Orientation.Vertical)
        self.resizeDocks([self.hierarchy_dock, self.inspector_dock], [270, 320], Qt.Orientation.Horizontal)
        self.resizeDocks([self.output_dock], [180], Qt.Orientation.Vertical)

    def _action(
        self,
        text: str,
        icon: QStyle.StandardPixmap,
        shortcut: QKeySequence.StandardKey | str | None,
        callback,
        tooltip: str,
    ) -> QAction:
        action = QAction(self.style().standardIcon(icon), text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
        action.triggered.connect(callback)
        return action

    def _create_actions(self) -> None:
        self.new_2d_action = self._action(
            "New 2D Game", QStyle.StandardPixmap.SP_FileIcon, "Ctrl+Alt+N", self.new_2d_project,
            "Starts from a safe copy of the beginner 2D template",
        )
        self.new_3d_action = self._action(
            "New Mobile 3D Game", QStyle.StandardPixmap.SP_ComputerIcon, "Ctrl+Shift+N", self.new_3d_project,
            "Starts from a safe copy of the Android 3D template",
        )
        self.open_action = self._action(
            "Open Project…", QStyle.StandardPixmap.SP_DialogOpenButton, QKeySequence.StandardKey.Open,
            self.open_project_dialog, "Open an existing project.json",
        )
        self.import_3d_shape_action = self._action(
            "Import 3D Shape…", QStyle.StandardPixmap.SP_DialogOpenButton, None,
            lambda: self.import_3d_shape(),
            "Import a Wavefront OBJ as an editable project shape",
        )
        self.save_action = self._action(
            "Save", QStyle.StandardPixmap.SP_DialogSaveButton, QKeySequence.StandardKey.Save,
            self.save_project, "Save changes to this project",
        )
        self.save_as_action = self._action(
            "Save As…", QStyle.StandardPixmap.SP_DialogSaveButton, QKeySequence.StandardKey.SaveAs,
            self.save_project_as, "Save a new copy in a location you choose",
        )
        self.exit_action = self._action(
            "Exit", QStyle.StandardPixmap.SP_DialogCloseButton, QKeySequence.StandardKey.Quit,
            self.close, "Close UGTS Studio",
        )
        self.undo_action = self.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.redo_action = self.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.play_action = self._action(
            "Play", QStyle.StandardPixmap.SP_MediaPlay, "F6", self.play,
            "Try the current scene; WASD or arrow keys move and Space acts/jumps",
        )
        self.stop_action = self._action(
            "Stop", QStyle.StandardPixmap.SP_MediaStop, "F8", self.stop,
            "Stop the preview and return to editing",
        )
        self.stop_action.setEnabled(False)
        self.validate_action = self._action(
            "Check Project", QStyle.StandardPixmap.SP_DialogApplyButton, "F7", self.validate_project,
            "Checks the project and explains anything that needs attention",
        )
        self.build_action = self._action(
            "Build Project…", QStyle.StandardPixmap.SP_DriveHDIcon, "Ctrl+B",
            lambda: self._build_requested(str(self.build_output.target.currentData() or "")),
            "Create a playable web, Android, or glTF build",
        )
        self.deploy_action = self._action(
            "Deploy to Phone", QStyle.StandardPixmap.SP_DriveNetIcon, "Ctrl+Shift+D",
            self.deploy_to_phone,
            "Build, install, and open the game on the one authorized ADB phone",
        )
        self.profile_phone_action = self._action(
            "Check Phone", QStyle.StandardPixmap.SP_DialogApplyButton, "Ctrl+Shift+P",
            self.profile_running_phone,
            "Measure the running phone game's frame pace, memory, and heat for 30 seconds",
        )
        self.fit_action = self._action(
            "Fit Scene", QStyle.StandardPixmap.SP_DesktopIcon, "F", self.viewport.fit_scene,
            "Show the whole scene",
        )
        for action in (
            self.save_action,
            self.save_as_action,
            self.import_3d_shape_action,
            self.play_action,
            self.validate_action,
            self.build_action,
            self.deploy_action,
            self.profile_phone_action,
        ):
            action.setEnabled(False)

    def _create_menus_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addActions([self.new_2d_action, self.new_3d_action, self.open_action])
        file_menu.addSeparator()
        file_menu.addAction(self.import_3d_shape_action)
        file_menu.addSeparator()
        file_menu.addActions([self.save_action, self.save_as_action])
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        edit_menu = self.menuBar().addMenu("Edit")
        edit_menu.addActions([self.undo_action, self.redo_action])
        project_menu = self.menuBar().addMenu("Project")
        project_menu.addActions([
            self.play_action, self.stop_action, self.validate_action,
            self.build_action, self.deploy_action, self.profile_phone_action,
        ])
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.fit_action)
        view_menu.addSeparator()
        for dock in (self.hierarchy_dock, self.assets_dock, self.inspector_dock, self.output_dock):
            view_menu.addAction(dock.toggleViewAction())

        toolbar = QToolBar("Main Tools")
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        toolbar.addActions([self.open_action, self.save_action])
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.play_action)
        play_widget = toolbar.widgetForAction(self.play_action)
        if play_widget is not None:
            play_widget.setObjectName("PlayButton")
        toolbar.addAction(self.stop_action)
        stop_widget = toolbar.widgetForAction(self.stop_action)
        if stop_widget is not None:
            stop_widget.setObjectName("StopButton")
        toolbar.addSeparator()
        toolbar.addAction(self.validate_action)
        toolbar.addAction(self.build_action)
        toolbar.addAction(self.deploy_action)
        deploy_widget = toolbar.widgetForAction(self.deploy_action)
        if deploy_widget is not None:
            deploy_widget.setObjectName("DeployButton")
        toolbar.addAction(self.profile_phone_action)
        profile_widget = toolbar.widgetForAction(self.profile_phone_action)
        if profile_widget is not None:
            profile_widget.setObjectName("ProfileButton")

    def _create_status_bar(self) -> None:
        self.status_message = QLabel("Ready — open a project or start with a template")
        self.status_kind = QLabel("No project")
        self.status_fps = QLabel("Preview idle")
        self.statusBar().addWidget(self.status_message, 1)
        self.statusBar().addPermanentWidget(self.status_kind)
        self.statusBar().addPermanentWidget(self.status_fps)

    def _connect_signals(self) -> None:
        self.welcome.openRequested.connect(self.open_project_dialog)
        self.welcome.new2dRequested.connect(self.new_2d_project)
        self.welcome.new3dRequested.connect(self.new_3d_project)
        self.fit_button.clicked.connect(self.viewport.fit_scene)
        self.focus_button.clicked.connect(self.viewport.focus_selection)
        self.hierarchy.selectionRequested.connect(self.document.set_selection)
        self.hierarchy.sceneRequested.connect(self.document.set_current_scene)
        self.hierarchy.addRequested.connect(self._add_scene_object)
        self.hierarchy.addTriggerRequested.connect(self._add_trigger_area)
        self.hierarchy.duplicateRequested.connect(self._duplicate_scene_object)
        self.hierarchy.deleteRequested.connect(self._delete_scene_object)
        self.viewport.selectionRequested.connect(self._viewport_selected)
        self.viewport.entityMoved.connect(self._viewport_moved)
        self.viewport.translationPreviewed.connect(self._viewport_translation_previewed)
        self.viewport.gizmoHelpRequested.connect(self._gentle_message)
        self.viewport.mouseScenePosition.connect(
            lambda x, y: self.status_message.setText(f"Scene position  X {x:.1f}   Y {y:.1f}")
        )
        self.inspector.transformEdited.connect(self._inspector_transform_edited)
        self.inspector.resourceEdited.connect(self._inspector_resource_edited)
        self.inspector.materialLookEdited.connect(self._inspector_material_look_edited)
        self.inspector.triggerAreaEdited.connect(self._inspector_trigger_area_edited)
        self.inspector.populationEdited.connect(self._inspector_population_edited)
        self.inspector.movementPatternEdited.connect(self._inspector_movement_pattern_edited)
        self.graph_page.graphEdited.connect(self._graph_edited)
        self.graph_page.graphRequested.connect(self._graph_requested)
        self.graph_page.helpRequested.connect(self._gentle_message)
        self.build_output.buildRequested.connect(self._build_requested)
        self.editor_tabs.currentChanged.connect(self._tab_changed)
        self.document.projectLoaded.connect(self._document_loaded)
        self.document.documentChanged.connect(self._document_dirty_changed)
        self.undo_stack.indexChanged.connect(self._undo_index_changed)
        self.document.sceneChanged.connect(self._scene_changed)
        self.document.selectionChanged.connect(self._selection_changed)
        self.document.transformChanged.connect(self._transform_changed)
        self.document.graphChanged.connect(self._graph_changed)
        self.document.structureChanged.connect(self._structure_changed)
        self.document.logicTraceChanged.connect(self._logic_trace_changed)

    def _show_welcome_state(self) -> None:
        self.central_stack.setCurrentWidget(self.welcome)
        self.hierarchy.set_document(None)
        self.assets_project.set_document(None)
        self.inspector.clear()
        self.build_output.set_kind(None)
        self._set_logic_read_only(False)
        self._clear_logic_trace()

    @staticmethod
    def _repository_root() -> Path:
        return Path(__file__).resolve().parents[3]

    def _maybe_save(self) -> bool:
        if not self.document.is_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Save your changes?",
            f"Would you like to save changes to “{self.document.display_name}” first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def open_project_dialog(self) -> None:
        if not self._maybe_save():
            return
        start = str(self.document.path.parent if self.document.path else self._repository_root())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a UGTS Project", start, "UGTS projects (project.json *.json);;JSON files (*.json)"
        )
        if path:
            self.open_project(path, check_dirty=False)

    def open_project(self, path: str | Path, *, as_copy: bool = False, check_dirty: bool = True) -> bool:
        if check_dirty and not self._maybe_save():
            return False
        try:
            self.stop()
            self.undo_stack.clear()
            self.document.load(path, as_copy=as_copy)
            self.undo_stack.setClean()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Could not open that project", str(exc))
            self._gentle_message("The project stayed unchanged. Choose another project file when ready.")
            return False

    def import_3d_shape(self, path: str | Path | None = None) -> bool:
        """Import one OBJ into the open 3D project as an undoable resource."""

        if self._playing or not isinstance(self.document.project, Mobile3DProject):
            return False
        if path is None:
            start = self.document.path.parent if self.document.path else self._repository_root()
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                "Import a 3D Shape",
                str(start),
                "Wavefront OBJ (*.obj);;All files (*)",
            )
            if not chosen:
                return False
            path = chosen
        try:
            mesh = self.document.imported_obj_mesh(path)
            project = self.document.project
            assert isinstance(project, Mobile3DProject)
            before = dict(project.meshes)
            after = dict(before)
            after[mesh.id] = mesh
            self.undo_stack.push(
                MeshResourcesCommand(
                    self.document,
                    f"Import {friendly(mesh.id)} 3D shape",
                    before,
                    after,
                )
            )
            self.assets_project.setCurrentIndex(0)
            self.build_output.append(
                f"Imported {friendly(mesh.id)}: {len(mesh.vertices)} vertices, "
                f"{len(mesh.triangles)} triangles.",
                "good",
            )
            self._gentle_message(
                f"Imported {friendly(mesh.id)}. Choose it from an object's Shape field."
            )
            return True
        except Exception as exc:
            self.build_output.append(f"3D shape import paused: {exc}", "warning")
            QMessageBox.warning(self, "Could not import that 3D shape", str(exc))
            self._gentle_message("The project stayed unchanged. Choose another OBJ when ready.")
            return False

    def new_2d_project(self) -> None:
        if not self._maybe_save():
            return
        try:
            self.stop()
            self.undo_stack.clear()
            self.document.create(first_steps_project())
            if self.assets_project.show_lesson():
                self.assets_dock.show()
                self.assets_dock.raise_()
            self._gentle_message(
                "Your first game is ready. Press Play, move with WASD, and dash with Space to count points."
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not start the 2D lesson", str(exc))

    def new_3d_project(self) -> None:
        if not self._maybe_save():
            return
        try:
            self.stop()
            self.undo_stack.clear()
            self.document.create(first_steps_mobile3d_project())
            if self.assets_project.show_lesson():
                self.assets_dock.show()
                self.assets_dock.raise_()
            self._gentle_message(
                "Your first mobile game is ready. Press Play, move, and use Space to dash and grow."
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not start the 3D project", str(exc))

    def save_project(self) -> bool:
        if not self.document.is_loaded:
            return False
        if self.document.path is None:
            return self.save_project_as()
        try:
            path = self.document.save()
            self.undo_stack.setClean()
            self.build_output.append(f"Saved {path.name}", "good")
            self._gentle_message("Saved safely.")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "This project was not saved", str(exc))
            self.build_output.append(f"Save paused: {exc}", "warning")
            return False

    def save_project_as(self) -> bool:
        if not self.document.is_loaded:
            return False
        suggested = self.document.path or (self._repository_root() / "my_game" / "project.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Your Project", str(suggested), "UGTS project (project.json *.json)"
        )
        if not path:
            return False
        if not Path(path).suffix:
            path += ".json"
        try:
            saved = self.document.save(path)
            self.undo_stack.setClean()
            self.build_output.append(f"Saved a copy at {saved}", "good")
            self._gentle_message("Saved your new project copy.")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "This project was not saved", str(exc))
            return False

    def _document_loaded(self) -> None:
        self._active_graph_id = None
        self.central_stack.setCurrentWidget(self.editor_tabs)
        self.hierarchy.set_document(self.document)
        self.assets_project.set_document(self.document)
        self.inspector.clear()
        self.viewport.set_document(self.document)
        self.graph_page.set_project_kind(self.document.kind)
        self._load_graph_context()
        self._set_logic_read_only(False)
        self._clear_logic_trace()
        self.build_output.set_kind(self.document.kind)
        self.build_output.append(
            f"Opened {self.document.display_name} as a {'2D' if self.document.kind == '2d' else 'mobile 3D'} project.",
            "good",
        )
        self.status_kind.setText("2D Project" if self.document.kind == "2d" else "Mobile 3D Project")
        self.scene_label.setText(
            f"Scene: {friendly(self.document.current_scene_id or 'Main 3D Scene')}"
        )
        for action in (self.save_action, self.save_as_action, self.play_action, self.validate_action, self.build_action):
            action.setEnabled(True)
        self.import_3d_shape_action.setEnabled(self.document.kind == "3d")
        self.deploy_action.setEnabled(self.document.kind == "3d")
        self.profile_phone_action.setEnabled(self.document.kind == "3d")
        self._update_title()
        self._gentle_message("Ready. Choose an object on the left or click it in the scene.")

    def _document_dirty_changed(self, dirty: bool) -> None:
        self._update_title()

    def _undo_index_changed(self, _index: int) -> None:
        """Keep the save marker aligned with QUndoStack's current clean index.

        Commands remember whether a brand-new, unsaved document was already
        dirty so undoing its first edit does not pretend that it is saved.  A
        later save can move the clean index, though, so the stack becomes the
        authority once the document has a file on disk.
        """

        if not self.document.is_loaded or self.document.path is None:
            return
        self.document.set_dirty(not self.undo_stack.isClean())

    def _update_title(self) -> None:
        if not self.document.is_loaded:
            self.setWindowTitle("UGTS Studio")
            return
        marker = "*" if self.document.is_dirty else ""
        self.setWindowTitle(f"{marker}{self.document.display_name} — UGTS Studio")

    def _scene_changed(self, scene_id: str) -> None:
        self._active_graph_id = None
        self.hierarchy.set_document(self.document)
        self.assets_project.refresh_lesson(self.document)
        self.viewport.refresh(keep_view=False)
        self._load_graph_context()
        self._refresh_logic_trace()
        self.scene_label.setText(f"Scene: {friendly(scene_id)}")
        self._gentle_message(f"Showing {friendly(scene_id)}.")

    def _selection_changed(self, selection: SelectionRef | None) -> None:
        self._active_graph_id = None
        self.hierarchy.set_selection(selection)
        self.inspector.set_selection(self.document, selection)
        self.viewport.set_selected_id(
            None
            if selection is None or selection.kind == "world_graph"
            else selection.object_id
        )
        if selection is None:
            self.status_message.setText("Choose an object to edit it")
        elif selection.kind == "world_graph":
            self.status_message.setText(
                f"World Logic: {friendly(selection.object_id)} — runs for the whole scene"
            )
        else:
            self.status_message.setText(f"Selected {friendly(selection.object_id)}")
        self._load_graph_context()
        self._refresh_logic_trace()

    def _selection_for_record(self, object_id: str) -> SelectionRef:
        kind = "entity" if self.document.kind == "2d" else "node"
        scene_id = self.document.current_scene_id if self.document.kind == "2d" else None
        return SelectionRef(kind, object_id, scene_id)

    def _scene_edit_error(self, message: str) -> None:
        self.build_output.append(f"Scene edit paused: {message}", "warning")
        self._gentle_message(message)
        QMessageBox.information(self, "That object needs to stay for now", message)

    def _add_scene_object(self) -> None:
        if not self.document.is_loaded or self._playing:
            return
        try:
            scene_id = self.document.current_scene_id if self.document.kind == "2d" else None
            before = tuple(self.document.scene_objects(scene_id))
            record = self.document.new_object_record()
            after = before + (record,)
            selection = self._selection_for_record(record.id)
            self.undo_stack.push(
                SceneObjectsCommand(
                    self.document,
                    f"Add {friendly(record.id)}",
                    before,
                    after,
                    self.document.selection,
                    selection,
                    scene_id,
                )
            )
            self._gentle_message(f"Added {friendly(record.id)}. Use the Inspector to place it.")
        except Exception as exc:
            self._scene_edit_error(str(exc))

    def _add_trigger_area(self) -> None:
        if self._playing or not isinstance(self.document.project, Mobile3DProject):
            return
        try:
            before = tuple(self.document.scene_objects())
            record = self.document.new_trigger_area_record()
            selection = SelectionRef("node", record.id)
            self.undo_stack.push(
                SceneObjectsCommand(
                    self.document,
                    f"Add {friendly(record.id)}",
                    before,
                    before + (record,),
                    self.document.selection,
                    selection,
                    None,
                )
            )
            self._gentle_message(
                f"Added {friendly(record.id)}. Enter and Exit Trigger Logic Blocks can react to it."
            )
        except Exception as exc:
            self._scene_edit_error(str(exc))

    def _duplicate_scene_object(self) -> None:
        if not self.document.is_loaded or self._playing:
            return
        try:
            source_selection = self.document.selection
            if source_selection is None:
                raise ValueError("Choose an object in the Scene Tree before making a copy.")
            scene_id = self.document.current_scene_id if self.document.kind == "2d" else None
            before = tuple(self.document.scene_objects(scene_id))
            source_index = next(
                index for index, record in enumerate(before)
                if record.id == source_selection.object_id
            )
            record = self.document.duplicate_object_record(source_selection)
            after = before[: source_index + 1] + (record,) + before[source_index + 1 :]
            selection = self._selection_for_record(record.id)
            self.undo_stack.push(
                SceneObjectsCommand(
                    self.document,
                    f"Duplicate {friendly(source_selection.object_id)}",
                    before,
                    after,
                    source_selection,
                    selection,
                    scene_id,
                )
            )
            self._gentle_message(f"Made {friendly(record.id)} and selected the copy.")
        except Exception as exc:
            self._scene_edit_error(str(exc) or "That object is no longer in the scene.")

    def _delete_scene_object(self) -> None:
        if not self.document.is_loaded or self._playing:
            return
        try:
            selection = self.document.selection
            problem = self.document.deletion_problem(selection)
            if problem:
                raise ValueError(problem)
            assert selection is not None
            scene_id = self.document.current_scene_id if self.document.kind == "2d" else None
            before = tuple(self.document.scene_objects(scene_id))
            source_index = next(
                index for index, record in enumerate(before)
                if record.id == selection.object_id
            )
            after = before[:source_index] + before[source_index + 1 :]
            neighbor = after[min(source_index, len(after) - 1)]
            after_selection = self._selection_for_record(neighbor.id)
            self.undo_stack.push(
                SceneObjectsCommand(
                    self.document,
                    f"Delete {friendly(selection.object_id)}",
                    before,
                    after,
                    selection,
                    after_selection,
                    scene_id,
                )
            )
            self._gentle_message(
                f"Deleted {friendly(selection.object_id)}. Undo brings it straight back."
            )
        except Exception as exc:
            self._scene_edit_error(str(exc) or "That object is no longer in the scene.")

    def _structure_changed(self) -> None:
        self.hierarchy.set_document(self.document)
        self.hierarchy.set_selection(self.document.selection)
        self.viewport.refresh(keep_view=True)
        self.assets_project.set_document(self.document)
        self.inspector.set_selection(self.document, self.document.selection)

    def _graph_edited(self, graph: Mapping[str, Any]) -> None:
        if self._playing:
            # A queued editor signal must never replace the runtime snapshot.
            self._load_graph_context()
            self._refresh_logic_trace()
            return
        context = self.document.graph_authoring_context(self._active_graph_id)
        if context.creation_problem is not None:
            self._load_graph_context()
            self._gentle_message(context.creation_problem)
            return
        before = context.graph
        after = dict(graph)
        if before == after:
            return
        self.undo_stack.push(GraphCommand(self.document, before, after))

    def _load_graph_context(self) -> None:
        if not self.document.is_loaded:
            return
        context = self.document.graph_authoring_context(self._active_graph_id)
        self._active_graph_id = context.active_graph_id
        self.graph_page.set_context(context)

    def _graph_requested(self, graph_id: str) -> None:
        if self._playing:
            return
        self._active_graph_id = str(graph_id)
        self._load_graph_context()
        self._refresh_logic_trace()

    def _graph_changed(self) -> None:
        self._load_graph_context()
        self._refresh_logic_trace()

    def _set_logic_read_only(self, read_only: bool) -> None:
        """Keep the Logic tab visible while preventing Preview-time edits."""

        self.graph_page.set_read_only(read_only)
        self.editor_tabs.setTabEnabled(self._logic_tab_index, True)

    def _logic_trace_for_current_context(self) -> LogicTraceSnapshot | None:
        """Return the newest trail relevant to the graph currently on screen."""

        if not self.document.is_loaded:
            return None
        graph_id = str(self.graph_page.graph_scene.property("graph_id") or "")
        if not graph_id:
            return None
        selection = self.document.selection
        if selection is None:
            return None
        if selection.kind == "world_graph":
            return self.document.logic_trace(graph_id, None)
        if selection.kind in {"entity", "node"}:
            # A graph may be bound to several objects. Never present another
            # object's or the world's run as if it belonged to this object.
            return self.document.logic_trace(graph_id, selection.object_id)
        return None

    def _show_logic_trace(self, snapshot: LogicTraceSnapshot | None) -> None:
        self._logic_trace_snapshot = snapshot
        self.graph_page.show_trace(snapshot)
        count = self.graph_page.trace_count
        title = "Logic Blocks" if count <= 0 else f"Logic Blocks • {count} ran"
        self.editor_tabs.setTabText(self._logic_tab_index, title)

    def _clear_logic_trace(self) -> None:
        self._show_logic_trace(None)

    def _refresh_logic_trace(self) -> None:
        self._show_logic_trace(self._logic_trace_for_current_context())

    def _logic_trace_changed(self, snapshot: LogicTraceSnapshot | None) -> None:
        if self._preserve_logic_trace_on_stop:
            return
        if snapshot is None:
            self._clear_logic_trace()
        else:
            self._refresh_logic_trace()

    def _viewport_selected(self, object_id: str) -> None:
        kind = "entity" if self.document.kind == "2d" else "node"
        self.document.set_selection(SelectionRef(kind, object_id, self.document.current_scene_id))

    def _viewport_moved(self, object_id: str, old_position, new_position) -> None:
        if self._playing:
            return
        kind = "entity" if self.document.kind == "2d" else "node"
        selection = SelectionRef(kind, object_id, self.document.current_scene_id)
        before = self.document.transform(selection)
        if before is None:
            return
        after = copy.deepcopy(before)
        if "position" in before:
            after["position"] = (float(new_position.x()), float(new_position.y()))
        elif "translation" in before:
            try:
                translation = tuple(float(value) for value in new_position)
            except (TypeError, ValueError):
                return
            if len(translation) != 3:
                return
            after["translation"] = translation
        else:
            return
        if _same_transform(before, after):
            return
        self.undo_stack.push(TransformCommand(self.document, selection, before, after))
        if "translation" in after:
            self._gentle_message(
                f"Moved {friendly(object_id)}. Undo brings it straight back."
            )

    def _viewport_translation_previewed(
        self, object_id: str, translation: object
    ) -> None:
        selection = self.document.selection
        if (
            self._playing
            or selection is None
            or selection.object_id != object_id
        ):
            return
        try:
            values = tuple(float(value) for value in translation)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if self.inspector.preview_3d_translation(object_id, values):
            self.status_message.setText(
                f"Placing {friendly(object_id)} — release to keep one undoable move"
            )

    def _inspector_transform_edited(self, transform: Mapping[str, Any]) -> None:
        selection = self.document.selection
        if selection is None or self._playing:
            return
        before = self.document.transform(selection)
        if before is None or _same_transform(before, transform):
            return
        self.undo_stack.push(TransformCommand(self.document, selection, before, transform))

    def _inspector_resource_edited(self, resource_kind: str, resource_id: str) -> None:
        selection = self.document.selection
        if selection is None or self._playing:
            return
        try:
            scene_id = self.document.current_scene_id if self.document.kind == "2d" else None
            before = tuple(self.document.scene_objects(scene_id))
            index = next(
                item_index for item_index, record in enumerate(before)
                if record.id == selection.object_id
            )
            updated = self.document.record_with_resource(
                selection, resource_kind, resource_id
            )
            if updated == before[index]:
                return
            after = before[:index] + (updated,) + before[index + 1 :]
            resource_name = {
                "vector_asset": "picture",
                "mesh": "shape",
                "material": "material",
            }.get(resource_kind, "appearance")
            self.undo_stack.push(
                SceneObjectsCommand(
                    self.document,
                    f"Change {friendly(selection.object_id)} {resource_name}",
                    before,
                    after,
                    selection,
                    selection,
                    scene_id,
                )
            )
            self._gentle_message(
                f"Changed {friendly(selection.object_id)} {resource_name} to {friendly(resource_id)}."
            )
        except Exception as exc:
            self.inspector.set_selection(self.document, selection)
            self.build_output.append(f"Appearance change paused: {exc}", "warning")
            self._gentle_message(str(exc))

    def _inspector_material_look_edited(self, look: str) -> None:
        selection = self.document.selection
        if selection is None or self._playing:
            return
        if look == "custom":
            # Custom describes values that do not match a preset. Selecting it
            # never rewrites an already classified material.
            self.inspector.set_selection(self.document, selection)
            return
        try:
            before_nodes = tuple(self.document.scene_objects())
            before_materials = self.document.material_resources()
            after_nodes, after_materials = self.document.material_look_snapshot(
                selection, look
            )
            before_node_data = [record.to_dict() for record in before_nodes]
            after_node_data = [record.to_dict() for record in after_nodes]
            before_material_data = {
                key: material.to_dict() for key, material in before_materials.items()
            }
            after_material_data = {
                key: material.to_dict() for key, material in after_materials.items()
            }
            if (
                before_node_data == after_node_data
                and before_material_data == after_material_data
            ):
                self.inspector.set_selection(self.document, selection)
                return
            look_name = friendly(look)
            self.undo_stack.push(
                MaterialLookCommand(
                    self.document,
                    f"Set {friendly(selection.object_id)} Material Look to {look_name}",
                    before_nodes,
                    after_nodes,
                    before_materials,
                    after_materials,
                    selection,
                )
            )
            self._gentle_message(
                f"{friendly(selection.object_id)} now uses {look_name}. "
                "Its colour stays the same, and Undo restores the previous material."
            )
        except Exception as exc:
            self.inspector.set_selection(self.document, selection)
            self.build_output.append(f"Material Look change paused: {exc}", "warning")
            self._gentle_message(str(exc))

    def _inspector_trigger_area_edited(self, values: Mapping[str, Any]) -> None:
        selection = self.document.selection
        if selection is None or self._playing:
            return
        try:
            before = tuple(self.document.scene_objects())
            index = next(
                item_index
                for item_index, record in enumerate(before)
                if record.id == selection.object_id
            )
            updated = self.document.record_with_trigger_area(selection, values)
            if updated == before[index]:
                return
            after = before[:index] + (updated,) + before[index + 1 :]
            enabled = bool(values.get("enabled", False))
            shape = friendly(str(values.get("shape", "sphere")))
            self.undo_stack.push(
                SceneObjectsCommand(
                    self.document,
                    f"Edit {friendly(selection.object_id)} Trigger Area",
                    before,
                    after,
                    selection,
                    selection,
                    None,
                )
            )
            message = (
                f"{friendly(selection.object_id)} now notices the player in a {shape} area."
                if enabled
                else f"{friendly(selection.object_id)} is no longer used as a Trigger Area."
            )
            self._gentle_message(message)
        except Exception as exc:
            self.inspector.set_selection(self.document, selection)
            self.build_output.append(f"Trigger Area change paused: {exc}", "warning")
            self._gentle_message(str(exc))

    def _inspector_population_edited(self, values: Mapping[str, Any]) -> None:
        selection = self.document.selection
        if selection is None or self._playing:
            return
        try:
            before = tuple(self.document.scene_objects())
            index = next(
                item_index
                for item_index, record in enumerate(before)
                if record.id == selection.object_id
            )
            updated = self.document.record_with_population(selection, values)
            # Node3DRecord deliberately excludes metadata from dataclass
            # equality, while Populate Area is stored entirely in metadata.
            if updated.to_dict() == before[index].to_dict():
                return
            after = before[:index] + (updated,) + before[index + 1 :]
            enabled = bool(values.get("enabled", False))
            count = 0
            if enabled:
                raw_population = updated.metadata.get("scatter_population", {})
                count = int(
                    raw_population.get("instance_count", values.get("instance_count", 8))
                )
            command_text = (
                f"Populate {friendly(selection.object_id)} with {count} Display Objects"
                if enabled
                else f"Remove {friendly(selection.object_id)} Populate Area"
            )
            self.undo_stack.push(
                SceneObjectsCommand(
                    self.document,
                    command_text,
                    before,
                    after,
                    selection,
                    selection,
                    None,
                )
            )
            self._gentle_message(
                f"One saved object becomes {count} display objects."
                if enabled
                else f"Removed Populate Area from {friendly(selection.object_id)}."
            )
        except Exception as exc:
            self.inspector.set_selection(self.document, selection)
            self.build_output.append(f"Populate Area change paused: {exc}", "warning")
            self._gentle_message(str(exc))

    def _inspector_movement_pattern_edited(self, values: Mapping[str, Any]) -> None:
        selection = self.document.selection
        if selection is None or self._playing:
            return
        try:
            before_nodes = tuple(self.document.scene_objects())
            before_profiles = self.document.movement_profiles()
            after_nodes, after_profiles = self.document.movement_pattern_snapshot(
                selection, values
            )
            before_data = [record.to_dict() for record in before_nodes]
            after_data = [record.to_dict() for record in after_nodes]
            if before_data == after_data and before_profiles == after_profiles:
                return
            pattern = str(values.get("pattern", "off"))
            pattern_name = {
                "off": "Off / Static",
                "orbit": "Orbit",
                "spiral_out": "Spiral Out",
                "spiral_in": "Spiral In",
            }.get(pattern, "Movement Pattern")
            self.undo_stack.push(
                MovementPatternCommand(
                    self.document,
                    f"Set {friendly(selection.object_id)} movement to {pattern_name}",
                    before_nodes,
                    after_nodes,
                    before_profiles,
                    after_profiles,
                    selection,
                )
            )
            self._gentle_message(
                f"{friendly(selection.object_id)} now uses {pattern_name}. Undo restores the previous movement."
            )
        except Exception as exc:
            self.inspector.set_selection(self.document, selection)
            self.build_output.append(f"Movement pattern paused: {exc}", "warning")
            self._gentle_message(str(exc))

    def _transform_changed(self, selection: SelectionRef) -> None:
        self.viewport.refresh(keep_view=True)
        if selection == self.document.selection:
            self.inspector.set_selection(self.document, selection)

    def _tab_changed(self, index: int) -> None:
        if index == self._logic_tab_index and self.document.is_loaded:
            self._load_graph_context()
            self._refresh_logic_trace()
            self._gentle_message(
                "Logic Trail is updating live. Press Stop when you want to edit blocks."
                if self._playing
                else "Logic Blocks: double-click a block, then drag between its dots."
            )
        elif self.document.is_loaded:
            self._refresh_logic_trace()

    def play(self) -> None:
        if not self.document.is_loaded or self._playing:
            return
        self._clear_logic_trace()
        try:
            self.document.begin_play()
        except Exception as exc:
            # begin_play() may retain a useful Ready-error trail even though it
            # cannot return a runtime world. Keep that new run visible.
            snapshot = self._logic_trace_for_current_context()
            self._show_logic_trace(snapshot)
            QMessageBox.warning(self, "Preview could not start", str(exc))
            return
        self._playing = True
        self.editor_tabs.setCurrentIndex(self._scene_tab_index)
        self._set_logic_read_only(True)
        self._refresh_logic_trace()
        self.inspector.setEnabled(False)
        self.hierarchy.set_authoring_enabled(False)
        self.viewport.set_playing(True)
        # set_playing() cancels any transient gizmo preview. The preview signal
        # is ignored once Preview owns the UI, so restore the Inspector from
        # the authoritative document before giving focus to the game.
        self.inspector.set_selection(self.document, self.document.selection)
        self.viewport.setFocus()
        self.play_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.save_action.setEnabled(False)
        self.import_3d_shape_action.setEnabled(False)
        self.deploy_action.setEnabled(False)
        self.profile_phone_action.setEnabled(False)
        self._frame_count = 0
        self._fps_started = time.perf_counter()
        self.play_timer.start()
        self.build_output.append("Preview started. Use WASD/arrow keys; Space acts or jumps.", "play")
        for warning in self.document.play_warnings:
            self.build_output.append(warning, "warning")
        self._gentle_message("Playing — press Stop when you want to edit again.")

    def _play_frame(self) -> None:
        try:
            state, events = self.document.step_play(self.viewport.pressed_keys)
            self.viewport.set_runtime_state(state)
            self._refresh_logic_trace()
            world_state = state.get("__world__", {})
            if "score" in world_state:
                self.status_message.setText(f"Playing — Score {world_state['score']}")
            for event in events:
                kind = getattr(event, "kind", "event")
                if kind in {"collected", "goal", "damaged", "entity_defeated"}:
                    self.build_output.append(f"Game event: {friendly(kind)}", "play")
        except Exception as exc:
            self.build_output.append(f"Preview stopped safely: {exc}", "warning")
            self.stop()
            return
        self._frame_count += 1
        elapsed = time.perf_counter() - self._fps_started
        if elapsed >= 0.75:
            self.status_fps.setText(f"Preview {self._frame_count / elapsed:.0f} FPS")
            self._frame_count = 0
            self._fps_started = time.perf_counter()

    def stop(self) -> None:
        if not self._playing:
            return
        self.play_timer.stop()
        retained_trace = self._logic_trace_snapshot
        self._preserve_logic_trace_on_stop = True
        try:
            self.document.stop_play()
        finally:
            self._preserve_logic_trace_on_stop = False
        self._playing = False
        self.viewport.set_playing(False)
        self.viewport.set_runtime_state(None)
        self._set_logic_read_only(False)
        self._show_logic_trace(retained_trace)
        self.inspector.setEnabled(True)
        self.hierarchy.set_authoring_enabled(True)
        self.play_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.save_action.setEnabled(True)
        self.import_3d_shape_action.setEnabled(self.document.kind == "3d")
        self.deploy_action.setEnabled(self.document.kind == "3d")
        self.profile_phone_action.setEnabled(
            self.document.kind == "3d" and self._profile_thread is None
            and self._build_thread is None
        )
        self.status_fps.setText("Preview idle")
        self.build_output.append("Preview stopped; project edits were kept separate.", "good")
        self._gentle_message("Back in edit mode.")

    def validate_project(self) -> None:
        if not self.document.is_loaded:
            return
        try:
            report = self.document.validate()
            issues = tuple(getattr(report, "issues", ()))
            android_graph_error: str | None = None
            if report.passed and isinstance(self.document.project, Mobile3DProject):
                try:
                    compile_graph_pack_bytes(self.document.project)
                except GraphPackError as exc:
                    android_graph_error = str(exc)
            if report.passed and not issues and android_graph_error is None:
                self.build_output.append("Project check passed — everything is ready.", "good")
                self._gentle_message("Project check passed.")
            else:
                tone = "warning" if report.passed and android_graph_error is None else "error"
                finding_count = len(issues) + int(android_graph_error is not None)
                self.build_output.append(
                    f"Project check found {finding_count} item(s) to review.", tone
                )
                for issue in issues[:12]:
                    message = getattr(issue, "message", str(issue))
                    path = getattr(issue, "path", "")
                    self.build_output.append(f"{message}" + (f" ({path})" if path else ""), tone)
                if android_graph_error is not None:
                    self.build_output.append(
                        "Android build cannot use these Logic Blocks yet: "
                        f"{android_graph_error}",
                        "error",
                    )
                self.output_dock.raise_()
                self._gentle_message(
                    "Review the messages below before building for Android."
                    if android_graph_error is not None
                    else "The project is safe; review the friendly messages below."
                )
            self.assets_project.set_document(self.document)
            if android_graph_error is not None:
                self.assets_project.project_status.setText(
                    "Needs attention · Android Logic Blocks"
                )
        except Exception as exc:
            self.build_output.append(f"Project check paused: {exc}", "error")

    def deploy_to_phone(self) -> None:
        """Build into UGTS-owned cache and install on the sole authorized phone."""

        project = self.document.project
        if not isinstance(project, Mobile3DProject) or self._playing:
            self.build_output.append("Open a Mobile 3D project before deploying to a phone.", "warning")
            return
        index = self.build_output.target.findData("android-install")
        if index >= 0:
            self.build_output.target.setCurrentIndex(index)
        root = self.document.path.parent if self.document.path else self._repository_root()
        destination = (
            root / ".ugts-studio" / "deploy" / f"{_safe_build_slug(project.id)}-android"
        )
        self._gentle_message(
            "Checking the connected phone, then building, installing, and opening the game…"
        )
        self._build_requested("android-install", destination)

    def profile_running_phone(self) -> None:
        """Measure a deployed Poco build without changing or controlling the phone."""

        project = self.document.project
        if not isinstance(project, Mobile3DProject) or self._playing:
            self.build_output.append(
                "Open a Mobile 3D project before checking a running phone.", "warning"
            )
            return
        if self._build_thread is not None or self._profile_thread is not None:
            return
        application_id = android_application_id(project.id) + ".pocox7pro"
        self._start_phone_profile(application_id)

    def _start_phone_profile(self, application_id: str) -> None:
        """Start one GUI-owned worker after the public preflight has succeeded."""

        self.build_output.set_busy(True)
        self.build_action.setEnabled(False)
        self.deploy_action.setEnabled(False)
        self.profile_phone_action.setEnabled(False)
        self.build_output.append(
            "Checking the running phone for 30 seconds. Keep the game visible and the screen on."
        )
        self.output_dock.raise_()
        self._gentle_message("Checking phone smoothness, memory, and heat…")
        thread = QThread(self)
        worker = PhoneProfileWorker(application_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._profile_finished)
        worker.failed.connect(self._profile_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._profile_thread_cleared)
        self._profile_thread = thread
        self._profile_worker = worker
        thread.start()

    def _build_requested(self, target: str, destination_override: Path | None = None) -> None:
        if (
            not self.document.is_loaded
            or not target
            or self._build_thread is not None
            or self._profile_thread is not None
        ):
            return
        project = self.document.project
        assert project is not None
        base = self.document.path.parent if self.document.path else self._repository_root()
        slug = (getattr(project, "id", None) or getattr(getattr(project, "metadata", None), "id", "game"))
        if destination_override is not None:
            destination = Path(destination_override)
        elif target == "gltf":
            suggested = base / "build" / f"{slug}.gltf"
            path, _ = QFileDialog.getSaveFileName(self, "Export a 3D Preview", str(suggested), "glTF (*.gltf)")
            if not path:
                return
            destination = Path(path)
        else:
            suffix = "web" if target == "html5" else "android"
            suggested = base / "build" / f"{slug}-{suffix}"
            path = QFileDialog.getExistingDirectory(
                self, "Choose Where to Put the Build Folder", str(suggested.parent),
                QFileDialog.Option.ShowDirsOnly,
            )
            if not path:
                return
            # Always build into a named child. The chosen parent is never cleaned.
            destination = Path(path) / suggested.name
            if destination.exists() and any(destination.iterdir()):
                answer = QMessageBox.question(
                    self, "Replace the old build?",
                    "This folder already has files. Building will replace its old build contents. Your source project is not affected.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        try:
            if isinstance(project, GameProject):
                snapshot: GameProject | Mobile3DProject = GameProject.from_dict(project.to_dict())
            else:
                snapshot = Mobile3DProject.from_dict(project.to_dict())
        except Exception as exc:
            self.build_output.append(f"Build paused: {exc}", "error")
            return
        self.build_output.set_busy(True)
        self.build_action.setEnabled(False)
        self.deploy_action.setEnabled(False)
        self.profile_phone_action.setEnabled(False)
        self.build_output.append(f"Building {self.build_output.target.currentText()}…")
        thread = QThread(self)
        worker = BuildWorker(snapshot, target, destination)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._build_finished)
        worker.partial.connect(self._build_partial)
        worker.failed.connect(self._build_failed)
        worker.finished.connect(thread.quit)
        worker.partial.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._build_thread_cleared)
        self._build_thread = thread
        self._build_worker = worker
        thread.start()

    @Slot(object)
    def _build_finished(self, result: object) -> None:
        summary, folder = result  # type: ignore[misc]
        self.build_output.set_busy(False)
        self.build_output.set_build_path(folder)
        self.build_output.append(str(summary), "good")
        self.output_dock.raise_()
        if " and opened" in str(summary):
            self._gentle_message("The game is running on the connected phone.")
        else:
            self._gentle_message("Build finished. Open Build Folder is ready.")

    @Slot(str)
    def _build_failed(self, message: str) -> None:
        self.build_output.set_busy(False)
        self.build_output.append(f"Build stopped: {message}", "error")
        self.output_dock.raise_()
        self._gentle_message("Nothing in your source project was changed.")

    @Slot(object)
    def _build_partial(self, result: object) -> None:
        summary, phase, detail, folder = result  # type: ignore[misc]
        self.build_output.set_busy(False)
        self.build_output.set_build_path(folder)
        self.build_output.append(str(summary), "good")
        if phase == "launch":
            self.build_output.append(
                f"The APK installed, but the game did not open: {detail}", "warning"
            )
            gentle = "The game is installed. Open it on the phone, or try Deploy again."
        else:
            self.build_output.append(
                f"APK install did not finish: {detail}", "warning"
            )
            gentle = "The APK is ready. Check the phone message, then try Deploy again."
        self.output_dock.raise_()
        self._gentle_message(gentle)

    @Slot()
    def _build_thread_cleared(self) -> None:
        self._build_thread = None
        self._build_worker = None
        self.build_action.setEnabled(self.document.is_loaded and not self._playing)
        self.deploy_action.setEnabled(self.document.kind == "3d" and not self._playing)
        self.profile_phone_action.setEnabled(
            self.document.kind == "3d" and not self._playing
            and self._profile_thread is None
        )

    @Slot(object)
    def _profile_finished(self, value: object) -> None:
        result = value
        if not isinstance(result, AndroidProfileResult):
            self._profile_failed("The phone returned an unreadable profile result.")
            return
        self.build_output.set_busy(False)
        lines = _phone_profile_lines(result)
        tone = "good" if not result.warnings else "warning"
        for index, line in enumerate(lines):
            self.build_output.append(line, tone if index == 0 else "info")
        self.output_dock.raise_()
        self._gentle_message(
            "Phone check passed."
            if not result.warnings
            else "Phone check finished — review the notes below."
        )

    @Slot(str)
    def _profile_failed(self, message: str) -> None:
        self.build_output.set_busy(False)
        self.build_output.append(f"Phone check stopped: {message}", "warning")
        self.output_dock.raise_()
        self._gentle_message(
            "Connect the phone, open the deployed game, and try Check Phone again."
        )

    @Slot()
    def _profile_thread_cleared(self) -> None:
        self._profile_thread = None
        self._profile_worker = None
        self.build_action.setEnabled(self.document.is_loaded and not self._playing)
        phone_ready = self.document.kind == "3d" and not self._playing
        self.deploy_action.setEnabled(phone_ready and self._build_thread is None)
        self.profile_phone_action.setEnabled(phone_ready)

    def _gentle_message(self, message: str) -> None:
        self.status_message.setText(message)
        self.statusBar().showMessage(message, 5500)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if any(url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".json" for url in urls):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        path = next(
            (Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".json"),
            None,
        )
        if path is not None:
            self.open_project(path)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        if self._build_thread is not None and self._build_thread.isRunning():
            QMessageBox.information(
                self, "A build is still running",
                "Please wait for the build to finish before closing UGTS Studio.",
            )
            event.ignore()
            return
        if self._profile_thread is not None and self._profile_thread.isRunning():
            QMessageBox.information(
                self, "A phone check is still running",
                "Please wait for the 30-second phone check to finish before closing UGTS Studio.",
            )
            event.ignore()
            return
        if self._maybe_save():
            self.stop()
            event.accept()
        else:
            event.ignore()


__all__ = [
    "EditorMainWindow",
    "GraphCommand",
    "MaterialLookCommand",
    "PhoneProfileWorker",
    "SceneObjectsCommand",
    "TransformCommand",
]
