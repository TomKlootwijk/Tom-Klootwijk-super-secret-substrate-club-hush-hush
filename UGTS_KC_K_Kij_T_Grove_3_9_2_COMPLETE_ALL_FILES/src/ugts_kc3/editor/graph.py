"""Beginner-friendly, serializable visual logic graph widgets."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import re
import uuid
from typing import Any, Iterable, Mapping

from PySide6.QtCore import QPointF, QRectF, QRegularExpression, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..packed_kinematics import POLAR_MOVEMENT_FIELDS
from ..visual_graph import BUILTIN_NODE_REGISTRY, PortDirection, PortKind, VisualGraph
from .document import GraphAuthoringContext


_MESSAGE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


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
    "event.timer": ("When Timer Rings", "Events"),
    "event.message": ("When Message Heard", "Events"),
    "flow.branch": ("If This Is True", "Choices"),
    "value.constant": ("A Value", "Values"),
    "value.seeded_number": ("Repeatable Random Number", "Values"),
    "value.state": ("Read Score or Game Value", "Values"),
    "value.component": ("Read Object Setting", "Values"),
    "value.polar_movement": ("Read Movement", "Movement"),
    "query.nearest_tag": ("Find Nearby Object", "Sensing"),
    "query.nearest_in_cone": ("Find Object Ahead", "Sensing"),
    "compare": ("Compare Two Things", "Choices"),
    "action.set_state": ("Change Score or Game Value", "Game Actions"),
    "action.set_component": ("Change Object Setting", "Game Actions"),
    "action.set_polar_movement": ("Change Movement", "Movement"),
    "action.set_polar_population_visible": ("Show or Hide Extra Copies", "Looks"),
    "action.emit_event": ("Send a Game Message", "Game Actions"),
    "action.apply_force": ("Push an Object", "Movement"),
    "action.play_animation": ("Play an Animation", "Animation"),
    "action.stop_animation": ("Stop an Animation", "Animation"),
    "action.set_active": ("Show or Hide Object", "Game Actions"),
    "action.despawn": ("Remove Object", "Game Actions"),
}
_FRIENDLY_NODE_DESCRIPTIONS = {
    "event.timer": (
        "Waits for the saved number of seconds, then starts the connected blocks. "
        "Turn Repeat on to ring again and again while this object is active."
    ),
    "event.message": (
        "Starts the connected blocks after Send a Game Message uses this exact name. "
        "Messages wait their turn, so one block cannot interrupt another halfway through."
    ),
    "query.nearest_in_cone": (
        "Finds the nearest chosen kind of object in a saved facing direction. "
        "Facing and View width use the same compact values on desktop, web, and phone."
    ),
    "action.play_animation": (
        "Starts one named animation clip on this object or another animated object. "
        "Restart begins it again from the first frame."
    ),
    "action.stop_animation": (
        "Stops the animation playing on this object or another animated object. "
        "Reset returns it to its starting pose."
    ),
    "value.polar_movement": (
        "Reads one named movement number without showing component names or packed words. "
        "The same quantized value is used on desktop and phone."
    ),
    "action.set_polar_movement": (
        "Changes one named movement number and immediately rebuilds the compact pose or motion. "
        "Use it only on an object with a Movement Pattern."
    ),
    "action.set_polar_population_visible": (
        "Shows or hides only the extra display copies made by Make Many. "
        "The real object stays visible and keeps running its Logic Blocks."
    ),
}
_LITERAL_ONLY_INPUTS = {
    "event.timer": frozenset({"seconds", "repeat"}),
    "event.message": frozenset({"message"}),
    "value.polar_movement": frozenset({"field"}),
    "action.set_polar_movement": frozenset({"field"}),
    "action.set_polar_population_visible": frozenset({"entity"}),
}
_CATEGORY_COLORS = {
    "Events": "#5ac8fa", "Choices": "#c792ea", "Values": "#f6c85f",
    "Math": "#f0a45d", "Movement": "#78e6a3", "Game Actions": "#ff8fab",
    "Sensing": "#64d8cb", "Looks": "#a78bfa",
    "Animation": "#ffb86c",
}

_THREE_D_ONLY_PALETTE_KEYS = frozenset(
    {
        "action.play_animation",
        "action.stop_animation",
        "value.polar_movement",
        "action.set_polar_movement",
        "action.set_polar_population_visible",
    }
)


@dataclass(frozen=True)
class PropertyChoiceSpec:
    """Canonical values and child-facing labels for one finite node setting."""

    choices: tuple[tuple[Any, str, str], ...]
    tooltip: str
    editable: bool = False


_COMPARISON_CHOICES = (
    ("equal", "Is equal to  (=)", "Both values must be the same"),
    ("not_equal", "Is not equal to  (≠)", "The values must be different"),
    ("less", "Is less than  (<)", "A must be smaller than B"),
    ("less_equal", "Is at most  (≤)", "A may be smaller than or equal to B"),
    ("greater", "Is greater than  (>)", "A must be larger than B"),
    ("greater_equal", "Is at least  (≥)", "A may be larger than or equal to B"),
)
_BOOLEAN_CHOICES = (
    (True, "Yes", "Store the boolean value true"),
    (False, "No", "Store the boolean value false"),
)
_PORTABLE_TAG_CHOICES = (
    ("player", "Player", "Find objects tagged as the player"),
    ("collectible", "Collectible", "Find coins, crystals, and other pickups"),
    ("goal", "Goal", "Find the nearest goal or finish object"),
    ("decorative", "Decoration", "Find a display-only scene object"),
    ("hazard", "Hazard", "Find the nearest dangerous object"),
)
_CONE_WIDTH_CHOICES = (
    (0.8660253882408142, "Narrow · 60°", "A focused 60-degree view"),
    (0.7071067690849304, "Normal · 90°", "A balanced 90-degree view"),
    (0.0, "Wide · 180°", "Everything in the facing half of the world"),
)
_CONE_DIRECTIONS = {
    "2d": (
        ((1.0, 0.0, 0.0), "Right", "Toward the right side of the scene"),
        ((-1.0, 0.0, 0.0), "Left", "Toward the left side of the scene"),
        ((0.0, 1.0, 0.0), "Down", "Toward the bottom of the scene"),
        ((0.0, -1.0, 0.0), "Up", "Toward the top of the scene"),
    ),
    "3d": (
        ((0.0, 0.0, -1.0), "Forward", "Forward along negative Z"),
        ((0.0, 0.0, 1.0), "Back", "Back along positive Z"),
        ((1.0, 0.0, 0.0), "Right", "Right along positive X"),
        ((-1.0, 0.0, 0.0), "Left", "Left along negative X"),
        ((0.0, 1.0, 0.0), "Up", "Up along positive Y"),
        ((0.0, -1.0, 0.0), "Down", "Down along negative Y"),
    ),
}
_ACTION_CHOICES = {
    "2d": (
        ("dash", "Dash", "Space, Shift, gamepad, or the Dash touch button"),
        ("move_x", "Move left / right", "The project's horizontal movement action"),
        ("move_y", "Move up / down", "The project's vertical movement action"),
        ("pause", "Pause", "Pause button"),
        ("restart", "Restart", "Restart button"),
        ("mute", "Mute sound", "Mute button"),
        ("save", "Save game", "Save button"),
        ("load", "Load game", "Load button"),
    ),
    "3d": (
        ("dash", "Dash / action", "The phone action button used by the starter lesson"),
        ("action", "Action", "The general phone action button"),
        ("accept", "Accept", "An alias for the phone action button"),
        ("jump", "Jump", "The phone jump button"),
        ("move_left", "Move left", "The left side of the movement control"),
        ("move_right", "Move right", "The right side of the movement control"),
        ("move_up", "Move forward", "The forward side of the movement control"),
        ("move_down", "Move backward", "The backward side of the movement control"),
    ),
}
_COMPONENT_FIELDS = {
    "2d": {
        "transform": ("position", "rotation", "scale"),
        "body": (
            "velocity", "angular_velocity", "acceleration", "force", "mass",
            "damping", "gravity_scale", "restitution", "friction", "max_speed",
            "fixed_rotation", "body_type",
        ),
        "collider": ("enabled", "offset", "tag", "filter.layer", "filter.mask", "filter.sensor"),
        "vector_renderer": ("asset_id", "z_index", "visible", "opacity", "tint"),
        "camera": ("position", "zoom", "rotation", "follow_entity", "follow_smoothing"),
        "lifetime": ("remaining",),
        "health": ("current", "maximum", "invulnerability", "invulnerable_remaining"),
        "bounds_constraint": ("mode",),
        "player_controller": (
            "x_action", "y_action", "speed", "dash_action", "dash_speed",
            "dash_duration", "dash_cooldown", "last_direction",
        ),
        "collectible": ("points", "state_key", "sound", "destroy_on_collect"),
        "hazard": ("damage", "knockback", "cooldown", "sound"),
        "packed_kinematic": ("pose_word", "motion_word", "profile_id"),
    },
    "3d": {
        "transform": ("translation", "position", "rotation", "scale"),
        "body": ("velocity", "angular_velocity", "dynamic", "mass", "restitution"),
        "velocity": ("x", "y", "z"),
        "angular_velocity": ("x", "y", "z"),
        "collider": ("shape", "radius", "half_extents", "sensor"),
        "render": ("mesh_id", "material_id"),
        "active": (),
        "alive": (),
        "polar_movement": POLAR_MOVEMENT_FIELDS,
    },
}
_POLAR_MOVEMENT_FIELD_CHOICES = (
    (
        "radius",
        "Distance from centre",
        "World-space distance from the movement centre; must fit this object's saved profile",
    ),
    (
        "angle_degrees",
        "Angle around centre (degrees)",
        "Where the object sits around the centre; values wrap around 360 degrees",
    ),
    (
        "facing_degrees",
        "Facing direction (degrees)",
        "Where the object points; values wrap around 360 degrees",
    ),
    (
        "turns_per_second",
        "Turns per second",
        "Positive circles one way and negative circles the other way",
    ),
    (
        "growth_per_second",
        "Grow / shrink speed",
        "Positive spirals outward and negative spirals inward in compact log-radius units",
    ),
    (
        "turn_acceleration",
        "Turn acceleration",
        "How much Turns per second changes each second",
    ),
    (
        "growth_acceleration",
        "Grow / shrink acceleration",
        "How much Grow / shrink speed changes each second",
    ),
)
_EVENT_CHOICES = {
    "2d": (
        "graph_event", "player.dashed", "dash", "collision_enter", "collision_stay", "collision_exit",
        "collected", "damaged", "entity_defeated", "lifetime_expired",
        "entity_spawned", "entity_despawned",
    ),
    "3d": (
        "graph_event", "player.dashed", "jump", "floor_contact", "bounds_contact", "collision",
        "collected", "goal",
    ),
}
_MESSAGE_CHOICES = {
    # Receiver presets are deliberately limited to names the starter graphs
    # actually send.  Engine events such as collision_enter remain useful on
    # Send a Game Message, but they are not implicitly queued for this block.
    "2d": ("graph_event", "player.dashed"),
    "3d": ("graph_event", "player.dashed"),
}
_PROPERTY_LABELS = {
    "action": "Button / action",
    "active": "Object is active",
    "component": "Object part",
    "clip": "Animation clip",
    "cone": "Facing + view",
    "condition": "Condition",
    "default": "Fallback value",
    "entity": "Object ID",
    "field": "Part setting",
    "force": "Push amount",
    "key": "Game value name",
    "kind": "Message name",
    "message": "Message name",
    "largest": "Largest",
    "operator": "Compare using",
    "origin": "Search from",
    "pick_number": "Pick number",
    "payload": "Message details",
    "source": "Sender object ID",
    "smallest": "Smallest",
    "tag": "Object kind",
    "target": "Receiver object ID",
    "radius": "Search distance",
    "repeat": "Repeat",
    "restart": "Restart from the beginning",
    "reset": "Return to starting pose",
    "seconds": "Seconds",
    "value": "Value",
    "visible": "Show extra copies",
    "world_number": "World number",
}


_TRACE_ERROR_STATUSES = frozenset({"error", "failed", "failure", "stopped"})
_TRACE_SKIPPED_STATUSES = frozenset({"skipped", "not_run", "not-run"})


def _record_value(record: object, key: str, default: Any = None) -> Any:
    """Read one field from a trace dataclass or its mapping representation."""

    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _compact_trace_value(value: Any, *, limit: int = 54) -> str:
    """Return a stable, child-facing summary for a runtime value."""

    def compact(item: Any, depth: int = 0) -> str:
        if item is None:
            return "Nothing"
        if isinstance(item, bool):
            return "Yes" if item else "No"
        if isinstance(item, float):
            if item == 0:
                return "0"
            return format(item, ".4g")
        if isinstance(item, int):
            return str(item)
        if isinstance(item, str):
            return item
        if isinstance(item, Mapping):
            if depth >= 1:
                return "{…}"
            pairs = list(item.items())
            shown = [
                f"{str(key).replace('_', ' ').title()}: {compact(nested, depth + 1)}"
                for key, nested in pairs[:2]
            ]
            if len(pairs) > 2:
                shown.append("…")
            return ", ".join(shown) if shown else "Nothing"
        if isinstance(item, (list, tuple)):
            if depth >= 1:
                return "[…]"
            shown = [compact(nested, depth + 1) for nested in item[:4]]
            if len(item) > 4:
                shown.append("…")
            return "(" + ", ".join(shown) + ")"
        return f"<{type(item).__name__}>"

    text = compact(value).replace("\n", " ").strip()
    if len(text) > limit:
        return text[: max(1, limit - 1)].rstrip() + "…"
    return text


def _trace_entry_summary(entry: object) -> str:
    error = _record_value(entry, "error")
    if error:
        return "Error: " + _compact_trace_value(str(error), limit=46)
    outputs = _record_value(entry, "outputs", {})
    if isinstance(outputs, Mapping) and outputs:
        return _compact_trace_value(outputs)
    flow_outputs = _record_value(entry, "flow_outputs", ())
    if isinstance(flow_outputs, Iterable) and not isinstance(flow_outputs, (str, bytes)):
        flow = tuple(str(item) for item in flow_outputs)
        if flow:
            friendly = " / ".join(item.replace("_", " ").title() for item in flow)
            return "Next: " + friendly
    status = str(_record_value(entry, "status", "ok") or "ok").casefold()
    if status in _TRACE_SKIPPED_STATUSES:
        return "Skipped"
    return "Ran"


def _node_templates() -> tuple[NodeTemplate, ...]:
    result: list[NodeTemplate] = []
    for definition in BUILTIN_NODE_REGISTRY:
        label, category = _FRIENDLY_NODE_NAMES.get(
            definition.type,
            (definition.label, "Math" if definition.category == "Math" else definition.category),
        )
        literal_only = _LITERAL_ONLY_INPUTS.get(definition.type, frozenset())
        inputs = tuple(
            port.name
            for port in definition.ports
            if port.direction is PortDirection.INPUT and port.name not in literal_only
        )
        outputs = tuple(port.name for port in definition.ports if port.direction is PortDirection.OUTPUT)
        result.append(
            NodeTemplate(
                definition.type,
                label,
                category,
                _FRIENDLY_NODE_DESCRIPTIONS.get(definition.type, definition.description),
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
            if scene.read_only:
                event.accept()
                return
            scene.begin_connection(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        scene = self.scene()
        if isinstance(scene, VisualGraphScene):
            if scene.read_only:
                event.accept()
                return
            scene.update_connection(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        scene = self.scene()
        if isinstance(scene, VisualGraphScene):
            if scene.read_only:
                event.accept()
                return
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
        # Runtime presentation state deliberately lives outside properties and
        # is therefore absent from VisualGraphScene.data().
        self.trace_steps: tuple[int, ...] = ()
        self.trace_status: str | None = None
        self.trace_summary = ""
        self.trace_error: str | None = None
        self._position_ports()

    def clear_trace(self) -> None:
        self.trace_steps = ()
        self.trace_status = None
        self.trace_summary = ""
        self.trace_error = None
        self.setToolTip(self.template.description)
        self.update()

    def add_trace_entry(self, entry: object, order: int) -> None:
        try:
            step = int(_record_value(entry, "step", order))
        except (TypeError, ValueError):
            step = order
        self.trace_steps = self.trace_steps + (step,)
        self.trace_status = str(_record_value(entry, "status", "ok") or "ok")
        error = _record_value(entry, "error")
        self.trace_error = None if error in (None, "") else str(error)
        self.trace_summary = _trace_entry_summary(entry)
        details = [self.template.description, f"Last Run step {step}: {self.trace_summary}"]
        if len(self.trace_steps) > 1:
            details.append("Visited at steps " + ", ".join(str(item) for item in self.trace_steps))
        self.setToolTip("\n".join(details))
        self.update()

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
        status = (self.trace_status or "").casefold()
        has_error = bool(self.trace_error) or status in _TRACE_ERROR_STATUSES
        skipped = status in _TRACE_SKIPPED_STATUSES
        traced = bool(self.trace_steps)
        if has_error:
            border = QColor("#ff6b81")
            body = QColor("#321a25")
        elif traced and skipped:
            border = QColor("#7f90a4")
            body = QColor("#1a2634")
        elif traced:
            border = QColor("#63d9a3")
            body = QColor("#142b29")
        else:
            border = QColor("#68d8ff") if selected else QColor("#2d4057")
            body = QColor("#152234")
        painter.setPen(QPen(border, 2.6 if selected or has_error else 1.5 if traced else 1.2))
        painter.setBrush(body)
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
        title_width = self.WIDTH - (62 if self.trace_steps else 26)
        painter.drawText(QRectF(13, 0, title_width, 43), Qt.AlignmentFlag.AlignVCenter, self.template.title)

        if self.trace_steps:
            badge_text = str(self.trace_steps[-1])
            if len(self.trace_steps) > 1:
                badge_text += f"×{len(self.trace_steps)}"
            badge_width = max(28.0, 12.0 + painter.fontMetrics().horizontalAdvance(badge_text))
            badge_rect = QRectF(self.WIDTH - badge_width - 10, 8, badge_width, 27)
            painter.setPen(QPen(QColor("#07111d"), 1))
            painter.setBrush(QColor("#ff8a9d") if has_error else QColor("#a5f0c9"))
            painter.drawRoundedRect(badge_rect, 8, 8)
            painter.setPen(QColor("#07111d"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

            font.setBold(False)
            font.setPointSizeF(7.7)
            painter.setFont(font)
            summary = painter.fontMetrics().elidedText(
                self.trace_summary, Qt.TextElideMode.ElideRight, int(self.WIDTH - 28)
            )
            painter.setPen(QColor("#ffb4c0") if has_error else QColor("#a7ddc6"))
            painter.drawText(
                QRectF(13, 43, self.WIDTH - 26, 18),
                Qt.AlignmentFlag.AlignVCenter,
                summary,
            )

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
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            scene = self.scene()
            if isinstance(scene, VisualGraphScene) and scene.read_only and not scene.loading:
                return self.pos()
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            if isinstance(scene, VisualGraphScene):
                scene.update_edges_for(self)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._press_position = QPointF(self.pos())
        scene = self.scene()
        if not isinstance(scene, VisualGraphScene) or not scene.read_only:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        scene = self.scene()
        self.setCursor(
            Qt.CursorShape.ArrowCursor
            if isinstance(scene, VisualGraphScene) and scene.read_only
            else Qt.CursorShape.OpenHandCursor
        )
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
        self._read_only = False
        self._graph_metadata: dict[str, Any] = {}

    @property
    def loading(self) -> bool:
        return self._loading

    @property
    def read_only(self) -> bool:
        return self._read_only

    def set_read_only(self, read_only: bool) -> None:
        """Disable graph mutations while retaining selection and navigation."""

        self._read_only = bool(read_only)
        if self._read_only:
            self.cancel_connection()
        for node in self.nodes.values():
            node.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                not self._read_only,
            )
            node.setCursor(
                Qt.CursorShape.ArrowCursor
                if self._read_only
                else Qt.CursorShape.OpenHandCursor
            )
            for port in (*node.input_ports.values(), *node.output_ports.values()):
                port.setAcceptedMouseButtons(
                    Qt.MouseButton.NoButton
                    if self._read_only
                    else Qt.MouseButton.LeftButton
                )

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
        if self._read_only and not self._loading:
            return
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
            self.set_read_only(self._read_only)

    def add_node(
        self,
        template: NodeTemplate,
        position: QPointF,
        *,
        node_id: str | None = None,
        properties: Mapping[str, Any] | None = None,
        notify: bool = True,
    ) -> GraphNode:
        if self._read_only and not self._loading:
            raise RuntimeError("The logic graph is read-only while the game is running.")
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
        if self._read_only:
            return
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
        if self._read_only:
            return
        self.cancel_connection()
        self._connecting_port = port
        self._temporary = QGraphicsPathItem()
        self._temporary.setZValue(-0.5)
        self._temporary.setPen(QPen(QColor("#f8d66d"), 2.4, Qt.PenStyle.DashLine))
        self.addItem(self._temporary)
        self.update_connection(port.scenePos())

    def update_connection(self, position: QPointF) -> None:
        if self._read_only:
            return
        if self._connecting_port is None or self._temporary is None:
            return
        start = self._connecting_port.scenePos()
        if self._connecting_port.direction == "input":
            start, position = position, start
        self._temporary.setPath(GraphConnection.curved_path(start, position))

    def finish_connection(self, position: QPointF) -> None:
        if self._read_only:
            self.cancel_connection()
            return
        start = self._connecting_port
        candidates = [item for item in self.items(position) if isinstance(item, GraphPort)]
        target = next((item for item in candidates if item is not start), None)
        self.cancel_connection()
        if start is None or target is None or start.node is target.node:
            return
        source, destination = (start, target) if start.direction == "output" else (target, start)
        if source.direction != "output" or destination.direction != "input":
            return
        literal_only = _LITERAL_ONLY_INPUTS.get(destination.node.template.key, frozenset())
        if destination.name in literal_only:
            self.connectionRejected.emit(
                "Set Seconds and Repeat in When Timer Rings settings. "
                "Those values are saved in the block and cannot use a wire."
            )
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
        if self._read_only and not self._loading:
            return
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
        if not self._loading and not self._read_only:
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
                allowed = (
                    template.key not in _THREE_D_ONLY_PALETTE_KEYS
                    or self._project_kind == "3d"
                )
                matches = allowed and query in (
                    f"{template.title} {template.category} {template.description}".casefold()
                )
                child.setHidden(not matches)
                visible = visible or matches
            category.setHidden(not visible)

    def set_project_kind(self, kind: str | None) -> None:
        self._project_kind = kind
        if kind == "3d":
            self.subtitle.setText("Compact Android-safe blocks are shown. Push uses the X/Z ground plane.")
        else:
            self.subtitle.setText("Pick a block, then connect its dots.")
        self._filter(self.search.text())

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
        self.project_kind: str | None = None
        self._entity_context_known = False
        self._entity_owner_id: str | None = None
        self._entity_choices: tuple[tuple[str, str], ...] = ()
        self._animation_choices: tuple[tuple[str, str], ...] = ()
        self._polar_population_choices: tuple[tuple[str, str], ...] = ()
        self._updating = False
        self._read_only = False
        self._editors: dict[str, QWidget] = {}
        self._items: dict[str, QTreeWidgetItem] = {}
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

    @property
    def read_only(self) -> bool:
        return self._read_only

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        self.values.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
            if self._read_only
            else (
                QAbstractItemView.EditTrigger.DoubleClicked
                | QAbstractItemView.EditTrigger.EditKeyPressed
            )
        )
        self.set_node(self.node)

    def set_project_kind(self, kind: str | None) -> None:
        kind = kind if kind in {"2d", "3d"} else None
        if kind == self.project_kind:
            return
        self.project_kind = kind
        if self.node is not None:
            self.set_node(self.node)

    def set_entity_context(
        self,
        owner_id: str | None,
        choices: tuple[tuple[str, str], ...],
    ) -> None:
        """Provide scene IDs for child-safe entity inputs in sensing blocks."""

        normalized = tuple((str(value), str(label)) for value, label in choices)
        changed = (
            not self._entity_context_known
            or owner_id != self._entity_owner_id
            or normalized != self._entity_choices
        )
        self._entity_context_known = True
        self._entity_owner_id = owner_id
        self._entity_choices = normalized
        if changed and self.node is not None:
            self.set_node(self.node)

    def set_animation_context(
        self, choices: tuple[tuple[str, str], ...]
    ) -> None:
        """Provide stable clip IDs and child-facing names for animation blocks."""

        normalized = tuple((str(value), str(label)) for value, label in choices)
        if normalized == self._animation_choices:
            return
        self._animation_choices = normalized
        if self.node is not None:
            self.set_node(self.node)

    def set_polar_population_context(
        self, choices: tuple[tuple[str, str], ...]
    ) -> None:
        """Provide only prototypes that own a valid Make Many recipe."""

        normalized = tuple((str(value), str(label)) for value, label in choices)
        if normalized == self._polar_population_choices:
            return
        self._polar_population_choices = normalized
        if self.node is not None:
            self.set_node(self.node)

    def editor_for(self, key: str) -> QWidget | None:
        """Return the contextual editor for tests and accessibility helpers."""

        return self._editors.get(str(key))

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

    @staticmethod
    def _friendly_value(value: str) -> str:
        if not value:
            return "Whole part"
        replacements = {
            "translation": "Position (3D)",
            "position": "Position",
            "angular_velocity": "Spin speed",
            "vector_renderer": "Picture",
            "packed_kinematic": "Packed polar movement",
            "polar_movement": "Polar movement",
            "angle_degrees": "Angle around centre (degrees)",
            "facing_degrees": "Facing direction (degrees)",
            "turns_per_second": "Turns per second",
            "growth_per_second": "Grow / shrink speed",
            "turn_acceleration": "Turn acceleration",
            "growth_acceleration": "Grow / shrink acceleration",
            "bounds_constraint": "Scene bounds",
            "player_controller": "Player controls",
        }
        return replacements.get(value, value.replace(".", " › ").replace("_", " ").title())

    def _actions(self) -> tuple[tuple[Any, str, str], ...]:
        if self.project_kind in _ACTION_CHOICES:
            return _ACTION_CHOICES[self.project_kind]
        seen: set[str] = set()
        result: list[tuple[Any, str, str]] = []
        for kind in ("2d", "3d"):
            for choice in _ACTION_CHOICES[kind]:
                if choice[0] not in seen:
                    result.append(choice)
                    seen.add(choice[0])
        return tuple(result)

    def _component_fields(self) -> Mapping[str, tuple[str, ...]]:
        if self.project_kind in _COMPONENT_FIELDS:
            return _COMPONENT_FIELDS[self.project_kind]
        return _COMPONENT_FIELDS["2d"]

    @staticmethod
    def _with_current_choice(
        choices: tuple[tuple[Any, str, str], ...], current: Any, noun: str
    ) -> tuple[tuple[Any, str, str], ...]:
        if any(value == current and type(value) is type(current) for value, _, _ in choices):
            return choices
        if not isinstance(current, str) or not current:
            return choices
        return choices + ((
            current,
            f"{NodePropertiesPanel._friendly_value(current)} (project custom)",
            f"Keep the custom {noun} already stored in this project: {current}",
        ),)

    def _choice_spec(self, node: GraphNode, key: str, value: Any) -> PropertyChoiceSpec | None:
        if node.template.key == "compare" and key == "operator":
            return PropertyChoiceSpec(
                _COMPARISON_CHOICES,
                "Choose how A and B are compared. The saved graph keeps the engine's exact operator name.",
            )

        if (
            node.template.key == "action.set_polar_population_visible"
            and key == "entity"
        ):
            choices: tuple[tuple[Any, str, str], ...] = ()
            if any(
                entity_id == self._entity_owner_id
                for entity_id, _label in self._polar_population_choices
            ):
                choices += ((
                    None,
                    "This object",
                    "Use the Make Many recipe owned by this Logic Blocks object",
                ),)
            choices += tuple(
                (
                    entity_id,
                    label,
                    f"Use the Make Many recipe on project object: {entity_id}",
                )
                for entity_id, label in self._polar_population_choices
            )
            return PropertyChoiceSpec(
                choices,
                "Choose an object that has Make Many. Other objects cannot be targeted.",
            )

        if (
            node.template.key == "action.set_polar_population_visible"
            and key == "visible"
        ):
            return PropertyChoiceSpec(
                (
                    (True, "Show extra copies", "Draw the extra Make Many copies"),
                    (False, "Hide extra copies", "Hide only the extra Make Many copies"),
                ),
                "The real object stays visible in both choices.",
            )

        definition = BUILTIN_NODE_REGISTRY.get(node.template.key)
        port = None if definition is None else definition.port(PortDirection.INPUT, key)
        if isinstance(value, bool) or (port is not None and port.data_type == "boolean"):
            return PropertyChoiceSpec(
                _BOOLEAN_CHOICES,
                "Choose Yes or No. This is stored as a real boolean, not text.",
            )

        if node.template.key == "event.input_pressed" and key == "action":
            return PropertyChoiceSpec(
                self._with_current_choice(self._actions(), value, "input action"),
                "Choose a button action available to this kind of project.",
            )

        if (
            node.template.key in {"action.play_animation", "action.stop_animation"}
            and key == "entity"
        ):
            choices: tuple[tuple[Any, str, str], ...] = ((
                None,
                "This object",
                "Animate the object that owns these Logic Blocks",
            ),)
            choices += tuple(
                (
                    entity_id,
                    label,
                    f"Animate project object: {entity_id}",
                )
                for entity_id, label in self._entity_choices
            )
            if (
                isinstance(value, str)
                and value
                and not any(choice[0] == value for choice in choices)
            ):
                choices += ((
                    value,
                    f"{self._friendly_value(value)} (chosen object)",
                    f"Animate project object: {value}",
                ),)
            return PropertyChoiceSpec(
                choices,
                "Choose This object, or type another project object ID.",
                editable=True,
            )

        if node.template.key == "action.play_animation" and key == "clip":
            choices = tuple(
                (
                    clip_id,
                    label,
                    f"Animation clip ID: {clip_id}",
                )
                for clip_id, label in self._animation_choices
            )
            choices = self._with_current_choice(choices, value, "animation clip")
            return PropertyChoiceSpec(
                choices,
                "Choose one of this object's clips, or type a clip ID for another object.",
                editable=True,
            )

        if node.template.key in {"query.nearest_tag", "query.nearest_in_cone"} and key == "origin":
            choices: tuple[tuple[Any, str, str], ...] = ()
            if not self._entity_context_known or self._entity_owner_id is not None:
                choices += ((
                    None,
                    "This object",
                    "Start at the object that owns these Logic Blocks",
                ),)
            choices += tuple(
                (
                    entity_id,
                    label,
                    f"Start at project object: {entity_id}",
                )
                for entity_id, label in self._entity_choices
            )
            if (
                isinstance(value, str)
                and value
                and not any(choice[0] == value for choice in choices)
            ):
                choices += ((
                    value,
                    f"{self._friendly_value(value)} (chosen object)",
                    f"Start at project object: {value}",
                ),)
            return PropertyChoiceSpec(
                choices,
                "Choose This object, or type another project object ID.",
                editable=True,
            )

        if node.template.key in {"query.nearest_tag", "query.nearest_in_cone"} and key == "tag":
            return PropertyChoiceSpec(
                _PORTABLE_TAG_CHOICES,
                "These five object kinds stay identical in desktop, web, and phone builds.",
            )

        if (
            node.template.key
            in {"value.polar_movement", "action.set_polar_movement"}
            and key == "entity"
        ):
            choices: tuple[tuple[Any, str, str], ...] = ((
                None,
                "This object",
                "Use the object that owns these Logic Blocks",
            ),)
            choices += tuple(
                (
                    entity_id,
                    label,
                    f"Use project object: {entity_id}",
                )
                for entity_id, label in self._entity_choices
            )
            return PropertyChoiceSpec(
                self._with_current_choice(choices, value, "movement object"),
                "Choose This object or another object with a Movement Pattern.",
                editable=True,
            )

        if (
            node.template.key
            in {"value.polar_movement", "action.set_polar_movement"}
            and key == "field"
        ):
            return PropertyChoiceSpec(
                _POLAR_MOVEMENT_FIELD_CHOICES,
                "Choose one friendly number from this object's compact movement. "
                "The engine quantizes each change identically on desktop and phone.",
            )

        if node.template.key in {"value.component", "action.set_component"} and key == "component":
            choices = tuple(
                (
                    component,
                    self._friendly_value(component),
                    f"Use the built-in {component} object part",
                )
                for component in self._component_fields()
            )
            return PropertyChoiceSpec(
                self._with_current_choice(choices, value, "component"),
                "Choose which built-in object part this block reads or changes.",
            )

        if node.template.key in {"value.component", "action.set_component"} and key == "field":
            component = str(node.properties.get("component", ""))
            fields = self._component_fields().get(component)
            if fields is None:
                return None
            if component == "polar_movement":
                return PropertyChoiceSpec(
                    _POLAR_MOVEMENT_FIELD_CHOICES,
                    "Choose one friendly number from this object's compact movement. "
                    "The engine quantizes each change identically on desktop and phone.",
                )
            choices = tuple(
                (field, self._friendly_value(field), f"Canonical field: {field or '(whole component)'}")
                for field in fields
            )
            whole_description = (
                "Read the complete component value"
                if node.template.key == "value.component"
                else "Replace the complete component value"
            )
            choices = (("", "Whole part", whole_description),) + choices
            return PropertyChoiceSpec(
                self._with_current_choice(choices, value, "component field"),
                f"Choose a setting that belongs to {self._friendly_value(component)}.",
            )

        if (
            (node.template.key == "action.emit_event" and key == "kind")
            or (node.template.key == "event.message" and key == "message")
        ):
            choice_source = (
                _MESSAGE_CHOICES
                if node.template.key == "event.message"
                else _EVENT_CHOICES
            )
            event_values = choice_source.get(
                self.project_kind or "", choice_source["2d"]
            )
            choices = tuple(
                (event, self._friendly_value(event), f"Canonical message name: {event}")
                for event in event_values
            )
            return PropertyChoiceSpec(
                self._with_current_choice(choices, value, "message name"),
                "Choose a familiar game message or type a custom message name.",
                editable=True,
            )
        return None

    def _make_choice_editor(
        self,
        key: str,
        value: Any,
        spec: PropertyChoiceSpec,
    ) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName(f"GraphProperty_{key}")
        combo.setProperty("graph_property_key", key)
        combo.setEditable(spec.editable)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setToolTip(spec.tooltip)
        combo.setEnabled(not self._read_only)
        for canonical, label, tooltip in spec.choices:
            combo.addItem(label, canonical)
            combo.setItemData(
                combo.count() - 1,
                f"{tooltip}\nSaved as: {canonical}",
                Qt.ItemDataRole.ToolTipRole,
            )
        current_index = next(
            (
                index for index in range(combo.count())
                if combo.itemData(index) == value
                and type(combo.itemData(index)) is type(value)
            ),
            -1,
        )
        combo.setCurrentIndex(current_index)
        if spec.editable and current_index < 0:
            combo.setCurrentText(str(value))
        combo.currentIndexChanged.connect(
            lambda _index, property_key=key, editor=combo: self._choice_changed(
                property_key, editor, custom_text=False
            )
        )
        if spec.editable and combo.lineEdit() is not None:
            if self.node is not None and self.node.template.key in {
                "action.emit_event",
                "event.message",
            }:
                combo.lineEdit().setMaxLength(64)
                combo.lineEdit().setValidator(
                    QRegularExpressionValidator(
                        QRegularExpression("[a-z][a-z0-9_.-]{0,63}"), combo
                    )
                )
            combo.lineEdit().editingFinished.connect(
                lambda property_key=key, editor=combo: self._choice_changed(
                    property_key, editor, custom_text=True
                )
            )
        return combo

    def _make_timer_seconds_editor(self, key: str, value: Any) -> QDoubleSpinBox:
        editor = QDoubleSpinBox()
        editor.setObjectName(f"GraphProperty_{key}")
        editor.setProperty("graph_property_key", key)
        editor.setAccessibleName("Seconds before the timer rings")
        editor.setRange(0.001, 86_400.0)
        editor.setDecimals(3)
        editor.setSingleStep(0.25)
        editor.setSuffix(" seconds")
        editor.setKeyboardTracking(False)
        editor.setToolTip(
            "How long to wait before this event rings. Choose more than 0 seconds, "
            "up to one day (86,400 seconds)."
        )
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 1.0
        editor.setValue(min(86_400.0, max(0.001, numeric)))
        editor.setEnabled(not self._read_only)
        editor.editingFinished.connect(
            lambda property_key=key, control=editor: self._commit_property(
                property_key, float(control.value())
            )
        )
        return editor

    def _make_timer_repeat_editor(self, key: str, value: Any) -> QCheckBox:
        editor = QCheckBox("Ring again and again")
        editor.setObjectName(f"GraphProperty_{key}")
        editor.setProperty("graph_property_key", key)
        editor.setAccessibleName("Repeat this timer")
        editor.setToolTip(
            "On: restart the timer after every ring. Off: ring only once each time "
            "the graph binding becomes active."
        )
        editor.setChecked(bool(value))
        editor.setEnabled(not self._read_only)
        editor.toggled.connect(
            lambda checked, property_key=key: self._commit_property(
                property_key, bool(checked)
            )
        )
        return editor

    def _make_cone_editor(self, key: str, value: Any) -> QWidget:
        default_axis = (0.0, 0.0, -1.0) if self.project_kind == "3d" else (1.0, 0.0, 0.0)
        try:
            values = tuple(float(item) for item in value)
        except (TypeError, ValueError):
            values = (*default_axis, 0.7071067690849304)
        if len(values) != 4:
            values = (*default_axis, 0.7071067690849304)
        current_axis = tuple(values[:3])
        current_width = values[3]

        editor = QWidget()
        editor.setObjectName(f"GraphProperty_{key}")
        editor.setProperty("graph_property_key", key)
        editor.setAccessibleName("Facing direction and view width")
        layout = QHBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        direction = QComboBox()
        direction.setObjectName("GraphProperty_cone_direction")
        direction.setAccessibleName("Facing direction")
        direction.setToolTip(
            "Choose a world-space direction. It stays exact and does not depend on the object's rotation."
        )
        choices = _CONE_DIRECTIONS.get(self.project_kind or "2d", _CONE_DIRECTIONS["2d"])
        for axis, label, tooltip in choices:
            direction.addItem(f"Facing: {label}", axis)
            direction.setItemData(direction.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)
        direction_index = direction.findData(current_axis)
        if direction_index < 0:
            direction.addItem("Facing: Custom (kept)", current_axis)
            direction_index = direction.count() - 1
        direction.setCurrentIndex(direction_index)

        width = QComboBox()
        width.setObjectName("GraphProperty_cone_width")
        width.setAccessibleName("View width")
        width.setToolTip(
            "Choose how wide the search view is. The saved value is an exact portable cosine."
        )
        for cosine, label, tooltip in _CONE_WIDTH_CHOICES:
            width.addItem(f"View: {label}", cosine)
            width.setItemData(width.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)
        width_index = width.findData(current_width)
        if width_index < 0:
            width.addItem("View: Custom (kept)", current_width)
            width_index = width.count() - 1
        width.setCurrentIndex(width_index)

        direction.setEnabled(not self._read_only)
        width.setEnabled(not self._read_only)
        layout.addWidget(direction, 1)
        layout.addWidget(width, 1)

        def commit_cone(_index: int = -1) -> None:
            if self._updating or self._read_only:
                return
            axis = direction.currentData()
            cosine = width.currentData()
            if not isinstance(axis, (tuple, list)) or len(axis) != 3:
                return
            self._commit_property(
                key,
                [float(axis[0]), float(axis[1]), float(axis[2]), float(cosine)],
            )

        direction.currentIndexChanged.connect(commit_cone)
        width.currentIndexChanged.connect(commit_cone)
        return editor

    def set_node(self, node: GraphNode | None) -> None:
        self._updating = True
        try:
            self.node = node
            self._editors.clear()
            self._items.clear()
            self.values.clear()
            if node is None:
                self.title.setText("Selected Block Settings")
                self.hint.setText(
                    "Select a block to inspect its values. The running game keeps them read-only."
                    if self._read_only
                    else "Select a block to change its friendly values."
                )
                return
            self.title.setText(node.template.title)
            if not node.properties:
                self.hint.setText("This block has no values to change. Connect its dots to use it.")
                return
            if self._read_only:
                hint = "View-only while the game is running. Stop it to change this block."
            elif node.template.key == "event.timer":
                hint = "Choose when it rings and whether it starts waiting again after each ring."
            elif node.template.key == "event.message":
                hint = "Use the exact same name in Send a Game Message and this listening block."
            elif node.template.key == "query.nearest_in_cone":
                hint = "Choose what to find, how far to look, and the saved Facing and View width."
            elif node.template.key in {
                "value.polar_movement",
                "action.set_polar_movement",
            }:
                hint = (
                    "Choose the object and a friendly movement number. Packed words "
                    "and component names stay hidden."
                )
            elif node.template.key == "action.set_polar_population_visible":
                hint = (
                    "Choose an object with Make Many, then Show or Hide only its "
                    "extra copies. The real object stays visible."
                )
            else:
                hint = "Choose friendly options or double-click an open value. Changes stay undoable."
            self.hint.setText(hint)
            for key, value in node.properties.items():
                if (
                    key == "field"
                    and node.template.key
                    in {"value.polar_movement", "action.set_polar_movement"}
                ):
                    label = "Movement number"
                elif (
                    node.template.key == "action.set_polar_population_visible"
                    and key == "entity"
                ):
                    label = "Make Many object"
                else:
                    label = _PROPERTY_LABELS.get(
                        key, key.replace("_", " ").title()
                    )
                item = QTreeWidgetItem([label, self._display(value)])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                item.setData(1, Qt.ItemDataRole.UserRole, value)
                item.setToolTip(0, f"Engine property: {key}")
                self._items[key] = item
                self.values.addTopLevelItem(item)
                choice_spec = self._choice_spec(node, key, value)
                if node.template.key == "event.timer" and key == "seconds":
                    editor = self._make_timer_seconds_editor(key, value)
                    self._editors[key] = editor
                    self.values.setItemWidget(item, 1, editor)
                    item.setToolTip(1, editor.toolTip())
                elif node.template.key == "event.timer" and key == "repeat":
                    editor = self._make_timer_repeat_editor(key, value)
                    self._editors[key] = editor
                    self.values.setItemWidget(item, 1, editor)
                    item.setToolTip(1, editor.toolTip())
                elif node.template.key == "query.nearest_in_cone" and key == "cone":
                    editor = self._make_cone_editor(key, value)
                    self._editors[key] = editor
                    self.values.setItemWidget(item, 1, editor)
                    item.setToolTip(
                        1,
                        "Facing uses an exact world direction; View width is Narrow, Normal, or Wide.",
                    )
                elif choice_spec is not None:
                    editor = self._make_choice_editor(key, value, choice_spec)
                    self._editors[key] = editor
                    self.values.setItemWidget(item, 1, editor)
                    item.setToolTip(1, choice_spec.tooltip)
                elif not isinstance(value, Mapping) and not self._read_only:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    if key in {"entity", "origin", "source", "target"}:
                        item.setToolTip(1, "Double-click to type a project object ID; custom IDs are allowed")
                    elif key in {"key", "kind"}:
                        item.setToolTip(1, "Double-click to type a custom project name")
                    else:
                        item.setToolTip(1, "Double-click to edit this open-ended value")
                else:
                    item.setToolTip(1, "This advanced mapping is kept safe but hidden here")
            self.values.resizeColumnToContents(0)
        finally:
            self._updating = False

    def _choice_changed(
        self, key: str, combo: QComboBox, *, custom_text: bool
    ) -> None:
        if self._updating or self._read_only or self.node is None:
            return
        original = self.node.properties.get(key)
        if custom_text:
            if (
                combo.currentIndex() >= 0
                and combo.currentText() == combo.itemText(combo.currentIndex())
            ):
                parsed = combo.currentData()
            else:
                parsed = combo.currentText().strip()
            if (
                not parsed
                and (
                    (
                        self.node.template.key
                        in {"query.nearest_tag", "query.nearest_in_cone"}
                        and key == "origin"
                    )
                    or (
                        self.node.template.key
                        in {"action.play_animation", "action.stop_animation"}
                        and key == "entity"
                    )
                )
            ):
                parsed = None
            elif not parsed:
                self._updating = True
                combo.setCurrentText(self._display(original))
                combo.setToolTip("This value cannot be empty; the previous value was kept")
                self._updating = False
                return
            elif (
                self.node.template.key in {"action.emit_event", "event.message"}
                and key in {"kind", "message"}
                and (not isinstance(parsed, str) or _MESSAGE_ID_RE.fullmatch(parsed) is None)
            ):
                self._updating = True
                combo.setCurrentText(self._display(original))
                combo.setToolTip(
                    "Use 1–64 lowercase letters, numbers, dots, dashes, or underscores; "
                    "the first character must be a letter."
                )
                self._updating = False
                return
        else:
            if combo.currentIndex() < 0:
                return
            parsed = combo.currentData()
        self._commit_property(key, parsed)

    def _commit_property(self, key: str, parsed: Any) -> None:
        if self._read_only or self.node is None:
            return
        original = self.node.properties.get(key)
        if parsed == original and type(parsed) is type(original):
            return
        node = self.node
        node.properties[key] = copy.deepcopy(parsed)
        if key == "component" and "field" in node.properties:
            fields = self._component_fields().get(str(parsed))
            if fields is not None and node.properties["field"] not in fields:
                node.properties["field"] = fields[0] if fields else ""
        item = self._items.get(key)
        if item is not None:
            self._updating = True
            item.setData(1, Qt.ItemDataRole.UserRole, copy.deepcopy(parsed))
            item.setText(1, self._display(parsed))
            self._updating = False
        if key == "component":
            self.set_node(node)
        node.update()
        scene = node.scene()
        if isinstance(scene, VisualGraphScene):
            scene.notify_edited()
        self.propertiesEdited.emit()

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or self._read_only or column != 1 or self.node is None:
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
        self._commit_property(key, parsed)


class LastRunPanel(QWidget):
    """Compact, non-editing view of the most recent graph execution."""

    nodeRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(6)
        title = QLabel("Last Run")
        title.setObjectName("PanelTitle")
        self.status = QLabel("Play the game to see its Logic Trail.")
        self.status.setObjectName("MutedLabel")
        self.status.setWordWrap(True)
        self.steps = QTreeWidget()
        self.steps.setObjectName("LogicTraceList")
        self.steps.setHeaderLabels(["#", "Block", "Result"])
        self.steps.setRootIsDecorated(False)
        self.steps.setAlternatingRowColors(True)
        self.steps.setUniformRowHeights(True)
        self.steps.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.steps.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.steps.setMinimumHeight(160)
        self.steps.setColumnWidth(0, 34)
        self.steps.setColumnWidth(1, 104)
        layout.addWidget(title)
        layout.addWidget(self.status)
        layout.addWidget(self.steps, 1)
        self.steps.itemClicked.connect(self._item_clicked)
        self.steps.itemActivated.connect(self._item_clicked)

    def _item_clicked(self, item: QTreeWidgetItem, column: int = 0) -> None:
        del column
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        if node_id:
            self.nodeRequested.emit(str(node_id))


class GraphPage(QWidget):
    graphEdited = Signal(object)
    graphRequested = Signal(str)
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
        self.context_label = QLabel("Project Logic")
        self.context_label.setObjectName("MutedLabel")
        self.context_label.setWordWrap(True)
        self.graph_choice = QComboBox()
        self.graph_choice.setObjectName("LogicGraphChoice")
        self.graph_choice.setToolTip("Choose which Logic Blocks graph belongs on this object")
        self.graph_choice.hide()
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.setToolTip("Removes only the selected block or connection")
        self.frame_button = QPushButton("Show All")
        self.frame_button.setToolTip("Fits every block on screen")
        bar_layout.addWidget(self.context_label, 1)
        bar_layout.addWidget(self.graph_choice)
        bar_layout.addWidget(self.delete_button)
        bar_layout.addWidget(self.frame_button)
        self.palette = NodePalette()
        self.properties = NodePropertiesPanel()
        self.last_run = LastRunPanel()
        self.trace_status = self.last_run.status
        self.last_run_status = self.last_run.status
        self.trace_list = self.last_run.steps
        self.last_run_list = self.last_run.steps
        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.setObjectName("LogicSidebarTabs")
        self.sidebar_tabs.setAccessibleName("Logic tools")
        self.sidebar_tabs.setDocumentMode(True)
        self.sidebar_tabs.addTab(self.palette, "Blocks")
        self.sidebar_tabs.addTab(self.properties, "Settings")
        self.sidebar_tabs.addTab(self.last_run, "Trail")
        self.sidebar_tabs.setTabToolTip(
            self.sidebar_tabs.indexOf(self.palette),
            "Block Picker — find and add a Logic Block",
        )
        self.sidebar_tabs.setTabToolTip(
            self.sidebar_tabs.indexOf(self.properties),
            "Settings — change the selected block",
        )
        self.sidebar_tabs.setTabToolTip(
            self.sidebar_tabs.indexOf(self.last_run),
            "Last Run — inspect the game's Logic Trail",
        )
        self.graph_scene = VisualGraphScene(self)
        self.view = VisualGraphView(self.graph_scene)
        splitter = QSplitter()
        splitter.setObjectName("LogicWorkspaceSplitter")
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setObjectName("LogicSidebar")
        left.setMinimumWidth(260)
        left.setMaximumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.sidebar_tabs)
        splitter.addWidget(left)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 700])
        layout.addWidget(bar)
        layout.addWidget(splitter, 1)
        self.palette.nodeRequested.connect(self.add_template)
        self.delete_button.clicked.connect(self.graph_scene.delete_selected)
        self.frame_button.clicked.connect(self.view.frame_all)
        self.graph_scene.graphEdited.connect(self.graphEdited)
        self.graph_scene.connectionRejected.connect(self.helpRequested)
        self.graph_scene.selectionChanged.connect(self._selection_changed)
        self.last_run.nodeRequested.connect(self.focus_trace_node)
        self.graph_choice.currentIndexChanged.connect(self._graph_choice_changed)
        self._project_kind: str | None = None
        self._read_only = False
        self._context_problem: str | None = None
        self._context_persisted = True
        self._query_default_origin: str | None = None
        self._animation_choices: tuple[tuple[str, str], ...] = ()
        self._polar_population_choices: tuple[tuple[str, str], ...] = ()
        self._owner_id: str | None = None
        self._updating_context = False
        self._trace_snapshot: object | None = None
        self.trace_step_count = 0
        self.trace_count = 0

    def set_project_kind(self, kind: str | None) -> None:
        self._project_kind = kind
        self.palette.set_project_kind(kind)
        self.properties.set_project_kind(kind)

    @property
    def read_only(self) -> bool:
        return self._read_only

    def set_read_only(self, read_only: bool) -> None:
        """Keep the graph inspectable while preventing every editor mutation."""

        self._read_only = bool(read_only)
        self._refresh_editability()

    def _refresh_editability(self) -> None:
        blocked = self._read_only or self._context_problem is not None
        self.graph_scene.set_read_only(blocked)
        self.properties.set_read_only(blocked)
        self.palette.setEnabled(not blocked)
        self.delete_button.setEnabled(not blocked)
        self.graph_choice.setEnabled(not self._read_only)
        if self._read_only:
            tooltip = "Stop the game before deleting logic blocks"
        elif self._context_problem is not None:
            tooltip = self._context_problem
        else:
            tooltip = "Removes only the selected block or connection"
        self.delete_button.setToolTip(
            tooltip
        )

    def set_context(self, context: GraphAuthoringContext) -> None:
        """Show an explicit owner and exact one-of-many bound graph choice."""

        self._context_problem = context.creation_problem
        self._context_persisted = context.persisted
        self._query_default_origin = (
            None if context.owner_id is not None else context.default_origin_id
        )
        self.properties.set_entity_context(
            context.owner_id, context.entity_choices
        )
        self._animation_choices = context.animation_choices
        self.properties.set_animation_context(context.animation_choices)
        self._owner_id = context.owner_id
        self._polar_population_choices = context.polar_population_choices
        self.properties.set_polar_population_context(
            context.polar_population_choices
        )
        self._updating_context = True
        try:
            self.graph_choice.clear()
            for graph_id, label in context.choices:
                self.graph_choice.addItem(label, graph_id)
            index = self.graph_choice.findData(context.active_graph_id)
            if index >= 0:
                self.graph_choice.setCurrentIndex(index)
            self.graph_choice.setVisible(len(context.choices) > 1)
        finally:
            self._updating_context = False

        if context.creation_problem is not None:
            message = context.creation_problem
        elif not context.persisted:
            message = "Pick a block to give this object its own logic."
        elif len(context.choices) > 1:
            message = "Choose one of this object's Logic Blocks graphs."
        else:
            message = "Drag from one dot to another to make the game flow."
        self.context_label.setText(f"{context.owner_label} — {message}")
        self.context_label.setToolTip(message)
        self.load_data(context.graph)
        self._refresh_editability()

    def _graph_choice_changed(self, index: int) -> None:
        if self._updating_context or index < 0:
            return
        graph_id = self.graph_choice.itemData(index)
        if isinstance(graph_id, str) and graph_id:
            self.graphRequested.emit(graph_id)

    def _clear_trace_presentation(self, *, drop_snapshot: bool = True) -> None:
        for node in self.graph_scene.nodes.values():
            node.clear_trace()
        self.trace_list.clear()
        self.trace_status.setText("Play the game to see its Logic Trail.")
        self.trace_status.setToolTip("")
        self.trace_step_count = 0
        self.trace_count = 0
        if drop_snapshot:
            self._trace_snapshot = None

    def show_trace(self, snapshot: object | None) -> bool:
        """Present a runtime trace when it belongs to the displayed graph.

        Trace records may be frozen dataclasses or plain mappings. Presentation
        state is intentionally never copied into graph properties or metadata.
        """

        if snapshot is None:
            self._clear_trace_presentation()
            return True

        current_graph_id = str(self.graph_scene.property("graph_id") or "scene_logic")
        snapshot_graph_id = str(_record_value(snapshot, "graph_id", ""))
        if snapshot_graph_id != current_graph_id:
            return False

        raw_trace = _record_value(snapshot, "trace", ())
        if isinstance(raw_trace, Mapping):
            entries = tuple(raw_trace.values())
        elif isinstance(raw_trace, Iterable) and not isinstance(raw_trace, (str, bytes)):
            entries = tuple(raw_trace)
        else:
            entries = ()

        self._clear_trace_presentation(drop_snapshot=False)
        self._trace_snapshot = snapshot
        error_count = 0
        for order, entry in enumerate(entries, 1):
            node_id = str(_record_value(entry, "node_id", ""))
            node = self.graph_scene.nodes.get(node_id)
            try:
                step = int(_record_value(entry, "step", order))
            except (TypeError, ValueError):
                step = order
            if node is not None:
                node.add_trace_entry(entry, order)

            node_type = str(_record_value(entry, "node_type", ""))
            friendly = (
                node.template.title
                if node is not None
                else _FRIENDLY_NODE_NAMES.get(
                    node_type,
                    (node_type.replace(".", " ").replace("_", " ").title() or "Unknown Block", ""),
                )[0]
            )
            summary = _trace_entry_summary(entry)
            item = QTreeWidgetItem([str(step), friendly, summary])
            item.setData(0, Qt.ItemDataRole.UserRole, node_id)

            status = str(_record_value(entry, "status", "ok") or "ok").casefold()
            error = _record_value(entry, "error")
            has_error = bool(error) or status in _TRACE_ERROR_STATUSES
            if has_error:
                brush = QBrush(QColor("#ff8fa3"))
                error_count += 1
            elif status in _TRACE_SKIPPED_STATUSES:
                brush = QBrush(QColor("#93a5b8"))
            else:
                brush = QBrush(QColor("#82e0b3"))
            for column in range(3):
                item.setForeground(column, brush)

            details = []
            flow_input = _record_value(entry, "flow_input")
            if flow_input:
                details.append("Entered through: " + str(flow_input).replace("_", " ").title())
            inputs = _record_value(entry, "inputs", {})
            if isinstance(inputs, Mapping) and inputs:
                details.append("Inputs: " + _compact_trace_value(inputs, limit=150))
            outputs = _record_value(entry, "outputs", {})
            if isinstance(outputs, Mapping) and outputs:
                details.append("Outputs: " + _compact_trace_value(outputs, limit=150))
            if error:
                details.append("Error: " + _compact_trace_value(error, limit=150))
            tooltip = "\n".join(details) or summary
            for column in range(3):
                item.setToolTip(column, tooltip)
            self.trace_list.addTopLevelItem(item)

        self.trace_step_count = len(entries)
        self.trace_count = self.trace_step_count
        completed = bool(_record_value(snapshot, "completed", False))
        if error_count:
            state = "Stopped with an error"
        elif completed:
            state = "Finished"
        else:
            state = "Stopped early"
        noun = "step" if self.trace_step_count == 1 else "steps"
        trigger = _record_value(snapshot, "trigger", "")
        trigger_text = _compact_trace_value(trigger, limit=38) if trigger not in (None, "") else ""
        status_text = f"{state} • {self.trace_step_count} {noun}"
        if trigger_text:
            status_text += " • " + trigger_text.replace("_", " ").title()
        self.trace_status.setText(status_text)
        owner_id = _record_value(snapshot, "owner_id", "")
        sequence = _record_value(snapshot, "sequence", "")
        status_details = [f"Graph: {snapshot_graph_id}"]
        if owner_id not in (None, ""):
            status_details.append(f"Owner: {owner_id}")
        if sequence not in (None, ""):
            status_details.append(f"Run: {sequence}")
        self.trace_status.setToolTip("\n".join(status_details))
        self.trace_list.resizeColumnToContents(0)
        self.trace_list.resizeColumnToContents(1)
        return True

    def focus_trace_node(self, node_id: str) -> bool:
        """Select and center the block referenced by one Last Run row."""

        node = self.graph_scene.nodes.get(str(node_id))
        if node is None:
            return False
        self.graph_scene.clearSelection()
        node.setSelected(True)
        self.view.centerOn(node)
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def load_data(self, data: Mapping[str, Any]) -> None:
        previous_graph_id = str(self.graph_scene.property("graph_id") or "")
        next_graph_id = str(data.get("id", "scene_logic"))
        selected_node_id = next(
            (
                item.node_id for item in self.graph_scene.selectedItems()
                if isinstance(item, GraphNode)
            ),
            None,
        )
        self.graph_scene.load_data(data)
        if previous_graph_id == next_graph_id and selected_node_id in self.graph_scene.nodes:
            self.graph_scene.clearSelection()
            self.graph_scene.nodes[selected_node_id].setSelected(True)
        if self._trace_snapshot is not None:
            trace_graph_id = str(_record_value(self._trace_snapshot, "graph_id", ""))
            if trace_graph_id == next_graph_id:
                self.show_trace(self._trace_snapshot)
            else:
                self._clear_trace_presentation()
        elif previous_graph_id != next_graph_id:
            self._clear_trace_presentation()
        if self.graph_scene.nodes:
            self.view.frame_all()
        else:
            self.view.resetTransform()
            self.view.centerOn(0, 0)

    def add_template(self, key: str) -> None:
        if self._read_only:
            return
        if self._context_problem is not None:
            self.helpRequested.emit(self._context_problem)
            return
        template = TEMPLATE_BY_KEY.get(key)
        if template is None:
            return
        center = self.view.mapToScene(self.view.viewport().rect().center())
        offset = QPointF(len(self.graph_scene.nodes) % 4 * 18, len(self.graph_scene.nodes) % 3 * 18)
        properties = None
        if self._project_kind == "3d" and key == "action.set_component":
            properties = {"entity": None, "component": "transform", "field": "translation", "value": [0, 0, 0]}
        elif key in {"query.nearest_tag", "query.nearest_in_cone"}:
            properties = {"origin": self._query_default_origin}
            if key == "query.nearest_in_cone":
                direction = [0.0, 0.0, -1.0] if self._project_kind == "3d" else [1.0, 0.0, 0.0]
                properties["cone"] = [
                    direction[0],
                    direction[1],
                    direction[2],
                    0.7071067690849304,
                ]
        elif key == "action.play_animation":
            properties = {
                "entity": None,
                "clip": (
                    self._animation_choices[0][0]
                    if self._animation_choices
                    else "main"
                ),
                "restart": True,
            }
        elif key == "action.stop_animation":
            properties = {"entity": None, "reset": True}
        elif key == "action.set_polar_population_visible":
            owner_is_prototype = any(
                entity_id == self._owner_id
                for entity_id, _label in self._polar_population_choices
            )
            properties = {
                "entity": (
                    None
                    if owner_is_prototype
                    else (
                        self._polar_population_choices[0][0]
                        if self._polar_population_choices
                        else None
                    )
                ),
                "visible": True,
            }
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
        if node is not None:
            self.sidebar_tabs.setCurrentWidget(self.properties)


__all__ = ["GraphPage", "NODE_TEMPLATES", "NodePalette", "VisualGraphScene"]
