"""QGraphicsView scene authoring previews for UGTS 2D and mobile 3D."""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
import math
import re
from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGradient,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QToolButton,
    QWidget,
)

from ..hierarchy3d import Hierarchy3DError, world_trs_by_id
from ..materials import shade_pbr_lite
from ..math3d import compose_trs, transform_point
from ..mobile3d import Mobile3DProject, Node3DRecord
from ..packed_kinematics import PackedKinematicComponent, PolarLookupTable
from ..polar_population import (
    POLAR_POPULATION_PRESET_LABELS,
    PolarPopulationError,
    PolarPopulationGroup,
    collect_polar_population_project_spec,
    polar_population_glow_sample,
    polar_population_instance,
)
from ..polarpack import quantized_profile_lut
from ..project import EntitySpec, GameProject
from ..renderpack import (
    RenderPackError,
    RenderSubstrateConfig,
    render_substrate_config_from_project,
)
from ..scatter import ScatterError, collect_scatter_project_spec, scatter_instances
from ..saved_scene import materialize_saved_scenes
from ..vector2d import LinearGradient, RadialGradient, VectorAsset2D, VectorPath
from .device_look import (
    DeviceLookOpenGLViewport,
    DeviceLookSupport,
    probe_device_look_gl,
)
from .document import EditorDocument


_RGBA_RE = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)",
    re.IGNORECASE,
)


def _color(value: str | QColor | None, fallback: str = "#ffffff") -> QColor:
    if isinstance(value, QColor):
        return QColor(value)
    text = fallback if value is None else str(value)
    match = _RGBA_RE.fullmatch(text)
    if match:
        red, green, blue = (max(0, min(255, int(float(match.group(i))))) for i in range(1, 4))
        alpha_text = match.group(4)
        alpha = 255 if alpha_text is None else max(0, min(255, int(float(alpha_text) * 255)))
        return QColor(red, green, blue, alpha)
    result = QColor(text)
    return result if result.isValid() else QColor(fallback)


def _friendly_name(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _path(path: VectorPath) -> QPainterPath:
    result = QPainterPath()
    for command in path.commands:
        operation, values = command.op.upper(), command.values
        if operation == "M":
            result.moveTo(values[0], values[1])
        elif operation == "L":
            result.lineTo(values[0], values[1])
        elif operation == "Q":
            result.quadTo(values[0], values[1], values[2], values[3])
        elif operation == "C":
            result.cubicTo(*values)
        elif operation == "Z":
            result.closeSubpath()
    result.setFillRule(
        Qt.FillRule.OddEvenFill if path.fill_rule == "evenodd" else Qt.FillRule.WindingFill
    )
    return result


def _gradient_brush(asset: VectorAsset2D, value: str | None) -> QBrush:
    if not value:
        return QBrush(Qt.BrushStyle.NoBrush)
    if not value.startswith("@"):
        return QBrush(_color(value))
    gradient = next((item for item in asset.gradients if item.id == value[1:]), None)
    if isinstance(gradient, LinearGradient):
        brush_gradient: QGradient = QLinearGradient(
            gradient.start[0], gradient.start[1], gradient.end[0], gradient.end[1]
        )
    elif isinstance(gradient, RadialGradient):
        focal = gradient.focal or gradient.center
        brush_gradient = QRadialGradient(
            gradient.center[0], gradient.center[1], gradient.radius, focal[0], focal[1]
        )
    else:
        return QBrush(_color("#ff66c4"))
    brush_gradient.setCoordinateMode(QGradient.CoordinateMode.LogicalMode)
    for stop in gradient.stops:
        brush_gradient.setColorAt(stop.offset, _color(stop.color))
    return QBrush(brush_gradient)


class EntityGraphicsItem(QGraphicsItemGroup):
    """Movable vector sprite that commits one undoable move on release."""

    def __init__(
        self,
        object_id: str,
        on_selected: Callable[[str], None],
        on_moved: Callable[[str, QPointF, QPointF], None],
    ) -> None:
        super().__init__()
        self.object_id = object_id
        self._on_selected = on_selected
        self._on_moved = on_moved
        self._press_position = QPointF()
        self.setData(0, object_id)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._press_position = QPointF(self.pos())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)
        self._on_selected(self.object_id)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self.pos() != self._press_position:
            self._on_moved(self.object_id, self._press_position, self.pos())


def _sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return float(a[0] - b[0]), float(a[1] - b[1]), float(a[2] - b[2])


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        float(a[1] * b[2] - a[2] * b[1]),
        float(a[2] * b[0] - a[0] * b[2]),
        float(a[0] * b[1] - a[1] * b[0]),
    )


def _normalized(value: Sequence[float]) -> tuple[float, float, float]:
    length = math.sqrt(_dot(value, value))
    if length <= 1.0e-9:
        return 0.0, 0.0, 0.0
    return float(value[0] / length), float(value[1] / length), float(value[2] / length)


class _PerspectiveProjector:
    def __init__(self, project: Mobile3DProject, width: float, height: float) -> None:
        camera = project.camera
        self.position = camera.position
        self.forward = _normalized(_sub(camera.target, camera.position))
        self.right = _normalized(_cross(self.forward, camera.up))
        self.up = _normalized(_cross(self.right, self.forward))
        self.near = camera.near
        self.width, self.height = width, height
        self.focal = height * 0.5 / math.tan(math.radians(camera.vertical_fov_degrees) * 0.5)

    def project(self, point: Sequence[float]) -> tuple[QPointF, float] | None:
        relative = _sub(point, self.position)
        depth = _dot(relative, self.forward)
        if depth <= self.near:
            return None
        x = self.width * 0.5 + _dot(relative, self.right) * self.focal / depth
        y = self.height * 0.5 - _dot(relative, self.up) * self.focal / depth
        return QPointF(x, y), depth


class ProjectedMeshItem(QGraphicsItem):
    """Paint all visible faces of one node as a single lightweight scene item."""

    def __init__(
        self,
        object_id: str,
        faces: list[tuple[float, QPolygonF, QColor]],
        selected: bool,
    ) -> None:
        super().__init__()
        self.object_id = object_id
        self.faces = sorted(faces, key=lambda item: item[0], reverse=True)
        self.selected = selected
        bounds = QRectF()
        for _, polygon, _ in self.faces:
            bounds = bounds.united(polygon.boundingRect())
        self._bounds = bounds.adjusted(-3, -3, 3, 3)
        self.setData(0, object_id)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setToolTip(f"{_friendly_name(object_id)}\nClick to inspect its 3D transform")

    def set_faces(self, faces: list[tuple[float, QPolygonF, QColor]]) -> None:
        """Replace projected geometry without rebuilding the QGraphicsScene."""

        self.prepareGeometryChange()
        self.faces = sorted(faces, key=lambda item: item[0], reverse=True)
        bounds = QRectF()
        for _, polygon, _ in self.faces:
            bounds = bounds.united(polygon.boundingRect())
        self._bounds = bounds.adjusted(-3, -3, 3, 3)
        self.update()

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return self._bounds

    def shape(self) -> QPainterPath:  # type: ignore[override]
        path = QPainterPath()
        for _, polygon, _ in self.faces:
            path.addPolygon(polygon)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        highlighted = self.selected or self.isSelected()
        for _, polygon, color in self.faces:
            painter.setBrush(color)
            painter.setPen(
                QPen(QColor("#65dbff"), 1.55)
                if highlighted
                else QPen(color.darker(145), 0.7)
            )
            painter.drawPolygon(polygon)


class TranslationGizmoHandle(QGraphicsObject):
    """One wide, child-readable 3D translation axis handle."""

    def __init__(
        self,
        object_id: str,
        axis: str,
        color: QColor,
        active_tooltip: str,
        authority_lock_reason: str | None,
        on_begin: Callable[["TranslationGizmoHandle", QPointF], bool],
        on_preview: Callable[["TranslationGizmoHandle", QPointF], None],
        on_finish: Callable[["TranslationGizmoHandle", QPointF], None],
        on_help: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.object_id = object_id
        self.axis = axis
        self.color = QColor(color)
        self.active_tooltip = active_tooltip
        self.authority_lock_reason = authority_lock_reason
        self.projection_lock_reason: str | None = None
        self._on_begin = on_begin
        self._on_preview = on_preview
        self._on_finish = on_finish
        self._on_help = on_help
        self._endpoint = QPointF(24.0, 0.0)
        self._shape = QPainterPath()
        self._bounds = QRectF()
        self._dragging = False
        self._locked_press = False
        self.setData(10, object_id)
        self.setData(11, axis)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setZValue(2_000_000)
        self._rebuild_shape()
        self._refresh_interaction()

    @property
    def endpoint(self) -> QPointF:
        return QPointF(self._endpoint)

    @property
    def locked_reason(self) -> str | None:
        return self.authority_lock_reason or self.projection_lock_reason

    @property
    def locked(self) -> bool:
        return self.locked_reason is not None

    def drag_point(self) -> QPointF:
        """Return a stable point inside the handle's wide hit target."""

        return self._endpoint * 0.72

    def set_geometry(
        self,
        origin: QPointF,
        endpoint: QPointF,
        *,
        projection_lock_reason: str | None = None,
    ) -> None:
        self.prepareGeometryChange()
        self._endpoint = QPointF(endpoint)
        self.projection_lock_reason = projection_lock_reason
        self._rebuild_shape(prepared=True)
        self.setPos(origin)
        self._refresh_interaction()
        self.update()

    def _rebuild_shape(self, *, prepared: bool = False) -> None:
        if not prepared:
            self.prepareGeometryChange()
        centre_line = QPainterPath()
        centre_line.moveTo(0.0, 0.0)
        centre_line.lineTo(self._endpoint)
        stroker = QPainterPathStroker()
        stroker.setWidth(18.0)
        hit_shape = stroker.createStroke(centre_line)
        knob = QPainterPath()
        knob.addEllipse(self._endpoint, 9.0, 9.0)
        self._shape = hit_shape.united(knob)
        label_bounds = QRectF(
            self._endpoint.x() - 18.0,
            self._endpoint.y() - 24.0,
            42.0,
            44.0,
        )
        self._bounds = self._shape.boundingRect().united(label_bounds).adjusted(-2, -2, 2, 2)

    def _refresh_interaction(self) -> None:
        reason = self.locked_reason
        self.setToolTip(reason or self.active_tooltip)
        self.setCursor(
            Qt.CursorShape.ForbiddenCursor if reason else Qt.CursorShape.OpenHandCursor
        )

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return self._bounds

    def shape(self) -> QPainterPath:  # type: ignore[override]
        return self._shape

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.color)
        if self.locked:
            color.setAlpha(105)
        pen = QPen(
            color,
            4.0,
            Qt.PenStyle.DashLine if self.locked else Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(color)
        painter.drawLine(QPointF(), self._endpoint)
        painter.drawEllipse(self._endpoint, 6.5, 6.5)
        painter.setPen(QPen(color.lighter(125), 1.0))
        painter.drawText(self._endpoint + QPointF(8.0, -8.0), self.axis.upper())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self.locked:
            self._locked_press = True
            self._on_help(self.locked_reason or "This handle is locked for now.")
            event.accept()
            return
        self._dragging = self._on_begin(self, event.scenePos())
        if self._dragging:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._locked_press:
            event.accept()
            return
        if self._dragging:
            self._on_preview(self, event.scenePos())
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._locked_press = False
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._on_finish(self, event.scenePos())
        event.accept()


@dataclass
class _TranslationDrag:
    object_id: str
    axis: str
    axis_index: int
    press_position: QPointF
    screen_direction: QPointF
    projected_pixels_per_unit: float
    base_translation: tuple[float, float, float]
    current_translation: tuple[float, float, float]


@dataclass(frozen=True)
class _PolarPopulationPreview:
    """One already-created display item and its authored random-access recipe."""

    prototype: Node3DRecord
    group: PolarPopulationGroup
    lut: PolarLookupTable
    index: int
    item: ProjectedMeshItem


class SceneViewport(QGraphicsView):
    """Editable 2D scene view and projected 3D mesh preview."""

    selectionRequested = Signal(str)
    entityMoved = Signal(str, object, object)
    translationPreviewed = Signal(str, object)
    gizmoHelpRequested = Signal(str)
    mouseScenePosition = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SceneViewport")
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._document: EditorDocument | None = None
        self._runtime_state: Mapping[str, Mapping[str, Any]] | None = None
        self._selected_id: str | None = None
        self._rendering = False
        self._first_render = True
        self._playing = False
        self._panning = False
        self._pan_origin = QPointF()
        self._mesh_items: dict[str, ProjectedMeshItem] = {}
        self._mesh_runtime_transforms: dict[str, tuple[Any, ...]] = {}
        self._chrono_pixmap_item: QGraphicsPixmapItem | None = None
        self._chrono_frame_receipt: dict[str, Any] | None = None
        self._polar_population_previews: list[_PolarPopulationPreview] = []
        self._saved_scene_owner_by_node: dict[str, str] = {}
        self._gizmo_handles: dict[str, TranslationGizmoHandle] = {}
        self._translation_drag: _TranslationDrag | None = None
        self._device_look_config: RenderSubstrateConfig | None = None
        self._device_look_config_error = ""
        self._device_look_support: DeviceLookSupport | None = None
        self._device_look_failure_reason = ""
        self._device_look_fallback_pending = False
        self._device_look_toggle = QToolButton(self)
        self._device_look_toggle.setObjectName("DeviceLookReferenceToggle")
        self._device_look_toggle.setCheckable(True)
        self._device_look_toggle.setAutoRaise(False)
        self._device_look_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._device_look_toggle.setToolTip(
            "Desktop reference only: applies the project's native Bayer presentation "
            "after the editor's exact binary16 polar-LUT composition. This does not "
            "reproduce or measure Android GPU performance. The editor grid and gizmos "
            "are included in this reference pass."
        )
        self._device_look_toggle.toggled.connect(self._device_look_toggled)
        self._set_device_look_text()
        self._device_look_toggle.hide()
        self.pressed_keys: set[str] = set()
        self.scene().selectionChanged.connect(self._scene_selection_changed)

    @property
    def gizmo_handles(self) -> tuple[TranslationGizmoHandle, ...]:
        """Expose the three current handles for accessibility and focused tests."""

        return tuple(
            self._gizmo_handles[axis]
            for axis in ("x", "y", "z")
            if axis in self._gizmo_handles
        )

    @property
    def device_look_toggle(self) -> QToolButton:
        """Expose the honest reference toggle for accessibility and focused tests."""

        return self._device_look_toggle

    @property
    def device_look_status(self) -> str:
        """Return the visible reference/fallback state."""

        return self._device_look_toggle.text()

    @property
    def device_look_uses_opengl(self) -> bool:
        """Whether the optional GL viewport is currently installed."""

        return isinstance(self.viewport(), DeviceLookOpenGLViewport)

    @property
    def chrono_frame_receipt(self) -> Mapping[str, Any] | None:
        """Receipt for the exact pre-presentation raster currently displayed."""

        return self._chrono_frame_receipt

    def set_chrono_frame(
        self, frame: Any | None, *, owner_node_id: str | None = None
    ) -> None:
        """Publish an exact chrono raster as the desktop scene background.

        The RGB buffer is exact before this method.  Qt scaling and the desktop
        compositor remain downstream presentation and are intentionally not
        represented as physically exact timing or pixel output.
        """

        previous = self._chrono_pixmap_item
        if previous is not None and previous.scene() is self.scene():
            self.scene().removeItem(previous)
        self._chrono_pixmap_item = None
        self._chrono_frame_receipt = None
        if frame is None:
            self.viewport().update()
            return
        rgb = frame.rgb
        shape = getattr(rgb, "shape", None)
        if (
            not isinstance(shape, tuple)
            or len(shape) != 3
            or shape[2] != 3
            or str(getattr(rgb, "dtype", "")) != "uint8"
        ):
            raise ValueError("chrono desktop frame must be an HxWx3 RGB uint8 raster")
        if not bool(rgb.flags.c_contiguous):
            rgb = rgb.copy(order="C")
        height, width, _channels = shape
        image = QImage(
            rgb.data,
            width,
            height,
            int(rgb.strides[0]),
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            1280,
            720,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        item = QGraphicsPixmapItem(pixmap)
        item.setZValue(-999999.0)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setToolTip(
            "Chrono source + UGCVLUT1 Q8 desktop raster\n"
            "Exact PTS/pixels before Qt scaling; compositor timing unverified"
        )
        item.setData(2, "chrono_desktop_raster")
        if owner_node_id is not None:
            item.setData(0, owner_node_id)
        self.scene().addItem(item)
        self._chrono_pixmap_item = item
        self._chrono_frame_receipt = {
            "ordinal": int(frame.ordinal),
            "source_pts": int(frame.source_pts),
            "rgb_sha256": str(frame.rgb_sha256),
            "backend": str(frame.backend),
            "logical_pts_exact": bool(frame.logical_pts_exact),
            "physical_display_timing_verified": bool(
                frame.physical_display_timing_verified
            ),
            "late_boundary": bool(frame.late_boundary),
            "owner_node_id": owner_node_id,
        }
        self.viewport().update()

    def set_document(self, document: EditorDocument | None) -> None:
        self._device_look_toggle.blockSignals(True)
        self._device_look_toggle.setChecked(False)
        self._device_look_toggle.blockSignals(False)
        self._set_raster_viewport()
        self._device_look_support = None
        self._device_look_failure_reason = ""
        self._document = document
        self._runtime_state = None
        self._selected_id = None
        self._first_render = True
        self.refresh()

    def set_playing(self, playing: bool) -> None:
        if playing:
            self._cancel_translation_drag()
        self._playing = playing
        self.pressed_keys.clear()
        for item in self.scene().items():
            if isinstance(item, EntityGraphicsItem):
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not playing)
        if playing:
            self._remove_3d_gizmo()
        else:
            self._rebuild_3d_gizmo_for_selection()

    def set_runtime_state(self, state: Mapping[str, Mapping[str, Any]] | None) -> None:
        self._runtime_state = state
        if (
            state is not None
            and self._document is not None
            and isinstance(self._document.project, Mobile3DProject)
        ):
            self._update_3d_runtime(self._preview_3d_project(), state)
            self.viewport().update()
        else:
            self.refresh(keep_view=True)

    def set_selected_id(self, object_id: str | None) -> None:
        if object_id == self._selected_id:
            if not self._playing and not self._gizmo_handles:
                self._rebuild_3d_gizmo_for_selection()
            return
        self._cancel_translation_drag()
        self._remove_3d_gizmo()
        self._selected_id = object_id
        # Selection must not rebuild/clear the scene from inside an item's mouse
        # handler: Qt would delete the very C++ object still processing the click.
        self._rendering = True
        try:
            for item in self.scene().items():
                item_id = item.data(0)
                if not isinstance(item_id, str):
                    continue
                selected = item_id == object_id
                if item.isSelected() != selected:
                    item.setSelected(selected)
                if isinstance(item, ProjectedMeshItem):
                    item.selected = selected
                if isinstance(item, EntityGraphicsItem):
                    for child in tuple(item.childItems()):
                        if child.data(2) == "selection_guide":
                            self.scene().removeItem(child)
                    if selected and self._document is not None:
                        scene_record = self._document.scene()
                        entity = None if scene_record is None else next(
                            (value for value in scene_record.entities if value.id == item.object_id),
                            None,
                        )
                        if entity is not None:
                            self._add_2d_selection_guides(item, entity)
                item.update()
        finally:
            self._rendering = False
        self._rebuild_3d_gizmo_for_selection()

    def refresh(self, keep_view: bool = True) -> None:
        self._resolve_device_look_config()
        self._sync_device_look_backend()
        transform = QTransform(self.transform())
        center = self.mapToScene(self.viewport().rect().center())
        self._rendering = True
        try:
            self._translation_drag = None
            self._gizmo_handles.clear()
            self.scene().clear()
            self._mesh_items.clear()
            self._mesh_runtime_transforms.clear()
            self._chrono_pixmap_item = None
            self._chrono_frame_receipt = None
            self._polar_population_previews.clear()
            self._saved_scene_owner_by_node.clear()
            if self._document is None or self._document.project is None:
                self._render_empty()
            elif isinstance(self._document.project, GameProject):
                self._render_2d(self._document.project)
            else:
                try:
                    self._saved_scene_owner_by_node = (
                        self._document.saved_scene_materialized_owner_map()
                    )
                except (TypeError, ValueError):
                    self._saved_scene_owner_by_node = {}
                self._render_3d(self._preview_3d_project())
        finally:
            self._rendering = False
        if self._first_render or not keep_view:
            self.fit_scene()
            self._first_render = False
        elif not transform.isIdentity():
            self.setTransform(transform)
            self.centerOn(center)

    def _preview_3d_project(self) -> Mobile3DProject:
        """Return a detached flat view including every compact linked group."""

        document = self._document
        if document is None or not isinstance(document.project, Mobile3DProject):
            raise RuntimeError("A mobile 3D project is not open.")
        try:
            preview = materialize_saved_scenes(document.project)
        except (TypeError, ValueError):
            # Project Check explains malformed Saved Scene metadata. Keeping the
            # authored nodes visible lets a child still open and repair a file.
            preview = copy.deepcopy(document.project)
        try:
            worlds = world_trs_by_id(preview.nodes)
        except (Hierarchy3DError, TypeError, ValueError):
            # Project Check owns malformed hierarchy diagnostics too. Roots and
            # local child poses remain visible enough to select and repair.
            return preview
        preview = copy.deepcopy(preview)
        preview.nodes = tuple(
            replace(
                node,
                transform=replace(
                    node.transform,
                    translation=worlds[node.id].translation,
                    rotation=worlds[node.id].rotation,
                    scale=worlds[node.id].scale,
                ),
                parent_id=None,
            )
            for node in preview.nodes
        )
        return preview

    def _set_device_look_text(self, suffix: str = "") -> None:
        text = "Device Look (reference)"
        if suffix:
            text += f" · {suffix}"
        self._device_look_toggle.setText(text)
        self._device_look_toggle.adjustSize()
        self._position_device_look_toggle()

    def _position_device_look_toggle(self) -> None:
        if not hasattr(self, "_device_look_toggle"):
            return
        margin = self.frameWidth() + 10
        viewport_geometry = self.viewport().geometry()
        x = max(
            margin,
            viewport_geometry.right() - self._device_look_toggle.width() - 10,
        )
        self._device_look_toggle.move(x, viewport_geometry.top() + 10)
        self._device_look_toggle.raise_()

    def _resolve_device_look_config(self) -> None:
        document = self._document
        project = None if document is None else document.project
        is_mobile = isinstance(project, Mobile3DProject)
        self._device_look_toggle.setVisible(is_mobile)
        self._device_look_config = None
        self._device_look_config_error = ""
        if not is_mobile:
            return
        try:
            self._device_look_config = render_substrate_config_from_project(project)
        except RenderPackError as exc:
            # Project Check owns the detailed repair guidance. The viewport
            # stays selectable and explicitly reports its raster fallback.
            self._device_look_config_error = str(exc)

    def _device_look_toggled(self, enabled: bool) -> None:
        if not enabled:
            self._device_look_failure_reason = ""
            self._device_look_support = None
        self._sync_device_look_backend()
        self.viewport().update()

    def _sync_device_look_backend(self) -> None:
        project = None if self._document is None else self._document.project
        if not isinstance(project, Mobile3DProject):
            self._set_raster_viewport()
            self._set_device_look_text()
            return
        if not self._device_look_toggle.isChecked():
            self._set_raster_viewport()
            self._set_device_look_text()
            return
        if self._device_look_config_error:
            self._set_raster_viewport()
            self._set_device_look_text("Invalid settings · raster fallback")
            return
        config = self._device_look_config
        if config is None or not config.bayer_enabled:
            # Do not introduce a GL copy/sample roundtrip when the native
            # recipe does not enable Bayer. Raster pixels remain untouched.
            self._set_raster_viewport()
            disabled_reason = (
                "Bayer Off"
                if config is None or config.bayer_mode == "off"
                else "Bayer strength 0"
            )
            self._set_device_look_text(f"{disabled_reason} · unchanged")
            return
        if self._device_look_failure_reason:
            self._set_raster_viewport()
            self._set_device_look_text("Raster fallback · GL pass unavailable")
            return
        if isinstance(self.viewport(), DeviceLookOpenGLViewport):
            self._set_device_look_text(
                f"CPU LUT + {_friendly_name(config.bayer_mode)} Bayer"
            )
            return
        if self._device_look_support is None:
            self._device_look_support = probe_device_look_gl()
        if not self._device_look_support.available:
            self._set_raster_viewport()
            self._set_device_look_text("Raster fallback · OpenGL unavailable")
            return

        viewport = DeviceLookOpenGLViewport()
        viewport.setMouseTracking(True)
        viewport.postFailed.connect(self._device_look_post_failed)
        self.setViewport(viewport)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )
        self._set_device_look_text(
            f"CPU LUT + {_friendly_name(config.bayer_mode)} Bayer"
        )

    def _set_raster_viewport(self) -> None:
        current = self.viewport()
        if isinstance(current, DeviceLookOpenGLViewport):
            current.shutdown()
            raster = QWidget()
            raster.setObjectName("SceneViewportRaster")
            raster.setMouseTracking(True)
            self.setViewport(raster)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        self._position_device_look_toggle()

    def _device_look_post_failed(self, reason: str) -> None:
        if self._device_look_fallback_pending:
            return
        self._device_look_failure_reason = reason or "unknown OpenGL failure"
        self._device_look_fallback_pending = True
        # Replacing a viewport while QGraphicsView is drawing would invalidate
        # the active painter. Defer the safe fallback until the event returns.
        QTimer.singleShot(0, self._finish_device_look_fallback)

    def _finish_device_look_fallback(self) -> None:
        self._device_look_fallback_pending = False
        self._set_raster_viewport()
        self._sync_device_look_backend()
        self.viewport().update()

    def fit_scene(self) -> None:
        rect = self.scene().sceneRect()
        if rect.isValid() and not rect.isEmpty():
            self.fitInView(rect.adjusted(-16, -16, 16, 16), Qt.AspectRatioMode.KeepAspectRatio)

    def focus_selection(self) -> None:
        selected = [item for item in self.scene().items() if item.data(0) == self._selected_id]
        if selected:
            rect = selected[0].sceneBoundingRect().adjusted(-80, -80, 80, 80)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self.fit_scene()

    def _render_empty(self) -> None:
        self.scene().setSceneRect(0, 0, 960, 540)
        background = QGraphicsRectItem(self.scene().sceneRect())
        gradient = QLinearGradient(0, 0, 0, 540)
        gradient.setColorAt(0, QColor("#111827"))
        gradient.setColorAt(1, QColor("#080d18"))
        background.setBrush(QBrush(gradient))
        background.setPen(Qt.PenStyle.NoPen)
        self.scene().addItem(background)
        text = QGraphicsSimpleTextItem("Open a project to see your game world")
        text.setBrush(QColor("#9aa9bd"))
        text.setPos(480 - text.boundingRect().width() / 2, 260)
        self.scene().addItem(text)

    def _render_2d(self, project: GameProject) -> None:
        scene_record = self._document.scene() if self._document else None
        if scene_record is None:
            self._render_empty()
            return
        width, height = scene_record.world_size
        self.scene().setSceneRect(0, 0, width, height)
        backdrop = QGraphicsRectItem(0, 0, width, height)
        backdrop.setBrush(_color(scene_record.background or project.display.background or "#101427"))
        backdrop.setPen(QPen(QColor("#26364f"), 2))
        backdrop.setZValue(-100000)
        self.scene().addItem(backdrop)
        self._add_2d_grid(width, height)

        ordered = sorted(
            scene_record.entities,
            key=lambda entity: int(entity.components.get("vector_renderer", {}).get("z_index", 0)),
        )
        for entity in ordered:
            transform = self._runtime_state.get(entity.id) if self._runtime_state else None
            transform = transform or entity.components.get("transform")
            renderer = entity.components.get("vector_renderer")
            if not isinstance(transform, Mapping):
                continue
            if not isinstance(renderer, Mapping):
                self._add_missing_asset(entity, transform, "has no vector art yet")
                continue
            if renderer.get("visible", True) is False:
                continue
            asset = project.vector_assets.assets.get(str(renderer.get("asset_id", "")))
            if asset is None:
                self._add_missing_asset(entity, transform, "uses a missing vector asset")
                continue
            item = self._vector_item(entity, asset, renderer)
            position = transform.get("position", (0, 0))
            scale = transform.get("scale", (1, 1))
            item.setPos(float(position[0]), float(position[1]))
            item.setRotation(math.degrees(float(transform.get("rotation", 0))))
            item.setTransform(QTransform.fromScale(float(scale[0]), float(scale[1])))
            item.setZValue(float(renderer.get("z_index", 0)))
            item.setOpacity(float(renderer.get("opacity", 1.0)))
            item.setToolTip(f"{_friendly_name(entity.id)}\nClick to select · drag to move")
            item.setSelected(entity.id == self._selected_id)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not self._playing)
            self.scene().addItem(item)
            if entity.id == self._selected_id:
                self._add_2d_selection_guides(item, entity)

        label = QGraphicsSimpleTextItem(
            f"2D Scene  •  {_friendly_name(scene_record.id)}  •  {len(scene_record.entities)} objects"
        )
        label.setBrush(QColor("#a9bbd2"))
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(18, 16)
        label.setZValue(100000)
        self.scene().addItem(label)

        world_state = dict(scene_record.initial_state)
        if self._runtime_state and isinstance(self._runtime_state.get("__world__"), Mapping):
            world_state.update(self._runtime_state["__world__"])
        score = world_state.get("score", 0)
        target = scene_record.rules.get("score_to_win")
        score_text = f"Score  {score}" if not target else f"Crystals  {score} / {target}"
        hud = QGraphicsSimpleTextItem(score_text)
        hud.setBrush(QColor("#f5fbff"))
        hud_font = hud.font()
        hud_font.setPointSizeF(15)
        hud_font.setBold(True)
        hud.setFont(hud_font)
        hud.setPos(20, 44)
        hud.setZValue(100001)
        self.scene().addItem(hud)
        replacements = {
            "{score}": str(score),
            "{target}": str(target or 0),
            "{health}": str(world_state.get("health", "-")),
            "{best}": str(world_state.get("best_score", 0)),
        }
        for record in scene_record.ui:
            if record.get("type") != "text":
                continue
            text = str(record.get("text", ""))
            for source, value in replacements.items():
                text = text.replace(source, value)
            item = QGraphicsSimpleTextItem(text)
            color = _color(record.get("color"), "#dce8f5")
            item.setBrush(color if color.isValid() else QColor("#dce8f5"))
            position = record.get("position", (0, 0))
            item.setPos(float(position[0]), float(position[1]))
            if record.get("align") == "center":
                item.setX(item.x() - item.boundingRect().width() * 0.5)
            elif record.get("align") == "right":
                item.setX(item.x() - item.boundingRect().width())
            item.setOpacity(float(record.get("opacity", 1.0)))
            item.setZValue(100001)
            self.scene().addItem(item)

    def _add_2d_grid(self, width: float, height: float) -> None:
        target_lines = 30
        raw = max(width, height) / target_lines
        magnitude = 10 ** math.floor(math.log10(max(raw, 1)))
        spacing = min((1, 2, 5, 10), key=lambda value: abs(raw - value * magnitude)) * magnitude
        minor = QPen(QColor(52, 74, 105, 72), max(0.0, spacing * 0.003))
        major = QPen(QColor(76, 107, 147, 105), max(0.0, spacing * 0.005))
        x = 0.0
        index = 0
        while x <= width + 0.001:
            line = self.scene().addLine(x, 0, x, height, major if index % 5 == 0 else minor)
            line.setZValue(-99999)
            x += spacing
            index += 1
        y = 0.0
        index = 0
        while y <= height + 0.001:
            line = self.scene().addLine(0, y, width, y, major if index % 5 == 0 else minor)
            line.setZValue(-99999)
            y += spacing
            index += 1

    def _vector_item(
        self, entity: EntitySpec, asset: VectorAsset2D, renderer: Mapping[str, Any]
    ) -> EntityGraphicsItem:
        group = EntityGraphicsItem(entity.id, self.selectionRequested.emit, self.entityMoved.emit)
        group.setTransformOriginPoint(0, 0)
        for vector_path in asset.paths:
            child = QGraphicsPathItem(_path(vector_path))
            child.setPos(-asset.pivot[0], -asset.pivot[1])
            child.setBrush(_gradient_brush(asset, vector_path.paint.fill))
            stroke = vector_path.paint.stroke
            if stroke:
                pen = QPen(_color(stroke), vector_path.paint.stroke_width)
                pen.setCapStyle(
                    {
                        "butt": Qt.PenCapStyle.FlatCap,
                        "round": Qt.PenCapStyle.RoundCap,
                        "square": Qt.PenCapStyle.SquareCap,
                    }.get(vector_path.paint.line_cap, Qt.PenCapStyle.RoundCap)
                )
                pen.setJoinStyle(
                    {
                        "miter": Qt.PenJoinStyle.MiterJoin,
                        "round": Qt.PenJoinStyle.RoundJoin,
                        "bevel": Qt.PenJoinStyle.BevelJoin,
                    }.get(vector_path.paint.line_join, Qt.PenJoinStyle.RoundJoin)
                )
                child.setPen(pen)
            else:
                child.setPen(Qt.PenStyle.NoPen)
            child.setOpacity(vector_path.paint.opacity)
            child.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            group.addToGroup(child)
        shadow_blur = float(renderer.get("shadow_blur", 0))
        if shadow_blur > 0:
            effect = QGraphicsDropShadowEffect()
            effect.setBlurRadius(min(shadow_blur, 36))
            effect.setOffset(0, max(2.0, shadow_blur * 0.12))
            effect.setColor(_color(renderer.get("shadow_color"), "#55000000"))
            group.setGraphicsEffect(effect)
        return group

    def _add_missing_asset(
        self, entity: EntitySpec, transform: Mapping[str, Any], reason: str
    ) -> None:
        position = transform.get("position", (0, 0))
        scale = transform.get("scale", (1, 1))
        item = EntityGraphicsItem(
            entity.id, self.selectionRequested.emit, self.entityMoved.emit
        )
        marker = QGraphicsRectItem(-20, -20, 40, 40)
        marker.setBrush(QColor(248, 113, 113, 55))
        marker.setPen(QPen(QColor("#f87171"), 3, Qt.PenStyle.DashLine))
        marker.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.addToGroup(marker)
        plus = QGraphicsSimpleTextItem("+", item)
        plus.setBrush(QColor("#fca5a5"))
        plus.setPos(-plus.boundingRect().width() * 0.5, -plus.boundingRect().height() * 0.55)
        plus.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setPos(float(position[0]), float(position[1]))
        item.setRotation(math.degrees(float(transform.get("rotation", 0.0))))
        item.setTransform(QTransform.fromScale(float(scale[0]), float(scale[1])))
        item.setSelected(entity.id == self._selected_id)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not self._playing)
        item.setToolTip(f"{_friendly_name(entity.id)} {reason}\nClick to select · drag to move")
        self.scene().addItem(item)
        if entity.id == self._selected_id:
            self._add_2d_selection_guides(item, entity)

    def _add_2d_selection_guides(self, item: EntityGraphicsItem, entity: EntitySpec) -> None:
        outline = QGraphicsRectItem(item.boundingRect().adjusted(-6, -6, 6, 6), item)
        outline.setBrush(Qt.BrushStyle.NoBrush)
        outline.setPen(QPen(QColor("#57d4ff"), 2, Qt.PenStyle.DashLine))
        outline.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        outline.setZValue(1000)
        outline.setData(2, "selection_guide")
        label = QGraphicsSimpleTextItem(_friendly_name(entity.id), item)
        label.setBrush(QColor("#e6f7ff"))
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(item.boundingRect().left(), item.boundingRect().top() - 27)
        label.setZValue(1001)
        label.setData(2, "selection_guide")

    def _render_3d(self, project: Mobile3DProject) -> None:
        width, height = 1280.0, 720.0
        self.scene().setSceneRect(0, 0, width, height)
        background = QGraphicsRectItem(0, 0, width, height)
        gradient = QLinearGradient(0, 0, 0, height)
        base = QColor.fromRgbF(*project.background)
        top = base.lighter(145)
        bottom = base.darker(135)
        gradient.setColorAt(0, top)
        gradient.setColorAt(0.58, base)
        gradient.setColorAt(1, bottom)
        background.setBrush(QBrush(gradient))
        background.setPen(Qt.PenStyle.NoPen)
        background.setZValue(-1000000)
        self.scene().addItem(background)

        projector = _PerspectiveProjector(project, width, height)
        self._add_3d_grid(projector, project)
        prototype_glow = self._polar_prototype_glow(project, self._runtime_state)
        for node in project.nodes:
            runtime = self._runtime_state.get(node.id) if self._runtime_state else None
            node_glow = prototype_glow.get(node.id, 0.0)
            faces = self._project_node_faces(
                project,
                node,
                projector,
                runtime,
                polar_glow=node_glow,
            )
            if not faces:
                continue
            selection_id = self._saved_scene_owner_by_node.get(node.id, node.id)
            item = ProjectedMeshItem(
                selection_id, faces, selection_id == self._selected_id
            )
            item.setData(4, node.id)
            item.setData(6, node_glow)
            # Grow is display-copy-only. The real prototype receives Glow
            # lighting, while its authored/gameplay scale remains exactly 1x.
            item.setData(7, 1.0)
            if selection_id != node.id:
                item.setToolTip(
                    f"{_friendly_name(node.id)} inside linked {_friendly_name(selection_id)}\n"
                    "Click to select and move the whole Saved Scene group"
                )
            average_depth = sum(face[0] for face in faces) / len(faces)
            item.setZValue(-average_depth)
            self.scene().addItem(item)
            self._mesh_items[node.id] = item
            transform = runtime or {
                "translation": node.transform.translation,
                "rotation": node.transform.rotation,
                "scale": node.transform.scale,
            }
            self._mesh_runtime_transforms[node.id] = (
                tuple(transform.get("translation", node.transform.translation)),
                tuple(transform.get("rotation", node.transform.rotation)),
                tuple(transform.get("scale", node.transform.scale)),
            )
        generated_total = 0
        generated_shown = 0
        preview_remaining = 256
        try:
            population_spec = collect_scatter_project_spec(project)
            generated_total = population_spec.generated_copies
            for group in population_spec.groups:
                prototype = project.nodes[group.prototype_node_index]
                copies = scatter_instances(prototype, group)
                group_limit = min(64, preview_remaining)
                for instance in copies[:group_limit]:
                    runtime = {
                        "translation": instance.translation,
                        "rotation": instance.rotation,
                        "scale": instance.scale,
                    }
                    faces = self._project_node_faces(
                        project, prototype, projector, runtime
                    )
                    if not faces:
                        continue
                    item = ProjectedMeshItem(
                        self._saved_scene_owner_by_node.get(
                            prototype.id, prototype.id
                        ),
                        faces,
                        self._saved_scene_owner_by_node.get(
                            prototype.id, prototype.id
                        )
                        == self._selected_id,
                    )
                    item.setData(3, "population_copy")
                    item.setToolTip(
                        f"{_friendly_name(prototype.id)} · generated copy "
                        f"{instance.index + 1} of {group.population.instance_count}\n"
                        "Click to edit the one compact Populate Area recipe"
                    )
                    item.setZValue(-sum(face[0] for face in faces) / len(faces))
                    self.scene().addItem(item)
                    generated_shown += 1
                preview_remaining -= min(len(copies), group_limit)
                if preview_remaining <= 0:
                    break
        except ScatterError:
            # The Inspector and Project Check surface the friendly validation
            # message; the viewport stays usable while the recipe is repaired.
            generated_total = 0
            generated_shown = 0
        try:
            polar_population_spec = collect_polar_population_project_spec(project)
            generated_total += polar_population_spec.generated_copies
            # Unlike the older scatter preview budget, KCPR copies require
            # random-access recipe derivation. Keep one global 64-copy polar
            # budget across every recipe, not 64 copies per recipe.
            polar_preview_remaining = min(64, preview_remaining)
            for group in polar_population_spec.groups:
                if polar_preview_remaining <= 0:
                    break
                prototype = project.nodes[group.prototype_node_index]
                group_limit = min(
                    polar_preview_remaining, group.recipe.instance_count - 1
                )
                lut = quantized_profile_lut(group.profile)
                for index in range(1, group_limit + 1):
                    instance = polar_population_instance(
                        prototype, group, index, lut=lut
                    )
                    glow_sample = instance.glow_sample
                    if glow_sample is None:
                        glow_sample = polar_population_glow_sample(
                            group,
                            index=instance.index,
                            pose_word=instance.pose_word,
                            lut=lut,
                        )
                    runtime = {
                        "translation": instance.translation,
                        "rotation": instance.rotation,
                        "scale": instance.scale,
                    }
                    faces = self._project_node_faces(
                        project,
                        prototype,
                        projector,
                        runtime,
                        polar_glow=(
                            0.0 if glow_sample is None else glow_sample.glow
                        ),
                    )
                    if not faces:
                        continue
                    selection_id = self._saved_scene_owner_by_node.get(
                        prototype.id, prototype.id
                    )
                    item = ProjectedMeshItem(
                        selection_id,
                        faces,
                        selection_id == self._selected_id,
                    )
                    item.setData(3, "polar_population_copy")
                    item.setData(5, instance.display_id)
                    item.setData(
                        6, 0.0 if glow_sample is None else glow_sample.glow
                    )
                    item.setData(
                        7,
                        1.0
                        if glow_sample is None
                        else glow_sample.display_scale_multiplier,
                    )
                    item.setToolTip(
                        f"{_friendly_name(prototype.id)} · polar display copy "
                        f"{instance.index + 1} of {group.recipe.instance_count}\n"
                        f"{POLAR_POPULATION_PRESET_LABELS[group.recipe.preset]} preset · "
                        "one real ECS prototype"
                        + (
                            "\nGlow by distance · exact compact preview"
                            if glow_sample is not None
                            else ""
                        )
                        + (
                            "\nGrow glowing copies · display only; real object unchanged"
                            if glow_sample is not None
                            and glow_sample.display_scale_multiplier != 1.0
                            else ""
                        )
                    )
                    item.setZValue(-sum(face[0] for face in faces) / len(faces))
                    self.scene().addItem(item)
                    item.setSelected(selection_id == self._selected_id)
                    self._polar_population_previews.append(
                        _PolarPopulationPreview(prototype, group, lut, index, item)
                    )
                    generated_shown += 1
                polar_preview_remaining -= group_limit
                preview_remaining -= group_limit
        except PolarPopulationError:
            # Project Check owns the learner-facing error while the rest of
            # the scene stays editable.
            pass
        if (
            self._selected_id
            and not self._playing
            and self._selected_id
            not in set(self._saved_scene_owner_by_node.values())
        ):
            self._add_3d_gizmo(projector, project, self._selected_id)

        if generated_total:
            population_text = (
                f"{generated_total} generated"
                if generated_shown == generated_total
                else f"{generated_total} generated · {generated_shown} shown"
            )
            object_text = f"{len(project.nodes)} visible · {population_text}"
        else:
            linked_count = len(set(self._saved_scene_owner_by_node.values()))
            object_text = f"{len(project.nodes)} objects"
            if linked_count:
                object_text += f" · {linked_count} linked group(s)"
        title = QGraphicsSimpleTextItem(
            f"3D Scene  •  {project.title}  •  {object_text}"
        )
        title.setBrush(QColor("#d4e7f7"))
        title.setPos(22, 18)
        title.setZValue(1000000)
        self.scene().addItem(title)
        hint = QGraphicsSimpleTextItem("WASD + Space while playing  •  Mouse wheel zooms")
        hint.setBrush(QColor(157, 177, 201, 190))
        hint.setPos(22, height - 38)
        hint.setZValue(1000000)
        self.scene().addItem(hint)

    def _project_node_faces(
        self,
        project: Mobile3DProject,
        node: Node3DRecord,
        projector: _PerspectiveProjector,
        runtime: Mapping[str, Any] | None,
        *,
        polar_glow: float = 0.0,
    ) -> list[tuple[float, QPolygonF, QColor]]:
        translation = node.transform.translation if runtime is None else runtime.get("translation", node.transform.translation)
        rotation = node.transform.rotation if runtime is None else runtime.get("rotation", node.transform.rotation)
        scale = node.transform.scale if runtime is None else runtime.get("scale", node.transform.scale)
        matrix = compose_trs(translation, rotation, scale)
        mesh = project.meshes.get(node.mesh_id)
        material = project.materials.get(node.material_id)
        if mesh is None or material is None:
            return []
        pbr_material = material.to_pbr()
        world_vertices = [transform_point(matrix, vertex) for vertex in mesh.vertices]
        faces: list[tuple[float, QPolygonF, QColor]] = []
        for ia, ib, ic in mesh.triangles:
            points3d = (world_vertices[ia], world_vertices[ib], world_vertices[ic])
            normal = _normalized(_cross(_sub(points3d[1], points3d[0]), _sub(points3d[2], points3d[0])))
            center = tuple(sum(point[axis] for point in points3d) / 3.0 for axis in range(3))
            if not material.double_sided and _dot(normal, _sub(project.camera.position, center)) <= 0:
                continue
            projected = [projector.project(point) for point in points3d]
            if any(point is None for point in projected):
                continue
            screen_points = [point[0] for point in projected if point is not None]
            depth = sum(point[1] for point in projected if point is not None) / 3.0
            shaded = shade_pbr_lite(
                pbr_material,
                normal,
                project.light.direction,
                _sub(project.camera.position, center),
                project.light.color,
                project.light.intensity,
                project.light.ambient,
            )
            # Match the native material boundary exactly: the deterministic
            # scalar adds base colour after ordinary light + authored emissive;
            # final post/Bayer remains downstream and alpha stays untouched.
            displayed = tuple(
                value + material.base_color[index] * polar_glow
                for index, value in enumerate(shaded)
            )
            color = QColor.fromRgbF(
                *(min(1.0, max(0.0, value)) for value in displayed),
                min(1.0, max(0.0, material.base_color[3])),
            )
            faces.append((depth, QPolygonF(screen_points), color))
        return faces

    def _polar_prototype_glow(
        self,
        project: Mobile3DProject,
        state: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, float]:
        """Evaluate index zero for lighting only; never grow the real object."""

        result: dict[str, float] = {}
        try:
            specification = collect_polar_population_project_spec(project)
        except (PolarPopulationError, TypeError, ValueError):
            return result
        for group in specification.groups:
            if group.glow_parameters is None:
                continue
            component = group.component
            if state is not None:
                runtime = state.get(group.prototype_id)
                packed_state = (
                    None if runtime is None else runtime.get("packed_kinematic")
                )
                if not isinstance(packed_state, Mapping):
                    continue
                try:
                    component = PackedKinematicComponent(
                        packed_state.get("pose_word"),  # type: ignore[arg-type]
                        packed_state.get("motion_word"),  # type: ignore[arg-type]
                        str(packed_state.get("profile_id", "")),
                    )
                    component.validate()
                except (TypeError, ValueError):
                    continue
            try:
                lut = quantized_profile_lut(group.profile)
                sample = polar_population_glow_sample(
                    group,
                    index=0,
                    pose_word=component.pose_word,
                    lut=lut,
                )
            except (
                IndexError,
                OverflowError,
                PolarPopulationError,
                TypeError,
                ValueError,
            ):
                continue
            if sample is not None:
                result[group.prototype_id] = sample.glow
        return result

    def _update_3d_runtime(
        self, project: Mobile3DProject, state: Mapping[str, Mapping[str, Any]]
    ) -> None:
        projector = _PerspectiveProjector(project, 1280.0, 720.0)
        prototype_glow = self._polar_prototype_glow(project, state)
        for node in project.nodes:
            runtime = state.get(node.id)
            if (
                runtime is None
                or not bool(runtime.get("active", True))
            ):
                previous = self._mesh_items.pop(node.id, None)
                self._mesh_runtime_transforms.pop(node.id, None)
                if previous is not None and previous.scene() is self.scene():
                    self.scene().removeItem(previous)
                continue
            try:
                signature = (
                    tuple(runtime.get("translation", node.transform.translation)),
                    tuple(runtime.get("rotation", node.transform.rotation)),
                    tuple(runtime.get("scale", node.transform.scale)),
                )
            except TypeError:
                previous = self._mesh_items.pop(node.id, None)
                self._mesh_runtime_transforms.pop(node.id, None)
                if previous is not None and previous.scene() is self.scene():
                    self.scene().removeItem(previous)
                continue
            if self._mesh_runtime_transforms.get(node.id) == signature:
                continue
            previous = self._mesh_items.pop(node.id, None)
            if previous is not None and previous.scene() is self.scene():
                self.scene().removeItem(previous)
            try:
                node_glow = prototype_glow.get(node.id, 0.0)
                faces = self._project_node_faces(
                    project,
                    node,
                    projector,
                    runtime,
                    polar_glow=node_glow,
                )
            except (IndexError, OverflowError, TypeError, ValueError):
                self._mesh_runtime_transforms.pop(node.id, None)
                continue
            if not faces:
                self._mesh_runtime_transforms[node.id] = signature
                continue
            selection_id = self._saved_scene_owner_by_node.get(node.id, node.id)
            item = ProjectedMeshItem(
                selection_id, faces, selection_id == self._selected_id
            )
            item.setData(4, node.id)
            item.setData(6, node_glow)
            item.setData(7, 1.0)
            if selection_id != node.id:
                item.setToolTip(
                    f"{_friendly_name(node.id)} inside linked {_friendly_name(selection_id)}\n"
                    "Click to select the whole Saved Scene group"
                )
            item.setZValue(-sum(face[0] for face in faces) / len(faces))
            self.scene().addItem(item)
            item.setSelected(selection_id == self._selected_id)
            self._mesh_items[node.id] = item
            self._mesh_runtime_transforms[node.id] = signature
        self._update_polar_population_runtime(project, state, projector)

    def _update_polar_population_runtime(
        self,
        project: Mobile3DProject,
        state: Mapping[str, Mapping[str, Any]],
        projector: _PerspectiveProjector,
    ) -> None:
        """Move only retained display copies from their real runtime prototype."""

        for preview in self._polar_population_previews:
            item = preview.item
            runtime = state.get(preview.prototype.id)
            if (
                runtime is None
                or not bool(runtime.get("active", True))
                or not bool(runtime.get("make_many_copies_visible", True))
            ):
                item.setVisible(False)
                continue
            packed_state = runtime.get("packed_kinematic")
            if not isinstance(packed_state, Mapping):
                item.setVisible(False)
                continue
            try:
                component = PackedKinematicComponent(
                    packed_state.get("pose_word"),  # type: ignore[arg-type]
                    packed_state.get("motion_word"),  # type: ignore[arg-type]
                    str(packed_state.get("profile_id", "")),
                )
                component.validate()
                runtime_prototype = replace(
                    preview.prototype,
                    transform=replace(
                        preview.prototype.transform,
                        translation=tuple(
                            runtime.get(
                                "translation", preview.prototype.transform.translation
                            )
                        ),
                        rotation=tuple(
                            runtime.get("rotation", preview.prototype.transform.rotation)
                        ),
                        scale=tuple(
                            runtime.get("scale", preview.prototype.transform.scale)
                        ),
                    ),
                    velocity=tuple(
                        runtime.get("velocity", preview.prototype.velocity)
                    ),
                )
                burst_kwargs: dict[str, Any] = {}
                if preview.group.recipe.preset == "burst":
                    fixed_tick = runtime.get("make_many_fixed_tick")
                    if type(fixed_tick) is not int or fixed_tick < 0:
                        raise ValueError(
                            "Radial Burst runtime state needs a nonnegative fixed tick"
                        )
                    burst_kwargs["fixed_tick"] = fixed_tick
                instance = polar_population_instance(
                    runtime_prototype,
                    preview.group,
                    preview.index,
                    component=component,
                    lut=preview.lut,
                    **burst_kwargs,
                )
                glow_sample = instance.glow_sample
                if glow_sample is None:
                    glow_sample = polar_population_glow_sample(
                        preview.group,
                        index=instance.index,
                        pose_word=instance.pose_word,
                        lut=preview.lut,
                    )
                faces = self._project_node_faces(
                    project,
                    runtime_prototype,
                    projector,
                    {
                        "translation": instance.translation,
                        "rotation": instance.rotation,
                        "scale": instance.scale,
                    },
                    polar_glow=(
                        0.0 if glow_sample is None else glow_sample.glow
                    ),
                )
            except (
                IndexError,
                OverflowError,
                PolarPopulationError,
                TypeError,
                ValueError,
            ):
                item.setVisible(False)
                continue
            if not faces:
                item.setVisible(False)
                continue
            item.set_faces(faces)
            item.setData(6, 0.0 if glow_sample is None else glow_sample.glow)
            item.setData(
                7,
                1.0
                if glow_sample is None
                else glow_sample.display_scale_multiplier,
            )
            item.setZValue(-sum(face[0] for face in faces) / len(faces))
            item.setVisible(True)
            selected = item.object_id == self._selected_id
            item.selected = selected
            item.setSelected(selected)

    def _add_3d_grid(self, projector: _PerspectiveProjector, project: Mobile3DProject) -> None:
        floor = project.world.floor_y
        extent = max(12, min(40, int(max(abs(value) for value in (*project.world.bounds_min, *project.world.bounds_max)))))
        for coordinate in range(-extent, extent + 1):
            major = coordinate == 0 or coordinate % 5 == 0
            color = QColor(72, 124, 157, 105 if major else 48)
            pen = QPen(color, 1.25 if major else 0.7)
            for start, end in (
                ((coordinate, floor, -extent), (coordinate, floor, extent)),
                ((-extent, floor, coordinate), (extent, floor, coordinate)),
            ):
                a, b = projector.project(start), projector.project(end)
                if a is None or b is None:
                    continue
                line = self.scene().addLine(a[0].x(), a[0].y(), b[0].x(), b[0].y(), pen)
                line.setZValue(-10000 + min(a[1], b[1]))

    def _add_3d_gizmo(
        self, projector: _PerspectiveProjector, project: Mobile3DProject, object_id: str
    ) -> None:
        node = next((item for item in project.nodes if item.id == object_id), None)
        if node is None:
            return
        packed_movement = isinstance(node.metadata.get("packed_kinematic"), Mapping)
        directions = {
            "x": "left or right",
            "y": "up or down",
            "z": "forward or backward",
        }
        colors = {"x": QColor("#ff647c"), "y": QColor("#71e59a"), "z": QColor("#62a8ff")}
        for axis in ("x", "y", "z"):
            lock_reason = None
            if packed_movement and axis in {"x", "z"}:
                lock_reason = (
                    f"Movement Pattern controls {_friendly_name(node.id)} on {axis.upper()}. "
                    "Choose Off / Static in the Inspector before dragging this handle."
                )
            handle = TranslationGizmoHandle(
                node.id,
                axis,
                colors[axis],
                (
                    f"Drag {axis.upper()} to move {_friendly_name(node.id)} "
                    f"{directions[axis]}. Release to keep one undoable move."
                ),
                lock_reason,
                self._begin_translation_drag,
                self._preview_translation_drag,
                self._finish_translation_drag,
                self.gizmoHelpRequested.emit,
            )
            self.scene().addItem(handle)
            self._gizmo_handles[axis] = handle
        self._update_gizmo_geometry(projector, node, node.transform.translation)

    def _remove_3d_gizmo(self) -> None:
        for handle in tuple(self._gizmo_handles.values()):
            if handle.scene() is self.scene():
                self.scene().removeItem(handle)
        self._gizmo_handles.clear()

    def _rebuild_3d_gizmo_for_selection(self) -> None:
        self._remove_3d_gizmo()
        document = self._document
        if (
            self._playing
            or self._selected_id is None
            or document is None
            or not isinstance(document.project, Mobile3DProject)
        ):
            return
        preview = self._preview_3d_project()
        projector = _PerspectiveProjector(preview, 1280.0, 720.0)
        self._add_3d_gizmo(projector, preview, self._selected_id)

    @staticmethod
    def _axis_vector(axis: str, length: float = 1.0) -> tuple[float, float, float]:
        if axis == "x":
            return length, 0.0, 0.0
        if axis == "y":
            return 0.0, length, 0.0
        return 0.0, 0.0, length

    def _update_gizmo_geometry(
        self,
        projector: _PerspectiveProjector,
        node: Node3DRecord,
        translation: Sequence[float],
    ) -> None:
        origin3d = tuple(float(value) for value in translation)
        origin = projector.project(origin3d)
        if origin is None:
            for handle in self._gizmo_handles.values():
                handle.setVisible(False)
            return
        fallback_offsets = {
            "x": QPointF(28.0, 0.0),
            "y": QPointF(0.0, -28.0),
            "z": QPointF(20.0, 20.0),
        }
        for axis, handle in self._gizmo_handles.items():
            delta = self._axis_vector(axis, 1.2)
            endpoint3d = tuple(origin3d[index] + delta[index] for index in range(3))
            endpoint = projector.project(endpoint3d)
            projection_reason = None
            offset = fallback_offsets[axis]
            if endpoint is not None:
                candidate = endpoint[0] - origin[0]
                length = math.hypot(candidate.x(), candidate.y())
                if length >= 5.0:
                    offset = candidate
                else:
                    projection_reason = (
                        f"{axis.upper()} points almost toward the camera in this view. "
                        f"Use Position {axis.upper()} in the Inspector."
                    )
            else:
                projection_reason = (
                    f"{axis.upper()} cannot be dragged from this camera view. "
                    f"Use Position {axis.upper()} in the Inspector."
                )
            handle.set_geometry(
                origin[0], offset, projection_lock_reason=projection_reason
            )
            handle.setVisible(not self._playing)

    def _begin_translation_drag(
        self, handle: TranslationGizmoHandle, press_position: QPointF
    ) -> bool:
        document = self._document
        if (
            self._playing
            or document is None
            or not isinstance(document.project, Mobile3DProject)
            or handle.object_id != self._selected_id
            or handle.locked
        ):
            return False
        node = next(
            (item for item in document.project.nodes if item.id == handle.object_id), None
        )
        if node is None:
            return False
        projector = _PerspectiveProjector(document.project, 1280.0, 720.0)
        try:
            world = document.node_world_trs(node.id)
        except ValueError:
            return False
        base = tuple(float(value) for value in world.translation)
        origin = projector.project(base)
        unit_delta = self._axis_vector(handle.axis)
        unit_endpoint = projector.project(
            tuple(base[index] + unit_delta[index] for index in range(3))
        )
        if origin is None or unit_endpoint is None:
            return False
        projected = unit_endpoint[0] - origin[0]
        projected_length = math.hypot(projected.x(), projected.y())
        if projected_length <= 1.0e-6:
            return False
        self._translation_drag = _TranslationDrag(
            handle.object_id,
            handle.axis,
            {"x": 0, "y": 1, "z": 2}[handle.axis],
            QPointF(press_position),
            QPointF(projected.x() / projected_length, projected.y() / projected_length),
            projected_length,
            base,
            base,
        )
        return True

    def _preview_translation_drag(
        self, handle: TranslationGizmoHandle, position: QPointF
    ) -> None:
        drag = self._translation_drag
        if (
            self._playing
            or drag is None
            or drag.object_id != handle.object_id
            or drag.axis != handle.axis
        ):
            return
        pointer_delta = position - drag.press_position
        projected_delta = (
            pointer_delta.x() * drag.screen_direction.x()
            + pointer_delta.y() * drag.screen_direction.y()
        )
        world_delta = projected_delta / drag.projected_pixels_per_unit
        values = list(drag.base_translation)
        values[drag.axis_index] = max(
            -1_000_000.0,
            min(1_000_000.0, values[drag.axis_index] + world_delta),
        )
        translation = tuple(values)
        if translation == drag.current_translation:
            return
        drag.current_translation = translation
        self._apply_translation_preview(drag.object_id, translation)

    def _apply_translation_preview(
        self, object_id: str, translation: tuple[float, float, float]
    ) -> None:
        document = self._document
        if document is None or not isinstance(document.project, Mobile3DProject):
            return
        project = document.project
        nodes_by_id = {node.id: node for node in project.nodes}
        node = nodes_by_id.get(object_id)
        if node is None:
            return
        try:
            preview_worlds = document.preview_world_trs_after_translation(
                node.id, translation
            )
        except ValueError:
            return
        projector = _PerspectiveProjector(project, 1280.0, 720.0)
        for affected_id, world in preview_worlds.items():
            affected_node = nodes_by_id[affected_id]
            runtime = {
                "translation": world.translation,
                "rotation": world.rotation,
                "scale": world.scale,
            }
            faces = self._project_node_faces(
                project, affected_node, projector, runtime
            )
            mesh_item = self._mesh_items.get(affected_id)
            if mesh_item is not None:
                mesh_item.set_faces(faces)
                if faces:
                    mesh_item.setZValue(
                        -sum(face[0] for face in faces) / len(faces)
                    )
            self._mesh_runtime_transforms[affected_id] = (
                tuple(world.translation),
                tuple(world.rotation),
                tuple(world.scale),
            )
        selected_world = preview_worlds[object_id]
        self._update_gizmo_geometry(
            projector, node, selected_world.translation
        )
        self.translationPreviewed.emit(object_id, selected_world.translation)

    def _finish_translation_drag(
        self, handle: TranslationGizmoHandle, position: QPointF
    ) -> None:
        drag = self._translation_drag
        if drag is None or drag.object_id != handle.object_id or drag.axis != handle.axis:
            return
        self._preview_translation_drag(handle, position)
        drag = self._translation_drag
        self._translation_drag = None
        if drag is None or drag.current_translation == drag.base_translation:
            return
        object_id = drag.object_id
        before = tuple(drag.base_translation)
        after = tuple(drag.current_translation)
        # TransformCommand synchronously refreshes the viewport. Queue the
        # release so this handle is never deleted inside its own mouse event.
        QTimer.singleShot(
            0,
            lambda: self.entityMoved.emit(object_id, before, after),
        )

    def _cancel_translation_drag(self) -> None:
        drag = self._translation_drag
        self._translation_drag = None
        if drag is not None and drag.current_translation != drag.base_translation:
            self._apply_translation_preview(drag.object_id, drag.base_translation)

    def _scene_selection_changed(self) -> None:
        if self._rendering:
            return
        selected = self.scene().selectedItems()
        if not selected:
            return
        object_id = selected[0].data(0)
        if object_id:
            self.selectionRequested.emit(str(object_id))

    def drawForeground(
        self, painter: QPainter, rect: QRectF
    ) -> None:  # noqa: N802 - Qt virtual name
        super().drawForeground(painter, rect)
        viewport = self.viewport()
        config = self._device_look_config
        if (
            isinstance(viewport, DeviceLookOpenGLViewport)
            and config is not None
            and config.bayer_enabled
        ):
            viewport.apply_bayer_reference(painter, config)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_device_look_toggle()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.16 if event.angleDelta().y() > 0 else 1 / 1.16
        current = self.transform().m11()
        if 0.04 <= current * factor <= 24:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_origin = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._panning:
            delta = event.position() - self._pan_origin
            self._pan_origin = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        point = self.mapToScene(event.position().toPoint())
        self.mouseScenePosition.emit(point.x(), point.y())
        super().mouseMoveEvent(event)

    @staticmethod
    def _key_name(key: int) -> str | None:
        return {
            Qt.Key.Key_A: "a", Qt.Key.Key_D: "d", Qt.Key.Key_W: "w", Qt.Key.Key_S: "s",
            Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
            Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
            Qt.Key.Key_Space: "space", Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Shift: "shift", Qt.Key.Key_J: "j",
        }.get(Qt.Key(key))

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        name = self._key_name(event.key())
        if name and not event.isAutoRepeat():
            self.pressed_keys.add(name)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # type: ignore[override]
        name = self._key_name(event.key())
        if name and not event.isAutoRepeat():
            self.pressed_keys.discard(name)
            event.accept()
            return
        super().keyReleaseEvent(event)


__all__ = ["SceneViewport", "TranslationGizmoHandle"]
