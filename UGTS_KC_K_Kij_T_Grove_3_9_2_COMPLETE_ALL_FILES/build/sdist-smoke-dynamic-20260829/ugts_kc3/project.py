"""Serializable game-project model shared by Python simulation and HTML5 builds."""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .audio import AudioBank
from .game import GameWorld, component_from_dict
from .game_input import InputMap
from .tilemap import TileMap
from .vector2d import VectorLibrary
from .version import __codename__, __game_project_schema__, __version__
from .packed_kinematics import (
    attach_packed_kinematics,
    pack_ecs_document,
    packed_kinematic_codecs_from_dict,
    unpack_ecs_document,
)
from .visual_graph import VisualGraph, attach_graph, run_ready_batch

_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9._-]*$")


def visual_graphs_from_rules(rules: Mapping[str, Any]) -> tuple[VisualGraph, ...]:
    """Load the additive graph resources accepted by a 2D scene.

    ``visual_graphs`` is normally a list.  A mapping keyed by graph id is also
    accepted because it is convenient for hand-authored JSON.  The earlier
    editor preview's singular ``visual_graph`` key remains readable.
    """
    raw: Any = rules.get("visual_graphs")
    if raw is None and "visual_graph" in rules:
        raw = [rules["visual_graph"]]
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        if "nodes" in raw or "schema" in raw:
            items = [raw]
        else:
            items = []
            for graph_id, value in sorted(raw.items(), key=lambda pair: str(pair[0])):
                if not isinstance(value, Mapping):
                    raise TypeError(f"visual graph {graph_id!r} must be an object")
                item = dict(value)
                item.setdefault("id", str(graph_id))
                items.append(item)
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise TypeError("scene rules.visual_graphs must be a list or object")
    graphs = tuple(
        item if isinstance(item, VisualGraph) else VisualGraph.from_dict(item)
        for item in items
    )
    ids = [graph.id for graph in graphs]
    if len(ids) != len(set(ids)):
        raise ValueError("scene contains duplicate visual graph ids")
    return tuple(sorted(graphs, key=lambda graph: graph.id))


def visual_graph_binding_ids(raw: Any, label: str = "visual graph binding") -> tuple[str, ...]:
    """Normalize one graph id or a list of ids without iterating text as characters."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = (raw,)
    elif isinstance(raw, (list, tuple)) and all(isinstance(item, str) for item in raw):
        values = tuple(raw)
    else:
        raise TypeError(f"{label} must be text or a list of text graph ids")
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{label} cannot contain an empty graph id")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} cannot contain the same graph id more than once")
    return normalized


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


@dataclass(frozen=True)
class ProjectMetadata:
    id: str
    title: str
    author: str = ""
    version: str = "0.1.0"
    runtime_version: str = __version__
    codename: str = __codename__
    description: str = ""
    license: str = "All rights reserved"
    website: str | None = None

    def validate(self) -> None:
        if not _PROJECT_ID_RE.match(self.id):
            raise ValueError("project id must begin with a lowercase letter and contain lowercase letters, digits, '.', '_' or '-'")
        if not self.title.strip():
            raise ValueError("project title is required")
        if not self.version.strip():
            raise ValueError("project version is required")
        if self.runtime_version.split(".")[0] != __version__.split(".")[0]:
            raise ValueError("project targets an incompatible runtime major version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "version": self.version,
            "runtime_version": self.runtime_version,
            "codename": self.codename,
            "description": self.description,
            "license": self.license,
            "website": self.website,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectMetadata":
        metadata = cls(
            str(data["id"]),
            str(data["title"]),
            str(data.get("author", "")),
            str(data.get("version", "0.1.0")),
            str(data.get("runtime_version", __version__)),
            str(data.get("codename", __codename__)),
            str(data.get("description", "")),
            str(data.get("license", "All rights reserved")),
            data.get("website"),
        )
        metadata.validate()
        return metadata


@dataclass(frozen=True)
class DisplaySettings:
    width: int = 960
    height: int = 540
    background: str = "#101427"
    scaling: str = "fit"
    pixel_ratio: str = "device"
    fullscreen: bool = False
    orientation: str = "landscape"
    antialias: bool = True

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("display dimensions must be positive")
        if self.width > 16384 or self.height > 16384:
            raise ValueError("display dimensions exceed the reference-runtime limit")
        if self.scaling not in {"fit", "fill", "stretch", "integer"}:
            raise ValueError("unsupported display scaling mode")
        if self.pixel_ratio not in {"device", "1", "2"}:
            raise ValueError("pixel_ratio must be device, 1 or 2")
        if self.orientation not in {"landscape", "portrait", "any"}:
            raise ValueError("orientation must be landscape, portrait or any")
        if not self.background:
            raise ValueError("display background is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "background": self.background,
            "scaling": self.scaling,
            "pixel_ratio": self.pixel_ratio,
            "fullscreen": self.fullscreen,
            "orientation": self.orientation,
            "antialias": self.antialias,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DisplaySettings":
        display = cls(
            int(data.get("width", 960)),
            int(data.get("height", 540)),
            str(data.get("background", "#101427")),
            str(data.get("scaling", "fit")),
            str(data.get("pixel_ratio", "device")),
            bool(data.get("fullscreen", False)),
            str(data.get("orientation", "landscape")),
            bool(data.get("antialias", True)),
        )
        display.validate()
        return display


@dataclass(frozen=True)
class EntitySpec:
    id: str
    components: Mapping[str, Mapping[str, Any]]
    tags: frozenset[str] = frozenset()
    active: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("entity spec id is required")
        if "transform" not in self.components and "camera" not in self.components:
            raise ValueError(f"entity {self.id} requires a transform or camera component")
        for name, data in self.components.items():
            if not isinstance(data, Mapping):
                raise TypeError(f"component {name} on {self.id} must be an object")
            component = component_from_dict(name, data)
            validate = getattr(component, "validate", None)
            if callable(validate):
                validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tags": sorted(self.tags),
            "active": self.active,
            "metadata": copy.deepcopy(dict(self.metadata)),
            "components": copy.deepcopy({name: dict(data) for name, data in sorted(self.components.items())}),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntitySpec":
        spec = cls(
            str(data["id"]),
            {str(name): copy.deepcopy(dict(component)) for name, component in data.get("components", {}).items()},
            frozenset(str(tag) for tag in data.get("tags", [])),
            bool(data.get("active", True)),
            copy.deepcopy(dict(data.get("metadata", {}))),
        )
        spec.validate()
        return spec


@dataclass(frozen=True)
class GameSceneSpec:
    id: str
    entities: tuple[EntitySpec, ...]
    world_size: tuple[float, float] = (1600.0, 900.0)
    background: str | None = None
    tilemaps: tuple[str, ...] = ()
    initial_state: Mapping[str, Any] = field(default_factory=lambda: {"score": 0})
    rules: Mapping[str, Any] = field(default_factory=dict)
    ui: tuple[Mapping[str, Any], ...] = ()

    def validate(self) -> None:
        if not self.id:
            raise ValueError("scene id is required")
        if len(self.world_size) != 2 or any(not math.isfinite(float(v)) or float(v) <= 0 for v in self.world_size):
            raise ValueError("scene world_size must contain two positive finite values")
        ids = [entity.id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError(f"scene {self.id} contains duplicate entity ids")
        for entity in self.entities:
            entity.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "world_size": list(self.world_size),
            "background": self.background,
            "tilemaps": list(self.tilemaps),
            "initial_state": copy.deepcopy(dict(self.initial_state)),
            "rules": copy.deepcopy(dict(self.rules)),
            "ui": [copy.deepcopy(dict(item)) for item in self.ui],
            "entities": [entity.to_dict() for entity in self.entities],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GameSceneSpec":
        scene = cls(
            str(data["id"]),
            tuple(EntitySpec.from_dict(item) for item in data.get("entities", [])),
            tuple(float(v) for v in data.get("world_size", (1600, 900))),  # type: ignore[arg-type]
            data.get("background"),
            tuple(str(item) for item in data.get("tilemaps", [])),
            copy.deepcopy(dict(data.get("initial_state", {"score": 0}))),
            copy.deepcopy(dict(data.get("rules", {}))),
            tuple(copy.deepcopy(dict(item)) for item in data.get("ui", [])),
        )
        scene.validate()
        return scene


@dataclass(frozen=True)
class ProjectIssue:
    severity: str
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class ProjectValidationReport:
    issues: tuple[ProjectIssue, ...]
    metrics: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [issue.__dict__ for issue in self.issues],
            "metrics": dict(self.metrics),
        }


class GameProject:
    def __init__(
        self,
        metadata: ProjectMetadata,
        display: DisplaySettings | None = None,
        input_map: InputMap | None = None,
        vector_assets: VectorLibrary | None = None,
        audio: AudioBank | None = None,
        tilemaps: Iterable[TileMap] = (),
        scenes: Iterable[GameSceneSpec] = (),
        start_scene: str | None = None,
        build: Mapping[str, Any] | None = None,
    ):
        self.metadata = metadata
        self.display = display or DisplaySettings()
        self.input_map = input_map or InputMap()
        self.vector_assets = vector_assets or VectorLibrary()
        self.audio = audio or AudioBank()
        self.tilemaps: dict[str, TileMap] = {}
        self.scenes: dict[str, GameSceneSpec] = {}
        for tilemap in tilemaps:
            if tilemap.id in self.tilemaps:
                raise ValueError(f"duplicate tilemap id: {tilemap.id}")
            self.tilemaps[tilemap.id] = tilemap
        for scene in scenes:
            if scene.id in self.scenes:
                raise ValueError(f"duplicate scene id: {scene.id}")
            self.scenes[scene.id] = scene
        self.start_scene = start_scene or (sorted(self.scenes)[0] if self.scenes else "")
        self.build = copy.deepcopy(dict(build or {"single_file": True, "minify": False, "debug": False}))

    def validate(self, raise_on_error: bool = True) -> ProjectValidationReport:
        issues: list[ProjectIssue] = []

        def capture(path: str, code: str, callback) -> None:
            try:
                callback()
            except Exception as exc:  # Validation needs to aggregate independent problems.
                issues.append(ProjectIssue("error", code, str(exc), path))

        capture("metadata", "metadata.invalid", self.metadata.validate)
        capture("display", "display.invalid", self.display.validate)
        capture("input", "input.invalid", self.input_map.validate)
        capture("audio", "audio.invalid", self.audio.validate)
        if not self.vector_assets.assets:
            issues.append(ProjectIssue("warning", "assets.empty", "project has no vector assets", "vector_assets"))
        for asset in self.vector_assets:
            capture(f"vector_assets.{asset.id}", "asset.invalid", asset.validate)
        if not self.scenes:
            issues.append(ProjectIssue("error", "scenes.empty", "project requires at least one scene", "scenes"))
        if self.start_scene not in self.scenes:
            issues.append(ProjectIssue("error", "start_scene.unknown", f"unknown start scene: {self.start_scene}", "start_scene"))
        for tilemap_id, tilemap in sorted(self.tilemaps.items()):
            for layer in tilemap.layers.values():
                capture(
                    f"tilemaps.{tilemap_id}.layers.{layer.name}",
                    "tilemap.invalid",
                    lambda current_layer=layer: current_layer.__post_init__(),
                )
        entity_total = 0
        graph_total = 0
        graph_binding_total = 0
        packed_profile_data = self.build.get("packed_kinematic_profiles", {})
        packed_profile_ids = {"default"}
        if not isinstance(packed_profile_data, Mapping):
            issues.append(ProjectIssue(
                "error", "packed_kinematic.profiles_type",
                "build.packed_kinematic_profiles must be an object",
                "build.packed_kinematic_profiles",
            ))
            packed_profile_data = {}
        try:
            packed_profile_ids = set(
                packed_kinematic_codecs_from_dict(packed_profile_data)
            )
        except (TypeError, ValueError) as exc:
            issues.append(ProjectIssue(
                "error", "packed_kinematic.profile_invalid", str(exc),
                "build.packed_kinematic_profiles",
            ))
        for scene_id, scene in sorted(self.scenes.items()):
            capture(f"scenes.{scene_id}", "scene.invalid", scene.validate)
            entity_total += len(scene.entities)
            graphs: tuple[VisualGraph, ...] = ()
            try:
                graphs = visual_graphs_from_rules(scene.rules)
                for graph in graphs:
                    graph.validate()
                graph_total += len(graphs)
            except (TypeError, ValueError) as exc:
                issues.append(ProjectIssue(
                    "error", "visual_graph.invalid", str(exc),
                    f"scenes.{scene_id}.rules.visual_graphs",
                ))
            graph_ids = {graph.id for graph in graphs}
            try:
                world_bindings = visual_graph_binding_ids(
                    scene.rules.get("world_graphs"),
                    f"scene {scene_id} world_graphs",
                )
                graph_binding_total += len(world_bindings)
                for graph_id in world_bindings:
                    if graph_id not in graph_ids:
                        issues.append(ProjectIssue(
                            "error", "visual_graph.unknown",
                            f"scene {scene_id} references unknown world visual graph {graph_id}",
                            f"scenes.{scene_id}.rules.world_graphs",
                        ))
            except (TypeError, ValueError) as exc:
                issues.append(ProjectIssue(
                    "error", "visual_graph.binding_type", str(exc),
                    f"scenes.{scene_id}.rules.world_graphs",
                ))
            for tilemap_id in scene.tilemaps:
                if tilemap_id not in self.tilemaps:
                    issues.append(ProjectIssue("error", "tilemap.unknown", f"scene references unknown tilemap {tilemap_id}", f"scenes.{scene_id}.tilemaps"))
            for entity in scene.entities:
                try:
                    bindings = visual_graph_binding_ids(
                        entity.metadata.get("visual_graph"),
                        f"entity {entity.id} visual_graph binding",
                    )
                    graph_binding_total += len(bindings)
                    for graph_id in bindings:
                        if graph_id not in graph_ids:
                            issues.append(ProjectIssue(
                                "error", "visual_graph.unknown",
                                f"entity {entity.id} references unknown visual graph {graph_id}",
                                f"scenes.{scene_id}.entities.{entity.id}.metadata.visual_graph",
                            ))
                except (TypeError, ValueError) as exc:
                    issues.append(ProjectIssue(
                        "error", "visual_graph.binding_type", str(exc),
                        f"scenes.{scene_id}.entities.{entity.id}.metadata.visual_graph",
                    ))
                renderer = entity.components.get("vector_renderer")
                if renderer and renderer.get("asset_id") not in self.vector_assets.assets:
                    issues.append(
                        ProjectIssue(
                            "error",
                            "asset.unknown",
                            f"entity {entity.id} references unknown vector asset {renderer.get('asset_id')}",
                            f"scenes.{scene_id}.entities.{entity.id}.components.vector_renderer",
                        )
                    )
                for component_name, component in entity.components.items():
                    if component_name == "packed_kinematic" and isinstance(component, Mapping):
                        profile_id = str(component.get("profile", "default"))
                        if profile_id not in packed_profile_ids:
                            issues.append(ProjectIssue(
                                "error", "packed_kinematic.profile_unknown",
                                f"entity {entity.id} references unknown packed kinematic profile {profile_id}",
                                f"scenes.{scene_id}.entities.{entity.id}.components.packed_kinematic.profile",
                            ))
                    sound = component.get("sound") if isinstance(component, Mapping) else None
                    if sound is not None and sound not in self.audio.cues:
                        issues.append(ProjectIssue("error", "audio.unknown", f"entity {entity.id} references unknown sound cue {sound}", f"scenes.{scene_id}.entities.{entity.id}.components.{component_name}"))
        report = ProjectValidationReport(
            tuple(issues),
            {
                "scene_count": len(self.scenes),
                "entity_count": entity_total,
                "vector_asset_count": len(self.vector_assets.assets),
                "audio_cue_count": len(self.audio.cues),
                "tilemap_count": len(self.tilemaps),
                "action_count": len(self.input_map.actions),
                "visual_graph_count": graph_total,
                "visual_graph_binding_count": graph_binding_total,
                "packed_kinematic_profile_count": len(packed_profile_ids),
            },
        )
        if raise_on_error and not report.passed:
            messages = "; ".join(f"{issue.path}: {issue.message}" for issue in report.issues if issue.severity == "error")
            raise ValueError(messages)
        return report

    def instantiate_world(self, scene_id: str | None = None, *, fixed_dt: float = 1.0 / 60.0) -> GameWorld:
        self.validate()
        scene = self.scenes[scene_id or self.start_scene]
        world = GameWorld(fixed_dt=fixed_dt, gravity=scene.rules.get("gravity", (0, 0)))
        world.state = copy.deepcopy(dict(scene.initial_state))
        world.state.setdefault("scene", scene.id)
        world.state.setdefault("score", 0)
        for spec in scene.entities:
            entity = world.spawn(spec.id, tags=spec.tags, metadata=spec.metadata, emit_event=False)
            entity.active = spec.active
            for name, data in spec.components.items():
                world.add_component(spec.id, component_from_dict(name, data), name)
        attach_packed_kinematics(
            world,
            codecs=packed_kinematic_codecs_from_dict(
                self.build.get("packed_kinematic_profiles", {})
            ),
        )
        graphs = {graph.id: graph for graph in visual_graphs_from_rules(scene.rules)}
        bindings = []
        for spec in scene.entities:
            graph_ids = visual_graph_binding_ids(
                spec.metadata.get("visual_graph"),
                f"entity {spec.id} visual_graph binding",
            )
            for graph_id in sorted(graph_ids):
                bindings.append(attach_graph(
                    world,
                    graphs[str(graph_id)],
                    entity_id=spec.id,
                    name=f"visual_graph:{scene.id}:{spec.id}:{graph_id}",
                    run_ready=False,
                ))
        for graph_id in sorted(
            visual_graph_binding_ids(
                scene.rules.get("world_graphs"), f"scene {scene.id} world_graphs"
            )
        ):
            bindings.append(attach_graph(
                world,
                graphs[str(graph_id)],
                name=f"visual_graph:{scene.id}:world:{graph_id}",
                run_ready=False,
            ))
        run_ready_batch(bindings)
        world.visual_graph_bindings = bindings
        return world

    def to_dict(self) -> dict[str, Any]:
        data = {
            "$schema": __game_project_schema__,
            "metadata": self.metadata.to_dict(),
            "display": self.display.to_dict(),
            "input": self.input_map.to_dict(),
            "vector_assets": self.vector_assets.to_dict(),
            "audio": self.audio.to_dict(),
            "tilemaps": {tilemap_id: tilemap.to_dict() for tilemap_id, tilemap in sorted(self.tilemaps.items())},
            "scenes": {scene_id: scene.to_dict() for scene_id, scene in sorted(self.scenes.items())},
            "start_scene": self.start_scene,
            "build": copy.deepcopy(self.build),
        }
        return _normalize_json_numbers(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], validate: bool = True) -> "GameProject":
        schema = data.get("$schema", __game_project_schema__)
        if schema != __game_project_schema__:
            raise ValueError(f"unsupported project schema: {schema}")
        vector_data = data.get("vector_assets", {})
        project = cls(
            ProjectMetadata.from_dict(data["metadata"]),
            DisplaySettings.from_dict(data.get("display", {})),
            InputMap.from_dict(data.get("input", {})),
            VectorLibrary.from_dict(vector_data),
            AudioBank.from_dict(data.get("audio", {})),
            (TileMap.from_dict(item) for item in data.get("tilemaps", {}).values()),
            (GameSceneSpec.from_dict(item) for item in data.get("scenes", {}).values()),
            str(data.get("start_scene", "")),
            data.get("build", {}),
        )
        if validate:
            project.validate()
        return project

    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    def write(self, path: str | Path, *, validate: bool = True) -> Path:
        if validate:
            self.validate()
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output

    def write_packed(self, path: str | Path, *, validate: bool = True) -> Path:
        """Write the same editable project as a compact, checksummed ECS archive."""
        if validate:
            self.validate()
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(pack_ecs_document(self.to_dict()))
        return output

    @classmethod
    def load(cls, path: str | Path, *, validate: bool = True) -> "GameProject":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), validate=validate)

    @classmethod
    def load_packed(cls, path: str | Path, *, validate: bool = True) -> "GameProject":
        """Load a project written by :meth:`write_packed`."""
        return cls.from_dict(unpack_ecs_document(Path(path).read_bytes()), validate=validate)
