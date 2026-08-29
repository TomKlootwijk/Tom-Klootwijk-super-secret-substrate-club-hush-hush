"""Dock panels and welcoming beginner surfaces for the UGTS editor."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from ..mobile3d import Mobile3DProject, Node3DRecord
from ..project import EntitySpec, GameProject
from .document import (
    EditorDocument,
    SelectionRef,
    euler_degrees_to_quaternion,
    quaternion_to_euler_degrees,
)


def friendly(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _spin(step: float = 0.1) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(-1_000_000.0, 1_000_000.0)
    widget.setDecimals(4)
    widget.setSingleStep(step)
    widget.setKeyboardTracking(False)
    return widget


class InspectorPanel(QWidget):
    """Friendly transform editor with optional, summarized advanced details."""

    transformEdited = Signal(object)
    resourceEdited = Signal(str, str)
    messageRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._updating = False
        self._selection: SelectionRef | None = None
        self._mode: str | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(9)
        self.title = QLabel("Nothing selected")
        self.title.setObjectName("PanelTitle")
        self.subtitle = QLabel("Click an object in the scene or Scene Tree.")
        self.subtitle.setObjectName("MutedLabel")
        self.subtitle.setWordWrap(True)
        root.addWidget(self.title)
        root.addWidget(self.subtitle)

        self.transform_box = QGroupBox("Transform")
        transform_layout = QVBoxLayout(self.transform_box)
        transform_layout.setContentsMargins(8, 12, 8, 8)
        self.transform_stack = QStackedWidget()
        transform_layout.addWidget(self.transform_stack)
        self.form2d_widget = QWidget()
        form2d = QFormLayout(self.form2d_widget)
        form2d.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.x2, self.y2 = _spin(), _spin()
        self.rotation2 = _spin(1.0)
        self.sx2, self.sy2 = _spin(0.05), _spin(0.05)
        form2d.addRow("Position X", self.x2)
        form2d.addRow("Position Y", self.y2)
        form2d.addRow("Rotation °", self.rotation2)
        form2d.addRow("Scale X", self.sx2)
        form2d.addRow("Scale Y", self.sy2)
        self.form3d_widget = QWidget()
        form3d = QFormLayout(self.form3d_widget)
        form3d.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.x3, self.y3, self.z3 = _spin(), _spin(), _spin()
        self.rx3, self.ry3, self.rz3 = _spin(1.0), _spin(1.0), _spin(1.0)
        self.sx3, self.sy3, self.sz3 = _spin(0.05), _spin(0.05), _spin(0.05)
        form3d.addRow("Position X", self.x3)
        form3d.addRow("Position Y", self.y3)
        form3d.addRow("Position Z", self.z3)
        form3d.addRow("Rotation X °", self.rx3)
        form3d.addRow("Rotation Y °", self.ry3)
        form3d.addRow("Rotation Z °", self.rz3)
        form3d.addRow("Scale X", self.sx3)
        form3d.addRow("Scale Y", self.sy3)
        form3d.addRow("Scale Z", self.sz3)
        self.transform_stack.addWidget(self.form2d_widget)
        self.transform_stack.addWidget(self.form3d_widget)
        root.addWidget(self.transform_box)
        self.transform_box.hide()

        self.appearance_box = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout(self.appearance_box)
        appearance_layout.setContentsMargins(8, 12, 8, 8)
        self.appearance_stack = QStackedWidget()
        appearance_layout.addWidget(self.appearance_stack)
        self.appearance2d_widget = QWidget()
        appearance2d = QFormLayout(self.appearance2d_widget)
        appearance2d.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.vector_asset_combo = QComboBox()
        self.vector_asset_combo.setObjectName("VectorAssetCombo")
        self.vector_asset_combo.setToolTip("Choose one of this project's existing vector pictures")
        appearance2d.addRow("Picture", self.vector_asset_combo)
        self.appearance3d_widget = QWidget()
        appearance3d = QFormLayout(self.appearance3d_widget)
        appearance3d.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.mesh_combo = QComboBox()
        self.mesh_combo.setObjectName("MeshCombo")
        self.mesh_combo.setToolTip("Choose one of this project's existing 3D shapes")
        self.material_combo = QComboBox()
        self.material_combo.setObjectName("MaterialCombo")
        self.material_combo.setToolTip("Choose one of this project's existing materials")
        appearance3d.addRow("Shape", self.mesh_combo)
        appearance3d.addRow("Material", self.material_combo)
        self.appearance_stack.addWidget(self.appearance2d_widget)
        self.appearance_stack.addWidget(self.appearance3d_widget)
        root.addWidget(self.appearance_box)
        self.appearance_box.hide()

        self.quick_info = QLabel()
        self.quick_info.setObjectName("MutedLabel")
        self.quick_info.setWordWrap(True)
        root.addWidget(self.quick_info)

        self.details_button = QPushButton("Show More Details")
        self.details_button.setCheckable(True)
        self.details_button.setToolTip("Shows components and settings; beginners can safely leave this closed")
        self.details = QTreeWidget()
        self.details.setHeaderLabels(["Setting", "Value"])
        self.details.setAlternatingRowColors(True)
        self.details.setRootIsDecorated(True)
        self.details.setVisible(False)
        root.addWidget(self.details_button)
        root.addWidget(self.details, 1)
        self.details_button.toggled.connect(self._toggle_details)
        for widget in (
            self.x2, self.y2, self.rotation2, self.sx2, self.sy2,
            self.x3, self.y3, self.z3, self.rx3, self.ry3, self.rz3,
            self.sx3, self.sy3, self.sz3,
        ):
            widget.editingFinished.connect(self._emit_transform)
        self.vector_asset_combo.currentIndexChanged.connect(self._emit_vector_asset)
        self.mesh_combo.currentIndexChanged.connect(self._emit_mesh)
        self.material_combo.currentIndexChanged.connect(self._emit_material)

    def clear(self) -> None:
        self._selection = None
        self._mode = None
        self.title.setText("Nothing selected")
        self.subtitle.setText("Click an object in the scene or Scene Tree.")
        self.transform_box.hide()
        self.appearance_box.hide()
        self.vector_asset_combo.clear()
        self.mesh_combo.clear()
        self.material_combo.clear()
        self.quick_info.clear()
        self.details.clear()

    def set_selection(self, document: EditorDocument, selection: SelectionRef | None) -> None:
        self._updating = True
        try:
            self._selection = selection
            if selection is None:
                self.clear()
                return
            details = document.object_details(selection)
            transform = document.transform(selection)
            self.title.setText(friendly(selection.object_id))
            self.subtitle.setText(selection.object_id)
            tags = details.get("tags", [])
            components = details.get("components", {})
            role_names = list(components) if isinstance(components, Mapping) else []
            selected = document.entity(selection)
            self._set_appearance(document, selected)
            if tags:
                self.quick_info.setText("Tags: " + ", ".join(friendly(str(tag)) for tag in tags))
            elif role_names:
                self.quick_info.setText("Parts: " + ", ".join(friendly(str(name)) for name in role_names[:5]))
            else:
                self.quick_info.setText("A scene object you can position, rotate, and scale.")
            self._populate_details(details)
            if transform is None:
                self._mode = None
                self.transform_box.hide()
                self.subtitle.setText(f"{selection.object_id} · no editable transform")
                return
            self.transform_box.show()
            if "position" in transform:
                self._mode = "2d"
                self.transform_stack.setCurrentWidget(self.form2d_widget)
                self.x2.setValue(float(transform["position"][0]))
                self.y2.setValue(float(transform["position"][1]))
                self.rotation2.setValue(math.degrees(float(transform["rotation"])))
                self.sx2.setValue(float(transform["scale"][0]))
                self.sy2.setValue(float(transform["scale"][1]))
            else:
                self._mode = "3d"
                self.transform_stack.setCurrentWidget(self.form3d_widget)
                translation = transform["translation"]
                rotation = quaternion_to_euler_degrees(transform["rotation"])
                scale = transform["scale"]
                for widget, value in zip((self.x3, self.y3, self.z3), translation):
                    widget.setValue(float(value))
                for widget, value in zip((self.rx3, self.ry3, self.rz3), rotation):
                    widget.setValue(float(value))
                for widget, value in zip((self.sx3, self.sy3, self.sz3), scale):
                    widget.setValue(float(value))
        finally:
            self._updating = False

    @staticmethod
    def _fill_resource_combo(combo: QComboBox, resource_ids: list[str], current_id: str) -> None:
        combo.clear()
        for resource_id in sorted(resource_ids, key=lambda value: friendly(value).casefold()):
            combo.addItem(friendly(resource_id), resource_id)
            combo.setItemData(
                combo.count() - 1,
                f"Project resource: {resource_id}",
                Qt.ItemDataRole.ToolTipRole,
            )
        current_index = combo.findData(current_id)
        combo.setCurrentIndex(current_index)

    def _set_appearance(
        self,
        document: EditorDocument,
        selected: EntitySpec | Node3DRecord | None,
    ) -> None:
        self.appearance_box.hide()
        self.vector_asset_combo.clear()
        self.mesh_combo.clear()
        self.material_combo.clear()
        if isinstance(document.project, GameProject) and isinstance(selected, EntitySpec):
            renderer = selected.components.get("vector_renderer")
            if not isinstance(renderer, Mapping):
                return
            self._fill_resource_combo(
                self.vector_asset_combo,
                list(document.project.vector_assets.assets),
                str(renderer.get("asset_id", "")),
            )
            if self.vector_asset_combo.count():
                self.appearance_stack.setCurrentWidget(self.appearance2d_widget)
                self.appearance_box.show()
            return
        if isinstance(document.project, Mobile3DProject) and isinstance(selected, Node3DRecord):
            self._fill_resource_combo(
                self.mesh_combo, list(document.project.meshes), selected.mesh_id
            )
            self._fill_resource_combo(
                self.material_combo, list(document.project.materials), selected.material_id
            )
            if self.mesh_combo.count() and self.material_combo.count():
                self.appearance_stack.setCurrentWidget(self.appearance3d_widget)
                self.appearance_box.show()

    def _emit_resource(self, resource_kind: str, combo: QComboBox) -> None:
        if self._updating or self._selection is None or combo.currentIndex() < 0:
            return
        resource_id = combo.currentData()
        if isinstance(resource_id, str) and resource_id:
            self.resourceEdited.emit(resource_kind, resource_id)

    def _emit_vector_asset(self) -> None:
        self._emit_resource("vector_asset", self.vector_asset_combo)

    def _emit_mesh(self) -> None:
        self._emit_resource("mesh", self.mesh_combo)

    def _emit_material(self) -> None:
        self._emit_resource("material", self.material_combo)

    def _emit_transform(self) -> None:
        if self._updating or self._selection is None:
            return
        if self._mode == "2d":
            value = {
                "position": (self.x2.value(), self.y2.value()),
                "rotation": math.radians(self.rotation2.value()),
                "scale": (self.sx2.value(), self.sy2.value()),
            }
        elif self._mode == "3d":
            value = {
                "translation": (self.x3.value(), self.y3.value(), self.z3.value()),
                "rotation": euler_degrees_to_quaternion((self.rx3.value(), self.ry3.value(), self.rz3.value())),
                "scale": (self.sx3.value(), self.sy3.value(), self.sz3.value()),
            }
        else:
            return
        self.transformEdited.emit(value)

    def _toggle_details(self, checked: bool) -> None:
        self.details.setVisible(checked)
        self.details_button.setText("Hide More Details" if checked else "Show More Details")

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if value is None:
            return "Not set"
        if isinstance(value, float):
            return f"{value:.4g}"
        if isinstance(value, (list, tuple)):
            if len(value) <= 6 and all(not isinstance(item, (dict, list, tuple)) for item in value):
                return ", ".join(InspectorPanel._format_value(item) for item in value)
            return f"{len(value)} items"
        return str(value)

    def _add_detail_value(self, parent: QTreeWidgetItem, key: str, value: Any, depth: int = 0) -> None:
        if isinstance(value, Mapping) and depth < 2:
            item = QTreeWidgetItem([friendly(str(key)), f"{len(value)} settings"])
            parent.addChild(item)
            for child_key, child_value in value.items():
                self._add_detail_value(item, str(child_key), child_value, depth + 1)
        else:
            parent.addChild(QTreeWidgetItem([friendly(str(key)), self._format_value(value)]))

    def _populate_details(self, details: Mapping[str, Any]) -> None:
        self.details.clear()
        hidden = {"id", "transform"}
        for key, value in details.items():
            if key in hidden:
                continue
            root = QTreeWidgetItem([friendly(str(key)), self._format_value(value)])
            self.details.addTopLevelItem(root)
            if isinstance(value, Mapping):
                root.setText(1, f"{len(value)} settings")
                for child_key, child_value in value.items():
                    self._add_detail_value(root, str(child_key), child_value)
        self.details.resizeColumnToContents(0)


class HierarchyPanel(QWidget):
    selectionRequested = Signal(object)
    sceneRequested = Signal(str)
    addRequested = Signal()
    duplicateRequested = Signal()
    deleteRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._has_document = False
        self._authoring_enabled = True
        self._selection: SelectionRef | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.add_button = QPushButton("+ Add")
        self.add_button.setObjectName("SceneAddButton")
        self.add_button.setToolTip("Add a new object to this scene")
        self.duplicate_button = QPushButton("Copy")
        self.duplicate_button.setObjectName("SceneDuplicateButton")
        self.duplicate_button.setToolTip("Duplicate the selected object, including its settings")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("SceneDeleteButton")
        self.delete_button.setToolTip("Delete the selected object when the scene can safely lose it")
        controls.addWidget(self.add_button)
        controls.addWidget(self.duplicate_button)
        controls.addWidget(self.delete_button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an object…")
        self.search.setClearButtonEnabled(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Kind"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addLayout(controls)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        self.add_button.clicked.connect(self.addRequested)
        self.duplicate_button.clicked.connect(self.duplicateRequested)
        self.delete_button.clicked.connect(self.deleteRequested)
        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(self._current_changed)
        self._update_authoring_buttons()

    def set_document(self, document: EditorDocument | None) -> None:
        self._has_document = document is not None and document.project is not None
        self._selection = None if document is None else document.selection
        self._update_authoring_buttons()
        blocker = QSignalBlocker(self.tree)
        self.tree.clear()
        if document is None or document.project is None:
            hint = QTreeWidgetItem(["Open a project to begin", ""])
            hint.setForeground(0, QColor("#8296ad"))
            self.tree.addTopLevelItem(hint)
            return
        root = QTreeWidgetItem([document.display_name, "Project"])
        root.setExpanded(True)
        self.tree.addTopLevelItem(root)
        if isinstance(document.project, GameProject):
            for scene_id, scene in document.project.scenes.items():
                scene_item = QTreeWidgetItem([friendly(scene_id), "2D Scene"])
                scene_item.setData(0, Qt.ItemDataRole.UserRole + 1, scene_id)
                scene_item.setExpanded(scene_id == document.current_scene_id)
                if scene_id == document.current_scene_id:
                    scene_item.setForeground(0, QColor("#68d8ff"))
                root.addChild(scene_item)
                for entity in scene.entities:
                    components = entity.components
                    if "camera" in components:
                        kind = "Camera"
                    elif "player_controller" in components or "player" in entity.tags:
                        kind = "Player"
                    elif "vector_renderer" in components:
                        kind = "Sprite"
                    else:
                        kind = "Object"
                    item = QTreeWidgetItem([friendly(entity.id), kind])
                    item.setData(0, Qt.ItemDataRole.UserRole, SelectionRef("entity", entity.id, scene_id))
                    item.setToolTip(0, f"Project ID: {entity.id}")
                    scene_item.addChild(item)
        else:
            scene_item = QTreeWidgetItem(["Main 3D Scene", "3D Scene"])
            scene_item.setExpanded(True)
            root.addChild(scene_item)
            for node in document.project.nodes:
                kind = "Player" if "player" in node.tags else "3D Object"
                item = QTreeWidgetItem([friendly(node.id), kind])
                item.setData(0, Qt.ItemDataRole.UserRole, SelectionRef("node", node.id))
                item.setToolTip(0, f"Mesh: {node.mesh_id} · Material: {node.material_id}")
                scene_item.addChild(item)
        self.tree.resizeColumnToContents(0)
        del blocker

    def set_selection(self, selection: SelectionRef | None) -> None:
        self._selection = selection
        self._update_authoring_buttons()
        blocker = QSignalBlocker(self.tree)
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == selection:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                break
            iterator += 1
        del blocker

    def set_authoring_enabled(self, enabled: bool) -> None:
        self._authoring_enabled = bool(enabled)
        self._update_authoring_buttons()

    def _update_authoring_buttons(self) -> None:
        can_add = self._has_document and self._authoring_enabled
        can_edit_selection = can_add and self._selection is not None
        self.add_button.setEnabled(can_add)
        self.duplicate_button.setEnabled(can_edit_selection)
        self.delete_button.setEnabled(can_edit_selection)

    def _current_changed(self, current: QTreeWidgetItem | None, previous=None) -> None:
        if current is None:
            return
        selection = current.data(0, Qt.ItemDataRole.UserRole)
        scene_id = current.data(0, Qt.ItemDataRole.UserRole + 1)
        if isinstance(selection, SelectionRef):
            self.selectionRequested.emit(selection)
        elif scene_id:
            self.sceneRequested.emit(str(scene_id))

    def _filter(self, text: str) -> None:
        query = text.casefold().strip()

        def visit(item: QTreeWidgetItem) -> bool:
            own = query in f"{item.text(0)} {item.text(1)}".casefold()
            child_match = any(visit(item.child(index)) for index in range(item.childCount()))
            visible = not query or own or child_match
            item.setHidden(not visible)
            if child_match and query:
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))


class AssetsProjectPanel(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.assets = QTreeWidget()
        self.assets.setHeaderLabels(["Resource", "Count / Type"])
        self.assets.setRootIsDecorated(True)
        self.summary = QWidget()
        form = QFormLayout(self.summary)
        form.setContentsMargins(12, 12, 12, 12)
        self.project_name = QLabel("No project")
        self.project_type = QLabel("—")
        self.project_objects = QLabel("0")
        self.project_target = QLabel("—")
        self.project_status = QLabel("Open a project to begin")
        self.project_status.setWordWrap(True)
        form.addRow("Project", self.project_name)
        form.addRow("Type", self.project_type)
        form.addRow("Objects", self.project_objects)
        form.addRow("Main target", self.project_target)
        form.addRow("Health", self.project_status)
        self.addTab(self.assets, "Resources")
        self.addTab(self.summary, "Project")

    @staticmethod
    def _category(name: str, count: int, parent: QTreeWidgetItem | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, str(count)])
        item.setExpanded(True)
        if parent is not None:
            parent.addChild(item)
        return item

    def set_document(self, document: EditorDocument | None) -> None:
        self.assets.clear()
        if document is None or document.project is None:
            self.assets.addTopLevelItem(QTreeWidgetItem(["Open a project to see resources", ""]))
            self.project_name.setText("No project")
            self.project_type.setText("—")
            self.project_objects.setText("0")
            self.project_target.setText("—")
            self.project_status.setText("Open a project to begin")
            return
        project = document.project
        self.project_name.setText(document.display_name)
        self.project_objects.setText(str(document.object_count))
        if isinstance(project, GameProject):
            self.project_type.setText("2D vector game")
            self.project_target.setText("Desktop editor + HTML5")
            vectors = self._category("Vector Art", len(project.vector_assets.assets))
            for asset in project.vector_assets:
                vectors.addChild(QTreeWidgetItem([friendly(asset.id), f"{asset.size[0]:g} × {asset.size[1]:g}"]))
            sounds = self._category("Sounds", len(project.audio.cues))
            for cue_id in sorted(project.audio.cues):
                sounds.addChild(QTreeWidgetItem([friendly(cue_id), "Sound"]))
            tilemaps = self._category("Tile Maps", len(project.tilemaps))
            for tilemap_id in sorted(project.tilemaps):
                tilemaps.addChild(QTreeWidgetItem([friendly(tilemap_id), "Tile Map"]))
            for category in (vectors, sounds, tilemaps):
                self.assets.addTopLevelItem(category)
        else:
            self.project_type.setText("Mobile 3D game")
            targets = ", ".join(profile.label for profile in project.target_profiles[:1]) or "Android"
            self.project_target.setText(targets)
            meshes = self._category("3D Meshes", len(project.meshes))
            for mesh in project.meshes.values():
                meshes.addChild(QTreeWidgetItem([friendly(mesh.id), f"{len(mesh.triangles)} triangles"]))
            materials = self._category("Materials", len(project.materials))
            for material in project.materials.values():
                materials.addChild(QTreeWidgetItem([friendly(material.id), "Material"]))
            profiles = self._category("Android Devices", len(project.target_profiles))
            for profile in project.target_profiles:
                profiles.addChild(QTreeWidgetItem([profile.label, f"{profile.target_refresh_hz} Hz target"]))
            for category in (meshes, materials, profiles):
                self.assets.addTopLevelItem(category)
        try:
            report = document.validate()
            issue_count = len(getattr(report, "issues", ()))
            if report.passed:
                self.project_status.setText("Ready" if issue_count == 0 else f"Ready · {issue_count} gentle warning(s)")
            else:
                self.project_status.setText(f"Needs attention · {issue_count} issue(s)")
        except Exception:
            self.project_status.setText("Could not check yet")
        self.assets.resizeColumnToContents(0)


class BuildOutputPanel(QWidget):
    buildRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.last_build_path: Path | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Build for"))
        self.target = QComboBox()
        self.build_button = QPushButton("Build Project…")
        self.build_button.setObjectName("PrimaryButton")
        self.build_button.setToolTip("Creates a playable/exportable copy; it never changes your source project")
        self.open_button = QPushButton("Open Build Folder")
        self.open_button.setEnabled(False)
        self.clear_button = QPushButton("Clear Messages")
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(110)
        controls.addWidget(self.target)
        controls.addWidget(self.build_button)
        controls.addWidget(self.open_button)
        controls.addWidget(self.progress)
        controls.addStretch(1)
        controls.addWidget(self.clear_button)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(300)
        self.output.setPlaceholderText("Helpful messages from Play, checks, and builds appear here.")
        layout.addLayout(controls)
        layout.addWidget(self.output, 1)
        self.build_button.clicked.connect(
            lambda: self.buildRequested.emit(str(self.target.currentData() or ""))
        )
        self.open_button.clicked.connect(self.open_last_build)
        self.clear_button.clicked.connect(self.output.clear)
        self.set_kind(None)

    def set_kind(self, kind: str | None) -> None:
        self.target.clear()
        if kind == "2d":
            self.target.addItem("Web / HTML5", "html5")
        elif kind == "3d":
            self.target.addItem("Poco X7 Pro APK (Debug)", "android-apk")
            self.target.addItem("Poco APK + Install", "android-install")
            self.target.addItem("Android Studio Project", "android")
            self.target.addItem("glTF 3D Preview", "gltf")
        else:
            self.target.addItem("Open a project first", "")
        self.build_button.setEnabled(kind is not None)

    def append(self, text: str, tone: str = "info") -> None:
        prefix = {"good": "✓", "warning": "!", "error": "×", "play": "▶"}.get(tone, "•")
        self.output.appendPlainText(f"{prefix} {text}")

    def set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 1)
        self.build_button.setEnabled(not busy and bool(self.target.currentData()))

    def set_build_path(self, path: str | Path) -> None:
        self.last_build_path = Path(path)
        self.open_button.setEnabled(True)

    def open_last_build(self) -> None:
        if self.last_build_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_build_path.resolve())))


class WelcomePage(QWidget):
    openRequested = Signal()
    new2dRequested = Signal()
    new3dRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 34, 40, 34)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(760)
        layout = QVBoxLayout(content)
        layout.setSpacing(15)
        title = QLabel("UGTS Studio")
        title.setObjectName("WelcomeTitle")
        subtitle = QLabel("Make a game by arranging objects, changing friendly settings, and connecting logic blocks.")
        subtitle.setObjectName("WelcomeSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        card = QFrame()
        card.setObjectName("WelcomeCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(10)
        start_label = QLabel("What would you like to make?")
        start_label.setObjectName("PanelTitle")
        self.new2d_button = QPushButton("Start a Simple 2D Game")
        self.new2d_button.setObjectName("PrimaryButton")
        self.new2d_button.setToolTip("Starts from a safe copy of the included beginner template")
        self.new3d_button = QPushButton("Start a Mobile 3D Game")
        self.new3d_button.setToolTip("Starts from a safe copy tuned for Android")
        self.open_button = QPushButton("Open My Project…")
        self.open_button.setToolTip("Opens an existing UGTS project.json file")
        tip = QLabel("Templates open as unsaved copies, so the originals stay safe. You can also drop a project.json anywhere on this window.")
        tip.setObjectName("MutedLabel")
        tip.setWordWrap(True)
        card_layout.addWidget(start_label)
        card_layout.addWidget(self.new2d_button)
        card_layout.addWidget(self.new3d_button)
        card_layout.addWidget(self.open_button)
        card_layout.addWidget(tip)
        layout.addWidget(card)
        steps = QLabel("1. Pick an object   →   2. Change its Transform   →   3. Press Play")
        steps.setObjectName("MutedLabel")
        steps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        steps.setWordWrap(True)
        layout.addWidget(steps)
        outer.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self.open_button.clicked.connect(self.openRequested)
        self.new2d_button.clicked.connect(self.new2dRequested)
        self.new3d_button.clicked.connect(self.new3dRequested)


__all__ = [
    "AssetsProjectPanel",
    "BuildOutputPanel",
    "HierarchyPanel",
    "InspectorPanel",
    "WelcomePage",
    "friendly",
]
