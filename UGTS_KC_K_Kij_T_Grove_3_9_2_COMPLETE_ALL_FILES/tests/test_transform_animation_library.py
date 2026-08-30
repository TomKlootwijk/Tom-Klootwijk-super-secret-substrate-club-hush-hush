from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.animation3d import (  # noqa: E402
    ANIMATION_LIBRARY_METADATA_KEY,
    ANIMATION_METADATA_KEY,
    DEFAULT_ANIMATION_CLIP_ID,
    MAX_ANIMATION_CLIPS_PER_NODE,
    MAX_ANIMATION_CLIPS_TOTAL,
    TransformAnimation3D,
    TransformAnimationError,
    TransformAnimationLibrary3D,
    TransformClip3D,
    TransformKey3D,
    animation_clip_hash,
    collect_transform_animation_spec,
    default_transform_animation_library,
    metadata_with_transform_animation,
    metadata_with_transform_animation_library,
    transform_animation_from_metadata,
    transform_animation_library_from_metadata,
)
from ugts_kc3.animationpack import (  # noqa: E402
    ANIMATION_PACK_MAGIC,
    ANIMATION_PACK_VERSION,
    LEGACY_ANIMATION_PACK_VERSION,
    AnimationPackError,
    compile_animation_pack_bytes,
    inspect_animation_pack,
)
from ugts_kc3.mobile3d import InputFrame3D  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402


def _clip(offset: float, *, duration: float = 1.0, loop_mode: str = "once"):
    return TransformAnimation3D(
        duration,
        (
            TransformKey3D(0.0),
            TransformKey3D(
                duration,
                (offset, 0.0, 0.0),
                (1.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 1.0),
                "linear",
            ),
        ),
        loop_mode,
    )


def _library(*, autoplay: str | None = "move") -> TransformAnimationLibrary3D:
    return TransformAnimationLibrary3D(
        (
            TransformClip3D("move", "Move", _clip(2.0)),
            TransformClip3D("idle", "Idle", _clip(0.0, loop_mode="loop")),
        ),
        autoplay,
    )


def _with_library(project, library: TransformAnimationLibrary3D):
    floor = project.nodes[0]
    metadata = metadata_with_transform_animation_library(floor.metadata, library)
    project.nodes = (replace(floor, metadata=metadata), *project.nodes[1:])
    return project.nodes[0]


class TransformAnimationLibraryTests(unittest.TestCase):
    def test_default_roundtrip_hash_and_legacy_normalization(self) -> None:
        library = default_transform_animation_library()
        self.assertEqual(library.clips[0].id, DEFAULT_ANIMATION_CLIP_ID)
        self.assertEqual(library.clips[0].label, "Main")
        self.assertEqual(library.autoplay, "main")
        self.assertEqual(animation_clip_hash("main"), 0x1F5962A2CE9803C8)
        self.assertEqual(
            TransformAnimationLibrary3D.from_dict(
                json.loads(json.dumps(library.to_dict()))
            ),
            library,
        )

        legacy = _clip(3.0)
        metadata = metadata_with_transform_animation({}, legacy)
        normalized = transform_animation_library_from_metadata(metadata)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized.clips, (TransformClip3D("main", "Main", legacy),))
        self.assertEqual(normalized.autoplay, "main")
        self.assertEqual(transform_animation_from_metadata(metadata), legacy)

    def test_metadata_forms_are_exclusive_and_compatibility_view_is_stable(
        self,
    ) -> None:
        library = _library(autoplay=None)
        metadata = metadata_with_transform_animation_library(
            {ANIMATION_METADATA_KEY: _clip(1.0).to_dict(), "kept": True}, library
        )
        self.assertNotIn(ANIMATION_METADATA_KEY, metadata)
        self.assertIn(ANIMATION_LIBRARY_METADATA_KEY, metadata)
        self.assertEqual(
            transform_animation_from_metadata(metadata), library.clips[0].animation
        )

        legacy = metadata_with_transform_animation(metadata, _clip(4.0))
        self.assertNotIn(ANIMATION_LIBRARY_METADATA_KEY, legacy)
        self.assertIn(ANIMATION_METADATA_KEY, legacy)
        self.assertTrue(legacy["kept"])

        mixed = {
            ANIMATION_METADATA_KEY: _clip(1.0).to_dict(),
            ANIMATION_LIBRARY_METADATA_KEY: library.to_dict(),
        }
        for reader in (
            transform_animation_from_metadata,
            transform_animation_library_from_metadata,
        ):
            with self.subTest(reader=reader.__name__):
                with self.assertRaisesRegex(TransformAnimationError, "cannot use"):
                    reader(mixed)

    def test_ids_autoplay_and_bounds_are_rejected(self) -> None:
        for bad_id in ("Main", "1main", "with space", "a" * 33, "møve"):
            with self.subTest(bad_id=bad_id):
                with self.assertRaisesRegex(TransformAnimationError, "clip id"):
                    TransformClip3D(bad_id, "Bad", _clip(1.0))

        with self.assertRaisesRegex(TransformAnimationError, "unique"):
            TransformAnimationLibrary3D(
                (
                    TransformClip3D("same", "One", _clip(1.0)),
                    TransformClip3D("same", "Two", _clip(2.0)),
                )
            )
        with self.assertRaisesRegex(TransformAnimationError, "autoplay clip"):
            TransformAnimationLibrary3D(
                (TransformClip3D("idle", "Idle", _clip(0.0)),), "missing"
            )
        with self.assertRaisesRegex(TransformAnimationError, "1 to 16"):
            TransformAnimationLibrary3D(
                tuple(
                    TransformClip3D(f"clip{index}", str(index), _clip(float(index)))
                    for index in range(MAX_ANIMATION_CLIPS_PER_NODE + 1)
                )
            )

        project = blank_mobile3d_project()
        prototype = project.nodes[0]
        clips = tuple(
            TransformClip3D(f"clip{index}", str(index), _clip(float(index)))
            for index in range(MAX_ANIMATION_CLIPS_PER_NODE)
        )
        library = TransformAnimationLibrary3D(clips)
        node_count = MAX_ANIMATION_CLIPS_TOTAL // MAX_ANIMATION_CLIPS_PER_NODE + 1
        project.nodes = tuple(
            replace(
                prototype,
                id=f"animated_{index}",
                metadata=metadata_with_transform_animation_library({}, library),
            )
            for index in range(node_count)
        )
        with self.assertRaisesRegex(TransformAnimationError, "at most 256"):
            collect_transform_animation_spec(project)

    def test_collection_is_hash_canonical_and_preserves_legacy_shape(self) -> None:
        legacy_project = blank_mobile3d_project()
        legacy_floor = legacy_project.nodes[0]
        legacy_project.nodes = (
            replace(
                legacy_floor,
                metadata=metadata_with_transform_animation({}, _clip(1.0)),
            ),
            *legacy_project.nodes[1:],
        )
        legacy_spec = collect_transform_animation_spec(legacy_project)
        self.assertTrue(legacy_spec.legacy)
        self.assertEqual(legacy_spec.clip_count, 1)
        self.assertEqual(legacy_spec.bindings[0].clip_id, "main")
        self.assertTrue(legacy_spec.bindings[0].autoplay)
        self.assertTrue(legacy_spec.bindings[0].legacy)

        project = blank_mobile3d_project()
        _with_library(project, _library(autoplay="idle"))
        spec = collect_transform_animation_spec(project)
        self.assertFalse(spec.legacy)
        self.assertEqual(spec.clip_count, 2)
        self.assertEqual(spec.animated_node_count, 1)
        self.assertEqual(
            [binding.clip_hash for binding in spec.bindings],
            sorted(binding.clip_hash for binding in spec.bindings),
        )
        by_id = {binding.clip_id: binding for binding in spec.bindings}
        self.assertTrue(by_id["idle"].autoplay)
        self.assertFalse(by_id["move"].autoplay)
        self.assertTrue(all(not binding.legacy for binding in spec.bindings))

    def test_runtime_play_stop_once_and_inactive_clock(self) -> None:
        project = blank_mobile3d_project()
        _with_library(project, _library(autoplay=None))
        world = project.instantiate_world()
        entity = world.require(project.nodes[0].id)
        component = entity.extra_components[ANIMATION_METADATA_KEY]
        base = tuple(entity.position)
        self.assertIsNone(component.active_clip)
        self.assertFalse(component.playing)

        component.play("move")
        entity.active = False
        for _ in range(120):
            world.step(InputFrame3D())
        self.assertEqual(component.elapsed, 1.0)
        self.assertFalse(component.playing)
        self.assertEqual(entity.position, base)

        entity.active = True
        world.step(InputFrame3D())
        self.assertEqual(entity.position[0], base[0] + 2.0)
        component.stop(reset=False)
        paused_elapsed = component.elapsed
        world.step(InputFrame3D())
        self.assertEqual(component.elapsed, paused_elapsed)
        self.assertEqual(entity.position[0], base[0] + 2.0)

        component.stop()
        self.assertIsNone(component.active_clip)
        self.assertEqual(component.elapsed, 0.0)
        component.reset_pose(entity)
        self.assertEqual(entity.position, base)
        component.play("idle", restart=False)
        self.assertEqual(component.active_clip, "idle")
        self.assertTrue(component.playing)

    def test_kcan_v1_golden_bytes_and_v2_records(self) -> None:
        legacy_project = blank_mobile3d_project()
        floor = legacy_project.nodes[0]
        golden_clip = TransformAnimation3D(
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
        legacy_project.nodes = (
            replace(
                floor,
                metadata=metadata_with_transform_animation({}, golden_clip),
            ),
            *legacy_project.nodes[1:],
        )
        legacy = compile_animation_pack_bytes(legacy_project)
        self.assertEqual(len(legacy), 88)
        self.assertEqual(
            hashlib.sha256(legacy).hexdigest(),
            "d338488324e634f75e3b1602960d4ff2ec36cf951fb21c4559bf518008edcb93",
        )
        legacy_info = inspect_animation_pack(
            legacy, node_count=len(legacy_project.nodes)
        )
        self.assertEqual(legacy_info["format_version"], LEGACY_ANIMATION_PACK_VERSION)
        self.assertNotIn("clip_hash", legacy_info["bindings"][0])

        project = blank_mobile3d_project()
        _with_library(project, _library(autoplay="move"))
        packed = compile_animation_pack_bytes(project)
        self.assertEqual(packed[:8], ANIMATION_PACK_MAGIC)
        self.assertEqual(
            struct.unpack_from("<I", packed, 12)[0], ANIMATION_PACK_VERSION
        )
        self.assertEqual(len(packed), 168)
        info = inspect_animation_pack(packed, node_count=len(project.nodes))
        self.assertEqual(info["format_version"], 2)
        self.assertEqual(info["binding_count"], 2)
        self.assertEqual(info["packed_key_count"], 4)
        self.assertEqual(
            [(item["node_index"], item["clip_hash"]) for item in info["bindings"]],
            sorted(
                (item["node_index"], item["clip_hash"]) for item in info["bindings"]
            ),
        )
        self.assertEqual(sum(item["autoplay"] for item in info["bindings"]), 1)
        self.assertEqual(
            compile_animation_pack_bytes(
                type(project).from_dict(json.loads(json.dumps(project.to_dict())))
            ),
            packed,
        )

        corrupt = bytearray(packed)
        corrupt[47] |= 0x02
        with self.assertRaisesRegex(AnimationPackError, "flags"):
            inspect_animation_pack(bytes(corrupt), node_count=len(project.nodes))

        mixed = blank_mobile3d_project()
        library_floor = _with_library(mixed, _library(autoplay="move"))
        mixed.nodes = (
            library_floor,
            *mixed.nodes[1:],
            replace(
                library_floor,
                id="legacy_copy",
                metadata=metadata_with_transform_animation({}, _clip(5.0)),
            ),
        )
        mixed_info = inspect_animation_pack(
            compile_animation_pack_bytes(mixed), node_count=len(mixed.nodes)
        )
        self.assertEqual(mixed_info["format_version"], ANIMATION_PACK_VERSION)
        self.assertEqual(mixed_info["binding_count"], 3)
        self.assertEqual(
            mixed_info["bindings"][-1]["clip_hash"], animation_clip_hash("main")
        )
        self.assertTrue(mixed_info["bindings"][-1]["autoplay"])


if __name__ == "__main__":
    unittest.main()
