from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from ugts_kc3.androidexport import compile_scene_pack_bytes, inspect_scene_pack
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.objimport import (
    DEFAULT_OBJ_LIMITS,
    ObjImportError,
    load_wavefront_obj,
    parse_wavefront_obj,
)
from ugts_kc3.templates3d import first_steps_mobile3d_project


TRIANGLE_POSITIONS = """\
v 0 0 0
v 1 0 0
v 0 1 0
"""


class WavefrontObjImportTests(unittest.TestCase):
    def test_all_face_corner_forms_and_negative_indices_are_supported(self) -> None:
        prefix = TRIANGLE_POSITIONS + """\
vt 0 0
vt 1 0
vt 0 1
vn 0 0 2
"""
        cases = {
            "positions": "f 1 2 3\n",
            "textures": "f 1/1 2/2 3/3\n",
            "normals": "f 1//1 2//1 3//1\n",
            "both": "f 1/1/1 2/2/1 3/3/1\n",
            "negative": "f -3/-3/-1 -2/-2/-1 -1/-1/-1\n",
        }
        for label, face in cases.items():
            with self.subTest(label=label):
                mesh = parse_wavefront_obj(prefix + face, label)
                self.assertEqual(mesh.triangles, ((0, 1, 2),))
                self.assertEqual(len(mesh.vertices), 3)
                if label in {"normals", "both", "negative"}:
                    self.assertEqual(mesh.normals, ((0.0, 0.0, 1.0),) * 3)
                else:
                    self.assertEqual(mesh.normals, ())

    def test_ngon_uses_deterministic_fan_and_homogeneous_vertices(self) -> None:
        mesh = parse_wavefront_obj(
            """\
v 0 0 0 2
v 2 0 0 2
v 2 2 0 2
v 0 2 0 2
f 1 2 3 4
""",
            "quad",
        )
        self.assertEqual(
            mesh.vertices,
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
             (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
        )
        self.assertEqual(mesh.triangles, ((0, 1, 2), (0, 2, 3)))
        self.assertEqual(mesh.metadata["source_faces"], 1)

    def test_bad_input_has_bounded_plain_language_errors(self) -> None:
        cases = {
            "empty": ("# nothing here\n", "vertex records"),
            "no faces": (TRIANGLE_POSITIONS, "face records"),
            "nonfinite": ("v nan 0 0\n", "must be finite"),
            "bad vertex": ("v 0 1\n", "vertex needs three"),
            "zero weight": ("v 0 0 0 0\n", "weight cannot be zero"),
            "short face": (TRIANGLE_POSITIONS + "f 1 2\n", "at least three"),
            "zero index": (TRIANGLE_POSITIONS + "f 0 2 3\n", "index 0 is invalid"),
            "high index": (TRIANGLE_POSITIONS + "f 1 2 4\n", "out of range"),
            "negative index": (TRIANGLE_POSITIONS + "f -4 -2 -1\n", "out of range"),
            "empty texture": (TRIANGLE_POSITIONS + "f 1/ 2/ 3/\n", "empty texture"),
            "empty normal": (TRIANGLE_POSITIONS + "f 1// 2// 3//\n", "empty normal"),
            "too many slashes": (TRIANGLE_POSITIONS + "f 1/1/1/1 2 3\n", "malformed"),
            "missing texture": (TRIANGLE_POSITIONS + "f 1/1 2/1 3/1\n", "out of range"),
            "repeated corner": (TRIANGLE_POSITIONS + "f 1 2 1\n", "repeated vertices"),
            "zero normal": (TRIANGLE_POSITIONS + "vn 0 0 0\nf 1//1 2//1 3//1\n", "zero vector"),
        }
        for label, (source, message) in cases.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(ObjImportError, message):
                    parse_wavefront_obj(source, "bad")

    def test_byte_line_vertex_corner_and_triangle_limits_are_enforced(self) -> None:
        cases = (
            (
                "v 0 0 0\n",
                replace(DEFAULT_OBJ_LIMITS, max_bytes=4),
                "byte import limit",
            ),
            (
                TRIANGLE_POSITIONS + "f 1 2 3\n",
                replace(DEFAULT_OBJ_LIMITS, max_lines=3),
                "line import limit",
            ),
            (
                TRIANGLE_POSITIONS + "f 1 2 3\n",
                replace(DEFAULT_OBJ_LIMITS, max_vertices=2),
                "vertex import limit",
            ),
            (
                TRIANGLE_POSITIONS + "f 1 2 3\n",
                replace(DEFAULT_OBJ_LIMITS, max_face_corners=2),
                "face-corner import limit",
            ),
            (
                "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n",
                replace(DEFAULT_OBJ_LIMITS, max_triangles=1),
                "triangle import limit",
            ),
        )
        for source, limits, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ObjImportError, message):
                    parse_wavefront_obj(source, "limited", limits=limits)

    def test_file_load_project_roundtrip_and_native_pack_keep_imported_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "Tiny Ship.obj"
            source.write_text(TRIANGLE_POSITIONS + "f 1 2 3\n", encoding="utf-8")
            mesh = load_wavefront_obj(source, "tiny_ship")
            project = first_steps_mobile3d_project()
            project.meshes[mesh.id] = mesh
            project.validate()
            path = project.write(folder / "project.json")
            loaded = Mobile3DProject.load(path)

        self.assertEqual(loaded.meshes["tiny_ship"].vertices, mesh.vertices)
        self.assertEqual(loaded.meshes["tiny_ship"].triangles, mesh.triangles)
        packed = inspect_scene_pack(compile_scene_pack_bytes(loaded))
        packed_mesh = next(value for value in packed["meshes"] if value["id"] == "tiny_ship")
        self.assertEqual(packed_mesh["vertex_count"], 3)
        self.assertEqual(packed_mesh["index_count"], 3)


if __name__ == "__main__":
    unittest.main()
