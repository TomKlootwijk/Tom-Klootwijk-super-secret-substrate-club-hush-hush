"""QGraphicsView scene authoring previews for UGTS 2D and mobile 3D."""
from __future__ import annotations

import math
import re
from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from ..math3d import compose_trs, transform_point
from ..mobile3d import Mobile3DProject
from ..project import EntitySpec, GameProject
from ..vector2d import LinearGradient, RadialGradient, VectorAsset2D, VectorPath
from .document import EditorDocument, SelectionRef


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
        self._on_selected(self.object_id)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

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


class SceneViewport(QGraphicsView):
    """Editable 2D scene view and projected 3D mesh preview."""

    selectionRequested = Signal(str)
    entityMoved = Signal(str, object, object)
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
        self.pressed_keys: set[str] = set()
        self.scene().selectionChanged.connect(self._scene_selection_changed)

    def set_document(self, document: EditorDocument | None) -> None:
        self._document = document
        self._runtime_state = None
        self._selected_id = None
        self._first_render = True
        self.refresh()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.pressed_keys.clear()
        for item in self.scene().items():
            if isinstance(item, EntityGraphicsItem):
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not playing)

    def set_runtime_state(self, state: Mapping[str, Mapping[str, Any]] | None) -> None:
        self._runtime_state = state
        self.refresh(keep_view=True)

    def set_selected_id(self, object_id: str | None) -> None:
        if object_id == self._selected_id:
            return
        self._selected_id = object_id
        self.refresh(keep_view=True)

    def refresh(self, keep_view: bool = True) -> None:
        transform = QTransform(self.transform())
        center = self.mapToScene(self.viewport().rect().center())
        self._rendering = True
        try:
            self.scene().clear()
            if self._document is None or self._document.project is None:
                self._render_empty()
            elif isinstance(self._document.project, GameProject):
                self._render_2d(self._document.project)
            else:
                self._render_3d(self._document.project)
        finally:
            self._rendering = False
        if self._first_render or not keep_view:
            self.fit_scene()
            self._first_render = False
        elif not transform.isIdentity():
            self.setTransform(transform)
            self.centerOn(center)

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
            if not isinstance(transform, Mapping) or not isinstance(renderer, Mapping):
                continue
            if renderer.get("visible", True) is False:
                continue
            asset = project.vector_assets.assets.get(str(renderer.get("asset_id", "")))
            if asset is None:
                self._add_missing_asset(entity, transform)
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

    def _add_missing_asset(self, entity: EntitySpec, transform: Mapping[str, Any]) -> None:
        position = transform.get("position", (0, 0))
        item = QGraphicsRectItem(-20, -20, 40, 40)
        item.setPos(float(position[0]), float(position[1]))
        item.setBrush(QColor(248, 113, 113, 55))
        item.setPen(QPen(QColor("#f87171"), 3, Qt.PenStyle.DashLine))
        item.setData(0, entity.id)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        item.setToolTip(f"{_friendly_name(entity.id)} uses a missing vector asset")
        self.scene().addItem(item)

    def _add_2d_selection_guides(self, item: EntityGraphicsItem, entity: EntitySpec) -> None:
        outline = QGraphicsRectItem(item.boundingRect().adjusted(-6, -6, 6, 6), item)
        outline.setBrush(Qt.BrushStyle.NoBrush)
        outline.setPen(QPen(QColor("#57d4ff"), 2, Qt.PenStyle.DashLine))
        outline.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        outline.setZValue(1000)
        label = QGraphicsSimpleTextItem(_friendly_name(entity.id), item)
        label.setBrush(QColor("#e6f7ff"))
        label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        label.setPos(item.boundingRect().left(), item.boundingRect().top() - 27)
        label.setZValue(1001)

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
        triangles: list[tuple[float, str, QPolygonF, QColor]] = []
        light_direction = _normalized(tuple(-value for value in project.light.direction))
        for node in project.nodes:
            runtime = self._runtime_state.get(node.id) if self._runtime_state else None
            translation = node.transform.translation if runtime is None else runtime.get("translation", node.transform.translation)
            rotation = node.transform.rotation if runtime is None else runtime.get("rotation", node.transform.rotation)
            scale = node.transform.scale if runtime is None else runtime.get("scale", node.transform.scale)
            matrix = compose_trs(translation, rotation, scale)
            mesh = project.meshes.get(node.mesh_id)
            material = project.materials.get(node.material_id)
            if mesh is None or material is None:
                continue
            world_vertices = [transform_point(matrix, vertex) for vertex in mesh.vertices]
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
                diffuse = max(0.0, _dot(normal, light_direction))
                brightness = min(1.7, project.light.ambient + diffuse * project.light.intensity)
                base_color = material.base_color
                emissive = material.emissive
                color = QColor.fromRgbF(
                    min(1.0, base_color[0] * brightness * project.light.color[0] + emissive[0]),
                    min(1.0, base_color[1] * brightness * project.light.color[1] + emissive[1]),
                    min(1.0, base_color[2] * brightness * project.light.color[2] + emissive[2]),
                    min(1.0, base_color[3]),
                )
                triangles.append((depth, node.id, QPolygonF(screen_points), color))

        for index, (depth, node_id, polygon, color) in enumerate(
            sorted(triangles, key=lambda item: item[0], reverse=True)
        ):
            item = QGraphicsPolygonItem(polygon)
            selected = node_id == self._selected_id
            item.setBrush(color)
            item.setPen(
                QPen(QColor("#65dbff"), 1.6)
                if selected
                else QPen(color.darker(145), 0.7)
            )
            item.setData(0, node_id)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            item.setToolTip(f"{_friendly_name(node_id)}\nClick to inspect its 3D transform")
            item.setZValue(index)
            self.scene().addItem(item)
        if self._selected_id:
            self._add_3d_gizmo(projector, project, self._selected_id)

        title = QGraphicsSimpleTextItem(f"3D Scene  •  {project.title}  •  {len(project.nodes)} objects")
        title.setBrush(QColor("#d4e7f7"))
        title.setPos(22, 18)
        title.setZValue(1000000)
        self.scene().addItem(title)
        hint = QGraphicsSimpleTextItem("WASD + Space while playing  •  Mouse wheel zooms")
        hint.setBrush(QColor(157, 177, 201, 190))
        hint.setPos(22, height - 38)
        hint.setZValue(1000000)
        self.scene().addItem(hint)

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
        runtime = self._runtime_state.get(node.id) if self._runtime_state else None
        origin3d = node.transform.translation if runtime is None else runtime.get("translation", node.transform.translation)
        origin = projector.project(origin3d)
        if origin is None:
            return
        axes = (
            ((1.2, 0, 0), QColor("#ff647c"), "X"),
            ((0, 1.2, 0), QColor("#71e59a"), "Y"),
            ((0, 0, 1.2), QColor("#62a8ff"), "Z"),
        )
        for delta, color, label_text in axes:
            end3d = tuple(origin3d[index] + delta[index] for index in range(3))
            end = projector.project(end3d)
            if end is None:
                continue
            line = self.scene().addLine(
                origin[0].x(), origin[0].y(), end[0].x(), end[0].y(), QPen(color, 3)
            )
            line.setZValue(999999)
            label = QGraphicsSimpleTextItem(label_text)
            label.setBrush(color)
            label.setPos(end[0] + QPointF(3, -8))
            label.setZValue(1000000)
            self.scene().addItem(label)

    def _scene_selection_changed(self) -> None:
        if self._rendering:
            return
        selected = self.scene().selectedItems()
        if not selected:
            return
        object_id = selected[0].data(0)
        if object_id:
            self.selectionRequested.emit(str(object_id))

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.16 if event.angleDelta().y() > 0 else 1 / 1.16
        current = self.transform().m11()
        if 0.04 <= current * factor <= 24:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            synthetic = type(event)(
                event.type(), event.position(), event.scenePosition(), event.globalPosition(),
                Qt.MouseButton.LeftButton, event.buttons() | Qt.MouseButton.LeftButton,
                event.modifiers(), event.source(), event.pointingDevice(),
            )
            super().mousePressEvent(synthetic)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
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


__all__ = ["SceneViewport"]
