"""Deterministic 2D game world and pragmatic component runtime.

This module is deliberately dependency-free. It supports headless simulation and
uses the same serializable component records consumed by the HTML5 exporter.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

from .collision2d import (
    AABB2,
    Circle2,
    CollisionFilter,
    CollisionManifold,
    ConvexPolygon2,
    Shape2D,
    SpatialHash2D,
    add2,
    collide,
    dot2,
    length2,
    normalize2,
    scale2,
    shape_bounds,
    shape_from_dict,
    sub2,
)
from .game_input import InputFrame

Vec2 = tuple[float, float]


def _normalize_json_numbers(value: Any) -> Any:
    """Canonicalize JSON numbers so mathematically equal values hash identically.

    Python constructors naturally accept both ``1`` and ``1.0`` for scalar game
    values. JSON preserves that spelling distinction even though the runtime does
    not. Normalizing integral floats avoids save/load and project round-trip hash
    drift while preserving all non-integral values.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        if value == 0.0:
            return 0
        return int(value) if value.is_integer() else value
    if isinstance(value, int | str):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_normalize_json_numbers(item) for item in value]
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(_normalize_json_numbers(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _vec2(value: Sequence[float]) -> Vec2:
    if len(value) != 2:
        raise ValueError("expected a two-dimensional vector")
    result = (float(value[0]), float(value[1]))
    if not all(math.isfinite(v) for v in result):
        raise ValueError("vector values must be finite")
    return result


def _rotate(point: Sequence[float], angle: float) -> Vec2:
    c, s = math.cos(angle), math.sin(angle)
    return float(point[0]) * c - float(point[1]) * s, float(point[0]) * s + float(point[1]) * c


@dataclass
class Transform2D:
    position: Vec2 = (0.0, 0.0)
    rotation: float = 0.0
    scale: Vec2 = (1.0, 1.0)

    def validate(self) -> None:
        self.position = _vec2(self.position)
        self.scale = _vec2(self.scale)
        self.rotation = float(self.rotation)
        if not math.isfinite(self.rotation):
            raise ValueError("rotation must be finite")
        if abs(self.scale[0]) <= 1.0e-12 or abs(self.scale[1]) <= 1.0e-12:
            raise ValueError("transform scale components must be non-zero")


@dataclass
class Body2D:
    body_type: str = "dynamic"
    velocity: Vec2 = (0.0, 0.0)
    angular_velocity: float = 0.0
    acceleration: Vec2 = (0.0, 0.0)
    force: Vec2 = (0.0, 0.0)
    mass: float = 1.0
    damping: float = 0.0
    gravity_scale: float = 1.0
    restitution: float = 0.0
    friction: float = 0.2
    max_speed: float | None = None
    fixed_rotation: bool = False

    def validate(self) -> None:
        if self.body_type not in {"dynamic", "kinematic", "static"}:
            raise ValueError("body_type must be dynamic, kinematic or static")
        self.velocity = _vec2(self.velocity)
        self.acceleration = _vec2(self.acceleration)
        self.force = _vec2(self.force)
        for value, name in (
            (self.angular_velocity, "angular_velocity"),
            (self.mass, "mass"),
            (self.damping, "damping"),
            (self.gravity_scale, "gravity_scale"),
            (self.restitution, "restitution"),
            (self.friction, "friction"),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.body_type == "dynamic" and self.mass <= 0:
            raise ValueError("dynamic body mass must be positive")
        if self.damping < 0:
            raise ValueError("damping must be non-negative")
        if not 0 <= self.restitution <= 1 or not 0 <= self.friction <= 1:
            raise ValueError("restitution and friction must be in [0, 1]")
        if self.max_speed is not None and (not math.isfinite(self.max_speed) or self.max_speed <= 0):
            raise ValueError("max_speed must be positive and finite")

    @property
    def inverse_mass(self) -> float:
        return 1.0 / self.mass if self.body_type == "dynamic" else 0.0


@dataclass
class Collider2D:
    shape: Shape2D = field(default_factory=lambda: Circle2((0.0, 0.0), 0.5))
    filter: CollisionFilter = field(default_factory=CollisionFilter)
    offset: Vec2 = (0.0, 0.0)
    enabled: bool = True
    tag: str = ""

    def validate(self) -> None:
        self.offset = _vec2(self.offset)
        shape_bounds(self.shape)
        if not isinstance(self.filter, CollisionFilter):
            raise TypeError("filter must be CollisionFilter")


@dataclass
class VectorRenderer2D:
    asset_id: str
    z_index: int = 0
    visible: bool = True
    opacity: float = 1.0
    tint: str = "#ffffff"

    def validate(self) -> None:
        if not self.asset_id:
            raise ValueError("renderer asset_id is required")
        if not 0 <= self.opacity <= 1:
            raise ValueError("renderer opacity must be in [0, 1]")
        if not self.tint:
            raise ValueError("renderer tint is required")


@dataclass
class Camera2D:
    position: Vec2 = (0.0, 0.0)
    zoom: float = 1.0
    rotation: float = 0.0
    viewport: Vec2 = (960.0, 540.0)
    follow_entity: str | None = None
    follow_smoothing: float = 8.0
    bounds: AABB2 | None = None

    def validate(self) -> None:
        self.position = _vec2(self.position)
        self.viewport = _vec2(self.viewport)
        if self.viewport[0] <= 0 or self.viewport[1] <= 0:
            raise ValueError("camera viewport must be positive")
        if not math.isfinite(self.zoom) or self.zoom <= 0:
            raise ValueError("camera zoom must be positive and finite")
        if not math.isfinite(self.rotation):
            raise ValueError("camera rotation must be finite")
        if self.follow_smoothing < 0 or not math.isfinite(self.follow_smoothing):
            raise ValueError("follow_smoothing must be finite and non-negative")

    def update(self, world: "GameWorld", dt: float) -> None:
        if self.follow_entity is None or self.follow_entity not in world.entities:
            return
        transform = world.get(self.follow_entity, Transform2D)
        if transform is None:
            return
        alpha = 1.0 if self.follow_smoothing <= 0 else 1.0 - math.exp(-self.follow_smoothing * dt)
        self.position = (
            self.position[0] + (transform.position[0] - self.position[0]) * alpha,
            self.position[1] + (transform.position[1] - self.position[1]) * alpha,
        )
        if self.bounds is not None:
            half = (self.viewport[0] * 0.5 / self.zoom, self.viewport[1] * 0.5 / self.zoom)
            min_x = self.bounds.minimum[0] + half[0]
            max_x = self.bounds.maximum[0] - half[0]
            min_y = self.bounds.minimum[1] + half[1]
            max_y = self.bounds.maximum[1] - half[1]
            x = (self.bounds.minimum[0] + self.bounds.maximum[0]) * 0.5 if min_x > max_x else max(min_x, min(max_x, self.position[0]))
            y = (self.bounds.minimum[1] + self.bounds.maximum[1]) * 0.5 if min_y > max_y else max(min_y, min(max_y, self.position[1]))
            self.position = (x, y)

    def world_to_screen(self, point: Sequence[float]) -> Vec2:
        local = sub2(point, self.position)
        local = _rotate(local, -self.rotation)
        return self.viewport[0] * 0.5 + local[0] * self.zoom, self.viewport[1] * 0.5 + local[1] * self.zoom

    def screen_to_world(self, point: Sequence[float]) -> Vec2:
        local = ((float(point[0]) - self.viewport[0] * 0.5) / self.zoom, (float(point[1]) - self.viewport[1] * 0.5) / self.zoom)
        return add2(self.position, _rotate(local, self.rotation))


@dataclass
class Lifetime2D:
    remaining: float

    def validate(self) -> None:
        if not math.isfinite(self.remaining) or self.remaining < 0:
            raise ValueError("lifetime remaining must be finite and non-negative")


@dataclass
class Health2D:
    current: float
    maximum: float
    invulnerability: float = 0.0
    invulnerable_remaining: float = 0.0

    def validate(self) -> None:
        if not math.isfinite(self.maximum) or self.maximum <= 0:
            raise ValueError("health maximum must be positive and finite")
        if not math.isfinite(self.current):
            raise ValueError("health current must be finite")
        self.current = max(0.0, min(self.maximum, self.current))
        if self.invulnerability < 0 or self.invulnerable_remaining < 0:
            raise ValueError("invulnerability values must be non-negative")


@dataclass
class BoundsConstraint2D:
    bounds: AABB2
    mode: str = "clamp"

    def validate(self) -> None:
        if self.mode not in {"clamp", "bounce", "wrap"}:
            raise ValueError("bounds mode must be clamp, bounce or wrap")


@dataclass
class PlayerController2D:
    x_action: str = "move_x"
    y_action: str = "move_y"
    speed: float = 220.0
    dash_action: str | None = "dash"
    dash_speed: float = 520.0
    dash_duration: float = 0.12
    dash_cooldown: float = 0.65
    dash_remaining: float = 0.0
    cooldown_remaining: float = 0.0
    last_direction: Vec2 = (1.0, 0.0)

    def validate(self) -> None:
        if not self.x_action or not self.y_action:
            raise ValueError("movement actions are required")
        if self.speed < 0 or self.dash_speed < 0:
            raise ValueError("controller speeds must be non-negative")
        if self.dash_duration < 0 or self.dash_cooldown < 0:
            raise ValueError("dash timings must be non-negative")
        self.last_direction = normalize2(self.last_direction)


@dataclass
class Collectible2D:
    points: int = 1
    state_key: str = "score"
    sound: str | None = None
    destroy_on_collect: bool = True

    def validate(self) -> None:
        if self.points < 0:
            raise ValueError("collectible points must be non-negative")
        if not self.state_key:
            raise ValueError("collectible state_key is required")


@dataclass
class Hazard2D:
    damage: float = 1.0
    knockback: float = 220.0
    cooldown: float = 0.5
    sound: str | None = None
    last_hits: dict[str, float] = field(default_factory=dict)

    def validate(self) -> None:
        if self.damage < 0 or self.knockback < 0 or self.cooldown < 0:
            raise ValueError("hazard values must be non-negative")


@dataclass
class GameEvent:
    sequence: int
    tick: int
    time: float
    kind: str
    source: str | None = None
    target: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class GameEntity:
    id: str
    tags: set[str] = field(default_factory=set)
    components: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("entity id is required")
        for component in self.components.values():
            validate = getattr(component, "validate", None)
            if callable(validate):
                validate()


_COMPONENT_NAMES: dict[type, str] = {
    Transform2D: "transform",
    Body2D: "body",
    Collider2D: "collider",
    VectorRenderer2D: "vector_renderer",
    Camera2D: "camera",
    Lifetime2D: "lifetime",
    Health2D: "health",
    BoundsConstraint2D: "bounds_constraint",
    PlayerController2D: "player_controller",
    Collectible2D: "collectible",
    Hazard2D: "hazard",
}
_COMPONENT_TYPES = {name: kind for kind, name in _COMPONENT_NAMES.items()}


def component_name(component_or_type: Any) -> str:
    kind = component_or_type if isinstance(component_or_type, type) else type(component_or_type)
    return _COMPONENT_NAMES.get(kind, kind.__name__)


def _shape_to_dict(shape: Shape2D) -> dict[str, Any]:
    return shape.to_dict()


def _encode_value(value: Any) -> Any:
    if isinstance(value, (AABB2, Circle2, ConvexPolygon2)):
        return _shape_to_dict(value)
    if isinstance(value, CollisionFilter):
        return {"layer": value.layer, "mask": value.mask, "sensor": value.sensor}
    if is_dataclass(value):
        return {field_.name: _encode_value(getattr(value, field_.name)) for field_ in fields(value)}
    if isinstance(value, tuple):
        return [_encode_value(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_encode_value(v) for v in value)
    if isinstance(value, Mapping):
        return {str(k): _encode_value(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_encode_value(v) for v in value]
    return value


def component_to_dict(component: Any) -> dict[str, Any]:
    if isinstance(component, Collider2D):
        return {
            "shape": _shape_to_dict(component.shape),
            "filter": _encode_value(component.filter),
            "offset": list(component.offset),
            "enabled": component.enabled,
            "tag": component.tag,
        }
    if isinstance(component, BoundsConstraint2D):
        return {"bounds": component.bounds.to_dict(), "mode": component.mode}
    if is_dataclass(component):
        return _encode_value(component)
    if isinstance(component, Mapping):
        return copy.deepcopy(dict(component))
    raise TypeError(f"component {type(component).__name__} is not serializable")


def component_from_dict(name: str, data: Mapping[str, Any]) -> Any:
    if name == "transform":
        return Transform2D(tuple(data.get("position", (0, 0))), float(data.get("rotation", 0)), tuple(data.get("scale", (1, 1))))
    if name == "body":
        return Body2D(
            str(data.get("body_type", "dynamic")),
            tuple(data.get("velocity", (0, 0))),
            float(data.get("angular_velocity", 0)),
            tuple(data.get("acceleration", (0, 0))),
            tuple(data.get("force", (0, 0))),
            float(data.get("mass", 1)),
            float(data.get("damping", 0)),
            float(data.get("gravity_scale", 1)),
            float(data.get("restitution", 0)),
            float(data.get("friction", 0.2)),
            None if data.get("max_speed") is None else float(data["max_speed"]),
            bool(data.get("fixed_rotation", False)),
        )
    if name == "collider":
        filter_data = data.get("filter", {})
        return Collider2D(
            shape_from_dict(dict(data.get("shape", {"type": "circle", "radius": 0.5}))),
            CollisionFilter(int(filter_data.get("layer", 1)), int(filter_data.get("mask", 0xFFFFFFFF)), bool(filter_data.get("sensor", False))),
            tuple(data.get("offset", (0, 0))),
            bool(data.get("enabled", True)),
            str(data.get("tag", "")),
        )
    if name == "vector_renderer":
        return VectorRenderer2D(str(data["asset_id"]), int(data.get("z_index", 0)), bool(data.get("visible", True)), float(data.get("opacity", 1)), str(data.get("tint", "#ffffff")))
    if name == "camera":
        bounds_data = data.get("bounds")
        return Camera2D(
            tuple(data.get("position", (0, 0))),
            float(data.get("zoom", 1)),
            float(data.get("rotation", 0)),
            tuple(data.get("viewport", (960, 540))),
            data.get("follow_entity"),
            float(data.get("follow_smoothing", 8)),
            None if bounds_data is None else shape_from_dict(dict(bounds_data)),  # type: ignore[arg-type]
        )
    if name == "lifetime":
        return Lifetime2D(float(data["remaining"]))
    if name == "health":
        return Health2D(float(data["current"]), float(data["maximum"]), float(data.get("invulnerability", 0)), float(data.get("invulnerable_remaining", 0)))
    if name == "bounds_constraint":
        bounds = shape_from_dict(dict(data["bounds"]))
        if not isinstance(bounds, AABB2):
            raise ValueError("bounds_constraint requires an AABB")
        return BoundsConstraint2D(bounds, str(data.get("mode", "clamp")))
    if name == "player_controller":
        return PlayerController2D(
            str(data.get("x_action", "move_x")),
            str(data.get("y_action", "move_y")),
            float(data.get("speed", 220)),
            data.get("dash_action", "dash"),
            float(data.get("dash_speed", 520)),
            float(data.get("dash_duration", 0.12)),
            float(data.get("dash_cooldown", 0.65)),
            float(data.get("dash_remaining", 0)),
            float(data.get("cooldown_remaining", 0)),
            tuple(data.get("last_direction", (1, 0))),
        )
    if name == "collectible":
        return Collectible2D(int(data.get("points", 1)), str(data.get("state_key", "score")), data.get("sound"), bool(data.get("destroy_on_collect", True)))
    if name == "hazard":
        return Hazard2D(float(data.get("damage", 1)), float(data.get("knockback", 220)), float(data.get("cooldown", 0.5)), data.get("sound"), {str(k): float(v) for k, v in data.get("last_hits", {}).items()})
    return copy.deepcopy(dict(data))


SystemCallback = Callable[["GameWorld", float, InputFrame | None], None]


@dataclass(order=True)
class _SystemEntry:
    priority: int
    name: str
    callback: SystemCallback = field(compare=False)


class GameWorld:
    PHASES = ("input", "pre_physics", "post_physics", "update", "late")

    def __init__(self, fixed_dt: float = 1.0 / 60.0, gravity: Sequence[float] = (0.0, 0.0), broadphase_cell_size: float = 96.0):
        if not math.isfinite(fixed_dt) or fixed_dt <= 0:
            raise ValueError("fixed_dt must be positive and finite")
        self.fixed_dt = float(fixed_dt)
        self.gravity = _vec2(gravity)
        self.tick = 0
        self.time = 0.0
        self.entities: dict[str, GameEntity] = {}
        self.state: dict[str, Any] = {"score": 0}
        self.events: list[GameEvent] = []
        self._event_sequence = 0
        self._step_events: list[GameEvent] = []
        self._contacts: dict[tuple[str, str], CollisionManifold] = {}
        self._systems: dict[str, list[_SystemEntry]] = {phase: [] for phase in self.PHASES}
        self._listeners: dict[str, list[Callable[[GameEvent], None]]] = {}
        self._pending_despawn: set[str] = set()
        self._stepping = False
        self._next_entity = 1
        self._broadphase_cell_size = float(broadphase_cell_size)

    def spawn(
        self,
        entity_id: str | None = None,
        *,
        tags: Iterable[str] = (),
        components: Iterable[Any] | Mapping[str, Any] = (),
        metadata: Mapping[str, Any] | None = None,
        emit_event: bool = True,
    ) -> GameEntity:
        if entity_id is None:
            while (candidate := f"e{self._next_entity:06d}") in self.entities:
                self._next_entity += 1
            entity_id = candidate
            self._next_entity += 1
        if entity_id in self.entities:
            raise ValueError(f"entity already exists: {entity_id}")
        entity = GameEntity(entity_id, set(str(tag) for tag in tags), {}, True, dict(metadata or {}))
        self.entities[entity_id] = entity
        try:
            if isinstance(components, Mapping):
                for name, component in components.items():
                    self.add_component(entity_id, component_from_dict(name, component) if isinstance(component, Mapping) else component, name)
            else:
                for component in components:
                    self.add_component(entity_id, component)
            entity.validate()
        except Exception:
            del self.entities[entity_id]
            raise
        if emit_event:
            self.emit("entity_spawned", source=entity_id)
        return entity

    def despawn(self, entity_id: str, *, emit_event: bool = True) -> None:
        if entity_id not in self.entities:
            raise KeyError(entity_id)
        if self._stepping:
            self._pending_despawn.add(entity_id)
            return
        del self.entities[entity_id]
        self._contacts = {pair: manifold for pair, manifold in self._contacts.items() if entity_id not in pair}
        if emit_event:
            self.emit("entity_despawned", source=entity_id)

    def add_component(self, entity_id: str, component: Any, name: str | None = None, replace_existing: bool = False) -> None:
        entity = self.entities[entity_id]
        component_key = name or component_name(component)
        if component_key in entity.components and not replace_existing:
            raise ValueError(f"entity {entity_id} already has component {component_key}")
        validate = getattr(component, "validate", None)
        if callable(validate):
            validate()
        entity.components[component_key] = component

    def remove_component(self, entity_id: str, component_or_name: type | str) -> Any:
        name = component_or_name if isinstance(component_or_name, str) else component_name(component_or_name)
        return self.entities[entity_id].components.pop(name)

    def get(self, entity_id: str, component_or_name: type | str, default: Any = None) -> Any:
        name = component_or_name if isinstance(component_or_name, str) else component_name(component_or_name)
        return self.entities[entity_id].components.get(name, default)

    def require(self, entity_id: str, component_or_name: type | str) -> Any:
        component = self.get(entity_id, component_or_name)
        if component is None:
            name = component_or_name if isinstance(component_or_name, str) else component_name(component_or_name)
            raise KeyError(f"entity {entity_id} lacks component {name}")
        return component

    def query(self, *component_types: type | str, tags: Iterable[str] = (), active_only: bool = True) -> tuple[GameEntity, ...]:
        names = tuple(item if isinstance(item, str) else component_name(item) for item in component_types)
        required_tags = set(tags)
        return tuple(
            entity
            for entity_id in sorted(self.entities)
            if (entity := self.entities[entity_id])
            and (entity.active or not active_only)
            and required_tags.issubset(entity.tags)
            and all(name in entity.components for name in names)
        )

    def add_system(self, callback: SystemCallback, *, phase: str = "update", priority: int = 0, name: str | None = None) -> None:
        if phase not in self._systems:
            raise ValueError(f"unknown system phase: {phase}")
        system_name = name or getattr(callback, "__name__", "system")
        self._systems[phase].append(_SystemEntry(int(priority), system_name, callback))
        self._systems[phase].sort()

    def on(self, kind: str, listener: Callable[[GameEvent], None]) -> None:
        self._listeners.setdefault(kind, []).append(listener)

    def emit(self, kind: str, source: str | None = None, target: str | None = None, payload: Mapping[str, Any] | None = None) -> GameEvent:
        self._event_sequence += 1
        event = GameEvent(self._event_sequence, self.tick, self.time, kind, source, target, copy.deepcopy(dict(payload or {})))
        self.events.append(event)
        self._step_events.append(event)
        for listener in (*self._listeners.get(kind, ()), *self._listeners.get("*", ())):
            listener(event)
        return event

    def drain_events(self) -> tuple[GameEvent, ...]:
        events = tuple(self._step_events)
        self._step_events.clear()
        return events

    def apply_force(self, entity_id: str, force: Sequence[float]) -> None:
        body: Body2D = self.require(entity_id, Body2D)
        body.force = add2(body.force, force)

    def world_shape(self, entity_id: str) -> Shape2D:
        transform: Transform2D = self.require(entity_id, Transform2D)
        collider: Collider2D = self.require(entity_id, Collider2D)
        offset = _rotate((collider.offset[0] * transform.scale[0], collider.offset[1] * transform.scale[1]), transform.rotation)
        origin = add2(transform.position, offset)
        shape = collider.shape
        if isinstance(shape, Circle2):
            center_offset = _rotate((shape.center[0] * transform.scale[0], shape.center[1] * transform.scale[1]), transform.rotation)
            radius = shape.radius * max(abs(transform.scale[0]), abs(transform.scale[1]))
            return Circle2(add2(origin, center_offset), radius)
        if isinstance(shape, AABB2):
            points = (
                shape.minimum,
                (shape.maximum[0], shape.minimum[1]),
                shape.maximum,
                (shape.minimum[0], shape.maximum[1]),
            )
        else:
            points = shape.points
        transformed = tuple(
            add2(origin, _rotate((point[0] * transform.scale[0], point[1] * transform.scale[1]), transform.rotation))
            for point in points
        )
        if abs(transform.rotation) <= 1.0e-12 and isinstance(shape, AABB2):
            return AABB2(
                (min(p[0] for p in transformed), min(p[1] for p in transformed)),
                (max(p[0] for p in transformed), max(p[1] for p in transformed)),
            )
        return ConvexPolygon2(transformed)

    def _run_systems(self, phase: str, dt: float, input_frame: InputFrame | None) -> None:
        for entry in self._systems[phase]:
            entry.callback(self, dt, input_frame)

    def _controller_step(self, dt: float, input_frame: InputFrame | None) -> None:
        if input_frame is None:
            return
        for entity in self.query(Transform2D, PlayerController2D):
            controller: PlayerController2D = entity.components["player_controller"]
            controller.cooldown_remaining = max(0.0, controller.cooldown_remaining - dt)
            controller.dash_remaining = max(0.0, controller.dash_remaining - dt)
            direction = input_frame.vector(controller.x_action, controller.y_action)
            if length2(direction) > 1.0e-6:
                direction = normalize2(direction)
                controller.last_direction = direction
            if controller.dash_remaining > 0:
                velocity = scale2(controller.last_direction, controller.dash_speed)
            else:
                velocity = scale2(direction, controller.speed)
                if controller.dash_action and controller.cooldown_remaining <= 0 and input_frame.pressed(controller.dash_action):
                    controller.dash_remaining = controller.dash_duration
                    controller.cooldown_remaining = controller.dash_cooldown
                    velocity = scale2(controller.last_direction, controller.dash_speed)
                    self.emit("dash", source=entity.id)
            body: Body2D | None = entity.components.get("body")
            if body is not None:
                body.velocity = velocity
            else:
                transform: Transform2D = entity.components["transform"]
                transform.position = add2(transform.position, scale2(velocity, dt))

    def _physics_step(self, dt: float) -> None:
        for entity in self.query(Transform2D, Body2D):
            transform: Transform2D = entity.components["transform"]
            body: Body2D = entity.components["body"]
            if body.body_type == "static":
                body.force = (0.0, 0.0)
                continue
            if body.body_type == "dynamic":
                acceleration = add2(body.acceleration, scale2(self.gravity, body.gravity_scale))
                acceleration = add2(acceleration, scale2(body.force, body.inverse_mass))
                body.velocity = add2(body.velocity, scale2(acceleration, dt))
                if body.damping > 0:
                    body.velocity = scale2(body.velocity, math.exp(-body.damping * dt))
                if body.max_speed is not None and length2(body.velocity) > body.max_speed:
                    body.velocity = scale2(normalize2(body.velocity), body.max_speed)
            transform.position = add2(transform.position, scale2(body.velocity, dt))
            if not body.fixed_rotation:
                transform.rotation += body.angular_velocity * dt
            body.force = (0.0, 0.0)

    def _bounds_step(self) -> None:
        for entity in self.query(Transform2D, BoundsConstraint2D):
            transform: Transform2D = entity.components["transform"]
            constraint: BoundsConstraint2D = entity.components["bounds_constraint"]
            bounds = constraint.bounds
            body: Body2D | None = entity.components.get("body")
            x, y = transform.position
            if constraint.mode == "wrap":
                if x < bounds.minimum[0]:
                    x = bounds.maximum[0]
                elif x > bounds.maximum[0]:
                    x = bounds.minimum[0]
                if y < bounds.minimum[1]:
                    y = bounds.maximum[1]
                elif y > bounds.maximum[1]:
                    y = bounds.minimum[1]
            else:
                clamped_x = max(bounds.minimum[0], min(bounds.maximum[0], x))
                clamped_y = max(bounds.minimum[1], min(bounds.maximum[1], y))
                if body is not None and constraint.mode == "bounce":
                    vx, vy = body.velocity
                    if clamped_x != x:
                        vx = -vx * body.restitution
                    if clamped_y != y:
                        vy = -vy * body.restitution
                    body.velocity = (vx, vy)
                x, y = clamped_x, clamped_y
            transform.position = (x, y)

    def _resolve_contact(self, a_id: str, b_id: str, manifold: CollisionManifold) -> None:
        a_body: Body2D | None = self.get(a_id, Body2D)
        b_body: Body2D | None = self.get(b_id, Body2D)
        inv_a = 0.0 if a_body is None else a_body.inverse_mass
        inv_b = 0.0 if b_body is None else b_body.inverse_mass
        total_inv = inv_a + inv_b
        if total_inv <= 0:
            return
        correction = scale2(manifold.normal, max(0.0, manifold.penetration - 1.0e-6) * 0.8 / total_inv)
        if inv_a > 0:
            transform: Transform2D = self.require(a_id, Transform2D)
            transform.position = sub2(transform.position, scale2(correction, inv_a))
        if inv_b > 0:
            transform = self.require(b_id, Transform2D)
            transform.position = add2(transform.position, scale2(correction, inv_b))

        velocity_a = (0.0, 0.0) if a_body is None else a_body.velocity
        velocity_b = (0.0, 0.0) if b_body is None else b_body.velocity
        relative = sub2(velocity_b, velocity_a)
        velocity_along_normal = dot2(relative, manifold.normal)
        if velocity_along_normal >= 0:
            return
        restitution = min(a_body.restitution if a_body else 0.0, b_body.restitution if b_body else 0.0)
        impulse_magnitude = -(1.0 + restitution) * velocity_along_normal / total_inv
        impulse = scale2(manifold.normal, impulse_magnitude)
        if a_body is not None and inv_a > 0:
            a_body.velocity = sub2(a_body.velocity, scale2(impulse, inv_a))
        if b_body is not None and inv_b > 0:
            b_body.velocity = add2(b_body.velocity, scale2(impulse, inv_b))

        relative = sub2((0.0, 0.0) if b_body is None else b_body.velocity, (0.0, 0.0) if a_body is None else a_body.velocity)
        tangent = sub2(relative, scale2(manifold.normal, dot2(relative, manifold.normal)))
        if length2(tangent) > 1.0e-9:
            tangent = normalize2(tangent)
            friction_impulse = -dot2(relative, tangent) / total_inv
            friction = math.sqrt((a_body.friction if a_body else 0.0) * (b_body.friction if b_body else 0.0))
            friction_impulse = max(-impulse_magnitude * friction, min(impulse_magnitude * friction, friction_impulse))
            impulse_t = scale2(tangent, friction_impulse)
            if a_body is not None and inv_a > 0:
                a_body.velocity = sub2(a_body.velocity, scale2(impulse_t, inv_a))
            if b_body is not None and inv_b > 0:
                b_body.velocity = add2(b_body.velocity, scale2(impulse_t, inv_b))

    def _collision_step(self) -> None:
        broadphase = SpatialHash2D(self._broadphase_cell_size)
        shapes: dict[str, Shape2D] = {}
        filters: dict[str, CollisionFilter] = {}
        for entity in self.query(Transform2D, Collider2D):
            collider: Collider2D = entity.components["collider"]
            if not collider.enabled:
                continue
            shape = self.world_shape(entity.id)
            shapes[entity.id] = shape
            filters[entity.id] = collider.filter
            broadphase.insert(entity.id, shape_bounds(shape))

        contacts: dict[tuple[str, str], CollisionManifold] = {}
        for a_id, b_id in broadphase.potential_pairs():
            if not filters[a_id].allows(filters[b_id]):
                continue
            manifold = collide(shapes[a_id], shapes[b_id])
            if manifold is None:
                continue
            pair = (a_id, b_id)
            contacts[pair] = manifold
            previous = pair in self._contacts
            kind = "collision_stay" if previous else "collision_enter"
            self.emit(
                kind,
                source=a_id,
                target=b_id,
                payload={"normal": list(manifold.normal), "penetration": manifold.penetration, "contacts": [list(p) for p in manifold.contacts]},
            )
            if not (filters[a_id].sensor or filters[b_id].sensor):
                self._resolve_contact(a_id, b_id, manifold)

        for pair, manifold in sorted(self._contacts.items()):
            if pair not in contacts and pair[0] in self.entities and pair[1] in self.entities:
                self.emit("collision_exit", source=pair[0], target=pair[1], payload={"normal": list(manifold.normal)})
        self._contacts = contacts

    def _gameplay_interactions(self) -> None:
        collision_events = [event for event in self._step_events if event.kind in {"collision_enter", "collision_stay"}]
        for event in collision_events:
            if event.source not in self.entities or event.target not in self.entities:
                continue
            pairs = ((event.source, event.target), (event.target, event.source))
            for special_id, other_id in pairs:
                special = self.entities[special_id]
                other = self.entities[other_id]
                collectible: Collectible2D | None = special.components.get("collectible")
                if collectible is not None and "player" in other.tags and event.kind == "collision_enter":
                    self.state[collectible.state_key] = int(self.state.get(collectible.state_key, 0)) + collectible.points
                    self.emit(
                        "collected",
                        source=other_id,
                        target=special_id,
                        payload={"points": collectible.points, "state_key": collectible.state_key, "sound": collectible.sound},
                    )
                    special.active = False
                    renderer: VectorRenderer2D | None = special.components.get("vector_renderer")
                    if renderer:
                        renderer.visible = False
                    collider: Collider2D | None = special.components.get("collider")
                    if collider:
                        collider.enabled = False
                    if collectible.destroy_on_collect:
                        self._pending_despawn.add(special_id)
                hazard: Hazard2D | None = special.components.get("hazard")
                health: Health2D | None = other.components.get("health")
                if hazard is not None and health is not None:
                    last = hazard.last_hits.get(other_id, -math.inf)
                    if self.time - last + 1.0e-12 < hazard.cooldown or health.invulnerable_remaining > 0:
                        continue
                    hazard.last_hits[other_id] = self.time
                    health.current = max(0.0, health.current - hazard.damage)
                    health.invulnerable_remaining = health.invulnerability
                    normal = tuple(event.payload.get("normal", (1, 0)))
                    if special_id == event.target:
                        normal = scale2(normal, -1.0)
                    body: Body2D | None = other.components.get("body")
                    if body is not None:
                        body.velocity = add2(body.velocity, scale2(normal, -hazard.knockback))
                    self.emit(
                        "damaged",
                        source=special_id,
                        target=other_id,
                        payload={"damage": hazard.damage, "health": health.current, "sound": hazard.sound},
                    )
                    if health.current <= 0:
                        self.emit("entity_defeated", source=special_id, target=other_id)

    def _lifetime_step(self, dt: float) -> None:
        for entity in self.query(Lifetime2D):
            lifetime: Lifetime2D = entity.components["lifetime"]
            lifetime.remaining = max(0.0, lifetime.remaining - dt)
            if lifetime.remaining <= 0:
                self.emit("lifetime_expired", source=entity.id)
                self._pending_despawn.add(entity.id)
        for entity in self.query(Health2D):
            health: Health2D = entity.components["health"]
            health.invulnerable_remaining = max(0.0, health.invulnerable_remaining - dt)

    def _flush_despawn(self) -> None:
        pending = sorted(self._pending_despawn)
        self._pending_despawn.clear()
        previous_stepping = self._stepping
        self._stepping = False
        try:
            for entity_id in pending:
                if entity_id in self.entities:
                    self.despawn(entity_id)
        finally:
            self._stepping = previous_stepping

    def step(self, input_frame: InputFrame | None = None, steps: int = 1) -> tuple[GameEvent, ...]:
        if steps < 1:
            raise ValueError("steps must be positive")
        produced: list[GameEvent] = []
        for _ in range(steps):
            self._step_events = []
            self._stepping = True
            try:
                self._run_systems("input", self.fixed_dt, input_frame)
                self._controller_step(self.fixed_dt, input_frame)
                self._run_systems("pre_physics", self.fixed_dt, input_frame)
                self._physics_step(self.fixed_dt)
                self._bounds_step()
                self._run_systems("post_physics", self.fixed_dt, input_frame)
                self._collision_step()
                self._gameplay_interactions()
                self._run_systems("update", self.fixed_dt, input_frame)
                self._lifetime_step(self.fixed_dt)
                self._run_systems("late", self.fixed_dt, input_frame)
                for entity in self.query(Camera2D):
                    camera: Camera2D = entity.components["camera"]
                    camera.update(self, self.fixed_dt)
            finally:
                self._stepping = False
            self._flush_despawn()
            self.tick += 1
            self.time = round(self.tick * self.fixed_dt, 12)
            produced.extend(self._step_events)
        return tuple(produced)

    def entity_to_dict(self, entity: GameEntity) -> dict[str, Any]:
        return {
            "id": entity.id,
            "tags": sorted(entity.tags),
            "active": entity.active,
            "metadata": copy.deepcopy(entity.metadata),
            "components": {name: component_to_dict(component) for name, component in sorted(entity.components.items())},
        }

    def snapshot(self, include_events: bool = True) -> dict[str, Any]:
        data = {
            "schema": "ugts-kc-game-world-3.9",
            "fixed_dt": self.fixed_dt,
            "gravity": list(self.gravity),
            "tick": self.tick,
            "time": self.time,
            "state": copy.deepcopy(self.state),
            "next_entity": self._next_entity,
            "event_sequence": self._event_sequence,
            "entities": [self.entity_to_dict(self.entities[entity_id]) for entity_id in sorted(self.entities)],
            "contacts": [
                {
                    "pair": list(pair),
                    "normal": list(manifold.normal),
                    "penetration": manifold.penetration,
                    "contacts": [list(point) for point in manifold.contacts],
                }
                for pair, manifold in sorted(self._contacts.items())
            ],
        }
        if include_events:
            data["events"] = [_encode_value(event) for event in self.events]
        return _normalize_json_numbers(data)

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> "GameWorld":
        if data.get("schema") != "ugts-kc-game-world-3.9":
            raise ValueError("unsupported game world schema")
        world = cls(float(data["fixed_dt"]), data.get("gravity", (0, 0)))
        world.tick = int(data.get("tick", 0))
        world.time = float(data.get("time", world.tick * world.fixed_dt))
        world.state = copy.deepcopy(dict(data.get("state", {})))
        world._next_entity = int(data.get("next_entity", 1))
        world._event_sequence = int(data.get("event_sequence", 0))
        for entity_data in data.get("entities", []):
            entity = world.spawn(
                str(entity_data["id"]),
                tags=entity_data.get("tags", []),
                metadata=entity_data.get("metadata", {}),
                emit_event=False,
            )
            entity.active = bool(entity_data.get("active", True))
            for name, component_data in entity_data.get("components", {}).items():
                world.add_component(entity.id, component_from_dict(name, component_data), name)
        for item in data.get("contacts", []):
            pair = tuple(item["pair"])
            world._contacts[pair] = CollisionManifold(tuple(item["normal"]), float(item["penetration"]), tuple(tuple(p) for p in item.get("contacts", [])))  # type: ignore[index]
        world.events = [GameEvent(**event) for event in data.get("events", [])]
        world._step_events = []
        return world

    def state_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.snapshot(include_events=False))).hexdigest()

    def save(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output

    @classmethod
    def load(cls, path: str | Path) -> "GameWorld":
        return cls.from_snapshot(json.loads(Path(path).read_text(encoding="utf-8")))
