from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project  # noqa: E402
from ugts_kc3.animation3d import (  # noqa: E402
    ANIMATION_METADATA_KEY,
    TransformAnimation3D,
    TransformKey3D,
)
from ugts_kc3.animationpack import (  # noqa: E402
    ANIMATION_PACK_ASSET,
    ANIMATION_PACK_MAGIC,
    AnimationPackError,
    compile_animation_pack_bytes,
    inspect_animation_pack,
)
from ugts_kc3.mobile3d import Mobile3DProject, Transform3DRecord  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402


def _animate(project, *, copies: int = 0):
    animation = TransformAnimation3D(
        2.0,
        (
            TransformKey3D(0.0),
            TransformKey3D(
                2.0,
                (2.0, 0.0, -1.0),
                (0.9238795325, 0.0, 0.3826834324, 0.0),
                (1.5, 0.75, 2.0),
                "smoothstep",
            ),
        ),
        "pingpong",
    )
    floor = project.nodes[0]
    animated = replace(
        floor,
        metadata={**floor.metadata, ANIMATION_METADATA_KEY: animation.to_dict()},
    )
    nodes = [animated, *project.nodes[1:]]
    for index in range(copies):
        nodes.append(
            replace(
                animated,
                id=f"animated_copy_{index + 1}",
                transform=Transform3DRecord((10.0 + index * 4.0, 0.0, 0.0)),
                metadata=json.loads(json.dumps(animated.metadata)),
            )
        )
    project.nodes = tuple(nodes)
    return project


class AndroidTransformAnimationTests(unittest.TestCase):
    def test_unanimated_project_has_no_asset_or_runtime_records(self) -> None:
        project = blank_mobile3d_project()
        self.assertEqual(compile_animation_pack_bytes(project), b"")
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNone(built.animation_pack)
            self.assertFalse(
                (built.output_dir / "app/src/main/assets" / ANIMATION_PACK_ASSET).exists()
            )
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertIsNone(report["transform_animation_runtime"])

    def test_sparse_pack_is_deterministic_contiguous_and_small(self) -> None:
        project = _animate(blank_mobile3d_project(), copies=1)
        packed = compile_animation_pack_bytes(project)
        self.assertEqual(packed[:8], ANIMATION_PACK_MAGIC)
        self.assertEqual(
            compile_animation_pack_bytes(Mobile3DProject.from_dict(project.to_dict())),
            packed,
        )
        info = inspect_animation_pack(packed, node_count=len(project.nodes))
        self.assertEqual(info["binding_count"], 2)
        self.assertEqual(info["authored_key_count"], 4)
        self.assertEqual(info["packed_key_count"], 4)
        self.assertEqual(info["bindings"][0]["first_key"], 0)
        self.assertEqual(info["bindings"][1]["first_key"], 2)
        self.assertLess(info["byte_length"], 160)

    def test_android_source_export_contains_optional_runtime_and_evidence(self) -> None:
        project = _animate(blank_mobile3d_project())
        packed = compile_animation_pack_bytes(project)
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNotNone(built.animation_pack)
            self.assertEqual(built.animation_pack.read_bytes(), packed)
            report = json.loads(built.build_report.read_text("utf-8"))
            runtime = report["transform_animation_runtime"]
            self.assertEqual(runtime["binding_count"], 1)
            self.assertEqual(runtime["packed_key_count"], 2)
            self.assertFalse(report["authoring_assets_packaged"])
            self.assertFalse(
                (built.output_dir / "app/src/main/assets/project.json").exists()
            )
            cpp = built.output_dir / "app/src/main/cpp"
            engine = (cpp / "engine.cpp").read_text("utf-8")
            self.assertLess(
                engine.index('readAsset("packed_kinematics.kcpk")'),
                engine.index('readAsset("transform_animations.kcan")'),
            )
            self.assertLess(
                engine.index("transformAnimations_.tick(dt,nodes_)"),
                engine.index("graphVm_.tick(dt,fixedTick_"),
            )
            self.assertIn("transform_animation.cpp", (cpp / "CMakeLists.txt").read_text("utf-8"))

    def test_reader_rejects_corruption_trailing_bytes_and_bad_references(self) -> None:
        project = _animate(blank_mobile3d_project())
        packed = compile_animation_pack_bytes(project)
        self.assertEqual(len(packed), 88)
        with self.assertRaisesRegex(AnimationPackError, "trailing bytes"):
            inspect_animation_pack(packed + b"x", node_count=len(project.nodes))

        corrupt = bytearray(packed)
        struct.pack_into("<I", corrupt, 32, 1)
        with self.assertRaisesRegex(AnimationPackError, "range"):
            inspect_animation_pack(bytes(corrupt), node_count=len(project.nodes))

        corrupt = bytearray(packed)
        corrupt[66] = 9
        with self.assertRaisesRegex(AnimationPackError, "easing"):
            inspect_animation_pack(bytes(corrupt), node_count=len(project.nodes))

        corrupt = bytearray(packed)
        struct.pack_into("<H", corrupt, 82, 0xBC00)
        with self.assertRaisesRegex(AnimationPackError, "size"):
            inspect_animation_pack(bytes(corrupt), node_count=len(project.nodes))

        corrupt = bytearray(packed)
        struct.pack_into("<H", corrupt, 68, 0x7000)
        with self.assertRaisesRegex(AnimationPackError, "position"):
            inspect_animation_pack(bytes(corrupt), node_count=len(project.nodes))

        corrupt = bytearray(packed)
        struct.pack_into("<H", corrupt, 82, 0x5800)
        with self.assertRaisesRegex(AnimationPackError, "size"):
            inspect_animation_pack(bytes(corrupt), node_count=len(project.nodes))

        with self.assertRaisesRegex(AnimationPackError, "scene node"):
            inspect_animation_pack(packed, node_count=0)


if __name__ == "__main__":
    unittest.main()
