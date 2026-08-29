"""Editor-facing project document and undoable model mutations.

The editor deliberately talks to the public :mod:`ugts_kc3.project` and
:mod:`ugts_kc3.mobile3d` records instead of maintaining a second authoring
format.  A small amount of unknown top-level JSON is retained so newer Grove
extensions survive an edit/save cycle in this version of the editor.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal

from ..game import Transform2D
from ..game_input import InputFrame
from ..mobile3d import (
    InputFrame3D,
    Mobile3DProject,
    Node3DRecord,
    Transform3DRecord,
)
from ..project import EntitySpec, GameProject, GameSceneSpec


GRAPH_KEY = "visual_graph"


@dataclass(frozen=True)
class SelectionRef:
    """Stable reference used by the hierarchy, viewport, and inspector."""

    kind: str
    object_id: str
    scene_id: str | None = None


def quaternion_to_euler_degrees(rotation: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """Convert the engine's ``(w, x, y, z)`` quaternion to XYZ Euler degrees."""

    w, x, y, z = (float(value) for value in rotation)
    length = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / length, x / length, y / length, z / length
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    sinp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.asin(sinp)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return tuple(math.degrees(value) for value in (roll, pitch, yaw))  # type: ignore[return-value]


def euler_degrees_to_quaternion(rotation: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """Convert XYZ Euler degrees to the engine's normalized quaternion order."""

    roll, pitch, yaw = (math.radians(float(value)) * 0.5 for value in rotation)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    result = (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )
    length = math.sqrt(sum(value * value for value in result)) or 1.0
    return tuple(value / length for value in result)  # type: ignore[return-value]


class EditorDocument(QObject):
    """A loaded 2D or mobile-3D project with editor-friendly signals."""

    projectLoaded = Signal()
    documentChanged = Signal(bool)
    sceneChanged = Signal(str)
    selectionChanged = Signal(object)
    transformChanged = Signal(object)
    graphChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project: GameProject | Mobile3DProject | None = None
        self.kind: str | None = None
        self.path: Path | None = None
        self.current_scene_id: str | None = None
        self.selection: SelectionRef | None = None
        self._dirty = False
        self._extra_top_level: dict[str, Any] = {}
        self._runtime_world: Any | None = None
        self._previous_input: InputFrame | None = None

    @property
    def is_loaded(self) -> bool:
        return self.project is not None

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def display_name(self) -> str:
        if isinstance(self.project, GameProject):
            return self.project.metadata.title
        if isinstance(self.project, Mobile3DProject):
            return self.project.title
        return "No project"

    @property
    def object_count(self) -> int:
        if isinstance(self.project, GameProject):
            return sum(len(scene.entities) for scene in self.project.scenes.values())
        if isinstance(self.project, Mobile3DProject):
            return len(self.project.nodes)
        return 0

    def load(self, path: str | Path, *, as_copy: bool = False) -> None:
        source = Path(path).expanduser().resolve()
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("A project file must contain one JSON object.")

        if "schema" in raw and ("nodes" in raw or str(raw.get("schema", "")).startswith("ugts-kc-mobile-3d")):
            project: GameProject | Mobile3DProject = Mobile3DProject.from_dict(raw, validate=False)
            kind = "3d"
        elif "$schema" in raw or "scenes" in raw:
            project = GameProject.from_dict(raw, validate=False)
            kind = "2d"
        else:
            raise ValueError("This does not look like a UGTS 2D or Mobile 3D project.")

        known = set(project.to_dict())
        self._extra_top_level = {
            str(key): copy.deepcopy(value) for key, value in raw.items() if key not in known
        }
        self.project = project
        self.kind = kind
        self.path = None if as_copy else source
        self.current_scene_id = project.start_scene if isinstance(project, GameProject) else None
        self.selection = None
        self._runtime_world = None
        self._previous_input = None
        self._dirty = bool(as_copy)
        self.projectLoaded.emit()
        self.documentChanged.emit(self._dirty)
        if self.current_scene_id:
            self.sceneChanged.emit(self.current_scene_id)
        self.selectionChanged.emit(None)

    def serialize(self) -> dict[str, Any]:
        if self.project is None:
            raise RuntimeError("No project is open.")
        data = copy.deepcopy(self._extra_top_level)
        data.update(self.project.to_dict())
        return data

    def validate(self):
        if self.project is None:
            raise RuntimeError("No project is open.")
        return self.project.validate(raise_on_error=False)

    def save(self, path: str | Path | None = None) -> Path:
        if self.project is None:
            raise RuntimeError("No project is open.")
        destination = Path(path).expanduser().resolve() if path is not None else self.path
        if destination is None:
            raise ValueError("Choose a file name before saving this project.")
        report = self.validate()
        if not report.passed:
            issues = getattr(report, "issues", ())
            message = "; ".join(getattr(issue, "message", str(issue)) for issue in issues)
            raise ValueError(message or "The project has validation errors.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.serialize(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.path = destination
        self.set_dirty(False)
        return destination

    def set_dirty(self, dirty: bool = True) -> None:
        dirty = bool(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.documentChanged.emit(dirty)

    def set_current_scene(self, scene_id: str) -> None:
        if not isinstance(self.project, GameProject) or scene_id not in self.project.scenes:
            return
        if scene_id == self.current_scene_id:
            return
        self.current_scene_id = scene_id
        self.set_selection(None)
        self.sceneChanged.emit(scene_id)

    def set_selection(self, selection: SelectionRef | None) -> None:
        if selection == self.selection:
            return
        self.selection = selection
        self.selectionChanged.emit(selection)

    def scene(self, scene_id: str | None = None) -> GameSceneSpec | None:
        if not isinstance(self.project, GameProject):
            return None
        key = scene_id or self.current_scene_id
        return self.project.scenes.get(key or "")

    def entity(self, selection: SelectionRef | None = None) -> EntitySpec | Node3DRecord | None:
        selection = selection or self.selection
        if selection is None or self.project is None:
            return None
        if isinstance(self.project, GameProject):
            scene = self.project.scenes.get(selection.scene_id or self.current_scene_id or "")
            if scene is None:
                return None
            return next((entity for entity in scene.entities if entity.id == selection.object_id), None)
        return next((node for node in self.project.nodes if node.id == selection.object_id), None)

    def transform(self, selection: SelectionRef | None = None) -> dict[str, Any] | None:
        selected = self.entity(selection)
        if isinstance(selected, EntitySpec):
            value = selected.components.get("transform")
            if not isinstance(value, Mapping):
                return None
            return {
                "position": tuple(float(v) for v in value.get("position", (0, 0))),
                "rotation": float(value.get("rotation", 0.0)),
                "scale": tuple(float(v) for v in value.get("scale", (1, 1))),
            }
        if isinstance(selected, Node3DRecord):
            return {
                "translation": tuple(selected.transform.translation),
                "rotation": tuple(selected.transform.rotation),
                "scale": tuple(selected.transform.scale),
            }
        return None

    @staticmethod
    def _safe_scale(values: tuple[float, ...]) -> tuple[float, ...]:
        return tuple(0.0001 if abs(float(value)) < 0.0001 else float(value) for value in values)

    def set_transform(self, selection: SelectionRef, transform: Mapping[str, Any]) -> None:
        """Replace a transform through the authoritative project record model."""

        if isinstance(self.project, GameProject):
            scene_id = selection.scene_id or self.current_scene_id or ""
            scene = self.project.scenes.get(scene_id)
            if scene is None:
                raise KeyError(scene_id)
            replacement: list[EntitySpec] = []
            found = False
            for entity in scene.entities:
                if entity.id != selection.object_id:
                    replacement.append(entity)
                    continue
                found = True
                components = copy.deepcopy({name: dict(value) for name, value in entity.components.items()})
                previous = dict(components.get("transform", {}))
                previous.update(
                    {
                        "position": [float(v) for v in transform["position"]],
                        "rotation": float(transform["rotation"]),
                        "scale": list(self._safe_scale(tuple(transform["scale"]))),
                    }
                )
                components["transform"] = previous
                updated = replace(entity, components=components)
                updated.validate()
                replacement.append(updated)
            if not found:
                raise KeyError(selection.object_id)
            self.project.scenes[scene_id] = replace(scene, entities=tuple(replacement))
        elif isinstance(self.project, Mobile3DProject):
            replacement_nodes: list[Node3DRecord] = []
            found = False
            for node in self.project.nodes:
                if node.id != selection.object_id:
                    replacement_nodes.append(node)
                    continue
                found = True
                record = Transform3DRecord(
                    tuple(float(v) for v in transform["translation"]),  # type: ignore[arg-type]
                    tuple(float(v) for v in transform["rotation"]),  # type: ignore[arg-type]
                    self._safe_scale(tuple(transform["scale"])),  # type: ignore[arg-type]
                )
                record.validate()
                replacement_nodes.append(replace(node, transform=record))
            if not found:
                raise KeyError(selection.object_id)
            self.project.nodes = tuple(replacement_nodes)
        else:
            raise RuntimeError("No project is open.")
        self.set_dirty(True)
        self.transformChanged.emit(selection)

    def object_details(self, selection: SelectionRef | None = None) -> dict[str, Any]:
        selected = self.entity(selection)
        if isinstance(selected, EntitySpec):
            return selected.to_dict()
        if isinstance(selected, Node3DRecord):
            return selected.to_dict()
        return {}

    def graph_data(self) -> dict[str, Any]:
        if isinstance(self.project, GameProject):
            scene = self.scene()
            value = None if scene is None else scene.rules.get(GRAPH_KEY)
        elif isinstance(self.project, Mobile3DProject):
            value = self.project.metadata.get(GRAPH_KEY)
        else:
            value = None
        if not isinstance(value, Mapping):
            return {"version": 1, "nodes": [], "connections": []}
        result = copy.deepcopy(dict(value))
        result.setdefault("version", 1)
        result.setdefault("nodes", [])
        result.setdefault("connections", [])
        return result

    def set_graph_data(self, graph: Mapping[str, Any]) -> None:
        payload = copy.deepcopy(dict(graph))
        if isinstance(self.project, GameProject):
            scene = self.scene()
            if scene is None:
                return
            rules = copy.deepcopy(dict(scene.rules))
            rules[GRAPH_KEY] = payload
            self.project.scenes[scene.id] = replace(scene, rules=rules)
        elif isinstance(self.project, Mobile3DProject):
            metadata = copy.deepcopy(self.project.metadata)
            metadata[GRAPH_KEY] = payload
            self.project.metadata = metadata
        else:
            return
        self.set_dirty(True)
        self.graphChanged.emit()

    def begin_play(self) -> None:
        if isinstance(self.project, GameProject):
            self._runtime_world = self.project.instantiate_world(self.current_scene_id)
        elif isinstance(self.project, Mobile3DProject):
            self._runtime_world = self.project.instantiate_world()
        else:
            raise RuntimeError("Open a project before pressing Play.")
        self._previous_input = None

    def stop_play(self) -> None:
        self._runtime_world = None
        self._previous_input = None

    def step_play(self, pressed_keys: set[str]) -> tuple[dict[str, dict[str, Any]], tuple[Any, ...]]:
        """Advance the real reference runtime and return render-friendly transforms."""

        if self._runtime_world is None:
            return {}, ()
        left = "left" in pressed_keys or "a" in pressed_keys
        right = "right" in pressed_keys or "d" in pressed_keys
        up = "up" in pressed_keys or "w" in pressed_keys
        down = "down" in pressed_keys or "s" in pressed_keys
        if isinstance(self.project, GameProject):
            values = {
                "move_x": float(right) - float(left),
                "move_y": float(down) - float(up),
                "dash": float("space" in pressed_keys),
                "jump": float("space" in pressed_keys),
                "action": float("enter" in pressed_keys),
            }
            frame = self.project.input_map.frame_from_actions(values, self._previous_input)
            self._previous_input = frame
            events = self._runtime_world.step(frame)
            state: dict[str, dict[str, Any]] = {}
            for entity_id, entity in self._runtime_world.entities.items():
                transform = entity.components.get("transform")
                if isinstance(transform, Transform2D) and entity.active:
                    state[entity_id] = {
                        "position": transform.position,
                        "rotation": transform.rotation,
                        "scale": transform.scale,
                    }
            return state, events
        frame3d = InputFrame3D(
            float(right) - float(left),
            float(down) - float(up),
            jump="space" in pressed_keys,
            action="enter" in pressed_keys,
        )
        events = self._runtime_world.step(frame3d)
        state = {
            entity_id: {
                "translation": entity.position,
                "rotation": entity.rotation,
                "scale": entity.scale,
            }
            for entity_id, entity in self._runtime_world.entities.items()
            if entity.alive
        }
        return state, events


__all__ = [
    "EditorDocument",
    "GRAPH_KEY",
    "SelectionRef",
    "euler_degrees_to_quaternion",
    "quaternion_to_euler_degrees",
]
