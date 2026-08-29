"""Beginner-friendly, serializable visual logic graph widgets."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import uuid
from typing import Any, Mapping

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..visual_graph import BUILTIN_NODE_REGISTRY, PortDirection, PortKind, VisualGraph


@dataclass(frozen=True)
class NodeTemplate:
    key: str
    title: str
    category: str
    description: str
    color: str
    inputs: tuple[str, ...] = ("in",)
    outputs: tuple[str, ...] = ("next",)
    default_properties: Mapping[str, Any] | None = None


_FRIENDLY_NODE_NAMES = {
    "event.ready": ("When Game Starts", "Events"),
    "event.tick": ("Every Frame", "Events"),
    "event.input_pressed": ("When Button Pressed", "Events"),
    "flow.branch": ("If This Is True", "Choices"),
    "value.constant": ("A Value", "Values"),
    "value.state": ("Read Score or Game Value", "Values"),
    "value.component": ("Read Object Setting", "Values"),
    "compare": ("Compare Two Things", "Choices"),
    "action.set_state": ("Change Score or Game Value", "Game Actions"),
    "action.set_component": ("Change Object Setting", "Game Actions"),
    "action.emit_event": ("Send a Game Message", "Game Actions"),
    "action.apply_force": ("Push an Object", "Movement"),
    "action.set_active": ("Show or Hide Object", "Game Actions"),
    "action.despawn": ("Remove Object", "Game Actions"),
}
_CATEGORY_COLORS = {
    "Events": "#5ac8fa", "Choices": "#c792ea", "Values": "#f6c85f",
    "Math": "#f0a45d", "Movement": "#78e6a3", "Game Actions": "#ff8fab",
}


def _node_templates() -> tuple[NodeTemplate, ...]:
    result: list[NodeTemplate] = []
    for definition in BUILTIN_NODE_REGISTRY:
        label, category = _FRIENDLY_NODE_NAMES.get(
            definition.type,
            (definition.label, "Math" if definition.category == "Math" else definition.category),
        )
        inputs = tuple(port.name for port in definition.ports if port.direction is PortDirection.INPUT)
        outputs = tuple(port.name for port in definition.ports if port.direction is PortDirection.OUTPUT)
        result.append(
            NodeTemplate(
                definition.type, label, category, definition.description,
                _CATEGORY_COLORS.get(category, "#91a4b7"), inputs, outputs,
                dict(definition.default_properties),
            )
        )
    return tuple(sorted(result, key=lambda item: (item.category, item.title)))


NODE_TEMPLATES: tuple[NodeTemplate, ...] = _node_templates()
TEMPLATE_BY_KEY = {item.key: item for item in NODE_TEMPLATES}


class GraphPort(QGraphicsObject):
    RADIUS = 6.0

    def __init__(self, node: "GraphNode", name: str, direction: str) -> None:
        super().__init__(node)
        self.node = node
        self.name = name
        self.direction = direction
        definition = BUILTIN_NODE_REGISTRY.get(node.template.key)
        port = None if definition is None else definition.port(direction, name)
        self.port_kind = None if port is None else port.kind
        self.data_type = None if port is None else port.data_type
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        description = f"{name.replace('_', ' ').title()}"
        if self.port_kind is PortKind.DATA:
            description += f" ({self.data_type} value)"
        else:
            description += " (step flow)"
        self.setToolTip(description + " — drag to " + ("an input" if direction == "output" else "an output"))

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        radius = self.RADIUS + 3
        return QRectF(-radius, -radius, radius * 2, radius * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        active = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#dce9f8"), 1.5))
        active_color = QColor("#f7c968") if self.port_kind is PortKind.DATA else QColor("#73d8ff")
        idle_color = QColor("#6e5b35") if self.port_kind is PortKind.DATA else QColor("#344963")
        painter.setBrush(active_color if active else idle_color)
        painter.drawEllipse(QPointF(0, 0), self.RADIUS, self.RADIUS)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        scene = self.scene()
        if isinstance(scene, VisualGraphScene):
            scene.begin_connection(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        scene = self.scene()
        if isinstance(scene, VisualGraphScene):
            scene.update_connection(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        scene = self.scene()
        if isinstance(scene, VisualGraphScene):
            scene.finish_connection(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class GraphNode(QGraphicsObject):
    WIDTH = 210.0

    def __init__(self, node_id: str, template: NodeTemplate, properties: Mapping[str, Any] | None = None) -> None:
        super().__init__()
        self.node_id = node_id
        self.template = template
        self.properties = dict(template.default_properties or {})
        if properties is not None:
            self.properties.update(dict(properties))
        rows = max(len(template.inputs), len(template.outputs), 1)
        self.height = 78.0 + rows * 24.0 + (30.0 if self.properties else 0.0)
        self.input_ports = {
            name: GraphPort(self, name, "input") for name in template.inputs
        }
        self.output_ports = {
            name: GraphPort(self, name, "output") for name in template.outputs
        }
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(template.description)
        self._press_position = QPointF()
        self._position_ports()

    def _position_ports(self) -> None:
        for index, port in enumerate(self.input_ports.values()):
            port.setPos(0, 73 + index * 24)
        for index, port in enumerate(self.output_ports.values()):
            port.setPos(self.WIDTH, 73 + index * 24)

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return QRectF(-9, -6, self.WIDTH + 18, self.height + 12)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QPen(QColor("#68d8ff") if selected else QColor("#2d4057"), 2.2 if selected else 1.2))
        painter.setBrush(QColor("#152234"))
        painter.drawRoundedRect(QRectF(0, 0, self.WIDTH, self.height), 10, 10)

        header = QPainterPath()
        header.addRoundedRect(QRectF(0, 0, self.WIDTH, 43), 10, 10)
        header.addRect(QRectF(0, 32, self.WIDTH, 11))
        painter.fillPath(header, QColor(self.template.color))
        painter.setPen(QColor("#07111d"))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(10.5)
        painter.setFont(font)
        painter.drawText(QRectF(13, 0, self.WIDTH - 26, 43), Qt.AlignmentFlag.AlignVCenter, self.template.title)

        font.setBold(False)
        font.setPointSizeF(8.4)
        painter.setFont(font)
        for index, name in enumerate(self.template.inputs):
            painter.setPen(QColor("#aebfd3"))
            painter.drawText(QRectF(13, 62 + index * 24, 85, 22), Qt.AlignmentFlag.AlignVCenter, name.replace("_", " ").title())
        for index, name in enumerate(self.template.outputs):
            painter.setPen(QColor("#cbe5f5"))
            painter.drawText(
                QRectF(self.WIDTH - 98, 62 + index * 24, 85, 22),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                name.replace("_", " ").title(),
            )
        if self.properties:
            painter.setPen(QPen(QColor("#293d53"), 1))
            painter.drawLine(12, self.height - 29, self.WIDTH - 12, self.height - 29)
            key, value = next(iter(self.properties.items()))
            display = str(value)
            if len(display) > 20:
                display = display[:19] + "…"
            painter.setPen(QColor("#8fa9c1"))
            painter.drawText(
                QRectF(13, self.height - 27, self.WIDTH - 26, 24),
                Qt.AlignmentFlag.AlignVCenter,
                f"{key.replace('_', ' ').title()}: {display}",
            )

    def itemChange(self, change, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            if isinstance(scene, VisualGraphScene):
                scene.update_edges_for(self)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._press_position = QPointF(self.pos())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        scene = self.scene()
        if isinstance(scene, VisualGraphScene) and self.pos() != self._press_position:
            scene.notify_edited()


class GraphConnection(QGraphicsPathItem):
    def __init__(self, source: GraphPort, target: GraphPort) -> None:
        super().__init__()
        self.source = source
        self.target = target
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setPen(QPen(QColor("#69cbed"), 2.4))
        self.setToolTip("A logic connection — select it and press Delete to remove it")
        self.update_path()

    @staticmethod
    def curved_path(start: QPointF, end: QPointF) -> QPainterPath:
        path = QPainterPath(start)
        distance = max(55.0, abs(end.x() - start.x()) * 0.48)
        direction = 1.0 if end.x() >= start.x() else -1.0
        path.cubicTo(
            start + QPointF(distance * direction, 0),
            end - QPointF(distance * direction, 0),
            end,
        )
        return path

    def update_path(self) -> None:
        self.setPath(self.curved_path(self.source.scenePos(), self.target.scenePos()))

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[override]
        self.setPen(
            QPen(QColor("#f8d66d"), 3.2)
            if option.state & QStyle.StateFlag.State_Selected
            else QPen(QColor("#69cbed"), 2.4)
        )
        super().paint(painter, option, widget)


class VisualGraphScene(QGraphicsScene):
    graphEdited = Signal(object)
    connectionRejected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSceneRect(-1600, -1000, 3200, 2000)
        self.nodes: dict[str, GraphNode] = {}
        self.connections: list[GraphConnection] = []
        self._connecting_port: GraphPort | None = None
        self._temporary: QGraphicsPathItem | None = None
        self._loading = False
        self._graph_metadata: dict[str, Any] = {}

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # type: ignore[override]
        painter.fillRect(rect, QColor("#0b1320"))
        minor = QPen(QColor(48, 68, 91, 75), 1)
        major = QPen(QColor(55, 88, 116, 115), 1)
        left = int(math_floor(rect.left(), 24))
        top = int(math_floor(rect.top(), 24))
        for x in range(left, int(rect.right()) + 24, 24):
            painter.setPen(major if x % 120 == 0 else minor)
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for y in range(top, int(rect.bottom()) + 24, 24):
            painter.setPen(major if y % 120 == 0 else minor)
            painter.drawLine(rect.left(), y, rect.right(), y)

    def clear_graph(self) -> None:
        super().clear()
        self.nodes.clear()
        self.connections.clear()
        self._connecting_port = None
        self._temporary = None

    def load_data(self, data: Mapping[str, Any]) -> None:
        self._loading = True
        try:
            self.clear_graph()
            self.setProperty("graph_id", str(data.get("id", "scene_logic")))
            raw_metadata = data.get("metadata", {})
            self._graph_metadata = copy.deepcopy(
                dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
            )
            for raw in data.get("nodes", []):
                if not isinstance(raw, Mapping):
                    continue
                template = TEMPLATE_BY_KEY.get(str(raw.get("type", "")))
                if template is None:
                    template = NodeTemplate(
                        str(raw.get("type", "custom")),
                        str(raw.get("title", "Custom Block")),
                        "Advanced",
                        "A block created by a newer editor.",
                        "#91a4b7",
                    )
                position = raw.get("position", (0, 0))
                self.add_node(
                    template,
                    QPointF(float(position[0]), float(position[1])),
                    node_id=str(raw.get("id") or uuid.uuid4().hex[:10]),
                    properties=raw.get("properties", {}),
                    notify=False,
                )
            for raw in data.get("links", data.get("connections", [])):
                if not isinstance(raw, Mapping):
                    continue
                source_node = self.nodes.get(str(raw.get("source_node", raw.get("from_node", ""))))
                target_node = self.nodes.get(str(raw.get("target_node", raw.get("to_node", ""))))
                if source_node is None or target_node is None:
                    continue
                source = source_node.output_ports.get(str(raw.get("source_port", raw.get("from_port", ""))))
                target = target_node.input_ports.get(str(raw.get("target_port", raw.get("to_port", ""))))
                if source is not None and target is not None:
                    self._add_connection(source, target, notify=False)
        finally:
            self._loading = False

    def add_node(
        self,
        template: NodeTemplate,
        position: QPointF,
        *,
        node_id: str | None = None,
        properties: Mapping[str, Any] | None = None,
        notify: bool = True,
    ) -> GraphNode:
        node_id = node_id or f"{template.key}_{uuid.uuid4().hex[:8]}"
        while node_id in self.nodes:
            node_id = f"{template.key}_{uuid.uuid4().hex[:8]}"
        node = GraphNode(node_id, template, properties)
        node.setPos(position)
        self.addItem(node)
        self.nodes[node_id] = node
        self.clearSelection()
        node.setSelected(True)
        if notify:
            self.notify_edited()
        return node

    def delete_selected(self) -> None:
        selected = list(self.selectedItems())
        if not selected:
            return
        removed = False
        for item in selected:
            if isinstance(item, GraphConnection):
                if item in self.connections:
                    self.connections.remove(item)
                self.removeItem(item)
                removed = True
            elif isinstance(item, GraphNode):
                edges = [edge for edge in self.connections if edge.source.node is item or edge.target.node is item]
                for edge in edges:
                    self.connections.remove(edge)
                    self.removeItem(edge)
                self.nodes.pop(item.node_id, None)
                self.removeItem(item)
                removed = True
        if removed:
            self.notify_edited()

    def begin_connection(self, port: GraphPort) -> None:
        self.cancel_connection()
        self._connecting_port = port
        self._temporary = QGraphicsPathItem()
        self._temporary.setZValue(-0.5)
        self._temporary.setPen(QPen(QColor("#f8d66d"), 2.4, Qt.PenStyle.DashLine))
        self.addItem(self._temporary)
        self.update_connection(port.scenePos())

    def update_connection(self, position: QPointF) -> None:
        if self._connecting_port is None or self._temporary is None:
            return
        start = self._connecting_port.scenePos()
        if self._connecting_port.direction == "input":
            start, position = position, start
        self._temporary.setPath(GraphConnection.curved_path(start, position))

    def finish_connection(self, position: QPointF) -> None:
        start = self._connecting_port
        candidates = [item for item in self.items(position) if isinstance(item, GraphPort)]
        target = next((item for item in candidates if item is not start), None)
        self.cancel_connection()
        if start is None or target is None or start.node is target.node:
            return
        source, destination = (start, target) if start.direction == "output" else (target, start)
        if source.direction != "output" or destination.direction != "input":
            return
        source_definition = BUILTIN_NODE_REGISTRY.get(source.node.template.key)
        target_definition = BUILTIN_NODE_REGISTRY.get(destination.node.template.key)
        source_port = None if source_definition is None else source_definition.port(PortDirection.OUTPUT, source.name)
        target_port = None if target_definition is None else target_definition.port(PortDirection.INPUT, destination.name)
        if source_port is not None and target_port is not None:
            same_kind = source_port.kind is target_port.kind
            same_type = (
                source_port.kind is PortKind.FLOW
                or source_port.data_type == "any"
                or target_port.data_type == "any"
                or source_port.data_type == target_port.data_type
            )
            if not same_kind or not same_type:
                self.connectionRejected.emit(
                    "Those dots carry different kinds of information. Try another matching dot."
                )
                return
        self._add_connection(source, destination)

    def cancel_connection(self) -> None:
        if self._temporary is not None and self._temporary.scene() is self:
            self.removeItem(self._temporary)
        self._temporary = None
        self._connecting_port = None

    def _add_connection(self, source: GraphPort, target: GraphPort, notify: bool = True) -> None:
        duplicate = any(edge.source is source and edge.target is target for edge in self.connections)
        if duplicate:
            return
        edge = GraphConnection(source, target)
        self.connections.append(edge)
        self.addItem(edge)
        if notify:
            self.notify_edited()

    def update_edges_for(self, node: GraphNode) -> None:
        for edge in self.connections:
            if edge.source.node is node or edge.target.node is node:
                edge.update_path()

    def data(self) -> dict[str, Any]:
        graph = {
            "schema": VisualGraph.SCHEMA,
            "id": str(self.property("graph_id") or "scene_logic"),
            "nodes": [
                {
                    "id": node.node_id,
                    "type": node.template.key,
                    "position": [round(node.pos().x(), 3), round(node.pos().y(), 3)],
                    "properties": dict(node.properties),
                }
                for node in sorted(self.nodes.values(), key=lambda item: item.node_id)
            ],
            "links": [
                {
                    "source_node": edge.source.node.node_id,
                    "source_port": edge.source.name,
                    "target_node": edge.target.node.node_id,
                    "target_port": edge.target.name,
                }
                for edge in self.connections
            ],
            "metadata": {**copy.deepcopy(self._graph_metadata), "editor": "ugts-studio"},
        }
        return VisualGraph.from_dict(graph).to_dict()

    def notify_edited(self) -> None:
        if not self._loading:
            self.graphEdited.emit(self.data())


def math_floor(value: float, spacing: int) -> float:
    return value - (value % spacing)


class VisualGraphView(QGraphicsView):
    def __init__(self, scene: VisualGraphScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setObjectName("VisualGraphView")
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.25 <= self.transform().m11() * factor <= 2.8:
            self.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            scene = self.scene()
            if isinstance(scene, VisualGraphScene):
                scene.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def frame_all(self) -> None:
        bounds = self.scene().itemsBoundingRect()
        if bounds.isValid() and not bounds.isEmpty():
            self.fitInView(bounds.adjusted(-100, -100, 100, 100), Qt.AspectRatioMode.KeepAspectRatio)


class NodePalette(QWidget):
    nodeRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("NodePalette")
        self.setMinimumWidth(225)
        self.setMaximumWidth(310)
        self._project_kind: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)
        title = QLabel("Build with Blocks")
        title.setObjectName("PanelTitle")
        self.subtitle = QLabel("Pick a block, then connect its dots.")
        self.subtitle.setObjectName("MutedLabel")
        self.subtitle.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a block…")
        self.search.setClearButtonEnabled(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(16)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.description = QLabel("Choose a block to learn what it does.")
        self.description.setObjectName("MutedLabel")
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(52)
        self.add_button = QPushButton("Add Block")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setEnabled(False)
        self.add_button.setToolTip("Adds the selected block to the middle of the graph")
        layout.addWidget(title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.description)
        layout.addWidget(self.add_button)
        self._populate()
        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self._request_current())
        self.add_button.clicked.connect(self._request_current)

    def _populate(self) -> None:
        self.tree.clear()
        categories: dict[str, QTreeWidgetItem] = {}
        for template in NODE_TEMPLATES:
            category = categories.get(template.category)
            if category is None:
                category = QTreeWidgetItem([template.category])
                category.setFlags(category.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                categories[template.category] = category
                self.tree.addTopLevelItem(category)
            item = QTreeWidgetItem([template.title])
            item.setData(0, Qt.ItemDataRole.UserRole, template.key)
            item.setToolTip(0, template.description)
            item.setForeground(0, QColor(template.color))
            category.addChild(item)
        self.tree.expandAll()

    def _filter(self, text: str) -> None:
        query = text.casefold().strip()
        for index in range(self.tree.topLevelItemCount()):
            category = self.tree.topLevelItem(index)
            visible = False
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                template = TEMPLATE_BY_KEY[str(child.data(0, Qt.ItemDataRole.UserRole))]
                compatible = not (
                    self._project_kind == "3d" and template.key == "action.apply_force"
                )
                matches = compatible and query in f"{template.title} {template.category} {template.description}".casefold()
                child.setHidden(not matches)
                visible = visible or matches
            category.setHidden(not visible)

    def set_project_kind(self, kind: str | None) -> None:
        self._project_kind = kind
        if kind == "3d":
            self.subtitle.setText("Android-safe blocks are shown. Use 3 numbers for 3D positions and scale.")
        else:
            self.subtitle.setText("Pick a block, then connect its dots.")
        self._filter(self.search.text())
        current = self.tree.currentItem()
        if (
            current is not None
            and kind == "3d"
            and current.data(0, Qt.ItemDataRole.UserRole) == "action.apply_force"
        ):
            self.tree.setCurrentItem(None)

    def _selection_changed(self, current: QTreeWidgetItem | None, previous=None) -> None:
        key = None if current is None else current.data(0, Qt.ItemDataRole.UserRole)
        template = TEMPLATE_BY_KEY.get(str(key)) if key else None
        self.add_button.setEnabled(template is not None)
        self.description.setText(
            template.description if template else "Choose a block to learn what it does."
        )

    def _request_current(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key:
            self.nodeRequested.emit(str(key))


class NodePropertiesPanel(QWidget):
    """Small type-aware property editor for the selected logic block."""

    propertiesEdited = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.node: GraphNode | None = None
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(7)
        self.title = QLabel("Selected Block Settings")
        self.title.setObjectName("PanelTitle")
        self.hint = QLabel("Select a block to change its friendly values.")
        self.hint.setObjectName("MutedLabel")
        self.hint.setWordWrap(True)
        self.values = QTreeWidget()
        self.values.setHeaderLabels(["Setting", "Value"])
        self.values.setRootIsDecorated(False)
        self.values.setAlternatingRowColors(True)
        self.values.setMinimumHeight(120)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addWidget(self.values, 1)
        self.values.itemChanged.connect(self._item_changed)

    @staticmethod
    def _display(value: Any) -> str:
        if value is None:
            return "Not set"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        if isinstance(value, Mapping):
            return "Advanced value"
        return str(value)

    @staticmethod
    def _parse(text: str, original: Any) -> Any:
        value = text.strip()
        if isinstance(original, bool):
            return value.casefold() in {"yes", "true", "on", "1"}
        if isinstance(original, int) and not isinstance(original, bool):
            return int(float(value))
        if isinstance(original, float):
            return float(value)
        if isinstance(original, (list, tuple)):
            parts = [part.strip() for part in value.strip("[]() ").split(",") if part.strip()]
            parsed: list[Any] = []
            for index, part in enumerate(parts):
                sample = original[min(index, len(original) - 1)] if original else 0.0
                parsed.append(NodePropertiesPanel._parse(part, sample))
            return parsed
        if original is None:
            if not value or value.casefold() in {"none", "not set"}:
                return None
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def set_node(self, node: GraphNode | None) -> None:
        self._updating = True
        try:
            self.node = node
            self.values.clear()
            if node is None:
                self.title.setText("Selected Block Settings")
                self.hint.setText("Select a block to change its friendly values.")
                return
            self.title.setText(node.template.title)
            if not node.properties:
                self.hint.setText("This block has no values to change. Connect its dots to use it.")
                return
            self.hint.setText("Double-click a value to change it. Your edit is saved in the graph.")
            for key, value in node.properties.items():
                item = QTreeWidgetItem([key.replace("_", " ").title(), self._display(value)])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                item.setData(1, Qt.ItemDataRole.UserRole, value)
                if not isinstance(value, Mapping):
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    item.setToolTip(1, "Double-click to edit")
                else:
                    item.setToolTip(1, "This advanced mapping is kept safe but hidden here")
                self.values.addTopLevelItem(item)
            self.values.resizeColumnToContents(0)
        finally:
            self._updating = False

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 1 or self.node is None:
            return
        key = str(item.data(0, Qt.ItemDataRole.UserRole))
        original = item.data(1, Qt.ItemDataRole.UserRole)
        try:
            parsed = self._parse(item.text(1), original)
        except (TypeError, ValueError):
            self._updating = True
            item.setText(1, self._display(original))
            self._updating = False
            item.setToolTip(1, "That value did not fit, so the previous safe value was kept")
            return
        self.node.properties[key] = parsed
        item.setData(1, Qt.ItemDataRole.UserRole, parsed)
        item.setText(1, self._display(parsed))
        self.node.update()
        scene = self.node.scene()
        if isinstance(scene, VisualGraphScene):
            scene.notify_edited()
        self.propertiesEdited.emit()


class GraphPage(QWidget):
    graphEdited = Signal(object)
    helpRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("GraphToolbar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 8, 12, 8)
        hint = QLabel("Tip: drag from one dot to another to make the game flow.")
        hint.setObjectName("MutedLabel")
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.setToolTip("Removes only the selected block or connection")
        self.frame_button = QPushButton("Show All")
        self.frame_button.setToolTip("Fits every block on screen")
        bar_layout.addWidget(hint, 1)
        bar_layout.addWidget(self.delete_button)
        bar_layout.addWidget(self.frame_button)
        self.palette = NodePalette()
        self.properties = NodePropertiesPanel()
        self.graph_scene = VisualGraphScene(self)
        self.view = VisualGraphView(self.graph_scene)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setMinimumWidth(225)
        left.setMaximumWidth(310)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.palette, 3)
        left_layout.addWidget(self.properties, 2)
        splitter.addWidget(left)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(bar)
        layout.addWidget(splitter, 1)
        self.palette.nodeRequested.connect(self.add_template)
        self.delete_button.clicked.connect(self.graph_scene.delete_selected)
        self.frame_button.clicked.connect(self.view.frame_all)
        self.graph_scene.graphEdited.connect(self.graphEdited)
        self.graph_scene.connectionRejected.connect(self.helpRequested)
        self.graph_scene.selectionChanged.connect(self._selection_changed)
        self._project_kind: str | None = None

    def set_project_kind(self, kind: str | None) -> None:
        self._project_kind = kind
        self.palette.set_project_kind(kind)

    def load_data(self, data: Mapping[str, Any]) -> None:
        self.graph_scene.load_data(data)
        if self._project_kind == "3d" and any(
            node.template.key == "action.apply_force" for node in self.graph_scene.nodes.values()
        ):
            self.helpRequested.emit(
                "This graph uses Push an Object, which is 2D-only. Remove it before an Android build."
            )
        if self.graph_scene.nodes:
            self.view.frame_all()
        else:
            self.view.resetTransform()
            self.view.centerOn(0, 0)

    def add_template(self, key: str) -> None:
        template = TEMPLATE_BY_KEY.get(key)
        if template is None:
            return
        center = self.view.mapToScene(self.view.viewport().rect().center())
        offset = QPointF(len(self.graph_scene.nodes) % 4 * 18, len(self.graph_scene.nodes) % 3 * 18)
        properties = None
        if self._project_kind == "3d" and key == "action.set_component":
            properties = {"entity": None, "component": "transform", "field": "translation", "value": [0, 0, 0]}
        node = self.graph_scene.add_node(
            template,
            center - QPointF(105, 50) + offset,
            properties=properties,
            notify=False,
        )
        node_id = node.node_id
        # The main window records the edit through QUndoStack. Its synchronous
        # redo reloads this scene, so the original QGraphicsObject may already
        # be deleted when notify_edited returns. Reacquire the persisted node
        # before selecting or centering it.
        self.graph_scene.notify_edited()
        persisted = self.graph_scene.nodes.get(node_id)
        if persisted is not None:
            self.graph_scene.clearSelection()
            persisted.setSelected(True)
            self.view.centerOn(persisted)
        self.helpRequested.emit(f"Added “{template.title}”. Drag its dots to connect it.")

    def _selection_changed(self) -> None:
        node = next(
            (item for item in self.graph_scene.selectedItems() if isinstance(item, GraphNode)),
            None,
        )
        self.properties.set_node(node)


__all__ = ["GraphPage", "NODE_TEMPLATES", "NodePalette", "VisualGraphScene"]
