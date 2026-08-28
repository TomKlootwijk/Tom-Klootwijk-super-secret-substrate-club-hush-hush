"""Ready-to-build project templates for the KC Elizabeth game stack."""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from typing import Iterable

from .audio import AudioBank, Envelope, MusicSequence, SequenceNote, SoundCue
from .game_input import ActionDefinition, InputBinding, InputMap
from .project import DisplaySettings, EntitySpec, GameProject, GameSceneSpec, ProjectMetadata
from .vector2d import (
    GradientStop,
    LinearGradient,
    RadialGradient,
    VectorAsset2D,
    VectorLibrary,
    VectorPaint,
    VectorPath,
    VectorPathBuilder,
    polygon_path,
    rectangle_asset,
    star_asset,
)

PLAYER_LAYER = 1
WORLD_LAYER = 2
PICKUP_LAYER = 4
HAZARD_LAYER = 8


def _input_map() -> InputMap:
    actions = [
        ActionDefinition(
            "move_x",
            (
                InputBinding("key", "KeyA", -1), InputBinding("key", "KeyD", 1),
                InputBinding("key", "ArrowLeft", -1), InputBinding("key", "ArrowRight", 1),
                InputBinding("gamepad_axis", "0", 1), InputBinding("touch_axis", "move_x", 1),
            ),
            deadzone=0.12,
        ),
        ActionDefinition(
            "move_y",
            (
                InputBinding("key", "KeyW", -1), InputBinding("key", "KeyS", 1),
                InputBinding("key", "ArrowUp", -1), InputBinding("key", "ArrowDown", 1),
                InputBinding("gamepad_axis", "1", 1), InputBinding("touch_axis", "move_y", 1),
            ),
            deadzone=0.12,
        ),
        ActionDefinition("dash", (InputBinding("key", "Space"), InputBinding("key", "ShiftLeft"), InputBinding("gamepad_button", "0"), InputBinding("touch_axis", "dash")), deadzone=0.0),
        ActionDefinition("pause", (InputBinding("key", "Escape"), InputBinding("key", "KeyP"), InputBinding("gamepad_button", "9")), deadzone=0.0),
        ActionDefinition("restart", (InputBinding("key", "KeyR"),), deadzone=0.0),
        ActionDefinition("mute", (InputBinding("key", "KeyM"),), deadzone=0.0),
        ActionDefinition("save", (InputBinding("key", "KeyK"),), deadzone=0.0),
        ActionDefinition("load", (InputBinding("key", "KeyL"),), deadzone=0.0),
    ]
    return InputMap(actions)


def _circle_path(path_id: str, radius: float, paint: VectorPaint) -> VectorPath:
    k = radius * 0.5522847498307936
    return (
        VectorPathBuilder(path_id, paint)
        .move_to(radius, 0)
        .cubic_to(radius, k, k, radius, 0, radius)
        .cubic_to(-k, radius, -radius, k, -radius, 0)
        .cubic_to(-radius, -k, -k, -radius, 0, -radius)
        .cubic_to(k, -radius, radius, -k, radius, 0)
        .close()
        .build()
    )


def _player_asset() -> VectorAsset2D:
    gradients = (
        LinearGradient("player-body", (-34, -30), (32, 34), (GradientStop(0, "#75f6ff"), GradientStop(0.48, "#4aa5ff"), GradientStop(1, "#8b6cff"))),
        RadialGradient("player-core", (0, 0), 22, (GradientStop(0, "#ffffff"), GradientStop(0.32, "#c4fbff"), GradientStop(1, "#49d8ff"))),
    )
    body = polygon_path("body", [(0, -34), (30, 19), (11, 14), (0, 31), (-11, 14), (-30, 19)], VectorPaint(fill="@player-body", stroke="#d9fbff", stroke_width=2.2))
    core = _circle_path("core", 10, VectorPaint(fill="@player-core", stroke="#ffffff", stroke_width=1.2, opacity=0.95))
    wing_left = polygon_path("wing-left", [(-8, 10), (-31, 25), (-14, 2)], VectorPaint(fill="#3848af", stroke="#88b9ff", stroke_width=1.2))
    wing_right = polygon_path("wing-right", [(8, 10), (31, 25), (14, 2)], VectorPaint(fill="#3848af", stroke="#88b9ff", stroke_width=1.2))
    asset = VectorAsset2D("player_ship", (80, 80), (0, 0), (wing_left, wing_right, body, core), gradients, {"role": "player"})
    asset.validate()
    return asset


def _crystal_asset() -> VectorAsset2D:
    gradients = (
        LinearGradient("crystal-main", (-22, -28), (22, 28), (GradientStop(0, "#fff6a5"), GradientStop(0.4, "#ffd44f"), GradientStop(1, "#ff8f3d"))),
        RadialGradient("crystal-core", (0, -2), 16, (GradientStop(0, "#ffffff"), GradientStop(0.45, "#fff9bf"), GradientStop(1, "#ffb23f"))),
    )
    body = polygon_path("body", [(0, -30), (20, -6), (13, 24), (0, 33), (-13, 24), (-20, -6)], VectorPaint(fill="@crystal-main", stroke="#fffbd3", stroke_width=2))
    facet = polygon_path("facet", [(0, -25), (9, -4), (0, 23), (-9, -4)], VectorPaint(fill="@crystal-core", stroke="#ffffff", stroke_width=0.8, opacity=0.82))
    asset = VectorAsset2D("crystal", (72, 72), (0, 0), (body, facet), gradients, {"role": "collectible"})
    asset.validate()
    return asset


def _hazard_asset() -> VectorAsset2D:
    gradients = (
        RadialGradient("hazard-core", (-5, -7), 33, (GradientStop(0, "#ffd0d6"), GradientStop(0.22, "#ff647e"), GradientStop(0.72, "#bb164c"), GradientStop(1, "#450526"))),
    )
    outer = _circle_path("outer", 31, VectorPaint(fill="@hazard-core", stroke="#ff9ab0", stroke_width=2.5))
    inner = _circle_path("inner", 13, VectorPaint(fill="#29051c", stroke="#ff7390", stroke_width=2, opacity=0.96))
    spikes = polygon_path(
        "spikes",
        [(math.cos(-math.pi / 2 + i * math.pi / 6) * (40 if i % 2 == 0 else 28), math.sin(-math.pi / 2 + i * math.pi / 6) * (40 if i % 2 == 0 else 28)) for i in range(12)],
        VectorPaint(fill="#8f1244", stroke="#ff6b89", stroke_width=1.3, opacity=0.9),
    )
    asset = VectorAsset2D("hazard_orb", (90, 90), (0, 0), (spikes, outer, inner), gradients, {"role": "hazard"})
    asset.validate()
    return asset


def _obstacle_asset() -> VectorAsset2D:
    base = rectangle_asset("obstacle", 120, 72, fill="#263a72", stroke="#607cc5", corner_radius=14)
    gradient = LinearGradient("obstacle-main", (-60, -36), (60, 36), (GradientStop(0, "#304b8d"), GradientStop(0.5, "#203362"), GradientStop(1, "#121d43")))
    body = replace(base.paths[0], paint=replace(base.paths[0].paint, fill="@obstacle-main", stroke="#718ed7", stroke_width=2))
    inset = rectangle_asset("inset", 96, 48, fill="#172653", stroke="#4667ac", corner_radius=10).paths[0]
    asset = VectorAsset2D("obstacle", (120, 72), (0, 0), (body, replace(inset, id="inset")), (gradient,), {"role": "world"})
    asset.validate()
    return asset


def _portal_asset() -> VectorAsset2D:
    gradients = (
        RadialGradient("portal", (0, 0), 48, (GradientStop(0, "rgba(255,255,255,0)"), GradientStop(0.45, "#7b5cff"), GradientStop(0.75, "#35d4ff"), GradientStop(1, "rgba(20,30,90,0)"))),
    )
    ring = _circle_path("ring", 43, VectorPaint(fill=None, stroke="@portal", stroke_width=12, opacity=0.88))
    core = _circle_path("core", 22, VectorPaint(fill="#12295d", stroke="#74ecff", stroke_width=2, opacity=0.55))
    asset = VectorAsset2D("portal", (104, 104), (0, 0), (ring, core), gradients, {"role": "decoration"})
    asset.validate()
    return asset


def _vector_library() -> VectorLibrary:
    return VectorLibrary((_player_asset(), _crystal_asset(), _hazard_asset(), _obstacle_asset(), _portal_asset()))


def _audio_bank() -> AudioBank:
    cues = [
        SoundCue.from_note("collect", "E6", waveform="triangle", duration=0.11, volume=0.18, sweep_to=note_frequency_safe("B6"), envelope=Envelope(0.002, 0.025, 0.45, 0.09)),
        SoundCue.from_note("dash", "A3", waveform="sawtooth", duration=0.09, volume=0.13, sweep_to=note_frequency_safe("A5"), envelope=Envelope(0.002, 0.02, 0.3, 0.06)),
        SoundCue.from_note("damage", "C3", waveform="square", duration=0.14, volume=0.12, sweep_to=note_frequency_safe("F2"), envelope=Envelope(0.001, 0.03, 0.35, 0.12), noise=0.2),
        SoundCue.from_note("win", "C5", waveform="triangle", duration=0.45, volume=0.17, sweep_to=note_frequency_safe("C6"), envelope=Envelope(0.01, 0.08, 0.7, 0.3)),
        SoundCue.from_note("game_over", "D3", waveform="sine", duration=0.5, volume=0.16, sweep_to=note_frequency_safe("A2"), envelope=Envelope(0.01, 0.1, 0.55, 0.35)),
        SoundCue.from_note("save", "G5", waveform="sine", duration=0.08, volume=0.1, envelope=Envelope(0.002, 0.015, 0.5, 0.05)),
        SoundCue.from_note("music_pluck", "C5", waveform="sine", duration=0.12, volume=0.025, envelope=Envelope(0.005, 0.04, 0.25, 0.1)),
    ]
    sequence = MusicSequence(
        "garden_pulse",
        96,
        8,
        (
            SequenceNote(0, "music_pluck", 1.0, 0.55),
            SequenceNote(2, "music_pluck", 1.25, 0.42),
            SequenceNote(4, "music_pluck", 1.5, 0.5),
            SequenceNote(6, "music_pluck", 1.25, 0.42),
        ),
    )
    return AudioBank(cues, (sequence,))


def note_frequency_safe(note: str) -> float:
    # Local import avoids adding note helpers to the template's public surface.
    from .audio import note_frequency
    return note_frequency(note)


def _entity(entity_id: str, components: dict, tags: Iterable[str] = (), metadata: dict | None = None) -> EntitySpec:
    return EntitySpec(entity_id, components, frozenset(tags), True, metadata or {})


def elizabeth_vector_quest_project(author: str = "Tom Klootwijk") -> GameProject:
    vector_assets = _vector_library()
    audio = _audio_bank()
    entities: list[EntitySpec] = []
    bounds = {"type": "aabb", "minimum": [45, 45], "maximum": [1555, 855]}
    entities.append(
        _entity(
            "player",
            {
                "transform": {"position": [170, 450], "rotation": math.pi / 2, "scale": [1, 1]},
                "body": {"body_type": "dynamic", "mass": 1, "damping": 1.5, "gravity_scale": 0, "restitution": 0.15, "friction": 0.15, "max_speed": 560, "fixed_rotation": True},
                "collider": {"shape": {"type": "circle", "center": [0, 0], "radius": 19}, "filter": {"layer": PLAYER_LAYER, "mask": WORLD_LAYER | PICKUP_LAYER | HAZARD_LAYER, "sensor": False}},
                "vector_renderer": {"asset_id": "player_ship", "z_index": 20, "shadow_blur": 18, "shadow_color": "rgba(70,190,255,.5)"},
                "player_controller": {"x_action": "move_x", "y_action": "move_y", "speed": 245, "dash_action": "dash", "dash_speed": 590, "dash_duration": 0.13, "dash_cooldown": 0.62, "last_direction": [1, 0]},
                "health": {"current": 5, "maximum": 5, "invulnerability": 0.7},
                "bounds_constraint": {"bounds": bounds, "mode": "clamp"},
            },
            tags=("player", "controllable"),
            metadata={"description": "Player-controlled vector ship"},
        )
    )
    entities.append(
        _entity(
            "camera",
            {
                "camera": {"position": [480, 450], "viewport": [960, 540], "zoom": 1.0, "follow_entity": "player", "follow_smoothing": 7.5, "bounds": {"type": "aabb", "minimum": [0, 0], "maximum": [1600, 900]}},
            },
            tags=("camera",),
        )
    )
    entities.append(
        _entity(
            "portal_start",
            {
                "transform": {"position": [170, 450], "rotation": 0, "scale": [1.1, 1.1]},
                "vector_renderer": {"asset_id": "portal", "z_index": -2, "opacity": 0.78, "shadow_blur": 22, "shadow_color": "rgba(70,120,255,.5)"},
                "spin": {"speed": -0.25},
                "pulse": {"amount": 0.08, "speed": 2.2},
            },
            tags=("decoration",),
        )
    )

    crystal_positions = [
        (360, 180), (590, 135), (820, 210), (1100, 145), (1400, 250), (420, 430),
        (760, 410), (1040, 390), (1320, 500), (320, 735), (735, 720), (1210, 735),
    ]
    for index, position in enumerate(crystal_positions, 1):
        entities.append(
            _entity(
                f"crystal_{index:02d}",
                {
                    "transform": {"position": list(position), "rotation": index * 0.31, "scale": [0.82, 0.82]},
                    "collider": {"shape": {"type": "circle", "center": [0, 0], "radius": 22}, "filter": {"layer": PICKUP_LAYER, "mask": PLAYER_LAYER, "sensor": True}},
                    "vector_renderer": {"asset_id": "crystal", "z_index": 8, "shadow_blur": 16, "shadow_color": "rgba(255,205,80,.5)"},
                    "collectible": {"points": 1, "state_key": "score", "sound": "collect", "destroy_on_collect": True},
                    "spin": {"speed": 0.65 + (index % 3) * 0.16},
                    "pulse": {"amount": 0.10, "speed": 2.6, "phase": index * 0.7},
                },
                tags=("collectible",),
            )
        )

    obstacles = [
        (520, 300, 1.6, 0.8), (890, 105, 1.15, 0.72), (1170, 285, 1.45, 0.78),
        (675, 565, 1.55, 0.74), (1060, 610, 1.25, 0.82), (1420, 690, 1.0, 0.8),
        (220, 610, 0.9, 1.4),
    ]
    for index, (x, y, sx, sy) in enumerate(obstacles, 1):
        half_x, half_y = 58 * sx, 34 * sy
        entities.append(
            _entity(
                f"obstacle_{index:02d}",
                {
                    "transform": {"position": [x, y], "rotation": 0, "scale": [sx, sy]},
                    "body": {"body_type": "static", "velocity": [0, 0], "restitution": 0.15, "friction": 0.55},
                    "collider": {"shape": {"type": "aabb", "minimum": [-58, -34], "maximum": [58, 34]}, "filter": {"layer": WORLD_LAYER, "mask": PLAYER_LAYER | HAZARD_LAYER, "sensor": False}},
                    "vector_renderer": {"asset_id": "obstacle", "z_index": 4, "shadow_blur": 12, "shadow_color": "rgba(0,0,0,.45)"},
                },
                tags=("world", "obstacle"),
            )
        )

    hazards = [
        (505, 770, (1, -0.35), 120), (865, 325, (-0.5, 1), 108),
        (1260, 165, (-1, 0.42), 132), (1370, 610, (-0.75, -1), 116),
    ]
    for index, (x, y, direction, speed) in enumerate(hazards, 1):
        entities.append(
            _entity(
                f"hazard_{index:02d}",
                {
                    "transform": {"position": [x, y], "rotation": index * 0.4, "scale": [0.9, 0.9]},
                    "body": {"body_type": "kinematic", "velocity": [0, 0], "restitution": 1.0, "friction": 0},
                    "collider": {"shape": {"type": "circle", "center": [0, 0], "radius": 29}, "filter": {"layer": HAZARD_LAYER, "mask": PLAYER_LAYER | WORLD_LAYER, "sensor": False}},
                    "vector_renderer": {"asset_id": "hazard_orb", "z_index": 12, "shadow_blur": 18, "shadow_color": "rgba(255,40,100,.48)"},
                    "hazard": {"damage": 1, "knockback": 260, "cooldown": 0.65, "sound": "damage"},
                    "patrol": {"direction": list(direction), "speed": speed},
                    "bounds_constraint": {"bounds": {"type": "aabb", "minimum": [80, 80], "maximum": [1520, 820]}, "mode": "bounce"},
                    "spin": {"speed": (-1 if index % 2 else 1) * (0.75 + index * 0.08)},
                },
                tags=("hazard", "enemy"),
            )
        )

    scene = GameSceneSpec(
        "vector_garden",
        tuple(entities),
        (1600, 900),
        "#0a0f25",
        (),
        {"score": 0},
        {
            "player_id": "player",
            "score_to_win": len(crystal_positions),
            "pause_action": "pause",
            "restart_action": "restart",
            "collect_sound": "collect",
            "damage_sound": "damage",
            "dash_sound": "dash",
            "win_sound": "win",
            "game_over_sound": "game_over",
            "save_sound": "save",
            "music": "garden_pulse",
            "gravity": [0, 0],
            "grid": {"enabled": True, "spacing": 80, "color": "rgba(125,170,255,.055)"},
            "vignette": True,
        },
        (
            {"type": "text", "text": "WASD / arrows / stick · Space dash · P pause · K save · L load", "position": [936, 30], "align": "right", "font": "12px system-ui, sans-serif", "color": "rgba(225,235,255,.72)"},
            {"type": "text", "text": "Best {best}", "position": [936, 51], "align": "right", "font": "12px system-ui, sans-serif", "color": "rgba(175,205,255,.65)"},
        ),
    )
    project = GameProject(
        ProjectMetadata(
            "kc.elizabeth.vector-quest",
            "Elizabeth's Vector Garden",
            author,
            "1.0.0",
            description="A dependency-free vector-art arcade demonstration for the UGTS-KC 3.9 KC Elizabeth edition.",
            license="Requester-controlled project content; runtime attribution retained",
        ),
        DisplaySettings(960, 540, "#070b1b", "fit", "device", False, "landscape", True),
        _input_map(),
        vector_assets,
        audio,
        scenes=(scene,),
        start_scene="vector_garden",
        build={"single_file": True, "minify": False, "debug": False},
    )
    project.validate()
    return project


def blank_vector_game_project(title: str = "My KC Elizabeth Game", author: str = "") -> GameProject:
    project_id = "game." + "".join(character.lower() if character.isalnum() else "-" for character in title).strip("-")
    project_id = project_id[:64] or "game.kc-elizabeth"
    assets = VectorLibrary((_player_asset(), _crystal_asset(), _obstacle_asset()))
    scene = GameSceneSpec(
        "main",
        (
            _entity(
                "player",
                {
                    "transform": {"position": [480, 270], "rotation": math.pi / 2, "scale": [1, 1]},
                    "body": {"body_type": "dynamic", "mass": 1, "damping": 1.4, "gravity_scale": 0, "fixed_rotation": True},
                    "collider": {"shape": {"type": "circle", "radius": 19}, "filter": {"layer": PLAYER_LAYER, "mask": WORLD_LAYER | PICKUP_LAYER, "sensor": False}},
                    "vector_renderer": {"asset_id": "player_ship", "z_index": 10},
                    "player_controller": {"speed": 230, "dash_action": "dash"},
                    "bounds_constraint": {"bounds": {"type": "aabb", "minimum": [35, 35], "maximum": [925, 505]}, "mode": "clamp"},
                },
                tags=("player",),
            ),
            _entity(
                "first_collectible",
                {
                    "transform": {"position": [720, 270], "rotation": 0, "scale": [0.85, 0.85]},
                    "collider": {"shape": {"type": "circle", "radius": 22}, "filter": {"layer": PICKUP_LAYER, "mask": PLAYER_LAYER, "sensor": True}},
                    "vector_renderer": {"asset_id": "crystal", "z_index": 5},
                    "collectible": {"points": 1, "sound": "collect"},
                    "spin": {"speed": 0.8},
                    "pulse": {"amount": 0.1, "speed": 3},
                },
                tags=("collectible",),
            ),
        ),
        (960, 540),
        "#0a0f25",
        initial_state={"score": 0},
        rules={"player_id": "player", "score_to_win": 1, "collect_sound": "collect", "win_sound": "win", "grid": {"enabled": True, "spacing": 64}},
        ui=({"type": "text", "text": "Edit project.json, then rebuild with: python -m ugts_kc3 build-web project.json dist", "position": [930, 30], "align": "right", "color": "rgba(225,235,255,.72)"},),
    )
    project = GameProject(
        ProjectMetadata(project_id, title, author, "0.1.0", description="KC Elizabeth starter game"),
        DisplaySettings(),
        _input_map(),
        assets,
        _audio_bank(),
        scenes=(scene,),
        start_scene="main",
    )
    project.validate()
    return project


def write_template(project: GameProject, directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return project.write(directory / "project.json")
