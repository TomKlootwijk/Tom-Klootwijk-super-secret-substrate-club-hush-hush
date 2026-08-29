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
import re
from typing import Any, Mapping
import unicodedata

from PySide6.QtCore import QObject, Signal

from ..game import Transform2D
from ..game_input import InputFrame
from ..mobile3d import (
    Collider3DRecord,
    InputFrame3D,
    Mesh3DRecord,
    Mobile3DProject,
    Node3DRecord,
    Transform3DRecord,
    visual_graphs_from_metadata,
)
from ..objimport import load_wavefront_obj
from ..packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PackedKinematicComponent,
    PolarLookupTable,
    PolarMotion,
    PolarPose,
    packed_kinematic_codecs_from_dict,
)
from ..project import (
    EntitySpec,
    GameProject,
    GameSceneSpec,
    visual_graph_binding_ids,
    visual_graphs_from_rules,
)
from ..scatter import (
    SCATTER_METADATA_KEY,
    ScatterError,
    ScatterPopulation,
    validate_scatter_prototype,
)
from ..visual_graph import GraphExecutionError, TraceEntry, VisualGraph


GRAPHS_KEY = "visual_graphs"
BINDING_KEY = "visual_graph"
MOVEMENT_PROFILES_KEY = "packed_kinematic_profiles"
MOVEMENT_COMPONENT_KEY = "packed_kinematic"
STUDIO_MOVEMENT_PROFILE_ID = "studio_movement"
PACKED_COMPONENT_ANDROID_BYTES = 24
_STUDIO_MOVEMENT_PROFILE = LogPolarProfile(
    r0=1.0, rho_min=-2.0, rho_max=4.0, core_radius=1.0e-5
)
_STUDIO_MOVEMENT_RANGE = MotionRange(
    rho_velocity=1.0,
    theta_velocity=8.0,
    rho_acceleration=1.0,
    theta_acceleration=8.0,
)
_STUDIO_MOVEMENT_LUT_RESOLUTION = 128
_SPIRAL_LOG_RATE = 0.2
_CURRENT_GRAPH_SELECTION = object()


def studio_movement_profile_config() -> dict[str, Any]:
    """Return a fresh canonical shared profile used by Inspector presets."""

    return {
        "profile": _STUDIO_MOVEMENT_PROFILE.to_dict(),
        "motion_range": _STUDIO_MOVEMENT_RANGE.to_dict(),
        "lut_resolution": _STUDIO_MOVEMENT_LUT_RESOLUTION,
    }


def friendly_rule_name(value: str) -> str:
    """Turn an internal rule key into a short phrase for learner messages."""

    return value.replace("_", " ").replace("-", " ").strip().casefold()


@dataclass(frozen=True)
class SelectionRef:
    """Stable reference used by the hierarchy, viewport, and inspector."""

    kind: str
    object_id: str
    scene_id: str | None = None


@dataclass(frozen=True, slots=True)
class LogicTraceSnapshot:
    """One useful, read-only Logic Blocks execution captured from Preview.

    Snapshots deliberately live outside the project model.  ``sequence`` is a
    per-preview recency counter for editor presentation, not simulation state.
    """

    graph_id: str
    owner_id: str | None
    trigger: str
    steps: int
    trace: tuple[TraceEntry, ...]
    completed: bool
    sequence: int

    @property
    def key(self) -> tuple[str, str | None]:
        return self.graph_id, self.owner_id


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
    structureChanged = Signal()
    logicTraceChanged = Signal(object)

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
        self._logic_traces: dict[tuple[str, str | None], LogicTraceSnapshot] = {}
        self._logic_trace_results: dict[tuple[str, str | None], object] = {}
        self._logic_trace_sequence = 0
        self.play_warnings: list[str] = []

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
        self._clear_logic_traces()
        self._dirty = bool(as_copy)
        self.projectLoaded.emit()
        self.documentChanged.emit(self._dirty)
        if self.current_scene_id:
            self.sceneChanged.emit(self.current_scene_id)
        self.selectionChanged.emit(None)

    def create(self, project: GameProject | Mobile3DProject) -> None:
        """Adopt a freshly generated project as an unsaved editor document."""

        if not isinstance(project, (GameProject, Mobile3DProject)):
            raise TypeError("EditorDocument.create needs a GameProject or Mobile3DProject.")
        self.project = project
        self.kind = "2d" if isinstance(project, GameProject) else "3d"
        self.path = None
        self.current_scene_id = project.start_scene if isinstance(project, GameProject) else None
        self.selection = None
        self._runtime_world = None
        self._previous_input = None
        self._clear_logic_traces()
        self._extra_top_level = {}
        self._dirty = True
        self.projectLoaded.emit()
        self.documentChanged.emit(True)
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
        if (
            isinstance(self.project, GameProject)
            and selection is not None
            and selection.kind == "world_graph"
            and selection.scene_id in self.project.scenes
            and selection.scene_id != self.current_scene_id
        ):
            # A World Logic item belongs to its scene. Activate that scene
            # without an intermediate empty selection so Preview runs the
            # graph the child just chose.
            self.current_scene_id = selection.scene_id
            self.selection = selection
            self.sceneChanged.emit(selection.scene_id)
            self.selectionChanged.emit(selection)
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
        if selection.kind not in {"entity", "node"}:
            return None
        if isinstance(self.project, GameProject):
            scene = self.project.scenes.get(selection.scene_id or self.current_scene_id or "")
            if scene is None:
                return None
            return next((entity for entity in scene.entities if entity.id == selection.object_id), None)
        return next((node for node in self.project.nodes if node.id == selection.object_id), None)

    def scene_objects(
        self, scene_id: str | None = None
    ) -> tuple[EntitySpec, ...] | tuple[Node3DRecord, ...]:
        """Return the editable records for one scene without changing the project."""

        if isinstance(self.project, GameProject):
            scene = self.scene(scene_id)
            return () if scene is None else scene.entities
        if isinstance(self.project, Mobile3DProject):
            return self.project.nodes
        return ()

    @staticmethod
    def _friendly_id_base(label: str, fallback: str = "new_object") -> str:
        ascii_label = unicodedata.normalize("NFKD", str(label)).encode("ascii", "ignore").decode("ascii")
        base = re.sub(r"[^a-z0-9]+", "_", ascii_label.casefold()).strip("_")
        if not base:
            base = fallback
        if not base[0].isalpha():
            base = f"object_{base}"
        return base[:56].rstrip("_") or fallback

    def collision_free_object_id(self, label: str, scene_id: str | None = None) -> str:
        """Make a readable, stable id that cannot collide in the active scene."""

        base = self._friendly_id_base(label)
        used = {record.id for record in self.scene_objects(scene_id)}
        if base not in used:
            return base
        suffix = 2
        while f"{base}_{suffix}" in used:
            suffix += 1
        return f"{base}_{suffix}"

    def collision_free_mesh_id(self, label: str) -> str:
        """Make a readable resource id without overwriting an existing mesh."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Import 3D Shape is available in mobile 3D projects.")
        base = self._friendly_id_base(label, "imported_shape")
        used = set(self.project.meshes)
        if base not in used:
            return base
        suffix = 2
        while f"{base}_{suffix}" in used:
            suffix += 1
        return f"{base}_{suffix}"

    def imported_obj_mesh(self, path: str | Path) -> Mesh3DRecord:
        """Parse an OBJ into a new, collision-free project mesh snapshot."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Open a mobile 3D project before importing a 3D shape.")
        source = Path(path)
        return load_wavefront_obj(source, self.collision_free_mesh_id(source.stem))

    def new_object_record(self) -> EntitySpec | Node3DRecord:
        """Create a small visible object that uses resources already in the project."""

        if isinstance(self.project, GameProject):
            scene = self.scene()
            if scene is None:
                raise ValueError("Choose a 2D scene before adding an object.")
            count = len(scene.entities)
            width, height = scene.world_size
            position = (
                width * 0.5 + ((count % 5) - 2) * 28.0,
                height * 0.5 + (((count // 5) % 5) - 2) * 28.0,
            )
            components: dict[str, dict[str, Any]] = {
                "transform": {
                    "position": [float(position[0]), float(position[1])],
                    "rotation": 0.0,
                    "scale": [1.0, 1.0],
                }
            }
            asset_id = next(iter(sorted(self.project.vector_assets.assets)), None)
            if asset_id is not None:
                components["vector_renderer"] = {
                    "asset_id": asset_id,
                    "z_index": 0,
                    "visible": True,
                    "opacity": 1.0,
                }
            record = EntitySpec(
                self.collision_free_object_id("new_object"),
                components,
                frozenset({"new_object"}),
                True,
                {"description": "A new object made in UGTS Studio"},
            )
            record.validate()
            return record

        if isinstance(self.project, Mobile3DProject):
            mesh_id = next(
                (key for key in ("cube", "sphere", "pyramid") if key in self.project.meshes),
                next(iter(sorted(self.project.meshes)), ""),
            )
            material_id = next(
                (key for key in ("accent", "default", "player") if key in self.project.materials),
                next(iter(sorted(self.project.materials)), ""),
            )
            if not mesh_id or not material_id:
                raise ValueError(
                    "This 3D project needs at least one mesh and material before an object can be added."
                )
            count = len(self.project.nodes)
            record = Node3DRecord(
                self.collision_free_object_id("new_object"),
                mesh_id,
                material_id,
                Transform3DRecord(
                    (((count % 5) - 2) * 1.5, 1.0, ((count // 5) % 5) * -1.5)
                ),
                tags=("new_object",),
                metadata={"description": "A new object made in UGTS Studio"},
            )
            record.validate()
            return record
        raise RuntimeError("Open a project before adding an object.")

    def new_trigger_area_record(self) -> Node3DRecord:
        """Create one visible, static trigger using existing project resources."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Trigger Areas are available in mobile 3D projects.")
        mesh_id = next(
            (key for key in ("sphere", "cube", "pyramid") if key in self.project.meshes),
            next(iter(sorted(self.project.meshes)), ""),
        )
        material_id = next(
            (key for key in ("accent", "default", "player") if key in self.project.materials),
            next(iter(sorted(self.project.materials)), ""),
        )
        if not mesh_id or not material_id:
            raise ValueError(
                "This 3D project needs at least one shape and material before a Trigger Area can be added."
            )
        count = len(self.project.nodes)
        record = Node3DRecord(
            self.collision_free_object_id("trigger_area"),
            mesh_id,
            material_id,
            Transform3DRecord(
                (((count % 5) - 2) * 1.5, 1.0, ((count // 5) % 5) * -1.5)
            ),
            collider=Collider3DRecord(
                "sphere", radius=1.5, half_extents=(1.5, 1.5, 1.5), sensor=True
            ),
            dynamic=False,
            tags=("trigger_area",),
            metadata={
                "description": (
                    "A Trigger Area that notices when the player enters or leaves, "
                    "without pushing anything."
                )
            },
        )
        record.validate()
        candidate = copy.deepcopy(self.project)
        candidate.nodes = tuple(candidate.nodes) + (record,)
        candidate.validate()
        return record

    def duplicate_object_record(
        self, selection: SelectionRef | None = None
    ) -> EntitySpec | Node3DRecord:
        """Deep-copy one selected record, changing only its id and placement."""

        selection = selection or self.selection
        source = self.entity(selection)
        if source is None:
            raise ValueError("Choose an object in the Scene Tree before making a copy.")
        new_id = self.collision_free_object_id(f"{source.id}_copy", selection.scene_id if selection else None)
        if isinstance(source, EntitySpec):
            components = copy.deepcopy({name: dict(value) for name, value in source.components.items()})
            transform = components.get("transform")
            if isinstance(transform, Mapping):
                updated_transform = copy.deepcopy(dict(transform))
                position = updated_transform.get("position", (0.0, 0.0))
                updated_transform["position"] = [float(position[0]) + 32.0, float(position[1]) + 32.0]
                components["transform"] = updated_transform
            record = replace(
                source,
                id=new_id,
                components=components,
                metadata=copy.deepcopy(dict(source.metadata)),
            )
            record.validate()
            return record
        if isinstance(source, Node3DRecord):
            x, y, z = source.transform.translation
            record = replace(
                source,
                id=new_id,
                transform=replace(source.transform, translation=(x + 1.0, y, z + 1.0)),
                metadata=copy.deepcopy(source.metadata),
            )
            record.validate()
            return record
        raise ValueError("Only 2D entities and 3D objects can be copied.")

    @staticmethod
    def _contains_entity_reference(value: Any, object_id: str) -> bool:
        if not isinstance(value, Mapping):
            return False
        for key, child in value.items():
            normalized_key = str(key).casefold()
            if (
                normalized_key.endswith(("_entity", "_entity_id"))
                or normalized_key in {"follow_entity", "target_entity", "owner_entity"}
            ) and child == object_id:
                return True
            if isinstance(child, Mapping) and EditorDocument._contains_entity_reference(child, object_id):
                return True
            if isinstance(child, (list, tuple)) and any(
                isinstance(item, Mapping)
                and EditorDocument._contains_entity_reference(item, object_id)
                for item in child
            ):
                return True
        return False

    def deletion_problem(self, selection: SelectionRef | None = None) -> str | None:
        """Explain why a selected record must remain, or return ``None``."""

        selection = selection or self.selection
        source = self.entity(selection)
        if source is None or selection is None:
            return "Choose an object in the Scene Tree before deleting it."
        records = self.scene_objects(selection.scene_id)
        if len(records) <= 1:
            return "Keep at least one object in the scene so there is always something to edit."
        if isinstance(source, EntitySpec):
            scene = self.scene(selection.scene_id)
            if scene is None:
                return "Choose a 2D scene before deleting an object."
            for key, value in scene.rules.items():
                normalized_key = str(key).casefold()
                if value == source.id and (normalized_key.endswith("_id") or normalized_key == "player"):
                    return (
                        f"{source.id} is the scene's {friendly_rule_name(str(key))}. "
                        "Choose a different object in the scene rules before deleting it."
                    )
            for other in scene.entities:
                if other.id != source.id and self._contains_entity_reference(other.components, source.id):
                    return (
                        f"{other.id} still points to {source.id}. Change that reference before deleting it."
                    )
        return None

    def replace_scene_objects(
        self,
        records: tuple[EntitySpec, ...] | tuple[Node3DRecord, ...],
        selection: SelectionRef | None,
        scene_id: str | None = None,
    ) -> None:
        """Apply one validated object-list snapshot and notify every editor surface."""

        snapshot = copy.deepcopy(tuple(records))
        if isinstance(self.project, GameProject):
            key = scene_id or self.current_scene_id or ""
            scene = self.project.scenes.get(key)
            if scene is None or not all(isinstance(record, EntitySpec) for record in snapshot):
                raise ValueError("The 2D scene object list is not valid.")
            candidate = replace(scene, entities=snapshot)
            candidate.validate()
            self.project.scenes[key] = candidate
        elif isinstance(self.project, Mobile3DProject):
            if not all(isinstance(record, Node3DRecord) for record in snapshot):
                raise ValueError("The 3D scene object list is not valid.")
            ids = [record.id for record in snapshot]
            if len(ids) != len(set(ids)):
                raise ValueError("Every 3D object needs a unique name.")
            for record in snapshot:
                record.validate()
                if record.mesh_id not in self.project.meshes:
                    raise ValueError(f"{record.id} uses a missing mesh: {record.mesh_id}")
                if record.material_id not in self.project.materials:
                    raise ValueError(f"{record.id} uses a missing material: {record.material_id}")
            self.project.nodes = snapshot
        else:
            raise RuntimeError("Open a project before editing its scene.")
        self._runtime_world = None
        self.set_dirty(True)
        self.structureChanged.emit()
        self.set_selection(selection)

    def replace_mesh_resources(self, meshes: Mapping[str, Mesh3DRecord]) -> None:
        """Apply a validated 3D-mesh snapshot and refresh all editor surfaces."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Open a mobile 3D project before changing its 3D shapes.")
        snapshot = copy.deepcopy(dict(meshes))
        if not snapshot:
            raise ValueError("A mobile 3D project must keep at least one 3D shape.")
        for key, mesh in snapshot.items():
            if not isinstance(mesh, Mesh3DRecord) or key != mesh.id:
                raise ValueError("Every imported 3D shape needs a matching resource name.")
            mesh.validate()
        for node in self.project.nodes:
            if node.mesh_id not in snapshot:
                raise ValueError(f"{node.id} still uses the missing 3D shape {node.mesh_id}.")
        candidate = copy.deepcopy(self.project)
        candidate.meshes = snapshot
        candidate.validate()
        self.project.meshes = snapshot
        self._runtime_world = None
        self.set_dirty(True)
        self.structureChanged.emit()

    def movement_profiles(self) -> dict[str, Any]:
        """Return a detached snapshot of canonical packed-movement profiles."""

        if not isinstance(self.project, Mobile3DProject):
            return {}
        raw = self.project.metadata.get(MOVEMENT_PROFILES_KEY, {})
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ValueError("Movement pattern profiles must be a project object.")
        return copy.deepcopy(dict(raw))

    @staticmethod
    def _profile_resolution(profiles: Mapping[str, Any], profile_id: str) -> int:
        raw = profiles.get(profile_id, {})
        if not isinstance(raw, Mapping):
            return 256
        value = raw.get("lut_resolution", 256)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 256

    @staticmethod
    def _profile_limits(codec: PackedKinematicCodec) -> tuple[float, float, float]:
        minimum = codec.profile.r0 * math.exp(codec.profile.rho_min)
        maximum = codec.profile.r0 * math.exp(codec.profile.rho_max)
        turn_speed = codec.motion_range.theta_velocity / math.tau
        return minimum, maximum, turn_speed

    @staticmethod
    def _movement_pattern(
        motion: PolarMotion, codec: PackedKinematicCodec
    ) -> str:
        rho_epsilon = codec.motion_range.rho_velocity / 32767.0 * 1.5
        theta_accel_epsilon = codec.motion_range.theta_acceleration / 32767.0 * 1.5
        rho_accel_epsilon = codec.motion_range.rho_acceleration / 32767.0 * 1.5
        if (
            abs(motion.rho_acceleration) > rho_accel_epsilon
            or abs(motion.theta_acceleration) > theta_accel_epsilon
        ):
            return "custom"
        preset_rate = min(
            _SPIRAL_LOG_RATE, codec.motion_range.rho_velocity * 0.5
        )
        if abs(motion.rho_velocity) <= rho_epsilon:
            return "orbit"
        if abs(motion.rho_velocity - preset_rate) <= rho_epsilon:
            return "spiral_out"
        if abs(motion.rho_velocity + preset_rate) <= rho_epsilon:
            return "spiral_in"
        return "custom"

    def movement_pattern_state(
        self, selection: SelectionRef | None = None
    ) -> dict[str, Any] | None:
        """Decode one 3D node's packed words into friendly Inspector values."""

        if not isinstance(self.project, Mobile3DProject):
            return None
        selected = self.entity(selection)
        if not isinstance(selected, Node3DRecord):
            return None
        raw_component = selected.metadata.get(MOVEMENT_COMPONENT_KEY)
        profiles = self.movement_profiles()
        x, _y, z = selected.transform.translation
        authored_radius = math.hypot(x, z)
        authored_angle = math.degrees(math.atan2(z, x)) % 360.0
        base: dict[str, Any] = {
            "dynamic": bool(selected.dynamic),
            "has_component": raw_component is not None,
            "pattern": "off",
            "radius": authored_radius if authored_radius >= 0.25 else 3.0,
            "speed": 0.2,
            "start_angle": authored_angle,
            "radius_min": 0.25,
            "radius_max": 40.0,
            "speed_max": _STUDIO_MOVEMENT_RANGE.theta_velocity / math.tau,
            "spiral_rate": _SPIRAL_LOG_RATE,
            "component_bytes": PACKED_COMPONENT_ANDROID_BYTES,
            "shared_lut_bytes": len(
                PolarLookupTable.generate(
                    _STUDIO_MOVEMENT_PROFILE, _STUDIO_MOVEMENT_LUT_RESOLUTION
                ).to_bytes()
            ),
            "lut_resolution": _STUDIO_MOVEMENT_LUT_RESOLUTION,
            "error": "",
        }
        if raw_component is None:
            return base
        try:
            if not isinstance(raw_component, Mapping):
                raise TypeError("the saved movement component is not an object")
            component = PackedKinematicComponent.from_dict(raw_component)
            codecs = packed_kinematic_codecs_from_dict(profiles)
            if component.profile_id not in codecs:
                raise ValueError(f"unknown movement profile {component.profile_id}")
            codec = codecs[component.profile_id]
            pose = codec.unpack_pose(component.pose_word)
            motion = codec.unpack_motion(component.motion_word)
            minimum, maximum, speed_max = self._profile_limits(codec)
            resolution = self._profile_resolution(profiles, component.profile_id)
            base.update(
                {
                    "pattern": self._movement_pattern(motion, codec),
                    "radius": codec.profile.r0 * math.exp(pose.rho),
                    "speed": motion.theta_velocity / math.tau,
                    "start_angle": math.degrees(pose.theta) % 360.0,
                    "radius_min": minimum,
                    "radius_max": maximum,
                    "speed_max": speed_max,
                    "spiral_rate": min(
                        _SPIRAL_LOG_RATE, codec.motion_range.rho_velocity * 0.5
                    ),
                    "shared_lut_bytes": len(
                        PolarLookupTable.generate(codec.profile, resolution).to_bytes()
                    ),
                    "lut_resolution": resolution,
                }
            )
        except (KeyError, OverflowError, TypeError, ValueError) as exc:
            base.update({"pattern": "invalid", "error": str(exc)})
        return base

    @staticmethod
    def _profile_matches_studio(raw: Any) -> bool:
        if not isinstance(raw, Mapping):
            return False
        try:
            profile_data = raw.get("profile", raw)
            motion_data = raw.get("motion_range", {})
            return (
                isinstance(profile_data, Mapping)
                and isinstance(motion_data, Mapping)
                and LogPolarProfile.from_dict(profile_data) == _STUDIO_MOVEMENT_PROFILE
                and MotionRange.from_dict(motion_data) == _STUDIO_MOVEMENT_RANGE
                and raw.get("lut_resolution", 256) == _STUDIO_MOVEMENT_LUT_RESOLUTION
            )
        except (TypeError, ValueError):
            return False

    @classmethod
    def _shared_studio_profile(cls, profiles: dict[str, Any]) -> str:
        for profile_id, raw in profiles.items():
            if cls._profile_matches_studio(raw):
                return str(profile_id)
        profile_id = STUDIO_MOVEMENT_PROFILE_ID
        suffix = 2
        while profile_id in profiles:
            profile_id = f"{STUDIO_MOVEMENT_PROFILE_ID}_{suffix}"
            suffix += 1
        profiles[profile_id] = studio_movement_profile_config()
        return profile_id

    def movement_pattern_snapshot(
        self,
        selection: SelectionRef,
        values: Mapping[str, Any],
    ) -> tuple[tuple[Node3DRecord, ...], dict[str, Any]]:
        """Build validated node/profile snapshots for one friendly movement edit."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Movement patterns are available in mobile 3D projects.")
        selected = self.entity(selection)
        if not isinstance(selected, Node3DRecord):
            raise ValueError("Choose a 3D object before changing its movement pattern.")
        pattern = str(values.get("pattern", "off"))
        if pattern not in {"off", "orbit", "spiral_out", "spiral_in"}:
            raise ValueError("Choose Off, Orbit, Spiral Out, or Spiral In.")
        if selected.dynamic and pattern != "off":
            raise ValueError(
                "Physics already controls this dynamic object. Turn Dynamic off before adding a movement pattern."
            )
        profiles = self.movement_profiles()
        metadata = copy.deepcopy(selected.metadata)
        updated = selected
        if pattern == "off":
            metadata.pop(MOVEMENT_COMPONENT_KEY, None)
            updated = replace(selected, metadata=metadata)
        else:
            raw_existing = selected.metadata.get(MOVEMENT_COMPONENT_KEY)
            existing: PackedKinematicComponent | None = None
            if isinstance(raw_existing, Mapping):
                try:
                    existing = PackedKinematicComponent.from_dict(raw_existing)
                except (TypeError, ValueError):
                    existing = None
            codecs = packed_kinematic_codecs_from_dict(profiles)
            if existing is not None and existing.profile_id in codecs:
                profile_id = existing.profile_id
            else:
                profile_id = self._shared_studio_profile(profiles)
                codecs = packed_kinematic_codecs_from_dict(profiles)
            codec = codecs[profile_id]
            existing_pose = (
                codec.unpack_pose(existing.pose_word)
                if existing is not None and existing.profile_id == profile_id
                else None
            )
            radius = float(values.get("radius", 3.0))
            speed = float(values.get("speed", 0.2))
            angle_degrees = float(values.get("start_angle", 0.0))
            if not all(math.isfinite(value) for value in (radius, speed, angle_degrees)):
                raise ValueError("Movement radius, speed, and start angle must be finite numbers.")
            if radius <= 0:
                raise ValueError("Movement radius must be greater than zero.")
            rho = math.log(radius / codec.profile.r0)
            if not codec.profile.rho_min <= rho <= codec.profile.rho_max:
                minimum, maximum, _speed_max = self._profile_limits(codec)
                raise ValueError(
                    f"This shared movement profile supports radii from {minimum:.2f} to {maximum:.2f}."
                )
            theta_velocity = speed * math.tau
            if abs(theta_velocity) > codec.motion_range.theta_velocity + 1.0e-12:
                _minimum, _maximum, speed_max = self._profile_limits(codec)
                raise ValueError(
                    f"Turn speed must stay between {-speed_max:.2f} and {speed_max:.2f} turns per second."
                )
            radial_rate = min(_SPIRAL_LOG_RATE, codec.motion_range.rho_velocity * 0.5)
            rho_velocity = (
                radial_rate if pattern == "spiral_out"
                else -radial_rate if pattern == "spiral_in"
                else 0.0
            )
            theta = math.radians(angle_degrees) % math.tau
            component = codec.component(
                PolarPose(
                    rho,
                    theta,
                    0 if existing_pose is None else existing_pose.tick,
                    theta if existing_pose is None else existing_pose.heading,
                ),
                PolarMotion(rho_velocity=rho_velocity, theta_velocity=theta_velocity),
                profile_id=profile_id,
            )
            if (
                isinstance(raw_existing, Mapping)
                and component.to_dict() == dict(raw_existing)
            ):
                updated = selected
            else:
                metadata[MOVEMENT_COMPONENT_KEY] = component.to_dict()
                quantized_pose = codec.unpack_pose(component.pose_word)
                x, z = codec.profile.decode_cartesian(
                    quantized_pose.rho, quantized_pose.theta
                )
                transform = replace(
                    selected.transform,
                    translation=(x, selected.transform.translation[1], z),
                    rotation=(
                        math.cos(quantized_pose.heading * 0.5),
                        0.0,
                        math.sin(quantized_pose.heading * 0.5),
                        0.0,
                    ),
                )
                updated = replace(selected, transform=transform, metadata=metadata)
        updated.validate()
        nodes = tuple(
            updated if node.id == selected.id else copy.deepcopy(node)
            for node in self.project.nodes
        )
        candidate = copy.deepcopy(self.project)
        candidate.nodes = nodes
        candidate_metadata = copy.deepcopy(candidate.metadata)
        if profiles:
            candidate_metadata[MOVEMENT_PROFILES_KEY] = copy.deepcopy(profiles)
        else:
            candidate_metadata.pop(MOVEMENT_PROFILES_KEY, None)
        candidate.metadata = candidate_metadata
        candidate.validate()
        return nodes, profiles

    def replace_movement_patterns(
        self,
        nodes: tuple[Node3DRecord, ...],
        profiles: Mapping[str, Any],
        selection: SelectionRef | None,
    ) -> None:
        """Apply one validated packed-movement snapshot and refresh editor views."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Open a mobile 3D project before changing movement patterns.")
        snapshot_nodes = copy.deepcopy(tuple(nodes))
        snapshot_profiles = copy.deepcopy(dict(profiles))
        candidate = copy.deepcopy(self.project)
        candidate.nodes = snapshot_nodes
        metadata = copy.deepcopy(candidate.metadata)
        if snapshot_profiles:
            metadata[MOVEMENT_PROFILES_KEY] = snapshot_profiles
        else:
            metadata.pop(MOVEMENT_PROFILES_KEY, None)
        candidate.metadata = metadata
        candidate.validate()
        self.project.nodes = snapshot_nodes
        self.project.metadata = metadata
        self._runtime_world = None
        self.set_dirty(True)
        self.structureChanged.emit()
        self.set_selection(selection)

    def population_state(
        self, selection: SelectionRef | None = None
    ) -> dict[str, Any] | None:
        """Describe one node's compact, static Populate Area recipe."""

        if not isinstance(self.project, Mobile3DProject):
            return None
        selected = self.entity(selection)
        if not isinstance(selected, Node3DRecord):
            return None
        raw = selected.metadata.get(SCATTER_METADATA_KEY)
        population = ScatterPopulation()
        saved_error = ""
        if raw is not None:
            try:
                if not isinstance(raw, Mapping):
                    raise ScatterError("the saved population recipe is not an object")
                population = ScatterPopulation.from_mapping(raw)
            except ScatterError as exc:
                saved_error = str(exc)
        safety_error = ""
        try:
            validate_scatter_prototype(selected)
        except ScatterError as exc:
            safety_error = str(exc)
        quality_budget = 0
        for tier in self.project.quality_tiers:
            if tier.id == self.project.start_quality:
                quality_budget = int(tier.max_visible_nodes)
                break
        return {
            "enabled": raw is not None,
            "valid": not saved_error and not safety_error,
            "can_enable": not safety_error,
            "instance_count": population.instance_count,
            "seed": population.seed,
            "size_x": population.size[0],
            "size_y": population.size[1],
            "size_z": population.size[2],
            "scale_min": population.scale_min,
            "scale_max": population.scale_max,
            "random_yaw": population.random_yaw,
            "recipe_bytes": 36,
            "shared_header_bytes": 24,
            "quality_budget": quality_budget,
            "over_start_budget": population.instance_count > max(0, quality_budget),
            "error": saved_error or safety_error,
        }

    def record_with_population(
        self,
        selection: SelectionRef,
        values: Mapping[str, Any],
    ) -> Node3DRecord:
        """Return one project-validated node with a sparse population recipe."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Populate Area is available in mobile 3D projects.")
        selected = self.entity(selection)
        if not isinstance(selected, Node3DRecord):
            raise ValueError("Choose a 3D object before using Populate Area.")
        enabled = values.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("Populate this object must be on or off.")
        metadata = copy.deepcopy(selected.metadata)
        if enabled:
            population = ScatterPopulation.from_mapping(
                {
                    "instance_count": values.get("instance_count", 8),
                    "seed": values.get("seed", 1),
                    "size": [
                        values.get("size_x", 8.0),
                        values.get("size_y", 0.0),
                        values.get("size_z", 8.0),
                    ],
                    "scale_min": values.get("scale_min", 0.85),
                    "scale_max": values.get("scale_max", 1.15),
                    "random_yaw": values.get("random_yaw", True),
                }
            )
            metadata[SCATTER_METADATA_KEY] = population.to_dict()
        else:
            metadata.pop(SCATTER_METADATA_KEY, None)
        updated = replace(selected, metadata=metadata)
        updated.validate()
        candidate = copy.deepcopy(self.project)
        candidate.nodes = tuple(
            updated if node.id == selected.id else node for node in candidate.nodes
        )
        candidate.validate()
        return updated

    def record_with_resource(
        self,
        selection: SelectionRef,
        resource_kind: str,
        resource_id: str,
    ) -> EntitySpec | Node3DRecord:
        """Return one validated record with an existing visual resource selected."""

        selected = self.entity(selection)
        resource_id = str(resource_id).strip()
        if not resource_id:
            raise ValueError("Choose a project resource first.")
        if isinstance(self.project, GameProject) and isinstance(selected, EntitySpec):
            if resource_kind != "vector_asset":
                raise ValueError("A 2D object can only choose a vector picture here.")
            if resource_id not in self.project.vector_assets.assets:
                raise ValueError(f"That vector picture is not in this project: {resource_id}")
            components = copy.deepcopy(
                {name: dict(value) for name, value in selected.components.items()}
            )
            renderer = components.get("vector_renderer")
            if not isinstance(renderer, Mapping):
                raise ValueError(f"{selected.id} does not have a picture to change.")
            updated_renderer = copy.deepcopy(dict(renderer))
            updated_renderer["asset_id"] = resource_id
            components["vector_renderer"] = updated_renderer
            updated = replace(selected, components=components)
            updated.validate()
            return updated
        if isinstance(self.project, Mobile3DProject) and isinstance(selected, Node3DRecord):
            if resource_kind == "mesh":
                if resource_id not in self.project.meshes:
                    raise ValueError(f"That 3D shape is not in this project: {resource_id}")
                updated = replace(selected, mesh_id=resource_id)
            elif resource_kind == "material":
                if resource_id not in self.project.materials:
                    raise ValueError(f"That material is not in this project: {resource_id}")
                updated = replace(selected, material_id=resource_id)
            else:
                raise ValueError("A 3D object can only choose a shape or material here.")
            updated.validate()
            return updated
        raise ValueError("Choose a scene object before changing its appearance.")

    def trigger_area_state(
        self, selection: SelectionRef | None = None
    ) -> dict[str, Any] | None:
        """Return one 3D collider as friendly full-size Trigger Area values."""

        if not isinstance(self.project, Mobile3DProject):
            return None
        selected = self.entity(selection)
        if not isinstance(selected, Node3DRecord):
            return None
        collider = selected.collider
        shape = collider.shape if collider.shape in {"sphere", "box"} else "sphere"
        return {
            "enabled": bool(collider.sensor),
            "shape": shape,
            "radius": float(collider.radius),
            "size_x": float(collider.half_extents[0]) * 2.0,
            "size_y": float(collider.half_extents[1]) * 2.0,
            "size_z": float(collider.half_extents[2]) * 2.0,
        }

    def record_with_trigger_area(
        self,
        selection: SelectionRef,
        values: Mapping[str, Any],
    ) -> Node3DRecord:
        """Return one project-validated node with friendly trigger settings."""

        if not isinstance(self.project, Mobile3DProject):
            raise ValueError("Trigger Areas are available in mobile 3D projects.")
        selected = self.entity(selection)
        if not isinstance(selected, Node3DRecord):
            raise ValueError("Choose a 3D object before changing its Trigger Area.")
        enabled_value = values.get("enabled", False)
        if not isinstance(enabled_value, bool):
            raise ValueError("Use as Trigger must be on or off.")
        shape = str(values.get("shape", "sphere")).strip().casefold()
        if shape not in {"sphere", "box"}:
            raise ValueError("Choose Sphere or Box for the Trigger Area shape.")
        try:
            radius = float(values.get("radius", selected.collider.radius))
            size = tuple(
                float(values.get(key, selected.collider.half_extents[index] * 2.0))
                for index, key in enumerate(("size_x", "size_y", "size_z"))
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Trigger Area size values must be numbers.") from exc
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError("Trigger Area radius must be greater than zero.")
        if any(not math.isfinite(value) or value <= 0 for value in size):
            raise ValueError("Every Trigger Area box size must be greater than zero.")
        collider = Collider3DRecord(
            shape,
            radius,
            tuple(value * 0.5 for value in size),
            enabled_value,
        )
        collider.validate()
        updated = replace(selected, collider=collider)
        updated.validate()
        candidate = copy.deepcopy(self.project)
        candidate.nodes = tuple(
            updated if node.id == selected.id else node for node in candidate.nodes
        )
        candidate.validate()
        return updated

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

    def world_graph_ids(self, scene_id: str | None = None) -> tuple[str, ...]:
        """Return the explicitly world-bound graph ids for one authored scene."""

        if isinstance(self.project, GameProject):
            scene = self.scene(scene_id)
            raw = None if scene is None else scene.rules.get("world_graphs")
            where = f"scene {scene_id or self.current_scene_id or ''} world Logic Blocks"
        elif isinstance(self.project, Mobile3DProject):
            raw = self.project.metadata.get("world_graphs")
            where = "mobile 3D world Logic Blocks"
        else:
            return ()
        try:
            return visual_graph_binding_ids(raw, where)
        except (TypeError, ValueError):
            # The editor can open an invalid project so Check Project can explain
            # it.  A malformed binding must not make the whole Scene Tree fail.
            return ()

    def graph_title(self, graph_id: str, scene_id: str | None = None) -> str | None:
        """Return an authored learner-facing graph title when one is available."""

        try:
            if isinstance(self.project, GameProject):
                scene = self.scene(scene_id)
                graphs = () if scene is None else visual_graphs_from_rules(scene.rules)
            elif isinstance(self.project, Mobile3DProject):
                graphs = visual_graphs_from_metadata(self.project.metadata)
            else:
                return None
        except (TypeError, ValueError):
            return None
        graph = next((item for item in graphs if item.id == str(graph_id)), None)
        if graph is None:
            return None
        title = str(graph.metadata.get("title", "")).strip()
        return title or None

    def graph_data(self) -> dict[str, Any]:
        if isinstance(self.project, GameProject):
            scene_id = (
                self.selection.scene_id
                if self.selection is not None and self.selection.kind == "world_graph"
                else None
            )
            scene = self.scene(scene_id)
            values = [] if scene is None else scene.rules.get(GRAPHS_KEY, [])
            legacy = None if scene is None else scene.rules.get(BINDING_KEY)
        elif isinstance(self.project, Mobile3DProject):
            values = self.project.metadata.get(GRAPHS_KEY, [])
            legacy = self.project.metadata.get(BINDING_KEY)
        else:
            values, legacy = [], None
        if not isinstance(values, (list, tuple)):
            values = []
        if not values and isinstance(legacy, Mapping):
            values = [legacy]
        binding = None
        if self.selection is not None and self.selection.kind == "world_graph":
            binding = self.selection.object_id
        else:
            selected = self.entity()
            if isinstance(selected, (EntitySpec, Node3DRecord)):
                binding = selected.metadata.get(BINDING_KEY)
        exact_candidate = next(
            (
                item
                for item in values
                if isinstance(item, Mapping) and item.get("id") == binding
            ),
            None,
        )
        candidate = (
            exact_candidate
            if self.selection is not None
            and self.selection.kind == "world_graph"
            else exact_candidate
            or next((item for item in values if isinstance(item, Mapping)), None)
        )
        if candidate is None:
            if self.selection is not None and self.selection.kind == "world_graph":
                return VisualGraph(id=self.selection.object_id).to_dict()
            base = self.current_scene_id or getattr(self.project, "id", "scene")
            return VisualGraph(id=f"{base}_logic").to_dict()
        raw = copy.deepcopy(dict(candidate))
        # One early editor preview used connections/from_node keys. Migrate it in memory.
        if "connections" in raw and "links" not in raw:
            raw["links"] = [
                {
                    "source_node": item.get("from_node"), "source_port": item.get("from_port"),
                    "target_node": item.get("to_node"), "target_port": item.get("to_port"),
                }
                for item in raw.get("connections", []) if isinstance(item, Mapping)
            ]
            raw.pop("connections", None)
        raw.setdefault("schema", VisualGraph.SCHEMA)
        raw.setdefault("id", f"{self.current_scene_id or 'scene'}_logic")
        raw.setdefault("metadata", {})
        return VisualGraph.from_dict(raw).to_dict()

    def set_graph_data(
        self,
        graph: Mapping[str, Any],
        selection: SelectionRef | None | object = _CURRENT_GRAPH_SELECTION,
    ) -> None:
        context_selection = (
            self.selection
            if selection is _CURRENT_GRAPH_SELECTION
            else selection
        )
        if context_selection is not None and not isinstance(
            context_selection, SelectionRef
        ):
            raise TypeError("Logic graph selection context must be a SelectionRef or None.")
        payload = VisualGraph.from_dict(graph).to_dict()
        graph_id = str(payload["id"])
        if isinstance(self.project, GameProject):
            scene_id = (
                context_selection.scene_id
                if context_selection is not None
                and context_selection.kind == "world_graph"
                else None
            )
            scene = self.scene(scene_id)
            if scene is None:
                return
            rules = copy.deepcopy(dict(scene.rules))
            existing_graph_ids = {
                str(item.get("id")) for item in rules.get(GRAPHS_KEY, [])
                if isinstance(item, Mapping) and item.get("id") is not None
            }
            should_bind = graph_id not in existing_graph_ids
            graphs: list[dict[str, Any]] = []
            replaced = False
            for item in rules.get(GRAPHS_KEY, []):
                if not isinstance(item, Mapping):
                    continue
                if item.get("id") == graph_id:
                    if not replaced:
                        graphs.append(payload)
                        replaced = True
                    continue
                graphs.append(copy.deepcopy(dict(item)))
            if not replaced:
                graphs.append(payload)
            rules[GRAPHS_KEY] = graphs
            rules.pop(BINDING_KEY, None)
            binding_id = None
            if (
                should_bind
                and context_selection is not None
                and context_selection.kind == "entity"
                and context_selection.scene_id in (None, scene.id)
            ):
                binding_id = context_selection.object_id
            if (
                should_bind
                and binding_id is None
                and not (
                    context_selection is not None
                    and context_selection.kind == "world_graph"
                )
            ):
                wanted = str(scene.rules.get("player_id", ""))
                binding_id = wanted if any(item.id == wanted for item in scene.entities) else None
            if (
                should_bind
                and binding_id is None
                and not (
                    context_selection is not None
                    and context_selection.kind == "world_graph"
                )
            ):
                binding_id = next((item.id for item in scene.entities if "transform" in item.components), None)
            entities: list[EntitySpec] = []
            for entity in scene.entities:
                if entity.id == binding_id:
                    metadata = copy.deepcopy(dict(entity.metadata))
                    metadata[BINDING_KEY] = graph_id
                    entity = replace(entity, metadata=metadata)
                entities.append(entity)
            self.project.scenes[scene.id] = replace(scene, rules=rules, entities=tuple(entities))
        elif isinstance(self.project, Mobile3DProject):
            metadata = copy.deepcopy(self.project.metadata)
            existing_graph_ids = {
                str(item.get("id")) for item in metadata.get(GRAPHS_KEY, [])
                if isinstance(item, Mapping) and item.get("id") is not None
            }
            should_bind = graph_id not in existing_graph_ids
            graphs = []
            replaced = False
            for item in metadata.get(GRAPHS_KEY, []):
                if not isinstance(item, Mapping):
                    continue
                if item.get("id") == graph_id:
                    if not replaced:
                        graphs.append(payload)
                        replaced = True
                    continue
                graphs.append(copy.deepcopy(dict(item)))
            if not replaced:
                graphs.append(payload)
            metadata[GRAPHS_KEY] = graphs
            metadata.pop(BINDING_KEY, None)
            self.project.metadata = metadata
            binding_id = (
                context_selection.object_id
                if should_bind
                and context_selection is not None
                and context_selection.kind == "node"
                else None
            )
            world_selection = bool(
                context_selection is not None
                and context_selection.kind == "world_graph"
            )
            if should_bind and binding_id is None and not world_selection:
                binding_id = next((node.id for node in self.project.nodes if "player" in node.tags), None)
            if should_bind and binding_id is None and self.project.nodes and not world_selection:
                binding_id = self.project.nodes[0].id
            nodes: list[Node3DRecord] = []
            for node in self.project.nodes:
                if node.id == binding_id:
                    node_metadata = copy.deepcopy(node.metadata)
                    node_metadata[BINDING_KEY] = graph_id
                    node = replace(node, metadata=node_metadata)
                nodes.append(node)
            self.project.nodes = tuple(nodes)
        else:
            return
        self.set_dirty(True)
        self.graphChanged.emit()

    def logic_trace(
        self, graph_id: str, owner_id: str | None = None
    ) -> LogicTraceSnapshot | None:
        """Return the cached Preview trail for one exact graph/owner binding."""

        return self._logic_traces.get((str(graph_id), None if owner_id is None else str(owner_id)))

    def latest_logic_trace(self, graph_id: str | None = None) -> LogicTraceSnapshot | None:
        """Return the newest useful Preview trail, optionally for one graph."""

        wanted = None if graph_id is None else str(graph_id)
        candidates = (
            snapshot
            for snapshot in self._logic_traces.values()
            if wanted is None or snapshot.graph_id == wanted
        )
        return max(candidates, key=lambda snapshot: snapshot.sequence, default=None)

    def logic_traces(self) -> tuple[LogicTraceSnapshot, ...]:
        """Return all useful Preview trails from oldest to newest."""

        return tuple(sorted(self._logic_traces.values(), key=lambda snapshot: snapshot.sequence))

    def _clear_logic_traces(self) -> None:
        """Clear presentation-only trails without touching project dirty state."""

        self._logic_traces.clear()
        self._logic_trace_results.clear()
        self._logic_trace_sequence = 0
        self.logicTraceChanged.emit(None)

    @staticmethod
    def _useful_logic_result(result: Any) -> bool:
        """Ignore idle event polling while retaining activated flow and errors."""

        if not bool(getattr(result, "completed", True)):
            return True
        return any(
            str(getattr(entry, "status", "ok")) != "ok"
            or bool(getattr(entry, "error", None))
            or bool(getattr(entry, "flow_outputs", ()))
            for entry in getattr(result, "trace", ())
        )

    def _store_logic_trace(
        self,
        graph_id: str,
        owner_id: str | None,
        result: Any,
        *,
        result_marker: object | None = None,
    ) -> bool:
        """Store and announce one useful result exactly once."""

        if not self._useful_logic_result(result):
            return False
        key = (str(graph_id), None if owner_id is None else str(owner_id))
        marker = result if result_marker is None else result_marker
        if self._logic_trace_results.get(key) is marker:
            return False
        trace = tuple(getattr(result, "trace", ()))
        if not all(isinstance(entry, TraceEntry) for entry in trace):
            return False
        self._logic_trace_sequence += 1
        snapshot = LogicTraceSnapshot(
            key[0],
            key[1],
            str(getattr(result, "trigger", "preview")),
            int(getattr(result, "steps", len(trace))),
            trace,
            bool(getattr(result, "completed", True)),
            self._logic_trace_sequence,
        )
        self._logic_trace_results[key] = marker
        self._logic_traces[key] = snapshot
        self.logicTraceChanged.emit(snapshot)
        return True

    def _capture_logic_traces(self) -> bool:
        """Harvest the newest results before a later fixed step can replace them."""

        world = self._runtime_world
        changed = False
        for binding in tuple(getattr(world, "visual_graph_bindings", ()) if world is not None else ()):
            runtime = getattr(binding, "runtime", None)
            result = getattr(runtime, "last_result", None)
            graph = getattr(runtime, "graph", None)
            graph_id = getattr(graph, "id", None)
            if result is None or not graph_id:
                continue
            changed = self._store_logic_trace(
                str(graph_id), getattr(binding, "entity_id", None), result
            ) or changed
        return changed

    def _authored_logic_graphs(self) -> tuple[VisualGraph, ...]:
        """Return graphs solely to identify a Ready error from a partial build."""

        try:
            if isinstance(self.project, GameProject):
                scene = self.scene()
                return () if scene is None else visual_graphs_from_rules(scene.rules)
            if isinstance(self.project, Mobile3DProject):
                return visual_graphs_from_metadata(self.project.metadata)
        except (TypeError, ValueError):
            pass
        return ()

    def _logic_graph_owners(self, graph_id: str) -> tuple[str | None, ...]:
        """Resolve authored owners for a trace raised before a world was returned."""

        owners: list[str | None] = []
        if isinstance(self.project, GameProject):
            scene = self.scene()
            if scene is None:
                return ()
            try:
                if graph_id in visual_graph_binding_ids(
                    scene.rules.get("world_graphs"), "world Logic Blocks"
                ):
                    owners.append(None)
                for entity in scene.entities:
                    if graph_id in visual_graph_binding_ids(
                        entity.metadata.get(BINDING_KEY), f"{entity.id} Logic Blocks"
                    ):
                        owners.append(entity.id)
            except (TypeError, ValueError):
                return tuple(owners)
        elif isinstance(self.project, Mobile3DProject):
            try:
                if graph_id in visual_graph_binding_ids(
                    self.project.metadata.get("world_graphs"), "world Logic Blocks"
                ):
                    owners.append(None)
                for node in self.project.nodes:
                    if graph_id in visual_graph_binding_ids(
                        node.metadata.get(BINDING_KEY), f"{node.id} Logic Blocks"
                    ):
                        owners.append(node.id)
            except (TypeError, ValueError):
                return tuple(owners)
        return tuple(owners)

    def _capture_unbound_logic_error(
        self, error: GraphExecutionError, trigger: str
    ) -> bool:
        """Keep a Ready trace even if project instantiation never returned a world."""

        trace = tuple(error.trace)
        if not trace:
            return False
        traced_nodes = {entry.node_id for entry in trace}
        candidates = [
            graph
            for graph in self._authored_logic_graphs()
            if traced_nodes.issubset({node.id for node in graph.nodes})
        ]
        if not candidates:
            return False
        current_id = str(self.graph_data().get("id", ""))
        graph = next((item for item in candidates if item.id == current_id), candidates[0])
        owners = self._logic_graph_owners(graph.id)
        owner: str | None = None
        traced_owner = next(
            (
                str(value)
                for entry in trace
                for values in (entry.outputs, entry.inputs)
                if (value := values.get("entity")) not in (None, "")
            ),
            None,
        )
        if traced_owner in owners:
            owner = traced_owner
        elif self.selection is not None and self.selection.object_id in owners:
            owner = self.selection.object_id
        elif len(owners) == 1:
            owner = owners[0]

        class _IncompleteResult:
            completed = False

            def __init__(self) -> None:
                self.trigger = trigger
                self.trace = trace
                self.steps = max((entry.step for entry in trace), default=0)

        return self._store_logic_trace(
            graph.id, owner, _IncompleteResult(), result_marker=error
        )

    def begin_play(self) -> None:
        self._clear_logic_traces()
        self.play_warnings = []
        self._runtime_world = None
        try:
            if isinstance(self.project, GameProject):
                self._runtime_world = self.project.instantiate_world(self.current_scene_id)
            elif isinstance(self.project, Mobile3DProject):
                self._runtime_world = self.project.instantiate_world()
            else:
                raise RuntimeError("Open a project before pressing Play.")
            self._previous_input = None
        except GraphExecutionError as exc:
            self._capture_unbound_logic_error(exc, "ready")
            raise
        finally:
            self._capture_logic_traces()

    def stop_play(self) -> None:
        self._runtime_world = None
        self._previous_input = None

    def step_play(self, pressed_keys: set[str]) -> tuple[dict[str, dict[str, Any]], tuple[Any, ...]]:
        """Advance the real reference runtime and return render-friendly transforms."""

        if self._runtime_world is None:
            return {}, ()
        try:
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
                state["__world__"] = copy.deepcopy(self._runtime_world.state)
                return state, events
            frame3d = InputFrame3D(
                float(right) - float(left),
                float(down) - float(up),
                jump=bool({"space", "j"} & pressed_keys),
                action=bool({"space", "enter", "shift"} & pressed_keys),
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
            state["__world__"] = copy.deepcopy(self._runtime_world.state)
            return state, events
        finally:
            # Trigger graphs run after pre-physics and are replaced by the next
            # fixed-step poll, so the editor must harvest them before returning.
            self._capture_logic_traces()


__all__ = [
    "BINDING_KEY",
    "EditorDocument",
    "GRAPHS_KEY",
    "LogicTraceSnapshot",
    "SelectionRef",
    "euler_degrees_to_quaternion",
    "quaternion_to_euler_degrees",
]
