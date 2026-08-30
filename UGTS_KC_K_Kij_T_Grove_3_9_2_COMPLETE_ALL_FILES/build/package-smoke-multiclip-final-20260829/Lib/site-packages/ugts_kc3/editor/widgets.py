"""Dock panels and welcoming beginner surfaces for the UGTS editor."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QScrollArea,
    QSpinBox,
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
from ..reusable import reusable_source_id
from .document import (
    EditorDocument,
    MATERIAL_LOOK_CHOICES,
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
    materialLookEdited = Signal(str)
    movementPatternEdited = Signal(object)
    triggerAreaEdited = Signal(object)
    populationEdited = Signal(object)
    messageRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._updating = False
        self._selection: SelectionRef | None = None
        self._mode: str | None = None
        self._movement_spiral_rate = 0.2
        self._movement_values: dict[str, float] = {}
        self._movement_display_values: dict[str, float] = {}
        self._trigger_values: dict[str, float] = {}
        self._trigger_display_values: dict[str, float] = {}
        self._population_values: dict[str, float] = {}
        self._population_display_values: dict[str, float] = {}
        self._population_can_enable = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("InspectorScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(9)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area)
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
        self.material_look_combo = QComboBox()
        self.material_look_combo.setObjectName("MaterialLookCombo")
        self.material_look_combo.setToolTip(
            "Choose a ready-made surface style. It keeps this object's colour; "
            "Custom leaves the material exactly as it is."
        )
        for label, look in MATERIAL_LOOK_CHOICES:
            self.material_look_combo.addItem(label, look)
        appearance3d.addRow("Shape", self.mesh_combo)
        appearance3d.addRow("Material", self.material_combo)
        appearance3d.addRow("Material Look", self.material_look_combo)
        self.appearance_stack.addWidget(self.appearance2d_widget)
        self.appearance_stack.addWidget(self.appearance3d_widget)
        root.addWidget(self.appearance_box)
        self.appearance_box.hide()

        self.trigger_box = QGroupBox("Trigger Area")
        trigger_layout = QVBoxLayout(self.trigger_box)
        trigger_layout.setContentsMargins(8, 12, 8, 8)
        trigger_layout.setSpacing(6)
        self.trigger_explanation = QLabel()
        self.trigger_explanation.setObjectName("MutedLabel")
        self.trigger_explanation.setWordWrap(True)
        trigger_layout.addWidget(self.trigger_explanation)
        self.trigger_enabled = QCheckBox("Use as Trigger")
        self.trigger_enabled.setObjectName("TriggerEnabledCheck")
        self.trigger_enabled.setToolTip(
            "Notice the player entering or leaving without pushing anything"
        )
        trigger_layout.addWidget(self.trigger_enabled)
        self.trigger_form = QFormLayout()
        self.trigger_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.trigger_shape = QComboBox()
        self.trigger_shape.setObjectName("TriggerShapeCombo")
        self.trigger_shape.addItem("Sphere", "sphere")
        self.trigger_shape.addItem("Box", "box")
        self.trigger_radius = _spin(0.25)
        self.trigger_radius.setObjectName("TriggerRadius")
        self.trigger_radius.setRange(0.05, 10_000.0)
        self.trigger_radius.setDecimals(2)
        self.trigger_radius.setSuffix(" units")
        self.trigger_size_x = _spin(0.25)
        self.trigger_size_y = _spin(0.25)
        self.trigger_size_z = _spin(0.25)
        for name, widget in (
            ("TriggerSizeX", self.trigger_size_x),
            ("TriggerSizeY", self.trigger_size_y),
            ("TriggerSizeZ", self.trigger_size_z),
        ):
            widget.setObjectName(name)
            widget.setRange(0.05, 10_000.0)
            widget.setDecimals(2)
            widget.setSuffix(" units")
        self.trigger_form.addRow("Shape", self.trigger_shape)
        self.trigger_form.addRow("Radius", self.trigger_radius)
        self.trigger_form.addRow("Size X", self.trigger_size_x)
        self.trigger_form.addRow("Size Y", self.trigger_size_y)
        self.trigger_form.addRow("Size Z", self.trigger_size_z)
        trigger_layout.addLayout(self.trigger_form)
        root.addWidget(self.trigger_box)
        self.trigger_box.hide()

        self.movement_box = QGroupBox("Movement Pattern")
        movement_layout = QVBoxLayout(self.movement_box)
        movement_layout.setContentsMargins(8, 12, 8, 8)
        movement_layout.setSpacing(6)
        self.movement_explanation = QLabel()
        self.movement_explanation.setObjectName("MutedLabel")
        self.movement_explanation.setWordWrap(True)
        movement_layout.addWidget(self.movement_explanation)
        movement_form = QFormLayout()
        movement_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.movement_pattern_combo = QComboBox()
        self.movement_pattern_combo.setObjectName("MovementPatternCombo")
        self.movement_pattern_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.movement_pattern_combo.setMinimumContentsLength(18)
        self.movement_pattern_combo.setToolTip(
            "Choose a small, efficient movement pattern for this object"
        )
        self.movement_radius = _spin(0.25)
        self.movement_radius.setObjectName("MovementRadius")
        self.movement_radius.setDecimals(2)
        self.movement_radius.setSuffix(" units")
        self.movement_radius.setToolTip("Distance from the centre of the world")
        self.movement_speed = _spin(0.05)
        self.movement_speed.setObjectName("MovementSpeed")
        self.movement_speed.setDecimals(3)
        self.movement_speed.setSuffix(" turns/s")
        self.movement_speed.setToolTip(
            "How many circles per second; a minus sign reverses direction"
        )
        self.movement_angle = _spin(5.0)
        self.movement_angle.setObjectName("MovementStartAngle")
        self.movement_angle.setDecimals(1)
        self.movement_angle.setRange(0.0, 359.9)
        self.movement_angle.setWrapping(True)
        self.movement_angle.setSuffix(" °")
        self.movement_angle.setToolTip("Where around the circle the object starts")
        movement_form.addRow("Pattern", self.movement_pattern_combo)
        movement_form.addRow("Radius", self.movement_radius)
        movement_form.addRow("Circle speed", self.movement_speed)
        movement_form.addRow("Start angle", self.movement_angle)
        movement_layout.addLayout(movement_form)
        self.movement_cost = QLabel()
        self.movement_cost.setObjectName("MutedLabel")
        self.movement_cost.setWordWrap(True)
        movement_layout.addWidget(self.movement_cost)
        root.addWidget(self.movement_box)
        self.movement_box.hide()

        self.population_box = QGroupBox("Populate Area")
        population_layout = QVBoxLayout(self.population_box)
        population_layout.setContentsMargins(8, 12, 8, 8)
        population_layout.setSpacing(6)
        self.population_explanation = QLabel()
        self.population_explanation.setObjectName("MutedLabel")
        self.population_explanation.setWordWrap(True)
        population_layout.addWidget(self.population_explanation)
        self.population_enabled = QCheckBox("Populate this object")
        self.population_enabled.setObjectName("PopulationEnabledCheck")
        self.population_enabled.setToolTip(
            "Make deterministic static display copies without duplicating saved objects"
        )
        population_layout.addWidget(self.population_enabled)
        self.population_form = QFormLayout()
        self.population_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.population_count = QSpinBox()
        self.population_count.setObjectName("PopulationCount")
        self.population_count.setRange(2, 256)
        self.population_count.setKeyboardTracking(False)
        self.population_count.setToolTip("Copy 1 is the object you placed; the rest appear when shown")
        self.population_seed = QDoubleSpinBox()
        self.population_seed.setObjectName("PopulationSeed")
        self.population_seed.setDecimals(0)
        self.population_seed.setRange(0, 4_294_967_295)
        self.population_seed.setSingleStep(1)
        self.population_seed.setKeyboardTracking(False)
        self.population_seed.setToolTip("The same world number always makes the same layout")
        self.population_size_x = _spin(0.5)
        self.population_size_y = _spin(0.5)
        self.population_size_z = _spin(0.5)
        for name, widget in (
            ("PopulationWidth", self.population_size_x),
            ("PopulationHeight", self.population_size_y),
            ("PopulationDepth", self.population_size_z),
        ):
            widget.setObjectName(name)
            widget.setRange(0.0, 100_000.0)
            widget.setDecimals(2)
            widget.setSuffix(" units")
        self.population_scale_min = _spin(0.05)
        self.population_scale_max = _spin(0.05)
        for name, widget in (
            ("PopulationScaleMin", self.population_scale_min),
            ("PopulationScaleMax", self.population_scale_max),
        ):
            widget.setObjectName(name)
            widget.setRange(0.05, 8.0)
            widget.setDecimals(2)
        self.population_random_yaw = QCheckBox("Turn copies randomly")
        self.population_random_yaw.setObjectName("PopulationRandomYawCheck")
        self.population_form.addRow("Objects in group", self.population_count)
        self.population_form.addRow("World number", self.population_seed)
        self.population_form.addRow("Area width", self.population_size_x)
        self.population_form.addRow("Area height", self.population_size_y)
        self.population_form.addRow("Area depth", self.population_size_z)
        self.population_form.addRow("Smallest size", self.population_scale_min)
        self.population_form.addRow("Largest size", self.population_scale_max)
        self.population_form.addRow("", self.population_random_yaw)
        population_layout.addLayout(self.population_form)
        self.population_cost = QLabel()
        self.population_cost.setObjectName("MutedLabel")
        self.population_cost.setWordWrap(True)
        population_layout.addWidget(self.population_cost)
        root.addWidget(self.population_box)
        self.population_box.hide()

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
        self.material_look_combo.currentIndexChanged.connect(self._emit_material_look)
        self.trigger_enabled.toggled.connect(self._trigger_area_changed)
        self.trigger_shape.currentIndexChanged.connect(self._trigger_area_changed)
        for widget in (
            self.trigger_radius,
            self.trigger_size_x,
            self.trigger_size_y,
            self.trigger_size_z,
        ):
            widget.editingFinished.connect(self._emit_trigger_area)
        self.movement_pattern_combo.currentIndexChanged.connect(
            self._movement_pattern_changed
        )
        for widget in (
            self.movement_radius,
            self.movement_speed,
            self.movement_angle,
        ):
            widget.editingFinished.connect(self._emit_movement_pattern)
        self.population_enabled.toggled.connect(self._population_changed)
        self.population_random_yaw.toggled.connect(self._population_changed)
        self.population_count.editingFinished.connect(self._emit_population)
        for widget in (
            self.population_seed,
            self.population_size_x,
            self.population_size_y,
            self.population_size_z,
            self.population_scale_min,
            self.population_scale_max,
        ):
            widget.editingFinished.connect(self._emit_population)

    def clear(self) -> None:
        self._selection = None
        self._mode = None
        self.title.setText("Nothing selected")
        self.subtitle.setText("Click an object in the scene or Scene Tree.")
        self.transform_box.hide()
        self.appearance_box.hide()
        self.trigger_box.hide()
        self.movement_box.hide()
        self.population_box.hide()
        self._set_packed_transform_guard(False)
        self.vector_asset_combo.clear()
        self.mesh_combo.clear()
        self.material_combo.clear()
        self.material_look_combo.setCurrentIndex(
            max(0, self.material_look_combo.findData("custom"))
        )
        self._trigger_values.clear()
        self._trigger_display_values.clear()
        self.movement_pattern_combo.clear()
        self.movement_explanation.clear()
        self.movement_cost.clear()
        self._movement_values.clear()
        self._movement_display_values.clear()
        self._population_values.clear()
        self._population_display_values.clear()
        self.population_explanation.clear()
        self.population_cost.clear()
        self.quick_info.clear()
        self.details.clear()

    def set_selection(self, document: EditorDocument, selection: SelectionRef | None) -> None:
        self._updating = True
        try:
            self._selection = selection
            if selection is None:
                self.clear()
                return
            if selection.kind == "world_graph":
                self.clear()
                self._selection = selection
                self.title.setText("World Logic")
                self.subtitle.setText(
                    f"{friendly(selection.object_id)} · runs for the whole scene"
                )
                self.quick_info.setText(
                    "Open Logic Blocks to edit this graph. It is not attached to "
                    "one object, so Preview shows only its whole-scene Logic Trail."
                )
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
            self._set_trigger_area(document.trigger_area_state(selection))
            self._set_movement_pattern(document.movement_pattern_state(selection))
            self._set_population(document.population_state(selection))
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

    def preview_3d_translation(
        self, object_id: str, translation: Sequence[float]
    ) -> bool:
        """Show a gizmo drag without emitting or changing the document model."""

        if (
            self._selection is None
            or self._selection.object_id != str(object_id)
            or self._mode != "3d"
            or len(translation) != 3
        ):
            return False
        self._updating = True
        try:
            for widget, value in zip((self.x3, self.y3, self.z3), translation):
                widget.setValue(float(value))
        finally:
            self._updating = False
        return True

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
        self.material_look_combo.setCurrentIndex(
            max(0, self.material_look_combo.findData("custom"))
        )
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
            look_index = self.material_look_combo.findData(
                document.material_look_key()
            )
            self.material_look_combo.setCurrentIndex(max(0, look_index))
            if self.mesh_combo.count() and self.material_combo.count():
                self.appearance_stack.setCurrentWidget(self.appearance3d_widget)
                self.appearance_box.show()

    def _set_trigger_area(self, state: Mapping[str, Any] | None) -> None:
        self.trigger_box.hide()
        self._trigger_values.clear()
        self._trigger_display_values.clear()
        if state is None:
            return
        self.trigger_box.show()
        self.trigger_enabled.setChecked(bool(state.get("enabled", False)))
        shape = str(state.get("shape", "sphere"))
        shape_index = self.trigger_shape.findData(shape)
        self.trigger_shape.setCurrentIndex(max(0, shape_index))
        self._trigger_values = {
            "radius": float(state.get("radius", 0.5)),
            "size_x": float(state.get("size_x", 1.0)),
            "size_y": float(state.get("size_y", 1.0)),
            "size_z": float(state.get("size_z", 1.0)),
        }
        controls = {
            "radius": self.trigger_radius,
            "size_x": self.trigger_size_x,
            "size_y": self.trigger_size_y,
            "size_z": self.trigger_size_z,
        }
        for key, widget in controls.items():
            widget.setValue(self._trigger_values[key])
            self._trigger_display_values[key] = widget.value()
        self._refresh_trigger_area_controls()

    def _refresh_trigger_area_controls(self) -> None:
        enabled = self.trigger_enabled.isChecked()
        sphere = self.trigger_shape.currentData() == "sphere"
        self.trigger_shape.setEnabled(enabled)
        self.trigger_radius.setEnabled(enabled and sphere)
        for widget in (
            self.trigger_size_x,
            self.trigger_size_y,
            self.trigger_size_z,
        ):
            widget.setEnabled(enabled and not sphere)
        self.trigger_form.setRowVisible(self.trigger_radius, sphere)
        for widget in (
            self.trigger_size_x,
            self.trigger_size_y,
            self.trigger_size_z,
        ):
            self.trigger_form.setRowVisible(widget, not sphere)
        if enabled:
            self.trigger_explanation.setText(
                "Enter and Exit Trigger Logic Blocks react when the player crosses "
                "this area. It only notices overlap, so it never pushes objects."
            )
        else:
            self.trigger_explanation.setText(
                "Turn this on when Logic Blocks should react to the player entering "
                "or leaving this area."
            )

    def _trigger_area_changed(self, _value: Any = None) -> None:
        if self._updating or self._selection is None:
            return
        self._refresh_trigger_area_controls()
        self._emit_trigger_area()

    def _emit_trigger_area(self) -> None:
        if self._updating or self._selection is None:
            return
        displayed = {
            "radius": self.trigger_radius.value(),
            "size_x": self.trigger_size_x.value(),
            "size_y": self.trigger_size_y.value(),
            "size_z": self.trigger_size_z.value(),
        }
        values: dict[str, Any] = {
            "enabled": self.trigger_enabled.isChecked(),
            "shape": str(self.trigger_shape.currentData() or "sphere"),
        }
        for key, value in displayed.items():
            values[key] = (
                self._trigger_values.get(key, value)
                if value == self._trigger_display_values.get(key)
                else value
            )
        self.triggerAreaEdited.emit(values)

    def _set_packed_transform_guard(self, active: bool) -> None:
        """Keep transform-authoritative packed movement from fighting the form."""

        guarded = (self.x3, self.z3, self.rx3, self.ry3, self.rz3)
        explanation = (
            "The movement pattern controls this value while the game runs. "
            "Choose Off / Static to edit it directly."
        )
        for widget in guarded:
            widget.setEnabled(not active)
            widget.setToolTip(explanation if active else "")

    def _set_movement_pattern(self, state: Mapping[str, Any] | None) -> None:
        self.movement_box.hide()
        self.movement_pattern_combo.clear()
        self._movement_values.clear()
        self._movement_display_values.clear()
        self._set_packed_transform_guard(False)
        if state is None:
            return

        self.movement_box.show()
        dynamic = bool(state.get("dynamic", False))
        has_component = bool(state.get("has_component", False))
        if dynamic:
            if has_component:
                self.movement_pattern_combo.addItem(
                    "Physics conflict (keep for now)", "guarded"
                )
                self.movement_pattern_combo.addItem(
                    "Remove Movement Pattern", "off"
                )
                self.movement_pattern_combo.setEnabled(True)
                self.movement_explanation.setText(
                    "Physics and a movement pattern cannot both steer this object. "
                    "Remove the pattern here, or turn Dynamic off first."
                )
            else:
                self.movement_pattern_combo.addItem(
                    "Unavailable while Dynamic is on", "guarded"
                )
                self.movement_pattern_combo.setEnabled(False)
                self.movement_explanation.setText(
                    "Physics already moves this object. Turn Dynamic off before "
                    "giving it a movement pattern."
                )
            for widget in (
                self.movement_radius,
                self.movement_speed,
                self.movement_angle,
            ):
                widget.setEnabled(False)
            self.movement_cost.setText(
                "Remove the saved movement conflict first. Its compact record uses "
                "about 24 bytes."
                if has_component
                else "No extra packed movement is added while physics owns the object."
            )
            self._set_packed_transform_guard(has_component)
            return

        choices = (
            ("Off / Static", "off", "Stay where you place it."),
            ("Orbit (circle)", "orbit", "Circle the centre at one radius."),
            ("Spiral Out", "spiral_out", "Circle while gently moving outward."),
            ("Spiral In", "spiral_in", "Circle while gently moving inward."),
        )
        for label, value, tooltip in choices:
            self.movement_pattern_combo.addItem(label, value)
            self.movement_pattern_combo.setItemData(
                self.movement_pattern_combo.count() - 1,
                tooltip,
                Qt.ItemDataRole.ToolTipRole,
            )
        pattern = str(state.get("pattern", "off"))
        if pattern == "custom":
            self.movement_pattern_combo.addItem(
                "Custom movement (kept until changed)", "custom"
            )
        elif pattern == "invalid":
            self.movement_pattern_combo.addItem("Movement needs repair", "invalid")
        index = self.movement_pattern_combo.findData(pattern)
        self.movement_pattern_combo.setCurrentIndex(max(0, index))
        self.movement_pattern_combo.setEnabled(True)

        radius_min = max(0.001, float(state.get("radius_min", 0.25)))
        radius_max = max(radius_min, float(state.get("radius_max", 40.0)))
        speed_max = max(0.001, float(state.get("speed_max", 1.0)))
        self.movement_radius.setRange(radius_min, radius_max)
        self.movement_speed.setRange(-speed_max, speed_max)
        self._movement_values = {
            "radius": float(state.get("radius", 3.0)),
            "speed": float(state.get("speed", 0.2)),
            "start_angle": float(state.get("start_angle", 0.0)) % 360.0,
        }
        self.movement_radius.setValue(self._movement_values["radius"])
        self.movement_speed.setValue(self._movement_values["speed"])
        self.movement_angle.setValue(self._movement_values["start_angle"])
        self._movement_display_values = {
            "radius": self.movement_radius.value(),
            "speed": self.movement_speed.value(),
            "start_angle": self.movement_angle.value(),
        }
        self._movement_spiral_rate = max(
            0.0, float(state.get("spiral_rate", 0.2))
        )

        component_bytes = int(state.get("component_bytes", 24))
        lut_kib = float(state.get("shared_lut_bytes", 0)) / 1024.0
        resolution = int(state.get("lut_resolution", 128))
        if has_component:
            self.movement_cost.setText(
                f"Compact on Android: about {component_bytes} bytes for this object, "
                f"plus one shared {resolution}-step lookup (about {lut_kib:.1f} KiB)."
            )
        else:
            self.movement_cost.setText(
                f"Off adds no movement record. A preset uses about {component_bytes} "
                f"bytes per object plus one shared {resolution}-step lookup "
                f"(about {lut_kib:.1f} KiB)."
            )
        self._refresh_movement_controls()
        self._set_packed_transform_guard(has_component)

    def _refresh_movement_controls(self) -> None:
        pattern = str(self.movement_pattern_combo.currentData() or "guarded")
        editable = pattern in {"orbit", "spiral_out", "spiral_in"}
        for widget in (
            self.movement_radius,
            self.movement_speed,
            self.movement_angle,
        ):
            widget.setEnabled(editable)
        outward_percent = (math.exp(self._movement_spiral_rate) - 1.0) * 100.0
        inward_percent = (1.0 - math.exp(-self._movement_spiral_rate)) * 100.0
        explanations = {
            "off": "This object stays where you place it.",
            "orbit": (
                "The object circles the world centre at a fixed radius. "
                "Use a minus speed to reverse direction."
            ),
            "spiral_out": (
                "The object circles while its radius grows gently "
                f"(about {outward_percent:.0f}% each second)."
            ),
            "spiral_in": (
                "The object circles while its radius shrinks gently "
                f"(about {inward_percent:.0f}% each second)."
            ),
            "custom": (
                "This saved movement uses advanced values. It stays unchanged until "
                "you choose one of the simple presets."
            ),
            "invalid": (
                "This saved movement cannot be read. Choose Off / Static or a preset "
                "to repair it."
            ),
        }
        if pattern in explanations:
            self.movement_explanation.setText(explanations[pattern])

    def _movement_pattern_changed(self, _index: int = -1) -> None:
        if self._updating or self._selection is None:
            return
        self._refresh_movement_controls()
        self._emit_movement_pattern()

    def _emit_movement_pattern(self) -> None:
        if self._updating or self._selection is None:
            return
        pattern = str(self.movement_pattern_combo.currentData() or "")
        if pattern not in {"off", "orbit", "spiral_out", "spiral_in"}:
            return
        displayed = {
            "pattern": pattern,
            "radius": self.movement_radius.value(),
            "speed": self.movement_speed.value(),
            "start_angle": self.movement_angle.value(),
        }
        values = {"pattern": pattern}
        for key in ("radius", "speed", "start_angle"):
            value = float(displayed[key])
            if value == self._movement_display_values.get(key):
                value = self._movement_values.get(key, value)
            values[key] = value
        self.movementPatternEdited.emit(values)

    def _set_population(self, state: Mapping[str, Any] | None) -> None:
        self.population_box.hide()
        self._population_values.clear()
        self._population_display_values.clear()
        self._population_can_enable = False
        if state is None:
            return
        self.population_box.show()
        enabled = bool(state.get("enabled", False))
        self._population_can_enable = bool(state.get("can_enable", False))
        self.population_enabled.setChecked(enabled)
        # A conflicting/old recipe must always remain removable.
        self.population_enabled.setEnabled(enabled or self._population_can_enable)
        self._population_values = {
            "instance_count": float(state.get("instance_count", 8)),
            "seed": float(state.get("seed", 1)),
            "size_x": float(state.get("size_x", 8.0)),
            "size_y": float(state.get("size_y", 0.0)),
            "size_z": float(state.get("size_z", 8.0)),
            "scale_min": float(state.get("scale_min", 0.85)),
            "scale_max": float(state.get("scale_max", 1.15)),
        }
        self.population_count.setValue(int(self._population_values["instance_count"]))
        self.population_seed.setValue(self._population_values["seed"])
        for key, widget in (
            ("size_x", self.population_size_x),
            ("size_y", self.population_size_y),
            ("size_z", self.population_size_z),
            ("scale_min", self.population_scale_min),
            ("scale_max", self.population_scale_max),
        ):
            widget.setValue(self._population_values[key])
        self.population_random_yaw.setChecked(bool(state.get("random_yaw", True)))
        self._population_display_values = {
            "instance_count": float(self.population_count.value()),
            "seed": self.population_seed.value(),
            "size_x": self.population_size_x.value(),
            "size_y": self.population_size_y.value(),
            "size_z": self.population_size_z.value(),
            "scale_min": self.population_scale_min.value(),
            "scale_max": self.population_scale_max.value(),
        }
        error = str(state.get("error", ""))
        if error:
            self.population_explanation.setText(error)
        elif enabled:
            count = int(self._population_values["instance_count"])
            self.population_explanation.setText(
                f"One saved object becomes {count} static display objects when playing "
                "or building. Copies share the same shape and material."
            )
        else:
            self.population_explanation.setText(
                "Turn this on to fill an area with compact, repeatable display copies. "
                "Use ordinary Duplicate when copies need gameplay or Logic Blocks."
            )
        recipe_bytes = int(state.get("recipe_bytes", 36))
        header_bytes = int(state.get("shared_header_bytes", 24))
        budget = int(state.get("quality_budget", 0))
        cost = (
            f"Compact Android recipe: {recipe_bytes} bytes for this group plus one "
            f"shared {header_bytes}-byte header; copies are generated at load time."
        )
        if bool(state.get("over_start_budget", False)) and budget:
            cost += f" The starting quality shows a deterministic prefix of up to {budget} objects."
        self.population_cost.setText(cost)
        self._refresh_population_controls()

    def _refresh_population_controls(self) -> None:
        editable = self.population_enabled.isChecked() and self._population_can_enable
        for widget in (
            self.population_count,
            self.population_seed,
            self.population_size_x,
            self.population_size_y,
            self.population_size_z,
            self.population_scale_min,
            self.population_scale_max,
            self.population_random_yaw,
        ):
            widget.setEnabled(editable)

    def _population_changed(self, _value: Any = None) -> None:
        if self._updating or self._selection is None:
            return
        self._refresh_population_controls()
        self._emit_population()

    def _emit_population(self) -> None:
        if self._updating or self._selection is None:
            return
        displayed = {
            "instance_count": float(self.population_count.value()),
            "seed": self.population_seed.value(),
            "size_x": self.population_size_x.value(),
            "size_y": self.population_size_y.value(),
            "size_z": self.population_size_z.value(),
            "scale_min": self.population_scale_min.value(),
            "scale_max": self.population_scale_max.value(),
        }
        values: dict[str, Any] = {
            "enabled": self.population_enabled.isChecked(),
            "random_yaw": self.population_random_yaw.isChecked(),
        }
        for key, displayed_value in displayed.items():
            value = (
                self._population_values.get(key, displayed_value)
                if displayed_value == self._population_display_values.get(key)
                else displayed_value
            )
            if key in {"instance_count", "seed"}:
                value = int(value)
            values[key] = value
        self.populationEdited.emit(values)

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

    def _emit_material_look(self) -> None:
        if self._updating or self._selection is None:
            return
        look = self.material_look_combo.currentData()
        if isinstance(look, str):
            self.materialLookEdited.emit(look)

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
        if str(key) == "packed_kinematic":
            parent.addChild(
                QTreeWidgetItem(
                    ["Movement Pattern", "Packed compactly; use the friendly controls above"]
                )
            )
            return
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
    addTriggerRequested = Signal()
    duplicateRequested = Signal()
    deleteRequested = Signal()
    saveReusableRequested = Signal()
    addReusableRequested = Signal()
    removeReusableRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._has_document = False
        self._is_3d_document = False
        self._has_reusable_objects = False
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
        self.add_trigger_button = QPushButton("+ Trigger Area")
        self.add_trigger_button.setObjectName("SceneAddTriggerButton")
        self.add_trigger_button.setToolTip(
            "Add an area that Logic Blocks can notice when the player enters or leaves"
        )
        self.add_trigger_button.hide()
        reusable_controls = QHBoxLayout()
        reusable_controls.setSpacing(5)
        self.save_reusable_button = QPushButton("Save Object")
        self.save_reusable_button.setObjectName("SceneSaveReusableButton")
        self.save_reusable_button.setToolTip(
            "Save a one-time snapshot of shape, look and physics; later edits do not update it, and Logic Blocks stay shared"
        )
        self.add_reusable_button = QPushButton("+ Saved Object…")
        self.add_reusable_button.setObjectName("SceneAddReusableButton")
        self.add_reusable_button.setToolTip(
            "Place a fresh object from your Saved Objects library"
        )
        self.remove_reusable_button = QPushButton("Remove Saved…")
        self.remove_reusable_button.setObjectName("SceneRemoveReusableButton")
        self.remove_reusable_button.setToolTip(
            "Remove a Saved Objects library entry; objects already placed stay in the scene"
        )
        self.save_reusable_button.hide()
        self.add_reusable_button.hide()
        self.remove_reusable_button.hide()
        reusable_controls.addWidget(self.save_reusable_button)
        reusable_controls.addWidget(self.add_reusable_button)
        reusable_controls.addWidget(self.remove_reusable_button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an object…")
        self.search.setClearButtonEnabled(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Kind"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addLayout(controls)
        layout.addWidget(self.add_trigger_button)
        layout.addLayout(reusable_controls)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        self.add_button.clicked.connect(self.addRequested)
        self.add_trigger_button.clicked.connect(self.addTriggerRequested)
        self.duplicate_button.clicked.connect(self.duplicateRequested)
        self.delete_button.clicked.connect(self.deleteRequested)
        self.save_reusable_button.clicked.connect(self.saveReusableRequested)
        self.add_reusable_button.clicked.connect(self.addReusableRequested)
        self.remove_reusable_button.clicked.connect(self.removeReusableRequested)
        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(self._current_changed)
        self._update_authoring_buttons()

    def set_document(self, document: EditorDocument | None) -> None:
        self._has_document = document is not None and document.project is not None
        self._is_3d_document = bool(
            document is not None and isinstance(document.project, Mobile3DProject)
        )
        try:
            self._has_reusable_objects = bool(
                document is not None and document.reusable_objects()
            )
        except (TypeError, ValueError):
            self._has_reusable_objects = False
        self._selection = None if document is None else document.selection
        self.add_trigger_button.setVisible(self._is_3d_document)
        self.save_reusable_button.setVisible(self._is_3d_document)
        self.add_reusable_button.setVisible(self._is_3d_document)
        self.remove_reusable_button.setVisible(self._is_3d_document)
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
                world_graph_ids = document.world_graph_ids(scene_id)
                if world_graph_ids:
                    logic_item = QTreeWidgetItem(["World Logic", "Whole Scene"])
                    logic_item.setExpanded(True)
                    logic_item.setToolTip(
                        0,
                        "Logic Blocks that run for the whole scene instead of one object",
                    )
                    scene_item.addChild(logic_item)
                    for graph_id in world_graph_ids:
                        item = QTreeWidgetItem(
                            [
                                document.graph_title(graph_id, scene_id)
                                or friendly(graph_id),
                                "World Logic",
                            ]
                        )
                        item.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            SelectionRef("world_graph", graph_id, scene_id),
                        )
                        item.setToolTip(
                            0,
                            f"Whole-scene Logic Blocks · Project ID: {graph_id}",
                        )
                        logic_item.addChild(item)
        else:
            scene_item = QTreeWidgetItem(["Main 3D Scene", "3D Scene"])
            scene_item.setExpanded(True)
            root.addChild(scene_item)
            for node in document.project.nodes:
                reusable_id = reusable_source_id(node)
                if node.collider.sensor and node.collider.shape != "none":
                    kind = "Saved Trigger" if reusable_id is not None else "Trigger Area"
                elif "player" in node.tags:
                    kind = "Saved Player" if reusable_id is not None else "Player"
                elif reusable_id is not None:
                    kind = "Saved Object"
                else:
                    kind = "3D Object"
                item = QTreeWidgetItem([friendly(node.id), kind])
                item.setData(0, Qt.ItemDataRole.UserRole, SelectionRef("node", node.id))
                if kind in {"Trigger Area", "Saved Trigger"}:
                    shape = "sphere" if node.collider.shape == "sphere" else "box"
                    item.setToolTip(
                        0,
                        f"A {shape} area that notices the player without pushing anything"
                        + (
                            " · placed from Saved Objects; its Logic Blocks stay shared"
                            if reusable_id is not None
                            else ""
                        ),
                    )
                elif reusable_id is not None:
                    item.setToolTip(
                        0,
                        "Placed from Saved Objects · position, look and physics are editable; Logic Blocks stay shared",
                    )
                else:
                    item.setToolTip(0, f"Mesh: {node.mesh_id} · Material: {node.material_id}")
                scene_item.addChild(item)
            world_graph_ids = document.world_graph_ids()
            if world_graph_ids:
                logic_item = QTreeWidgetItem(["World Logic", "Whole Scene"])
                logic_item.setExpanded(True)
                logic_item.setToolTip(
                    0,
                    "Logic Blocks that run for the whole scene instead of one object",
                )
                scene_item.addChild(logic_item)
                for graph_id in world_graph_ids:
                    item = QTreeWidgetItem(
                        [document.graph_title(graph_id) or friendly(graph_id), "World Logic"]
                    )
                    item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        SelectionRef("world_graph", graph_id),
                    )
                    item.setToolTip(
                        0,
                        f"Whole-scene Logic Blocks · Project ID: {graph_id}",
                    )
                    logic_item.addChild(item)
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
        can_edit_selection = (
            can_add
            and self._selection is not None
            and self._selection.kind in {"entity", "node"}
        )
        self.add_button.setEnabled(can_add)
        self.add_trigger_button.setEnabled(can_add and self._is_3d_document)
        self.duplicate_button.setEnabled(can_edit_selection)
        self.delete_button.setEnabled(can_edit_selection)
        self.save_reusable_button.setEnabled(
            can_edit_selection and self._is_3d_document
        )
        self.add_reusable_button.setEnabled(
            can_add and self._is_3d_document and self._has_reusable_objects
        )
        self.remove_reusable_button.setEnabled(
            can_add and self._is_3d_document and self._has_reusable_objects
        )

    def _current_changed(self, current: QTreeWidgetItem | None, previous=None) -> None:
        if current is None:
            self.selectionRequested.emit(None)
            return
        selection = current.data(0, Qt.ItemDataRole.UserRole)
        scene_id = current.data(0, Qt.ItemDataRole.UserRole + 1)
        if isinstance(selection, SelectionRef):
            self.selectionRequested.emit(selection)
        elif scene_id:
            self.sceneRequested.emit(str(scene_id))
        else:
            self.selectionRequested.emit(None)

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
        self.lesson_scroll = QScrollArea()
        self.lesson_scroll.setObjectName("FirstStepsScrollArea")
        self.lesson_scroll.setWidgetResizable(True)
        self.lesson_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lesson_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        lesson_content = QWidget()
        lesson_layout = QVBoxLayout(lesson_content)
        lesson_layout.setContentsMargins(12, 12, 12, 12)
        lesson_layout.setSpacing(10)
        self.lesson_title = QLabel()
        self.lesson_title.setObjectName("PanelTitle")
        self.lesson_title.setTextFormat(Qt.TextFormat.PlainText)
        self.lesson_title.setWordWrap(True)
        self.lesson_intro = QLabel("Try one step at a time. You can come back here whenever you like.")
        self.lesson_intro.setObjectName("MutedLabel")
        self.lesson_intro.setWordWrap(True)
        self.lesson_steps = QLabel()
        self.lesson_steps.setObjectName("FirstStepsList")
        self.lesson_steps.setTextFormat(Qt.TextFormat.PlainText)
        self.lesson_steps.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.lesson_steps.setWordWrap(True)
        lesson_layout.addWidget(self.lesson_title)
        lesson_layout.addWidget(self.lesson_intro)
        lesson_layout.addWidget(self.lesson_steps)
        lesson_layout.addStretch(1)
        self.lesson_scroll.setWidget(lesson_content)
        self.addTab(self.assets, "Resources")
        self.addTab(self.summary, "Project")
        self.lesson_tab_index = self.addTab(self.lesson_scroll, "First Steps")
        self._has_lesson = False
        self.setTabVisible(self.lesson_tab_index, False)

    @staticmethod
    def _category(name: str, count: int, parent: QTreeWidgetItem | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, str(count)])
        item.setExpanded(True)
        if parent is not None:
            parent.addChild(item)
        return item

    @staticmethod
    def _validated_lesson(value: object) -> tuple[str, tuple[str, ...]] | None:
        if not isinstance(value, Mapping):
            return None
        raw_title = value.get("title")
        raw_steps = value.get("steps")
        if not isinstance(raw_title, str) or not raw_title.strip():
            return None
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)):
            return None
        steps: list[str] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, str) or not raw_step.strip():
                return None
            steps.append(raw_step.strip())
        if not steps:
            return None
        return raw_title.strip(), tuple(steps)

    @classmethod
    def _document_lesson(
        cls, document: EditorDocument | None
    ) -> tuple[str, tuple[str, ...]] | None:
        if document is None or document.project is None:
            return None
        project = document.project
        if isinstance(project, GameProject):
            scene_id = document.current_scene_id or project.start_scene
            scene = project.scenes.get(scene_id)
            source = scene.rules if scene is not None else None
        else:
            source = project.metadata
        if not isinstance(source, Mapping):
            return None
        return cls._validated_lesson(source.get("lesson"))

    def clear_lesson(self) -> None:
        was_current = self.currentIndex() == self.lesson_tab_index
        self._has_lesson = False
        self.lesson_title.clear()
        self.lesson_steps.clear()
        self.setTabVisible(self.lesson_tab_index, False)
        if was_current:
            self.setCurrentIndex(0)

    def refresh_lesson(self, document: EditorDocument | None) -> bool:
        lesson = self._document_lesson(document)
        if lesson is None:
            self.clear_lesson()
            return False
        title, steps = lesson
        self.lesson_title.setText(title)
        self.lesson_steps.setText(
            "\n\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
        )
        self._has_lesson = True
        self.setTabVisible(self.lesson_tab_index, True)
        return True

    def show_lesson(self) -> bool:
        if not self._has_lesson:
            return False
        self.setCurrentIndex(self.lesson_tab_index)
        return True

    def set_document(self, document: EditorDocument | None) -> None:
        self.assets.clear()
        self.refresh_lesson(document)
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
            trigger_nodes = [
                node
                for node in project.nodes
                if node.collider.sensor and node.collider.shape != "none"
            ]
            triggers = self._category("Trigger Areas", len(trigger_nodes))
            for node in trigger_nodes:
                if node.collider.shape == "sphere":
                    size_text = f"Sphere · radius {node.collider.radius:g}"
                else:
                    full_size = tuple(value * 2.0 for value in node.collider.half_extents)
                    size_text = (
                        f"Box · {full_size[0]:g} × {full_size[1]:g} × {full_size[2]:g}"
                    )
                triggers.addChild(QTreeWidgetItem([friendly(node.id), size_text]))
            movement_nodes = [
                node
                for node in project.nodes
                if isinstance(node.metadata.get("packed_kinematic"), Mapping)
            ]
            movement = self._category("Movement Patterns", len(movement_nodes))
            pattern_labels = {
                "orbit": "Orbit",
                "spiral_out": "Spiral Out",
                "spiral_in": "Spiral In",
                "custom": "Custom Movement",
                "invalid": "Needs Repair",
            }
            referenced_profiles: set[str] = set()
            for node in movement_nodes:
                raw_component = node.metadata.get("packed_kinematic", {})
                if isinstance(raw_component, Mapping):
                    profile_id = raw_component.get("profile")
                    if isinstance(profile_id, str) and profile_id:
                        referenced_profiles.add(profile_id)
                state = document.movement_pattern_state(SelectionRef("node", node.id))
                pattern = "custom" if state is None else str(state.get("pattern", "custom"))
                movement.addChild(
                    QTreeWidgetItem(
                        [friendly(node.id), f"{pattern_labels.get(pattern, 'Movement')} · about 24 bytes"]
                    )
                )
            if referenced_profiles:
                movement.addChild(
                    QTreeWidgetItem(
                        [
                            "Shared lookups",
                            f"{len(referenced_profiles)} compact table(s), reused by objects",
                        ]
                    )
                )
            population_nodes = [
                node
                for node in project.nodes
                if isinstance(node.metadata.get("scatter_population"), Mapping)
            ]
            populations = self._category("Populated Areas", len(population_nodes))
            for node in population_nodes:
                raw_population = node.metadata.get("scatter_population", {})
                count = raw_population.get("instance_count", "?")
                populations.addChild(
                    QTreeWidgetItem(
                        [
                            friendly(node.id),
                            f"{count} display objects · 36-byte recipe",
                        ]
                    )
                )
            reusable_objects = document.reusable_objects()
            reusable = self._category("Saved Objects", len(reusable_objects))
            for definition in reusable_objects:
                instance_count = sum(
                    reusable_source_id(node) == definition.id
                    for node in project.nodes
                )
                reusable.addChild(
                    QTreeWidgetItem(
                        [
                            definition.label,
                            f"{instance_count} placed · {friendly(definition.node.mesh_id)}",
                        ]
                    )
                )
            profiles = self._category("Android Devices", len(project.target_profiles))
            for profile in project.target_profiles:
                profiles.addChild(QTreeWidgetItem([profile.label, f"{profile.target_refresh_hz} Hz target"]))
            for category in (
                meshes,
                materials,
                reusable,
                triggers,
                movement,
                populations,
                profiles,
            ):
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
            self.target.addItem("Poco: Build + Install + Open", "android-install")
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
