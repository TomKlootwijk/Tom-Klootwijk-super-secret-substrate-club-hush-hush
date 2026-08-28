"""Practical mobile-3D templates for UGTS-KC 3.9.1 Signature Edition."""
from __future__ import annotations

import math

from .math3d import quat_from_axis_angle
from .mobile3d import (
    AndroidTargetProfile, Camera3DRecord, Collider3DRecord,
    DirectionalLight3DRecord, Material3DRecord, Mobile3DProject,
    Node3DRecord, QualityTier3D, Transform3DRecord, World3DSettings,
    cube_mesh3d, plane_mesh3d, pyramid_mesh3d, uv_sphere_mesh3d,
)


def signature_quality_tiers() -> tuple[QualityTier3D, ...]:
    """Descending order used by the adaptive controller."""
    return (
        QualityTier3D("signature_ultra", 120, 1.0, 1024, 4, True, 2),
        QualityTier3D("high", 90, 0.92, 720, 2, True, 1),
        QualityTier3D("balanced", 60, 0.82, 480, 0, True, 0),
        QualityTier3D("safe", 60, 0.68, 280, 0, False, 0),
        QualityTier3D("thermal", 45, 0.55, 160, 0, False, 0),
    )


def signature_android_targets() -> tuple[AndroidTargetProfile, ...]:
    return (
        AndroidTargetProfile(
            "poco_x7_pro_12gb", "POCO X7 Pro 12 GB Signature Target",
            preferred_abis=("arm64-v8a",), target_refresh_hz=120,
            memory_floor_mb=10240, device_hints=("POCO X7 Pro",),
            gpu_hints=("Mali-G720",), default_quality="signature_ultra",
        ),
        AndroidTargetProfile(
            "android_high", "High-end Android",
            preferred_abis=("arm64-v8a",), target_refresh_hz=90,
            memory_floor_mb=7168, default_quality="high",
        ),
        AndroidTargetProfile(
            "android_balanced", "Mainstream Android",
            preferred_abis=("arm64-v8a", "armeabi-v7a"),
            target_refresh_hz=60, memory_floor_mb=3584,
            default_quality="balanced",
        ),
        AndroidTargetProfile(
            "android_compat", "Compatibility Android",
            preferred_abis=("arm64-v8a", "armeabi-v7a", "x86_64"),
            target_refresh_hz=60, memory_floor_mb=2048,
            default_quality="safe",
        ),
    )


def blank_mobile3d_project(
    title: str = "My UGTS-KC Mobile 3D Game", author: str = ""
) -> Mobile3DProject:
    meshes = {
        "cube": cube_mesh3d("cube"),
        "floor": plane_mesh3d("floor", 24, 24),
        "sphere": uv_sphere_mesh3d("sphere", 0.5, 16, 10),
    }
    materials = {
        "floor": Material3DRecord(
            "floor", (0.06, 0.1, 0.16, 1), 0.05, 0.8
        ),
        "player": Material3DRecord(
            "player", (0.2, 0.78, 1, 1), 0.15, 0.28,
            (0.02, 0.16, 0.22),
        ),
        "accent": Material3DRecord(
            "accent", (0.92, 0.32, 0.78, 1), 0.25, 0.34,
            (0.08, 0.01, 0.06),
        ),
    }
    nodes = (
        Node3DRecord("floor", "floor", "floor"),
        Node3DRecord(
            "player", "sphere", "player",
            Transform3DRecord((0, 0.55, 3)),
            collider=Collider3DRecord("sphere", 0.5),
            dynamic=True, restitution=0.1, tags=("player",),
        ),
        Node3DRecord(
            "goal", "cube", "accent",
            Transform3DRecord((0, 1.25, -5), scale=(1.2, 2.5, 0.4)),
            angular_velocity=(0, 0.5, 0),
            collider=Collider3DRecord(
                "box", half_extents=(0.6, 1.25, 0.2), sensor=True
            ),
            tags=("goal",),
        ),
    )
    return Mobile3DProject(
        "my_mobile_3d_game", title, author, meshes, materials, nodes,
        quality_tiers=signature_quality_tiers(),
        target_profiles=signature_android_targets(),
        start_quality="balanced",
        metadata={"template": "blank-mobile-3d", "signature_edition": True},
    )


def tom_signature_arena_project(
    author: str = "Tom Klootwijk"
) -> Mobile3DProject:
    meshes = {
        "cube": cube_mesh3d("cube"),
        "floor": plane_mesh3d("floor", 42, 42),
        "pyramid": pyramid_mesh3d("pyramid", 1.2, 1.8),
        "sphere": uv_sphere_mesh3d("sphere", 0.5, 20, 12),
    }
    materials = {
        "obsidian": Material3DRecord(
            "obsidian", (0.035, 0.055, 0.09, 1), 0.55, 0.22
        ),
        "grid": Material3DRecord(
            "grid", (0.045, 0.085, 0.13, 1), 0.1, 0.72,
            (0.003, 0.012, 0.02),
        ),
        "signature_cyan": Material3DRecord(
            "signature_cyan", (0.16, 0.82, 1, 1), 0.24, 0.25,
            (0.025, 0.18, 0.26),
        ),
        "signature_magenta": Material3DRecord(
            "signature_magenta", (0.95, 0.24, 0.74, 1), 0.25, 0.3,
            (0.16, 0.01, 0.09),
        ),
        "signature_gold": Material3DRecord(
            "signature_gold", (1, 0.72, 0.2, 1), 0.68, 0.24,
            (0.12, 0.045, 0.004),
        ),
        "hazard": Material3DRecord(
            "hazard", (1, 0.17, 0.11, 1), 0.1, 0.32,
            (0.22, 0.012, 0.004),
        ),
        "goal": Material3DRecord(
            "goal", (0.4, 1, 0.62, 0.86), 0.15, 0.22,
            (0.08, 0.28, 0.1), True,
        ),
        "violet": Material3DRecord(
            "violet", (0.46, 0.3, 1, 1), 0.4, 0.24,
            (0.035, 0.018, 0.18),
        ),
    }
    nodes: list[Node3DRecord] = [
        Node3DRecord("arena_floor", "floor", "grid"),
        Node3DRecord(
            "player", "sphere", "signature_cyan",
            Transform3DRecord((0, 0.6, 8)),
            collider=Collider3DRecord("sphere", 0.54),
            dynamic=True, mass=1, restitution=0.08,
            tags=("player",), metadata={"native_controlled": True},
        ),
        Node3DRecord(
            "signature_monolith", "cube", "obsidian",
            Transform3DRecord(
                (0, 3.8, 0),
                quat_from_axis_angle((0, 1, 0), math.radians(18)),
                (2.2, 7.6, 1.1),
            ),
            angular_velocity=(0, 0.16, 0),
            collider=Collider3DRecord(
                "box", half_extents=(1.1, 3.8, 0.55)
            ),
            tags=("decorative",),
        ),
    ]
    for index, (x, z) in enumerate(
        ((-9, -9), (9, -9), (-9, 9), (9, 9))
    ):
        nodes.append(
            Node3DRecord(
                f"tower_{index}", "cube", "obsidian",
                Transform3DRecord((x, 2.5, z), scale=(1.4, 5, 1.4)),
                angular_velocity=(
                    0, 0.08 * (-1 if index % 2 else 1), 0
                ),
                collider=Collider3DRecord(
                    "box", half_extents=(0.7, 2.5, 0.7)
                ),
                tags=("decorative",),
            )
        )
    helix_materials = (
        "signature_cyan", "signature_magenta", "signature_gold", "violet"
    )
    for index in range(40):
        angle = index * math.tau / 20
        radius = 6.4 + 0.8 * math.sin(index * 0.7)
        y = 1 + (index % 10) * 0.42
        x, z = math.cos(angle) * radius, math.sin(angle) * radius
        size = 0.42 + 0.08 * (index % 3)
        nodes.append(
            Node3DRecord(
                f"helix_{index:02d}", "cube",
                helix_materials[index % len(helix_materials)],
                Transform3DRecord(
                    (x, y, z),
                    quat_from_axis_angle((1, 1, 0.4), angle * 0.5),
                    (size, size, size),
                ),
                angular_velocity=(
                    0.18 + index * 0.002,
                    0.34 + index * 0.003,
                    0.12,
                ),
                tags=("decorative",),
            )
        )
    for index in range(12):
        x = math.sin(index * 0.8) * 3.2
        z = 6.5 - index * 1.05
        y = 0.75 + 0.22 * math.sin(index)
        nodes.append(
            Node3DRecord(
                f"crystal_{index:02d}", "sphere", "signature_gold",
                Transform3DRecord((x, y, z), scale=(0.38, 0.58, 0.38)),
                angular_velocity=(0, 1.2 + index * 0.03, 0.25),
                collider=Collider3DRecord("sphere", 0.46, sensor=True),
                tags=("collectible",),
            )
        )
    for index, x in enumerate((-6.5, -3.2, 3.2, 6.5, -1.8, 1.8)):
        z = -4.6 if index < 4 else 3.2
        nodes.append(
            Node3DRecord(
                f"hazard_{index}", "pyramid", "hazard",
                Transform3DRecord((x, 0, z), scale=(0.9, 1, 0.9)),
                angular_velocity=(
                    0, (-1 if index % 2 else 1) * 0.65, 0
                ),
                collider=Collider3DRecord("sphere", 0.75, sensor=True),
                tags=("hazard",),
            )
        )
    nodes.append(
        Node3DRecord(
            "goal_portal", "sphere", "goal",
            Transform3DRecord((0, 1.6, -9.5), scale=(1.6, 3, 0.55)),
            angular_velocity=(0, 0.75, 0),
            collider=Collider3DRecord("sphere", 1.35, sensor=True),
            tags=("goal",),
        )
    )
    return Mobile3DProject(
        "tom_klootwijk_signature_arena_3d",
        "Tom Klootwijk Signature Arena 3D", author,
        meshes, materials, tuple(nodes),
        Camera3DRecord(
            (11.5, 7.2, 14.5), (0, 1.7, 0),
            vertical_fov_degrees=58, near=0.05, far=180,
        ),
        DirectionalLight3DRecord(
            (-0.42, -1, -0.28), (1, 0.95, 0.88), 1.38, 0.2
        ),
        signature_quality_tiers(), signature_android_targets(),
        World3DSettings(
            1 / 120, (0, -12, 0), 0,
            (-18, -6, -18), (18, 24, 18), 7.2, 8.6,
        ),
        "signature_ultra", (0.012, 0.022, 0.046, 1),
        metadata={
            "signature_edition": True,
            "primary_device_target": "POCO X7 Pro 12 GB",
            "render_backend": "OpenGL ES 3.0 native NDK",
            "vulkan_backend": "reserved interface / not implemented in 3.9.1",
            "controls": (
                "left touch stick or keyboard/gamepad moves; "
                "right drag orbits camera; two-finger pinch zooms"
            ),
            "4d_status": "explicit post-3.9.1 TODO",
        },
    )
